from __future__ import annotations

from fastapi import FastAPI

from app.api.routes_admin import router as admin_router
from app.api.routes_chat import router as chat_router
from app.api.routes_health import router as health_router
from app.persistence.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="Vehicle Finance Chatbot",
        description=(
            "Mobile-banking taşıt finansmanı ön başvuru asistanı. "
            "Local-LLM uyumlu, RAG destekli, deterministic rule validation."
        ),
        version="0.1.0",
    )
    init_db()
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(admin_router)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    from app.config import get_settings

    s = get_settings()
    uvicorn.run("app.main:app", host=s.app_host, port=s.app_port, reload=False)
