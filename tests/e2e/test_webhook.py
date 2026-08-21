import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import psycopg
import pytest
import respx
from fastapi.testclient import TestClient

from src.api.dependencies import get_conn_rw, get_embedder_dep, get_llm_dep
from src.ingestion.embedder import FakeEmbedder
from src.ingestion.exclusion import EXCLUDE_MARKER_PATH
from src.ingestion.github_client import GITHUB_API_BASE
from src.main import app
from src.query.synthesizer import FakeLLMClient
from tests.integration.conftest import db_conn, migrated_db  # noqa: F401

WEBHOOK_SECRET = "test-webhook-secret"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "payloads"


def _mock_not_excluded(full_name: str) -> None:
    respx.get(f"{GITHUB_API_BASE}/repos/{full_name}/contents/{EXCLUDE_MARKER_PATH}").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )


def _load_unique_payload(name: str) -> dict:
    payload = json.loads((FIXTURES / name).read_text())
    unique = uuid.uuid4().hex[:8]
    full_name = f"pavle-K/demo-repo-{unique}"
    payload["repository"]["name"] = f"demo-repo-{unique}"
    payload["repository"]["full_name"] = full_name
    payload["repository"]["html_url"] = f"https://github.com/{full_name}"
    return payload


def _sign(payload: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()


def _post_webhook(client: TestClient, event: str, payload: dict) -> httpx.Response:
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-Hub-Signature-256": _sign(body),
            "Content-Type": "application/json",
        },
    )


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-github-token")


@pytest.fixture
def client(db_conn: psycopg.Connection) -> Iterator[TestClient]:  # noqa: F811
    def override_conn_rw() -> Iterator[psycopg.Connection]:
        yield db_conn

    app.dependency_overrides[get_conn_rw] = override_conn_rw
    app.dependency_overrides[get_embedder_dep] = lambda: FakeEmbedder()
    app.dependency_overrides[get_llm_dep] = lambda: FakeLLMClient(response="commit summary")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_invalid_signature_is_rejected(client: TestClient) -> None:
    payload = _load_unique_payload("push_readme_only.json")
    body = json.dumps(payload).encode()
    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401


def test_missing_signature_is_rejected(client: TestClient) -> None:
    payload = _load_unique_payload("push_readme_only.json")
    response = client.post("/webhook/github", json=payload, headers={"X-GitHub-Event": "push"})
    assert response.status_code == 401


def test_ping_event_is_acknowledged(client: TestClient) -> None:
    response = _post_webhook(client, "ping", {})
    assert response.status_code == 200
    assert response.json() == {"status": "pong"}


