"""Visible backend activity and timing from durable command timestamps."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st


STAGES = {
    'start': 'Starting investigation', 'resume': 'Resuming investigation',
    'finalize': 'Completing investigation', 'validate_seed': 'Preparing search',
    'discover': 'Searching for sources', 'inspect_results': 'Assessing search results',
    'fill_profile': 'Collecting and coding evidence', 'collecting_sources': 'Collecting source text',
    'extracting_claims': 'Extracting facts from sources', 'validating_claims': 'Checking facts against source passages',
    'review_next': 'Preparing search review', 'prepare_coding': 'AI coding evidence',
    'final_coding': 'Preparing findings for case Review',
}


def duration(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m {seconds:02d}s' if hours else f'{minutes}m {seconds:02d}s'


def timing_text(task, now=None):
    created = task.get('created_at')
    if not created:
        return ''
    now = now or datetime.now(timezone.utc)
    active = task['status'] in ('queued', 'running')
    end = now if active else task.get('last_finished_at') or now
    parts = ['Total elapsed ' + duration((end - created).total_seconds())]
    if 'worker_seconds' in task:
        parts += ['Worker ' + duration(task['worker_seconds']), 'Queue ' + duration(task['queue_seconds'])]
    if task.get('first_review_at'):
        parts.append('First review ready in ' + duration((task['first_review_at'] - created).total_seconds()))
    return ' · '.join(parts)


def submitted_text(task):
    created = task.get('created_at')
    if not created:
        return ''
    local = created.astimezone(ZoneInfo('America/New_York'))
    label = 'Linked' if task.get('status') == 'saved' else 'Submitted'
    return f"{label} {local.strftime('%b %d, %Y at %I:%M:%S %p %Z')}"


def render_activity(task, compact=False):
    status = task['status']
    label = ('Waiting for a worker to start' if status == 'queued' else
             STAGES.get(task.get('stage'), 'Investigating') if status == 'running' else
             'Ready for your review' if status == 'awaiting_review' else
             'Investigation complete' if status == 'finished' else 'Investigation ' + status)
    if compact:
        st.markdown(f'**{label}**')
        text = submitted_text(task)
        if text:
            st.caption(text)
        if task.get('heartbeat_at'):
            updated = task['heartbeat_at'].astimezone(ZoneInfo('America/New_York'))
            st.caption('Last worker update: ' + updated.strftime('%b %d at %I:%M:%S %p %Z'))
        if status == 'queued':
            st.caption('Starting a worker can take tens of seconds; busy workers add queue time. This view updates every 2 seconds.')
        elif status == 'running':
            st.caption('Progress updates automatically. Fields appear after a source batch has been extracted and checked.')
        return
    box = st.status(label, state='running' if status in ('queued', 'running') else
                    'error' if status in ('failed', 'interrupted') else 'complete', expanded=True)
    if status == 'queued':
        box.caption('Your investigation is saved. Starting a worker can take tens of seconds; busy workers add queue time. This view updates every 2 seconds.')
    elif status == 'running':
        box.caption('Progress updates automatically. Fields appear after a source batch has been extracted and checked.')
    text = submitted_text(task)
    if text:
        box.caption(text)
