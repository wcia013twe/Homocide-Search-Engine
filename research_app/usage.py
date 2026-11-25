"""Settings and usage for the researcher's investigations."""
from decimal import Decimal

import streamlit as st
from research_app.issue_reporting import capture_error

from research_app.investigation_tasks import database_configured
from research_app import usage_store


def cost_label(rows):
    known = sum((row['cost'] or 0) for row in rows)
    incomplete = any(row['calls'] == 0 or row['priced_calls'] < row['calls'] for row in rows)
    if not any(row['priced_calls'] for row in rows):
        return 'Unavailable'
    return f'${known:.4f}' + (' (partial)' if incomplete else '')



def model_cost_label(row, prices):
    price = prices.get(row['model_endpoint'])
    if not price or not row['metered_calls']:
        return 'Unavailable'
    cost = (Decimal(row['input_tokens']) * price['input_price'] +
            Decimal(row['output_tokens']) * price['output_price']) / 1_000_000
    return f'${cost:.4f}' + (' (partial)' if row['metered_calls'] < row['model_calls'] else '')


def render(workspace: dict, save):
    st.title('Usage')
    if not database_configured():
        st.info('Live investigation usage is available when the shared database is connected.')
        return
    st.caption('Your investigations and estimated costs.')
    actor = st.session_state['research_user']
    try:
        config = usage_store.settings(actor)
        st.subheader('Settings')
        st.caption('These settings apply to your new investigations. Existing investigations keep their original settings.')
        with st.form('usage_settings'):
            provider = st.selectbox('Search provider', ['Exa', 'Brave'], index=['Exa', 'Brave'].index(config['search_provider']))
            endpoint = st.text_input('Model endpoint', value=config['model_endpoint'])
            if st.form_submit_button('Save settings'):
                if not endpoint.strip():
                    st.error('Enter a model endpoint.')
                else:
                    usage_store.save_settings(actor, provider, endpoint)
                    st.success('Settings saved for new investigations.')
        st.subheader('Model prices')
        st.caption('Set prices per million tokens for each endpoint. Current rates apply to all recorded usage, including older investigations.')
        prices = usage_store.model_prices(actor)
        price_endpoint = st.text_input('Endpoint for pricing', value=config['model_endpoint'])
        saved_price = prices.get(price_endpoint.strip(), {})
        with st.form('model_prices'):
            input_price = st.text_input('Input price per million tokens (USD)', value=str(saved_price.get('input_price', '')), key=f'input_price_{price_endpoint}')
            output_price = st.text_input('Output price per million tokens (USD)', value=str(saved_price.get('output_price', '')), key=f'output_price_{price_endpoint}')
            if st.form_submit_button('Save model prices'):
                try:
                    usage_store.save_model_price(actor, price_endpoint, input_price, output_price)
                    prices = usage_store.model_prices(actor)
                    st.success('Model prices saved.')
                except ValueError as exc:
                    st.error(str(exc))
        st.subheader('Investigations')
        days = st.selectbox('Period', [30, 7, 90, 365], format_func=lambda value: f'Last {value} days')
        rows = usage_store.runs(actor, days)
        completed = [row for row in rows if row['status'] in ('awaiting_review', 'finished', 'failed', 'interrupted')]
        successes = sum(row['status'] in ('awaiting_review', 'finished') for row in completed)
        a, b, c = st.columns(3)
        a.metric('Exa search estimate', cost_label([row for row in rows if row['search_provider'] == 'Exa']))
        b.metric('Investigations', len(rows))
        c.metric('Success rate', f'{successes / len(completed):.0%}' if completed else 'Unavailable')
        st.caption('Success means reached review or finished. In-progress investigations are excluded. Exa costs are provider estimates and may be partial; older investigations may have no recorded costs.')
        if rows:
            st.dataframe([{'Started': row['created_at'], 'Investigation': row['query'], 'Status': row['status'].replace('_', ' ').title(),
                           'Provider': row['search_provider'] or 'Unavailable', 'Model endpoint': row['model_endpoint'] or 'Unavailable',
                           'Exa search estimate': cost_label([row]) if row['search_provider'] == 'Exa' else 'Unavailable',
                           'Model estimate': model_cost_label(row, prices)} for row in rows], hide_index=True, width='stretch')
        else:
            st.write('No investigations in this period.')
        st.caption('Model estimates use recorded tokens and your current endpoint prices. Missing usage or prices makes estimates unavailable or partial. These are not invoice amounts.')
    except Exception as issue_exc:
        capture_error(issue_exc, "usage.render")
        st.error('Investigation usage is temporarily unavailable. Check the database setup and try again.')
