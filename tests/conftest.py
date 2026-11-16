"""Общие фикстуры pytest для приложения «Winners».

Тесты полностью изолированы: используется временная папка данных,
автосев демонстрационных данных отключён, а каждый тест получает
собственную SQLite-базу.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ВАЖНО: переменные окружения задаются до импорта модулей приложения.
os.environ["WINNERS_DATA_DIR"] = tempfile.mkdtemp(prefix="winners-tests-")
os.environ["WINNERS_SEED_DEMO"] = "0"

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app import models  # noqa: E402,F401  (регистрация таблиц в метаданных)
from app.database import Base, get_db  # noqa: E402


@pytest.fixture()
def engine(tmp_path):
    """Отдельный движок SQLite с созданными таблицами на каждый тест."""
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session_factory(engine):
    """Фабрика сессий, привязанная к тестовому движку."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture()
def db(session_factory):
    """Готовая сессия БД для тестов сервисов и парсера."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine, session_factory):
    """HTTP-клиент FastAPI с подменённой зависимостью БД (без lifespan)."""
    from fastapi.testclient import TestClient

    from app.main import app

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()
