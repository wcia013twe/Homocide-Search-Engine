"""Run the current app locally with its deployed Databricks resource bindings."""
import base64
import os
from pathlib import Path
import subprocess
import sys

import yaml
from databricks.sdk import WorkspaceClient


def configure():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ['PATH'] = str(Path.home() / '.local/bin') + os.pathsep + os.environ['PATH']
    os.environ.setdefault('DATABRICKS_CONFIG_PROFILE', 'pc')
    client = WorkspaceClient()
    app = client.apps.get('homocide-ai-research')
    resources = {item.name: item for item in app.resources}
    for item in yaml.safe_load((root / 'app.yaml').read_text())['env']:
        if 'value' in item:
            os.environ[item['name']] = str(item['value'])
            continue
        resource = resources[item['valueFrom']]
        if resource.secret:
            secret = client.secrets.get_secret(scope=resource.secret.scope, key=resource.secret.key)
            value = base64.b64decode(secret.value, validate=True).decode()
        elif resource.job:
            value = resource.job.id
        elif resource.sql_warehouse:
            value = resource.sql_warehouse.id
        elif resource.serving_endpoint:
            value = resource.serving_endpoint.name
        else:
            raise ValueError('Unsupported local resource: ' + resource.name)
        os.environ[item['name']] = str(value)
    os.environ['HR_REQUIRE_PROXY_IDENTITY'] = 'false'
    os.environ['HR_DATA_DIR'] = str(root / 'local-audit/ui-testing')
    os.environ['PGUSER'] = client.current_user.me().user_name
    return client


if __name__ == '__main__':
    configure()
    print('Local app uses shared Databricks research data: http://localhost:8501', flush=True)
    subprocess.run([sys.executable, '-m', 'streamlit', 'run', 'app.py',
                    '--server.address', '127.0.0.1', '--server.port', '8501'], check=True)
