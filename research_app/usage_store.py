"""Investigation settings and provider-reported usage."""
import os
from uuid import uuid4

from research_app.investigation_tasks import connection, read_connection


def settings(actor):
    with read_connection() as conn:
        row = conn.execute('SELECT search_provider, model_endpoint FROM research_usage_settings WHERE actor=%s', [actor]).fetchone()
    return row or {'search_provider': 'Exa', 'model_endpoint': os.environ.get('HR_RESEARCH_MODEL_ENDPOINT', '')}


def save_settings(actor, provider, endpoint):
    if provider not in ('Exa', 'Brave') or not endpoint.strip():
        raise ValueError('Choose a provider and enter a model endpoint.')
    with connection() as conn:
        conn.execute('''INSERT INTO research_usage_settings(actor,search_provider,model_endpoint) VALUES (%s,%s,%s)
            ON CONFLICT(actor) DO UPDATE SET search_provider=excluded.search_provider, model_endpoint=excluded.model_endpoint''',
            [actor, provider, endpoint.strip()])


def begin_call(investigation_id, kind, provider):
    call_id = str(uuid4())
    with connection() as conn:
        conn.execute('INSERT INTO research_usage_calls(id,investigation_id,kind,provider) VALUES (%s,%s,%s,%s)',
                     [call_id, investigation_id, kind, provider])
    return call_id


def finish_call(call_id, cost=None, usage=None):
    usage = usage or {}
    with connection() as conn:
        conn.execute('UPDATE research_usage_calls SET cost_usd=%s,input_tokens=%s,output_tokens=%s WHERE id=%s',
                     [cost, usage.get('prompt_tokens'), usage.get('completion_tokens'), call_id])


def runs(actor, days):
    with read_connection() as conn:
        return conn.execute('''SELECT t.id,t.query,t.created_at,t.status,t.search_provider,t.model_endpoint,
            count(c.id) FILTER (WHERE c.kind='search' AND c.provider='Exa') AS calls,
            count(c.cost_usd) FILTER (WHERE c.kind='search' AND c.provider='Exa') AS priced_calls,
            sum(c.cost_usd) FILTER (WHERE c.kind='search' AND c.provider='Exa') AS cost,
            count(c.id) FILTER (WHERE c.kind='model') AS model_calls,
            count(c.id) FILTER (WHERE c.kind='model' AND c.provider=t.model_endpoint AND c.input_tokens IS NOT NULL AND c.output_tokens IS NOT NULL) AS metered_calls,
            sum(c.input_tokens) FILTER (WHERE c.kind='model' AND c.provider=t.model_endpoint AND c.input_tokens IS NOT NULL AND c.output_tokens IS NOT NULL) AS input_tokens,
            sum(c.output_tokens) FILTER (WHERE c.kind='model' AND c.provider=t.model_endpoint AND c.input_tokens IS NOT NULL AND c.output_tokens IS NOT NULL) AS output_tokens
            FROM investigation_tasks t LEFT JOIN research_usage_calls c ON c.investigation_id=t.id
            WHERE t.actor=%s AND t.created_at >= current_date - ((%s - 1) * interval '1 day')
            GROUP BY t.id ORDER BY t.created_at DESC''', [actor, days]).fetchall()



def model_prices(actor):
    with read_connection() as conn:
        rows = conn.execute('SELECT endpoint, input_price, output_price FROM research_model_prices WHERE actor=%s', [actor]).fetchall()
    return {row['endpoint']: row for row in rows}


def save_model_price(actor, endpoint, input_price, output_price):
    from decimal import Decimal, InvalidOperation
    try:
        rates = [Decimal(str(value)) for value in (input_price, output_price)]
        if not all(rate.is_finite() and rate >= 0 for rate in rates):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError('Enter valid nonnegative prices.')
    if not endpoint.strip():
        raise ValueError('Enter a model endpoint.')
    with connection() as conn:
        conn.execute('''INSERT INTO research_model_prices(actor, endpoint, input_price, output_price)
            VALUES (%s,%s,%s,%s) ON CONFLICT(actor,endpoint) DO UPDATE
            SET input_price=excluded.input_price, output_price=excluded.output_price''',
            [actor, endpoint.strip(), *rates])
