"""FastAPI Application entry point (IMPLEMENTATION_PLAN.md P9/P10).
Provides the HTTP API surface for document upload, job status, review queues,
Excel consumption, and static source-document image serving for the React UI.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pharma_di.api.routes_documents import router as documents_router
from pharma_di.api.routes_review import router as review_router
from pharma_di.workers.jobs import default_job_manager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and graceful shutdown lifecycle."""
    yield
    default_job_manager.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pharma Stock & Sale Intelligence API",
        description="Local-only, privacy-first document intelligence pipeline for pharmaceutical distributor statements.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(documents_router)
    app.include_router(review_router)

    # Serve source document images so the React review UI can display them
    # alongside extracted rows.  Mounts data/ as /api/static.
    # React UI constructs: GET /api/static/input/<basename>
    try:
        from fastapi.staticfiles import StaticFiles
        from pharma_di.config import REPO_ROOT

        data_dir = REPO_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/api/static", StaticFiles(directory=str(data_dir), html=False), name="static_data")
    except Exception:
        pass  # StaticFiles optional — UI degrades gracefully to "image not available"

    @app.get("/health", tags=["system"], summary="Health check endpoint")
    async def health_check():
        return {"status": "ok", "service": "pharma-di-api", "version": "0.1.0"}

    @app.get("/", tags=["system"], summary="API Root")
    async def root():
        return {
            "name": "Pharma Stock & Sale Intelligence API",
            "version": "0.1.0",
            "docs": "/docs",
            "endpoints": [
                "/api/documents/upload",
                "/api/jobs",
                "/api/documents",
                "/api/review-queue",
                "/api/static/<filename>",
                "/health",
            ],
        }

    return app


app = create_app()
