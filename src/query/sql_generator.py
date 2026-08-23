"""LLM-generated SQL against the live schema. Read-only enforcement is NOT done
here - it's enforced at the database role level (app_ro grants, Stage 1), since
application-level guards are bypassable by a sufficiently creative query.
"""

from __future__ import annotations

import re

import psycopg

from src.query.synthesizer import UNTRUSTED_CONTENT_INSTRUCTION, LLMClient, wrap_untrusted

SQL_SYSTEM_PROMPT = (
    "You are a PostgreSQL query generator. Given a database schema and a natural language "
    "question, write ONE read-only SELECT statement that answers it. Use only the tables "
    "and columns listed in the schema. Output ONLY the raw SQL statement - no markdown, "
    "no explanation, no semicolons, no multiple statements.\n\n"
    "For tech-stack questions (what technology/library/framework a project uses), the "
    "technologies/project_technologies tables are populated only from project.yaml "
    "manifests and may be sparse or empty. The dependencies table (kind='package', "
    "external_name) is populated by static analysis of requirements.txt/pyproject.toml/"
    "package.json and often has real data even when technologies does not - check both, "
    "e.g. via UNION, when a project.yaml-derived table alone would miss coverage.\n\n"
    + UNTRUSTED_CONTENT_INSTRUCTION
)

_CODE_FENCE_RE = re.compile(r"^```(?:sql)?\s*|```\s*$", re.MULTILINE)


def introspect_schema(conn: psycopg.Connection) -> str:
    rows = conn.execute(
        """
        select table_name, column_name, data_type
        from information_schema.columns
        where table_schema = 'public'
        order by table_name, ordinal_position
        """
    ).fetchall()

    tables: dict[str, list[str]] = {}
    for table_name, column_name, data_type in rows:
        tables.setdefault(table_name, []).append(f"{column_name} ({data_type})")

    return "\n".join(f"{table}: {', '.join(columns)}" for table, columns in tables.items())


def generate_sql(
    query: str, schema_description: str, llm: LLMClient, previous_error: str | None = None
) -> str:
    user_prompt = f"Schema:\n{schema_description}\n\nQuestion:\n{wrap_untrusted(query)}"
    if previous_error:
        user_prompt += (
            f"\n\nThe previous attempt failed with this error - fix it:\n{previous_error}"
        )
    raw = llm.complete(SQL_SYSTEM_PROMPT, user_prompt)
    return _CODE_FENCE_RE.sub("", raw).strip()
