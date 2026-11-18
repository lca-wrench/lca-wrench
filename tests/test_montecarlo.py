"""Monte-Carlo: every number is checked against a plain bw2calc loop with the same seeds (mc.mc_lca)."""

import time

import bw2data as bd
import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import beispiel, montecarlo as mc
from lca_wrench.api import app

N = 8
SEED = 5


@pytest.fixture(scope="module")
def setup():
    bd.projects.set_current(TEST_PROJECT)
    # the same two datasets as always, in Brightway's own search order (the app's search ranks differently)
    hits = bd.Database("BAFU-2025-v2").search("electricity low voltage", limit=400)
    ids = [a.id for a in hits if a["location"] == "CH" and a["unit"] == "kilowatt hour"][:2]
    methods = [m for m in sorted(bd.methods) if m[0] == "Werkbank"]
    assert len(ids) == 2 and len(methods) >= 2
    return ids, methods


def bw2calc_scores(node_id, amount, method, n, seed):
    lca = mc.mc_lca({bd.get_node(id=node_id): amount}, method, seed)
    out = [lca.score]
    for _ in range(n - 1):
        next(lca)
        out.append(lca.score)
    return np.array(out)


@pytest.fixture(scope="module")
def draws(setup):
    ids, methods = setup
    fus = [(ids[0], 1.0), (ids[1], 2.0), (ids[0], 2.0)]
    return mc.run_chunk(TEST_PROJECT, fus, methods[:2], N, SEED)


def test_matches_bw2calc_same_seed(setup, draws):
    ids, methods = setup
    ref = bw2calc_scores(ids[0], 1.0, methods[0], N, SEED)
    assert draws.shape == (N, 3, 2)
    assert np.allclose(draws[:, 0, 0], ref, rtol=1e-8)
    assert len(set(np.round(ref, 6))) == N  # the draws really differ (BAFU has uncertainty data)
    ref2 = bw2calc_scores(ids[1], 2.0, methods[0], N, SEED)
    assert np.allclose(draws[:, 1, 0], ref2, rtol=1e-8)


def test_draws_are_coupled(draws):
    # same product with double amount: exactly double in every single draw, for every method
    assert np.allclose(draws[:, 2, :], 2 * draws[:, 0, :], rtol=1e-10)


def test_reproducible_and_chunks(setup):
    ids, methods = setup
    fus = [(ids[0], 1.0)]
    a = mc.simulate(TEST_PROJECT, fus, methods[:1], 6, SEED, workers=2, progress=mp_array(2))
    b = np.concatenate([mc.run_chunk(TEST_PROJECT, fus, methods[:1], 3, SEED),
                        mc.run_chunk(TEST_PROJECT, fus, methods[:1], 3, SEED + 1)])
    assert np.allclose(a, b, rtol=1e-12)
    assert mc.split(7, 3) == [3, 2, 2] and mc.split(2, 8) == [1, 1]


def test_single_worker_runs_in_own_process(setup, monkeypatch):
    """run_chunk switches the Brightway project; in a thread of the server that would disturb running requests."""
    ids, methods = setup
    fus = [(ids[0], 1.0)]
    ref = mc.run_chunk(TEST_PROJECT, fus, methods[:1], 3, SEED)
    monkeypatch.setattr(mc, "run_chunk", lambda *a, **k: pytest.fail("ran in the server process"))
    a = mc.simulate(TEST_PROJECT, fus, methods[:1], 3, SEED, workers=1, progress=mp_array(1))
    assert np.allclose(a, ref, rtol=1e-12)


def mp_array(n):
    import multiprocessing as multiproc

    return multiproc.get_context("spawn").Array("i", [0] * n, lock=False)


def test_statistics_and_better_matrix():
    rng = np.random.default_rng(1)
    d = rng.lognormal(0, 0.5, size=(400, 3, 2))
    st = mc.summarize(d)
    assert np.allclose(st["median"], np.median(d, axis=0).T)
    assert np.allclose(st["p5"], np.percentile(d, 5, axis=0).T)
    assert np.allclose(st["p95"], np.percentile(d, 95, axis=0).T)
    assert np.allclose(st["mean"], d.mean(axis=0).T)
    assert np.allclose(st["std"], d.std(axis=0, ddof=1).T)
    b = mc.better_matrix(d)
    for k in range(2):
        for i in range(3):
            assert b[k][i][i] is None
            for j in range(3):
                if i != j:
                    assert b[k][i][j] == pytest.approx((d[:, i, k] < d[:, j, k]).mean())
                    assert b[k][i][j] + b[k][j][i] == pytest.approx(1.0)
    # ties count half
    t = np.ones((4, 2, 1))
    assert mc.better_matrix(t)[0][0][1] == 0.5


