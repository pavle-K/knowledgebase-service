"""Converts an internal QueryState into the JSON-safe `data` field for /v1/query."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.query.vector_search import SearchResult

if TYPE_CHECKING:
    from src.query.query_engine import QueryState


def search_result_to_dict(result: SearchResult) -> dict[str, object]:
    return {
        "project_name": result.project_name,
        "source_path": result.source_path,
        "content": result.content,
        "distance": result.distance,
        "layer": result.layer,
        "symbol_name": result.symbol_name,
        "symbol_type": result.symbol_type,
        "committed_at": result.committed_at.isoformat() if result.committed_at else None,
    }


def state_to_data(state: QueryState) -> object:
    intent = state["intent"]

    if intent == "sql":
        sql_result = state["sql_result"]
        return sql_result.rows if sql_result else None

    if intent == "graph":
        graph_result = state["graph_result"]
        if graph_result is None:
            return None
        return [
            {"name": p.name, "repo_url": p.repo_url, "distance": p.distance}
            for p in graph_result.impacted
        ]

    if intent == "hybrid":
        sql_result = state["sql_result"]
        return {
            "sql_rows": sql_result.rows if sql_result else None,
            "vector_results": [search_result_to_dict(r) for r in state["vector_results"]],
        }

    # 'vector' and 'time'
    return [search_result_to_dict(r) for r in state["vector_results"]]
