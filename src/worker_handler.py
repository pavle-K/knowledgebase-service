"""SQS worker entry point: consumes GitHub webhook events enqueued by src/api/webhook.py
and runs the actual ingestion (src/ingestion/webhook_processor.py).

No FastAPI/Mangum here - this Lambda is invoked directly by SQS, not behind API Gateway,
so it isn't bound by the 30s API Gateway integration timeout. Batch size is 1 (see
infra/lambda.tf), so a raised exception fails just that message; SQS's own visibility
timeout / redrive-to-DLQ handles retries.
"""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg

from src.ingestion.embedder import get_embedder
from src.ingestion.github_client import GitHubClient
from src.ingestion.webhook_processor import process_event
from src.query.synthesizer import get_llm_client


def handler(event: dict[str, Any], context: Any) -> None:
    for record in event["Records"]:
        _process_record(record)


def _process_record(record: dict[str, Any]) -> None:
    body = json.loads(record["body"])
    conn = psycopg.connect(os.environ["DATABASE_URL_RW"])
    client = GitHubClient(token=os.environ["GITHUB_TOKEN"])
    try:
        process_event(
            conn, client, get_embedder(), get_llm_client(), body["event"], body["payload"]
        )
    finally:
        client.close()
        conn.close()
