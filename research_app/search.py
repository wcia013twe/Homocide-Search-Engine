"""Live web search."""

import requests
import streamlit as st

from research_app.providers import PROVIDERS, search_web
from research_app.explore_search import extract_leads, lead_extractor
from research_app.search_audit import AuditConfigurationError, SearchAuditStore
def scoped_query(query: str, state: str = "", county: str = "", year: int | None = None) -> str:
    county = county.strip()
    if county and not county.lower().endswith(" county"):
        county += " County"
    parts = (query.strip(), county, state.strip(), str(year) if year is not None else "")
    return " ".join(part for part in parts if part)


def render(workspace: dict, save):
    st.title("Search")
    st.caption("Discover sources on the web.")
    provider = st.selectbox("Provider", list(PROVIDERS), key="search_live_provider")
    live_query = st.text_input("Search the web", placeholder="Homicide research methods", key="search_live_query")
    state_column, county_column, year_column = st.columns(3)
    state = state_column.text_input("State (optional)", placeholder="Texas", key="search_live_state")
    county = county_column.text_input("County (optional)", placeholder="Brazos", key="search_live_county")
    year = year_column.number_input("Incident year (optional)", min_value=1800, max_value=2100,
                                    value=None, step=1, placeholder="2023", key="search_live_year")
    query = scoped_query(live_query, state, county, year)
    st.caption("Filters add search terms. Results may include other locations or years; incident dates need checking.")
    if live_query.strip() and (state.strip() or county.strip() or year is not None):
        st.text(f"Search query: {query}")
    mode = st.radio("Search mode", ["Search web", "explore-search"], horizontal=True, key="search_live_mode")
    if mode == "explore-search":
        st.caption("Find and save individual identifying details with their source excerpts. One useful detail is enough; the incident loop has not started.")
    if st.button(mode, type="primary", disabled=not live_query.strip(), key="search_live_submit"):
        st.session_state.pop("search_live_lead_notice", None)
        try:
            extractor = lead_extractor() if mode == "explore-search" else None
            with st.spinner(f"Searching {provider}..."):
                response = search_web(provider, query)
            st.session_state["search_live_results"] = response
            record = None
            try:
                record = SearchAuditStore.from_environment().record(response, st.session_state["research_user"])
                st.session_state["search_live_audit"] = f"Recorded search {record.search_run_id}."
            except AuditConfigurationError:
                st.session_state["search_live_audit"] = "Configure the audit volume and SQL warehouse to record this search."
            except Exception:
                st.session_state["search_live_audit"] = "Search succeeded, but the audit record could not be written."
            if extractor is not None:
                with st.spinner("Finding identifying details..."):
                    leads = extract_leads(response, extractor, record.search_run_id if record else None)
                existing = workspace.get("leads", [])
                known = {lead["id"] for lead in existing}
                new_leads = [lead for lead in leads if lead["id"] not in known]
                if new_leads:
                    workspace["leads"] = existing + new_leads
                    if not save():
                        return
                st.session_state["search_live_lead_notice"] = (
                    f"Saved {len(new_leads)} new identifying leads. Incident loop has not started."
                    if leads else "No useful identifying details were found in these excerpts. Try another query."
                )
        except requests.RequestException:
            st.error(f"{provider} Search could not complete the request. Try again shortly.")
        except RuntimeError as exc:
            st.error(str(exc))
        except Exception:
            st.error("Search or lead extraction could not finish. Check the provider and model configuration, then try again.")
    if st.session_state.get("search_live_audit"):
        st.caption(st.session_state["search_live_audit"])
    if st.session_state.get("search_live_lead_notice"):
        st.info(st.session_state["search_live_lead_notice"])
    saved_leads = workspace.get("leads", [])
    if saved_leads:
        with st.expander(f"Saved identifying leads ({len(saved_leads)})"):
            st.caption("Provisional details for follow-up searches. Multiple details can refer to the same incident.")
            for lead in saved_leads:
                st.write(lead["identifying_detail"])
                st.caption(f'{lead["detail_type"]} | {lead["status"]} | Search: {lead["search_query"]}')
                st.text(lead["supporting_excerpt"])
                st.link_button("Open supporting source", lead["source_url"])
    live_response = st.session_state.get("search_live_results")
    for result in live_response.results if live_response else []:
        with st.container(border=True):
            st.subheader(result.title)
            if result.published_date:
                st.caption(result.published_date)
            st.write(result.snippet or "No excerpt was returned.")
            if result.url.startswith(("https://", "http://")):
                st.link_button("Open result", result.url)
