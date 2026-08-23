"""Deterministic intent classification - not LLM-based.

Impact/blast-radius questions MUST route to graph, never vector - this is the
single most important routing rule in the system, so it's implemented as a hard
rule rather than left to a probabilistic classifier.
"""

from __future__ import annotations

import re

Intent = str  # 'graph' | 'sql' | 'hybrid' | 'vector' | 'time' | 'latest'

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

# "which projects depend on other projects of mine" shares vocabulary with a
# single-target impact question but is actually a structural listing query - no
# specific interface is named, so graph's extraction step could never resolve one.
_AGGREGATE_OVERRIDE_PATTERNS = [
    r"\bother projects? of mine\b",
    r"\beach other\b",
    r"\bone another\b",
]

# "latest/newest" asks for the single most recent thing, ranked by date - a plain
# similarity search (even time-windowed) can't answer that, since it ranks by how
# well content matches the query text, not by how recent it is. Checked ahead of
# _TIME_PATTERNS: "most recent" would otherwise also match "recent(?:ly)?" below.
_LATEST_PATTERNS = [
    r"\blatest\b",
    r"\bnewest\b",
    r"\bmost recent\b",
]

_TIME_PATTERNS = [
    r"\b(?:past|last) (?:week|month|year|\d+ days?)\b",
    r"\bthis week\b",
    r"\btoday\b",
    r"\byesterday\b",
    r"\brecent(?:ly)?\b",
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

    is_graph_signal = any(re.search(p, q) for p in _GRAPH_PATTERNS)
    is_aggregate_override = any(re.search(p, q) for p in _AGGREGATE_OVERRIDE_PATTERNS)
    if is_graph_signal and not is_aggregate_override:
        return "graph"

    if any(re.search(p, q) for p in _LATEST_PATTERNS):
        return "latest"

    if any(re.search(p, q) for p in _TIME_PATTERNS):
        return "time"

    # aggregate_override phrases ("each other", etc.) are themselves a structural/sql
    # signal, regardless of whether they also match a _SQL_PATTERNS phrasing.
    is_sql = is_aggregate_override or any(re.search(p, q) for p in _SQL_PATTERNS)
    is_hybrid_signal = any(re.search(p, q) for p in _HYBRID_TRIGGER_PATTERNS)

    if is_sql and is_hybrid_signal:
        return "hybrid"
    if is_sql:
        return "sql"
    return "vector"
