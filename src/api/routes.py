"""POST /v1/query and POST /v1/impact - see CLAUDE.md section 8."""

from __future__ import annotations

import time
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends

from src.api.dependencies import get_conn, get_embedder_dep, get_llm_dep
from src.api.schemas import (
    ImpactedProjectResponse,
    ImpactRequest,
    ImpactResponse,
    QueryRequest,
    QueryResponse,
)
from src.api.serialization import state_to_data
from src.ingestion.embedder import Embedder
from src.query.impact_graph import run_impact_query
from src.query.query_engine import run_query_engine
from src.query.synthesizer import LLMClient

router = APIRouter()

ConnDep = Annotated[psycopg.Connection, Depends(get_conn)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder_dep)]
LLMDep = Annotated[LLMClient, Depends(get_llm_dep)]


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
