"""Completed factors for sub-compartments (completion.py) and the list of flows a method does not assess.

On the BAFU 2025 data: the Ecological Scarcity 2021 methods of the Brightway template carry most factors only on the
flow without sub-compartment, so emissions into 'high. pop.' or 'low. pop.' count as zero without the completion.
"""

import io

import bw2data as bd
import numpy as np
import openpyxl
import pytest
from fastapi.testclient import TestClient

from lca_wrench import analysis, completion, engine, models
from lca_wrench import service as s
from lca_wrench.api import app

BIO = "BAFU-2025-biosphere"
GW = (s.PROFILE_FAMILY, "Global warming")


@pytest.fixture
def switch():
    """The completion as the test sets it; afterwards off again, as for the other tests (conftest.py)."""
    yield completion.set_enabled
    completion.set_enabled(False)


@pytest.fixture(scope="module")
def electricity():
    return next(a for a in bd.Database("BAFU-2025-v2")
                if a["name"] == "Electricity, low voltage, at grid" and a.get("location") == "CH")


def _flow(name, *categories):
    return next(i for i, (n, cats, _u) in completion.flows(BIO).items() if n == name and cats == categories)


def test_climate_of_swiss_electricity_with_and_without(electricity, switch):
    """1 kWh low voltage electricity CH: 14.2 g CO2-eq with the method as stored, 97.1 g with completed factors."""
    switch(False)
    without = models.system_for(electricity.id).score({electricity.id: 1.0}, s.CLIMATE_METHOD)
    switch(True)
    with_ = models.system_for(electricity.id).score({electricity.id: 1.0}, s.CLIMATE_METHOD)
    assert without == pytest.approx(0.0142065, rel=1e-5)
    assert with_ == pytest.approx(0.0970550, rel=1e-5)


def test_only_missing_factors_are_completed(switch):
    cf = engine.method_cfs(GW)
    cand = completion.candidates(GW)
    flows = completion.flows(BIO)
    assert cand and not set(cand) & set(cf)  # never a flow the method has a factor for
    for i, (factor, src) in cand.items():
        name, cats, unit = flows[i]
        assert len(cats) > 1 and not completion.long_term(cats)
        assert flows[src] == (name, cats[:1], unit) and cf[src] == factor != 0
    # the special case stays: CO2 in the stratosphere has its own factor (3100 UBP, not 1000)
    strato = _flow("Carbon dioxide, fossil", "emissions to air", "stratosphere + troposphere")
    assert cf[strato] == 3100.0 and strato not in cand
    assert cand[_flow("Carbon dioxide, fossil", "emissions to air", "high. pop.")][0] == 1000.0
    # an explicit zero stays zero: heavy metals into groundwater are not assessed on purpose
    hm = (s.PROFILE_FAMILY, "Heavy metals into water")
    cd = _flow("Cadmium", "emissions to water", "groundwater")
    assert engine.method_cfs(hm)[cd] == 0.0 and cd not in completion.candidates(hm)
    assert _flow("Cadmium", "emissions to water", "river") in completion.candidates(hm)
    # long-term emissions are never completed
    assert not any(completion.long_term(flows[i][1]) for m in bd.methods for i in completion.candidates(m))
    # switched off: nothing is added, and the stored method is the same either way
    switch(False)
    assert completion.added(GW) == {} and completion.addition(GW, list(cand)) is None
    assert engine.method_cfs(GW) == cf


def test_total_stays_the_sum_of_its_categories(electricity, switch):
    fam = sorted(m for m in bd.methods if m[0] == s.PROFILE_FAMILY)
    for on in (False, True):
        switch(on)
        S = models.system_for(electricity.id)
        total = S.score({electricity.id: 1.0}, s.UBP_TOTAL_METHOD)
        assert total == pytest.approx(sum(S.score({electricity.id: 1.0}, m) for m in fam), rel=1e-9)


def test_cross_check_compares_like_with_like(electricity, switch):
    methods = [s.CLIMATE_METHOD, s.UBP_TOTAL_METHOD, GW]
    for on in (False, True):
        switch(on)
        v = s.verify([{"id": electricity.id, "amount": 1.0}], methods)
        assert v["ok"] and v["max_rel"] < 1e-8 and v["checked"] == 3


