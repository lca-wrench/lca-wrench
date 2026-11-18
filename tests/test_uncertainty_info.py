"""The data sheet shows each input's uncertainty (95 % range, distribution) and the dataset's description; own models
can set a distribution per input, which moves along when the amount changes and can be undone."""

import math

import bw2data as bd
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import models, service as s
from lca_wrench.api import app

DB = "Test Uncertainty"


def test_ranges_of_the_distributions():
    u = models.uncertainty({"amount": 2.0, "uncertainty type": 2, "loc": math.log(2.0), "scale": 0.2,
                            "pedigree": {"reliability": 2, "completeness": 3}})
    assert u["name"] == "lognormal" and u["gsd2"] == pytest.approx(math.exp(0.4))
    assert u["lo"] == pytest.approx(2 * math.exp(-1.959964 * 0.2), rel=1e-5)
    assert u["hi"] == pytest.approx(2 * math.exp(1.959964 * 0.2), rel=1e-5)
    assert u["pedigree"] == {"reliability": 2, "completeness": 3}
    neg = models.uncertainty({"amount": -2.0, "uncertainty type": 2, "loc": math.log(2.0), "scale": 0.2})
    assert neg["lo"] == pytest.approx(-u["hi"]) and neg["hi"] == pytest.approx(-u["lo"])
    n = models.uncertainty({"amount": 10.0, "uncertainty type": 3, "loc": 10.0, "scale": 1.0})
    assert (n["lo"], n["hi"], n["sd"]) == (pytest.approx(10 - 1.959964, rel=1e-6), pytest.approx(10 + 1.959964, rel=1e-6), 1.0)
    uni = models.uncertainty({"amount": 5.0, "uncertainty type": 4, "minimum": 4.0, "maximum": 6.0})
    assert (uni["lo"], uni["hi"]) == (pytest.approx(4.05), pytest.approx(5.95))
    assert models.uncertainty({"amount": 1.0, "uncertainty type": 0}) is None
    assert models.uncertainty({"amount": 1.0}) is None


def test_fields_for_what_the_user_gives():
    f = models.uncertainty_fields(4.0, {"type": "lognormal", "gsd2": "1.5"})
    assert f["uncertainty type"] == 2 and f["loc"] == pytest.approx(math.log(4)) and f["scale"] == pytest.approx(math.log(1.5) / 2)
    u = models.uncertainty({"amount": 4.0, **{k: v for k, v in f.items() if v is not None}})
    assert u["gsd2"] == pytest.approx(1.5) and u["hi"] == pytest.approx(4 * 1.5 ** 0.979982, rel=1e-5)  # σ = ln GSD
    assert models.uncertainty_fields(4.0, {"type": "normal", "pct": 10})["scale"] == pytest.approx(0.4)
    assert models.uncertainty_fields(4.0, {"type": "none"})["uncertainty type"] == 0
    for bad in ({"type": "lognormal", "gsd2": "0.9"}, {"type": "lognormal", "gsd2": "abc"}, {"type": "normal", "sd": "inf"}, {"type": "normal", "sd": "0"},
                {"type": "uniform", "minimum": 5, "maximum": 3}, {"type": "triangular", "minimum": 5, "maximum": 6},
                {"type": "cauchy"}):
        with pytest.raises(ValueError):
            models.uncertainty_fields(4.0, bad)


def _sigma(basic, *factors):
    return math.sqrt(sum(math.log(f) ** 2 for f in (basic, *factors))) / 2


PED = {"reliability": 2, "completeness": 3, "temporal correlation": 2, "geographical correlation": 1,
       "further technological correlation": 4}


