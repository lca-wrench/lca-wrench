"""Factors that depend on the location of the emitting activity (regional.py), on the BAFU 2025 data.

The reference is computed here independently: bw2calc's inventory (supply, biosphere matrix), and for every entry of
a flow with factors by location the factor of the activity's location, looked up by the simple rules written out in
`expected_factor`. Methods without such factors must give exactly what they gave before, and what bw2calc gives.
"""

import re

import bw2calc as bc
import bw2data as bd
import numpy as np
import pytest
from bw2data.backends.schema import ActivityDataset as AD
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import analysis, engine, models, regional, regions, service as s
from lca_wrench import montecarlo as mc
from lca_wrench.api import app

BIO = "BAFU-2025-biosphere"
M_ROWS = ("zz Regional Test", "CO2 by location")
M_COPY = ("zz Regional Test", "CO2 country copy")
M_PV = ("zz Regional Test", "CO2 production volume")
TABLE = {"CH": 2.0, "DE": 3.0, "CS": 5.0, "US": 0.5}  # factors by location of fossil CO2; 1.0 elsewhere
ALIAS = {"RS": "CS", "ME": "CS", "XK": "CS"}
COPY_DB, PV_DB, MODEL_DB = "zz-regional-copies", "zz-regional-pv", "zz-regional-model"


@pytest.fixture
def switch():
    """Factors by location as the test sets them; afterwards on again (the default)."""
    yield regional.set_enabled
    regional.set_enabled(True)


@pytest.fixture(scope="module")
def co2():
    bd.projects.set_current(TEST_PROJECT)
    ids = [f.id for f in bd.Database(BIO) if f["name"] == "Carbon dioxide, fossil" and f["categories"][0] == "emissions to air"]
    assert len(ids) >= 3
    return ids


@pytest.fixture(scope="module")
def methods(co2):
    """A method with rows by location (Brightway's convention), one with a country copy, one for the weights."""
    bd.projects.set_current(TEST_PROJECT)
    m = bd.Method(M_ROWS)
    m.register(unit="kg CO2")
    m.write([(f, 1.0) for f in co2] + [(f, v, loc) for f in co2 for loc, v in TABLE.items()])
    # a copy of the first CO2 flow for Switzerland, in a flow list of its own, as the EF 3.1 water flows of a PEF project
    gen = bd.get_node(id=co2[0])
    if COPY_DB in bd.databases:
        del bd.databases[COPY_DB]
    bd.Database(COPY_DB).write({(COPY_DB, f"{gen['code']}_CH"): {
        "name": f"{gen['name']}, CH", "categories": tuple(gen["categories"]), "unit": gen["unit"], "type": "emission",
        "location": "CH"}})
    copy = bd.get_node(database=COPY_DB, code=f"{gen['code']}_CH").id
    m = bd.Method(M_COPY)
    m.register(unit="kg CO2")
    m.write([(f, 1.0) for f in co2] + [(copy, 2.0)])
    yield {"copy": copy, "generic": co2[0]}
    bd.projects.set_current(TEST_PROJECT)
    for mt in (M_ROWS, M_COPY):
        bd.Method(mt).deregister()
    if COPY_DB in bd.databases:
        del bd.databases[COPY_DB]


def bafu(name, loc):
    return AD.select(AD.id).where(AD.database == "BAFU-2025-v2", AD.name == name, AD.location == loc).scalar()


def expected_factor(loc, table=TABLE, normal=1.0):
    """The rules of regional.py, written out: own, alias, country of a part, equal average over a region."""
    def own(code):
        return table.get(code, table.get(ALIAS.get(code)))
    if own(loc) is not None:
        return own(loc)
    m = re.match(r"^([A-Z]{2})-", loc or "")
    if m and not loc.startswith("UN-"):
        return own(m.group(1)) if own(m.group(1)) is not None else normal
    members = regions.members(loc)
    if members:
        vals = [own(c) for c in members]
        return float(np.mean([v if v is not None else normal for v in vals])) if any(v is not None for v in vals) else normal
    return normal


