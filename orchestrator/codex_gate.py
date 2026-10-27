"""Select only a byte-bound, offline-qualified Codex tool-gate runtime.

The installed desktop CLI and its configuration are not changed. The trusted
host selects a receipt; worker/model content cannot choose an executable.
"""
import hashlib
import json
import os
from pathlib import Path
from .runtime_outcomes import Hold
from .tool_authority import CONTRACT

UPSTREAM_REVISION = '740e5af33c71225640e0c1c1555c514c2c93ab74'
PATCH_SHA256 = '84fe22a0870fb03bcd67430a2e319de0cce5f8ca5ac0fc06439de514c33c33d9'
REQUIRED_CHECKS = frozenset(('missing_authority', 'mismatched_authority',
    'closed_surface', 'denied_native_effects', 'dynamic_dispatch',
    'name_collision', 'hosted_scope', 'restart', 'no_credentials', 'model_override', 'standalone_search'))


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def selected(receipt_path=None):
    from task_relay.relay_paths import PATHS
    path=Path(receipt_path) if receipt_path is not None else Path(os.environ.get('TASK_RELAY_CODEX_GATE_RECEIPT',str(PATHS.data/'codex-runtime/qualified.json')))
    try:
        if not path.is_absolute():raise ValueError('Receipt path must be absolute')
        receipt=json.loads(path.read_text())
        binary=Path(receipt['executable']);proof_path=Path(receipt['qualification'])
        if not binary.is_absolute() or not proof_path.is_absolute():raise ValueError('Runtime paths must be absolute')
        evidence=digest(proof_path);proof=json.loads(proof_path.read_text())
        if (receipt['version']!=1 or receipt['contract']!=CONTRACT
                or receipt['upstream_revision']!=UPSTREAM_REVISION or receipt['patch_sha256']!=PATCH_SHA256
                or receipt['qualification_sha256']!=evidence or proof['contract']!=CONTRACT
                or proof['passed'] is not True or proof['patch_sha256']!=PATCH_SHA256
                or set(proof['checks'])!=REQUIRED_CHECKS or any(value is not True for value in proof['checks'].values())
                or digest(binary)!=receipt['executable_sha256'] or proof['executable_sha256']!=receipt['executable_sha256']):
            raise ValueError('Changed or incomplete runtime qualification')
        return dict(executable=str(binary),executable_sha256=receipt['executable_sha256'],
                    tool_gate=dict(contract=CONTRACT,qualified=True,pre_execution=True,evidence_sha256=evidence),
                    gate_receipt=str(path),gate_receipt_sha256=digest(path))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise Hold('tool_boundary_unqualified','Codex requires an exact offline-qualified pre-execution gate: '+str(exc)) from exc
