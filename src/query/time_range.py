"""Parses common natural-language time expressions into an actual (since, until) range.

Deterministic, not LLM-based - the phrasings the router recognizes are a small,
well-known set, so a regex parser is cheaper and more testable than an LLM call.
"""

from __future__ import annotations

import datetime as dt
import re


def parse_time_range(query: str, now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    now = now or dt.datetime.now(dt.UTC)
    q = query.lower()

    if re.search(r"\byesterday\b", q):
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_today - dt.timedelta(days=1), start_of_today

    if re.search(r"\btoday\b", q):
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now

    if match := re.search(r"past (\d+) days?", q):
        return now - dt.timedelta(days=int(match.group(1))), now

    if re.search(r"\bthis week\b", q):
        since = (now - dt.timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return since, now

    if re.search(r"\b(?:past|last) week\b", q):
        return now - dt.timedelta(days=7), now

    if re.search(r"\b(?:past|last) month\b", q):
        return now - dt.timedelta(days=30), now

    if re.search(r"\b(?:past|last) year\b", q):
        return now - dt.timedelta(days=365), now

    if re.search(r"\brecent(?:ly)?\b", q):
        return now - dt.timedelta(days=14), now

    return now - dt.timedelta(days=30), now  # sensible default for a time-scoped query
