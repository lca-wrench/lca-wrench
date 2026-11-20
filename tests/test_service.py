"""Reference tests: every number the app shows must match plain Brightway.

Needs the BAFU project from setup_daten.py; skipped otherwise.
"""

import random

import bw2calc as bc
import bw2data as bd
import numpy as np
import pytest

from conftest import TEST_PROJECT
from lca_wrench import registry, service as s

PROJECT = TEST_PROJECT

METHODS = [s.CLIMATE_METHOD, s.UBP_TOTAL_METHOD, (s.PROFILE_FAMILY, "Main air pollutants and PM")]


@pytest.fixture(autouse=True)
def project():
    bd.projects.set_current(PROJECT)
    yield
    bd.projects.set_current(PROJECT)


def sample_activities(n=20, seed=42):
    db = bd.Database("BAFU-2025-v2")
    ids = sorted(a.id for a in db)  # SQLite row order is not stable across writes
    random.Random(seed).shuffle(ids)
    return ids[:n]


@pytest.mark.parametrize("method", METHODS)
def test_unit_scores_match_bw2calc(method):
    for aid in sample_activities():
        lca = bc.LCA({bd.get_node(id=aid): 1}, method)
        lca.lci()
        lca.lcia()
        assert s.unit_score(aid, method) == pytest.approx(lca.score, rel=1e-9, abs=1e-12), aid


def test_calculate_matches_bw2calc_and_contributions_add_up():
    aid = s.examples()[0]["id"]
    r = s.calculate(aid, 2.5, s.CLIMATE_METHOD, top=10_000)
    lca = bc.LCA({bd.get_node(id=int(aid)): 2.5}, s.CLIMATE_METHOD)
    lca.lci()
    lca.lcia()
    assert r["score"] == pytest.approx(lca.score, rel=1e-6)
    assert sum(x["value"] for x in r["by_activity"]) + r["by_activity_rest"] == pytest.approx(r["score"], rel=1e-9)
    assert sum(x["value"] for x in r["by_flow"]) + r["by_flow_rest"] == pytest.approx(r["score"], rel=1e-9)
    assert len(r["profile"]) == 21


def test_ubp_total_is_sum_of_profile():
    aid = s.examples()[1]["id"]
    total = s.calculate(aid, 1, s.UBP_TOTAL_METHOD)
    assert sum(p["value"] for p in total["profile"]) == pytest.approx(total["score"], rel=1e-9)


def test_climate_method_factors():
    cfs = {}
    for key, cf in bd.Method(s.CLIMATE_METHOD).load():
        node = bd.get_node(id=key)
        cfs[(node["name"], tuple(node["categories"]))] = cf
    assert cfs[("Carbon dioxide, fossil", ("emissions to air",))] == 1.0
    assert cfs[("Methane, fossil", ("emissions to air",))] == 30.0
    assert cfs[("Dinitrogen monoxide", ("emissions to air",))] == 270.0


@pytest.mark.parametrize("method", METHODS[:2])
def test_activity_inputs_add_up(method):
    for aid in sample_activities(8, seed=7):
        a = s.activity(aid, method)
        parts = sum(x["contribution"] for x in a["technosphere"]) + a["direct"]
        assert parts == pytest.approx(a["score"], rel=1e-4, abs=1e-9), a["name"]


def test_graph_shares():
    aid = s.examples()[0]["id"]
    g = s.graph(aid, 3, s.CLIMATE_METHOD, cutoff=0.005, depth=5)
    root = g["nodes"][0]
    assert root["share"] == pytest.approx(1.0)
    assert g["total"] == pytest.approx(3 * s.unit_score(aid, s.CLIMATE_METHOD))
    for n in g["nodes"][1:]:
        assert abs(n["share"]) >= 0.005 - 1e-12
        assert n["depth"] == g["nodes"][n["parent"]]["depth"] + 1


