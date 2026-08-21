import asyncio
from typing import Any

from src.lambda_handler import handler


class _FakeLambdaContext:
    aws_request_id = "test-request-id"


def _api_gateway_v2_event(method: str, path: str) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {},
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "stage": "$default",
            "requestId": "test-request-id",
            "routeKey": f"{method} {path}",
            "domainName": "example.com",
            "time": "01/Jan/2026:00:00:00 +0000",
            "timeEpoch": 0,
        },
        "isBase64Encoded": False,
    }


def test_handler_processes_healthz_via_api_gateway_v2_event() -> None:
    # Mangum's lifespan handling uses the legacy asyncio.get_event_loop(),
    # which needs a current loop already set in this thread. A real Lambda
    # cold start always has a fresh thread/loop; pytest's shared process
    # doesn't once another test's asyncio.run() has already closed one.
    asyncio.set_event_loop(asyncio.new_event_loop())

    event = _api_gateway_v2_event("GET", "/healthz")
    result = handler(event, _FakeLambdaContext())

    assert result["statusCode"] == 200
    assert result["body"] == '{"status":"ok"}'