def independent(node_id, amount, method, co2, table=TABLE):
    """Score from bw2calc's inventory, each CO2 entry with the factor of its activity's location; and without."""
    lca = bc.LCA({bd.get_node(id=node_id): amount}, method)
    lca.lci()
    lca.lcia()
    acts = {i: a for a, i in lca.dicts.activity.items()}
    flows = {i: f for f, i in lca.dicts.biosphere.items()}
    loc = dict(AD.select(AD.id, AD.location).where(AD.id << list(acts.values())).tuples())
    B = lca.biosphere_matrix.tocoo()
    x = lca.supply_array
    score = gross = 0.0
    for r, j, b in zip(B.row, B.col, B.data):
        if flows[r] in co2:
            v = expected_factor(loc[acts[j]], table) * b * x[j]
            score += v
            gross += abs(v)
    return score, gross, lca


def test_regions():
    assert regions.members("CH") is None and regions.members("GLO") is None and regions.members("OCE") is None
    assert regions.members("RER w/o CH+DE") == regions.members("RER") - {"CH", "DE"}
    assert regions.members("Europe without Switzerland and Austria") == regions.members("RER") - {"CH", "AT"}
    assert regions.members("Europe, without Russia and Turkey") == regions.members("RER") - {"RU", "TR"}
    assert regions.members("UCTE without Germany") == regions.members("UCTE") - {"DE"}
    assert regions.members("Europe without NORDEL (NCPA)") == regions.members("RER") - regions.members("NORDEL")
    assert regions.members("Europe without Atlantis") is None
    assert regions.country_of("CA-QC") == "CA" and regions.country_of("US-WECC") == "US"
    assert regions.country_of("UN-OCEANIA") is None and regions.country_of("CH") is None
    assert len(regions.members("UN-AFRICA")) == 54 and len(regions.members("UN-EUROPE")) == 45  # with Kosovo


def test_without_factors_by_location_nothing_changes(switch):
    """A method without rows by location or country copies: no part by location, the same numbers either way."""
    el = bafu("Electricity, low voltage, at grid", "CH")
    for m in (s.CLIMATE_METHOD, s.UBP_TOTAL_METHOD):
        assert regional.table(m) is None
        switch(True)
        S = models.system_for(el)
        assert S.regional(m) is None and S.bg.regional(m) is None
        on = S.score({el: 1.0}, m), S.direct(m).copy()
        switch(False)
        S = models.system_for(el)
        assert S.score({el: 1.0}, m) == on[0] and np.array_equal(S.direct(m), on[1])
        lca = bc.LCA({bd.get_node(id=el): 1.0}, m)
        lca.lci()
        lca.lcia()
        assert abs(on[0] - lca.score) <= 1e-7 * float(abs(lca.characterized_inventory).sum())


def test_table_from_rows_and_copies(methods, co2):
    T = regional.table(M_ROWS)
    assert set(T.factors) == set(co2) and all(T.factors[f] == TABLE for f in co2)
    assert all(T.source[(f, loc)] is None for f in co2 for loc in TABLE)
    # bw2calc uses only the global rows: the stored method gives its normal result
    assert engine.method_cfs(M_ROWS) == {f: 1.0 for f in co2}
    C = regional.table(M_COPY)
    assert C.factors == {methods["generic"]: {"CH": 2.0}} and C.source == {(methods["generic"], "CH"): methods["copy"]}
    rows = regional.table_rows(M_COPY)
    assert len(rows) == 1 and rows[0]["source"] == "copy" and rows[0]["location"] == "CH" and rows[0]["normal"] == 1.0


@pytest.mark.parametrize("name,loc", [("Electricity, low voltage, at grid", "CH"), ("Aluminium, primary, at plant", "RER")])
def test_scores_match_independent_calculation(methods, co2, switch, name, loc):
    node = bafu(name, loc)
    ref, gross, lca = independent(node, 2.0, M_ROWS, co2)
    switch(True)
    S = models.system_for(node)
    on = S.score({node: 2.0}, M_ROWS)
    assert abs(on - ref) <= 1e-9 * gross
    switch(False)
    off = models.system_for(node).score({node: 2.0}, M_ROWS)
    assert abs(off - lca.score) <= 1e-7 * float(abs(lca.characterized_inventory).sum())  # bw2calc: global rows only
    assert abs(on - off) > 1e-3 * abs(off)  # the factors by location matter here


