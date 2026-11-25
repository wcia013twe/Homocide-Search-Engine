"""Pure evidence grouping shared by live, review, and published views."""
from copy import deepcopy

from research_app.coding_review import _value_key, normalized_value


def group_field_sources(claims, sources, selected_claim_ids=()):
    """Group exact values by subject; count documents, retaining every capture."""
    selected = set(selected_claim_ids)
    groups = {}
    for claim in claims:
        value, source_id = claim['value'], claim['source_id']
        source_record = sources.get(source_id)
        document_id = source_identity(source_id, source_record or {})
        key = (claim.get('subject_id', 'incident'), _value_key(normalized_value(value)))
        group = groups.setdefault(key, {'value': value, 'subject_id': key[0], 'sources': {}})
        source = group['sources'].setdefault(document_id, {
            'source_id': source_id, 'document_id': document_id, 'source': source_record,
            'claims': [], 'selected': False, 'captures': {},
        })
        source['captures'][source_id] = source_record
        source['claims'].append(claim)
        source['selected'] = source['selected'] or claim['claim_id'] in selected
    return [dict(value=group['value'], subject_id=group['subject_id'],
                 sources=list(group['sources'].values()), source_count=len(group['sources']))
            for group in groups.values()]


def state_evidence(state, investigation_id=None):
    """Project a checkpoint to gold fields without losing original claims."""
    from research_app.gold_fields import gold_field
    fields, sources = {}, deepcopy(state.get('sources', {}))
    prefix = investigation_id + ':' if investigation_id else ''
    if prefix:
        sources = {prefix + key: value for key, value in sources.items()}
    profile = state.get('profile', {})
    coded = state.get('coded_fields', {})
    for original in dict.fromkeys([*profile, *coded]):
        item = deepcopy(coded.get(original) or profile.get(original) or {})
        if not isinstance(item, dict):
            item = {'value': item}
        claims = deepcopy(profile.get(original, {}).get('claims', []) if isinstance(profile.get(original), dict) else [])
        claims.extend(c for c in item.get('claims', []) if c not in claims)
        if item.get('inferred'):
            # Keep the original claim intact while making its inference available
            # to case review and its existing evidence validation.
            for support in item.get('supporting_claims', []):
                claims.append({**deepcopy(support), 'claim_id': 'inferred:' + original + ':' + support['claim_id'],
                               'value': item['value'], 'inferred': True,
                               'supporting_claim_id': support['claim_id'], 'supporting_value': support['value']})
        name = gold_field(original) or original
        target = fields.setdefault(name, {'claims': [], 'claim_ids': [], 'value': item.get('value'),
                                          'status': item.get('status', 'Not yet coded')})
        for claim in claims:
            claim['claim_id'] = prefix + claim['claim_id']
            claim['source_id'] = prefix + claim['source_id']
            claim.setdefault('original_field', original)
            target['claims'].append(claim)
        target['claim_ids'].extend(prefix + key for key in item.get('claim_ids', []))
        if item.get('reason'):
            target['reason'] = item['reason']
        values = {_value_key(normalized_value(c['value'])) for c in target['claims']}
        if len(values) > 1:
            target['conflicting'] = True
    relocated = []
    for original, item in fields.items():
        retained = []
        for claim in item['claims']:
            assigned = claim.get('assigned_field', original)
            destination = (gold_field(assigned) or assigned) if assigned else 'Unassigned findings'
            if destination != original:
                relocated.append((destination, claim))
            else:
                retained.append(claim)
        if item['claims'] and not retained:
            item['value'], item['status'] = None, 'Reassigned'
        item['claims'] = retained
    for destination, claim in relocated:
        fields.setdefault(destination, {'claims': [], 'claim_ids': [], 'value': None})['claims'].append(claim)
    return fields, sources


def case_evidence(links, decisions=None):
    """Build one case projection from saved investigation snapshots only."""
    fields, sources = {}, {}
    for link in links:
        projected, captured = state_evidence(link['snapshot'], link['investigation_id'])
        sources.update(captured)
        for name, item in projected.items():
            target = fields.setdefault(name, {'claims': [], 'claim_ids': [], 'value': None})
            target['claims'].extend(item.get('claims', []))
            target['claim_ids'].extend(item.get('claim_ids', []))
    all_claims = {claim['claim_id']: claim for item in fields.values() for claim in item.get('claims', [])}
    for name, decision in (decisions or {}).items():
        # Assignment changes relocate the evidence reference, never rewrite its original statement.
        assigned = set(decision.get('claim_ids', []))
        moved = [all_claims[key] for key in assigned if key in all_claims]
        for original, item in fields.items():
            if original != name:
                item['claims'] = [claim for claim in item.get('claims', []) if claim['claim_id'] not in assigned]
        target = fields.setdefault(name, {'claims': []})
        retained = target['claims']
        retained.extend(claim for claim in moved if claim not in retained)
        target.update(deepcopy(decision))
        target['claims'] = retained
    return fields, sources


def source_identity(source_id, source):
    from research_app.evidence_registry import canonical_url
    url = source.get('canonical_url') or source.get('url')
    return (source.get('document_id') or source.get('document_key')
            or (canonical_url(url) if url else source_id))


def deduplicate_sources(sources):
    """Keep all investigation captures under their existing document identity."""
    documents: dict = {}
    for source_id, source in sources.items():
        identity = source_identity(source_id, source)
        document = documents.setdefault(identity, {'document_id': identity, 'source': source, 'captures': {}})
        document['captures'][source_id] = source
    return list(documents.values())
