import base64
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


class WorkerEntrypointTests(unittest.TestCase):
    def test_nonsecret_job_arguments_and_provider_secret_loading(self):
        spec = importlib.util.spec_from_file_location('worker_entry', Path(__file__).resolve().parents[1] / 'hosting/run_worker.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        client = Mock()
        client.secrets.get_secret.return_value.value = base64.b64encode(b'test-provider-value').decode()
        with patch.dict(os.environ, {}, clear=True):
            module.configure(['--lakebase-endpoint','projects/p/branches/b/endpoints/e', '--db-host','host',
                              '--db-name','db', '--db-user','worker-role', '--audit-volume','/Volumes/c/s/v',
                              '--warehouse-id','warehouse', '--model-endpoint','model'], client)
            self.assertEqual(os.environ['HR_LAKEBASE_ENDPOINT'], 'projects/p/branches/b/endpoints/e')
            self.assertEqual(os.environ['PGUSER'], 'worker-role')
            self.assertEqual(os.environ['EXA_API_KEY'], 'test-provider-value')
            self.assertNotIn('HR_RESEARCH_CHECKPOINT_DSN', os.environ)
        self.assertEqual(client.secrets.get_secret.call_count, 2)

    def test_databricks_execution_without_file_global(self):
        script = Path(__file__).resolve().parents[1] / 'hosting/run_worker.py'
        namespace = {'__name__': 'databricks_task'}
        with patch('sys.argv', [str(script)]), patch('sys.path', []):
            exec(compile(script.read_text(), str(script), 'exec'), namespace)
        self.assertTrue(callable(namespace['configure']))
