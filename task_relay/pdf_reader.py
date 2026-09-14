"""Local PDF text extraction in a short-lived, timeout-supervised process."""
import hashlib
import io
import json
import logging
import sys

MAX_BYTES = 20_000_000
MAX_PAGES = 500
PAGES_PER_READ = 8
MAX_STREAM_BYTES = 8_000_000


def extract(raw, args):
    from pypdf import PdfReader, filters
    # Limit decoded streams as well as the uploaded file. No OCR, rendering,
    # embedded scripts, attachments or external links are executed.
    for name in ('ZLIB_MAX_OUTPUT_LENGTH', 'LZW_MAX_OUTPUT_LENGTH',
                 'RUN_LENGTH_MAX_OUTPUT_LENGTH', 'MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH',
                 'JBIG2_MAX_OUTPUT_LENGTH'):
        if hasattr(filters, name):
            setattr(filters, name, MAX_STREAM_BYTES)
    if len(raw) > MAX_BYTES or not raw.startswith(b'%PDF-'):
        return {'ok': False, 'error': 'Choose a PDF file no larger than 20 MB.'}
    digest = hashlib.sha256(raw).hexdigest()
    if args['sha256'] and args['sha256'] != digest:
        return {'ok': False, 'error': 'The PDF changed since the previous read. Start again at page 1 with an empty sha256.'}
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        return {'ok': False, 'error': 'Encrypted PDFs are not supported. Use an unlocked copy.'}
    total = len(reader.pages)
    if total > MAX_PAGES:
        return {'ok': False, 'error': 'PDF exceeds the 500-page reading limit.'}
    number, offset, remaining = args['page'], args['offset'], args['limit']
    if not 1 <= number <= total:
        return {'ok': False, 'error': 'Page is outside the PDF.', 'total_pages': total}
    rows = []
    while number <= total and len(rows) < PAGES_PER_READ and remaining > 0:
        page = reader.pages[number - 1]
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > MAX_STREAM_BYTES:
            return {'ok': False, 'error': 'PDF page content exceeds the extraction limit.', 'page': number}
        text = page.extract_text() or ''
        if offset > len(text):
            return {'ok': False, 'error': 'Character offset is outside this PDF page.', 'page': number}
        end = min(len(text), offset + remaining)
        rows.append({'page': number, 'offset': offset, 'text': text[offset:end],
                     'total_characters': len(text), 'no_extractable_text': not text.strip()})
        remaining -= end - offset
        if end < len(text):
            offset = end
            break
        number += 1
        offset = 0
    return {'ok': True, 'sha256': digest, 'total_pages': total, 'pages': rows,
            'next_page': number if number <= total else None,
            'next_offset': offset if number <= total else None,
            'limitations': 'Text layer only; page layout, drawings and images were not visually inspected. '
                            'Pages with no extractable text may be blank or require OCR.'}


def main():
    logging.disable(logging.CRITICAL)
    try:
        result = extract(sys.stdin.buffer.read(MAX_BYTES + 1), json.loads(sys.argv[1]))
    except ImportError:
        result = {'ok': False, 'error': 'PDF reader dependency is unavailable in this Relay runtime. Update the installation.'}
    except Exception:
        result = {'ok': False, 'error': 'PDF text extraction failed. The document may be damaged or exceed decoding limits.'}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    main()
