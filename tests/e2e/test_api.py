import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_conn, get_embedder_dep, get_llm_dep
from src.ingestion.documents import upsert_project
from src.ingestion.embedder import FakeEmbedder
from src.ingestion.github_client import RepoInfo
from src.main import app
from src.query.synthesizer import FakeLLMClient
from tests.integration.conftest import MigratedDb, db_conn, migrated_db  # noqa: F401

API_AUTH_KEY = "test-auth-key"


@pytest.fixture(autouse=True)
def _set_auth_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_AUTH_KEY", API_AUTH_KEY)


@pytest.fixture
def client(db_conn: psycopg.Connection) -> Iterator[TestClient]:  # noqa: F811
    def override_get_conn() -> Iterator[psycopg.Connection]:
        yield db_conn

    app.dependency_overrides[get_conn] = override_get_conn
    app.dependency_overrides[get_embedder_dep] = lambda: FakeEmbedder()
    app.dependency_overrides[get_llm_dep] = lambda: FakeLLMClient(response="test summary")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _fake_repo() -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"api-test-{unique}",
        full_name=f"pavle-K/api-test-{unique}",
        html_url=f"https://github.com/pavle-K/api-test-{unique}",
        description=None,
        default_branch="main",
        is_private=False,
        fork=False,
    )


def test_healthz_works_without_auth() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_query_rejected_without_auth(client: TestClient) -> None:
    response = client.post("/v1/query", json={"query": "test"})
    assert response.status_code == 401


def test_query_rejected_with_wrong_token(client: TestClient) -> None:
    response = client.post(
        "/v1/query", json={"query": "test"}, headers={"Authorization": "Bearer wrong-key"}
    )
    assert response.status_code == 401


def test_impact_rejected_without_auth(client: TestClient) -> None:
    response = client.post("/v1/impact", json={"project": "x", "interface": "y"})
    assert response.status_code == 401


def test_query_succeeds_and_matches_documented_schema(client: TestClient) -> None:
    response = client.post(
        "/v1/query",
        json={"query": "what does this project do"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "summary",
        "intent",
        "data",
        "confidence",
        "coverage_note",
        "execution_time_ms",
    }
    assert body["intent"] in ("vector", "sql", "graph", "hybrid", "time")
    assert isinstance(body["execution_time_ms"], int)


def test_query_over_max_length_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/query",
        json={"query": "x" * 2001},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 422


def test_query_respects_layers_filter(client: TestClient) -> None:
    response = client.post(
        "/v1/query",
        json={"query": "where do I implement rate limiting", "layers": ["code"]},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200


def test_impact_is_deterministic_for_project_with_no_dependents(
    client: TestClient,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    repo = _fake_repo()
    upsert_project(db_conn, repo)

    response = client.post(
        "/v1/impact",
        json={"project": repo.name, "interface": "GET /nope"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project_found"] is True
    assert body["interface_declared"] is False
    assert body["impacted"] == []


def test_impact_unknown_project(client: TestClient) -> None:
    response = client.post(
        "/v1/impact",
        json={"project": "definitely-does-not-exist", "interface": "x"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json()["project_found"] is False


# --- Private-project visibility, end to end over the real roles ---

API_ADMIN_KEY = "test-admin-key"


@pytest.fixture
def tiered_client(
    migrated_db: MigratedDb,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str]]:
    """No get_conn override: the request's tier picks a real database role."""
    monkeypatch.setenv("API_ADMIN_KEY", API_ADMIN_KEY)
    monkeypatch.setenv("DATABASE_URL_RO", migrated_db.app_ro_url)
    monkeypatch.setenv("DATABASE_URL_RO_PUBLIC", migrated_db.app_ro_public_url)

    unique = uuid.uuid4().hex[:8]
    name = f"private-repo-{unique}"
    with psycopg.connect(migrated_db.admin_url) as conn:
        conn.execute(
            """
            insert into projects (name, repo_url, source, default_branch, is_private)
            values (%s, %s, 'github', 'main', true)
            """,
            (name, f"https://github.com/pavle-K/{name}"),
        )
        conn.commit()

    app.dependency_overrides[get_embedder_dep] = lambda: FakeEmbedder()
    app.dependency_overrides[get_llm_dep] = lambda: FakeLLMClient(response="test summary")
    try:
        yield TestClient(app), name
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(migrated_db.admin_url) as conn:
            conn.execute("delete from projects where name = %s", (name,))
            conn.commit()


def test_public_key_cannot_see_a_private_project(
    tiered_client: tuple[TestClient, str],
) -> None:
    client, private_name = tiered_client
    response = client.post(
        "/v1/impact",
        json={"project": private_name, "interface": "GET /x"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json()["project_found"] is False


def test_admin_key_can_see_a_private_project(
    tiered_client: tuple[TestClient, str],
) -> None:
    client, private_name = tiered_client
    response = client.post(
        "/v1/impact",
        json={"project": private_name, "interface": "GET /x"},
        headers={"Authorization": f"Bearer {API_ADMIN_KEY}"},
    )
    assert response.status_code == 200
    assert response.json()["project_found"] is True


# --- Scoped lookup endpoints (dependencies/projects/search) ---

_SCOPED_ENDPOINTS = [
    ("/v1/dependencies", {"project": "x"}),
    ("/v1/projects", {}),
    ("/v1/projects/info", {"project": "x"}),
    ("/v1/search/docs", {"query": "x"}),
    ("/v1/search/code", {"query": "x"}),
    ("/v1/search/commits", {"query": "x"}),
    ("/v1/commits/recent", {}),
]


@pytest.mark.parametrize("path,body", _SCOPED_ENDPOINTS)
def test_scoped_endpoint_rejected_without_auth(client: TestClient, path: str, body: dict) -> None:
    response = client.post(path, json=body)
    assert response.status_code == 401


def test_get_dependencies_unknown_project(client: TestClient) -> None:
    response = client.post(
        "/v1/dependencies",
        json={"project": "does-not-exist"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json() == {"project_found": False, "dependencies": []}


def test_list_projects_returns_seeded_project(
    client: TestClient,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    repo = _fake_repo()
    upsert_project(db_conn, repo)

    response = client.post(
        "/v1/projects", json={}, headers={"Authorization": f"Bearer {API_AUTH_KEY}"}
    )
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert repo.name in names


def test_get_project_info_unknown_project(client: TestClient) -> None:
    response = client.post(
        "/v1/projects/info",
        json={"project": "does-not-exist"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json()["found"] is False


def test_search_docs_succeeds(client: TestClient) -> None:
    response = client.post(
        "/v1/search/docs",
        json={"query": "what does this do"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_search_code_succeeds(client: TestClient) -> None:
    response = client.post(
        "/v1/search/code",
        json={"query": "rate limiting"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_search_commits_succeeds(client: TestClient) -> None:
    response = client.post(
        "/v1/search/commits",
        json={"query": "auth changes"},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_get_recent_commits_succeeds(client: TestClient) -> None:
    response = client.post(
        "/v1/commits/recent",
        json={},
        headers={"Authorization": f"Bearer {API_AUTH_KEY}"},
    )
    assert response.status_code == 200
    assert response.json() == []
