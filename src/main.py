from fastapi import FastAPI

from src.api.auth import auth_middleware
from src.api.routes import router as api_router
from src.api.webhook import router as webhook_router

app = FastAPI(title="knowledgebase-service")
app.middleware("http")(auth_middleware)
app.include_router(api_router)
app.include_router(webhook_router)


@app.get("/healthz", operation_id="healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
