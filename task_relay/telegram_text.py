"""Render common Markdown as Telegram text entities, never raw HTML."""
import html
import re
from urllib.parse import urlsplit


def units(value):
    return len(value.encode('utf-16-le')) // 2


class Text:
    def __init__(self):
        self.pieces, self.entities, self.length = [], [], 0

    def add(self, value, entities=()):
        self.pieces.append(value)
        self.entities.extend({**e, 'offset': self.length + e['offset']} for e in entities)
        self.length += units(value)

    def styled(self, value, kind, extra=None):
        if not value:
            return
        self.add(value, [{'type': kind, 'offset': 0, 'length': units(value), **(extra or {})}])

    def result(self):
        # Duplicate bold spans can arise from a heading containing **bold**.
        entities = list({tuple(sorted(e.items())): e for e in self.entities if e['length'] > 0}.values())
        return ''.join(self.pieces), sorted(entities, key=lambda e: (e['offset'], -e['length']))


INLINE = re.compile(
    r'(?P<code>`+)(?P<codebody>[^`\n]+)(?P=code)'
    r'|!?\[(?P<label>[^\]\n]+)\]\(\s*(?P<url><[^>\n]+>|(?:[^()\n]|\([^()\n]*\))+)\s*\)'
    r'|(?P<strong>\*\*|__)(?P<strongbody>.+?)(?P=strong)'
    r'|~~(?P<strike>.+?)~~'
    r'|(?<![\w*])\*(?!\*)(?P<italic>[^*\n]+)\*(?!\*)'
    r'|(?<!\w)_(?P<underitalic>[^_\n]+)_(?!\w)'
    r'|\\(?P<escaped>[\\`*_{}\[\]()#+.!>|-])', re.S)


def inline(value, depth=0):
    if depth > 8:
        return value, []
    out, pos = Text(), 0
    for match in INLINE.finditer(value):
        out.add(value[pos:match.start()])
        if match['code']:
            out.styled(match['codebody'], 'code')
        elif match['label'] is not None:
            label, nested = inline(match['label'], depth + 1)
            url = match['url'].strip().strip('<>')
            try:
                scheme = urlsplit(url).scheme
            except ValueError:
                scheme = ''
            if scheme in ('http', 'https', 'mailto', 'tg'):
                nested = [e for e in nested if e['type'] not in ('code', 'pre', 'text_link')]
                nested.append({'type': 'text_link', 'offset': 0, 'length': units(label), 'url': url})
            out.add(label, nested)
        elif match['escaped'] is not None:
            out.add(match['escaped'])
        else:
            body = match['strongbody'] or match['strike'] or match['italic'] or match['underitalic']
            kind = 'bold' if match['strongbody'] else ('strikethrough' if match['strike'] else 'italic')
            plain, nested = inline(body, depth + 1)
            # Telegram disallows code/pre nesting with other entities.
            if not any(e['type'] in ('code', 'pre') for e in nested):
                nested.append({'type': kind, 'offset': 0, 'length': units(plain)})
            out.add(plain, nested)
        pos = match.end()
    out.add(value[pos:])
    return out.result()


def blocks(value):
    out = Text()
    for line in value.splitlines(keepends=True):
        heading = re.match(r'^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?(\n?)$', line)
        quote = re.match(r'^ {0,3}>\s?(.*?)(\n?)$', line)
        if heading or quote:
            match = heading or quote
            plain, entities = inline(match[1])
            if not any(e['type'] in ('code', 'pre') for e in entities):
                entities.append({'type': 'bold' if heading else 'blockquote', 'offset': 0, 'length': units(plain)})
            out.add(plain, entities)
            out.add(match[2])
        else:
            out.add(*inline(line))
    return out.result()


def render(value):
    # Copied task responses may contain HTML entities and escaped link delimiters.
    value = html.unescape(value)
    value = re.sub(r'\\([\[\]()])', r'\1', value)
    out, pos = Text(), 0
    fence = re.compile(r'(?ms)^ {0,3}```([^\n]*)\n(.*?)(?:^ {0,3}```[ \t]*(?:\n|$)|\Z)')
    for match in fence.finditer(value):
        out.add(*blocks(value[pos:match.start()]))
        language = match[1].strip()
        extra = {'language': language} if re.fullmatch(r'[A-Za-z0-9_+-]{1,30}', language) else {}
        out.styled(match[2], 'pre', extra)
        pos = match.end()
    out.add(*blocks(value[pos:]))
    return out.result()


def parts(value, splitter):
    plain, entities = render(value)
    return split_rendered(plain, entities, splitter)


def split_rendered(plain, entities, splitter):
    """Split literal, already formatted text without re-parsing Markdown."""
    chunks = splitter(plain)
    result, offset = [], 0
    for index, chunk in enumerate(chunks, 1):
        prefix = f'Part {index}/{len(chunks)}\n\n' if len(chunks) > 1 else ''
        length = units(chunk)
        selected = []
        for entity in entities:
            start = max(entity['offset'], offset)
            end = min(entity['offset'] + entity['length'], offset + length)
            if end > start:
                selected.append({**entity, 'offset': start - offset + units(prefix), 'length': end - start})
        result.append((prefix + chunk, selected))
        offset += length
    return result
