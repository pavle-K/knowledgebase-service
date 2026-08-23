import uuid
from collections.abc import Iterator

import psycopg
import pytest

from tests.integration.conftest import MigratedDb


@pytest.fixture
def seeded(migrated_db: MigratedDb) -> Iterator[dict[str, uuid.UUID]]:
    """One public and one private project, each with a row in every content table."""
    ids: dict[str, uuid.UUID] = {}
    with psycopg.connect(migrated_db.admin_url) as conn:
        for label, is_private in (("public", False), ("private", True)):
            unique = uuid.uuid4().hex[:8]
            row = conn.execute(
                """
                insert into projects (name, repo_url, source, default_branch, is_private)
                values (%s, %s, 'github', 'main', %s)
                returning id
                """,
                (f"{label}-{unique}", f"https://github.com/pavle-K/{label}-{unique}", is_private),
            ).fetchone()
            assert row is not None
            project_id = row[0]
            ids[label] = project_id

            conn.execute(
                """
                insert into documents
                    (project_id, doc_type, source_path, chunk_index, content, content_hash)
                values (%s, 'readme', 'README.md', 0, %s, %s)
                """,
                (project_id, f"{label} readme body", f"hash-{unique}"),
            )
            conn.execute(
                """
                insert into code_chunks
                    (project_id, file_path, symbol_name, symbol_type, language,
                     start_line, content, content_hash)
                values (%s, 'src/app.py', 'handler', 'function', 'python', 1, %s, %s)
                """,
                (project_id, f"def handler(): return '{label}'", f"code-{unique}"),
            )
            conn.execute(
                "insert into commits (project_id, sha, message, diff_summary)"
                " values (%s, %s, 'msg', %s)",
                (project_id, f"sha-{unique}", f"{label} change"),
            )
            conn.execute(
                "insert into exposed_interfaces (project_id, kind, identifier, source)"
                " values (%s, 'http_endpoint', 'GET /x', 'manifest')",
                (project_id,),
            )
            conn.execute(
                "insert into dependencies"
                " (consumer_project_id, kind, identifier, external_name, source)"
                " values (%s, 'package', 'boto3', 'boto3', 'static_analysis')",
                (project_id,),
            )
            conn.execute(
                "insert into secret_scan_findings (project_id, file_path, rule_id)"
                " values (%s, '.env', 'AWSKeyDetector')",
                (project_id,),
            )
            conn.execute(
                "insert into ingestion_log (source, project_id, layer, status)"
                " values ('manual', %s, 'documents', 'success')",
                (project_id,),
            )
        conn.commit()
    yield ids
    with psycopg.connect(migrated_db.admin_url) as conn:
        conn.execute("delete from projects where id = any(%s)", (list(ids.values()),))
        conn.commit()


CONTENT_TABLES = [
    ("documents", "project_id"),
    ("code_chunks", "project_id"),
    ("commits", "project_id"),
    ("exposed_interfaces", "project_id"),
    ("dependencies", "consumer_project_id"),
]


def test_public_role_sees_public_project_but_not_private(
    migrated_db: MigratedDb, seeded: dict[str, uuid.UUID]
) -> None:
    with psycopg.connect(migrated_db.app_ro_public_url) as conn:
        visible = {
            row[0]
            for row in conn.execute(
                "select id from projects where id = any(%s)", (list(seeded.values()),)
            ).fetchall()
        }
    assert seeded["public"] in visible
    assert seeded["private"] not in visible


@pytest.mark.parametrize(("table", "column"), CONTENT_TABLES)
def test_public_role_cannot_read_private_project_content(
    migrated_db: MigratedDb, seeded: dict[str, uuid.UUID], table: str, column: str
) -> None:
    with psycopg.connect(migrated_db.app_ro_public_url) as conn:
        private_rows = conn.execute(
            f"select count(*) from {table} where {column} = %s", (seeded["private"],)
        ).fetchone()
        public_rows = conn.execute(
            f"select count(*) from {table} where {column} = %s", (seeded["public"],)
        ).fetchone()
    assert private_rows == (0,)
    assert public_rows == (1,)


def test_public_role_cannot_reach_private_content_by_joining_around_projects(
    migrated_db: MigratedDb, seeded: dict[str, uuid.UUID]
) -> None:
    """RLS must hold for generated SQL that never mentions projects.is_private."""
    with psycopg.connect(migrated_db.app_ro_public_url) as conn:
        rows = conn.execute(
            "select d.content from documents d where d.content like %s", ("private%",)
        ).fetchall()
    assert rows == []


def test_public_role_cannot_read_findings_or_ingestion_history(
    migrated_db: MigratedDb, seeded: dict[str, uuid.UUID]
) -> None:
    with psycopg.connect(migrated_db.app_ro_public_url) as conn:
        findings = conn.execute("select count(*) from secret_scan_findings").fetchone()
        logs = conn.execute("select count(*) from ingestion_log").fetchone()
    assert findings == (0,)
    assert logs == (0,)


def test_privileged_role_sees_both_projects(
    migrated_db: MigratedDb, seeded: dict[str, uuid.UUID]
) -> None:
    with psycopg.connect(migrated_db.app_ro_url) as conn:
        visible = {
            row[0]
            for row in conn.execute(
                "select id from projects where id = any(%s)", (list(seeded.values()),)
            ).fetchall()
        }
    assert visible == set(seeded.values())


def test_public_role_still_cannot_write(
    migrated_db: MigratedDb, seeded: dict[str, uuid.UUID]
) -> None:
    with psycopg.connect(migrated_db.app_ro_public_url) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("update projects set name = 'hijacked' where id = %s", (seeded["public"],))


def test_ingestion_role_still_writes_to_private_projects(
    migrated_db: MigratedDb, seeded: dict[str, uuid.UUID]
) -> None:
    """RLS must not lock ingestion out of the private repos it is meant to index."""
    with psycopg.connect(migrated_db.app_rw_url) as conn:
        conn.execute(
            """
            insert into documents
                (project_id, doc_type, source_path, chunk_index, content, content_hash)
            values (%s, 'docs', 'docs/extra.md', 0, 'more private text', 'hash-extra')
            """,
            (seeded["private"],),
        )
        count = conn.execute(
            "select count(*) from documents where project_id = %s", (seeded["private"],)
        ).fetchone()
        conn.commit()
    assert count == (2,)
