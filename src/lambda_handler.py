"""Lambda entry point: adapts the FastAPI app to the Lambda runtime via Mangum."""

from __future__ import annotations

from mangum import Mangum

from src.main import app

handler = Mangum(app)
