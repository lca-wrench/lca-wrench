"""«Warum anders?»: the parts add up exactly to the difference between working copy and original."""

import bw2calc as bc
import bw2data as bd
import pytest

from conftest import TEST_PROJECT
from lca_wrench import registry, service as s


def bw2calc_score(project, node_id, amount, method):
    bd.projects.set_current(project)
    lca = bc.LCA({node_id: amount}, method)
    lca.lci()
    lca.lcia()
    return lca.score


@pytest.fixture()
def working_copy():
    bd.projects.set_current(TEST_PROJECT)
    name = s.make_working_copy()
    yield name
    bd.projects.set_current(TEST_PROJECT)
    s.remove_project(name)
    reg = registry.load()
    reg["copies"].pop(name, None)
    registry.save(reg)
    s.acknowledge()


def test_parts_add_up_to_difference(working_copy):
    method = s.CLIMATE_METHOD
    aid = int(s.examples()[0]["id"])
    a = s.activity(str(aid), method)
    tech = a["technosphere"]
    bio = a["biosphere"]
    assert len(tech) >= 2 and bio
    # two input changes and one emission change, all in the supply chain of the product
    s.edit_exchange(tech[0]["exchange"], tech[0]["amount"] * 0.5)
    s.edit_exchange(tech[1]["exchange"], tech[1]["amount"] * 1.7)
    s.edit_exchange(bio[0]["exchange"], bio[0]["amount"] * 3.0)

    r = s.explain_difference(str(aid), 2.0, method)
    h0 = bw2calc_score(TEST_PROJECT, aid, 2.0, method)
    h1 = bw2calc_score(working_copy, aid, 2.0, method)
    bd.projects.set_current(working_copy)
    assert r["score_original"] == pytest.approx(h0, rel=1e-9) and r["score_copy"] == pytest.approx(h1, rel=1e-9)
    assert r["difference"] == pytest.approx(h1 - h0, rel=1e-9)
    assert len(r["parts"]) == 3 and all(p["contribution"] is not None for p in r["parts"])
    assert sum(p["contribution"] for p in r["parts"]) == pytest.approx(h1 - h0, rel=1e-9, abs=1e-12 * abs(h0))
    assert abs(r["rest"]) <= 1e-9 * abs(h0)
    assert [abs(p["contribution"]) for p in r["parts"]] == sorted((abs(p["contribution"]) for p in r["parts"]), reverse=True)
    assert bd.projects.current == working_copy  # the project is restored after the look at the original
    assert {p["kind"] for p in r["parts"]} == {"input", "emission"}


def test_single_change_equals_difference(working_copy):
    method = s.CLIMATE_METHOD
    aid = int(s.examples()[1]["id"])
    top = s.activity(str(aid), method)["technosphere"][0]
    s.edit_exchange(top["exchange"], top["amount"] * 2.0)
    r = s.explain_difference(str(aid), 1.0, method)
    assert len(r["parts"]) == 1
    assert r["parts"][0]["contribution"] == pytest.approx(r["difference"], rel=1e-9)
    assert r["parts"][0]["share"] == pytest.approx(1.0, rel=1e-9)


def test_only_in_working_copy():
    bd.projects.set_current(TEST_PROJECT)
    with pytest.raises(ValueError):
        s.explain_difference(s.examples()[0]["id"], 1.0, s.CLIMATE_METHOD)
