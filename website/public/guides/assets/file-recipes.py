#!/usr/bin/env python3
"""Small local recipes: preview invoice names or reconcile CSV exports.

Python 3.11+. Invoice extraction additionally needs pypdf. All outputs go to a
new directory. A completed receipt is written last; interrupted folders must be
inspected and a different output directory selected, never blindly reused.
"""
import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import sys


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_files(folder, suffix):
    folder = Path(folder)
    files = sorted(folder.glob('*' + suffix))
    if not files:
        raise ValueError('No ' + suffix + ' files found')
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError('Input entries must be regular files, not symbolic links')
    return files


def write_json(path, data):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def safe_name(value):
    if not isinstance(value, str) or not value or value in ('.', '..'):
        raise ValueError('Invalid filename')
    if Path(value).name != value or any(c in value for c in '/\\\x00'):
        raise ValueError('Filename must not contain a path')
    return value


def invoice_plan(folder, patterns):
    from pypdf import PdfReader
    fields = ('vendor', 'date', 'invoice')
    if set(patterns) != set(fields):
        raise ValueError('Patterns must define vendor, date and invoice')
    compiled = {k: re.compile(patterns[k], re.MULTILINE) for k in fields}
    if any(p.groups != 1 for p in compiled.values()):
        raise ValueError('Each pattern needs exactly one capture group')
    rows, names = [], {}
    for path in regular_files(folder, '.pdf'):
        raw = path.read_bytes()
        row = {'source': path.name, 'sha256': digest(raw)}
        try:
            reader = PdfReader(io.BytesIO(raw))
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            values = {}
            for key, pattern in compiled.items():
                matches = set(v.strip() for v in pattern.findall(text))
                if len(matches) != 1 or not next(iter(matches)):
                    raise ValueError('Missing or ambiguous ' + key)
                values[key] = next(iter(matches))
            date.fromisoformat(values['date'])
            parts = [re.sub(r'[^A-Za-z0-9_-]+', '-', values[k]).strip('-')
                     for k in fields]
            if not all(parts):
                raise ValueError('Unusable filename fields')
            target = '-'.join(parts) + '.pdf'
            if len(target) > 180:
                raise ValueError('Proposed filename too long')
            row.update(fields=values, target=target, status='ready')
            names.setdefault(target.casefold(), []).append(row)
        except Exception as error:
            row.update(status='review', reason=str(error))
        rows.append(row)
    for group in names.values():
        if len(group) > 1:
            for row in group:
                row.update(status='review', reason='Proposed filename collision')
    return {'version': 1, 'recipe': 'invoice-copies', 'files': rows}


def apply_invoice_plan(folder, plan, output):
    if plan.get('version') != 1 or plan.get('recipe') != 'invoice-copies':
        raise ValueError('Unsupported invoice plan')
    rows = plan.get('files')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Empty invoice plan')
    ready, seen_source, seen_target = [], set(), set()
    for row in rows:
        if row.get('status') != 'ready':
            raise ValueError('Resolve every review row before applying this plan')
        source, target = safe_name(row['source']), safe_name(row['target'])
        if not source.endswith('.pdf') or not target.endswith('.pdf'):
            raise ValueError('Only PDF copies are allowed')
        if source.casefold() in seen_source or target.casefold() in seen_target:
            raise ValueError('Duplicate source or target')
        seen_source.add(source.casefold())
        seen_target.add(target.casefold())
        path = Path(folder) / source
        if path.is_symlink() or not path.is_file():
            raise ValueError('Input is missing or is a symbolic link')
        raw = path.read_bytes()
        if digest(raw) != row['sha256']:
            raise ValueError('Source changed after preview: ' + source)
        ready.append((target, raw))
    output = Path(output)
    output.mkdir(parents=False, exist_ok=False)
    for name, raw in ready:
        with (output / name).open('xb') as stream:
            stream.write(raw)
    write_json(output / 'receipt.json', {'status': 'complete', **plan})
    return {'copied': len(ready), 'output': str(output)}


CSV_FIELDS = ['record_id', 'date', 'customer', 'amount', 'currency']


def merge_csv(folder, output):
    records, lineage, source_files, totals = {}, {}, [], {}
    input_rows = 0
    for path in regular_files(folder, '.csv'):
        raw = path.read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
        if reader.fieldnames is None or len(reader.fieldnames) != len(CSV_FIELDS) or set(reader.fieldnames) != set(CSV_FIELDS):
            raise ValueError('Unexpected CSV columns: ' + path.name)
        count = 0
        for row in reader:
            count += 1
            if set(row) != set(CSV_FIELDS) or any(v is None or not v.strip() for v in row.values()):
                raise ValueError('Missing/extra values: ' + path.name)
            # Reject unsafe spreadsheet text rather than silently alter source values.
            if any(row[k].lstrip().startswith(('=', '+', '-', '@')) for k in ('record_id', 'customer')):
                raise ValueError('Spreadsheet formula-like text requires review')
            date.fromisoformat(row['date'])
            if not re.fullmatch(r'[A-Z]{3}', row['currency']):
                raise ValueError('Currency must be a three-letter code')
            try:
                amount = Decimal(row['amount'])
            except InvalidOperation as error:
                raise ValueError('Invalid amount') from error
            if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
                raise ValueError('Amount must be finite with at most two decimal places')
            key = row['record_id']
            normalized = {**row, 'amount': format(amount, '.2f')}
            if key in records and records[key] != normalized:
                raise ValueError('Conflicting record_id: ' + key)
            if key not in records:
                records[key] = normalized
                totals[row['currency']] = totals.get(row['currency'], Decimal(0)) + amount
            lineage.setdefault(key, []).append({'file': path.name, 'record': count})
        input_rows += count
        source_files.append({'name': path.name, 'sha256': digest(raw), 'rows': count})
    if not records:
        raise ValueError('No data rows')
    output = Path(output)
    output.mkdir(parents=False, exist_ok=False)
    with (output / 'combined.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(records.values(), key=lambda r: (r['date'], r['record_id'])))
    receipt = {'status': 'complete', 'recipe': 'csv-consolidation', 'version': 1,
               'input_rows': input_rows, 'output_rows': len(records),
               'duplicate_rows': input_rows - len(records),
               'totals_by_currency': {k: str(v) for k, v in sorted(totals.items())},
               'sources': source_files, 'lineage': lineage,
               'output_sha256': digest((output / 'combined.csv').read_bytes())}
    write_json(output / 'receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preview = commands.add_parser('invoice-preview')
    preview.add_argument('input')
    preview.add_argument('patterns')
    preview.add_argument('plan')
    apply = commands.add_parser('invoice-apply')
    apply.add_argument('input')
    apply.add_argument('plan')
    apply.add_argument('output')
    merge = commands.add_parser('csv-merge')
    merge.add_argument('input')
    merge.add_argument('output')
    args = parser.parse_args()
    try:
        if args.command == 'invoice-preview':
            result = invoice_plan(args.input, json.loads(Path(args.patterns).read_text()))
            write_json(args.plan, result)
        elif args.command == 'invoice-apply':
            result = apply_invoice_plan(args.input, json.loads(Path(args.plan).read_text()), args.output)
        else:
            result = merge_csv(args.input, args.output)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError, InvalidOperation) as error:
        print('Stopped: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
