"""Version comparison: the parts add up to the difference of two independent bw2calc results.

Version 2 is a copy of the test project with changed amounts, a changed emission, a removed exchange, a new dataset
that the product now uses, and a changed characterization factor.
"""

import bw2calc as bc
import bw2data as bd
import pytest

from conftest import TEST_PROJECT
from lca_wrench import engine, service as s, versions

V2 = "lca-wrench-test-version2"
BG = "BAFU-2025-v2"


def bw_score(project, node_id, method):
    bd.projects.set_current(project)
    lca = bc.LCA({bd.get_node(id=node_id): 1.0}, method)
    lca.lci()
    lca.lcia()
    return float(lca.score)


@pytest.fixture(scope="module")
def two_versions():
    bd.projects.set_current(TEST_PROJECT)
    if V2 in bd.projects:
        bd.projects.delete_project(V2, delete_dir=True)
    hit = [h for h in s.search("electricity low voltage", "CH") if h["unit"] == "kWh"][0]
    pid = int(hit["id"])
    bd.projects.copy_project(V2, switch=True)
    p = bd.get_node(id=pid)
    techs = sorted(p.technosphere(), key=lambda e: -abs(e["amount"]))
    e1 = techs[0]
    e1["amount"] = e1["amount"] * 1.5
    e1.save()
    up = e1.input
    bio = max(up.biosphere(), key=lambda e: abs(e["amount"]))
    bio["amount"] = bio["amount"] * 2
    bio.save()
    removed = [e for e in up.technosphere() if e.input.id != up.id][-1]
    removed_name = removed.input["name"]
    removed.delete()
    co2 = [f for f in bd.Database("BAFU-2025-biosphere").search("carbon dioxide fossil", limit=50)
           if f["name"].lower().startswith("carbon dioxide, fossil")][0]
    new = bd.Database(BG).new_activity(code="lca-wrench-test-neuer-datensatz", name="Neuer Datensatz", unit="kilogram",
                                       location="CH", type="process", **{"reference product": "Neuer Datensatz"})
    new.save()
    new.new_exchange(input=new, amount=1.0, type="production").save()
    new.new_exchange(input=co2, amount=3.0, type="biosphere").save()
    new.new_exchange(input=up, amount=0.2, type="technosphere").save()
    p.new_exchange(input=new, amount=0.05, type="technosphere").save()
    bd.Database(BG).process()
    m = bd.Method(s.CLIMATE_METHOD)
    data = m.load()
    m.write([(k, cf * 1.25 if k == co2.key or k == co2.id else cf) for k, cf in data])
    engine.bump_background(V2)
    bd.projects.set_current(TEST_PROJECT)
    yield {"pid": pid, "up": up["name"], "removed": removed_name}
    bd.projects.set_current(TEST_PROJECT)
    bd.projects.delete_project(V2, delete_dir=True)


def test_parts_add_up_to_the_difference_of_two_bw2calc_results(two_versions):
    pid, method = two_versions["pid"], s.CLIMATE_METHOD
    h0, h1 = bw_score(TEST_PROJECT, pid, method), bw_score(V2, pid, method)
    bd.projects.set_current(TEST_PROJECT)
    r = versions.compare(pid, 1.0, method, V2, BG)
    assert bd.projects.current == TEST_PROJECT
    assert r["version0"]["score"] == pytest.approx(h0, rel=1e-8)
    assert r["version1"]["score"] == pytest.approx(h1, rel=1e-8)
    assert abs(h1 - h0) > 1e-3 * abs(h0)  # the changes matter
    # exact: the parts (datasets, characterization factors, demand) give the difference
    assert r["explained"] == pytest.approx(r["difference"], rel=1e-9, abs=1e-15)
    shown = sum(p["contribution"] for p in r["parts"]) + r["parts_rest"]
    assert shown + r["flows_total"] + r["demand"] == pytest.approx(r["difference"], rel=1e-9)
    assert r["datasets_new"] == 1
    assert any(p["status"] == "new" and p["name"] == "Neuer Datensatz" and p["contribution"] > 0 for p in r["parts"])
    assert r["flows"] and r["flows"][0]["new_cf"] == pytest.approx(r["flows"][0]["old_cf"] * 1.25)
    names = {p["name"] for p in r["parts"]}
    assert two_versions["up"] in names  # its emission and its removed input


