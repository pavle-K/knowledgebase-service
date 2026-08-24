"""Extracts (project, interface) from a free-text impact question.

impact_analysis() needs structured params; the router only knows the query is
graph-shaped, not which project/interface it's about. A small LLM call bridges
that gap. If extraction is ambiguous, returns None rather than guessing.
"""

from __future__ import annotations

import re

from src.query.synthesizer import LLMClient

EXTRACT_SYSTEM_PROMPT = (
    "Given a question about software dependencies, extract the project name and the "
    "interface/endpoint/table identifier being discussed. Respond with EXACTLY this "
    "format and nothing else:\nPROJECT: <name>\nINTERFACE: <identifier>\n"
    "If you cannot confidently identify both, respond with exactly: UNKNOWN"
)


def extract_impact_params(query: str, llm: LLMClient) -> tuple[str, str] | None:
    raw = llm.complete(EXTRACT_SYSTEM_PROMPT, query, name="impact-param-extraction")
    if raw.strip() == "UNKNOWN":
        return None

    project_match = re.search(r"PROJECT:\s*(.+)", raw)
    interface_match = re.search(r"INTERFACE:\s*(.+)", raw)
    if not project_match or not interface_match:
        return None

    return project_match.group(1).strip(), interface_match.group(1).strip()
