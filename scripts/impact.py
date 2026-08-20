"""CLI: python -m scripts.impact "<project>" "<interface>" - deterministic, no LLM."""

from __future__ import annotations

import os
import sys

import psycopg

from src.query.impact_graph import run_impact_query


def main() -> int:
    if len(sys.argv) < 3:
        print('usage: python -m scripts.impact "<project>" "<interface>"', file=sys.stderr)
        return 1

    project_name, interface_identifier = sys.argv[1], sys.argv[2]
    database_url = os.environ.get("DATABASE_URL_RO")
    if not database_url:
        print("DATABASE_URL_RO is not set", file=sys.stderr)
        return 1

    with psycopg.connect(database_url) as conn:
        result = run_impact_query(conn, project_name, interface_identifier)

    if not result.project_found:
        print(f"No project named '{project_name}' found.")
        return 0

    if not result.interface_declared:
        print(
            f"Warning: '{interface_identifier}' is not declared in {project_name}'s "
            "exposed_interfaces - it may not exist, or the identifier may be wrong."
        )
    elif result.interface_source == "static_analysis":
        print(
            f"Note: '{interface_identifier}' was found by static analysis, not declared "
            f"in a manifest - medium confidence."
        )

    if result.provider_manifest_missing:
        print(f"Coverage note: {project_name} has no project.yaml - graph edges may be incomplete.")

    if not result.impacted:
        print(f"No projects depend on {project_name} {interface_identifier}.")
        return 0

    print(f"Projects impacted by a change to {project_name} {interface_identifier}:")
    for p in result.impacted:
        print(f"  [distance {p.distance}] {p.name} ({p.repo_url or 'unknown repo'})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
