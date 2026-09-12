"""Find explicit local file links and snapshot them for reliable delivery."""
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit

from task_relay.relay_paths import PATHS

MAX_FILE = 50_000_000
MAX_PHOTO = 10_000_000
MAX_ATTACHMENTS = 6
MIMES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
         '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
         '.tif': 'image/tiff', '.tiff': 'image/tiff'}


def attachment_links(text, cwd=None, thread_id=None):
    # Both image embeds and download links, including spaces in <...> and one
    # level of parentheses in filenames. Never fetch remote URLs automatically.
    text = re.sub(r'\\([\[\]()])', r'\1', text)
    pattern = r'!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|(?:[^()\n]|\([^()\n]*\))+)\s*\)'
    seen = set()
    roots = [PATHS.install, PATHS.workspaces, PATHS.generated, PATHS.data, Path.home() / 'Documents/Codex', Path.home() / '.codex/generated_images',
             Path('/private/tmp'), Path(tempfile.gettempdir())]
    if cwd:
        roots.append(Path(cwd))
    roots = [root.resolve() for root in roots]
    visualizations = (Path.home() / '.codex/visualizations').resolve()
    for match in re.finditer(pattern, text):
        target = match[1].strip()
        if target.startswith('<'):
            target = target[1:target.index('>')]
        else:
            target = re.sub(r'\s+["\'].*["\']$', '', target)
        if urlsplit(target).scheme or target.startswith('//'):
            continue
        target = re.sub(r':\d+(?::\d+)?$', '', unquote(target))
        path = Path(target)
        if not path.is_absolute():
            if not cwd:
                continue
            path = Path(cwd) / path
        path = path.resolve()
        own_visualization = False
        if thread_id and path.is_relative_to(visualizations):
            parts = path.relative_to(visualizations).parts
            own_visualization = (len(parts) >= 5 and parts[3] == thread_id
                                 and bool(re.fullmatch(r'\d{4}/\d{2}/\d{2}', '/'.join(parts[:3]))))
        if path in seen or not (own_visualization or any(path.is_relative_to(root) for root in roots)):
            continue
        seen.add(path)
        yield path


def image_links(text, cwd=None, thread_id=None):
    """Image-only discovery, retained for callers that specifically need images."""
    yield from (p for p in attachment_links(text, cwd, thread_id) if p.suffix.lower() in MIMES)


def valid_image(data, suffix):
    return bool(
        suffix == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n') or
        suffix in ('.jpg', '.jpeg') and data.startswith(b'\xff\xd8\xff') or
        suffix == '.gif' and data[:6] in (b'GIF87a', b'GIF89a') or
        suffix == '.webp' and data[:4] == b'RIFF' and data[8:12] == b'WEBP' or
        suffix == '.bmp' and data[:2] == b'BM' or
        suffix in ('.tif', '.tiff') and data[:4] in (b'II*\x00', b'MM\x00*'))


def queue_attachments(state, event_id, thread_id, title, summary, cwd=None):
    """Called within the watcher's transaction, together with the text outbox."""
    paths = list(attachment_links(summary, cwd, thread_id))
    # Directory links are navigation, not downloadable files. Never archive them.
    paths = [p for p in paths if not p.is_dir()]
    if len(paths) > MAX_ATTACHMENTS:
        state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                         (event_id + ':attachment-limit', thread_id,
                          f'Attaching up to the first {MAX_ATTACHMENTS} linked files. Open Codex for the remaining files.'))
    for index, path in enumerate(paths[:MAX_ATTACHMENTS]):
        key = f'{event_id}:attachment:{index}'
        if state.db.execute('SELECT 1 FROM media_outbox WHERE id IN (?,?)',
                            (key + ':original', key + ':video')).fetchone():
            continue
        try:
            if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE:
                raise ValueError('missing, empty, or oversized file')
            with path.open('rb') as stream:
                data = stream.read(MAX_FILE + 1)
            if len(data) > MAX_FILE or (path.suffix.lower() in MIMES and not valid_image(data, path.suffix.lower())):
                raise ValueError('oversized file or unsupported image contents')
            state.media_dir.mkdir(mode=0o700, exist_ok=True)
            snapshot = state.media_dir / (hashlib.sha256(key.encode()).hexdigest() + path.suffix.lower())
            temporary = snapshot.with_suffix('.tmp')
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            temporary.replace(snapshot)
        except (OSError, ValueError):
            state.db.execute('INSERT OR IGNORE INTO outbox(id,thread_id,text) VALUES (?,?,?)',
                             (key + ':unavailable', thread_id,
                              f'Could not attach {path.name[:180]}: missing, empty, unsupported, or over 50 MB.'))
            continue
        modes = ['original']
        if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') and len(data) <= MAX_PHOTO:
            modes.insert(0, 'preview')
        elif path.suffix.lower() in ('.mp4', '.m4v') and data[4:8] == b'ftyp':
            modes = ['video']
        elif path.suffix.lower() == '.mp3':
            modes = ['audio']
        for mode in modes:
            caption = f'{title[:120]}\n{path.name[:180]} — {mode}\nReply to continue this task.'
            state.db.execute('INSERT OR IGNORE INTO media_outbox '
                             '(id,event_id,thread_id,path,filename,kind,caption) VALUES (?,?,?,?,?,?,?)',
                             (key + ':' + mode, event_id, thread_id, str(snapshot), path.name, mode, caption))


# Backward-compatible helper name used by existing local setup/test scripts.
queue_images = queue_attachments


def video_metadata(path):
    """Read display dimensions without transforming the original video bytes."""
    import json
    import math
    import shutil
    import subprocess
    from fractions import Fraction
    probe = shutil.which('ffprobe')
    if not probe and Path('/opt/homebrew/bin/ffprobe').is_file():
        probe = '/opt/homebrew/bin/ffprobe'
    if not probe:
        return {}
    try:
        result = subprocess.run(
            [probe, '-v', 'error', '-protocol_whitelist', 'file', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,sample_aspect_ratio:stream_tags=rotate:stream_side_data=rotation:format=duration',
             '-of', 'json', str(Path(path).resolve())], stdin=subprocess.DEVNULL,
            capture_output=True, timeout=5, check=True)
        info = json.loads(result.stdout)
        stream = info['streams'][0]
        width, height = int(stream['width']), int(stream['height'])
        sar = stream.get('sample_aspect_ratio', '1:1')
        if sar not in ('N/A', '0:1', ''):
            width = round(width * Fraction(sar.replace(':', '/')))
        rotation = stream.get('tags', {}).get('rotate', 0)
        for side in stream.get('side_data_list', []):
            if 'rotation' in side:
                rotation = side['rotation']
                break
        rotation = float(rotation)
        if not math.isfinite(rotation) or abs(rotation / 90 - round(rotation / 90)) > .001:
            return {}
        if round(rotation / 90) % 2:
            width, height = height, width
        if not (0 < width <= 65535 and 0 < height <= 65535):
            return {}
        metadata = {'width': width, 'height': height}
        duration = float(info.get('format', {}).get('duration', 0))
        if math.isfinite(duration) and duration > 0:
            metadata['duration'] = math.ceil(duration)
        return metadata
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
        return {}
