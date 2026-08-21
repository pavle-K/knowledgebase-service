"""Request/response models for the REST surface (CLAUDE.md, section 8)."""

from __future__ import annotations

from pydantic import BaseModel, Field

# Bounds embedding + LLM cost per request - a natural-language question has no
# legitimate reason to be longer than this.
MAX_QUERY_LENGTH = 2000


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
