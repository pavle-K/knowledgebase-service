"""Deterministic intent classification - not LLM-based.

Impact/blast-radius questions MUST route to graph, never vector - this is the
single most important routing rule in the system (CLAUDE.md, section 7), so it's
implemented as a hard rule rather than left to a probabilistic classifier.
"""

from __future__ import annotations

import re

Intent = str  # 'graph' | 'sql' | 'hybrid' | 'vector'

_GRAPH_PATTERNS = [
    r"\bwhat(?:'s| is| would| will)? break",
    r"\bwhat breaks\b",
    r"\bdepends? on\b",
    r"\bdependents?\b",
    r"\bwho (?:calls?|consumes?|uses?)\b",
    r"\bimpact of\b",
    r"\bif i change\b",
    r"\bif we change\b",
    r"\bblast radius\b",
]

_SQL_PATTERNS = [
    r"\bhow many\b",
    r"\bcount of\b",
    r"\blist all\b",
    r"\bwhich (?:of my )?(?:repos?|projects?)\b",
]

_HYBRID_TRIGGER_PATTERNS = [
    r"\band (?:also )?(?:tell me|show|summarize)\b",
    r"\bas well as\b",
]


def classify_intent(query: str) -> Intent:
    q = query.lower()

    if any(re.search(p, q) for p in _GRAPH_PATTERNS):
        return "graph"

    is_sql = any(re.search(p, q) for p in _SQL_PATTERNS)
    is_hybrid_signal = any(re.search(p, q) for p in _HYBRID_TRIGGER_PATTERNS)

    if is_sql and is_hybrid_signal:
        return "hybrid"
    if is_sql:
        return "sql"
    return "vector"
