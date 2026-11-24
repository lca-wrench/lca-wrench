"""Reference tests for the live engine and own models: every number must match plain bw2calc.

Builds a small model database inside the BAFU project (loop between two
processes, an avoided product, a flow no background process emits) and
deletes it afterwards. Needs the BAFU project from setup_daten.py.
"""

import os

import bw2calc as bc
import bw2data as bd
import numpy as np
import pytest
from bw2data.backends.schema import ActivityDataset as AD

from conftest import TEST_PROJECT
from lca_wrench import analysis, engine, models, registry, service as s, setups

PROJECT = TEST_PROJECT
DB = "zz Werkbank Testmodell"
BIO = "zz Werkbank Testbiosphäre"
RARE_METHOD = ("zz Werkbank Test", "Testgas")

METHODS = [s.CLIMATE_METHOD, s.UBP_TOTAL_METHOD, (s.PROFILE_FAMILY, "Main air pollutants and PM"),
           (s.PROFILE_FAMILY, "Radioactive substances into air"), ("zz Werkbank Test", "Testgas")]


def bafu(name, loc):
    return AD.select(AD.id).where(AD.database == "BAFU-2025-v2", AD.name == name, AD.location == loc).scalar()


def flow(name, cats):
    for f in bd.Database("BAFU-2025-biosphere"):
        if f["name"] == name and tuple(f["categories"]) == cats:
            return f.id
    raise LookupError(name)


@pytest.fixture(scope="module")
def model():
    bd.projects.set_current(PROJECT)
    if DB in bd.databases:
        del bd.databases[DB]
    models.create_database(DB)
    el = bafu("Electricity, low voltage, at grid", "CH")
    al = bafu("Aluminium, primary, at plant", "RER")
    tr = bafu("Transport, freight, lorry, 7.5t-16t gross weight, fleet average", "CH")
    co = bafu("Concrete, normal, at plant, with resource correction", "CH")
    co2 = flow("Carbon dioxide, fossil", ("emissions to air",))
    # a flow that no background process knows, so it only exists in the model's biosphere rows
    if BIO in bd.databases:
        del bd.databases[BIO]
    bd.Database(BIO).write({(BIO, "rare"): {"name": "Testgas", "categories": ("emissions to air",),
                                            "unit": "kilogram", "type": "emission"}})
    rare = bd.get_node(database=BIO, code="rare").id
    bd.Method(RARE_METHOD).register(unit="kg")
    bd.Method(RARE_METHOD).write([(rare, 100.0), (co2, 1.0)])
    p1 = int(models.create_process(DB, "Gehäuse", "kilogram", "CH"))
    p2 = int(models.create_process(DB, "Gerät", "unit", "CH"))
    p3 = int(models.create_process(DB, "Service", "unit", "CH"))
    ex = {}
    ex["p1_el"] = models.add_exchange(p1, el, 2.0)
    ex["p1_al"] = models.add_exchange(p1, al, 0.5)
    ex["p1_co2"] = models.add_exchange(p1, co2, 1.0)
    ex["p1_rare"] = models.add_exchange(p1, rare, 0.01)
    ex["p2_p1"] = models.add_exchange(p2, p1, 3.0)
    ex["p2_tr"] = models.add_exchange(p2, tr, 10.0)
    ex["p2_co"] = models.add_exchange(p2, co, 0.2, "substitution")
    ex["p2_p3"] = models.add_exchange(p2, p3, 0.2)
    ex["p3_p2"] = models.add_exchange(p3, p2, 0.1)
    ex["p3_el"] = models.add_exchange(p3, el, 5.0)
    yield {"p1": p1, "p2": p2, "p3": p3, "el": el, "al": al, "ex": ex}
    bd.projects.set_current(PROJECT)
    models.delete_database(DB)
    del bd.databases[BIO]
    bd.Method(RARE_METHOD).deregister()
    reg = registry.load()
    reg.get("journal", {}).pop(PROJECT, None)
    registry.save(reg)


def bw2calc_lca(node_id, amount, method):
    lca = bc.LCA({bd.get_node(id=node_id): amount}, method)
    lca.lci()
    lca.lcia()
    return lca


