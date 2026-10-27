"""Bounded inert display of saved HTML. No reads, scripts, or artifact edits."""
import base64
import html
import io
import hashlib
from html.parser import HTMLParser


STYLE = "body{background:#f4f3ee;color:#26332c;font:15px/1.5 system-ui;margin:0;overflow-wrap:anywhere}main{max-width:1200px;margin:auto;padding:20px}h1{font-size:28px;line-height:1.2}h2{font-size:19px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:18px}article{background:white;border:1px solid #ddd;border-radius:12px;overflow:hidden}img{max-width:100%;height:auto}article img{width:100%;height:260px;object-fit:contain}article div{padding:16px}a{color:#176347}code{font-size:11px}pre{white-space:pre-wrap}details{margin-top:16px}table{border-collapse:collapse;max-width:100%}td,th{padding:6px;border:1px solid #ddd}"
STYLE_HASH = base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
CSP = "default-src 'none'; img-src data:; style-src 'sha256-"+STYLE_HASH+"'; base-uri 'none'; form-action 'none'"


def render(content):
    from PIL import Image, ImageOps

    class Preview(HTMLParser):
        tags = set('html head body title style main section article aside header footer div span p h1 h2 h3 h4 h5 h6 ul ol li dl dt dd details summary pre code strong em b i small br hr table thead tbody tr td th figure figcaption img a'.split())
        blocked = set('script style iframe object embed svg math template noscript'.split())

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []; self.depth = 0; self.text_bytes = 0; self.images = 0
            self.image_count = max(1, content.lower().count(b'<img'))
            self.budget = min(100000, 400000 // min(64, self.image_count))

        def handle_starttag(self, tag, attrs):
            if self.depth:
                if tag in self.blocked: self.depth += 1
                return
            if tag in self.blocked:
                if tag not in ('embed',): self.depth = 1
                return
            if tag not in self.tags: return
            clean = []
            for name, value in attrs:
                if value is None: continue
                if name in ('class', 'id', 'title', 'alt', 'lang'):
                    clean.append((name, value[:4000]))
                elif tag == 'a' and name == 'href':
                    clean.append(('title', value[:4000]))  # No frame navigation.
                elif tag == 'img' and name == 'src':
                    src = self.picture(value)
                    if src: clean.append(('src', src))
            self.parts.append('<' + tag + ''.join(' '+k+'="'+html.escape(v, quote=True)+'"' for k,v in clean) + '>')

        def picture(self, value):
            if self.images >= 64: return None
            self.images += 1
            if not value.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,', 'data:image/gif;base64,')): return None
            try:
                raw = base64.b64decode(value.split(',', 1)[1], validate=True)
                with Image.open(io.BytesIO(raw)) as source:
                    if source.width * source.height > 20_000_000: return None
                    picture = ImageOps.exif_transpose(source).convert('RGB')
                picture.thumbnail((800, 800), Image.Resampling.LANCZOS)
                while True:
                    buf = io.BytesIO(); picture.save(buf, format='JPEG', quality=78)
                    encoded = base64.b64encode(buf.getvalue()).decode()
                    if len(encoded) <= self.budget: return 'data:image/jpeg;base64,' + encoded
                    picture = picture.resize(tuple(max(1, int(n*.75)) for n in picture.size), Image.Resampling.LANCZOS)
            except (ValueError, OSError, Image.DecompressionBombError):
                return None

        def handle_endtag(self, tag):
            if self.depth:
                if tag in self.blocked: self.depth -= 1
                return
            if tag in self.tags: self.parts.append('</'+tag+'>')

        def handle_data(self, data):
            if self.depth: return
            self.text_bytes += len(data.encode())
            if self.text_bytes > 200000: raise ValueError('HTML text exceeds the inline preview limit.')
            self.parts.append(html.escape(data))

    parser = Preview(); parser.feed(content.decode('utf-8')); parser.close()
    # CSP is first, and source meta/base/link elements are never retained.
    result = '<!doctype html><meta http-equiv="Content-Security-Policy" content="'+html.escape(CSP, quote=True)+'"><style>'+STYLE+'</style>' + ''.join(parser.parts)
    import json
    if len(json.dumps(result).encode()) > 850000: raise ValueError('HTML exceeds the inline preview limit.')
    return result
