"""Search by unit and region, all categories of a method family, export, and moving a model to another region."""

import csv
import io

import bw2data as bd
import openpyxl
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import models, regions, reproject, service as s
from lca_wrench.api import app

DB = "Test Region"


@pytest.fixture(scope="module")
def client():
    bd.projects.set_current(TEST_PROJECT)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        yield c


def bafu(name, loc):
    return next(a.id for a in bd.Database("BAFU-2025-v2") if a["name"] == name and a["location"] == loc)


def test_regions():
    assert regions.resolve("Switzerland") == "CH" == regions.resolve("schweiz") == regions.resolve("ch")
    assert regions.resolve("Europe") == "RER"
    ch = regions.chain("CH")
    assert ch[0] == "CH" and ch[-2:] == ["GLO", "RoW"] and "RER" in ch and "Europe without Switzerland" not in ch
    assert "UCTE" not in regions.chain("NO")
    assert regions.find_in_query("electricity low voltage Germany") == ("electricity low voltage", "DE")
    assert regions.find_in_query("steel") == ("steel", None)


def test_search_by_unit_and_location():
    energy = s.search("electricity", unit="energy")
    assert energy and all(h["unit"] in ("kWh", "MJ") for h in energy)
    assert not any(h["unit"] == "Stück" for h in energy)  # no power plants or grids (infrastructure)
    # a country without its own dataset gets the nearest region, marked as stand-in
    li = s.search("electricity low voltage at grid", location="Liechtenstein")
    assert li and all(h.get("region") == "LI" for h in li)
    # location and unit at the end of the query count too
    q = s.search("electricity low voltage CH kwh")
    assert q and q[0]["location"] == "CH" and all(h["unit"] in ("kWh", "MJ") for h in q)
    # the words as typed come first
    first = s.search("concrete normal")[0]
    assert "concrete" in first["name"].lower() and "normal" in first["name"].lower()
    opts = s.search_options()
    assert "energy" in opts["units"] and "CH" in opts["locations"][:5]


