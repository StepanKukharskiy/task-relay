"""Build the skills-only plugin or an explicit historical MCP development profile."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import ipaddress
import zipfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HOSTED = ROOT / 'plugins' / 'relay' / 'hosted'


def build(out, python, database=None, projects=()):
    if database is None and projects:
        raise ValueError('The web plugin does not accept local project grants')
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('Choose a new build directory; existing profiles are preserved')
    out.mkdir(parents=True, mode=0o700)
    for name in ('plugin.json', 'README.md'):
        shutil.copyfile(HOSTED / name, out / name)
    shutil.copytree(ROOT / 'plugins' / 'relay' / 'assets', out / 'assets')
    if database is None:
        shutil.copytree(HOSTED / 'skills', out / 'skills')
    readme = out / 'README.md'
    text = readme.read_text()
    for name in ('relay-chatgpt-plugin.md', 'relay-chatgpt-connection.md',
                 'relay-chatgpt-hosted-panel.md', 'relay-chatgpt-hosted-connection.md'):
        text = text.replace('../../../docs/' + name, str(ROOT / 'docs' / name))
        text = text.replace('../../docs/' + name, str(ROOT / 'docs' / name))
    readme.write_text(text)
    manifest = json.loads((HOSTED / 'mcp.json').read_text())
    config = manifest['mcpServers']['relay']
    # Preserve a virtual environment's interpreter path; resolving its symlink
    # can launch the system interpreter without the installed plugin SDK.
    config['command'] = str(Path(python).absolute())
    if database is not None:
        # Explicit database builds retain the historical local runtime contract.
        # The public web package and its Skill never expose these operations.
        config['args'] = ['-m', 'task_relay.chatgpt_plugin', '--db', str(Path(database).absolute())]
        for pid in projects:
            config['args'] += ['--project', pid]
        (out / 'README.md').write_text('# Task Relay — legacy local work-state development profile\n\n'
            'This explicit database profile preserves the local project runtime. '
            'It is separate from the portable web plugin V1.\n')
    config['env'] = {'PYTHONPATH': str(ROOT)}
    (out / 'mcp.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # Compatibility profile for local clients using the existing Codex format.
    (out / '.mcp.json').write_text(json.dumps({'mcpServers': {'relay': {k: v for k, v in config.items() if k != 'type'}}}, indent=2) + '\n')
    (out / '.codex-plugin').mkdir()
    overlay = {'name': 'relay-work', 'version': json.loads((out / 'plugin.json').read_text())['version'], 'description': 'Make useful work reusable', 'mcpServers': './.mcp.json',
               'interface': manifest_interface(hosted=True)}
    (out / '.codex-plugin' / 'plugin.json').write_text(json.dumps(overlay, indent=2) + '\n')
    receipt = {'schema': 'task-relay.plugin-build', 'version': 1,
               'mode': 'local-work-state-development' if database else 'stateless-web-development', 'source_runtime': str(ROOT),
               'installed': False, 'registered': False, 'published': False,
               'runtime_sources': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                   'task_relay/portable_work.py', 'task_relay/web_plugin.py', 'task_relay/assets/relay-reusable.html',
                   'task_relay/assets/relay-reusable.js', 'task_relay/assets/relay-reusable.css',
                   'task_relay/work_state.py', 'task_relay/work_state_cli.py', 'task_relay/chatgpt_plugin.py',
                   'task_relay/plugin_auth.py', 'task_relay/work_understanding.py', 'task_relay/assets/relay-work.html', 'task_relay/assets/relay-work.js',
                   'task_relay/assets/relay-work.css', 'task_relay/assets/companion.css', 'task_relay/assets/messages-icon.png')},
               'files': {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(out.rglob('*')) if p.is_file()}}
    (out / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def build_remote(out, endpoint):
    """Package a remote connection, excluding local launchers, paths and credentials.

    This creates a submission candidate, not evidence of endpoint readiness.
    """
    parsed = urlsplit(endpoint)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError('Use a valid HTTPS endpoint port') from exc
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path != '/mcp'):
        raise ValueError('Use an HTTPS /mcp endpoint without credentials, query or fragment')
    host = parsed.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid', '.example')) or host in {'example.com', 'example.org', 'example.net'}:
        raise ValueError('Use the actual public MCP hostname')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('Public packages cannot use a private MCP address')
    out = Path(out).absolute()
    archive = out.parent / (out.name + '.zip')
    if out.exists() or archive.exists():
        raise ValueError('Choose a new build directory and ZIP; existing versions are preserved')
    out.mkdir(parents=True, mode=0o700)
    for name in ('plugin.json',):
        shutil.copyfile(HOSTED / name, out / name)
    shutil.copytree(ROOT / 'plugins' / 'relay' / 'assets', out / 'assets')
    shutil.copytree(HOSTED / 'skills', out / 'skills')
    (out / 'README.md').write_text('# Task Relay for ChatGPT\n\n'
        'Turn useful ChatGPT conversations into reusable Skills and work you can pick up again.\n\n'
        'This package connects to the stateless Task Relay web MCP server. '
        'Review and export each proposed Skill or work snapshot independently. '
        'Select saved files in a fresh chat to reuse them. No local database, '
        'Desktop connection, account store or synchronization is required. '
        'Host Library uploads are optional; explicit downloads remain available. '
        'This package does not deploy its server or establish host qualification.\n')
    (out / 'mcp.json').write_text(json.dumps({
        '$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
        'mcpServers': {'relay': {'type': 'streamable-http', 'url': endpoint}}
    }, indent=2) + '\n')
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file()}
    # Only these portable package files enter the archive; the receipt stays outside.
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in files:
            zipped.write(out / name, name)
    receipt = {'schema': 'task-relay.plugin-build', 'version': 1,
               'mode': 'remote-submission-candidate', 'endpoint': endpoint,
               'files': files, 'zip_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
               'installed': False, 'registered': False, 'published': False,
               'endpoint_checked': False,
               'pending': ['Public HTTPS endpoint and domain verification',
                           'Stateless endpoint deployment and request-size/rate controls',
                           'Publisher website, support, privacy and terms URLs',
                           'Connected positive/negative cases and walkthrough',
                           'Submission review and explicit publication']}
    (out / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def build_skills(out):
    """Package native host instructions, without an MCP server or account binding."""
    out = Path(out).absolute()
    archive = out.parent / (out.name + '.zip')
    receipt_path = out.parent / (out.name + '-receipt.json')
    if out.exists() or archive.exists() or receipt_path.exists():
        raise ValueError('Choose a new directory and archive; existing versions are preserved')
    manifest = json.loads((ROOT / 'plugins/relay/plugin.json').read_text())
    extension = manifest.get('extensions', {}).get('com.openai', {})
    if manifest.get('apps') is not None or extension.get('apps') is not None:
        raise ValueError('The skills-only upload cannot contain an app binding')
    out.mkdir(parents=True, mode=0o700)
    for name in ('plugin.json', 'README.md'):
        shutil.copyfile(ROOT / 'plugins/relay' / name, out / name)
    for name in ('assets', 'skills'):
        shutil.copytree(ROOT / 'plugins/relay' / name, out / name)
    files = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file()}
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in files: zipped.write(out / name, manifest['name'] + '/' + name)
    receipt = {'schema': 'task-relay.plugin-build', 'version': 1,
               'mode': 'skills-only-native-host', 'plugin_version': manifest['version'],
               'files': files, 'zip_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
               'installed': False, 'registered': False, 'published': False,
               'pending': ['Native ChatGPT workflow qualification', 'Verified publisher pages',
                           'Submission review and publication']}
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def manifest_interface(hosted=False):
    source = HOSTED if hosted else ROOT / 'plugins/relay'
    return json.loads((source / 'plugin.json').read_text())['extensions']['com.openai']['interface']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True); p.add_argument('--python'); p.add_argument('--db'); p.add_argument('--project', action='append', default=[])
    p.add_argument('--endpoint', help='Build a portable remote HTTPS submission candidate and ZIP')
    args = p.parse_args()
    if args.endpoint:
        if args.python or args.db or args.project:
            p.error('Remote packages cannot include local Python, database or project arguments')
        receipt = build_remote(args.out, args.endpoint)
    elif args.python:
        receipt = build(args.out, args.python, args.db, args.project)
    else:
        if args.db or args.project:
            p.error('The skills-only plugin takes no database or project grants; legacy profiles require --python')
        receipt = build_skills(args.out)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__': main()
