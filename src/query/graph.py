"""Minimal LangGraph query engine: vector search -> synthesizer."""

from __future__ import annotations

from typing import TypedDict, cast

import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.ingestion.embedder import Embedder
from src.query.synthesizer import LLMClient, synthesize
from src.query.vector_search import SearchResult, search_documents


class QueryState(TypedDict):
    query: str
    results: list[SearchResult]
    summary: str


def build_graph(
    conn: psycopg.Connection, embedder: Embedder, llm: LLMClient
) -> CompiledStateGraph[QueryState, None, QueryState, QueryState]:
    def vector_search_node(state: QueryState) -> dict[str, list[SearchResult]]:
        return {"results": search_documents(conn, state["query"], embedder)}

    def synthesize_node(state: QueryState) -> dict[str, str]:
        return {"summary": synthesize(state["query"], state["results"], llm)}

    graph = StateGraph(QueryState)
    graph.add_node("vector_search", vector_search_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_edge(START, "vector_search")
    graph.add_edge("vector_search", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def run_query(
    conn: psycopg.Connection, embedder: Embedder, llm: LLMClient, query: str
) -> QueryState:
    app = build_graph(conn, embedder, llm)
    return cast(QueryState, app.invoke({"query": query, "results": [], "summary": ""}))