def test_categories_and_exports(client):
    aid = str(bafu("Electricity, low voltage, at grid", "CH"))
    fam = s.PROFILE_FAMILY
    r = client.post("/api/categories", json={"id": aid, "amount": 2, "families": [fam, "Werkbank"]}).json()
    assert [f["family"] for f in r["families"]] == [fam, "Werkbank"]
    prof = s.calculate(aid, 2, s.UBP_TOTAL_METHOD)["profile"]
    got = {x["name"]: x["value"] for x in r["families"][0]["rows"]}
    for p in prof:
        assert got.get(p["name"], 0.0) == pytest.approx(p["value"], rel=1e-9)  # without factors: left out
    body = {"id": aid, "amount": 2, "method": list(s.CLIMATE_METHOD)}
    x = client.post("/api/export/result", json={**body, "format": "xlsx", "families": [fam]})
    assert x.status_code == 200 and "xlsx" in x.headers["content-disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    assert len(wb.sheetnames) == 6  # result, by activity, by flow, by location, all categories, inventory
    score = wb[wb.sheetnames[0]].cell(2, 7).value
    assert score == pytest.approx(s.calculate(aid, 2, s.CLIMATE_METHOD)["score"], rel=1e-9)
    c = client.post("/api/export/result", json={**body, "format": "csv"})
    rows = list(csv.reader(io.StringIO(c.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) > 20 and rows[0][0]
    st = client.post("/api/export/setup", json={"name": "Test", "format": "xlsx", "fus": [{"id": aid, "amount": 1}],
                                                "methods": [list(s.CLIMATE_METHOD), list(s.UBP_TOTAL_METHOD)]})
    ws = openpyxl.load_workbook(io.BytesIO(st.content)).worksheets[0]
    assert ws.cell(2, 5).value == pytest.approx(s.calculate(aid, 1, s.CLIMATE_METHOD)["score"], rel=1e-9)


def test_reproject_electricity():
    bd.projects.set_current(TEST_PROJECT)
    for name in (DB, f"{DB} [DE]"):
        if name in bd.databases:
            del bd.databases[name]
    models.create_database(DB)
    p = int(models.create_process(DB, "Gerät", "unit", "CH"))
    models.add_exchange(p, bafu("Electricity, low voltage, at grid", "CH"), 10.0)
    models.add_exchange(p, bafu("Aluminium, primary, at plant", "RER"), 1.0)
    plan = reproject.plan(DB, "Germany", "electricity")
    assert plan["target"] == "DE" and len(plan["swaps"]) == 1
    r = reproject.reproject(DB, "Germany")
    assert r["database"] == f"{DB} [DE]" and r["changed"] == 1
    moved = next(iter(bd.Database(r["database"])))
    assert moved["location"] == "DE"
    sup = {bd.get_node(id=e.input.id)["location"] for e in moved.technosphere()}
    assert sup == {"DE", "RER"}  # electricity from Germany, aluminium as before
    S = models.system()
    old, new = S.score({p: 1}, s.CLIMATE_METHOD), S.score({moved.id: 1}, s.CLIMATE_METHOD)
    assert new != pytest.approx(old)
    for name in (DB, r["database"]):
        models.delete_database(name)


def test_flow_search_smart(client):
    names = lambda q, **kw: [(h["name"], h["categories"], h["unit"]) for h in s.search(q, kind="flow", **kw)]
    assert names("CO2")[0][:2] == ("Carbon dioxide", "emissions to air")  # formula, main compartment first
    assert names("Lachgas")[0][0] == "Dinitrogen monoxide"  # German name
    assert names("pm10")[0][0] == "Particulates, < 10 um"
    assert names("carbn dioxid")[0][0] == "Carbon dioxide"  # typo
    soil = names("nitrate soil")
    assert soil and all("soil" in c for _n, c, _u in soil)
    water = client.get("/api/search", params={"q": "nitrate", "kind": "flow", "comp": "water"}).json()
    assert water and all("water" in h["categories"] for h in water)
    bq = names("uranium", unit="radioactivity")
    assert bq and all(u in ("kBq", "Becquerel") for _n, _c, u in bq)
    opts = s.search_options()
    assert "radioactivity" in opts["flow_units"] and opts["compartments"] == ["air", "water", "soil", "resource"]


def test_methods_grouped_and_compared_by_topic(client):
    """ecoinvent's method names ("ecoinvent-3.x", "EF v3.1", …) are grouped by the method; one kind of impact
    (climate change) can be compared across all methods."""
    from lca_wrench import overview

    bd.projects.set_current(TEST_PROJECT)
    cfs = bd.Method(s.CLIMATE_METHOD).load()
    made = [("ecoinvent-3.99", "EF v3.1", "climate change", "global warming potential (GWP100)"),
            ("ecoinvent-3.99", "ReCiPe 2016 v1.03, midpoint (H)", "climate change", "global warming potential (GWP100)"),
            ("ecoinvent-3.99", "EF v3.1", "acidification", "accumulated exceedance (AE)")]
    try:
        for mt in made:
            m = bd.Method(mt)
            m.register(unit="kg CO2-Eq")
            m.write(cfs)
        assert overview.method_family(made[0]) == "EF v3.1"
        assert overview.method_name(made[0]) == "climate change · global warming potential (GWP100)"
        assert [overview.topic(m) for m in made] == ["climate", "climate", "acidification"]
        st = client.get("/api/state").json()
        ef = [m for m in st["methods"] if m["family"] == "EF v3.1"]
        assert len(ef) == 2 and {m["topic"] for m in ef} == {"climate", "acidification"}
        aid = str(bafu("Electricity, low voltage, at grid", "CH"))
        r = client.post("/api/categories", json={"id": aid, "amount": 1, "families": ["*"], "topic": "climate"}).json()
        fams = {f["family"]: f["rows"] for f in r["families"]}
        assert "EF v3.1" in fams and "ReCiPe 2016 v1.03, midpoint (H)" in fams
        assert all(row["topic"] == "climate" for rows in fams.values() for row in rows)
        assert len(fams["EF v3.1"]) == 1  # acidification left out
        ef_val = fams["EF v3.1"][0]["value"]
        assert ef_val == pytest.approx(s.calculate(aid, 1, s.CLIMATE_METHOD)["score"], rel=1e-9)
        one = client.post("/api/categories", json={"id": aid, "amount": 1, "families": ["EF v3.1"]}).json()
        assert len(one["families"][0]["rows"]) == 2
        x = client.post("/api/export/result", json={"id": aid, "amount": 1, "method": list(s.CLIMATE_METHOD),
                                                    "families": ["*"], "topic": "climate", "format": "csv"})
        assert x.status_code == 200 and "ReCiPe" in x.content.decode("utf-8-sig")
    finally:
        for mt in made:
            if mt in bd.methods:
                bd.Method(mt).deregister()


def test_reproject_foreground_from_elsewhere_and_together():
    """A foreground database not made in LCA Wrench (e.g. Activity Browser) can be moved too; moved together, a model
    using another one gets its inputs from the other one's copy."""
    bd.projects.set_current(TEST_PROJECT)
    ext, own = "Test AB foreground", "Test Region user"
    for name in (ext, own, f"{ext} [DE]", f"{own} [DE]"):
        if name in bd.databases:
            del bd.databases[name]
    elec = bd.get_node(id=bafu("Electricity, low voltage, at grid", "CH"))
    db = bd.Database(ext)
    db.register()
    db.write({(ext, "part"): {"name": "Part", "unit": "kilogram", "location": "CH", "type": "process",
                              "reference product": "part",
                              "exchanges": [{"input": (ext, "part"), "amount": 1, "type": "production"},
                                            {"input": elec.key, "amount": 5, "type": "technosphere"}]}})
    try:
        assert ext not in models.model_databases() and models.roles()[ext] == "model"
        models.create_database(own)
        p = int(models.create_process(own, "Device", "unit", "CH"))
        models.add_exchange(p, bd.get_node(database=ext, code="part").id, 2.0)
        made = reproject.reproject_many([ext, own], "Germany")
        assert [m["database"] for m in made] == [f"{ext} [DE]", f"{own} [DE]"]
        part = bd.get_node(database=f"{ext} [DE]", code="part")
        assert {bd.get_node(id=e.input.id)["location"] for e in part.technosphere()} == {"DE"}
        dev = next(iter(bd.Database(f"{own} [DE]")))
        assert [e.input["database"] for e in dev.technosphere()] == [f"{ext} [DE]"]  # the copy, not the original
        orig = bd.get_node(database=ext, code="part")
        assert {bd.get_node(id=e.input.id)["location"] for e in orig.technosphere()} == {"CH"}  # original as it was
    finally:
        for name in (f"{own} [DE]", f"{ext} [DE]", own):
            if name in bd.databases:
                models.delete_database(name)
        if ext in bd.databases:
            del bd.databases[ext]
