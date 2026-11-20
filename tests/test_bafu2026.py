"""BAFU:2026 with EF 3.1 imported with sentier-brightway (lca_wrench/bafu2026.py).

The import runs once into its own project `lca-wrench-test-bafu2026` (needs internet on the first run, about 36 MB, then
the sentier-brightway cache; about a minute) and is deleted afterwards. Checked: the three databases and 25 methods,
roles in LCA Wrench, unit scores of LCA Wrench's engine against plain bw2calc, an existing install is never
written to, a failed import job leaves nothing behind, the API.
"""

import time

import bw2calc as bc
import bw2data as bd
import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.sparse.linalg import splu

from conftest import TEST_PROJECT

from lca_wrench import bafu2026, engine, imports
from lca_wrench import service as s
from lca_wrench.api import app

pytest.importorskip("sentier_brightway")

PROJECT = "lca-wrench-test-bafu2026"
CLIMATE = ("sentier", "EF v3.1", "Climate change")


def _drop(name):
    if name in bd.projects:
        if bd.projects.current == name:
            bd.projects.set_current(TEST_PROJECT)
        s.remove_project(name)


@pytest.fixture(scope="module")
def imported():
    _drop(PROJECT)
    bd.projects.set_current(TEST_PROJECT)
    info = bafu2026.install(PROJECT)
    yield info
    _drop(PROJECT)
    bd.projects.set_current(TEST_PROJECT)


def test_databases_methods_and_roles(imported):
    assert imported["processes"] == 11947 and imported["methods"] == 25
    assert imported["flows_mapped"] / imported["flows_used"] > 0.95
    assert "BAFU:2026" in imported["citation"]
    s.set_project(PROJECT)
    assert set(bd.databases) == {"bafu-2026", "ef-3.1-biosphere", "bafu-2026-residual"}
    assert engine.database_roles() == {"bafu-2026": "background", "ef-3.1-biosphere": "biosphere",
                                       "bafu-2026-residual": "biosphere"}
    assert len([m for m in bd.methods if m[:2] == ("sentier", "EF v3.1")]) == 25
    assert s.default_method(sorted(bd.methods)) == list(CLIMATE)


def test_engine_matches_bw2calc(imported):
    s.set_project(PROJECT)
    acts = [a for a in bd.Database("bafu-2026") if a["location"] == "CH" and "electricity, low voltage" in a["name"].lower()][:3]
    acts += [a for a in bd.Database("bafu-2026") if "heat" in a["name"].lower()][:3]
    assert len(acts) >= 4
    for m in (CLIMATE, ("sentier", "EF v3.1", "Acidification")):
        for a in acts:
            lca = bc.LCA({a: 1.0}, m)
            lca.lci()
            lca.lcia()
            ours = s.unit_score(a.id, m)
            # bw2calc solves once (scipy's SuperLU here; no pypardiso or scikit-umfpack in the lock file) and
            # without iterative refinement; the result of one solve differs slightly between platforms and BLAS builds. This matrix is ill-conditioned, so its supply vector is only good to
            # about 1e-8 (seen: 1.2e-8 on Linux x86-64 in CI; below 1e-8 on macOS arm64). Its own solution, refined until the
            # residual is gone, is the reference; the plain score has to agree within what one solve can give.
            exact = _refined_score(lca)
            assert abs(ours - exact) <= 1e-9 * max(abs(exact), 1e-12), (a["name"], m, ours, exact)
            assert abs(ours - lca.score) <= 1e-6 * max(abs(lca.score), 1e-12), (a["name"], m, ours, lca.score)


def _refined_score(lca) -> float:
    """bw2calc's score with its supply vector refined: x += A^-1 (b - A x) until the residual stays."""
    A = lca.technosphere_matrix.tocsc()
    b = np.asarray(lca.demand_array, dtype=float)
    x = np.asarray(lca.supply_array, dtype=float).copy()
    lu = splu(A)
    for _ in range(3):
        x = x + lu.solve(b - A @ x)
    # backward error per row: each residual entry relative to the size of its row, (|A| |x|)_i, or to the demand,
    # whichever is larger. The matrix has entries up to about 1e10, so measured against |b| = 1 alone the residual
    # stays around 1e-11 on some platforms although x is as exact as double precision allows.
    r = np.abs(b - A @ x)
    scale = abs(A) @ np.abs(x) + np.abs(b).max()
    assert np.max(r / scale) <= 1e-13
    return float((lca.characterization_matrix @ (lca.biosphere_matrix @ x)).sum())


def test_existing_project_is_never_written(imported):
    s.set_project(PROJECT)
    before = {n: len(bd.Database(n)) for n in bd.databases}
    with pytest.raises(ValueError, match="schon Daten"):
        bafu2026.install(PROJECT)
    assert {n: len(bd.Database(n)) for n in bd.databases} == before


def test_failed_import_leaves_nothing(monkeypatch):
    import sentier_brightway as sb

    name = PROJECT + "-kaputt"
    _drop(name)
    s.set_project(TEST_PROJECT)

    def half(project, *a, **k):
        bd.projects.set_current(project)
        bd.Database("ef-3.1-biosphere").write({("ef-3.1-biosphere", "x"): {"name": "x", "type": "emission"}})
        raise RuntimeError("abgebrochen")

    monkeypatch.setattr(sb, "import_db", half)
    job = imports.start(name, "bafu2026", {})
    while imports.JOBS[job["id"]].state == "läuft":
        time.sleep(0.2)
    job = imports.status(job["id"])
    assert job["state"] == "fehler" and "abgebrochen" in job["error"]
    assert name not in bd.projects
    assert bd.projects.current == TEST_PROJECT == s.OPEN["project"]


def test_api_offers_and_refuses(imported, monkeypatch):
    c = TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"})
    bd.projects.set_current(TEST_PROJECT)
    assert c.get("/api/state").json()["bafu2026_import"] is (bafu2026.PROJECT not in bd.projects)
    assert c.get("/api/import/options").json()["bafu2026"] is True
    r = c.post("/api/import/start", json={"name": PROJECT, "source": "bafu2026"})  # has data: refused, nothing written
    assert r.status_code == 400 and "schon Daten" in r.json()["detail"]
    monkeypatch.setattr(bafu2026, "PROJECT", PROJECT)
    assert c.get("/api/state").json()["bafu2026_import"] is False
