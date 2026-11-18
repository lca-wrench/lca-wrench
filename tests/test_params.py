"""Parameters and formulas: a chain project -> model -> process -> exchange, checked against bw2calc and against
the values Brightway itself stores; undo, guards against broken formulas, background stays untouched."""

import bw2calc as bc
import bw2data as bd
import pytest
from bw2data.parameters import ActivityParameter, DatabaseParameter, Group, ParameterizedExchange, ProjectParameter

from conftest import TEST_PROJECT
from lca_wrench import beispiel, models, params, service as s

METHOD = s.CLIMATE_METHOD


@pytest.fixture()
def example():
    bd.projects.set_current(TEST_PROJECT)
    s.acknowledge()
    ProjectParameter.delete().execute()
    r = beispiel.create()
    db = r["database"]
    bike = next(a for a in bd.Database(db) if a["name"] == "E-Bike, montiert")
    steel = next(e for e in bike.technosphere() if e.input["name"].startswith("Steel"))
    yield {"db": db, "bike": bike, "steel": steel._document.id, "ride": int(r["process"])}
    for name in [n for n in bd.databases if n.startswith(db)]:
        models.delete_database(name)
    ProjectParameter.delete().execute()


def amount(exc_id):
    from bw2data.backends.schema import ExchangeDataset
    return ExchangeDataset.get_by_id(exc_id).data["amount"]


def bw2calc_score(db, node_id):
    bd.Database(db).process()
    lca = bc.LCA({bd.get_node(id=node_id): 1.0}, METHOD)
    lca.lci()
    lca.lcia()
    return float(lca.score)


def chain(ex):
    params.set_parameter("project", "km_jahr", "3000")
    params.set_parameter("database", "faktor", "km_jahr / 1000", database=ex["db"])
    params.set_parameter("activity", "stahl", "7 * faktor / 3", database=ex["db"], activity_id=ex["bike"].id)
    params.set_exchange_formula(ex["steel"], "stahl")


def test_chain_of_scopes_matches_bw2calc_and_brightway(example):
    before = models.system().score({example["ride"]: 1.0}, METHOD)
    chain(example)
    assert amount(example["steel"]) == pytest.approx(7.0)
    assert models.system().score({example["ride"]: 1.0}, METHOD) == pytest.approx(before, rel=1e-12)
    params.set_parameter("project", "km_jahr", "6000")
    assert amount(example["steel"]) == pytest.approx(14.0)
    # Brightway's own tables hold the same values
    assert ProjectParameter.get(name="km_jahr").amount == 6000
    assert DatabaseParameter.get(database=example["db"], name="faktor").amount == pytest.approx(6.0)
    assert ActivityParameter.get(name="stahl").amount == pytest.approx(14.0)
    live = models.system().score({example["ride"]: 1.0}, METHOD)
    assert live == pytest.approx(bw2calc_score(example["db"], example["ride"]), rel=1e-6)  # bw2calc stores float32
    assert live > before
    ov = params.overview(example["db"])
    assert [p["name"] for p in ov["project"]] == ["km_jahr"] and ov["database"]["params"][0]["amount"] == pytest.approx(6)
    bike = next(p for p in ov["processes"] if p["name"] == "E-Bike, montiert")
    assert bike["params"][0]["name"] == "stahl" and bike["formulas"] == 1 and ov["problem"] is None


def test_undo_goes_back_step_by_step(example):
    chain(example)
    params.set_parameter("project", "km_jahr", "6000")
    assert amount(example["steel"]) == pytest.approx(14.0)
    models.undo()
    assert amount(example["steel"]) == pytest.approx(7.0) and ProjectParameter.get(name="km_jahr").amount == 3000
    models.undo()  # the exchange formula
    from bw2data.backends.schema import ExchangeDataset
    assert "formula" not in ExchangeDataset.get_by_id(example["steel"]).data
    assert amount(example["steel"]) == pytest.approx(7.0)