def test_flows_without_a_factor(electricity, switch):
    S = models.system_for(electricity.id)
    switch(False)
    rows = analysis.inventory(S, electricity.id, 1.0, s.CLIMATE_METHOD)
    summ = analysis.factor_summary(rows)
    assert summ["flows"] == len(rows) and summ["completed"] == 0 and 0 < summ["namesakes"] < summ["uncharacterized"]
    co2 = next(r for r in rows if r["name"] == "Carbon dioxide, fossil" and r["categories"].endswith("high. pop."))
    assert co2["status"] == "none" and co2["namesake"] == {"categories": "emissions to air", "factor": 1.0}
    assert co2["estimate"] == pytest.approx(co2["amount"])
    own = next(r for r in rows if r["name"] == "Carbon dioxide, fossil" and r["categories"] == "emissions to air")
    assert own["status"] == "own" and own["factor"] == 1.0
    # the estimate over the namesakes is what the completion then adds (long-term flows excepted)
    score0 = S.score({electricity.id: 1.0}, s.CLIMATE_METHOD)
    switch(True)
    S = models.system_for(electricity.id)
    rows = analysis.inventory(S, electricity.id, 1.0, s.CLIMATE_METHOD)
    done = analysis.factor_summary(rows)
    co2 = next(r for r in rows if r["name"] == "Carbon dioxide, fossil" and r["categories"].endswith("high. pop."))
    assert co2["status"] == "completed" and co2["factor"] == 1.0 and co2["source"] == "emissions to air"
    score1 = S.score({electricity.id: 1.0}, s.CLIMATE_METHOD)
    assert done["completed"] > 0 and done["completed_value"] == pytest.approx(score1 - score0, rel=1e-9)
    assert summ["estimate"] == pytest.approx(done["completed_value"] + done["estimate"], rel=1e-9)
    # a method without factors on a flow list: everything is "none", nothing breaks
    assert {r["status"] for r in analysis.inventory(S, electricity.id, 1.0, (s.PROFILE_FAMILY, "Noise"))} == {"none"}
    assert all("status" not in r for r in analysis.inventory(S, electricity.id, 1.0))


def test_api_switch_list_and_export(electricity, switch):
    body = {"id": str(electricity.id), "amount": 1.0, "method": list(s.CLIMATE_METHOD)}
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.post("/api/completion", json={"enabled": True}).json() == {"enabled": True}
        assert c.get("/api/state").json()["completion"] == {"enabled": True}
        on = c.post("/api/calc", json=body).json()
        assert on["factors"]["completion"] and on["factors"]["completed"] > 0 and on["factors"]["completable"] == 29
        assert c.post("/api/completion", json={"enabled": False}).json() == {"enabled": False}
        off = c.post("/api/calc", json=body).json()
        assert off["score"] == pytest.approx(0.0142065, rel=1e-5) and on["score"] == pytest.approx(0.0970550, rel=1e-5)
        assert off["factors"]["completed"] == 0 and off["factors"]["completable"] == 29
        assert off["factors"]["uncharacterized"] == on["factors"]["uncharacterized"] + on["factors"]["completed"]
        inv = c.post("/api/inventory", json=body).json()
        assert {r["status"] for r in inv} == {"own", "none"} and any("estimate" in r for r in inv)
        assert "status" not in c.post("/api/inventory", json={"id": body["id"], "amount": 1.0}).json()[0]
        table = c.post("/api/completion/factors", json={"method": body["method"]}).json()
        assert not table["enabled"] and len(table["rows"]) == 29
        assert {"name", "categories", "unit", "factor", "source"} <= set(table["rows"][0])
        assert c.post("/api/completion", json={"enabled": True}).json() == {"enabled": True}
        x = c.post("/api/export/result", json={**body, "families": None, "topic": None, "format": "xlsx"})
        assert x.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(x.content))
        ws = wb["Inventar"]
        head = [cell.value for cell in ws[1]]
        assert head[4:] == ["Charakterisiert", "Faktor", "Gleichnamiger Fluss mit Faktor", "Schätzung, falls gleich bewertet"]
        assert {"ja", "ja, ergänzt", "nein"} <= {row[4] for row in ws.iter_rows(min_row=2, values_only=True)}
        done = wb["Ergänzte Faktoren"]
        assert done.max_row - 1 == on["factors"]["completed"]
        assert np.isclose(sum(r[4] for r in done.iter_rows(min_row=2, values_only=True)), on["factors"]["completed_value"])


def test_a_family_that_specifies_its_sub_compartments_is_left_as_it_is():
    """A family that gives most sub-compartments of its substances a factor of its own has chosen which ones count, so
    a sub-compartment it leaves out stays out. The same factor on the flow without sub-compartment alone is completed."""
    co2 = {i: cats for i, (name, cats, _u) in completion.flows(BIO).items() if name == "Carbon dioxide, fossil"}
    top = next(i for i, c in co2.items() if c == ("emissions to air",))
    subs = sorted(i for i, c in co2.items() if len(c) > 1 and c[0] == "emissions to air" and not completion.long_term(c))
    assert len(subs) >= 3
    key = {i: bd.get_node(id=i).key for i in [top, *subs]}
    specified, sparse = ("test-specified", "Climate"), ("test-sparse", "Climate")  # one-method families
    bd.Method(specified).register(unit="kg CO2-eq")
    bd.Method(specified).write([(key[top], 1.0)] + [(key[i], 1.0) for i in subs[1:]])  # all but one sub-compartment
    bd.Method(sparse).register(unit="kg CO2-eq")
    bd.Method(sparse).write([(key[top], 1.0)])
    try:
        assert completion.sub_share(specified) == pytest.approx((len(subs) - 1) / len(subs))
        assert completion.sub_share(sparse) == 0
        assert not completion.needs_completion(specified) and completion.candidates(specified) == {}
        assert completion.needs_completion(sparse) and set(completion.candidates(sparse)) == set(subs)
        # the BAFU template's methods and the climate method derived from them keep their completed factors
        assert completion.needs_completion(GW) and completion.candidates(GW)
        assert completion.needs_completion(s.CLIMATE_METHOD) and completion.candidates(s.UBP_TOTAL_METHOD)
    finally:
        for m in (specified, sparse):
            bd.Method(m).deregister()
