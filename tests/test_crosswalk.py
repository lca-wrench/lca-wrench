"""BAFU <-> ecoinvent (lca_wrench/crosswalk.py): an own model on the BAFU data of the test project, calculated with a small
ecoinvent-like database in another project.

Checked: side A equals the normal result; side B equals a hand calculation from the matched datasets, the unit
conversion and the direct emissions; suggestions, the user's choice, "no counterpart" and going back; export in the
form of sentier-mappings (ecoinvent by code only) and loading it again; the same database twice gives the same
result; one pair of datasets split by its own inputs, again at the next level; method and unit matching; the API.
"""

import json

import bw2data as bd
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import crosswalk as cw
from lca_wrench import engine, models, registry
from lca_wrench import service as s
from lca_wrench.api import app

OTHER = "lca-wrench-test-crosswalk"
EI = "ei-mini-3.10-cutoff"
EI_BIO = "ei-mini-biosphere"
EI_METHOD = ("ei-mini-3.10", "EF v3.1", "climate change", "global warming potential (GWP100)")
MODEL = "zz Crosswalk Modell"
# kg CO2 per unit of each dataset (no technosphere inputs, so this is its unit score)
EI_DATA = [
    ("market for electricity, low voltage", "electricity, low voltage", "CH", "kilowatt hour", 0.1),
    ("electricity production, hard coal", "electricity, high voltage", "CH", "kilowatt hour", 1.0),
    ("market for transport, freight, lorry 16-32 metric ton, EURO5", "transport, freight, lorry 16-32 metric ton, EURO5",
     "RER", "ton kilometer", 0.2),
]


@pytest.fixture(scope="module")
def setup():
    bd.projects.set_current(TEST_PROJECT)
    elec = next(h for h in s.search("electricity low voltage at grid", "CH") if h["unit"] == "kWh"
                and h["name"].lower().startswith("electricity, low voltage, at grid"))
    lorry = next(h for h in s.search("transport freight lorry 16t-32t") if h["unit"] == "tkm")
    heat = next(h for h in s.search("heat natural gas") if h["unit"] == "MJ")
    co2 = next(f for f in bd.Database("BAFU-2025-biosphere").search("carbon dioxide fossil", limit=50)
               if f["name"] == "Carbon dioxide, fossil" and f["categories"] == ("emissions to air", "low. pop."))
    # the other project: an ecoinvent-like database and an EF 3.1 method in ecoinvent's spelling
    if OTHER in bd.projects:
        s.remove_project(OTHER)
    bd.projects.create_project(OTHER)
    bd.projects.set_current(OTHER)
    bd.Database(EI_BIO).write({(EI_BIO, "co2"): {"name": "Carbon dioxide, fossil", "categories": ("air", "urban air close to ground"),
                                               "unit": "kilogram", "type": "emission"}})
    data = {}
    for i, (name, product, loc, unit, kg) in enumerate(EI_DATA):
        data[(EI, f"ei{i}")] = {"name": name, "reference product": product, "location": loc, "unit": unit,
                                "type": "processwithreferenceproduct",
                                "exchanges": [{"input": (EI, f"ei{i}"), "amount": 1.0, "type": "production"},
                                              {"input": (EI_BIO, "co2"), "amount": kg, "type": "biosphere"}]}
    bd.Database(EI).write(data)
    m = bd.Method(EI_METHOD)
    m.register(unit="kg CO2-Eq")
    m.write([((EI_BIO, "co2"), 1.0)])
    engine.bump_background(OTHER)
    # the model on BAFU data: electricity, transport, heat (no counterpart there) and a direct CO2 emission
    bd.projects.set_current(TEST_PROJECT)
    s.set_project(TEST_PROJECT)
    if MODEL in bd.databases:
        models.delete_database(MODEL)
    models.create_database(MODEL)
    pid = models.create_process(MODEL, "Velo", unit="unit")
    models.add_exchange(pid, elec["id"], 3.0)
    models.add_exchange(pid, lorry["id"], 2.0)
    models.add_exchange(pid, heat["id"], 5.0)
    models.add_exchange(pid, co2.id, 0.5)
    reg = registry.load()
    reg.pop("matches", None)
    registry.save(reg)
    yield {"model": int(pid), "elec": elec, "lorry": lorry, "heat": heat}
    bd.projects.set_current(TEST_PROJECT)
    if MODEL in bd.databases:
        models.delete_database(MODEL)
    s.remove_project(OTHER)
    bd.projects.set_current(TEST_PROJECT)


