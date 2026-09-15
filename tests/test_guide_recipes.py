"""Controlled file-recipe checks; no provider or messenger execution."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'website/public/guides/assets/file-recipes.py'
spec = importlib.util.spec_from_file_location('guide_recipes', PATH)
recipes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipes)


def text_pdf(lines):
    content = 'BT /F1 12 Tf 40 700 Td ' + ' 0 -20 Td '.join('(' + s + ') Tj' for s in lines) + ' ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               ('<< /Length ' + str(len(content)) + ' >>\nstream\n' + content + '\nendstream').encode()]
    data, offsets = b'%PDF-1.4\n', [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(i).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets[1:])
    return data + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


class Recipes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'input'
        self.source.mkdir()
        self.output = self.root / 'output'
        self.patterns = {'vendor': r'^Vendor: (.+)$', 'date': r'^Date: (.+)$',
                         'invoice': r'^Invoice: (.+)$'}

    def invoice(self, name='download.pdf', lines=None):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest('Invoice recipe needs optional pypdf')
        raw = text_pdf(lines or ['Vendor: Example Studio', 'Date: 2026-09-01', 'Invoice: INV-100'])
        (self.source / name).write_bytes(raw)
        return raw

    def csv(self, name, rows):
        with (self.source / name).open('w', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(recipes.CSV_FIELDS)
            writer.writerows(rows)

    def test_invoice_copy_retains_exact_bytes_and_receipt(self):
        raw = self.invoice()
        plan = recipes.invoice_plan(self.source, self.patterns)
        recipes.apply_invoice_plan(self.source, plan, self.output)
        target = self.output / 'Example-Studio-2026-09-01-INV-100.pdf'
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual((self.source / 'download.pdf').read_bytes(), raw)
        self.assertEqual(json.loads((self.output / 'receipt.json').read_text())['status'], 'complete')

    def test_changed_source_stops_before_creating_output(self):
        self.invoice()
        plan = recipes.invoice_plan(self.source, self.patterns)
        (self.source / 'download.pdf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            recipes.apply_invoice_plan(self.source, plan, self.output)
        self.assertFalse(self.output.exists())

    def test_collisions_and_missing_fields_require_review(self):
        self.invoice('a.pdf')
        self.invoice('b.pdf')
        self.invoice('c.pdf', ['Vendor: Example Studio'])
        plan = recipes.invoice_plan(self.source, self.patterns)
        self.assertTrue(all(r['status'] == 'review' for r in plan['files']))
        with self.assertRaisesRegex(ValueError, 'review'):
            recipes.apply_invoice_plan(self.source, plan, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_partial_output_is_never_reused(self):
        self.invoice()
        plan = recipes.invoice_plan(self.source, self.patterns)
        self.output.mkdir()
        (self.output / 'keep.txt').write_text('original partial output')
        with self.assertRaises(FileExistsError):
            recipes.apply_invoice_plan(self.source, plan, self.output)
        self.assertEqual((self.output / 'keep.txt').read_text(), 'original partial output')
        self.assertFalse((self.output / 'receipt.json').exists())

    def test_csv_deduplicates_with_lineage_and_separate_currency_totals(self):
        a = ['A1', '2026-09-01', 'Example', '10.10', 'EUR']
        self.csv('a.csv', [a, ['A2', '2026-09-02', 'Example', '20.20', 'EUR']])
        self.csv('b.csv', [a, ['B1', '2026-09-03', 'Example', '7.00', 'USD']])
        receipt = recipes.merge_csv(self.source, self.output)
        self.assertEqual(receipt['totals_by_currency'], {'EUR': '30.30', 'USD': '7.00'})
        self.assertEqual((receipt['input_rows'], receipt['output_rows'], receipt['duplicate_rows']), (4, 3, 1))
        self.assertEqual(len(receipt['lineage']['A1']), 2)

    def test_conflicting_duplicate_stops_before_writing_any_output(self):
        self.csv('a.csv', [['A1', '2026-09-01', 'Example', '10.10', 'EUR']])
        self.csv('b.csv', [['A1', '2026-09-01', 'Example', '11.10', 'EUR']])
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            recipes.merge_csv(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_schema_drift_and_formula_text_stop_before_output(self):
        (self.source / 'a.csv').write_text('unexpected,column\nx,y\n')
        with self.assertRaisesRegex(ValueError, 'columns'):
            recipes.merge_csv(self.source, self.output)
        self.csv('a.csv', [['A1', '2026-09-01', '=1+1', '10.10', 'EUR']])
        with self.assertRaisesRegex(ValueError, 'formula'):
            recipes.merge_csv(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_symlink_input_rejected(self):
        external = self.root / 'other.csv'
        external.write_text('unrelated')
        (self.source / 'a.csv').symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symbolic'):
            recipes.merge_csv(self.source, self.output)


if __name__ == '__main__':
    unittest.main()
