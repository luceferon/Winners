"""Регрессия: init_db приводит дрейфующую SQLite-схему к текущим моделям.

create_all не удаляет существующие колонки, поэтому после удаления полей из
модели в базе остаются лишние NOT NULL-колонки, и вставка падает. Тест
воспроизводит такую устаревшую схему и проверяет, что миграция её исправляет.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import init_db
from app.models import Bet, Source

LEGACY_SOURCES = """
CREATE TABLE sources (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    kind VARCHAR(16) NOT NULL DEFAULT 'other',
    url VARCHAR(500),
    provider_key VARCHAR(60),
    api_key VARCHAR(200),
    reliability FLOAT,
    enabled BOOLEAN NOT NULL,
    notes TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""

LEGACY_BETS = """
CREATE TABLE bets (
    id INTEGER NOT NULL PRIMARY KEY,
    event_id INTEGER,
    sport VARCHAR(60) NOT NULL,
    event_name VARCHAR(300) NOT NULL,
    normalized_event_name VARCHAR(300) NOT NULL,
    prediction VARCHAR(120),
    coefficient FLOAT NOT NULL,
    stake FLOAT NOT NULL,
    source_id INTEGER,
    source_name VARCHAR(120),
    status VARCHAR(24) NOT NULL,
    payout FLOAT NOT NULL,
    comment TEXT,
    created_at DATETIME NOT NULL,
    settled_at DATETIME,
    auto_settled BOOLEAN NOT NULL,
    needs_review BOOLEAN NOT NULL,
    review_reason VARCHAR(300),
    match_confidence FLOAT,
    last_sync_at DATETIME,
    kind VARCHAR(16) NOT NULL DEFAULT 'single'
)
"""


def test_init_db_removes_legacy_columns_and_preserves_data(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(LEGACY_BETS)
        conn.exec_driver_sql("CREATE TABLE events (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql(
            "INSERT INTO bets (id, sport, event_name, normalized_event_name, coefficient,"
            " stake, status, payout, created_at, auto_settled, needs_review)"
            " VALUES (1, 'Хоккей', 'A - B', 'a b', 1.6, 100.0, 'pending', 0.0,"
            " '2026-11-16 08:00:00', 0, 0)"
        )

    init_db(engine)

    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(bets)")}
        tables = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        count = conn.exec_driver_sql("SELECT count(*) FROM bets").scalar()

    assert "auto_settled" not in columns
    assert "event_id" not in columns
    assert "events" not in tables
    assert count == 1

    # Новая вставка больше не падает на legacy NOT NULL-колонках.
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(
            Bet(
                sport="Хоккей",
                event_name="C - D",
                normalized_event_name="c d",
                coefficient=1.5,
                stake=50.0,
            )
        )
        session.commit()
        assert session.query(Bet).count() == 2

    engine.dispose()


def test_init_db_removes_legacy_source_columns_and_preserves_data(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy_sources.db').as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(LEGACY_SOURCES)
        conn.exec_driver_sql(
            "INSERT INTO sources (id, name, kind, url, provider_key, api_key, reliability,"
            " enabled, notes, created_at, updated_at)"
            " VALUES (1, 'Канал', 'tipster', 'https://t.me/', 'espn', 'secret', 88.0,"
            " 1, 'заметка', '2026-11-16 08:00:00', '2026-11-16 08:00:00')"
        )

    init_db(engine)

    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sources)")}
        count = conn.exec_driver_sql("SELECT count(*) FROM sources").scalar()
        row = conn.exec_driver_sql(
            "SELECT name, url, enabled, notes FROM sources WHERE id = 1"
        ).one()

    assert not {"kind", "provider_key", "api_key", "reliability"} & columns
    assert count == 1
    assert row == ("Канал", "https://t.me/", 1, "заметка")

    # Новая вставка больше не падает на legacy NOT NULL-колонках.
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(Source(name="Новый источник"))
        session.commit()
        assert session.query(Source).count() == 2

    engine.dispose()