def _row(res, hit):
    return next(r for r in res["rows"] if r["name"] == hit["name"] and r["location"] == hit["location"])


def test_model_with_other_background(setup):
    res = cw.compare(setup["model"], 2.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD))
    assert bd.projects.current == TEST_PROJECT
    normal = s.unit_score(setup["model"], s.CLIMATE_METHOD) * 2.0
    assert res["a"]["score"] == pytest.approx(normal, rel=1e-9) and res["a"]["check"] == pytest.approx(normal, rel=1e-9)
    elec, lorry, heat = _row(res, setup["elec"]), _row(res, setup["lorry"]), _row(res, setup["heat"])
    assert elec["amount"] == pytest.approx(6.0) and lorry["amount"] == pytest.approx(4.0)
    assert elec["match"]["name"] == "market for electricity, low voltage" and elec["origin"] == "auto"
    assert elec["quality"] == "good"
    assert lorry["match"]["name"].startswith("market for transport, freight, lorry 16-32")
    assert heat["match"] is None and res["open_share"] > 0
    # B by hand: 6 kWh x 0.1 + 4 tkm x 0.2 + direct 2 x 0.5 kg CO2 x 1
    assert res["direct"]["score_b"] == pytest.approx(1.0, rel=1e-6) and not res["direct"]["unmatched"]
    assert res["b"]["score"] == pytest.approx(0.6 + 0.8 + 1.0, rel=1e-6)
    assert res["difference"] == pytest.approx(res["b"]["score"] - res["a"]["score"])
    # the parts of the difference: one per dataset plus the direct emissions, adding up exactly, largest first
    dr = res["drivers"]
    assert sum(x["diff"] for x in dr["parts"]) == pytest.approx(res["difference"], rel=1e-9, abs=1e-12)
    assert sum(x["share"] for x in dr["parts"]) == pytest.approx(1.0)
    sizes = [abs(x["diff"]) for x in dr["parts"]]
    assert sizes == sorted(sizes, reverse=True) and dr["parts"][-1]["cumulative"] == pytest.approx(1.0)
    assert 1 <= dr["explain80"] <= len(dr["parts"])
    by_kind = {x["kind"] for x in dr["parts"]}
    assert {"dataset", "missing", "direct"} <= by_kind
    heat_part = next(x for x in dr["parts"] if x["kind"] == "missing")
    assert heat_part["diff"] == pytest.approx(-heat["score_a"]) and heat_part["ratio"] is None
    e = next(x for x in dr["parts"] if x["row"] is not None and res["rows"][x["row"]]["name"] == elec["name"])
    assert e["ratio"] == pytest.approx(elec["score_b"] / elec["score_a"])


def test_choices_are_kept_and_can_be_undone(setup):
    elec = setup["elec"]
    r = _row(cw.compare(setup["model"], 1.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD)), elec)
    coal = next(h for h in cw.search(OTHER, EI, "electricity hard coal", r["unit_long"]))
    assert coal["convertible"] and bd.projects.current == TEST_PROJECT
    typo = cw.search(OTHER, EI, "electrcity hard coal", r["unit_long"])  # a typo is corrected
    assert typo[0]["code"] == coal["code"] and typo[0]["spelling"]
    cw.choose(r["database"], r["code"], EI, coal["code"])
    r2 = _row(cw.compare(setup["model"], 1.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD)), elec)
    assert r2["origin"] == "user" and r2["match"]["name"] == "electricity production, hard coal"
    assert r2["score_b"] == pytest.approx(3.0, rel=1e-6)
    cw.choose(r["database"], r["code"], EI, None)  # no counterpart
    r3 = _row(cw.compare(setup["model"], 1.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD)), elec)
    assert r3["origin"] == "user" and r3["match"] is None
    cw.choose(r["database"], r["code"], EI, None, reset=True)
    r4 = _row(cw.compare(setup["model"], 1.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD)), elec)
    assert r4["origin"] == "auto" and r4["match"]["name"] == "market for electricity, low voltage"


