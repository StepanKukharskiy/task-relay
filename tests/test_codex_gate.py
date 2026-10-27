"""Byte binding and authority projection; no CLI/model/network calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from orchestrator import codex_gate
from orchestrator.runtime_outcomes import Hold
from orchestrator.tool_authority import CONTRACT, manifest, require_relay_dispatch
from orchestrator.workers import atomic


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.binary=self.root/'binary';self.binary.write_bytes(b'offline nonexecutable fixture')
        self.proof=self.root/'proof.json';self.receipt=self.root/'qualified.json'
        self.evidence=dict(contract=CONTRACT,passed=True,patch_sha256=codex_gate.PATCH_SHA256,
            executable_sha256=codex_gate.digest(self.binary),checks={key:True for key in codex_gate.REQUIRED_CHECKS})
        self.binding=dict(version=1,contract=CONTRACT,upstream_revision=codex_gate.UPSTREAM_REVISION,
            patch_sha256=codex_gate.PATCH_SHA256,executable=str(self.binary),executable_sha256=codex_gate.digest(self.binary),qualification=str(self.proof))
        self.save()
        self.addCleanup(patch.stopall)
        patch.dict('os.environ',{'TASK_RELAY_CODEX_GATE_RECEIPT':str(self.receipt)}).start()

    def save(self):
        atomic(self.proof,self.evidence)
        self.binding['qualification_sha256']=codex_gate.digest(self.proof)
        atomic(self.receipt,self.binding)

    def test_exact_qualification_allows_transport_but_rebuilt_binary_requires_requalification(self):
        selected=codex_gate.selected()
        require_relay_dispatch('provider',selected['tool_gate'])
        self.binary.write_bytes(b'different build')
        with self.assertRaises(Hold):codex_gate.selected()

    def test_missing_failed_and_changed_qualification_cannot_be_promoted(self):
        original=copy.deepcopy(self.evidence)
        for update in (dict(passed=False),dict(patch_sha256='f'*64),dict(checks={})):
            self.evidence={**original,**update};self.save()
            with self.assertRaises(Hold):codex_gate.selected()
        self.evidence=original;self.save();self.proof.write_text('{}')
        with self.assertRaises(Hold):codex_gate.selected()

    def test_node_setup_selects_only_verified_receipt_without_running_binary(self):
        from types import SimpleNamespace
        from task_relay import desktop_node_setup as setup
        from unittest.mock import patch
        destination=self.root.resolve()/'selected'
        with patch.object(setup,'PATHS',SimpleNamespace(data=destination)):
            setup.configure_codex({'path':str(self.receipt)})
            self.assertEqual(codex_gate.selected(destination/'codex-runtime/qualified.json')['executable_sha256'],self.binding['executable_sha256'])
            previous=(destination/'codex-runtime/qualified.json').read_bytes()
            self.binary.write_bytes(b'changed')
            with self.assertRaises(Hold):setup.configure_codex({'path':str(self.receipt)})
            self.assertEqual((destination/'codex-runtime/qualified.json').read_bytes(),previous)

    def test_adapter_projects_only_exact_declarations_and_explicit_hosted_scope(self):
        self.assertEqual(manifest([dict(name='finish'),dict(name='read')]),dict(version=1,dynamic_tools=['finish','read'],hosted_tools=[]))
        self.assertEqual(manifest([],hosted_tools=['web_search']),dict(version=1,dynamic_tools=[],hosted_tools=['web_search']))
        with self.assertRaises(ValueError):manifest([dict(name='read'),dict(name='read')])
        with self.assertRaises(ValueError):manifest([dict(name='web_search')],hosted_tools=['web_search'])
        with self.assertRaises(Hold):require_relay_dispatch('provider',dict(qualified=True))


if __name__=='__main__':unittest.main()
