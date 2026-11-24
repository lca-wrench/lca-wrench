"""Excel round trip: export a model, import it again, every process and exchange must come back the same."""

import io
import random
import tempfile
from pathlib import Path

import bw2data as bd
import openpyxl
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from bw2data.parameters import ActivityParameter, Group, ProjectParameter

from lca_wrench import beispiel, excel, models, params, service as s
from lca_wrench.api import app


def _partner(e, db):
    """Background partners by id; partners inside the model by name (their ids differ in a copy)."""
    if e["type"] == "production":
        return "self"
    return f"model:{e.input['name']}" if e.input["database"] == db else f"id:{e.input.id}"


def snapshot(db):
    """{process name: (meta, sorted exchanges as (type, input id, rounded amount))} for a model database."""
    out = {}
    for act in bd.Database(db):
        ex = sorted((e["type"], _partner(e, db), round(float(e["amount"]), 12)) for e in act.exchanges())
        out[act["name"]] = ({k: act.get(k) for k in ("unit", "location", "reference product", "type", "comment")}, ex)
    return out


@pytest.fixture()
def example():
    bd.projects.set_current(TEST_PROJECT)
    s.acknowledge()
    r = beispiel.create()
    models.add_exchange(r["process"], [h for h in s.search("carbon dioxide, fossil", "", 5, None, "flow")][0]["id"], 0.001)
    yield r["database"]
    for name in [n for n in bd.databases if n.startswith(r["database"])]:
        if name in bd.databases:
            models.delete_database(name)
    ProjectParameter.delete().execute()
    s.acknowledge()


def test_round_trip_example(example):
    data, filename = excel.export_model(example)
    assert filename.endswith(".xlsx") and data[:2] == b"PK"
    r = excel.import_model(data)
    assert r["database"] == f"{example} (Import)" and r["processes"] == 5
    assert snapshot(r["database"]) == snapshot(example)
    assert r["database"] in models.model_databases() and models.roles()[r["database"]] == "model"
    # the numbers agree: same product, same score
    method = s.CLIMATE_METHOD
    orig = next(a for a in bd.Database(example) if a["name"].startswith("Fahrt"))
    copy = next(a for a in bd.Database(r["database"]) if a["name"].startswith("Fahrt"))
    S = models.system()
    assert S.score({copy.id: 1.0}, method) == pytest.approx(S.score({orig.id: 1.0}, method), rel=1e-12)
    # internal links of the import point to the import, not to the original
    inner = [e for a in bd.Database(r["database"]) for e in a.technosphere() if e.input["database"] not in ("BAFU-2025-v2",)]
    assert inner and all(e.input["database"] == r["database"] for e in inner)
    # second import gets the next free name
    assert excel.import_model(data)["database"] == f"{example} (Import 2)"


def test_round_trip_many_background_inputs(example):
    """Names are not unique ids: a larger sample of background processes must still link to the same partner."""
    bd.projects.set_current(TEST_PROJECT)
    ids = [int(h["id"]) for q in ("electricity", "steel", "transport", "concrete", "plastic", "aluminium", "wood", "glass")
           for h in s.search(q, "", 40) if h["role"] == "background"]
    rnd = random.Random(1)
    ids = rnd.sample(sorted(set(ids)), 150)
    pid = models.create_process(example, "Stresstest", "unit", "CH")
    for i in ids:
        models.add_exchange(pid, i, 1.0)
    data, _ = excel.export_model(example)
    r = excel.import_model(data, "Stresstest-Import")
    a = next(x for x in bd.Database(example) if x["name"] == "Stresstest")
    b = next(x for x in bd.Database(r["database"]) if x["name"] == "Stresstest")
    ia = sorted(e.input.id for e in a.technosphere())
    ib = sorted(e.input.id for e in b.technosphere())
    assert ia == ib
    models.delete_database(r["database"])


