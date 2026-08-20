"""Seed sync: fetch repos, docs (L1) and code (L2), embed, upsert - idempotent via content_hash.

Graph/commits arrive in later stages.
"""

from __future__ import annotations

import os
import sys

import psycopg

from src.ingestion.chunker_code import is_candidate_code_file
from src.ingestion.code import sync_code_file
from src.ingestion.documents import record_ingestion_log, sync_document, upsert_project
from src.ingestion.embedder import get_embedder
from src.ingestion.github_client import GitHubClient

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

            code_totals = dict.fromkeys(STAT_KEYS, 0)
            all_files = client.list_all_files(repo.full_name, repo.default_branch)
            for file_path in filter(is_candidate_code_file, all_files):
                content = client.get_file(repo.full_name, file_path)
                if content is not None:
                    stats = sync_code_file(conn, project_id, file_path, content, embedder)
                    _accumulate(code_totals, stats)
            record_ingestion_log(conn, "manual", project_id, "code", "success", code_totals)

            conn.commit()
            print(f"  {repo.full_name}: docs={doc_totals} code={code_totals}")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
