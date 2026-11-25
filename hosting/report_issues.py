"""Databricks job: deliver saved issue reports without opening the research database."""
import argparse
import base64
from pathlib import Path
import sys

sys.path.insert(0, str(Path(globals().get('__file__', sys.argv[0])).resolve().parents[1]))

from research_app.issue_reporting import deliver_report


def main():
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import NotFound

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--volume', required=True)
    parser.add_argument('--report-id', default='pending')
    parser.add_argument('--secret-scope', default='homicide-issue-reporting')
    args = parser.parse_args()
    client = WorkspaceClient()
    secret = client.secrets.get_secret(scope=args.secret_scope, key='GITHUB_ISSUES_TOKEN')
    token = base64.b64decode(secret.value, validate=True).decode()
    if args.report_id != 'pending':
        receipt = deliver_report(client, args.volume, args.report_id, token)
        print(receipt['issue_url'])
        return
    try:
        entries = client.files.list_directory_contents(args.volume.rstrip('/') + '/issues/reports')
        delivered = 0
        for entry in entries:
            if entry.is_directory or not entry.path.endswith('.json'):
                continue
            report_id = Path(entry.path).stem
            from research_app.issue_reporting import read_json, report_path
            try:
                read_json(client, report_path(args.volume, report_id, 'receipts'))
                continue
            except NotFound:
                pass
            print(deliver_report(client, args.volume, report_id, token)['issue_url'])
            delivered += 1
            if delivered >= 20:
                break
    except NotFound:
        return


if __name__ == '__main__':
    main()
