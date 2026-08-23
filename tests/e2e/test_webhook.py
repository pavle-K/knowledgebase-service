import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_queue_client_dep
from src.ingestion.queue_client import FakeQueueClient
from src.main import app

WEBHOOK_SECRET = "test-webhook-secret"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "payloads"


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


@pytest.fixture
def queue_client() -> FakeQueueClient:
    return FakeQueueClient()


@pytest.fixture
def client(queue_client: FakeQueueClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_queue_client_dep] = lambda: queue_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_invalid_signature_is_rejected(client: TestClient, queue_client: FakeQueueClient) -> None:
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
    assert queue_client.sent == []


def test_missing_signature_is_rejected(client: TestClient, queue_client: FakeQueueClient) -> None:
    payload = _load_unique_payload("push_readme_only.json")
    response = client.post("/webhook/github", json=payload, headers={"X-GitHub-Event": "push"})
    assert response.status_code == 401
    assert queue_client.sent == []


def test_invalid_json_payload_returns_400(
    client: TestClient, queue_client: FakeQueueClient
) -> None:
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
    assert queue_client.sent == []


def test_ping_event_is_acknowledged_without_enqueueing(
    client: TestClient, queue_client: FakeQueueClient
) -> None:
    response = _post_webhook(client, "ping", {})
    assert response.status_code == 200
    assert response.json() == {"status": "pong"}
    assert queue_client.sent == []


def test_unrecognized_event_is_acknowledged_without_enqueueing(
    client: TestClient, queue_client: FakeQueueClient
) -> None:
    response = _post_webhook(client, "issues", {"action": "opened"})
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event": "issues"}
    assert queue_client.sent == []


def test_push_event_is_enqueued_verbatim(client: TestClient, queue_client: FakeQueueClient) -> None:
    payload = _load_unique_payload("push_readme_only.json")
    response = _post_webhook(client, "push", payload)
    assert response.status_code == 200
    assert response.json() == {"status": "queued", "event": "push"}
    assert queue_client.sent == [("push", payload)]


def test_repository_event_is_enqueued(client: TestClient, queue_client: FakeQueueClient) -> None:
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
    assert response.json() == {"status": "queued", "event": "repository"}
    assert queue_client.sent == [("repository", payload)]


def test_release_event_is_enqueued(client: TestClient, queue_client: FakeQueueClient) -> None:
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
    assert response.json() == {"status": "queued", "event": "release"}
    assert queue_client.sent == [("release", payload)]