def test_export_and_load_mapping(setup):
    res = cw.compare(setup["model"], 1.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD))
    src = _row(res, setup["elec"])["database"]
    pairs = [{"source": r["code"], "target": r["match"]["code"]} for r in res["rows"] if r["match"]]
    assert cw.confirm_all(src, EI, pairs) == 2
    pkg = cw.export_mapping(src, EI)
    assert pkg["target_proprietary"] is True and len(pkg["replace"]) == 2
    for e in pkg["replace"]:
        assert set(e["target"]) == {"database", "code"}  # ecoinvent by code only, as sentier-mappings requires
        assert e["source"]["name"]
    reg = registry.load()
    reg.pop("matches")
    registry.save(reg)
    assert cw.import_mapping(src, EI, json.dumps(pkg).encode()) == 2
    res = cw.compare(setup["model"], 1.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD))
    assert {r["origin"] for r in res["rows"] if r["match"]} == {"file"}
    with pytest.raises(ValueError, match="replace"):
        cw.import_mapping(src, EI, b'{"name": "x"}')
    with pytest.raises(ValueError, match="kein JSON"):
        cw.import_mapping(src, EI, b"\xff")
    reg = registry.load()
    reg.pop("matches")
    registry.save(reg)


def test_same_database_gives_the_same_result(setup):
    elec = int(setup["elec"]["id"])
    res = cw.compare(elec, 2.0, s.CLIMATE_METHOD, TEST_PROJECT, setup["elec"]["database"])
    assert [r["origin"] for r in res["rows"]] == ["same"]
    assert res["b"]["score"] == pytest.approx(res["a"]["score"], rel=1e-9)
    assert res["drivers"]["parts"] == [] and res["drivers"]["explain80"] == 0
    assert res["a"]["score"] == pytest.approx(2.0 * s.unit_score(elec, s.CLIMATE_METHOD), rel=1e-9)
    with pytest.raises(ValueError, match="keine passende Methode"):
        cw.compare(elec, 1.0, s.CLIMATE_METHOD, OTHER, EI)