def test_country_copy_applies_to_the_generic_flow(methods, co2):
    node = bafu("Electricity, low voltage, at grid", "CH")
    only_ch = {"CH": 2.0}
    # the copy itself is not emitted by any dataset; the generic flow gets its factor in Swiss datasets
    ref, gross, _lca = independent(node, 1.0, M_COPY, [methods["generic"]], only_ch)
    ref += independent(node, 1.0, M_COPY, co2[1:], {})[0]
    assert abs(models.system_for(node).score({node: 1.0}, M_COPY) - ref) <= 1e-9 * (gross + abs(ref))


def test_parts_add_up(methods, co2, switch):
    node = bafu("Electricity, low voltage, at grid", "CH")
    switch(False)
    off = models.system_for(node).score({node: 1.0}, M_ROWS)
    switch(True)
    S = models.system_for(node)
    c = analysis.contributions(S, node, 1.0, M_ROWS)
    score = c["score"]
    assert score == pytest.approx(S.score({node: 1.0}, M_ROWS), rel=1e-9)
    assert sum(r["value"] for r in c["by_activity"]) + c["by_activity_rest"] == pytest.approx(score, rel=1e-9)
    assert sum(r["value"] for r in c["by_flow"]) + c["by_flow_rest"] == pytest.approx(score, rel=1e-9)
    loc = c["by_location"]
    assert sum(r["value"] for r in loc) == pytest.approx(score, rel=1e-9)
    # the parts by location add up to the difference the factors by location make
    assert sum(r["regional"] for r in loc) == pytest.approx(score - off, rel=1e-9)
    assert c["regional"]["effect"] == pytest.approx(score - off, rel=1e-9) and c["regional"]["available"]
    by = {r["location"]: r for r in loc}
    assert by["CH"]["how"] == "own" and by["CH"]["kind"] == "country"
    regions_seen = [r for r in loc if r["kind"] == "region" and r["regional"]]
    assert regions_seen and all(r["how"] == "region" and r["weighting"] == "equal" for r in regions_seen)
    assert by["GLO"]["regional"] == 0.0 and by["GLO"]["how"] == "normal"


def test_factors_by_place(methods, co2):
    """Each column's factors: own, alias, region average (equal weights in BAFU), normal factor for GLO and RoW."""
    node = bafu("Electricity, low voltage, at grid", "CH")
    S = models.system_for(node)
    places = S.bg.places()
    k = S.bio_row[co2[0]]
    seen = set()
    for j in range(S.nb):
        loc = places.column(j).location
        if loc in seen:
            continue
        seen.add(loc)
        assert S.column_factors(M_ROWS, j)[k] == pytest.approx(expected_factor(loc), rel=1e-12), loc
    assert {"CH", "DE", "RER", "UCTE", "GLO", "RoW", "CS", "RS", "OCE"} <= seen


