"""Seed sync: fetch repos, docs (L1), code (L2), the dependency graph (L3), and commits (L4)."""

from __future__ import annotations

import os
import sys

import psycopg

from src.ingestion.chunker_code import is_candidate_code_file
from src.ingestion.code import sync_code_file
from src.ingestion.documents import record_ingestion_log, sync_document, upsert_project
from src.ingestion.embedder import get_embedder
from src.ingestion.github_client import GitHubClient
from src.ingestion.repo_sync import (
    PACKAGE_MANIFEST_PARSERS,
    sync_commits_for_repo,
    sync_manifest_for_repo,
    sync_static_analysis_for_file,
)
from src.query.synthesizer import get_llm_client

STAT_KEYS = ("chunks", "embedded", "skipped_unchanged", "skipped_secret")


def _accumulate(totals: dict[str, int], stats: dict[str, int]) -> None:
    for key in STAT_KEYS:
        totals[key] += stats[key]


def main() -> int:
    github_token = os.environ.get("GITHUB_TOKEN")
    database_url = os.environ.get("DATABASE_URL_RW")
    if not github_token or not database_url:
        print("GITHUB_TOKEN and DATABASE_URL_RW must both be set", file=sys.stderr)
        return 1

    embedder = get_embedder()
    llm = get_llm_client()
    client = GitHubClient(token=github_token)

    with psycopg.connect(database_url) as conn:
        repos = [r for r in client.list_repos() if not r.fork]
        print(f"Found {len(repos)} repos (forks excluded)")

        for repo in repos:
            project_id = upsert_project(conn, repo)

            doc_totals = dict.fromkeys(STAT_KEYS, 0)
            readme = client.get_readme(repo.full_name)
            if readme:
                _accumulate(
                    doc_totals,
                    sync_document(conn, project_id, "readme", "README.md", readme, embedder),
                )
            for doc_path in client.list_docs_files(repo.full_name):
                content = client.get_file(repo.full_name, doc_path)
                if content is not None:
                    _accumulate(
                        doc_totals,
                        sync_document(conn, project_id, "docs", doc_path, content, embedder),
                    )
            record_ingestion_log(conn, "manual", project_id, "documents", "success", doc_totals)

            sync_manifest_for_repo(conn, client, repo, project_id, source="manual")

            code_totals = dict.fromkeys(STAT_KEYS, 0)
            graph_edges = 0
            all_files = client.list_all_files(repo.full_name, repo.default_branch)
            for file_path in all_files:
                basename = file_path.rsplit("/", 1)[-1]
                needs_code = is_candidate_code_file(file_path)
                needs_manifest_scan = basename in PACKAGE_MANIFEST_PARSERS
                if not needs_code and not needs_manifest_scan:
                    continue

                content = client.get_file(repo.full_name, file_path)
                if content is None:
                    continue

                if needs_code:
                    stats = sync_code_file(conn, project_id, file_path, content, embedder)
                    _accumulate(code_totals, stats)

                graph_edges += sync_static_analysis_for_file(conn, project_id, file_path, content)

            record_ingestion_log(conn, "manual", project_id, "code", "success", code_totals)
            record_ingestion_log(
                conn, "manual", project_id, "graph", "success", {"static_edges": graph_edges}
            )

            commit_counts = sync_commits_for_repo(conn, client, repo, project_id, embedder, llm)
            record_ingestion_log(
                conn, "manual", project_id, "commits", "success", dict(commit_counts)
            )

            conn.commit()
            print(
                f"  {repo.full_name}: docs={doc_totals} code={code_totals} "
                f"graph_static_edges={graph_edges} commits={dict(commit_counts)}"
            )

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
