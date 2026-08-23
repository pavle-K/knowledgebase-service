"""Queue transport for handing GitHub webhook events from the API Lambda to the
worker Lambda (src/worker_handler.py) - see src/api/webhook.py for why this exists.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol


class QueueClient(Protocol):
    def send(self, event: str, payload: dict[str, Any]) -> None: ...


class SQSQueueClient:
    def __init__(self, queue_url: str) -> None:
        import boto3

        self._sqs = boto3.client("sqs")
        self._queue_url = queue_url

    def send(self, event: str, payload: dict[str, Any]) -> None:
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"event": event, "payload": payload}),
        )


class FakeQueueClient:
    """Records sent events in memory, no network calls. For tests only."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send(self, event: str, payload: dict[str, Any]) -> None:
        self.sent.append((event, payload))


def get_queue_client() -> QueueClient:
    queue_url = os.environ.get("WEBHOOK_QUEUE_URL")
    if not queue_url:
        raise RuntimeError("WEBHOOK_QUEUE_URL is not set")
    return SQSQueueClient(queue_url)