def test_production_volume_weights(co2):
    """A region's factor: its countries weighted by the production volumes of the datasets with the same name and
    product there; equally where there are none."""
    bd.projects.set_current(TEST_PROJECT)
    f = co2[0]
    if PV_DB in bd.databases:
        del bd.databases[PV_DB]

    def act(code, name, loc, pv=None):
        prod = {"input": (PV_DB, code), "amount": 1.0, "type": "production"}
        if pv is not None:
            prod["production volume"] = pv
        return {"name": name, "reference product": name, "unit": "kilogram", "location": loc, "type": "process",
                "exchanges": [prod, {"input": bd.get_node(id=f).key, "amount": 1.0, "type": "biosphere"}]}

    bd.Database(PV_DB).write({(PV_DB, "w-rer"): act("w-rer", "widget", "RER"), (PV_DB, "w-de"): act("w-de", "widget", "DE", 3.0),
                              (PV_DB, "w-fr"): act("w-fr", "widget", "FR", 1.0),
                              (PV_DB, "g-eu"): act("g-eu", "gadget", "Europe without Switzerland")})
    m = bd.Method(M_PV)
    m.register(unit="kg CO2")
    m.write([(f, 1.0), (f, 10.0, "DE"), (f, 2.0, "FR")])
    try:
        S = engine.alone(PV_DB)
        node = lambda code: bd.get_node(database=PV_DB, code=code).id  # noqa: E731
        assert S.score({node("w-rer"): 1.0}, M_PV) == pytest.approx((3 * 10.0 + 1 * 2.0) / 4, rel=1e-12)
        members = regions.members("Europe without Switzerland")
        equal = np.mean([10.0 if c == "DE" else 2.0 if c == "FR" else 1.0 for c in members])
        assert S.score({node("g-eu"): 1.0}, M_PV) == pytest.approx(equal, rel=1e-12)
        assert S.score({node("w-de"): 1.0}, M_PV) == pytest.approx(10.0, rel=1e-12)
        place = S.bg.places().column(S.bg.act_col[node("w-rer")])
        assert place.weighting == "volume" and dict(place.weights) == {"DE": 0.75, "FR": 0.25}
    finally:
        bd.Method(M_PV).deregister()
        del bd.databases[PV_DB]


def test_own_model_process(methods, co2):
    """A process of a model gets the factor of its own location, and its data sheet adds up to its direct impact."""
    bd.projects.set_current(TEST_PROJECT)
    if MODEL_DB in bd.databases:
        models.delete_database(MODEL_DB)
    models.create_database(MODEL_DB)
    try:
        p = int(models.create_process(MODEL_DB, "Trocknen", "kilogram", "DE"))
        models.add_exchange(p, co2[0], 2.0)
        models.add_exchange(p, bafu("Electricity, low voltage, at grid", "CH"), 1.0)
        S = models.system()
        el = bafu("Electricity, low voltage, at grid", "CH")
        assert S.score({p: 1.0}, M_ROWS) == pytest.approx(2.0 * 3.0 + S.score({el: 1.0}, M_ROWS), rel=1e-9)
        d = models.process_detail(p, M_ROWS)
        assert sum(b["contribution"] for b in d["biosphere"]) == pytest.approx(d["direct"], rel=1e-12)
        assert d["direct"] == pytest.approx(6.0, rel=1e-12)
    finally:
        models.delete_database(MODEL_DB)


def test_background_data_sheet_adds_up(methods):
    node = bafu("Electricity, high voltage, production DE, at grid", "DE") or bafu("Electricity, at cogen 1MWe lean burn, allocation exergy", "CH")
    d = models.process_detail(node, M_ROWS)
    assert d["direct"] is not None
    assert sum(b["contribution"] for b in d["biosphere"]) == pytest.approx(d["direct"], rel=1e-9, abs=1e-15)


def test_cross_check_with_bw2calc(methods):
    el = bafu("Electricity, low voltage, at grid", "CH")
    v = s.verify([{"id": el, "amount": 1.0}], [M_ROWS, s.CLIMATE_METHOD])
    assert v["ok"] and v["checked"] == 2


def test_monte_carlo_matches_bw2calc_same_seed(methods, co2):
    """The draws with factors by location: bw2calc's sampled inventory, each CO2 entry with its location's factor."""
    el = bafu("Electricity, low voltage, at grid", "CH")
    n, seed = 3, 11
    draws = mc.run_chunk(TEST_PROJECT, [(el, 1.0)], [M_ROWS], n, seed)
    bd.projects.set_current(TEST_PROJECT)
    lca = bc.LCA({bd.get_node(id=el): 1.0}, M_ROWS, use_distributions=True, seed_override=seed)
    lca.lci()
    lca.lcia()
    acts = {i: a for a, i in lca.dicts.activity.items()}
    flows = {i: f for f, i in lca.dicts.biosphere.items()}
    loc = dict(AD.select(AD.id, AD.location).where(AD.id << list(acts.values())).tuples())
    for i in range(n):
        if i:
            next(lca)
        B, x = lca.biosphere_matrix.tocoo(), lca.supply_array
        ref = sum(expected_factor(loc[acts[j]]) * b * x[j] for r, j, b in zip(B.row, B.col, B.data) if flows[r] in co2)
        assert draws[i, 0, 0] == pytest.approx(ref, rel=1e-8)


