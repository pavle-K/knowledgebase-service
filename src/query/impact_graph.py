"""Minimal LangGraph wrapping the deterministic impact-analysis CTE.

No LLM node here - /v1/impact exists so agents get a deterministic answer
without going through intent classification or synthesis (CLAUDE.md, sections 7-8).
"""

from __future__ import annotations

from typing import TypedDict, cast

import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.query.graph_traversal import ImpactResult, impact_analysis


class ImpactState(TypedDict):
    project_name: str
    interface_identifier: str
    result: ImpactResult | None


def build_impact_graph(
    conn: psycopg.Connection,
) -> CompiledStateGraph[ImpactState, None, ImpactState, ImpactState]:
    def graph_traversal_node(state: ImpactState) -> dict[str, ImpactResult]:
        result = impact_analysis(conn, state["project_name"], state["interface_identifier"])
        return {"result": result}

    graph = StateGraph(ImpactState)
    graph.add_node("graph_traversal", graph_traversal_node)
    graph.add_edge(START, "graph_traversal")
    graph.add_edge("graph_traversal", END)
    return graph.compile()


def run_impact_query(
    conn: psycopg.Connection, project_name: str, interface_identifier: str
) -> ImpactResult:
    app = build_impact_graph(conn)
    state = cast(
        ImpactState,
        app.invoke(
            {
                "project_name": project_name,
                "interface_identifier": interface_identifier,
                "result": None,
            }
        ),
    )
    result = state["result"]
    assert result is not None
    return result
