from fastapi import FastAPI
from apps.backend.core.logging import setup_logging
from apps.backend.core.tls import apply_tls_env
from apps.backend.api.routes import router

setup_logging()
apply_tls_env()
app = FastAPI(title="Sequoia Backend (Dify-RAG)", version="0.2.0")
app.include_router(router, prefix="/api")