def test_broken_formulas_change_nothing(example):
    chain(example)
    st = params.state()
    for bad in [lambda: params.set_parameter("database", "faktor", "gibts_nicht * 2", database=example["db"]),
                lambda: params.set_exchange_formula(example["steel"], "stahl +"),
                lambda: params.set_parameter("project", "a", "b"),
                lambda: params.delete_parameter("project", "km_jahr"),
                lambda: params.set_parameter("project", "2a", "1"),
                lambda: params.set_parameter("project", "sin", "1")]:
        with pytest.raises(ValueError):
            bad()
    assert params.state() == st
    # a circle: a = b, b = a
    params.set_parameter("project", "a", "1")
    params.set_parameter("project", "b", "a")
    with pytest.raises(ValueError):
        params.set_parameter("project", "a", "b")
    assert ProjectParameter.get(name="a").amount == 1


def test_formula_amount_is_not_edited_directly_and_background_stays(example):
    chain(example)
    with pytest.raises(ValueError, match="Formel"):
        models.update_exchange(example["steel"], amount=3.0)
    with pytest.raises(models.ReadOnlyError):
        params.set_parameter("database", "x", "1", database="BAFU-2025-v2")
    assert not DatabaseParameter.select().where(DatabaseParameter.database == "BAFU-2025-v2").count()


def test_rename_and_delete(example):
    chain(example)
    with pytest.raises(ValueError, match="«km_jahr» wird noch gebraucht"):  # still used in a formula
        params.set_parameter("project", "km", "3000", old_name="km_jahr")
    params.set_parameter("project", "unbenutzt", "1")
    params.set_parameter("project", "auch_unbenutzt", "1", old_name="unbenutzt")
    assert {p.name for p in ProjectParameter.select()} == {"km_jahr", "auch_unbenutzt"}
    params.delete_parameter("project", "auch_unbenutzt")
    assert {p.name for p in ProjectParameter.select()} == {"km_jahr"}


def test_deleting_a_process_and_undo_keeps_its_parameters(example):
    chain(example)
    params.set_exchange_formula(example["steel"], "stahl")
    users = models.users_of(example["bike"].id)
    for u in users:  # the ride uses the bike: remove that input first, then the bike can go
        ride = bd.get_node(id=int(u["id"]))
        for e in ride.technosphere():
            if e.input.id == example["bike"].id:
                models.delete_exchange(e._document.id)
    models.delete_process(example["bike"].id)
    assert not ActivityParameter.select().where(ActivityParameter.name == "stahl").count()
    models.undo()
    assert ActivityParameter.get(name="stahl").amount == pytest.approx(7.0)
    bike = next(a for a in bd.Database(example["db"]) if a["name"] == "E-Bike, montiert")
    steel = next(e for e in bike.technosphere() if e.input["name"].startswith("Steel"))
    assert steel["formula"] == "stahl"
    params.set_parameter("project", "km_jahr", "9000")
    assert next(e for e in bike.technosphere() if e.input["name"].startswith("Steel"))["amount"] == pytest.approx(21.0)


def test_deleting_the_model_removes_its_parameter_groups(example):
    chain(example)
    db = example["db"]
    assert Group.select().where(Group.name.startswith(db + ":")).count()
    models.delete_database(db)
    assert not Group.select().where((Group.name == db) | Group.name.startswith(db + ":")).count()
    assert not ParameterizedExchange.select().where(ParameterizedExchange.group.startswith(db + ":")).count()
    assert not DatabaseParameter.select().where(DatabaseParameter.database == db).count()


def test_api(example):
    from fastapi.testclient import TestClient

    from lca_wrench.api import app

    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        r = c.post("/api/params/set", json={"scope": "project", "name": "km_jahr", "value": "2,5"})
        assert r.status_code == 200 and r.json()["overview"]["project"][0]["amount"] == 2.5
        r = c.post("/api/params/set", json={"scope": "project", "name": "x", "value": "km_jahr * nix"}, headers={"X-Lang": "en"})
        assert r.status_code == 400 and "unknown name nix" in r.json()["detail"]
        r = c.post("/api/models/exchange/formula", json={"exchange": str(example["steel"]), "formula": "km_jahr * 2"})
        assert r.status_code == 200 and amount(example["steel"]) == 5.0
        assert c.get("/api/params", params={"db": example["db"]}).json()["database"]["name"] == example["db"]
