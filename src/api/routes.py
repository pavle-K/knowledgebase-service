"""REST surface - /v1/query is the only NL-routed
endpoint; everything else here is a scoped, deterministic lookup that also
backs an MCP tool (src/mcp_server.py) for agentic callers to pick directly.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends

from src.api.dependencies import get_conn, get_embedder_dep, get_llm_dep
from src.api.schemas import (
    CommitSearchRequest,
    DependenciesRequest,
    DependenciesResponse,
    DependencyResponse,
    ImpactedProjectResponse,
    ImpactRequest,
    ImpactResponse,
    ProjectInfoRequest,
    ProjectInfoResponse,
    ProjectLinkResponse,
    ProjectLinksRequest,
    ProjectsRequest,
    ProjectSummaryResponse,
    QueryRequest,
    QueryResponse,
    RecentCommitsRequest,
    SearchRequest,
    SearchResultResponse,
)
from src.api.serialization import search_result_to_dict, state_to_data
from src.ingestion.embedder import Embedder
from src.query.graph_traversal import list_dependencies
from src.query.impact_graph import run_impact_query
from src.query.project_lookup import get_project_info, get_project_links, list_projects
from src.query.query_engine import run_query_engine
from src.query.synthesizer import LLMClient
from src.query.vector_search import (
    search_code_chunks,
    search_commits,
    search_documents,
    search_latest_commits,
)

router = APIRouter()

ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder_dep)]
LLMDep = Annotated[LLMClient, Depends(get_llm_dep)]

# MCP tool calls with zero arguments arrive as a request with no HTTP body at all -
# these defaults let an all-optional body still bind instead of a 422. Module-level
# singletons (not a call in the signature) since both are read-only.
_EMPTY_PROJECTS_REQUEST = ProjectsRequest()
_EMPTY_RECENT_COMMITS_REQUEST = RecentCommitsRequest()
_EMPTY_PROJECT_LINKS_REQUEST = ProjectLinksRequest()


@router.post("/v1/query", response_model=QueryResponse, operation_id="query")
def query_endpoint(
    body: QueryRequest, conn: ConnDep, embedder: EmbedderDep, llm: LLMDep
) -> QueryResponse:
    start = time.monotonic()
    state = run_query_engine(conn, embedder, llm, body.query, layers=body.layers)
    execution_time_ms = int((time.monotonic() - start) * 1000)

    return QueryResponse(
        summary=state["summary"],
        intent=state["intent"],
        data=state_to_data(state),
        confidence=state["confidence"],
        coverage_note=state["coverage_note"],
        execution_time_ms=execution_time_ms,
    )


@router.post("/v1/impact", response_model=ImpactResponse, operation_id="impact")
def impact_endpoint(body: ImpactRequest, conn: ConnDep) -> ImpactResponse:
    result = run_impact_query(conn, body.project, body.interface)
    return ImpactResponse(
        project_found=result.project_found,
        interface_declared=result.interface_declared,
        interface_source=result.interface_source,
        provider_manifest_missing=result.provider_manifest_missing,
        impacted=[
            ImpactedProjectResponse(name=p.name, repo_url=p.repo_url, distance=p.distance)
            for p in result.impacted
        ],
    )


@router.post(
    "/v1/dependencies", response_model=DependenciesResponse, operation_id="get_dependencies"
)
def get_dependencies_endpoint(body: DependenciesRequest, conn: ConnDep) -> DependenciesResponse:
    """What a project declares it depends on - the forward direction of the graph."""
    deps = list_dependencies(conn, body.project)
    if deps is None:
        return DependenciesResponse(project_found=False, dependencies=[])
    return DependenciesResponse(
        project_found=True,
        dependencies=[
            DependencyResponse(
                kind=d.kind,
                identifier=d.identifier,
                provider_name=d.provider_name,
                external_name=d.external_name,
                version_constraint=d.version_constraint,
                source=d.source,
            )
            for d in deps
        ],
    )


@router.post(
    "/v1/projects", response_model=list[ProjectSummaryResponse], operation_id="list_projects"
)
def list_projects_endpoint(
    conn: ConnDep, body: ProjectsRequest = _EMPTY_PROJECTS_REQUEST
) -> list[ProjectSummaryResponse]:
    """List projects, optionally filtered by technology (e.g. 'postgres', 'fastapi')."""
    projects = list_projects(conn, technology=body.technology)
    return [
        ProjectSummaryResponse(
            name=p.name,
            repo_url=p.repo_url,
            description=p.description,
            technologies=p.technologies,
            manifest_missing=p.manifest_missing,
        )
        for p in projects
    ]


@router.post(
    "/v1/projects/info", response_model=ProjectInfoResponse, operation_id="get_project_info"
)
def get_project_info_endpoint(body: ProjectInfoRequest, conn: ConnDep) -> ProjectInfoResponse:
    """Metadata and tech stack for a single project by name."""
    info = get_project_info(conn, body.project)
    return ProjectInfoResponse(
        found=info.found,
        name=info.name,
        repo_url=info.repo_url,
        description=info.description,
        default_branch=info.default_branch,
        is_private=info.is_private,
        manifest_missing=info.manifest_missing,
        technologies=info.technologies,
    )


@router.post(
    "/v1/projects/links", response_model=list[ProjectLinkResponse], operation_id="get_project_links"
)
def get_project_links_endpoint(
    conn: ConnDep, body: ProjectLinksRequest = _EMPTY_PROJECT_LINKS_REQUEST
) -> list[ProjectLinkResponse]:
    """Canonical name + repo link per project - for citing an exact source, not
    recalling one from prose. `projects` narrows to those names; omitted, returns all."""
    links = get_project_links(conn, projects=body.projects)
    return [
        ProjectLinkResponse(name=link.name, repo_url=link.repo_url, description=link.description)
        for link in links
    ]


@router.post(
    "/v1/search/docs", response_model=list[SearchResultResponse], operation_id="search_docs"
)
def search_docs_endpoint(
    body: SearchRequest, conn: ConnDep, embedder: EmbedderDep
) -> list[SearchResultResponse]:
    """Semantic search over README/docs content (L1), optionally scoped to one project."""
    results = search_documents(conn, body.query, embedder, limit=body.limit, project=body.project)
    return [SearchResultResponse.model_validate(search_result_to_dict(r)) for r in results]


@router.post(
    "/v1/search/code", response_model=list[SearchResultResponse], operation_id="search_code"
)
def search_code_endpoint(
    body: SearchRequest, conn: ConnDep, embedder: EmbedderDep
) -> list[SearchResultResponse]:
    """Semantic search over code chunks (L2), optionally scoped to one project."""
    results = search_code_chunks(conn, body.query, embedder, limit=body.limit, project=body.project)
    return [SearchResultResponse.model_validate(search_result_to_dict(r)) for r in results]


@router.post(
    "/v1/search/commits", response_model=list[SearchResultResponse], operation_id="search_commits"
)
def search_commits_endpoint(
    body: CommitSearchRequest, conn: ConnDep, embedder: EmbedderDep
) -> list[SearchResultResponse]:
    """Semantic search over commit history (L4), optionally time- and project-scoped."""
    since = dt.datetime.fromisoformat(body.since) if body.since else None
    until = dt.datetime.fromisoformat(body.until) if body.until else None
    results = search_commits(
        conn, body.query, embedder, limit=body.limit, since=since, until=until, project=body.project
    )
    return [SearchResultResponse.model_validate(search_result_to_dict(r)) for r in results]


@router.post(
    "/v1/commits/recent",
    response_model=list[SearchResultResponse],
    operation_id="get_recent_commits",
)
def get_recent_commits_endpoint(
    conn: ConnDep, body: RecentCommitsRequest = _EMPTY_RECENT_COMMITS_REQUEST
) -> list[SearchResultResponse]:
    """Most recent commits by date, not relevance - no query text, no embedding call."""
    results = search_latest_commits(conn, limit=body.limit, project=body.project)
    return [SearchResultResponse.model_validate(search_result_to_dict(r)) for r in results]
