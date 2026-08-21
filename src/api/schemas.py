"""Request/response models for the REST surface (CLAUDE.md, section 8)."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


def _max_query_length(raw: str | None) -> int:
    return int(raw) if raw else 2000


# Bounds embedding + LLM cost per request. Overridable via MAX_QUERY_LENGTH -
# read once at import time, matching how Lambda env vars are fixed for the
# life of the execution environment.
MAX_QUERY_LENGTH = _max_query_length(os.environ.get("MAX_QUERY_LENGTH"))


class QueryRequest(BaseModel):
    query: str = Field(max_length=MAX_QUERY_LENGTH)
    layers: list[str] | None = None


class QueryResponse(BaseModel):
    summary: str
    intent: str
    data: object
    confidence: str
    coverage_note: str | None
    execution_time_ms: int


class ImpactRequest(BaseModel):
    project: str
    interface: str


class ImpactedProjectResponse(BaseModel):
    name: str
    repo_url: str | None
    distance: int


class ImpactResponse(BaseModel):
    project_found: bool
    interface_declared: bool
    interface_source: str | None
    provider_manifest_missing: bool
    impacted: list[ImpactedProjectResponse]
