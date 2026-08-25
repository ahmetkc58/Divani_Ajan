from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from karayol_agent import __version__
from karayol_agent.backend.routes import build_routers
from karayol_agent.orchestrator import EvrakOrchestrator, build_orchestrator

orchestrator = build_orchestrator()


def get_orchestrator() -> EvrakOrchestrator:
    """Resolve at request time so tests and alternate runtimes can replace it."""

    return orchestrator


def create_app() -> FastAPI:
    application = FastAPI(
        title="Karayolu Evrak Akıllı Ajan REST API",
        description=(
            "Bağımsız frontend istemcileri için kaynak doğrulamalı evrak işleme servisi"
        ),
        version=__version__,
        servers=[
            {
                "url": "http://127.0.0.1:8010",
                "description": "Yerel geliştirme backend'i",
            }
        ],
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(orchestrator.settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )
    api_router, legacy_router = build_routers(get_orchestrator)
    application.include_router(api_router)
    application.include_router(legacy_router)

    @application.get("/", include_in_schema=False)
    def service_root() -> dict[str, str]:
        return {
            "service": "karayol-evrak-agent-backend",
            "version": __version__,
            "api_base": "/api/v1",
            "openapi": "/docs",
        }

    return application


app = create_app()