def close(a, lca):
    """Equal to bw2calc within bw2calc's own precision (it does not refine; up to ~2e-8 on loops),
    measured against the gross impact because credits and burdens can cancel."""
    gross = float(abs(lca.characterized_inventory).sum())
    return abs(a - lca.score) <= 1e-7 * gross + 1e-15


def refined_full_solve(S, node_id, amount=1.0):
    """Independent reference: the whole system in one matrix, LU plus three refinement steps."""
    from scipy.sparse.linalg import splu
    A = S.A.tocsc()
    lu = splu(A)
    return engine.refined(lu.solve, A, S.demand_vector({node_id: amount}), steps=3)


def test_model_is_foreground(model):
    S = models.system()
    assert models.roles()[DB] == "model"
    own = [i for i in S.fg.act_ids if S.fg.nodes[int(i)]["database"] == DB]
    assert len(own) == 3 and not S.fg.errors
    assert len(S.fg.extra_bio) == 1  # the test gas is only known to the model
    assert models.roles()["BAFU-2025-v2"] == "background"


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("which", ["p1", "p2", "p3", "el"])
def test_scores_match_bw2calc(model, method, which):
    S = models.system()
    for amount in (1.0, 2.5):
        lca = bw2calc_lca(model[which], amount, method)
        assert close(S.score({model[which]: amount}, method), lca), (which, method)


def test_engine_matches_refined_full_solve(model):
    """The block solver must equal one big refined solve to ~1e-12, for models and background alike."""
    S = models.system()
    for which in ("p1", "p2", "p3", "el"):
        x = refined_full_solve(S, model[which])
        assert np.allclose(S.supply({model[which]: 1.0}), x, rtol=1e-10, atol=1e-14 * np.abs(x).max())
        for m in METHODS:
            ref_ci = S.cvec(m) * (S.B @ x)
            gross = float(np.abs(ref_ci).sum()) or 1.0
            assert abs(S.score({model[which]: 1.0}, m) - ref_ci.sum()) <= 1e-12 * gross, (which, m)


def test_supply_and_inventory_match_bw2calc(model):
    """Our solution must solve the system at least as well as bw2calc's, and both must agree."""
    S = models.system()
    lca = bw2calc_lca(model["p2"], 1.0, s.CLIMATE_METHOD)
    x = S.supply({model["p2"]: 1.0})
    ref_x = np.zeros_like(x)
    for aid, c in lca.dicts.activity.items():
        ref_x[S.col[aid]] = lca.supply_array[c]
    f = S.demand_vector({model["p2"]: 1.0})
    ours, theirs = np.abs(S.A @ x - f).max(), np.abs(S.A @ ref_x - f).max()
    assert ours <= max(theirs, 1e-12)
    assert np.allclose(x, ref_x, rtol=1e-4, atol=1e-9 * np.abs(ref_x).max())
    g = S.inventory(x)
    ref_g = np.zeros_like(g)
    inv = np.asarray(lca.inventory.sum(axis=1)).ravel()
    for fid, r in lca.dicts.biosphere.items():
        ref_g[S.bio_row[fid]] = inv[r]
    assert np.allclose(g, ref_g, rtol=1e-4, atol=1e-9 * np.abs(ref_g).max())


def test_contributions_add_up(model):
    S = models.system()
    c = analysis.contributions(S, model["p2"], 2.0, s.CLIMATE_METHOD, top=10_000)
    assert sum(x["value"] for x in c["by_activity"]) + c["by_activity_rest"] == pytest.approx(c["score"], rel=1e-9)
    assert sum(x["value"] for x in c["by_flow"]) + c["by_flow_rest"] == pytest.approx(c["score"], rel=1e-9)
    assert c["score"] == pytest.approx(S.score({model["p2"]: 2.0}, s.CLIMATE_METHOD), rel=1e-6)
    # own processes show up as contributors
    assert any(x["database"] == DB for x in c["by_activity"])


def test_process_detail_inputs_add_up(model):
    d = models.process_detail(model["p2"], s.CLIMATE_METHOD)
    parts = sum(x["contribution"] for x in d["technosphere"]) + sum(x["contribution"] for x in d["biosphere"])
    assert d["editable"] and parts == pytest.approx(d["score"], rel=1e-9)
    sub = next(x for x in d["technosphere"] if x["type"] == "substitution")
    assert sub["contribution"] < 0  # avoided concrete is a credit


