from fastapi import FastAPI
from apps.backend.core.logging import setup_logging
from apps.backend.api.routes import router

setup_logging()
app = FastAPI(title="Jupiter Backend (Dify-RAG)", version="0.2.0")
app.include_router(router, prefix="/api")
