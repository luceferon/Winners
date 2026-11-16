"""Демонстрационные данные для первого запуска приложения."""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Bet, BetLeg, CashFlow, Source
from app.services.bets_service import create_bet, set_result
from app.services.timeutil import now_utc
from app.schemas import BetCreate

DEMO_SOURCES = [
    {
        "name": "Букмекер «Лига Ставок»",
        "url": "https://www.ligastavok.ru",
        "notes": "Основная линия, ставки на топовые матчи",
    },
    {
        "name": "Прогнозы Сергея",
        "url": "",
        "notes": "Личный прогнозист, делится в чате",
    },
    {
        "name": "Telegram «SportTips Daily»",
        "url": "https://t.me/",
        "notes": "Публичный канал с бесплатными прогнозами",
    },
    {
        "name": "Собственный анализ",
        "url": "",
        "notes": "Ставки по собственной модели",
    },
]

_FIXTURES: list[tuple[str, str, list[str]]] = [
    ("Футбол", "Зенит — Спартак", ["П1", "ТБ 2.5", "1X", "ТМ 3.5"]),
    ("Футбол", "ЦСКА — Локомотив", ["X", "П2", "ТМ 2.5", "1X"]),
    ("Футбол", "Реал Мадрид — Барселона", ["ТБ 2.5", "П1", "X2", "Ф1 (-1)"]),
    ("Футбол", "Манчестер Сити — Ливерпуль", ["П1", "ТБ 3.5", "1X", "П2"]),
    ("Футбол", "Бавария — Боруссия Дортмунд", ["ТБ 2.5", "П1", "X2"]),
    ("Футбол", "Атлетико — Севилья", ["ТМ 2.5", "X", "1X"]),
    ("Хоккей", "СКА — ЦСКА", ["П1", "ТБ 4.5", "1X"]),
    ("Хоккей", "Динамо Москва — Ак Барс", ["ТМ 5.5", "П2", "X2"]),
    ("Баскетбол", "Лейкерс — Селтикс", ["П1", "ТБ 215.5"]),
    ("Баскетбол", "ЦСКА — Зенит", ["П2", "ТМ 165.5"]),
    ("Теннис", "Джокович — Алькарас", ["П1", "ТБ 3.5"]),
    ("Теннис", "Медведев — Зверев", ["П2", "ТМ 3.5"]),
    ("Волейбол", "Зенит Казань — Кузбасс", ["П1", "ТМ 3.5"]),
    ("Киберспорт", "Team Spirit — NAVI", ["П1", "ТБ 2.5"]),
    ("Единоборства", "Ислам Махачев — Чарльз Оливейра", ["П1"]),
    ("Гандбол", "Барселона — Киль", ["ТБ 55.5", "П1"]),
]

# Ожидаемые для демонстрации активные ставки: (часы от сейчас, прогноз)
_ACTIVE = [
    (+5, "П1"),
    (+26, "ТБ 2.5"),
    (-0.25, "1X"),
    (-0.5, "П2"),
    (-4, None),
]


def is_empty(db: Session) -> bool:
    """Пустая ли база (нет ни ставок, ни источников)."""
    bets = db.execute(select(func.count(Bet.id))).scalar_one()
    sources = db.execute(select(func.count(Source.id))).scalar_one()
    return not bets and not sources


def seed_demo_data(db: Session, *, force: bool = False) -> dict:
    """Заполнить базу демонстрационными данными."""
    if not force and not is_empty(db):
        return {"created": False, "reason": "База уже содержит данные"}

    rng = random.Random(20240115)
    now = now_utc()

    sources: list[Source] = []
    for payload in DEMO_SOURCES:
        existing = db.execute(select(Source).where(Source.name == payload["name"])).scalar_one_or_none()
        if existing is None:
            existing = Source(**payload)
            db.add(existing)
        sources.append(existing)
    db.commit()

    created_bets = 0
    # --- завершённые ставки за последние 45 дней ---------------------------
    # Фиксированный набор результатов: демо-журнал выглядит сбалансированно
    # (примерно 47% выигрышей, небольшой плюс) и воспроизводится от запуска к запуску.
    outcomes: list[str] = ["won"] * 14 + ["lost"] * 14 + ["push"] * 2
    rng.shuffle(outcomes)

    for index in range(len(outcomes)):
        sport, title, predictions = _FIXTURES[index % len(_FIXTURES)]
        prediction = rng.choice(predictions)
        coefficient = round(rng.uniform(1.45, 3.4), 2)
        stake = float(rng.choice([300, 500, 750, 1000, 1500, 2000, 2500]))
        source = sources[index % len(sources)]
        created = now - timedelta(days=rng.uniform(1, 45), hours=rng.uniform(0, 20))
        settled = created + timedelta(hours=rng.uniform(2, 8))

        bet = create_bet(
            db,
            BetCreate(
                sport=sport,
                event_name=title,
                prediction=prediction,
                coefficient=coefficient,
                stake=stake,
                source_id=source.id,
                comment=rng.choice(
                    ["", "По линии на открытии", "Догон", "Уверенный заход", "Пробная ставка"]
                )
                or None,
                created_at=created,
            ),
        )
        status = outcomes[index]
        payout = round(stake * coefficient, 2) if status == "won" else (stake if status == "push" else 0.0)
        set_result(db, bet, status, payout=payout, auto=False)
        bet.settled_at = settled
        db.commit()
        created_bets += 1

    # --- активные ставки --------------------------------------------------
    for offset_hours, prediction in _ACTIVE:
        sport, title, _ = _FIXTURES[rng.randrange(len(_FIXTURES))]
        coefficient = round(rng.uniform(1.6, 2.9), 2)
        stake = float(rng.choice([500, 1000, 1500]))
        source = sources[rng.randrange(len(sources))]
        start_time = now + timedelta(hours=offset_hours)

        create_bet(
            db,
            BetCreate(
                sport=sport,
                event_name=title,
                prediction=prediction,
                coefficient=coefficient,
                stake=stake,
                source_id=source.id,
                comment="Активная ставка (демо)",
                created_at=min(start_time, now) - timedelta(hours=1),
            ),
        )
        created_bets += 1

    return {
        "created": True,
        "sources": len(sources),
        "bets": created_bets,
        "message": f"Загружено демо-данных: ставок {created_bets}, источников {len(sources)}",
    }


def clear_all_data(db: Session, *, keep_sources: bool = False) -> dict:
    """Удалить все ставки и операции по счёту."""
    bets = db.execute(select(func.count(Bet.id))).scalar_one()
    operations = db.execute(select(func.count(CashFlow.id))).scalar_one()

    db.execute(BetLeg.__table__.delete())
    db.execute(Bet.__table__.delete())
    db.execute(CashFlow.__table__.delete())
    if not keep_sources:
        db.execute(Source.__table__.delete())
    db.commit()
    return {
        "deleted": {
            "bets": int(bets),
            "operations": int(operations),
        }
    }
