"""Intent-specific synthesis, including honest confidence/coverage reporting.

Graph synthesis is deliberately template-based, not LLM-paraphrased - matches
/v1/impact's non-LLM, deterministic contract and avoids an LLM softening or
dropping the confidence caveats CLAUDE.md requires (section 7, point 6).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.query.synthesizer import SYSTEM_PROMPT, LLMClient, format_context, synthesize

if TYPE_CHECKING:
    from src.query.query_engine import QueryState

logger = logging.getLogger(__name__)

SQL_SYNTHESIS_SYSTEM_PROMPT = (
    "You answer questions using only the provided SQL query results. Be concise. "
    "If the results don't answer the question, say so."
)


def _synthesize_graph(state: QueryState) -> tuple[str, str, str | None]:
    result = state["graph_result"]
    if result is None:
        return (
            "I couldn't confidently identify which project and interface you're asking "
            "about. Try phrasing it like: 'what breaks if I change POST /v1/query on "
            "knowledgebase-service'.",
            "low",
            None,
        )
    if not result.project_found:
        return ("No project matching that name was found.", "low", None)

    if not result.interface_declared:
        confidence = "low"
    elif result.interface_source == "manifest":
        confidence = "high"
    else:
        confidence = "medium"

    coverage_note = None
    if result.provider_manifest_missing:
        coverage_note = "This project has no project.yaml manifest - graph edges may be incomplete."

    if not result.impacted:
        summary = "Nothing currently depends on this interface."
    else:
        lines = "\n".join(f"- {p.name} (distance {p.distance})" for p in result.impacted)
        summary = f"These projects would be impacted by a change here:\n{lines}"

    return summary, confidence, coverage_note


def _synthesize_sql(state: QueryState, llm: LLMClient) -> tuple[str, str, str | None]:
    result = state["sql_result"]
    assert result is not None
    if result.error is not None:
        logger.warning(
            "SQL self-heal exhausted after %d attempts: %s", result.attempts, result.error
        )
        return (
            f"I couldn't answer that with SQL after {result.attempts} attempts.",
            "low",
            None,
        )
    if not result.rows:
        return ("No rows matched that query.", "high", None)

    context = "\n".join(str(row) for row in result.rows[:20])
    user_prompt = f"Question: {state['query']}\n\nSQL query results:\n{context}"
    summary = llm.complete(SQL_SYNTHESIS_SYSTEM_PROMPT, user_prompt)
    return summary, "high", None


def _synthesize_vector(state: QueryState, llm: LLMClient) -> tuple[str, str, str | None]:
    summary = synthesize(state["query"], state["vector_results"], llm)
    return summary, "medium", None


def _synthesize_sql_fallback(state: QueryState, llm: LLMClient) -> tuple[str, str, str | None]:
    """SQL returned zero rows (no error) and the engine fell back to vector search."""
    if not state["vector_results"]:
        return ("No rows matched that query.", "high", None)
    summary = synthesize(state["query"], state["vector_results"], llm)
    coverage_note = (
        "No structured data matched (technologies/manifest-derived tables may be "
        "sparse or unpopulated) - this answer is inferred from semantic search over "
        "code and docs, not declared metadata."
    )
    return summary, "medium", coverage_note


def _synthesize_hybrid(state: QueryState, llm: LLMClient) -> tuple[str, str, str | None]:
    result = state["sql_result"]
    sql_rows = result.rows if result and result.rows else []
    sql_context = "\n".join(str(row) for row in sql_rows[:20])
    vector_context = format_context(state["vector_results"])
    user_prompt = (
        f"Question: {state['query']}\n\n"
        f"Structured data:\n{sql_context}\n\n"
        f"Documents/code:\n{vector_context}"
    )
    summary = llm.complete(SYSTEM_PROMPT, user_prompt)
    confidence = "high" if result and not result.error else "medium"
    return summary, confidence, None


def build_synthesis(state: QueryState, llm: LLMClient) -> tuple[str, str, str | None]:
    intent = state["intent"]
    if intent == "graph":
        return _synthesize_graph(state)
    if intent == "sql":
        result = state["sql_result"]
        assert result is not None
        if result.error is None and not result.rows and state["vector_results"]:
            return _synthesize_sql_fallback(state, llm)
        return _synthesize_sql(state, llm)
    if intent == "hybrid":
        return _synthesize_hybrid(state, llm)
    # 'vector' and 'time' both synthesize from vector_results (time just pre-filtered it)
    return _synthesize_vector(state, llm)
