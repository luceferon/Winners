"""Тесты бизнес-логики ставок: CRUD, фильтры, расчёт результата."""

from __future__ import annotations

import pytest

from app.models import Source
from app.schemas import BetCreate, BetUpdate
from app.services import bets_service
from app.services.bets_service import BetError


def make_source(db, name: str = "Букмекер") -> Source:
    source = Source(name=name)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def make_bet(db, **overrides):
    payload = {
        "sport": "Футбол",
        "event_name": "Зенит — Спартак",
        "coefficient": 2.0,
        "stake": 1000,
    }
    payload.update(overrides)
    return bets_service.create_bet(db, BetCreate(**payload))


def test_create_bet_normalizes_and_resolves_source(db):
    source = make_source(db)
    bet = bets_service.create_bet(
        db,
        BetCreate(
            sport="Футбол",
            event_name="  Зенит — Спартак ",
            coefficient=2.0,
            stake=1000,
            source_id=source.id,
        ),
    )
    assert bet.normalized_event_name == "зенит спартак"
    assert bet.source_name == source.name
    assert bet.status == "pending"
    assert bet.payout == 0.0


def test_create_bet_unknown_source_raises(db):
    with pytest.raises(BetError):
        bets_service.create_bet(
            db,
            BetCreate(sport="Футбол", event_name="А — Б", coefficient=2.0, stake=100, source_id=999),
        )


def test_set_result_won_computes_payout_and_profit(db):
    bet = make_bet(db, coefficient=1.8, stake=1000)
    bets_service.set_result(db, bet, "won")
    assert bet.status == "won"
    assert bet.payout == 1800.0
    assert bet.profit == 800.0
    assert bet.settled_at is not None


def test_set_result_lost_has_negative_profit(db):
    bet = make_bet(db, stake=500)
    bets_service.set_result(db, bet, "lost")
    assert bet.payout == 0.0
    assert bet.profit == -500.0


def test_set_result_push_returns_stake(db):
    bet = make_bet(db, stake=700)
    bets_service.set_result(db, bet, "push")
    assert bet.payout == 700.0
    assert bet.profit == 0.0


def test_set_result_manual_payout_override(db):
    bet = make_bet(db)
    bets_service.set_result(db, bet, "won", payout=1234.5)
    assert bet.payout == 1234.5


def test_set_result_rejects_invalid_status(db):
    bet = make_bet(db)
    with pytest.raises(BetError):
        bets_service.set_result(db, bet, "bogus")


def test_set_result_back_to_pending_resets(db):
    bet = make_bet(db)
    bets_service.set_result(db, bet, "won")
    bets_service.set_result(db, bet, "pending")
    assert bet.status == "pending"
    assert bet.payout == 0.0
    assert bet.settled_at is None



def test_update_bet_changes_fields(db):
    bet = make_bet(db)
    updated = bets_service.update_bet(db, bet, BetUpdate(stake=2500, comment="догон"))
    assert updated.stake == 2500
    assert updated.comment == "догон"


def test_delete_bet(db):
    bet = make_bet(db)
    bet_id = bet.id
    bets_service.delete_bet(db, bet)
    assert db.get(type(bet), bet_id) is None


def seed_varied_bets(db):
    rows = [
        ("Футбол", "Зенит — Спартак", "won", 2.0, 1000),
        ("Футбол", "ЦСКА — Локомотив", "lost", 1.5, 500),
        ("Хоккей", "СКА — ЦСКА", "pending", 2.5, 1500),
        ("Теннис", "Джокович — Алькарас", "push", 1.7, 700),
    ]
    bets = []
    for sport, name, status, coefficient, stake in rows:
        bet = make_bet(db, sport=sport, event_name=name, coefficient=coefficient, stake=stake)
        if status != "pending":
            bets_service.set_result(db, bet, status)
        bets.append(bet)
    return bets


def test_list_bets_filter_by_status(db):
    seed_varied_bets(db)
    items, total = bets_service.list_bets(db, status="won")
    assert total == 1
    assert items[0].status == "won"


def test_list_bets_filter_by_sport(db):
    seed_varied_bets(db)
    _, total = bets_service.list_bets(db, sport="Хоккей")
    assert total == 1


def test_list_bets_search_matches_event_name(db):
    seed_varied_bets(db)
    items, total = bets_service.list_bets(db, search="зенит")
    assert total == 1
    assert "Зенит" in items[0].event_name


def test_list_bets_sort_by_stake_desc(db):
    seed_varied_bets(db)
    items, _ = bets_service.list_bets(db, sort="stake", order="desc")
    stakes = [bet.stake for bet in items]
    assert stakes == sorted(stakes, reverse=True)


def test_list_bets_pagination(db):
    seed_varied_bets(db)
    items, total = bets_service.list_bets(db, limit=2, offset=0)
    assert total == 4
    assert len(items) == 2


def test_settlement_feed_returns_settled(db):
    seed_varied_bets(db)
    feed = bets_service.settlement_feed(db)
    assert feed
    assert all(bet.settled_at is not None for bet in feed)


def test_available_sports(db):
    seed_varied_bets(db)
    sports = bets_service.available_sports(db)
    assert set(sports) == {"Футбол", "Хоккей", "Теннис"}


def test_compute_payout_variants(db):
    bet = make_bet(db, coefficient=3.0, stake=100)
    assert bets_service.compute_payout(bet, "won") == 300.0
    assert bets_service.compute_payout(bet, "push") == 100.0
    assert bets_service.compute_payout(bet, "lost") == 0.0
    assert bets_service.compute_payout(bet, "won", payout=555.0) == 555.0


