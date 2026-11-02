"""Exa Search API adapter."""
import os
from typing import Any

import requests

from research_app.search_provider import SearchResponse, SearchResult


def _cost(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("total")
    return float(value) if isinstance(value, (int, float)) else None


def exa_search(query: str, max_results: int = 10) -> SearchResponse:
    """Search the general web so agency and university pages remain discoverable."""
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise RuntimeError("Exa Search is not configured for this app.")
    request = {
        "query": query,
        "numResults": max_results,
        "contents": {"highlights": True},
    }
    response = requests.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        json=request,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    results = []
    for result in payload.get("results", []):
        highlights = tuple(item for item in result.get("highlights", []) if isinstance(item, str))
        results.append(
            SearchResult(
                title=result.get("title") or "Untitled result",
                url=result.get("url") or "",
                snippet="\n\n".join(highlights) or result.get("summary") or "",
                published_date=result.get("publishedDate"),
                author=result.get("author"),
                highlights=highlights,
                provider_result_id=result.get("id"),
                raw=result,
            )
        )
    return SearchResponse(
        provider="exa",
        query=query,
        request=request,
        raw_response=payload,
        results=tuple(results),
        provider_request_id=payload.get("requestId"),
        cost_usd=_cost(payload.get("costDollars")),
        provider_search_time_ms=payload.get("searchTime"),
        warnings=tuple(payload.get("warnings", [])),
        notices=tuple(payload.get("notices", [])),
    )