def test_pedigree_as_in_the_activity_browser():
    # Activity Browser 3: σ = √(Σ ln² U) / 2 over the basic uncertainty and the factors of the five scores
    f = models.uncertainty_fields(4.0, {"type": "pedigree", "scores": PED, "basic": "1.05"})
    sigma = _sigma(1.05, 1.54, 1.04, 1.03, 1.0, 2.08)
    assert f["uncertainty type"] == 2 and f["loc"] == pytest.approx(math.log(4)) and f["scale"] == pytest.approx(sigma)
    assert f["pedigree"] == {**PED, "basic uncertainty": 1.05}
    u = models.uncertainty({"amount": 4.0, **{k: v for k, v in f.items() if v is not None}})
    assert u["gsd2"] == pytest.approx(math.exp(2 * sigma)) and u["pedigree_scores"] == PED
    assert u["pedigree_basic"] == pytest.approx(1.05)
    # ecoinvent stores only the scores: the basic uncertainty follows from σ
    eco = models.uncertainty({"amount": 4.0, "uncertainty type": 2, "scale": sigma, "pedigree": PED})
    assert eco["pedigree_basic"] == pytest.approx(1.05)
    assert models.uncertainty_fields(4.0, {"type": "pedigree", "scores": PED})["scale"] == pytest.approx(_sigma(1, 1.54, 1.04, 1.03, 1, 2.08))
    neg = models.uncertainty_fields(-4.0, {"type": "pedigree", "scores": PED})
    assert neg["negative"] is True and neg["loc"] == pytest.approx(math.log(4))
    for bad in ({"scores": {**PED, "reliability": 6}}, {"scores": {**PED, "completeness": 2.5}},
                {"scores": {k: v for k, v in PED.items() if k != "completeness"}}, {"scores": PED, "basic": "0.9"},
                {"scores": {k: 1 for k in PED}}, {"scores": {k: 1 for k in PED}, "basic": 1}):
        with pytest.raises(ValueError):
            models.uncertainty_fields(4.0, {"type": "pedigree", **bad})
    with pytest.raises(ValueError):
        models.uncertainty_fields(0.0, {"type": "pedigree", "scores": PED})


@pytest.fixture()
def proc():
    bd.projects.set_current(TEST_PROJECT)
    if DB in bd.databases:
        models.delete_database(DB)
    models.create_database(DB)
    p = models.create_process(DB, "Gerät", "unit", "CH", comment="Ein Gerät aus Aluminium, Annahmen: 10 Jahre.")
    el = next(a.id for a in bd.Database("BAFU-2025-v2") if a["name"] == "Electricity, low voltage, at grid" and a["location"] == "CH")
    ex = int(models.add_exchange(p, el, 10.0))
    yield p, ex
    models.delete_database(DB)


def _row(p, ex):
    d = s.activity(p, s.CLIMATE_METHOD)
    return d, next(e for e in d["technosphere"] if e["exchange"] == str(ex))


def test_set_move_and_undo(proc):
    p, ex = proc
    d, e = _row(p, ex)
    assert d["comment"].startswith("Ein Gerät") and e["uncertainty"] is None
    models.set_uncertainty(ex, {"type": "lognormal", "gsd2": 2})
    _, e = _row(p, ex)
    f = 2 ** 0.979982  # 97.5 percentile: amount × GSD^1.96, a bit under amount × GSD²
    assert e["uncertainty"]["lo"] == pytest.approx(10 / f, rel=1e-5) and e["uncertainty"]["hi"] == pytest.approx(10 * f, rel=1e-5)
    models.update_exchange(ex, amount=4.0)  # the distribution moves along, same GSD²
    _, e = _row(p, ex)
    assert e["uncertainty"]["lo"] == pytest.approx(4 / f, rel=1e-5) and e["uncertainty"]["hi"] == pytest.approx(4 * f, rel=1e-5)
    models.undo()  # back to 10, and to 5 … 20
    _, e = _row(p, ex)
    assert e["amount"] == 10 and e["uncertainty"]["hi"] == pytest.approx(10 * f, rel=1e-5)
    models.undo()  # no distribution again
    assert _row(p, ex)[1]["uncertainty"] is None
    bg = next(x for x in bd.Database("BAFU-2025-v2") if any(True for _ in x.technosphere()))
    with pytest.raises(s.ReadOnlyError):  # background data stay unchanged
        models.set_uncertainty(next(iter(bg.technosphere()))._document.id, {"type": "lognormal", "gsd2": 2})


