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


class SearchRequest(BaseModel):
    query: str = Field(max_length=MAX_QUERY_LENGTH)
    project: str | None = None
    limit: int = 5


class CommitSearchRequest(SearchRequest):
    since: str | None = None  # ISO 8601
    until: str | None = None  # ISO 8601


class RecentCommitsRequest(BaseModel):
    project: str | None = None
    limit: int = 5


class SearchResultResponse(BaseModel):
    project_name: str
    source_path: str
    content: str
    distance: float
    layer: str
    symbol_name: str | None
    symbol_type: str | None
    committed_at: str | None


class DependenciesRequest(BaseModel):
    project: str


class DependencyResponse(BaseModel):
    kind: str
    identifier: str
    provider_name: str | None
    external_name: str | None
    version_constraint: str | None
    source: str


class DependenciesResponse(BaseModel):
    project_found: bool
    dependencies: list[DependencyResponse]


class ProjectsRequest(BaseModel):
    technology: str | None = None


class ProjectSummaryResponse(BaseModel):
    name: str
    repo_url: str | None
    description: str | None
    technologies: list[str]
    manifest_missing: bool


class ProjectInfoRequest(BaseModel):
    project: str


class ProjectInfoResponse(BaseModel):
    found: bool
    name: str | None
    repo_url: str | None
    description: str | None
    default_branch: str | None
    is_private: bool
    manifest_missing: bool
    technologies: list[str]