def _parameterize(db):
    """km_jahr (project) -> faktor (model) -> stahl (E-Bike) -> steel of the bike; the battery has a formula only."""
    ProjectParameter.delete().execute()
    bike = next(a for a in bd.Database(db) if a["name"] == "E-Bike, montiert")
    akku = next(a for a in bd.Database(db) if a["name"] == "Akku 500 Wh")
    params.set_parameter("project", "km_jahr", "3000")
    params.set_parameter("database", "faktor", "km_jahr / 1000", database=db)
    params.set_parameter("activity", "stahl", "7 * faktor / 3", database=db, activity_id=bike.id)
    params.set_exchange_formula(next(e for e in bike.technosphere() if e.input["name"].startswith("Steel"))._document.id, "stahl")
    params.set_exchange_formula(next(iter(akku.technosphere()))._document.id, "faktor * 0.1")


def _formulas(db):
    return sorted((a["name"], e.input["name"], e["formula"], round(e["amount"], 9)) for a in bd.Database(db)
                  for e in a.technosphere() if e.get("formula"))


def test_round_trip_with_parameters(example):
    _parameterize(example)
    before = {(o.group, o.name, o.amount) for o in ActivityParameter.select().where(ActivityParameter.database == example)}
    data, _ = excel.export_model(example)
    r = excel.import_model(data)
    new = r["database"]
    assert r["kept_project_parameters"] == ["km_jahr"] and ProjectParameter.select().count() == 1
    # own groups, named after the new model; the original's parameters are untouched
    groups = {o.group for o in ActivityParameter.select().where(ActivityParameter.database == new)}
    assert groups and all(g.startswith(new + ":") for g in groups)
    assert {(o.group, o.name, o.amount) for o in ActivityParameter.select().where(ActivityParameter.database == example)} == before
    ov = params.overview(new)
    assert ov["problem"] is None and [(p["name"], p["amount"]) for p in ov["database"]["params"]] == [("faktor", 3)]
    assert [p["name"] for p in next(x for x in ov["processes"] if x["name"] == "E-Bike, montiert")["params"]] == ["stahl"]
    assert _formulas(new) == _formulas(example) == [("Akku 500 Wh", "Battery, Li-ion, NMC111, rechargeable, prismatic", "faktor * 0.1", 0.3),
                                                     ("E-Bike, montiert", "Steel, low-alloyed, at plant", "stahl", 7.0)]
    method = s.CLIMATE_METHOD
    ride = lambda db: next(a for a in bd.Database(db) if a["name"].startswith("Fahrt")).id  # noqa: E731
    assert models.system().score({ride(new): 1.0}, method) == pytest.approx(models.system().score({ride(example): 1.0}, method), rel=1e-12)
    # one project parameter drives both models
    params.set_parameter("project", "km_jahr", "6000")
    assert [f[3] for f in _formulas(new)] == [f[3] for f in _formulas(example)] == [0.6, 14.0]


def test_import_brings_missing_project_parameters_and_undo_takes_them_back(example):
    _parameterize(example)
    data, _ = excel.export_model(example)
    models.delete_database(example)
    ProjectParameter.delete().execute()
    r = excel.import_model(data)
    assert r["kept_project_parameters"] == [] and ProjectParameter.get(name="km_jahr").amount == 3000
    assert [f[3] for f in _formulas(r["database"])] == [0.3, 7.0]
    models.undo()
    assert r["database"] not in bd.databases and not ProjectParameter.select().count()
    assert not Group.select().where(Group.name.startswith(r["database"] + ":")).count()


def test_broken_parameter_file_writes_nothing(example):
    _parameterize(example)
    data, _ = excel.export_model(example)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    for row in wb.active.iter_rows():
        for c in row:
            if c.value == "km_jahr / 1000":
                c.value = "km_jahr / gibts_nicht"
    buf = io.BytesIO()
    wb.save(buf)
    dbs, groups = set(bd.databases), {g.name for g in Group.select()}
    with pytest.raises(ValueError, match="lassen sich nicht berechnen.*gibts_nicht"):
        excel.import_model(buf.getvalue(), "Sollte-nicht-entstehen")
    assert set(bd.databases) == dbs and {g.name for g in Group.select()} == groups


def test_unlinkable_import_writes_nothing(example):
    data, _ = excel.export_model(example)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    for row in ws.iter_rows():
        for c in row:
            if c.value == "Battery, Li-ion, NMC111, rechargeable, prismatic":
                c.value = "Gibt es nicht, Testname"
    buf = io.BytesIO()
    wb.save(buf)
    before = set(bd.databases)
    with pytest.raises(ValueError, match="Gibt es nicht"):
        excel.import_model(buf.getvalue(), "Sollte-nicht-entstehen")
    assert set(bd.databases) == before