def test_live_edit_and_undo(model):
    m = s.CLIMATE_METHOD
    before = models.system().score({model["p2"]: 1}, m)
    models.update_exchange(model["ex"]["p1_al"], amount=0.8)
    after = models.system().score({model["p2"]: 1}, m)
    assert after > before
    assert close(after, bw2calc_lca(model["p2"], 1, m))
    models.undo()
    assert models.system().score({model["p2"]: 1}, m) == pytest.approx(before, rel=1e-12)


def test_delete_and_restore_process(model):
    m = s.CLIMATE_METHOD
    with pytest.raises(ValueError):
        models.delete_process(model["p1"])  # still used by "Gerät"
    tmp = int(models.create_process(DB, "Wegwerf", "unit"))
    models.add_exchange(tmp, model["el"], 3.0)
    score = models.system().score({tmp: 1}, m)
    key = bd.get_node(id=tmp).key
    models.delete_process(tmp)
    assert tmp not in models.system().col
    models.undo()
    restored = bd.get_node(database=key[0], code=key[1]).id  # same key, new database id
    assert models.system().score({restored: 1}, m) == pytest.approx(score, rel=1e-12)
    models.undo()  # input
    assert models.system().score({restored: 1}, m) == pytest.approx(0, abs=1e-12)
    models.undo()  # process itself
    assert restored not in models.system().col


def test_copy_background_process_into_model(model):
    m = s.UBP_TOTAL_METHOD
    new = int(models.copy_process(model["al"], DB))
    S = models.system()
    assert S.col[new] >= S.nb  # it lives in the foreground now
    assert S.score({new: 1}, m) == pytest.approx(S.score({model["al"]: 1}, m), rel=1e-6)
    models.undo()
    assert new not in models.system().col


def test_background_is_read_only(model):
    d = models.process_detail(model["el"], s.CLIMATE_METHOD)
    assert not d["editable"]
    with pytest.raises(models.ReadOnlyError):
        models.update_exchange(d["technosphere"][0]["exchange"], amount=1.0)
    with pytest.raises(models.ReadOnlyError):
        models.add_exchange(model["el"], model["al"], 1.0)


def test_broken_model_is_reported_not_crashing(model):
    p = int(models.create_process(DB, "Kaputt", "unit"))
    prod = next(e for e in bd.get_node(id=p).production())
    models.update_exchange(prod._document.id, amount=0.0)
    S = models.system()
    assert S.fg.errors
    with pytest.raises(engine.ModelError):
        S.score({model["p2"]: 1}, s.CLIMATE_METHOD)
    models.undo()
    models.undo()
    assert not models.system().fg.errors


def test_tree_and_sankey(model):
    S = models.system()
    m = s.CLIMATE_METHOD
    total = S.score({model["p2"]: 2}, m)
    t = analysis.tree(S, model["p2"], 2, m, cutoff=0.01, depth=5)
    assert t["total"] == pytest.approx(total)
    assert t["nodes"][0]["share"] == pytest.approx(1.0)
    for n in t["nodes"][1:]:
        assert abs(n["share"]) >= 0.01 - 1e-12
    sk = analysis.sankey(S, model["p2"], 2, m, cutoff=0.01, max_nodes=30)
    root = next(n for n in sk["nodes"] if n["layer"] == 0)
    assert root["value"] == pytest.approx(total)
    keys = {n["key"] for n in sk["nodes"]}
    assert all(lk["source"] in keys and lk["target"] in keys for lk in sk["links"])
    # the loop between Gerät and Service is detected
    assert any(lk["loop"] for lk in sk["links"]) or len(sk["nodes"]) < 3
    # inflows of the product never exceed its total by more than the loop share
    inflow = sum(lk["value"] for lk in sk["links"] if lk["target"] == root["key"] and not lk["loop"])
    assert inflow <= abs(total) * 1.5


def test_score_table_and_verify(model):
    fus = [{"id": str(model["p2"]), "amount": 1}, {"id": str(model["el"]), "amount": 10}]
    r = setups.calculate(fus, METHODS)
    assert len(r["scores"]) == len(METHODS) and len(r["scores"][0]) == 2
    v = s.verify(fus, METHODS)
    assert v["ok"] and v["checked"] == 2 * len(METHODS)