def test_trace_one_level_deeper(setup):
    """The part of one pair of datasets, split by their own inputs, adds up exactly, at every level."""
    elec = setup["elec"]
    code = bd.get_node(id=int(elec["id"]))["code"]
    unit = s.unit_score(int(elec["id"]), s.CLIMATE_METHOD)
    # the same dataset on both sides: every input pairs with itself, no difference anywhere
    same = cw.trace(int(elec["id"]), code, 2.0, 2.0, s.CLIMATE_METHOD, TEST_PROJECT, elec["database"], list(s.CLIMATE_METHOD))
    assert same["a"]["score"] == pytest.approx(2.0 * unit, rel=1e-9) and same["difference"] == pytest.approx(0, abs=1e-12)
    assert same["parts"] == [] and same["counts"]["paired"] == same["counts"]["a"] == same["counts"]["b"] > 0
    # another dataset of the same database: inputs pair by code or name; the parts add up to the pair's difference
    medium = next(h for h in s.search("electricity medium voltage at grid", "CH") if h["unit"] == "kWh"
                  and h["name"].lower().startswith("electricity, medium voltage, at grid"))
    mcode = bd.get_node(id=int(medium["id"]))["code"]
    res = cw.trace(int(elec["id"]), mcode, 3.0, 1.5, s.CLIMATE_METHOD, TEST_PROJECT, elec["database"], list(s.CLIMATE_METHOD))
    expect = 1.5 * s.unit_score(int(medium["id"]), s.CLIMATE_METHOD) - 3.0 * unit
    assert res["difference"] == pytest.approx(expect, rel=1e-9)
    assert sum(x["diff"] for x in res["parts"]) == pytest.approx(expect, rel=1e-9, abs=1e-12)
    assert res["counts"]["paired"] >= 1
    sizes = [abs(x["diff"]) for x in res["parts"]]
    assert sizes == sorted(sizes, reverse=True)
    # a pair splits again, down to its own inputs
    pair = next(x for x in res["parts"] if x["kind"] == "pair" and x["a"]["id"] != x["b"]["id"])
    a_unit = pair["a"]["amount"]
    deeper = cw.trace(int(pair["a"]["id"]), pair["b"]["code"], pair["a"]["amount"], pair["b"]["amount"], s.CLIMATE_METHOD,
                      TEST_PROJECT, elec["database"], list(s.CLIMATE_METHOD))
    assert deeper["difference"] == pytest.approx(pair["diff"], rel=1e-9, abs=1e-15) and a_unit
    assert sum(x["diff"] for x in deeper["parts"]) == pytest.approx(pair["diff"], rel=1e-9, abs=1e-15)
    # to ecoinvent, where the market has no inputs: everything here is "only here", plus the own emissions
    ei = cw.trace(int(elec["id"]), "ei0", 6.0, 6.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD))
    assert bd.projects.current == TEST_PROJECT
    assert ei["b"]["score"] == pytest.approx(0.6, rel=1e-6) and ei["a"]["score"] == pytest.approx(6.0 * unit, rel=1e-9)
    assert {x["kind"] for x in ei["parts"]} <= {"only_a", "direct"} and ei["counts"]["b"] == 0
    assert sum(x["diff"] for x in ei["parts"]) == pytest.approx(ei["difference"], rel=1e-9)
    with pytest.raises(KeyError, match="nicht mehr"):
        cw.trace(int(elec["id"]), "gibt-es-nicht", 1.0, 1.0, s.CLIMATE_METHOD, OTHER, EI, list(EI_METHOD))


def test_flows_in_other_spellings():
    assert cw._flow_name("Carbon Dioxide (fossil)") == cw._flow_name("Carbon dioxide, fossil")
    air = [("air",), ("emissions to air", "low. pop."), ("Emissions", "Emissions to air", "Emissions to air, unspecified")]
    assert {cw._compartment(c) for c in air} == {"air"}
    assert cw._compartment(("natural resource", "in water")) == "resource" != cw._compartment(("water", "ocean"))
    assert cw._compartment(("Resources", "in air")) == "resource"


def test_methods_and_units():
    ecoinvent = [("ecoinvent-3.10", "EF v3.1", "climate change", "global warming potential (GWP100)"),
                 ("ecoinvent-3.10", "EF v3.1", "climate change: biogenic", "global warming potential (GWP100)"),
                 ("ecoinvent-3.10", "EF v3.1", "human toxicity: carcinogenic", "comparative toxic unit for human (CTUh)"),
                 ("ecoinvent-3.10", "EF v3.1", "energy resources: non-renewable", "abiotic depletion potential (ADP): fossil fuels"),
                 ("ecoinvent-3.10", "EF v3.1", "particulate matter formation", "impact on human health"),
                 ("ecoinvent-3.10", "EF v3.1", "photochemical oxidant formation: human health", "tropospheric ozone concentration increase"),
                 ("ecoinvent-3.10", "EF v3.0", "climate change", "global warming potential (GWP100)")]
    sentier = lambda c: ("sentier", "EF v3.1", c)  # noqa: E731
    assert cw.match_method(sentier("Climate change"), ecoinvent) == ecoinvent[0]
    assert cw.match_method(sentier("Climate change-Biogenic"), ecoinvent) == ecoinvent[1]
    assert cw.match_method(sentier("Human toxicity, cancer"), ecoinvent) == ecoinvent[2]
    assert cw.match_method(sentier("Resource use, fossils"), ecoinvent) == ecoinvent[3]
    assert cw.match_method(sentier("EF-particulate Matter"), ecoinvent) == ecoinvent[4]
    assert cw.match_method(sentier("Photochemical ozone formation - human health"), ecoinvent) == ecoinvent[5]
    assert cw.match_method(sentier("Ozone depletion"), ecoinvent) is None
    assert cw.match_method(("Werkbank", "Klimawandel"), [("Werkbank", "Klimawandel")]) == ("Werkbank", "Klimawandel")
    assert cw._unit_key("kg CO2 eq") == cw._unit_key("kg CO2-Eq") != cw._unit_key("kg SO2-eq")
    assert cw.factor("kilowatt hour", "megajoule") == pytest.approx(3.6)
    assert cw.factor("kilogram", "ton") == pytest.approx(1e-3)
    assert cw.factor("normal cubic meter", "cubic meter") == 1.0
    assert cw.factor("kilogram", "megajoule") is None


