"""API smoke tests: endpoints answer, guard rails hold."""

import bw2data as bd
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import service as s
from lca_wrench.api import app

@pytest.fixture(scope="module")
def client():
    bd.projects.set_current(TEST_PROJECT)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        yield c


def test_foreign_host_rejected():
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/api/state").status_code == 403


def test_search_corrects_typos(client):
    exact = client.get("/api/search", params={"q": "steel"}).json()
    typo = client.get("/api/search", params={"q": "steeel"}).json()
    assert exact and not any(h.get("spelling") for h in exact)
    assert typo and {h["spelling"] for h in typo} == {"steel"}
    assert [h["id"] for h in typo] == [h["id"] for h in exact]
    cut = client.get("/api/search", params={"q": "concret"}).json()
    assert cut and cut[0]["spelling"] == "concrete"
    flows = client.get("/api/search", params={"q": "carbon dioxde", "kind": "flow"}).json()
    assert flows and any(h["name"].lower().startswith("carbon dioxide") for h in flows)
    assert client.get("/api/search", params={"q": "xyzzyq"}).json() == []
    assert s.respell("electrcity low voltage", ["BAFU-2025-v2"]) == "electricity low voltage"
    assert s.respell("steel", ["BAFU-2025-v2"]) is None


def test_flow_search_activity_calc_graph(client):
    st = client.get("/api/state").json()
    assert st["project"] == TEST_PROJECT and not st["is_copy"]
    m = st["default_method"]
    hits = client.get("/api/search", params={"q": "electricity low voltage", "loc": "CH"}).json()
    assert hits and hits[0]["location"] == "CH"
    # other locations only as stand-ins from the regions around Switzerland, marked as such
    assert all(h["location"] == "CH" or h.get("region") == "CH" for h in hits)
    aid = hits[0]["id"]
    act = client.post("/api/activity", json={"id": aid, "method": m}).json()
    assert act["editable"] is False and act["score"] > 0
    # 64-bit ids must survive the round trip as strings (JavaScript numbers would round them)
    assert isinstance(aid, str) and act["id"] == aid and int(aid) > 2**53
    calc = client.post("/api/calc", json={"id": aid, "amount": 2, "method": m}).json()
    assert calc["score"] == pytest.approx(2 * act["score"], rel=1e-6)
    v = client.post("/api/verify", json={"fus": [{"id": aid, "amount": 2}], "methods": [m]}).json()
    assert v["ok"] and v["checked"] == 1
    sk = client.post("/api/sankey", json={"id": aid, "amount": 2, "method": m, "cutoff": 0.02, "max_nodes": 20}).json()
    assert sk["nodes"] and sk["total"] == pytest.approx(calc["score"], rel=1e-9)
    inv = client.post("/api/inventory", json={"id": aid, "amount": 2}).json()
    assert len(inv) > 10
    g = client.post("/api/graph", json={"id": aid, "amount": 2, "method": m, "cutoff": 0.02, "depth": 3}).json()
    assert g["nodes"][0]["share"] == pytest.approx(1.0)
    cmp = client.post("/api/compare", json={"items": [{"project": TEST_PROJECT, "id": aid, "amount": 1}], "method": m}).json()
    assert cmp[0]["score"] == pytest.approx(act["score"], rel=1e-9)


def test_edit_original_refused(client):
    m = list(s.CLIMATE_METHOD)
    aid = client.get("/api/state").json()["examples"][0]["id"]
    ex = client.post("/api/activity", json={"id": aid, "method": m}).json()["technosphere"][0]["exchange"]
    r = client.post("/api/edit", json={"exchange": ex, "amount": 1.0})
    assert r.status_code == 409


def test_unknown_method_and_index(client):
    assert client.post("/api/calc", json={"id": "1", "amount": 1, "method": ["nope"]}).status_code == 404
    r = client.get("/")
    assert r.status_code == 200 and "LCA Wrench" in r.text


def test_model_editing_round_trip_with_64bit_ids(client):
    name = "zz API Testmodell"
    m = list(s.CLIMATE_METHOD)
    st = client.get("/api/state").json()
    el = st["examples"][1]["id"]  # electricity
    try:
        assert client.post("/api/models/db", json={"name": name}).status_code == 200
        pid = client.post("/api/models/process", json={"database": name, "name": "Test", "unit": "unit"}).json()["id"]
        ex = client.post("/api/models/exchange/add", json={"id": pid, "input": el, "amount": 2}).json()["exchange"]
        assert isinstance(ex, str) and int(ex) > 2**53  # exchange ids are 64-bit too
        sheet = client.post("/api/activity", json={"id": pid, "method": m}).json()
        assert sheet["edit_mode"] == "model" and sheet["technosphere"][0]["exchange"] == ex
        el_score = client.post("/api/activity", json={"id": el, "method": m}).json()["score"]
        assert sheet["score"] == pytest.approx(2 * el_score, rel=1e-6)
        assert client.post("/api/edit", json={"exchange": ex, "amount": 3}).status_code == 200
        sheet = client.post("/api/activity", json={"id": pid, "method": m}).json()
        assert sheet["score"] == pytest.approx(3 * el_score, rel=1e-6)
        undo = client.post("/api/models/undo", json={}).json()
        assert "2 → 3" in undo["undone"]
        sheet = client.post("/api/activity", json={"id": pid, "method": m}).json()
        assert sheet["score"] == pytest.approx(2 * el_score, rel=1e-6)
    finally:
        client.post("/api/models/db/delete", json={"name": name})