def test_amount_zero_drops_the_lognormal_and_undo_restores_it(proc):
    """Regression: set to 0, a lognormal kept loc = ln(old amount), so Monte Carlo sampled around the old value."""
    p, ex = proc
    models.set_uncertainty(ex, {"type": "lognormal", "gsd2": 2})
    before = {k: models._plain(models.Exchange(models.ExchangeDataset.get_by_id(ex)).get(k)) for k in models.UNC_FIELDS}
    models.update_exchange(ex, amount=0.0)
    exc = models.Exchange(models.ExchangeDataset.get_by_id(ex))
    assert exc["amount"] == 0 and int(exc.get("uncertainty type") or 0) == 0 and exc.get("loc") is None
    assert _row(p, ex)[1]["uncertainty"] is None
    models.undo()
    exc = models.Exchange(models.ExchangeDataset.get_by_id(ex))
    assert exc["amount"] == 10 and {k: models._plain(exc.get(k)) for k in models.UNC_FIELDS} == before
    models.undo()


def test_api_and_description_in_search(proc):
    p, ex = proc
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.post("/api/models/exchange/uncertainty", json={"exchange": str(ex), "spec": {"type": "uniform", "minimum": "8", "maximum": "12"}})
        assert r.status_code == 200, r.text
        r = c.post("/api/models/exchange/uncertainty", json={"exchange": str(ex), "spec": {"type": "lognormal", "gsd2": "1"}})
        assert r.status_code == 400
    _, e = _row(p, ex)
    assert e["uncertainty"]["name"] == "uniform" and e["uncertainty"]["lo"] == pytest.approx(8.1)
    hit = next(r for r in s.search("Gerät") if r["id"] == str(p))
    assert hit["comment"] == "Ein Gerät aus Aluminium, Annahmen: 10 Jahre."


def test_undo_restores_the_distribution_exactly(proc):
    p, ex = proc
    models.set_uncertainty(ex, {"type": "normal", "sd": "1.3"})
    for amount in (3.0, 7.7, 0.1):
        models.update_exchange(ex, amount=amount)
    for _ in range(3):
        models.undo()
    data = bd.get_node(id=int(p)).technosphere()
    exc = next(e for e in data if e._document.id == ex)
    assert exc["amount"] == 10 and exc["scale"] == 1.3 and exc["loc"] == 10  # exact, no rounding drift
    models.undo()  # and the distribution itself can still be undone
    assert _row(p, ex)[1]["uncertainty"] is None


def test_monte_carlo_samples_the_distribution_set_in_a_model(proc):
    from lca_wrench import montecarlo as mc

    p, _ex = proc
    method = s.CLIMATE_METHOD
    flow, cf = next((k, v) for k, v in bd.Method(method).load() if v == 1)
    co2 = int(models.add_exchange(p, bd.get_node(**({"id": flow} if isinstance(flow, int) else {"database": flow[0], "code": flow[1]})).id, 10.0))
    models.delete_exchange(_ex)  # only the CO2: the result is 1 × the drawn amount
    models.set_uncertainty(co2, {"type": "uniform", "minimum": 8, "maximum": 12})
    bd.Database(DB).process()
    d = mc.run_chunk(TEST_PROJECT, [(int(p), 1.0)], [method], 200, 7)[:, 0, 0]
    assert d.min() >= 8 - 1e-9 and d.max() <= 12 + 1e-9 and d.std() > 0.5


def test_pedigree_in_a_model_and_undo(proc):
    p, ex = proc
    models.set_uncertainty(ex, {"type": "pedigree", "scores": PED, "basic": 1.1})
    _, e = _row(p, ex)
    sigma = _sigma(1.1, 1.54, 1.04, 1.03, 1.0, 2.08)
    assert e["uncertainty"]["gsd2"] == pytest.approx(math.exp(2 * sigma)) and e["uncertainty"]["pedigree_scores"] == PED
    models.update_exchange(ex, amount=4.0)  # the scores stay with the moved distribution
    _, e = _row(p, ex)
    assert e["uncertainty"]["pedigree_basic"] == pytest.approx(1.1) and e["uncertainty"]["hi"] > 4
    models.set_uncertainty(ex, {"type": "lognormal", "gsd2": 1.5})  # a GSD² typed in: no pedigree any more
    assert "pedigree" not in _row(p, ex)[1]["uncertainty"]
    models.undo()
    assert _row(p, ex)[1]["uncertainty"]["pedigree_scores"] == PED
