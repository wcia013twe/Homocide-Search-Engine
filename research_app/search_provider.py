"""Common shape for web-search providers."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_date: str | None = None
    author: str | None = None
    highlights: tuple[str, ...] = ()
    provider_result_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class SearchResponse:
    provider: str
    query: str
    request: dict[str, Any]
    raw_response: dict[str, Any]
    results: tuple[SearchResult, ...]
    provider_request_id: str | None = None
    cost_usd: float | None = None
    provider_search_time_ms: int | None = None
    warnings: tuple[Any, ...] = ()
    notices: tuple[Any, ...] = ()