def test_job_via_api_and_reference_in_range(setup):
    ids, methods = setup
    body = {"fus": [{"id": str(ids[0]), "amount": 1}, {"id": str(ids[1]), "amount": 1}],
            "methods": [list(m) for m in methods[:2]], "n": 40, "seed": 3, "workers": 2}
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        st = c.post("/api/mc/start", json=body).json()
        assert st["state"] == "läuft" and st["n"] == 40
        for _ in range(300):
            st = c.get("/api/mc/status", params={"id": st["id"]}).json()
            if st["state"] != "läuft":
                break
            time.sleep(1)
        assert st["state"] == "fertig", st
        r = st["result"]
        assert st["done"] == 40 and r["n"] == 40 and r["workers"] == 2
        assert len(r["median"]) == 2 and len(r["median"][0]) == 2 and len(r["better"]) == 2
        assert len(r["draws"][0][0]) == 40
        for k in range(2):
            for j in range(2):
                assert r["p5"][k][j] <= r["median"][k][j] <= r["p95"][k][j]
                assert r["min"][k][j] <= r["p5"][k][j] and r["p95"][k][j] <= r["max"][k][j]
                # the deterministic score (engine) lies inside the spread of the draws
                assert r["p5"][k][j] <= r["reference"][k][j] <= r["p95"][k][j]
        assert c.get("/api/mc/status", params={"id": "gibtsnicht"}).status_code == 404
        assert c.post("/api/mc/start", json={**body, "n": 0}).status_code == 422


def test_own_model_in_draws():
    """Products of an own model database are part of the same draws (reference: bw2calc)."""
    bd.projects.set_current(TEST_PROJECT)
    r = beispiel.create()
    try:
        fahrt = int(r["process"])
        methods = [m for m in sorted(bd.methods) if m[0] == "Werkbank"][:1]
        d = mc.run_chunk(TEST_PROJECT, [(fahrt, 1.0)], methods, 5, SEED)
        ref = bw2calc_scores(fahrt, 1.0, methods[0], 5, SEED)
        assert np.allclose(d[:, 0, 0], ref, rtol=1e-8)
        assert len(set(np.round(ref, 9))) > 1
    finally:
        from lca_wrench import models

        models.delete_database(r["database"])


def test_separate_databases_draw_independently():
    """Regression: with one seed for every resource group, two alternatives in separate databases got identical
    draws (correlation 1, P(better) = 0.5 from ties). Each group must get its own variates."""
    bd.projects.set_current(TEST_PROJECT)
    bio = ("BAFU-2025-biosphere", next(iter(bd.Database("BAFU-2025-biosphere"))).key[1])
    names = ["mc-indep-1", "mc-indep-2"]
    try:
        for db in names:
            bd.Database(db).write({(db, "p"): {"name": db, "type": "process", "unit": "kg", "exchanges": [
                {"input": (db, "p"), "amount": 1, "type": "production"},
                {"input": bio, "amount": 1.0, "type": "biosphere", "uncertainty type": 2, "loc": 0.0,
                 "scale": 0.5}]}})
        bd.Method(("mc-indep",)).write([(bio, 1.0)])
        fus = [(bd.get_node(database=db, code="p").id, 1.0) for db in names]
        d = mc.run_chunk(TEST_PROJECT, fus, [("mc-indep",)], 200, SEED)
        a, b = d[:, 0, 0], d[:, 1, 0]
        assert abs(np.corrcoef(a, b)[0, 1]) < 0.3
        assert np.abs(a - b).max() > 0.1
        assert np.allclose(d, mc.run_chunk(TEST_PROJECT, fus, [("mc-indep",)], 200, SEED))  # still reproducible
    finally:
        for db in names:
            if db in bd.databases:
                del bd.databases[db]
        if ("mc-indep",) in bd.methods:
            bd.Method(("mc-indep",)).deregister()


# ---------- sensitivity ----------

@pytest.fixture(scope="module")
def sens_pilot(setup):
    ids, methods = setup
    fu = (ids[0], 1.0)
    stats, meta = mc._sens_pilot_chunk(TEST_PROJECT, fu, methods[0], 3, SEED)
    return fu, methods[0], stats, meta


