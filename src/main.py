from fastapi import FastAPI

from src.api.auth import auth_middleware
from src.api.routes import router as api_router
from src.api.webhook import router as webhook_router
from src.mcp_server import build_mcp

app = FastAPI(title="knowledgebase-service")
app.middleware("http")(auth_middleware)
app.include_router(api_router)
app.include_router(webhook_router)


@app.get("/healthz", operation_id="healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# Mounted at /mcp, same Bearer auth as everything else (not in EXEMPT_PATHS).
# The lifespan reassignment below is required - without it the MCP session
# manager never starts and every /mcp request fails.
mcp = build_mcp(app)
mcp_app = mcp.http_app(stateless_http=True, json_response=True)
app.router.lifespan_context = mcp_app.router.lifespan_context
app.mount("/", mcp_app)