def test_api(setup):
    c = TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"})
    t = c.get("/api/crosswalk/targets", params={"project": OTHER}).json()
    assert [d["name"] for d in t["databases"]] == [EI] and list(EI_METHOD) in t["methods"]
    r = c.post("/api/crosswalk", json={"id": str(setup["model"]), "amount": 1.0, "method": list(s.CLIMATE_METHOD),
                                       "project": OTHER, "database": EI, "target_method": list(EI_METHOD)})
    assert r.status_code == 200, r.text
    res = r.json()
    row = _row(res, setup["elec"])
    r = c.post("/api/crosswalk/choose", json={"source_database": row["database"], "source_code": row["code"],
                                              "target_database": EI, "target_code": row["match"]["code"]})
    assert r.status_code == 200
    r = c.get("/api/crosswalk/export", params={"source_database": row["database"], "target_database": EI})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert len(r.json()["replace"]) == 1
    r = c.post("/api/crosswalk/import", params={"source_database": row["database"], "target_database": EI},
               content=r.content)
    assert r.json()["saved"] == 1
    r = c.post("/api/crosswalk", json={"id": str(setup["model"]), "amount": 1.0, "method": list(s.CLIMATE_METHOD),
                                       "project": OTHER, "database": "gibt-es-nicht", "target_method": list(EI_METHOD)})
    assert r.status_code == 404
    r = c.post("/api/crosswalk/trace", json={"source_id": str(row["id"]), "target_code": row["match"]["code"],
                                             "scale_a": row["amount"], "scale_b": row["match"]["amount"],
                                             "method": list(s.CLIMATE_METHOD), "project": OTHER, "database": EI,
                                             "target_method": list(EI_METHOD)})
    assert r.status_code == 200, r.text
    assert r.json()["difference"] == pytest.approx(row["score_b"] - row["score_a"], rel=1e-6)
    assert bd.projects.current == TEST_PROJECT
    reg = registry.load()
    reg.pop("matches", None)
    registry.save(reg)


def test_search_nearest_location_first():
    """Manual search in the other database: convertible unit first, then the location nearest to the one asked for."""
    from collections import defaultdict

    idx = cw.TargetIndex.__new__(cw.TargetIndex)
    idx.rows, idx.words = {}, defaultdict(set)
    for i, (loc, unit) in enumerate([("RoW", "kilowatt hour"), ("DE", "kilowatt hour"), ("RER", "kilowatt hour"),
                                     ("CH", "unit"), ("GLO", "kilowatt hour")]):
        idx.rows[i] = {"code": str(i), "name": "market for electricity", "product": "", "location": loc, "unit": unit}
        for w in ("market", "electricity"):
            idx.words[w].add(i)
    rows, spelling = idx.search("electricity", "kilowatt hour", location="Germany")
    assert [d["location"] for d in rows] == ["DE", "RER", "GLO", "RoW", "CH"] and spelling is None
    rows, spelling = idx.search("electrcity", "kilowatt hour", location="CH")
    assert spelling == "electricity" and [d["location"] for d in rows][:3] == ["RER", "GLO", "RoW"]