def reference_lca(fu, method, seed):
    return mc.mc_lca({fu[0]: fu[1]}, method, seed)


def test_sensitivity_formulas_by_finite_difference(sens_pilot):
    """dh/dA_ij = -s_i x_j and dh/dB_kj = c_k x_j, checked by perturbing the first draw and solving again."""
    from scipy.sparse.linalg import spsolve

    fu, method, stats, meta = sens_pilot
    lca = reference_lca(fu, method, SEED)  # same first draw as the pilot
    A, B = lca.technosphere_matrix.tocsr(), lca.biosphere_matrix.tocsr()
    c = lca.characterization_matrix.diagonal()
    b = lca.demand_array

    def score(A_, B_):
        return float(c @ (B_ @ spsolve(A_.tocsc(), b)))

    base = score(A, B)
    assert base == pytest.approx(float(c @ (B @ meta["x"])), rel=1e-8)
    merged = mc._merge([stats])
    cands = mc.rank_candidates(meta, merged, 6)
    assert len(cands) >= 2
    for kind, idx, _ in cands:
        if kind == "A":
            i, j = int(meta["Arow"][idx]), int(meta["Acol"][idx])
            Mp, Mm = A.tolil(), A.tolil()
            eps = 1e-3 * max(abs(Mp[i, j]), 1e-12)
            Mp[i, j] += eps
            Mm[i, j] -= eps
            fd = (score(Mp.tocsr(), B) - score(Mm.tocsr(), B)) / (2 * eps)
            assert fd == pytest.approx(-meta["s"][i] * meta["x"][j], rel=2e-3, abs=1e-12)
        else:
            k, j = int(meta["Brow"][idx]), int(meta["Bcol"][idx])
            Mp, Mm = B.tolil(), B.tolil()
            eps = 1e-3 * max(abs(Mp[k, j]), 1e-12)
            Mp[k, j] += eps
            Mm[k, j] -= eps
            fd = (score(A, Mp.tocsr()) - score(A, Mm.tocsr())) / (2 * eps)
            assert fd == pytest.approx(meta["c"][k] * meta["x"][j], rel=2e-3, abs=1e-12)


def test_tracked_samples_match_bw2calc(sens_pilot):
    fu, method, stats, meta = sens_pilot
    cands = mc.rank_candidates(meta, mc._merge([stats]), 6)
    a_idx = np.array([i for m, i, _ in cands if m == "A"], dtype=int)
    b_idx = np.array([i for m, i, _ in cands if m == "B"], dtype=int)
    n = 5
    scores, xa, xb, _fab = mc._sens_main_chunk(TEST_PROJECT, fu, method, n, SEED, a_idx, b_idx)
    lca = reference_lca(fu, method, SEED)
    for it in range(n):
        if it:
            next(lca)
        assert scores[it] == pytest.approx(lca.score, rel=1e-8)
        A, B = lca.technosphere_matrix.tocsr(), lca.biosphere_matrix.tocsr()
        for col, i in enumerate(a_idx):
            assert xa[it, col] == pytest.approx(A[int(meta["Arow"][i]), int(meta["Acol"][i])], rel=1e-12)
        for col, i in enumerate(b_idx):
            assert xb[it, col] == pytest.approx(B[int(meta["Brow"][i]), int(meta["Bcol"][i])], rel=1e-12)


def test_sobol_pick_freeze_by_rank_one_update_is_exact(sens_pilot):
    """The score with all values of draw a but one entry from draw b, by Sherman-Morrison, equals solving again."""
    from scipy.sparse.linalg import spsolve

    fu, method, stats, meta = sens_pilot
    cands = mc.rank_candidates(meta, mc._merge([stats]), 8)
    sobol = [(m, i) for m, i, _ in cands]
    assert {m for m, _ in sobol} == {"A", "B"} or len(sobol) >= 2
    _s, _xa, _xb, fab = mc._sens_main_chunk(TEST_PROJECT, fu, method, 4, SEED, np.array([], int), np.array([], int), sobol)
    lca = reference_lca(fu, method, SEED)
    draws = []
    for it in range(4):
        if it:
            next(lca)
        draws.append((lca.technosphere_matrix.tocsr().copy(), lca.biosphere_matrix.tocsr().copy(),
                      lca.characterization_matrix.diagonal().copy()))
    for p in range(2):
        (Aa, Ba, ca), (Ab, Bb, _cb) = draws[2 * p], draws[2 * p + 1]
        for k, (kind, idx) in enumerate(sobol):
            A2, B2 = Aa.copy(), Ba.copy()
            if kind == "A":
                A2.data[idx] = Ab.data[idx]
            else:
                B2.data[idx] = Bb.data[idx]
            want = float(ca @ (B2 @ spsolve(A2.tocsc(), lca.demand_array)))
            assert fab[p, k] == pytest.approx(want, rel=1e-7, abs=1e-14)


