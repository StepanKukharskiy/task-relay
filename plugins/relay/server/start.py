"""Start the isolated public web service; no local database or credentials."""
import os
from task_relay.web_plugin import main

origin = os.environ.get('TASK_RELAY_PUBLIC_ORIGIN')
if not origin:
    raise SystemExit('Set TASK_RELAY_PUBLIC_ORIGIN to the actual public HTTPS origin.')
main(['--transport', 'http', '--host', '0.0.0.0',
      '--port', os.environ.get('PORT', '8080'), '--public-origin', origin])
