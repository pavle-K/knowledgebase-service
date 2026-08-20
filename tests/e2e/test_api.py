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
from tests.integration.conftest import db_conn, migrated_db  # noqa: F401

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
