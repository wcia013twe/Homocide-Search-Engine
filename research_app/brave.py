"""Minimal Brave Search API client."""
import os

import requests

from research_app.search_provider import SearchResponse, SearchResult


def brave_response(query: str, max_results: int = 10) -> SearchResponse:
    """Search Brave and return the shared discovery result shape."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        raise RuntimeError("Brave Search is not configured for this app.")
    request = {"q": query, "count": max_results}
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": api_key},
        params=request,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    results = tuple(
        SearchResult(
            title=result.get("title") or "Untitled result",
            url=result.get("url") or "",
            snippet=result.get("description") or "",
            published_date=result.get("page_age"),
            raw=result,
        )
        for result in payload.get("web", {}).get("results", [])
    )
    return SearchResponse(
        provider="brave",
        query=query,
        request=request,
        raw_response=payload,
        results=results,
    )


def brave_search(query: str) -> list[dict]:
    """Backward-compatible display helper for existing callers."""
    return [
        {"title": result.title, "url": result.url, "description": result.snippet}
        for result in brave_response(query, max_results=3).results
    ]