def test_setup_round_trip_in_activity_browser_format(model):
    name = "zz Testrechnung"
    try:
        setups.save(name, [{"id": str(model["p2"]), "amount": 2.0}], [list(s.CLIMATE_METHOD)])
        raw = bd.calculation_setups[name]
        assert raw["inv"] == [{(DB, bd.get_node(id=model["p2"])["code"]): 2.0}]
        assert [tuple(m) for m in raw["ia"]] == [s.CLIMATE_METHOD]
        got = setups.get(name)
        assert got["fus"][0]["id"] == str(model["p2"]) and got["fus"][0]["amount"] == 2.0
        setups.save("zz Testrechnung 2", got["fus"], got["methods"], old_name=name)
        assert name not in bd.calculation_setups and "zz Testrechnung 2" in bd.calculation_setups
    finally:
        setups.delete(name)
        setups.delete("zz Testrechnung 2")


def test_example_model_and_single_undo():
    bd.projects.set_current(PROJECT)
    from lca_wrench import beispiel
    if not beispiel.available():
        pytest.skip("BAFU processes for the example are missing")
    r = beispiel.create()
    try:
        assert models.roles()[r["database"]] == "model"
        cs = setups.get(r["setup"])
        res = setups.calculate(cs["fus"], [tuple(m) for m in cs["methods"]])
        own, bafu_ebike, velo, auto = res["scores"][0]
        assert 0 < own < auto and 0 < bafu_ebike < auto  # an e-bike km is far below a car km
        assert models.journal()[0]["label"].startswith("Beispiel")
        models.undo()
        assert r["database"] not in bd.databases and r["setup"] not in bd.calculation_setups
        assert r["database"] not in models.model_databases()
    finally:
        if r["database"] in bd.databases:
            models.delete_database(r["database"])
        setups.delete(r["setup"])


def test_unit_scores_are_refined():
    """Regression: SuperLU alone was off by 7.5e-6 for this process; refinement makes it exact."""
    bd.projects.set_current(PROJECT)
    aid = bafu("Packing, lime products", "CH")
    m = (s.PROFILE_FAMILY, "Main air pollutants and PM")
    lca = bw2calc_lca(aid, 1.0, m)
    assert models.system().score({aid: 1.0}, m) == pytest.approx(lca.score, rel=1e-10)


def test_cached_background_keeps_no_file_open():
    """bw2calc keeps its matrix files (processed/*.zip) open while the LCA lives, and the engine caches it: closed once
    read, or the cache locks them on Windows, where an open file cannot be deleted (removing a background database,
    deleting a project)."""
    psutil = pytest.importorskip("psutil")
    bd.projects.set_current(PROJECT)
    S = models.system()
    S.score({bafu("Packing, lime products", "CH"): 1.0}, s.CLIMATE_METHOD)  # the matrices and a method read
    assert S.bg.lca is not None
    processed = os.path.normcase(str(bd.projects.dir / "processed"))
    assert not [f.path for f in psutil.Process().open_files() if os.path.normcase(f.path).startswith(processed)]


def test_fast_lu_matches_default_and_falls_back():
    """fast_lu solves like SuperLU's default, and falls back where pivot-free elimination breaks down."""
    import numpy as np
    from scipy import sparse
    from scipy.sparse.linalg import splu

    rng = np.random.default_rng(3)
    n = 400
    A = sparse.identity(n, format="lil")
    for j in range(n):
        for i in rng.integers(0, n, size=6):
            if i != j:
                A[i, j] = -rng.uniform(0.0, 0.1)
    A = A.tocsc()
    b = rng.normal(size=n)
    lu = engine.fast_lu(A)
    x, ref = engine.refined(lu.solve, A, b), engine.refined(splu(A).solve, A, b)
    assert np.abs(x - ref).max() <= 1e-12 * np.abs(ref).max()
    xt = engine.refined(lambda v: lu.solve(v, trans="T"), A.T.tocsr(), b)
    assert np.linalg.norm(A.T @ xt - b) <= 1e-12 * np.linalg.norm(b)
    # zero diagonal: no pivot-free elimination possible, the default factorization has to take over
    P = sparse.csc_matrix(np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.5, 0.2, 2.0]]))
    lu2 = engine.fast_lu(P)
    y = lu2.solve(np.array([1.0, 2.0, 3.0]))
    assert np.allclose(P @ y, [1.0, 2.0, 3.0], atol=1e-12)
