"""Tests de ingesta + API (meta, buckets, títulos, detalle, sync)."""

from __future__ import annotations


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["snapshots"] == 1


def test_meta(client):
    meta = client.get("/api/meta").json()
    assert meta["titles"] == 3
    assert meta["files"] == 6
    assert meta["snapshot"]["account"] == "test@example.com"
    letters = {b["letter"] for b in meta["buckets"]}
    assert letters == {"A", "Z"}


def test_buckets(client):
    buckets = client.get("/api/buckets").json()
    by_letter = {b["letter"]: b for b in buckets}
    assert by_letter["A"]["titles"] == 2
    assert by_letter["Z"]["titles"] == 1


def test_titles_list_y_filtros(client):
    data = client.get("/api/titles").json()
    assert data["total"] == 3
    names = {i["name"] for i in data["items"]}
    assert names == {"A Game One", "A Second Game", "Zelda Echoes of Wisdom"}

    only_a = client.get("/api/titles", params={"letter": "A"}).json()
    assert only_a["total"] == 2

    buscado = client.get("/api/titles", params={"q": "zelda"}).json()
    assert buscado["total"] == 1
    assert buscado["items"][0]["name"] == "Zelda Echoes of Wisdom"

    sorted_by_size = client.get("/api/titles", params={"sort": "size"}).json()
    assert sorted_by_size["items"][0]["slug"] == "a-second-game"


def test_detalle_titulo(client):
    detail = client.get("/api/titles/a-game-one").json()
    assert detail["name"] == "A Game One"
    assert detail["formats"] == ["RAR"]
    assert len(detail["versions"]) == 3
    labels = {v["label"]: v for v in detail["versions"]}
    assert set(labels) == {"base", "update", "dlc"}
    assert len(labels["base"]["files"]) == 2
    assert labels["update"]["file_count"] == 1


def test_detalle_nsp(client):
    zelda = client.get("/api/titles/zelda-echoes-of-wisdom").json()
    assert zelda["formats"] == ["NSP"]
    assert zelda["versions"][0]["files"][0]["name"].endswith(".nsp")


def test_titulo_no_existe(client):
    assert client.get("/api/titles/does-not-exist").status_code == 404


def test_sync_status_sin_megacmd(client):
    status = client.get("/api/sync/status").json()
    assert status["last_snapshot"] is not None
    assert "megacmd_available" in status
