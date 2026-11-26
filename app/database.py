"""Подключение к базе данных, сессии и инициализация схемы."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Table, create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей."""


def build_engine(url: str = DATABASE_URL) -> Engine:
    """Создать движок БД. Для SQLite отключаем проверку потока (фоновые задачи)."""
    kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_engine(url, **kwargs)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: сессия БД на время запроса."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine: Engine | None = None) -> None:
    """Создать таблицы, если их нет, и синхронизировать схему существующих."""
    from app import models  # noqa: F401  (регистрация моделей в метаданных)

    target = target_engine or engine
    Base.metadata.create_all(target)
    _upgrade_schema(target)


def _upgrade_schema(target_engine: Engine) -> None:
    """Привести существующую SQLite-схему в соответствие с моделями.

    Проект использует create_all без миграций: create_all не меняет уже
    существующие таблицы. Поэтому при изменении моделей схема «дрейфует» —
    в таблицах остаются удалённые колонки, что ломает вставку (NOT NULL без
    значения). Здесь мы:
      * добавляем недостающие колонки (например, kind для экспрессов);
      * пересоздаём таблицы с лишними (удалёнными из модели) колонками,
        сохраняя данные по общим колонкам;
      * удаляем таблицы, которых больше нет в моделях (events, parse_logs).
    """
    if target_engine.dialect.name != "sqlite":
        return
    with target_engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(bets)")}
        if columns and "kind" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE bets ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'single'"
            )
        if columns and "telegram_message_id" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE bets ADD COLUMN telegram_message_id INTEGER"
            )

        existing = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table in Base.metadata.sorted_tables:
            if table.name in existing:
                _rebuild_if_drifted(conn, table)

        defined = {table.name for table in Base.metadata.sorted_tables}
        for name in sorted(existing - defined):
            if name.startswith("sqlite_"):
                continue
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{name}"')


def _rebuild_if_drifted(conn: Connection, table: Table) -> None:
    """Пересоздать таблицу, если в ней остались колонки, удалённые из модели.

    Данные сохраняются по общим колонкам. Порядок шагов (копия → DROP →
    CREATE → вставка) безопасен для SQLite: имена индексов освобождаются
    вместе с удаляемой таблицей, а ссылки других таблиц не переписываются
    """
    actual = [row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')]
    expected = [column.name for column in table.columns]
    if not [name for name in actual if name not in expected]:
        return

    common = [name for name in expected if name in actual]
    backup = f"_{table.name}_backup"
    cols = ", ".join(f'"{name}"' for name in common)

    conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{backup}"')
    conn.exec_driver_sql(f'CREATE TABLE "{backup}" AS SELECT {cols} FROM "{table.name}"')
    conn.exec_driver_sql(f'DROP TABLE "{table.name}"')
    table.create(bind=conn)
    if common:
        conn.exec_driver_sql(
            f'INSERT INTO "{table.name}" ({cols}) SELECT {cols} FROM "{backup}"'
        )
    conn.exec_driver_sql(f'DROP TABLE "{backup}"')