@respx.mock
def test_readme_only_push_syncs_l1_and_leaves_code_untouched(
    client: TestClient,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    payload = _load_unique_payload("push_readme_only.json")
    full_name = payload["repository"]["full_name"]
    _mock_not_excluded(full_name)

    readme_b64 = base64.b64encode(b"# Demo\nUpdated content.\n").decode()
    respx.get(f"{GITHUB_API_BASE}/repos/{full_name}/contents/README.md").mock(
        return_value=httpx.Response(200, json={"content": readme_b64, "encoding": "base64"})
    )

    response = _post_webhook(client, "push", payload)

    assert response.status_code == 200
    body = response.json()
    assert body["documents_synced"] == 1
    assert body["code_synced"] == 0
    assert body["commits_synced"] == 0

    project_row = db_conn.execute(
        "select id from projects where repo_url = %s", (payload["repository"]["html_url"],)
    ).fetchone()
    assert project_row is not None
    project_id = project_row[0]

    doc_count = db_conn.execute(
        "select count(*) from documents where project_id = %s", (project_id,)
    ).fetchone()
    assert doc_count is not None
    assert doc_count[0] > 0

    code_count = db_conn.execute(
        "select count(*) from code_chunks where project_id = %s", (project_id,)
    ).fetchone()
    assert code_count is not None
    assert code_count[0] == 0


@respx.mock
def test_code_push_syncs_code_and_commit_layers(
    client: TestClient,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    payload = _load_unique_payload("push_code_change.json")
    full_name = payload["repository"]["full_name"]
    sha = payload["commits"][0]["id"]
    _mock_not_excluded(full_name)

    code_b64 = base64.b64encode(b"def rate_limit():\n    return True\n").decode()
    respx.get(f"{GITHUB_API_BASE}/repos/{full_name}/contents/src/app.py").mock(
        return_value=httpx.Response(200, json={"content": code_b64, "encoding": "base64"})
    )
    respx.get(f"{GITHUB_API_BASE}/repos/{full_name}/commits/{sha}").mock(
        return_value=httpx.Response(
            200,
            json={
                "sha": sha,
                "commit": {"author": {"name": "pavle-K", "date": "2026-01-15T10:00:00Z"}},
                "stats": {"additions": 2, "deletions": 0},
                "files": [
                    {
                        "filename": "src/app.py",
                        "additions": 2,
                        "deletions": 0,
                        "patch": "@@ -0,0 +1,2 @@\n+def rate_limit():\n+    return True\n",
                    }
                ],
            },
        )
    )

    response = _post_webhook(client, "push", payload)

    assert response.status_code == 200
    body = response.json()
    assert body["code_synced"] == 1
    assert body["commits_synced"] == 1
    assert body["documents_synced"] == 0

    project_row = db_conn.execute(
        "select id from projects where repo_url = %s", (payload["repository"]["html_url"],)
    ).fetchone()
    assert project_row is not None
    project_id = project_row[0]

    code_count = db_conn.execute(
        "select count(*) from code_chunks where project_id = %s", (project_id,)
    ).fetchone()
    assert code_count is not None
    assert code_count[0] > 0

    commit_row = db_conn.execute(
        "select sha from commits where project_id = %s", (project_id,)
    ).fetchone()
    assert commit_row is not None
    assert commit_row[0] == sha


def test_unrecognized_event_is_acknowledged_without_processing(client: TestClient) -> None:
    response = _post_webhook(client, "issues", {"action": "opened"})
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event": "issues"}


def test_invalid_json_payload_returns_400(client: TestClient) -> None:
    body = b"not valid json"
    response = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


def test_repository_event_upserts_project(client: TestClient, db_conn: psycopg.Connection) -> None:  # noqa: F811
    unique = uuid.uuid4().hex[:8]
    full_name = f"pavle-K/repo-event-{unique}"
    payload = {
        "action": "edited",
        "repository": {
            "name": f"repo-event-{unique}",
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "description": "updated description",
            "default_branch": "main",
            "private": False,
            "fork": False,
        },
    }
    response = _post_webhook(client, "repository", payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "event": "repository"}

    row = db_conn.execute(
        "select description from projects where repo_url = %s",
        (f"https://github.com/{full_name}",),
    ).fetchone()
    assert row == ("updated description",)


def test_release_event_is_acknowledged(client: TestClient) -> None:
    unique = uuid.uuid4().hex[:8]
    full_name = f"pavle-K/release-event-{unique}"
    payload = {
        "action": "published",
        "repository": {
            "name": f"release-event-{unique}",
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "description": None,
            "default_branch": "main",
            "private": False,
            "fork": False,
        },
    }
    response = _post_webhook(client, "release", payload)
    assert response.status_code == 200
    assert response.json() == {"status": "acknowledged", "event": "release"}


@respx.mock
def test_project_yaml_push_syncs_graph_layer(
    client: TestClient,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    unique = uuid.uuid4().hex[:8]
    full_name = f"pavle-K/manifest-repo-{unique}"
    payload = {
        "repository": {
            "name": f"manifest-repo-{unique}",
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "description": "demo",
            "default_branch": "main",
            "private": False,
            "fork": False,
        },
        "commits": [
            {
                "id": "eee333",
                "message": "Add project.yaml",
                "timestamp": "2026-01-15T10:00:00Z",
                "author": {"name": "pavle-K"},
                "added": ["project.yaml"],
                "removed": [],
                "modified": [],
            }
        ],
    }
    _mock_not_excluded(full_name)
    manifest_b64 = base64.b64encode(b"name: demo\ntechnologies: [python]\n").decode()
    respx.get(f"{GITHUB_API_BASE}/repos/{full_name}/contents/project.yaml").mock(
        return_value=httpx.Response(200, json={"content": manifest_b64, "encoding": "base64"})
    )

    response = _post_webhook(client, "push", payload)

    assert response.status_code == 200
    body = response.json()
    assert "graph" in body["layers"].split(",")

    project_row = db_conn.execute(
        "select id, manifest_missing from projects where repo_url = %s",
        (f"https://github.com/{full_name}",),
    ).fetchone()
    assert project_row is not None
    assert project_row[1] is False


def test_push_only_ingests_commits_that_touch_code(
    client: TestClient,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    unique = uuid.uuid4().hex[:8]
    full_name = f"pavle-K/multi-commit-{unique}"
    payload = {
        "repository": {
            "name": f"multi-commit-{unique}",
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "description": "demo",
            "default_branch": "main",
            "private": False,
            "fork": False,
        },
        "commits": [
            {
                "id": "readme111",
                "message": "Docs only",
                "timestamp": "2026-01-15T10:00:00Z",
                "author": {"name": "pavle-K"},
                "added": [],
                "removed": [],
                "modified": ["README.md"],
            }
        ],
    }
    with respx.mock:
        _mock_not_excluded(full_name)
        readme_b64 = base64.b64encode(b"# Demo\n").decode()
        respx.get(f"{GITHUB_API_BASE}/repos/{full_name}/contents/README.md").mock(
            return_value=httpx.Response(200, json={"content": readme_b64, "encoding": "base64"})
        )
        response = _post_webhook(client, "push", payload)

    assert response.status_code == 200
    body = response.json()
    assert body["commits_synced"] == 0  # README-only commit never reaches L4


@respx.mock
def test_push_to_excluded_repo_purges_existing_data_and_skips_ingestion(
    client: TestClient,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    payload = _load_unique_payload("push_readme_only.json")
    full_name = payload["repository"]["full_name"]
    html_url = payload["repository"]["html_url"]

    # Pre-existing data from before the repo was excluded.
    project_row = db_conn.execute(
        """
        insert into projects (name, repo_url, source, default_branch, is_private)
        values (%s, %s, 'github', 'main', false)
        returning id
        """,
        (payload["repository"]["name"], html_url),
    ).fetchone()
    assert project_row is not None
    project_id = project_row[0]
    db_conn.execute(
        """
        insert into documents
            (project_id, doc_type, source_path, chunk_index, content, content_hash)
        values (%s, 'readme', 'README.md', 0, 'old content', 'hash1')
        """,
        (project_id,),
    )

    # Only the exclusion-marker check is mocked - any other GitHub call
    # respx doesn't recognize fails the test, proving nothing else ran.
    respx.get(f"{GITHUB_API_BASE}/repos/{full_name}/contents/{EXCLUDE_MARKER_PATH}").mock(
        return_value=httpx.Response(200, json={"content": "", "encoding": "base64"})
    )

    response = _post_webhook(client, "push", payload)

    assert response.status_code == 200
    assert response.json() == {
        "status": "excluded",
        "documents": 1,
        "code_chunks": 0,
        "commits": 0,
        "exposed_interfaces": 0,
        "dependencies": 0,
    }

    doc_count = db_conn.execute(
        "select count(*) from documents where project_id = %s", (project_id,)
    ).fetchone()
    assert doc_count == (0,)
