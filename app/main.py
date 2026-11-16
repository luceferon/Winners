"""Точка входа FastAPI-приложения «Winners»."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import bankroll, bets, settings as settings_api, sources, stats, system
from app.config import APP_TITLE, APP_VERSION, SEED_DEMO_ON_EMPTY, WEB_DIR
from app.database import SessionLocal, init_db
from app.services.logging_service import setup_logging

logger = logging.getLogger("winners")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    session = SessionLocal()
    try:
        if SEED_DEMO_ON_EMPTY:
            from app.seed import seed_demo_data

            result = seed_demo_data(session)
            if result.get("created"):
                logger.info("Загружены демонстрационные данные: %s", result.get("message"))
    finally:
        session.close()
    logger.info("Winners %s запущен", APP_VERSION)
    yield
    logger.info("Winners остановлен")


app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Локальная разработка: браузер не кэширует статику, чтобы модули не устаревали."""
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store"
    return response


for module in (stats, bets, sources, settings_api, system, bankroll):
    app.include_router(module.router)

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    # Статус 204 не допускает тело ответа: обычный Response без содержимого.
    return Response(status_code=204)
