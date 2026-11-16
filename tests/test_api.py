"""Тесты REST API: статистика, ставки, источники, настройки, банкролл."""

from __future__ import annotations

BET_PAYLOAD = {
    "sport": "Футбол",
    "event_name": "Зенит — Спартак",
    "prediction": "П1",
    "coefficient": 2.1,
    "stake": 1000,
}


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "counts" in body


def test_root_serves_spa(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_bets_crud_flow(client):
    created = client.post("/api/bets", json=BET_PAYLOAD)
    assert created.status_code == 201
    bet = created.json()
    assert bet["id"]
    assert bet["status"] == "pending"

    listed = client.get("/api/bets", params={"status": "pending"})
    assert listed.json()["total"] == 1

    updated = client.put(f"/api/bets/{bet['id']}", json={"stake": 1500})
    assert updated.json()["stake"] == 1500

    settled = client.patch(f"/api/bets/{bet['id']}/result", json={"status": "won"})
    assert settled.status_code == 200
    assert settled.json()["status"] == "won"
    assert settled.json()["payout"] == 3150.0

    feed = client.get("/api/bets/settlements/feed")
    assert any(item["id"] == bet["id"] for item in feed.json()["items"])

    deleted = client.delete(f"/api/bets/{bet['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/bets/{bet['id']}").status_code == 404


def test_bet_create_validation_error(client):
    response = client.post(
        "/api/bets",
        json={"sport": "Ф", "event_name": "A", "coefficient": 0.5, "stake": -5},
    )
    assert response.status_code == 422


def test_bet_not_found(client):
    assert client.get("/api/bets/9999").status_code == 404
    assert client.delete("/api/bets/9999").status_code == 404



def test_stats_summary_and_options(client):
    client.post("/api/bets", json=BET_PAYLOAD)

    summary = client.get("/api/stats/summary", params={"preset": "30d"})
    assert summary.status_code == 200
    body = summary.json()
    assert body["counts"]["total"] == 1
    assert body["amounts"]["active"] == 1000.0

    options = client.get("/api/stats/options")
    assert options.status_code == 200
    assert "Футбол" in options.json()["sports"]


def test_sources_crud_and_duplicate(client):
    created = client.post(
        "/api/sources",
        json={"name": "Канал", "url": "https://t.me/kanal", "notes": "Прогнозы"},
    )
    assert created.status_code == 201
    source_id = created.json()["id"]
    # Надёжность вычисляемая: без решённых ставок — null; legacy-полей в ответе нет.
    assert created.json()["reliability"] is None
    assert not {"kind", "provider_key", "api_key"} & created.json().keys()

    duplicate = client.post("/api/sources", json={"name": "Канал"})
    assert duplicate.status_code == 400

    updated = client.put(f"/api/sources/{source_id}", json={"name": "Канал 2", "url": None})
    assert updated.json()["name"] == "Канал 2"
    assert updated.json()["reliability"] is None

    listed = client.get("/api/sources").json()
    item = next(item for item in listed if item["id"] == source_id)
    assert item["name"] == "Канал 2"
    assert item["reliability"] is None
    assert not {"kind", "provider_key", "api_key"} & item.keys()

    deleted = client.delete(f"/api/sources/{source_id}")
    assert deleted.status_code == 200
    assert all(item["id"] != source_id for item in client.get("/api/sources").json())


def test_source_reliability_uses_decided_bet_results(client):
    source = client.post("/api/sources", json={"name": "Прогнозист"}).json()
    statuses = ["won", "lost", "push", "cancelled", "pending"]

    for status in statuses:
        bet = client.post("/api/bets", json={**BET_PAYLOAD, "source_id": source["id"]}).json()
        if status != "pending":
            response = client.patch(f"/api/bets/{bet['id']}/result", json={"status": status})
            assert response.status_code == 200

    item = next(
        row for row in client.get("/api/sources").json() if row["id"] == source["id"]
    )
    assert item["reliability"] == 50.0
    assert item["bets_count"] == len(statuses)

    # Надёжность только вычисляется по ставкам и не редактируется через API.
    renamed = client.put(f"/api/sources/{source['id']}", json={"name": "Прогнозист 2"})
    assert renamed.json()["reliability"] == 50.0


def test_source_exposes_last_bet_status(client):
    source_id = client.post("/api/sources", json={"name": "Букмекер"}).json()["id"]

    older = client.post("/api/bets", json={
        **BET_PAYLOAD, "source_id": source_id, "created_at": "2026-11-01T10:00:00",
    }).json()
    client.patch(f"/api/bets/{older['id']}/result", json={"status": "lost"})

    newer = client.post("/api/bets", json={
        **BET_PAYLOAD, "source_id": source_id, "created_at": "2026-11-10T10:00:00", "stake": 250,
    }).json()

    item = next(row for row in client.get("/api/sources").json() if row["id"] == source_id)
    # активная последняя ставка источника тоже учитывается
    assert item["last_status"] == "pending"
    assert item["last_stake"] == 250.0

    client.patch(f"/api/bets/{newer['id']}/result", json={"status": "won"})
    item = next(row for row in client.get("/api/sources").json() if row["id"] == source_id)
    assert item["last_status"] == "won"


def test_source_last_status_absent_without_bets(client):
    source_id = client.post("/api/sources", json={"name": "Пустой"}).json()["id"]
    item = next(row for row in client.get("/api/sources").json() if row["id"] == source_id)
    assert item["last_status"] is None
    assert item["last_stake"] is None


def test_settings_get_update_reset(client):
    current = client.get("/api/settings")
    assert current.status_code == 200
    assert current.json()["values"]["currency"] == "RUB"
    assert "sports" in current.json()["meta"]

    updated = client.put("/api/settings", json={"values": {"theme": "light"}})
    assert updated.status_code == 200
    assert updated.json()["values"]["theme"] == "light"

    invalid = client.put("/api/settings", json={"values": {"unknown_key": 1}})
    assert invalid.status_code == 400

    reset = client.post("/api/settings/reset")
    assert reset.status_code == 200


def test_system_demo_and_wipe(client):
    demo = client.post("/api/system/demo")
    assert demo.status_code == 200
    assert demo.json()["created"] is True
    assert client.get("/api/health").json()["counts"]["bets"] >= 1

    wiped = client.delete("/api/system/data")
    assert wiped.status_code == 200
    health = client.get("/api/health").json()
    assert health["counts"]["bets"] == 0
    assert "events" not in health["counts"]


EXPRESS_PAYLOAD = {
    "kind": "express",
    "sport": "Футбол",
    "stake": 1000,
    "legs": [
        {"event_name": "Зенит — Спартак", "prediction": "П1", "coefficient": 2.0},
        {"event_name": "ЦСКА — Локомотив", "prediction": "ТБ 2.5", "coefficient": 1.5},
    ],
}


def test_express_crud_and_leg_results(client):
    created = client.post("/api/bets", json=EXPRESS_PAYLOAD)
    assert created.status_code == 201
    bet = created.json()
    assert bet["kind"] == "express"
    assert bet["coefficient"] == 3.0
    assert bet["status"] == "pending"
    assert len(bet["legs"]) == 2

    first, second = bet["legs"]
    marked = client.patch(
        f"/api/bets/{bet['id']}/legs/{first['id']}/result", json={"status": "won"}
    )
    assert marked.status_code == 200
    assert marked.json()["status"] == "pending"

    finished = client.patch(
        f"/api/bets/{bet['id']}/legs/{second['id']}/result", json={"status": "won"}
    )
    assert finished.status_code == 200
    body = finished.json()
    assert body["status"] == "won"
    assert body["payout"] == 3000.0
    assert body["profit"] == 2000.0


def test_express_status_cannot_be_set_directly(client):
    bet = client.post("/api/bets", json=EXPRESS_PAYLOAD).json()
    response = client.patch(f"/api/bets/{bet['id']}/result", json={"status": "won"})
    assert response.status_code == 400


def test_express_leg_result_unknown_leg(client):
    bet = client.post("/api/bets", json=EXPRESS_PAYLOAD).json()
    response = client.patch(f"/api/bets/{bet['id']}/legs/9999/result", json={"status": "won"})
    assert response.status_code == 404


def test_express_requires_two_legs(client):
    response = client.post(
        "/api/bets",
        json={**EXPRESS_PAYLOAD, "legs": [{"event_name": "А — Б", "coefficient": 1.5}]},
    )
    assert response.status_code == 422


def test_single_bet_rejects_legs(client):
    response = client.post("/api/bets", json={**BET_PAYLOAD, "legs": EXPRESS_PAYLOAD["legs"]})
    assert response.status_code == 422


def test_bets_filter_by_kind(client):
    client.post("/api/bets", json=BET_PAYLOAD)
    client.post("/api/bets", json=EXPRESS_PAYLOAD)

    assert client.get("/api/bets").json()["total"] == 2
    singles = client.get("/api/bets", params={"kind": "single"}).json()
    expresses = client.get("/api/bets", params={"kind": "express"}).json()
    assert singles["total"] == 1
    assert expresses["total"] == 1
    assert expresses["items"][0]["kind"] == "express"

    invalid = client.get("/api/bets", params={"kind": "bogus"})
    assert invalid.status_code == 422


def test_bankroll_operations_flow(client):
    created = client.post("/api/bankroll/operations", json={"kind": "deposit", "amount": 5000})
    assert created.status_code == 201
    flow = created.json()
    assert flow["id"]
    assert flow["kind"] == "deposit"

    summary = client.get("/api/bankroll/summary").json()
    assert summary["deposits"] == 5000.0
    assert summary["balance"] == 5000.0
    assert summary["operations"] == 1

    listed = client.get("/api/bankroll/operations").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == flow["id"]

    updated = client.put(f"/api/bankroll/operations/{flow['id']}", json={"amount": 6000})
    assert updated.status_code == 200
    assert updated.json()["amount"] == 6000.0

    deleted = client.delete(f"/api/bankroll/operations/{flow['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/bankroll/summary").json()["operations"] == 0


def test_bankroll_balance_counts_bets(client):
    active = client.post("/api/bets", json={**BET_PAYLOAD, "stake": 1500}).json()

    summary = client.get("/api/bankroll/summary").json()
    assert summary["in_play"] == 1500.0
    assert summary["balance"] == -1500.0

    client.patch(f"/api/bets/{active['id']}/result", json={"status": "won"})
    summary = client.get("/api/bankroll/summary").json()
    assert summary["in_play"] == 0.0
    assert summary["balance"] == 1500 * 2.1 - 1500


def test_bankroll_operation_validation(client):
    bad_amount = client.post("/api/bankroll/operations", json={"kind": "deposit", "amount": -5})
    assert bad_amount.status_code == 422

    bad_kind = client.post("/api/bankroll/operations", json={"kind": "gift", "amount": 100})
    assert bad_kind.status_code == 422


def test_bankroll_operation_not_found(client):
    assert client.delete("/api/bankroll/operations/999").status_code == 404
    assert client.put("/api/bankroll/operations/999", json={"amount": 10}).status_code == 404


def test_bets_export_csv(client):
    client.post("/api/bets", json=BET_PAYLOAD)

    response = client.get("/api/bets/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "winners-bets-" in disposition

    text = response.content.decode("utf-8")
    # BOM нужен Excel для корректной кириллицы.
    assert text.startswith("\ufeff")
    lines = text.lstrip("\ufeff").splitlines()
    assert lines[0].split(";")[0] == "Дата"
    assert "Зенит — Спартак" in text
    assert "Активная" in text  # статус отдан человекочитаемой меткой


def test_bets_export_respects_filters(client):
    client.post("/api/bets", json=BET_PAYLOAD)
    won = client.post(
        "/api/bets", json={**BET_PAYLOAD, "event_name": "ЦСКА — Локомотив"}
    ).json()
    client.patch(f"/api/bets/{won['id']}/result", json={"status": "won"})

    text = client.get("/api/bets/export", params={"status": "won"}).content.decode("utf-8")
    assert "ЦСКА — Локомотив" in text
    assert "Зенит — Спартак" not in text


def test_stats_export_csv(client):
    created = client.post("/api/bets", json=BET_PAYLOAD).json()
    client.patch(f"/api/bets/{created['id']}/result", json={"status": "won"})

    response = client.get("/api/stats/export", params={"preset": "30d"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    text = response.content.decode("utf-8")
    assert text.startswith("\ufeff")
    assert "Показатель;Значение" in text
    assert "Финансовый результат" in text
    assert "Проходимость, %" in text
    assert "Футбол" in text  # разбивка по видам спорта


def test_stats_compare_endpoint(client):
    created = client.post("/api/bets", json=BET_PAYLOAD).json()
    client.patch(f"/api/bets/{created['id']}/result", json={"status": "won"})

    response = client.get("/api/stats/compare", params={"preset": "30d"})
    assert response.status_code == 200
    body = response.json()
    assert body["range"]["has_previous"] is True
    assert body["current"]["won"] == 1
    assert body["delta"]["won"] == 1


def test_sources_sort_by_roi(client):
    good = client.post("/api/sources", json={"name": "Хороший"}).json()
    bad = client.post("/api/sources", json={"name": "Плохой"}).json()

    won = client.post("/api/bets", json={**BET_PAYLOAD, "source_id": good["id"]}).json()
    client.patch(f"/api/bets/{won['id']}/result", json={"status": "won"})
    lost = client.post(
        "/api/bets",
        json={**BET_PAYLOAD, "source_id": bad["id"], "event_name": "ЦСКА — Локомотив"},
    ).json()
    client.patch(f"/api/bets/{lost['id']}/result", json={"status": "lost"})

    rows = client.get("/api/sources", params={"sort": "roi", "order": "desc"}).json()
    ids = [row["id"] for row in rows]
    assert ids.index(good["id"]) < ids.index(bad["id"])
    best = next(row for row in rows if row["id"] == good["id"])
    worst = next(row for row in rows if row["id"] == bad["id"])
    assert best["roi"] > worst["roi"]
    assert best["profit"] > 0


def test_bankroll_curve_endpoint(client):
    client.post("/api/bankroll/operations", json={"kind": "deposit", "amount": 1000})
    response = client.get("/api/bankroll/curve")
    assert response.status_code == 200
    points = response.json()["points"]
    assert points
    assert points[-1]["balance"] == 1000.0


def test_bets_suggest_endpoint(client):
    client.post("/api/bets", json=BET_PAYLOAD)
    response = client.get("/api/bets/suggest", params={"q": "зенит"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert items[0]["event_name"] == BET_PAYLOAD["event_name"]


def test_bets_duplicate_endpoint(client):
    bet = client.post("/api/bets", json=BET_PAYLOAD).json()
    client.patch(f"/api/bets/{bet['id']}/result", json={"status": "won"})

    copy = client.post(f"/api/bets/{bet['id']}/duplicate")
    assert copy.status_code == 201
    assert copy.json()["status"] == "pending"
    assert copy.json()["id"] != bet["id"]
    assert client.get("/api/bets").json()["total"] == 2


def test_bets_bulk_delete_endpoint(client):
    first = client.post("/api/bets", json=BET_PAYLOAD).json()
    second = client.post(
        "/api/bets", json={**BET_PAYLOAD, "event_name": "ЦСКА — Локомотив"}
    ).json()

    response = client.post(
        "/api/bets/bulk", json={"ids": [first["id"], second["id"]], "action": "delete"}
    )
    assert response.status_code == 200
    assert response.json()["affected"] == 2
    assert client.get("/api/bets").json()["total"] == 0


def test_bets_bulk_status_endpoint(client):
    bet = client.post("/api/bets", json=BET_PAYLOAD).json()
    response = client.post(
        "/api/bets/bulk",
        json={"ids": [bet["id"]], "action": "status", "status": "won"},
    )
    assert response.status_code == 200
    assert response.json()["affected"] == 1
    assert client.get(f"/api/bets/{bet['id']}").json()["status"] == "won"


def test_bets_bulk_status_requires_status(client):
    bet = client.post("/api/bets", json=BET_PAYLOAD).json()
    response = client.post(
        "/api/bets/bulk", json={"ids": [bet["id"]], "action": "status"}
    )
    assert response.status_code == 422