# --- экспрессы ---------------------------------------------------------------
def make_express(db, **overrides):
    payload = {
        "sport": "Футбол",
        "stake": 1000,
        "kind": "express",
        "legs": [
            {"event_name": "Зенит — Спартак", "prediction": "П1", "coefficient": 2.0},
            {"event_name": "ЦСКА — Локомотив", "prediction": "ТБ 2.5", "coefficient": 1.5},
        ],
    }
    payload.update(overrides)
    return bets_service.create_bet(db, BetCreate(**payload))


def test_create_express_combines_coefficients(db):
    bet = make_express(db)
    assert bet.kind == "express"
    assert bet.is_express is True
    assert bet.coefficient == 3.0
    assert bet.payout == 0.0
    assert bet.status == "pending"
    assert len(bet.legs) == 2
    assert "Зенит — Спартак" in bet.event_name


def test_express_stays_pending_until_all_legs_settled(db):
    bet = make_express(db)
    bets_service.set_leg_result(db, bet, bet.legs[0], "won")
    assert bet.status == "pending"
    assert bet.payout == 0.0


def test_express_leg_lost_loses_whole_bet(db):
    bet = make_express(db)
    bets_service.set_leg_result(db, bet, bet.legs[0], "won")
    bets_service.set_leg_result(db, bet, bet.legs[1], "lost")
    assert bet.status == "lost"
    assert bet.payout == 0.0
    assert bet.profit == -1000.0


def test_express_all_legs_won_multiplies_payout(db):
    bet = make_express(db)
    for leg in list(bet.legs):
        bets_service.set_leg_result(db, bet, leg, "won")
    assert bet.status == "won"
    assert bet.coefficient == 3.0
    assert bet.payout == 3000.0
    assert bet.profit == 2000.0
    assert bet.settled_at is not None


def test_express_push_leg_counts_as_one(db):
    bet = make_express(db)
    bets_service.set_leg_result(db, bet, bet.legs[0], "push")
    bets_service.set_leg_result(db, bet, bet.legs[1], "won")
    assert bet.status == "won"
    assert bet.coefficient == 1.5
    assert bet.payout == 1500.0


def test_express_all_push_returns_stake(db):
    bet = make_express(db)
    for leg in list(bet.legs):
        bets_service.set_leg_result(db, bet, leg, "push")
    assert bet.status == "push"
    assert bet.payout == 1000.0
    assert bet.profit == 0.0


def test_express_leg_result_rejects_invalid_status(db):
    bet = make_express(db)
    with pytest.raises(BetError):
        bets_service.set_leg_result(db, bet, bet.legs[0], "bogus")


def test_express_coefficient_is_not_overwritten_by_update(db):
    bet = make_express(db)
    bets_service.update_bet(db, bet, BetUpdate(coefficient=99.0, status="won"))
    assert bet.coefficient == 3.0
    assert bet.status == "pending"


def test_list_bets_filter_by_kind(db):
    make_bet(db)
    make_express(db)
    _, total_single = bets_service.list_bets(db, kind="single")
    express_items, total_express = bets_service.list_bets(db, kind="express")
    assert total_single == 1
    assert total_express == 1
    assert express_items[0].is_express is True


# --- Дублирование, массовые операции, подсказки -----------------------------
def test_duplicate_single_bet_creates_pending_copy(db):
    bet = make_bet(db, coefficient=2.0, stake=1000)
    bets_service.set_result(db, bet, "won")

    copy = bets_service.duplicate_bet(db, bet)
    assert copy.id != bet.id
    assert copy.status == "pending"
    assert copy.payout == 0.0
    assert copy.stake == bet.stake
    assert copy.event_name == bet.event_name
    assert copy.coefficient == bet.coefficient


def test_duplicate_express_resets_legs(db):
    bet = make_express(db)
    for leg in list(bet.legs):
        bets_service.set_leg_result(db, bet, leg, "won")

    copy = bets_service.duplicate_bet(db, bet)
    assert copy.kind == "express"
    assert copy.status == "pending"
    assert copy.payout == 0.0
    assert len(copy.legs) == 2
    assert all(leg.status == "pending" for leg in copy.legs)


def test_bulk_delete(db):
    bets = seed_varied_bets(db)
    result = bets_service.bulk_action(db, [bets[0].id, bets[1].id], "delete")
    assert result["affected"] == 2
    _, total = bets_service.list_bets(db)
    assert total == 2


def test_bulk_status_skips_express(db):
    single = make_bet(db)
    express = make_express(db)

    result = bets_service.bulk_action(db, [single.id, express.id], "status", status="won")
    assert result["affected"] == 1
    assert result["skipped"] == 1
    assert db.get(type(single), single.id).status == "won"
    assert db.get(type(express), express.id).status == "pending"


def test_bulk_rejects_empty_ids(db):
    with pytest.raises(BetError):
        bets_service.bulk_action(db, [], "delete")


def test_bulk_rejects_unknown_action(db):
    bet = make_bet(db)
    with pytest.raises(BetError):
        bets_service.bulk_action(db, [bet.id], "explode")


def test_suggest_matches_partial(db):
    make_bet(db, event_name="Зенит — Спартак")
    make_bet(db, event_name="ЦСКА — Локомотив")

    items = bets_service.suggest(db, "зенит")
    assert len(items) == 1
    assert items[0]["event_name"] == "Зенит — Спартак"
    assert items[0]["coefficient"] == 2.0


def test_suggest_dedupes_same_event(db):
    for _ in range(3):
        make_bet(db, event_name="Зенит — Спартак")
    items = bets_service.suggest(db, "зенит")
    assert len(items) == 1
