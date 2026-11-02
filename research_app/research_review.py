"""Explicit researcher response to a saved query proposal."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    search_run_id: str
    action: Literal["search", "stop"]
    query_index: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=1000)
