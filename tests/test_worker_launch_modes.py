"""Exercise real worker loops with script identity, not only package imports."""
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch
from orchestrator import gemini_worker
from tests import test_job_owner_loop as owner, test_shared_code_workers as code


class Tests(unittest.TestCase):
    def run_scenario(self,module,name):
        # The installed supervisor invokes the file path. run_path gives the
        # same empty package identity while allowing a scripted provider/client.
        namespace=runpy.run_path(str(Path(gemini_worker.__file__)))
        self.assertFalse(namespace['__package__'])
        result=unittest.TestResult()
        with patch.object(module,'execute',namespace['execute']):
            module.Tests(name).run(result)
        self.assertTrue(result.wasSuccessful(),str(result.errors+result.failures))

    def test_owner_context_through_script_identity(self):
        self.run_scenario(owner,'test_owner_discovers_registered_input_content_without_ungranted_adapter_probes')

    def test_all_provider_code_outputs_through_script_identity(self):
        self.run_scenario(code,'test_every_provider_can_export_binary_via_qualified_python')
