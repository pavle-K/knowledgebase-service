"""The full query engine: Intent Router -> {SQL | Vector | Graph | Hybrid} -> Synthesizer.

Supersedes the Stage 3 vector-only graph. Impact analysis keeps its own separate
minimal graph (impact_graph.py) for the deterministic /v1/impact contract - this
engine is for /v1/query, where natural language decides the route.

sql -> vector fallback: a successful SQL query that returns zero rows often means
the structured tables it depends on (e.g. technologies/project_technologies, which
are populated from project.yaml manifests) are sparse or unpopulated, not that the
answer doesn't exist - documents/code_chunks may still answer it semantically. A
genuine SQL error does NOT fall back; that's a self-heal failure, not a coverage gap.
"""

from __future__ import annotations

from typing import TypedDict, cast

import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.ingestion.embedder import Embedder
from src.query.graph_traversal import ImpactResult, impact_analysis
from src.query.impact_extractor import extract_impact_params
from src.query.intent_router import classify_intent
from src.query.query_synthesis import build_synthesis
from src.query.sql_exec import SqlResult, run_sql_with_self_heal
from src.query.sql_generator import introspect_schema
from src.query.synthesizer import LLMClient
from src.query.time_range import parse_time_range
from src.query.vector_search import SearchResult, search_all, search_commits


class QueryState(TypedDict):
    query: str
    layers: list[str] | None
    intent: str
    sql_result: SqlResult | None
    vector_results: list[SearchResult]
    graph_result: ImpactResult | None
    summary: str
    confidence: str
    coverage_note: str | None


def build_query_engine(
    conn: psycopg.Connection, embedder: Embedder, llm: LLMClient
) -> CompiledStateGraph[QueryState, None, QueryState, QueryState]:
    def router_node(state: QueryState) -> dict[str, str]:
        return {"intent": classify_intent(state["query"])}

    def sql_node(state: QueryState) -> dict[str, SqlResult]:
        schema = introspect_schema(conn)
        return {"sql_result": run_sql_with_self_heal(conn, state["query"], llm, schema)}

    def vector_node(state: QueryState) -> dict[str, list[SearchResult]]:
        results = search_all(conn, state["query"], embedder, layers=state["layers"])
        return {"vector_results": results}

    def time_node(state: QueryState) -> dict[str, list[SearchResult]]:
        since, until = parse_time_range(state["query"])
        results = search_commits(conn, state["query"], embedder, limit=10, since=since, until=until)
        return {"vector_results": results}

    def graph_node(state: QueryState) -> dict[str, ImpactResult | None]:
        params = extract_impact_params(state["query"], llm)
        if params is None:
            return {"graph_result": None}
        project_name, interface = params
        return {"graph_result": impact_analysis(conn, project_name, interface)}

    def synthesize_node(state: QueryState) -> dict[str, str | None]:
        summary, confidence, coverage_note = build_synthesis(state, llm)
        return {"summary": summary, "confidence": confidence, "coverage_note": coverage_note}

    graph = StateGraph(QueryState)
    graph.add_node("router", router_node)
    graph.add_node("sql", sql_node)
    graph.add_node("vector", vector_node)
    graph.add_node("time", time_node)
    graph.add_node("graph_traversal", graph_node)
    graph.add_node("synthesize", synthesize_node)

    def sql_needs_vector_fallback(state: QueryState) -> bool:
        result = state["sql_result"]
        return result is not None and result.error is None and not result.rows

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        lambda s: s["intent"],
        {
            "sql": "sql",
            "hybrid": "sql",
            "vector": "vector",
            "time": "time",
            "graph": "graph_traversal",
        },
    )
    graph.add_conditional_edges(
        "sql",
        lambda s: (
            "vector" if s["intent"] == "hybrid" or sql_needs_vector_fallback(s) else "synthesize"
        ),
        {"vector": "vector", "synthesize": "synthesize"},
    )
    graph.add_edge("vector", "synthesize")
    graph.add_edge("time", "synthesize")
    graph.add_edge("graph_traversal", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def run_query_engine(
    conn: psycopg.Connection,
    embedder: Embedder,
    llm: LLMClient,
    query: str,
    layers: list[str] | None = None,
) -> QueryState:
    app = build_query_engine(conn, embedder, llm)
    initial: QueryState = {
        "query": query,
        "layers": layers,
        "intent": "",
        "sql_result": None,
        "vector_results": [],
        "graph_result": None,
        "summary": "",
        "confidence": "",
        "coverage_note": None,
    }
    return cast(QueryState, app.invoke(initial))