def test_sobol_estimators_on_known_function():
    """y = 1000 + x1 + 2 x2 + x1 x3 with independent standard normals: S1 = 1/6, 4/6, 0; ST = 2/6, 4/6, 1/6."""
    rng = np.random.default_rng(5)
    m = 20000
    f = lambda x: 1000 + x[:, 0] + 2 * x[:, 1] + x[:, 0] * x[:, 2]  # large mean, as LCA scores have
    a, b = rng.normal(size=(m, 3)), rng.normal(size=(m, 3))
    fab = np.column_stack([f(np.where(np.arange(3) == i, b, a)) for i in range(3)])
    r = mc.sobol_indices(f(a), f(b), fab, n_boot=50)
    assert np.allclose(r["s1"], [1 / 6, 4 / 6, 0], atol=0.03)
    assert np.allclose(r["st"], [2 / 6, 4 / 6, 1 / 6], atol=0.03)
    assert np.all(r["s1_lo"] <= r["s1"]) and np.all(r["st"] <= r["st_hi"])


def test_spearman_and_merge_against_scipy_numpy():
    from scipy.stats import spearmanr

    rng = np.random.default_rng(2)
    y = rng.normal(size=60)
    x = np.column_stack([y + rng.normal(size=60), -y ** 3 + rng.normal(size=60), rng.normal(size=60), np.round(y)])
    ref = [spearmanr(x[:, k], y).statistic for k in range(4)]
    assert np.allclose(mc.spearman(x, y), ref, atol=1e-12)
    # chunked mean/spread equals the plain statistics
    data = rng.normal(size=(30, 5))
    parts = []
    for rows in (data[:7], data[7:19], data[19:]):
        m = rows.mean(axis=0)
        parts.append({"n": len(rows), "mA": m, "m2A": ((rows - m) ** 2).sum(axis=0), "mB": m, "m2B": ((rows - m) ** 2).sum(axis=0)})
    mean, sd = mc._merge(parts)["A"]
    assert np.allclose(mean, data.mean(axis=0)) and np.allclose(sd, data.std(axis=0, ddof=1))


def test_sensitivity_job_via_api(setup):
    ids, methods = setup
    body = {"id": str(ids[0]), "amount": 1, "method": list(methods[0]), "n": 60, "seed": 4, "workers": 2}
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        st = c.post("/api/mc/sensitivity", json=body).json()
        assert st["state"] == "läuft" and "Schritt" in st["phase"]
        for _ in range(300):
            st = c.get("/api/mc/status", params={"id": st["id"]}).json()
            if st["state"] != "läuft":
                break
            time.sleep(1)
        assert st["state"] == "fertig", st
        r = st["result"]
        es = r["entries"]
        assert 1 <= len([e for e in es if not e.get("extra")]) <= 10 and len(es) <= 15 and r["n"] == 60 and r["candidates"] >= len(es)
        by_rho = [abs(e["rho"]) for e in es if not e.get("extra")]
        assert by_rho == sorted(by_rho, reverse=True)
        assert all(-1 <= e["rho"] <= 1 and 0 <= e["share"] <= 1 and e["rel_sd"] > 0 for e in es)
        assert all(0 <= e["ctv"] <= 1 for e in es) and r["linear_share"] > 0
        assert r["sobol"]["pairs"] == 30 and any("sobol" in e for e in es)
        assert all(e["sobol"]["st_lo"] <= e["sobol"]["st_hi"] for e in es if "sobol" in e)
        assert all(e["supplier"]["name"] != "?" and e["consumer"]["name"] != "?" for e in es)
        assert r["score"]["p5"] <= r["score"]["median"] <= r["score"]["p95"]
        assert c.post("/api/mc/sensitivity", json={**body, "n": 5}).status_code == 422
