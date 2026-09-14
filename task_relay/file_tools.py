"""Bounded, read-only project tools. All opens stay beneath a directory descriptor."""
from contextlib import contextmanager
import fnmatch
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from .filesystem import Grant, FILES, AccessDenied
from .host import UnsupportedHost

MAX_FILE_BYTES = 1_000_000
MAX_SCAN_BYTES = 8_000_000
MAX_ENTRIES = 5000
MAX_CHARS = 24000
MAX_DEPTH = 12
EXCLUDED = {'private', 'node_modules', '__pycache__', 'venv', 'env', 'secrets', 'credentials'}
SECRET_PATTERNS = ('*.pem', '*.key', '*.p12', '*.pfx', '*.db', '*.sqlite*',
                   '*credentials*', '*secret*', 'id_rsa*', 'id_ed25519*')


def definition(name, description, properties):
    return {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties,
                           'required': list(properties), 'additionalProperties': False}}


DEFINITIONS = [
    definition('pdf_read', 'Read the actual PDF text layer with page citations and a version hash. '
               'Up to 8 pages and 24000 characters per call, 20 MB / 500 pages per PDF. '
               'Follow next_page/next_offset with the returned sha256. No OCR or visual diagram reading.', {
        'path': {'type': 'string'},
        'page': {'type': 'integer', 'minimum': 1, 'maximum': 500, 'description': 'PDF page number, initially 1.'},
        'offset': {'type': 'integer', 'minimum': 0, 'description': 'Character offset within page, initially 0.'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_CHARS},
        'sha256': {'type': 'string', 'maxLength': 64, 'description': 'Empty for the first read; returned sha256 for continuation to reject changed files.'}}),
    definition('file_list', 'List visible project files/directories. Paths are relative to the task folder. '
               'Hidden/private/dependency paths and symlinks are excluded. Results may be incomplete when scan limits are reached.', {
        'path': {'type': 'string', 'description': 'Directory, use . for the project root.'},
        'recursive': {'type': 'boolean'},
        'offset': {'type': 'integer', 'minimum': 0, 'description': 'Entry offset, initially 0.'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}),
    definition('file_read', 'Read a UTF-8 or BOM-marked UTF-16 text file up to 1 MB. '
               'Returns a character page and its starting line number; use next_offset to continue without losing long lines.', {
        'path': {'type': 'string'},
        'offset': {'type': 'integer', 'minimum': 0, 'description': 'Character offset, initially 0.'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_CHARS}}),
    definition('file_search', 'Search literal text in visible project text files. No regular expressions. '
               'Returns file paths, line numbers, and excerpts; scope the path when the scan is incomplete.', {
        'path': {'type': 'string', 'description': 'File or directory; . for the project root.'},
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'case_sensitive': {'type': 'boolean'},
        'offset': {'type': 'integer', 'minimum': 0, 'description': 'Matching line offset, initially 0.'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}),
]


class FileToolError(ValueError):
    pass


def excluded(name):
    name = name.casefold()
    return name.startswith('.') or name in EXCLUDED or any(fnmatch.fnmatchcase(name, pat) for pat in SECRET_PATTERNS)


def validate(name, arguments):
    spec = next((d for d in DEFINITIONS if d['name'] == name), None)
    if not spec:
        raise FileToolError('Unknown file tool.')
    if not isinstance(arguments, dict) or set(arguments) != set(spec['parameters']['properties']):
        raise FileToolError('Supply exactly the documented tool arguments.')
    for key, rule in spec['parameters']['properties'].items():
        value = arguments[key]
        kind = {'string': str, 'integer': int, 'boolean': bool}[rule['type']]
        if type(value) is not kind:
            raise FileToolError('Invalid argument type: ' + key)
        if kind is str and (len(value) > rule.get('maxLength', 4096) or len(value) < rule.get('minLength', 0)):
            raise FileToolError('Invalid argument length: ' + key)
        if kind is int and not rule.get('minimum', 0) <= value <= rule.get('maximum', 1_000_000):
            raise FileToolError('Argument outside supported range: ' + key)


class Workspace:
    def __init__(self, root, protected=(), grant=None):
        self.root = Path(root)
        self.protected = tuple(Path(p).resolve() for p in protected)
        self.grant = grant or Grant(self.root, "selected project read scope", protected=self.protected)
        if Path(self.grant.root)!=self.root:raise FileToolError("Grant and selected project roots differ")

    def parts(self, path):
        if not path or '\x00' in path or '..' in Path(path).parts:
            raise FileToolError('Use a path inside the selected project, without parent traversal.')
        target = Path(path)
        if target.is_absolute():
            try:
                target = target.relative_to(self.root)
            except ValueError:
                raise FileToolError('Path is outside the selected project.') from None
        parts = target.parts
        if any(excluded(part) for part in parts):
            raise FileToolError('Hidden, private, credential, and dependency paths are excluded.')
        absolute = self.root.joinpath(*parts)
        if any(absolute.is_relative_to(p) for p in self.protected):
            raise FileToolError('Task Relay private state is excluded.')
        return parts

    @contextmanager
    def open(self, path, directory=False):
        parts = self.parts(path)
        # Walk every component using O_NOFOLLOW, including the root's ancestors.
        # Directory fds prevent a symlink swap between checking and opening a file.
        if not self.root.is_absolute() or any(
                excluded(p) for index, p in enumerate(self.root.parts[1:], 1)
                if not (p == 'private' and index == 1)):
            raise FileToolError('Choose a visible project folder outside private/dependency directories.')
        try:
            with FILES.open(self.grant, path, directory=directory) as fd:
                yield fd
        except AccessDenied as exc:
            raise FileToolError(str(exc)) from None

    def read_text(self, path, budget=None):
        with self.open(path) as fd:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise FileToolError('Choose a regular text file.')
            if info.st_size > MAX_FILE_BYTES:
                raise FileToolError('File exceeds the 1 MB text limit.')
            remaining = MAX_SCAN_BYTES - budget['bytes'] if budget is not None else MAX_FILE_BYTES
            if info.st_size > remaining:
                budget['incomplete'] = True
                raise FileToolError('Search byte budget reached.')
            with os.fdopen(os.dup(fd), 'rb') as stream:
                raw = stream.read(min(MAX_FILE_BYTES, remaining) + 1)
        if budget is not None:
            budget['bytes'] += len(raw)
            if len(raw) > remaining:
                budget['incomplete'] = True
                raise FileToolError('Search byte budget reached.')
        if len(raw) > MAX_FILE_BYTES:
            raise FileToolError('File exceeds the 1 MB text limit.')
        try:
            text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        except UnicodeError:
            raise FileToolError('Unsupported binary or text encoding; use UTF-8 or BOM-marked UTF-16.') from None
        if any(ord(c) < 32 and c not in '\t\r\n\f' for c in text):
            raise FileToolError('Binary files are not supported by the text tools.')
        return text, len(raw)

    def walk(self, path, recursive, budget):
        def visit(current, depth):
            if depth > MAX_DEPTH:
                budget['incomplete'] = True
                return
            with self.open(current, directory=True) as fd:
                names = []
                with os.scandir(fd) as scan:
                    for entry in scan:
                        budget['entries'] += 1
                        if budget['entries'] > MAX_ENTRIES:
                            budget['incomplete'] = True
                            break
                        names.append(entry.name)
                for name in sorted(names):
                    relative = str(Path(current) / name)
                    try:
                        self.parts(relative)
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            kind = 'directory'
                        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                            kind = 'file'
                        else:
                            continue
                    except (OSError, FileToolError):
                        continue
                    yield {'path': relative, 'type': kind}
                    if recursive and kind == 'directory' and budget['entries'] < MAX_ENTRIES:
                        try:
                            yield from visit(relative, depth + 1)
                        except (OSError, FileToolError):
                            budget['incomplete'] = True
                    elif recursive and kind == 'directory':
                        budget['incomplete'] = True
        yield from visit(str(Path(*self.parts(path))) or '.', 0)

    def call(self, name, arguments):
        validate(name, arguments)
        path = arguments['path']
        offset, limit = arguments['offset'], arguments['limit']
        if name == 'pdf_read':
            return self.read_pdf(arguments)
        if name == 'file_read':
            text, _ = self.read_text(path)
            end = min(offset + limit, len(text))
            return {'path': str(Path(*self.parts(path))), 'offset': offset,
                    'start_line': text[:offset].count('\n') + 1, 'text': text[offset:end],
                    'next_offset': end if end < len(text) else None, 'total_characters': len(text)}
        budget = {'entries': 0, 'bytes': 0, 'incomplete': False}
        if name == 'file_list':
            rows = list(self.walk(path, arguments['recursive'], budget))
            return {'entries': rows[offset:offset + limit],
                    'next_offset': offset + limit if offset + limit < len(rows) else None,
                    'scan_incomplete': budget['incomplete']}
        with self.open(path) as fd:
            is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
        rows = self.walk(path, True, budget) if is_dir else [{'path': str(Path(*self.parts(path))), 'type': 'file'}]
        matches, seen, skipped = [], 0, 0
        query = arguments['query'] if arguments['case_sensitive'] else arguments['query'].casefold()
        for row in rows:
            if row['type'] != 'file':
                continue
            if budget['bytes'] >= MAX_SCAN_BYTES:
                budget['incomplete'] = True
                break
            try:
                text, _ = self.read_text(row['path'], budget)
            except (OSError, FileToolError):
                skipped += 1
                continue
            for number, line in enumerate(text.splitlines(), 1):
                haystack = line if arguments['case_sensitive'] else line.casefold()
                at = haystack.find(query)
                if at < 0:
                    continue
                seen += 1
                if seen <= offset:
                    continue
                if len(matches) == limit:
                    return {'matches': matches, 'next_offset': offset + limit,
                            'scan_incomplete': budget['incomplete'], 'skipped_files': skipped}
                start = max(0, at - 80)
                matches.append({'path': row['path'], 'line': number,
                                'excerpt': line[start:start + 400], 'excerpt_truncated': len(line) > 400})
        return {'matches': matches, 'next_offset': None,
                'scan_incomplete': budget['incomplete'], 'skipped_files': skipped}

    def read_pdf(self, arguments):
        try:
            from . import pdf_reader
        except ImportError:
            raise FileToolError('The installed Relay runtime is missing its PDF reader. '
                                'Install a complete app build and restart Relay; rephrasing is not required.') from None
        with self.open(arguments['path']) as fd:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > pdf_reader.MAX_BYTES:
                raise FileToolError('Choose a regular PDF file no larger than 20 MB.')
            with os.fdopen(os.dup(fd), 'rb') as stream:
                raw = stream.read(pdf_reader.MAX_BYTES + 1)
        if len(raw) > pdf_reader.MAX_BYTES or not raw.startswith(b'%PDF-'):
            raise FileToolError('Choose a PDF file no larger than 20 MB.')
        try:
            result = subprocess.run([sys.executable, str(Path(pdf_reader.__file__).resolve()),
                                     json.dumps(arguments)], input=raw, capture_output=True, timeout=15)
        except subprocess.TimeoutExpired:
            raise FileToolError('PDF extraction exceeded 15 seconds. No text was returned; no automatic retry was made.') from None
        if result.returncode or len(result.stdout) > 128000:
            raise FileToolError('PDF reader failed or exceeded its output limit.')
        value = json.loads(result.stdout)
        return {'path': str(Path(*self.parts(arguments['path']))), **value}


def execute(root, name, raw_arguments, protected=()):
    try:
        if not isinstance(raw_arguments, str) or len(raw_arguments) > 10000:
            raise FileToolError('Tool arguments must be a small JSON object.')
        arguments = json.loads(raw_arguments)
        result = {'ok': True, **Workspace(root, protected).call(name, arguments)}
        if len(json.dumps(result, ensure_ascii=False).encode()) > 128000:
            raise FileToolError('Result exceeds the output limit. Reduce the page limit or narrow the path.')
        return result
    except (FileToolError, UnsupportedHost) as exc:
        return {'ok': False, 'error': str(exc)}
    except (OSError, ValueError, RecursionError):
        # Never echo OS errors: they may expose paths outside the project.
        return {'ok': False, 'error': 'Cannot access this path or parse these arguments. Symlinks and non-project files are excluded.'}
