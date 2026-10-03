"""Prepare a private, project-scoped stdio launcher for Secure MCP Tunnel.

Does not install tunnel-client, transmit data, or register a ChatGPT connection.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import sqlite3
from contextlib import closing

if __package__:
    from .build_relay_plugin import build, ROOT
else:
    from build_relay_plugin import build, ROOT


def prepare(out, python, database, project_id):
    out = Path(out).absolute()
    python = Path(python).absolute()
    database = Path(database).resolve(strict=True)
    if out.exists():
        raise ValueError('Choose a new directory; previous connection profiles are preserved')
    if not python.is_file():
        raise ValueError('Choose the Python interpreter with the plugin extra installed')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT title, revision FROM work_projects WHERE id=?', (project_id,)).fetchone()
        if row is None:
            raise ValueError('The selected database does not contain that work project')
    out.mkdir(parents=True, mode=0o700)
    build(out / 'plugin', python, database, [project_id])
    # A script path avoids reliance on the tunnel process's working directory.
    launcher = out / 'serve.py'
    launcher.write_text(
        'import sys\n'
        f'sys.path.insert(0, {str(ROOT)!r})\n'
        'from task_relay.chatgpt_plugin import main\n'
        f'main({["--db", str(database), "--project", project_id]!r})\n')
    command = shlex.join([str(python), str(launcher)])
    (out / 'start-tunnel.py').write_text('''"""Run locally after creating a tunnel in OpenAI Platform."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--tunnel-id', required=True)
parser.add_argument('--client', default='tunnel-client')
args = parser.parse_args()
if not re.fullmatch(r'tunnel_[A-Za-z0-9]+', args.tunnel_id):
    parser.error('Use the tunnel_id from Platform tunnel settings')
client = shutil.which(args.client)
if not client:
    parser.error('Download tunnel-client from Platform tunnel settings and supply --client /path/to/tunnel-client')
client = str(Path(client).absolute())
env = dict(os.environ)
if not env.get('CONTROL_PLANE_API_KEY'):
    env['CONTROL_PLANE_API_KEY'] = getpass.getpass('Tunnel runtime API key (hidden, kept in process memory): ')
if not env['CONTROL_PLANE_API_KEY']:
    parser.error('A tunnel runtime API key is required')
folder = Path(__file__).resolve().parent
profile = 'task-relay'
profile_dir = folder / 'tunnel-profile'
configuration = profile_dir / (profile + '.yaml')
setup_path = folder / 'tunnel-setup.json'
identity = {'tunnel_id': args.tunnel_id, 'mcp_command': MCP_COMMAND}
if setup_path.exists():
    saved = json.loads(setup_path.read_text())
    if any(saved.get(k) != v for k, v in identity.items()):
        parser.error('This folder already belongs to another tunnel/launcher. Prepare a new connection directory.')
    if not configuration.is_file() or hashlib.sha256(configuration.read_bytes()).hexdigest() != saved['profile_sha256']:
        parser.error('The saved tunnel profile changed or is missing. Inspect it before reconnecting.')
else:
    if configuration.exists():
        parser.error('A profile exists without its setup receipt. Inspect the interrupted setup before retrying.')
    subprocess.run([client, 'init', '--sample', 'sample_mcp_stdio_local',
        '--profile', profile, '--profile-dir', str(profile_dir),
        '--tunnel-id', args.tunnel_id, '--mcp-command', MCP_COMMAND,
        '--health-listen-addr', '127.0.0.1:0'], cwd=folder, env=env, check=True)
    identity['profile_sha256'] = hashlib.sha256(configuration.read_bytes()).hexdigest()
    with setup_path.open('x') as receipt:
        json.dump(identity, receipt, indent=2)
commands = [
    [client, 'doctor', '--profile', profile, '--profile-dir', str(profile_dir), '--explain'],
    [client, 'run', '--profile', profile, '--profile-dir', str(profile_dir)],
]
for command in commands:
    subprocess.run(command, cwd=folder, env=env, check=True)
'''.replace('MCP_COMMAND', repr(command)))
    (out / 'CONNECT.txt').write_text(
        f'Task Relay — private ChatGPT test\nWork: {row[0]}\nSaved revision: {row[1]}\n\n'
        '1. Enable ChatGPT Developer mode in Settings > Security and login.\n'
        '2. Create a tunnel at https://platform.openai.com/settings/organization/tunnels.\n'
        '   Associate it with the ChatGPT workspace you will test in.\n'
        '3. Download tunnel-client from that page. Keep the runtime API key local.\n'
        '4. Run the command below in Terminal; it prompts for the key without echoing it.\n'
        f'{shlex.join([str(python), str(out / "start-tunnel.py")])} --tunnel-id YOUR_TUNNEL_ID --client /path/to/tunnel-client\n'
        '5. Keep it running. In ChatGPT Plugins > +, choose Connection > Tunnel.\n'
        '   Name: Task Relay. Select the same tunnel and create the connection.\n'
        '6. Enable Task Relay in a new chat and ask: Open my work in Task Relay.\n'
        '7. Inspect Current, choose Continue, send the context, and explicitly capture result notes.\n'
        '8. In a fresh chat, reopen work and confirm those notes survived.\n\n'
        'This shares only the selected work project through the connection. '
        'It does not connect your full chat history. Your database is live: '
        'explicit captures and reviews persist there. The HTML preview remains separate.\n'
        'This connection is a development test, not public publication.\n')
    receipt = {'schema': 'task-relay.chatgpt-connection', 'version': 1,
               'project_id': project_id, 'revision_at_preparation': row[1],
               'transport': 'Secure MCP Tunnel to project-scoped local stdio',
               'launcher_sha256': hashlib.sha256(launcher.read_bytes()).hexdigest(),
               'installed': False, 'tunnel_started': False, 'chatgpt_connected': False,
               'database_mutated': False, 'credentials_saved': False}
    (out / 'connection-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--python', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--project', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.out, args.python, args.db, args.project), indent=2))


if __name__ == '__main__':
    main()
