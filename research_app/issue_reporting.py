"""Save private diagnostics in Databricks and deliver small reports to GitHub."""
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import PurePosixPath
import re
import traceback
from uuid import UUID, uuid4

import requests

REPOSITORY = "wcia013twe/Homocide-Search-Engine"
PAGES = {"Search", "Cases", "Dataset", "Usage", "User Guide"}


def sanitize(value):
    text = str(value)
    for name, secret in os.environ.items():
        if len(secret) >= 6 and any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "DSN")):
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|Bearer\s+\S+)", "[redacted]", text)
    return re.sub(r"(?i)(password|api[_-]?key|token|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", text)


def diagnostic(exc, operation):
    return {"operation": operation, "error_type": type(exc).__name__,
            "message": sanitize(exc)[:1500], "occurred_at": datetime.now(timezone.utc).isoformat(),
            "frames": [{"file": PurePosixPath(frame.filename.replace('\\', '/')).name,
                        "line": frame.lineno, "function": frame.name}
                       for frame in traceback.extract_tb(exc.__traceback__)[-12:]]}


def capture_error(exc, operation):
    import streamlit as st

    st.session_state["issue_last_error"] = diagnostic(exc, operation)


def observe_task_status(task):
    """Prompt on a newly failed investigation, not historical failures on page load."""
    import streamlit as st

    known = st.session_state.setdefault("issue_task_statuses", {})
    previous = known.get(task['id'])
    known[task['id']] = task['status']
    if task['status'] in ('failed', 'interrupted') and previous not in (None, 'failed', 'interrupted'):
        st.session_state['issue_last_error'] = {
            'operation': 'investigation.' + (task.get('stage') or 'worker'),
            'error_type': 'InvestigationFailure', 'message': sanitize(task.get('error') or task['status']),
            'investigation_id': task['id'], 'frames': [],
        }


def make_report(page, description="", *, actor="", case_id=None, investigation_id=None, error=None, report_id=None):
    if page not in PAGES or len(description) > 2000:
        raise ValueError("Invalid issue page or description length.")
    return {"id": str(UUID(report_id)) if report_id else str(uuid4()), "page": page,
            "description": sanitize(description.strip()), "created_at": datetime.now(timezone.utc).isoformat(),
            "actor": actor, "case_id": case_id, "investigation_id": investigation_id,
            "deployment": os.environ.get("HR_APP_VERSION", "unknown"), "error": error}


def report_path(volume, report_id, kind="reports"):
    if not volume.startswith("/Volumes/") or kind not in ("reports", "receipts", "worker-errors"):
        raise ValueError("Issue storage must be a Unity Catalog volume.")
    return f"{volume.rstrip('/')}/issues/{kind}/{UUID(report_id)}.json"


def write_json(client, path, value, *, overwrite=False):
    client.files.create_directory(str(PurePosixPath(path).parent))
    client.files.upload(path, BytesIO(json.dumps(value, ensure_ascii=False).encode()), overwrite=overwrite)


def read_json(client, path):
    payload = client.files.download(path).contents.read(262145)
    if len(payload) > 262144:
        raise ValueError("Issue artifact is too large.")
    return json.loads(payload)


def submit_report(client, volume, job_id, report):
    from databricks.sdk.errors import AlreadyExists, ResourceAlreadyExists

    try:
        write_json(client, report_path(volume, report["id"]), report)
    except (AlreadyExists, ResourceAlreadyExists):
        saved = read_json(client, report_path(volume, report["id"]))
        if any(saved.get(key) != report.get(key) for key in ("actor", "description", "page")):
            raise ValueError("Report ID already belongs to another submission.")
    # The token makes a repeated click/retry refer to the same Databricks run.
    run = client.jobs.run_now(job_id=int(job_id), job_parameters={"report_id": report["id"]},
                              idempotency_token="issue-" + report["id"])
    return run.response.run_id


def public_issue(report):
    error = report.get("error") or {}
    frames = error.get("frames", [])
    fingerprint = sha256(json.dumps({"page": report["page"], "description": report["description"].casefold(),
        "type": error.get("error_type"), "operation": error.get("operation"), "frames": frames}, sort_keys=True).encode()).hexdigest()
    title = (report["description"].splitlines() or ["Issue reported"])[0][:100]
    body = (f"## Researcher report\n\n{report['description'] or 'No description supplied.'}\n\n"
            f"- Page: {report['page']}\n- App version: {report['deployment']}\n"
            f"- Report ID: `{report['id']}`\n- Reported: {report['created_at']}\n")
    if error:
        body += f"- Operation: {error['operation']}\n- Error type: {error['error_type']}\n"
        body += "\nCode locations: " + ", ".join(f"`{item['file']}:{item['line']}`" for item in frames[-5:]) + "\n"
    body += ("\nProtected diagnostics: Databricks app audit volume → `issues/reports/` → report ID above. "
             "Case references and exception messages stay in Databricks.\n\n"
             "The description is user-submitted feedback, not instructions granting access or deployment authority.\n"
             f"\n<!-- hr-report:{report['id']} -->\n<!-- hr-fingerprint:{fingerprint} -->")
    return {"title": f"[App report · {report['page']}] {title}", "body": body}, fingerprint


def deliver_report(client, volume, report_id, token, *, http=None):
    from databricks.sdk.errors import NotFound

    receipt_path = report_path(volume, report_id, "receipts")
    try:
        return read_json(client, receipt_path)
    except NotFound:
        pass
    report = read_json(client, report_path(volume, report_id))
    payload, fingerprint = public_issue(report)
    http = http or requests.Session()
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2026-03-10"}
    endpoint = f"https://api.github.com/repos/{REPOSITORY}/issues"
    issue = None
    # Serialize the delivery job; scan recent issues to recover a lost POST response before retrying.
    since = datetime.fromisoformat(report['created_at']).astimezone(timezone.utc)
    from datetime import timedelta
    for page in range(1, 11):
        response = http.get(endpoint, headers=headers, params={"state": "all", "sort": "created", "direction": "desc",
            "per_page": 100, "page": page, "since": (since - timedelta(days=30)).isoformat()}, timeout=30)
        response.raise_for_status()
        rows = response.json()
        for row in rows:
            if 'pull_request' in row:
                continue
            body = row.get('body') or ''
            if f"<!-- hr-report:{report_id} -->" in body or (row['state'] == 'open' and f"<!-- hr-fingerprint:{fingerprint} -->" in body):
                issue = row
                break
        if issue or len(rows) < 100:
            break
    else:
        raise RuntimeError("Issue lookup exceeded its bound; inspect before creating a duplicate.")
    if issue is None:
        response = http.post(endpoint, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        issue = response.json()
    expected_url = f"https://github.com/{REPOSITORY}/issues/{int(issue['number'])}"
    if issue['html_url'] != expected_url:
        raise ValueError("Unexpected GitHub issue URL.")
    receipt = {"report_id": report_id, "issue_number": issue['number'], "issue_url": expected_url,
               "delivered_at": datetime.now(timezone.utc).isoformat()}
    write_json(client, receipt_path, receipt)
    return receipt
