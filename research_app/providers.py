"""Search-provider registry used by Discovery."""
from research_app.brave import brave_response
from research_app.exa import exa_search
from research_app.search_provider import SearchResponse


PROVIDERS = {"Exa": exa_search, "Brave": brave_response}


def search_web(provider: str, query: str) -> SearchResponse:
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported search provider: {provider}")
    return PROVIDERS[provider](query)
