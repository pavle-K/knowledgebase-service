import uuid

import httpx
import psycopg
import respx

from src.ingestion.documents import upsert_project
from src.ingestion.embedder import FakeEmbedder
from src.ingestion.github_client import GITHUB_API_BASE, GitHubClient, RepoInfo
from src.ingestion.repo_sync import (
    sync_commits_for_repo,
    sync_manifest_for_repo,
    sync_static_analysis_for_file,
)
from src.query.synthesizer import FakeLLMClient


def _fake_repo(name: str) -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"{name}-{unique}",
        full_name=f"pavle-K/{name}-{unique}",
        html_url=f"https://github.com/pavle-K/{name}-{unique}",
        description="demo",
        default_branch="main",
        is_private=False,
        fork=False,
    )


@respx.mock
def test_sync_manifest_for_repo_with_valid_manifest(db_conn: psycopg.Connection) -> None:
    repo = _fake_repo("manifest-proj")
    project_id = upsert_project(db_conn, repo)
    respx.get(f"{GITHUB_API_BASE}/repos/{repo.full_name}/contents/project.yaml").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": (
                    "bmFtZTogZGVtbwp0ZWNobm9sb2dpZXM6IFtweXRob24sIGZhc3RhcGldCmV4cG9zZXM6"
                    "CiAgLSBraW5kOiBodHRwX2VuZHBvaW50CiAgICBpZGVudGlmaWVyOiAiR0VUIC9oZWFsdGh6Igo="
                ),
                "encoding": "base64",
            },
        )
    )

    client = GitHubClient(token="fake-token")
    sync_manifest_for_repo(db_conn, client, repo, project_id, source="github_webhook")

    missing = db_conn.execute(
        "select manifest_missing from projects where id = %s", (project_id,)
    ).fetchone()
    assert missing == (False,)

    exposed = db_conn.execute(
        "select identifier, source from exposed_interfaces where project_id = %s", (project_id,)
    ).fetchone()
    assert exposed == ("GET /healthz", "manifest")

    tech = db_conn.execute(
        "select t.name from project_technologies pt join technologies t on t.id = pt.technology_id"
        " where pt.project_id = %s order by t.name",
        (project_id,),
    ).fetchall()
    assert {r[0] for r in tech} == {"python", "fastapi"}


@respx.mock
def test_sync_manifest_for_repo_absent_marks_missing(db_conn: psycopg.Connection) -> None:
    repo = _fake_repo("no-manifest-proj")
    project_id = upsert_project(db_conn, repo)
    db_conn.execute("update projects set manifest_missing = false where id = %s", (project_id,))
    respx.get(f"{GITHUB_API_BASE}/repos/{repo.full_name}/contents/project.yaml").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    client = GitHubClient(token="fake-token")
    sync_manifest_for_repo(db_conn, client, repo, project_id)

    missing = db_conn.execute(
        "select manifest_missing from projects where id = %s", (project_id,)
    ).fetchone()
    assert missing == (True,)


@respx.mock
def test_sync_manifest_for_repo_malformed_logs_error(db_conn: psycopg.Connection) -> None:
    repo = _fake_repo("bad-manifest-proj")
    project_id = upsert_project(db_conn, repo)
    bad_yaml_b64 = "bmFtZTogYnJva2VuCiAgYmFkIGluZGVudDogW3VudGVybWluYXRlZA=="
    respx.get(f"{GITHUB_API_BASE}/repos/{repo.full_name}/contents/project.yaml").mock(
        return_value=httpx.Response(200, json={"content": bad_yaml_b64, "encoding": "base64"})
    )

    client = GitHubClient(token="fake-token")
    sync_manifest_for_repo(db_conn, client, repo, project_id)

    missing = db_conn.execute(
        "select manifest_missing from projects where id = %s", (project_id,)
    ).fetchone()
    assert missing == (True,)

    log = db_conn.execute(
        "select status from ingestion_log where project_id = %s and layer = 'graph'"
        " order by created_at desc limit 1",
        (project_id,),
    ).fetchone()
    assert log == ("error",)


def test_sync_static_analysis_for_file_requirements_txt(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("static-pkg-proj"))
    edges = sync_static_analysis_for_file(
        db_conn, project_id, "requirements.txt", "fastapi>=0.115\nhttpx\n"
    )
    assert edges == 2
    rows = db_conn.execute(
        "select identifier from dependencies where consumer_project_id = %s and kind = 'package'"
        " order by identifier",
        (project_id,),
    ).fetchall()
    assert [r[0] for r in rows] == ["fastapi", "httpx"]


def test_sync_static_analysis_for_file_fastapi_routes(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("static-route-proj"))
    content = '@app.get("/healthz")\ndef healthz():\n    return {"status": "ok"}\n'
    edges = sync_static_analysis_for_file(db_conn, project_id, "src/main.py", content)
    assert edges == 1
    row = db_conn.execute(
        "select identifier, source from exposed_interfaces where project_id = %s", (project_id,)
    ).fetchone()
    assert row == ("GET /healthz", "static_analysis")


def test_sync_static_analysis_for_file_hardcoded_url(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("static-url-proj"))
    content = 'requests.get("https://api.github.com/user/repos")'
    edges = sync_static_analysis_for_file(db_conn, project_id, "src/client.py", content)
    assert edges == 1
    row = db_conn.execute(
        "select identifier, kind from dependencies where consumer_project_id = %s", (project_id,)
    ).fetchone()
    assert row == ("https://api.github.com/user/repos", "http_call")


@respx.mock
def test_sync_commits_for_repo_ingests_and_respects_max_count(
    db_conn: psycopg.Connection,
) -> None:
    repo = _fake_repo("commits-proj")
    project_id = upsert_project(db_conn, repo)

    respx.get(f"{GITHUB_API_BASE}/repos/{repo.full_name}/commits", params={"page": "1"}).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "sha": "sha1",
                    "commit": {
                        "author": {"name": "pavle-K", "date": "2026-01-15T10:00:00Z"},
                        "message": "First commit",
                    },
                },
                {
                    "sha": "sha2",
                    "commit": {
                        "author": {"name": "pavle-K", "date": "2026-01-14T10:00:00Z"},
                        "message": "Second commit",
                    },
                },
            ],
        )
    )
    for sha in ("sha1", "sha2"):
        respx.get(f"{GITHUB_API_BASE}/repos/{repo.full_name}/commits/{sha}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "sha": sha,
                    "stats": {"additions": 1, "deletions": 0},
                    "files": [
                        {
                            "filename": "src/f.py",
                            "additions": 1,
                            "deletions": 0,
                            "patch": "@@ -0,0 +1 @@\n+x = 1\n",
                        }
                    ],
                },
            )
        )

    client = GitHubClient(token="fake-token")
    embedder = FakeEmbedder()
    llm = FakeLLMClient()

    counts = sync_commits_for_repo(db_conn, client, repo, project_id, embedder, llm, max_count=1)

    assert sum(counts.values()) == 1
    row = db_conn.execute(
        "select count(*) from commits where project_id = %s", (project_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == 1