def test_ambiguous_partner_is_a_clear_error(example):
    """Two processes that agree in every field of the file (also the product): a clear message, nothing written."""
    a = models.create_process(example, "Doppelt", "kg", "CH", product="Produkt")
    models.create_process(example, "Doppelt", "kg", "CH", product="Produkt")
    user = models.create_process(example, "Nutzer", "unit", "CH")
    models.add_exchange(user, a, 1.0)
    data, _ = excel.export_model(example)
    before = set(bd.databases)
    with pytest.raises(ValueError, match="mehrere") as err:
        excel.import_model(data, "Mehrdeutig")
    assert str(err.value).startswith("1 Austausch") and "«Doppelt»" in str(err.value)
    assert set(bd.databases) == before


def test_same_name_other_product_links_by_product(example):
    """Multi-product processes (ecoinvent): same name, unit and location, the reference product decides."""
    models.create_process(example, "Doppelt", "kg", "CH", product="Produkt A")
    b = models.create_process(example, "Doppelt", "kg", "CH", product="Produkt B")
    user = models.create_process(example, "Nutzer", "unit", "CH")
    models.add_exchange(user, b, 1.0)
    data, _ = excel.export_model(example)
    r = excel.import_model(data)
    nutzer = next(a for a in bd.Database(r["database"]) if a["name"] == "Nutzer")
    [inp] = [e.input for e in nutzer.technosphere()]
    assert inp["database"] == r["database"] and inp["reference product"] == "Produkt B"


def test_copied_background_process_stays_in_model(example):
    """A background process copied into the model keeps its name: inputs of the copy and of the original stay apart."""
    bd.projects.set_current(TEST_PROJECT)
    hit = [h for h in s.search("concrete", "CH", 20) if h["role"] == "background"][0]
    copy = models.copy_process(hit["id"], example)
    uses_copy = models.create_process(example, "Nutzt die Kopie", "unit", "CH")
    models.add_exchange(uses_copy, copy, 1.0)
    uses_original = models.create_process(example, "Nutzt das Original", "unit", "CH")
    models.add_exchange(uses_original, hit["id"], 1.0)
    data, _ = excel.export_model(example)
    r = excel.import_model(data)
    db = bd.Database(r["database"])
    for act in db:
        assert [e.input.id for e in act.production()] == [act.id]
    copy_new = next(a for a in db if a["name"] == hit["name"])
    assert [e.input.id for e in next(a for a in db if a["name"] == "Nutzt die Kopie").technosphere()] == [copy_new.id]
    assert [e.input.id for e in next(a for a in db if a["name"] == "Nutzt das Original").technosphere()] == [int(hit["id"])]
    assert snapshot(r["database"]) == snapshot(example)


def test_plain_bw2io_file_still_links(example):
    """Files without database and reference product (Activity Browser, older exports) link by name as before."""
    from bw2io.export.excel import write_lci_excel

    with tempfile.TemporaryDirectory() as d:
        data = Path(write_lci_excel(example, dirpath=d)).read_bytes()
    r = excel.import_model(data)
    assert snapshot(r["database"]) == snapshot(example)


def test_rejects_garbage_and_background_export(example):
    for bad in (b"", b"kein excel", b"PK\x03\x04kaputt"):
        with pytest.raises(ValueError):
            excel.import_model(bad)
    with pytest.raises(models.ReadOnlyError):
        excel.export_model("BAFU-2025-v2")


def test_api_download_and_upload(example):
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        r = c.get("/api/models/export", params={"db": example})
        assert r.status_code == 200 and r.content[:2] == b"PK" and ".xlsx" in r.headers["content-disposition"]
        up = c.post("/api/models/import", params={"name": "API-Import"}, content=r.content,
                    headers={"Content-Type": "application/octet-stream"})
        assert up.status_code == 200 and up.json()["database"] == "API-Import"
        assert any(d["name"] == "API-Import" and d["role"] == "model" for d in up.json()["state"]["databases"])
        assert c.post("/api/models/import", content=b"nein").status_code == 400
        assert c.get("/api/models/export", params={"db": "BAFU-2025-v2"}).status_code == 409
        models.delete_database("API-Import")