def test_versions_split_a_move_to_another_place(methods, co2):
    """Version 2: the Swiss dataset that emits most CO2 for the Swiss electricity mix sits in Germany. The difference
    splits exactly, and it is the moved dataset's part: the change of its factor by location (CH 2.0 to DE 3.0)."""
    import uuid

    from lca_wrench import versions

    # a name of its own each run: Windows can keep a deleted project's files locked, and the folder then stays
    v2 = f"lca-wrench-test-regional-v2-{uuid.uuid4().hex[:8]}"
    bd.projects.set_current(TEST_PROJECT)
    node = bafu("Electricity, low voltage, at grid", "CH")
    S = models.system_for(node)
    d = S.direct(M_ROWS) * S.supply({node: 1.0})
    moved = max((abs(d[j]), int(S.col_ids[j])) for j in range(S.nb)
                if S.bg.places().column(j).location == "CH" and int(S.col_ids[j]) != node and d[j])[1]
    bd.projects.copy_project(v2, switch=True)
    try:
        up = bd.get_node(id=moved)
        up["location"] = "DE"  # the matrices stay as they are; the engine reads the places from the database
        up.save()
        engine.bump_background(v2)
        h1 = independent(node, 1.0, M_ROWS, co2)[0]
        bd.projects.set_current(TEST_PROJECT)
        h0 = independent(node, 1.0, M_ROWS, co2)[0]
        r = versions.compare(node, 1.0, M_ROWS, v2, "BAFU-2025-v2")
        gross = abs(h0) + abs(h1)
        assert r["difference"] == pytest.approx(h1 - h0, abs=1e-9 * gross)
        assert abs(r["rest"]) <= 1e-9 * gross  # the parts add up to the difference
        assert h1 > h0
        part = next(x for x in r["parts"] if x["name"] == bd.get_node(id=moved)["name"] and x["location"] == "CH")
        assert part["contribution"] == pytest.approx(h1 - h0, rel=1e-9)
        assert versions.detail(part["k"])["total"] == pytest.approx(part["contribution"], rel=1e-9)
    finally:
        bd.projects.set_current(TEST_PROJECT)
        try:
            bd.projects.delete_project(v2, delete_dir=True)
        except OSError:
            pass  # Windows keeps the files of a just-closed project locked for a while


def test_api(methods, co2, switch):
    el = bafu("Electricity, low voltage, at grid", "CH")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        r = client.post("/api/calc", json={"id": str(el), "amount": 1, "method": list(M_ROWS)}).json()
        g = r["regional"]
        assert g["available"] and g["enabled"] and g["flows"] == len(co2) and g["locations"] == len(TABLE) and g["processes"]
        assert sum(x["value"] for x in r["by_location"]) == pytest.approx(r["score"], rel=1e-9)
        rows = client.post("/api/regional/factors", json={"method": list(M_ROWS)}).json()["rows"]
        assert {x["location"] for x in rows} == set(TABLE) and len(rows) == len(co2) * len(TABLE)
        st = client.post("/api/regional", json={"enabled": False}).json()
        assert st["enabled"] is False and regional.enabled() is False
        r2 = client.post("/api/calc", json={"id": str(el), "amount": 1, "method": list(M_ROWS)}).json()
        assert r2["regional"]["effect"] == 0.0 and r2["score"] == pytest.approx(r["score"] - g["effect"], rel=1e-9)
        assert client.get("/api/state").json()["regional"]["enabled"] is False
