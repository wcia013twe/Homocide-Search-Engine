"""One compact field/value/source presentation for every evidence entry point."""
import streamlit as st

from research_app.evidence_groups import group_field_sources
from research_app.gold_fields import GOLD_FIELDS


def render_fields(fields, sources, mode='live', key='evidence', compact=False, decisions=None):
    names = list(dict.fromkeys([*GOLD_FIELDS, *fields]))
    if decisions is not None:
        return _render_fields(names, fields, sources, mode, key, compact, decisions)
    populated = [name for name in names if fields.get(name)]
    missing = [name for name in names if name not in populated]
    if populated:
        _render_fields(populated, fields, sources, mode, key, compact)
    else:
        st.caption('No coded findings yet. Fields appear as evidence is reviewed.')
    if missing:
        with st.expander(f'Uncoded fields ({len(missing)})'):
            _render_fields(missing, fields, sources, mode, key, compact)


def _render_fields(names, fields, sources, mode, key, compact, decisions=None):
    choices = {}
    for name in names:
        field = fields.get(name, {})
        if not isinstance(field, dict):
            field = {'value': field}
        left, right = st.columns([2, 3])
        left.write(name.replace('_', ' · '))
        with right:
            groups = group_field_sources(field.get('claims', []), sources, field.get('claim_ids', []))
            editable = decisions is not None and name in GOLD_FIELDS and name != 'case_id'
            if not editable:
                st.write(field.get('value') if field.get('value') is not None else 'Not coded')
                if mode == 'live' or not compact or field.get('status') or field.get('value') is not None:
                    st.caption(('Conflicting' if _has_conflict(groups) else 'Supported' if groups else 'Missing or unclear')
                               if mode == 'live' else field.get('status') or 'Published')
            if field.get('reason'):
                st.caption(field['reason'])
            if editable:
                choices[name] = _review_choice(name, groups, decisions.get(name), key)
            if _has_conflict(groups):
                st.caption('Conflicting reported values retained')
            for index, group in enumerate(groups):
                subject = group['subject_id'].replace('_', ' ')
                st.write(f"{group['value']} · {subject}")
                st.caption(f"{group['source_count']} distinct source{'s' if group['source_count'] != 1 else ''}")
                for source in group['sources']:
                    metadata = source['source'] or {}
                    label = metadata.get('title') or metadata.get('url') or source['source_id']
                    with st.popover(('Selected · ' if source['selected'] else '') + label,
                                    key=f"{key}:{name}:{index}:{source['document_id']}"):
                        if metadata.get('url'):
                            st.write(metadata['url'])
                        for claim in source['claims']:
                            capture = source['captures'].get(claim['source_id']) or {}
                            st.caption(capture.get('evidence_kind', 'Evidence capture'))
                            if claim.get('inferred'):
                                st.caption('Inferred from the following passage')
                            st.text(claim.get('passage') or 'Supporting passage unavailable')
                            locator = claim.get('locator')
                            if locator:
                                st.caption(f"Locator: {locator}")
                            st.caption('Claim: ' + claim['claim_id'])
                        if not source['source']:
                            st.caption('Source metadata unavailable; saved claim retained.')
            if not groups and field.get('evidence'):
                st.caption('Checked sources')
                for source_id in field['evidence']:
                    source = sources.get(source_id, {})
                    with st.popover(source.get('title') or source.get('url') or source_id, key=f'{key}:{name}:checked:{source_id}'):
                        st.caption('Checked source · no selected supporting claim')
                        st.write(source.get('url', ''))
                        st.text(source.get('text') or source.get('snippet') or 'Saved capture is available in the document artifact.')
        if not compact:
            st.divider()
    return choices


def _has_conflict(groups):
    from research_app.coding_review import _value_key
    subjects: dict[str, set[str]] = {}
    for group in groups:
        subjects.setdefault(group['subject_id'], set()).add(_value_key(group['value']))
    return any(len(values) > 1 for values in subjects.values())


def _review_choice(name, groups, saved, key):
    from research_app.coding_review import _value_key
    options, labels = [], []
    for group in groups:
        claims = [claim for source in group['sources'] for claim in source['claims']]
        options.append({'value': group['value'], 'status': 'Reported',
                        'claim_ids': [claim['claim_id'] for claim in claims],
                        'source_ids': list(dict.fromkeys(claim['source_id'] for claim in claims))})
        labels.append(str(group['value']) + ' · ' + group['subject_id'].replace('_', ' '))
    if not groups:
        options.append({'value': None, 'status': 'Not Reported', 'claim_ids': [], 'source_ids': []})
        labels.append('Not Reported')
    options.append({'value': None, 'status': 'Unclear', 'claim_ids': [], 'source_ids': []})
    labels.append('Unclear')
    index = None
    if saved:
        index = next((i for i, option in enumerate(options) if option['status'] == saved['status']
                      and _value_key(option['value']) == _value_key(saved.get('value'))), None)
    elif len(groups) == 1:
        index = 0
    selected = st.radio('Choose a value' if groups else 'Evidence status', range(len(options)),
                        format_func=lambda i: labels[i], index=index, key=f'{key}:choice:{name}')
    if selected is None:
        return None
    choice = options[selected]
    # Reopening a review keeps the saved evidence selection as well as its value.
    if saved and index == selected:
        choice = {**choice, 'claim_ids': list(saved.get('claim_ids', [])),
                  'source_ids': list(saved.get('source_ids', saved.get('evidence', [])))}
    return choice
