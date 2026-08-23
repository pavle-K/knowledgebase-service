"""POST /webhook/github - HMAC-verified GitHub webhook receiver.

Only validates and enqueues. The actual ingestion (push/repository/release handling,
src/ingestion/webhook_processor.py) runs on a separate SQS-triggered Lambda
(src/worker_handler.py) - a real push can take minutes to ingest (file fetches,
embeddings, LLM diff summaries), far past API Gateway's 30s integration timeout,
so this endpoint must return fast.
"""

from __future__ import annotations

import json
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.dependencies import get_queue_client_dep
from src.api.webhook_auth import verify_github_signature
from src.ingestion.queue_client import QueueClient

router = APIRouter()

QueueClientDep = Annotated[QueueClient, Depends(get_queue_client_dep)]


@router.post("/webhook/github")
async def github_webhook(request: Request, queue: QueueClientDep) -> dict[str, str]:
    raw_body = await request.body()
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not secret or not verify_github_signature(raw_body, signature, secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"status": "pong"}
    if event in ("push", "repository", "release"):
        queue.send(event, payload)
        return {"status": "queued", "event": event}

    return {"status": "ignored", "event": event}
