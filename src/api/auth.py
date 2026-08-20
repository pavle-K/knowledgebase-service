"""Bearer token auth, applied to everything except /healthz and /webhook/github.

/webhook/github uses HMAC (X-Hub-Signature-256) instead, verified separately
in the webhook route itself - it's exempt here so that check even gets a chance
to run.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.responses import JSONResponse

EXEMPT_PATHS = {"/healthz", "/webhook/github"}


async def auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    expected = os.environ.get("API_AUTH_KEY")
    auth_header = request.headers.get("Authorization", "")
    if not expected or auth_header != f"Bearer {expected}":
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)