def test_detail_of_one_dataset_adds_up(two_versions):
    bd.projects.set_current(TEST_PROJECT)
    r = versions.compare(two_versions["pid"], 1.0, s.CLIMATE_METHOD, V2, BG)
    for part in r["parts"][:5]:
        d = versions.detail(part["k"])
        assert d["total"] == pytest.approx(part["contribution"], rel=1e-9, abs=1e-15)
    up = next(p for p in r["parts"] if p["name"] == two_versions["up"])
    rows = versions.detail(up["k"])["rows"]
    assert any(row["kind"] == "emission" and row["new"] == pytest.approx(2 * row["old"]) for row in rows)
    assert any(row["kind"] == "input" and row["name"] == two_versions["removed"] and row["new"] == 0 for row in rows)


def test_same_version_has_no_difference_and_guards(two_versions):
    bd.projects.set_current(TEST_PROJECT)
    with pytest.raises(ValueError):
        versions.compare(two_versions["pid"], 1.0, s.CLIMATE_METHOD, TEST_PROJECT, BG)
    with pytest.raises(KeyError):
        versions.compare(two_versions["pid"], 1.0, s.CLIMATE_METHOD, V2, "gibt-es-nicht")
    assert bd.projects.current == TEST_PROJECT
    assert {t["name"] for t in versions.targets(V2)} == {BG}


def test_matching_by_code_then_by_name_with_database_alias():
    info0 = {1: {"database": "ei-3.10", "code": "a", "name": "steel", "product": "steel", "location": "GLO", "unit": "kg"},
             2: {"database": "ei-3.10", "code": "b", "name": "power", "product": "power", "location": "CH", "unit": "kWh"},
             3: {"database": "shared", "code": "z", "name": "x", "product": "x", "location": "GLO", "unit": "kg"}}
    info1 = {11: {"database": "ei-3.11", "code": "a", "name": "steel", "product": "steel", "location": "GLO", "unit": "kg"},
             12: {"database": "ei-3.11", "code": "NEW", "name": "power", "product": "power", "location": "CH", "unit": "kWh"},
             13: {"database": "shared", "code": "z", "name": "x", "product": "x", "location": "GLO", "unit": "kg"},
             14: {"database": "ei-3.11", "code": "c", "name": "only new", "product": "only new", "location": "CH", "unit": "kg"}}
    m = versions._match(list(info1), info1, "ei-3.11", list(info0), info0, "ei-3.10")
    assert m == {11: 1, 12: 2, 13: 3}


def test_api(two_versions):
    from fastapi.testclient import TestClient

    from lca_wrench.api import app

    bd.projects.set_current(TEST_PROJECT)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        assert [t["name"] for t in c.get("/api/versions/targets", params={"project": V2}).json()] == [BG]
        body = {"id": str(two_versions["pid"]), "amount": 2, "method": list(s.CLIMATE_METHOD), "project": V2, "database": BG}
        r = c.post("/api/versions", json=body)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["explained"] == pytest.approx(j["difference"], rel=1e-9) and j["product"]["amount"] == 2
        d = c.get("/api/versions/detail", params={"k": j["parts"][0]["k"]}).json()
        assert d["total"] == pytest.approx(j["parts"][0]["contribution"], rel=1e-9)
        bad = c.post("/api/versions", json={**body, "database": "gibt-es-nicht"}, headers={"X-Lang": "en"})
        assert bad.status_code == 404 and "does not exist in this project" in bad.json()["detail"]
    assert bd.projects.current == TEST_PROJECT