def test_original_is_read_only():
    a = s.activity(s.examples()[0]["id"], s.CLIMATE_METHOD)
    with pytest.raises(s.ReadOnlyError):
        s.edit_exchange(a["technosphere"][0]["exchange"], 0.5)


def test_working_copy_edit_undo_and_compare():
    aid = s.examples()[0]["id"]
    before = s.unit_score(aid, s.CLIMATE_METHOD)
    name = s.make_working_copy()
    try:
        assert bd.projects.current == name and s.is_working_copy()
        a = s.activity(aid, s.CLIMATE_METHOD)
        top = a["technosphere"][0]
        s.edit_exchange(top["exchange"], top["amount"] * 0.5)

        lca = bc.LCA({bd.get_node(id=int(aid)): 1}, s.CLIMATE_METHOD)
        lca.lci()
        lca.lcia()
        after = s.unit_score(aid, s.CLIMATE_METHOD)
        assert after == pytest.approx(lca.score, rel=1e-6)
        assert after < before

        cmp = s.compare([{"project": PROJECT, "id": aid, "amount": 1}, {"project": name, "id": aid, "amount": 1}],
                        s.CLIMATE_METHOD)
        assert bd.projects.current == name
        assert cmp[0]["score"] == pytest.approx(before) and cmp[1]["score"] == pytest.approx(after)

        s.undo_change(top["exchange"])
        assert s.unit_score(aid, s.CLIMATE_METHOD) == pytest.approx(before, rel=1e-9)
        assert s.state()["changes"] == []
    finally:
        bd.projects.set_current(PROJECT)
        s.remove_project(name)
        reg = registry.load()
        reg["copies"].pop(name, None)
        registry.save(reg)
    assert np.isclose(s.unit_score(aid, s.CLIMATE_METHOD), before)


def test_test_projects_hidden_and_source_protected():
    assert PROJECT in bd.projects
    names = [p["name"] for p in s.state()["projects"]]
    # the open project is always listed, so that the project selector shows the truth; other test projects never
    assert names.count(PROJECT) == 1
    assert all(n == PROJECT or not n.startswith(s.TEST_PROJECT_PREFIX) for n in names)
    with pytest.raises(RuntimeError):
        bd.projects.set_current("bafu-2025")
    assert bd.projects.current == PROJECT


def test_removing_a_copy_closes_its_files_and_frees_the_name():
    """Windows cannot delete open files (WinError 32): a copy the engine has calculated in keeps its processed
    datapackages open until engine.forget. remove_project closes them and leaves no folder; a folder left over by
    an earlier failed deletion does not block the next copy."""
    from bw2data.project import ProjectDataset

    from lca_wrench import engine

    aid = s.examples()[0]["id"]
    name = s.make_working_copy()
    try:
        s.unit_score(aid, s.CLIMATE_METHOD)  # builds and caches the copy's background
        bgs = [bg for (p, _v, _d), bg in engine._backgrounds.items() if p == name]
        assert bgs and bgs[0].lca.packages
        zips = [dp.fs.zip for dp in bgs[0].lca.packages if hasattr(getattr(dp, "fs", None), "zip")]
        assert zips and all(z.fp is not None for z in zips)
        folder = bd.projects._project_dir(ProjectDataset.get(ProjectDataset.name == name))
        bd.projects.set_current(PROJECT)
        s.remove_project(name)
        assert all(z.fp is None for z in zips)  # closed
        assert not any(p == name for (p, _v, _d) in engine._backgrounds)
        assert name not in bd.projects and not folder.exists()

        folder.mkdir(parents=True)  # what a failed deletion left behind
        try:
            again = s.make_working_copy()
            assert again != name and bd.projects.current == again
            bd.projects.set_current(PROJECT)
            s.remove_project(again)
        finally:
            s.remove_folder(folder)
    finally:
        bd.projects.set_current(PROJECT)
        if name in bd.projects:
            s.remove_project(name)
        reg = registry.load()
        for n in [n for n in reg["copies"] if n.startswith(name)]:
            reg["copies"].pop(n, None)
        registry.save(reg)
