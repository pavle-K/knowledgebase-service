"""Bearer token auth, applied to everything except /healthz and /webhook/github.

Two tiers: API_ADMIN_KEY reads the whole corpus, API_AUTH_KEY reads public
projects only. The tier is recorded on request.state and turned into a database
role by dependencies.get_conn - the filtering itself is enforced by row-level
security, not here.

/webhook/github uses HMAC (X-Hub-Signature-256) instead, verified separately
in the webhook route itself - it's exempt here so that check even gets a chance
to run.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.responses import JSONResponse

from src.query.synthesizer import get_langfuse_client

EXEMPT_PATHS = {"/healthz", "/webhook/github"}


def _matches(auth_header: str, key: str | None) -> bool:
    return bool(key) and hmac.compare_digest(auth_header, f"Bearer {key}")


async def auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if _matches(auth_header, os.environ.get("API_ADMIN_KEY")):
        request.state.privileged = True
    elif _matches(auth_header, os.environ.get("API_AUTH_KEY")):
        request.state.privileged = False
    else:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    try:
        return await call_next(request)
    finally:
        # Langfuse batches traces in a background thread; Lambda can freeze the
        # execution environment the instant this handler returns, silently
        # dropping anything still queued. Flush before that happens. A no-op
        # when Langfuse isn't configured (get_langfuse_client() returns None).
        langfuse = get_langfuse_client()
        if langfuse is not None:
            langfuse.flush()
