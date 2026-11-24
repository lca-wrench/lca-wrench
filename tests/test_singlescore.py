"""Single scores (singlescore.py): EF 3.1 normalized and weighted, ReCiPe 2016 endpoint points, total UBP.

The EF and ReCiPe methods here are synthetic: named as in sentier's and ecoinvent's projects (the names only, no data),
their factors are those of LCA Wrench's climate method times a number. So each category's result is that number times
the climate result, and the single scores can be worked out by hand. Ecological Scarcity 2021 is the real BAFU template.
"""

import json

import bw2data as bd
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import models, singlescore
from lca_wrench import service as s
from lca_wrench.api import app

EF = ("sentier", "EF v3.1")
EF_NOLT = ("ecoinvent-style", "EF v3.1 no LT")
RECIPE_H = ("ReCiPe 2016 v1.03, endpoint (H)",)
RECIPE_I = ("ecoinvent-style", "ReCiPe 2016 v1.03, endpoint (I) no LT")
ES = ("ecoinvent-style", "Ecological Scarcity 2021 no LT")

EF31 = json.loads((singlescore.DATA / "ef31.json").read_text(encoding="utf-8"))
RECIPE = json.loads((singlescore.DATA / "recipe2016-endpoint.json").read_text(encoding="utf-8"))
NF_H = RECIPE["normalisation"]["H"]

# method -> (unit, multiple of the climate result)
METHODS = {
    **{EF + (c["label"],): (c["unit"], i + 1.0) for i, c in enumerate(EF31["categories"])},
    EF_NOLT + ("climate change no LT", "global warming potential (GWP100) no LT"): ("kg CO2-Eq", 1.0),
    EF_NOLT + ("particulate matter formation no LT", "impact on human health no LT"): ("disease incidence", 2e-6),
    EF_NOLT + ("climate change: fossil no LT", "global warming potential (GWP100) no LT"): ("kg CO2-Eq", 1.0),  # a part
    RECIPE_H + ("total: human health", "human health"): ("DALYs", 1.03e-6),
    RECIPE_H + ("human health", "climate change: human health"): ("DALYs", 9.3e-7),
    RECIPE_H + ("human health", "particulate matter formation"): ("DALYs", 1e-7),
    RECIPE_H + ("total: ecosystem quality", "ecosystem quality"): ("species.yr", 3e-9),  # not its categories' sum
    RECIPE_H + ("ecosystem quality", "climate change: terrestrial ecosystems"): ("species.yr", 2.8e-9),
    RECIPE_H + ("total: natural resources", "natural resources"): ("USD 2013", 0.05),  # no categories: the total
    RECIPE_I + ("total: human health no LT", "human health no LT"): ("DALYs", 1e-6),
    ES + ("total no LT", "UBP no LT"): ("UBP", 1500.0),
    ES + ("climate change no LT", "UBP no LT"): ("UBP", 1000.0),
    ES + ("water use no LT", "UBP no LT"): ("UBP", 500.0),
}


@pytest.fixture(scope="module")
def methods():
    cfs = bd.Method(s.CLIMATE_METHOD).load()
    for name, (unit, k) in METHODS.items():
        m = bd.Method(name)
        m.register(unit=unit, description="test_singlescore.py")
        m.write([(key, cf * k) for key, cf in cfs])
    yield METHODS
    for name in METHODS:
        bd.Method(name).deregister()


@pytest.fixture(scope="module")
def electricity():
    return next(a for a in bd.Database("BAFU-2025-v2")
                if a["name"] == "Electricity, low voltage, at grid" and a.get("location") == "CH")


@pytest.fixture(scope="module")
def climate(electricity):
    """The system and the climate result of 1 kWh, which the synthetic methods multiply."""
    S = models.system_for(electricity.id)
    return S, {electricity.id: 1.0}, S.score({electricity.id: 1.0}, s.CLIMATE_METHOD)


def test_factor_files():
    cats = EF31["categories"]
    assert len(cats) == 16 and sum(c["weighting"] for c in cats) == pytest.approx(100)
    cc = next(c for c in cats if c["label"] == "Climate change")
    assert cc["normalisation"] == pytest.approx(7553.08, rel=1e-6) and cc["weighting"] == 21.06 and EF31["scale"] == 1000
    assert NF_H["human health"] == pytest.approx(0.0240019, rel=1e-5)  # RIVM, world 2010, the sum of 8 categories
    assert NF_H["natural resources"] == pytest.approx(28033.3, rel=1e-5)
    # ecosystem quality with land use (occupation), the row whose name in RIVM's sheet ends in a space
    assert RECIPE["normalisation_categories"]["ecosystem quality"]["H"]["Land use - occupation"] == pytest.approx(
        6.23363e-4, rel=1e-5)
    assert NF_H["ecosystem quality"] == pytest.approx(1.479212e-3, rel=1e-5)
    assert all(sum(w.values()) == 1000 for w in RECIPE["weighting"].values())
    assert RECIPE["default_weighting"] == {"I": "I/I", "H": "H/A", "E": "E/E"}


def test_names_in_the_usual_spellings():
    assert singlescore.norm("Climate change no LT") == "climate change"
    found = singlescore._sets_ef([("EF v3.1 PEF", "EF-particulate Matter"), ("EF v3.1 PEF", "Climate change"),
                                  ("EF v3.0", "climate change"), ("sentier", "EF v3.1", "climate change: fossil")])
    assert [x["family"] for x in found] == [("EF v3.1 PEF",)]  # EF 3.0 is another method; a part is no category
    assert [c["label"] for c in found[0]["components"]] == ["Climate change", "Particulate matter"]
    assert len(found[0]["missing"]) == 14
    rec = singlescore._sets_recipe([("ReCiPe 2016 v1.03, endpoint (E) no LT", "total: natural resources no LT", "x"),
                                    ("ReCiPe 2016 v1.03, midpoint (H)", "climate change", "global warming potential")])
    assert len(rec) == 1 and rec[0]["perspective"] == "E" and rec[0]["weighting"] == "E/E"
    assert rec[0]["components"] == ["natural resources"] and rec[0]["missing"] == ["human health", "ecosystem quality"]


def test_sets_order_and_what_is_missing(methods):
    sets = singlescore.sets()
    kinds = [x["kind"] for x in sets]
    assert kinds == sorted(kinds, key=["ef31", "recipe2016", "es2021"].index)
    assert [x["family"] for x in sets if x["kind"] == "ef31"][:2] == [EF, EF_NOLT]  # long-term emissions first
    assert [x.get("perspective") for x in sets if x["kind"] == "recipe2016"] == ["H", "I"]
    rec_i = singlescore.summary(singlescore.find("recipe2016:" + "|".join(RECIPE_I)))
    assert rec_i["weighting"] == "I/I" and rec_i["missing"] == ["Ökosystemqualität", "Natürliche Ressourcen"]
    with pytest.raises(KeyError):
        singlescore.find("ef31:nothing")


def test_ef31_all_16_categories(methods, climate):
    S, demand, c = climate
    r = singlescore.compute(S, demand, singlescore.find("ef31:sentier|EF v3.1"))
    assert r["unit"] == "mPt" and len(r["rows"]) == 16 and not r["missing"] and not r["notes"]
    by = {x["label"]: x for x in r["rows"]}
    for cat in EF31["categories"]:
        k = methods[EF + (cat["label"],)][1]
        row = by[cat["label"]]
        assert row["result"] == pytest.approx(k * c, rel=1e-6)
        assert row["normalised"] == pytest.approx(k * c / cat["normalisation"], rel=1e-6)
        assert row["score"] == pytest.approx(k * c / cat["normalisation"] * cat["weighting"] / 100 * 1000, rel=1e-6)
    assert r["total"] == pytest.approx(sum(x["score"] for x in r["rows"]), rel=1e-12)
    assert sum(x["share"] for x in r["rows"]) == pytest.approx(1)
    assert [x["score"] for x in r["rows"]] == sorted((x["score"] for x in r["rows"]), key=abs, reverse=True)


def test_ef31_with_missing_categories(methods, climate):
    S, demand, c = climate
    st = singlescore.find("ef31:" + "|".join(EF_NOLT))
    r = singlescore.compute(S, demand, st)
    cats = {x["label"]: x for x in EF31["categories"]}
    cc, pm = cats["Climate change"], cats["Particulate matter"]
    expected = (c / cc["normalisation"] * cc["weighting"] + 2e-6 * c / pm["normalisation"] * pm["weighting"]) / 100 * 1000
    assert r["total"] == pytest.approx(expected, rel=1e-6)
    assert {x["label"] for x in r["rows"]} == {"Climate change", "Particulate matter"}  # not "climate change: fossil"
    assert len(r["missing"]) == 14 and "14 Kategorie(n)" in r["notes"][0]


def test_recipe_endpoint_points(methods, climate):
    S, demand, c = climate
    st = singlescore.find("recipe2016:" + "|".join(RECIPE_H))
    assert st["perspective"] == "H" and st["weighting"] == "H/A"
    hh, eq, res = (9.3e-7 + 1e-7) * c, 2.8e-9 * c, 0.05 * c  # human health and ecosystems from their categories

    def points(w):
        w = RECIPE["weighting"][w]
        return (hh / NF_H["human health"] * w["human health"] + eq / NF_H["ecosystem quality"] * w["ecosystem quality"]
                + res / NF_H["natural resources"] * w["natural resources"])

    r = singlescore.compute(S, demand, st)
    assert r["unit"] == "Pt" and r["weighting"] == "H/A" and r["total"] == pytest.approx(points("H/A"), rel=1e-6)
    assert len(r["rows"]) == 4 and {x["group"] for x in r["rows"]} == {"Menschliche Gesundheit", "Ökosystemqualität",
                                                                       "Natürliche Ressourcen"}
    assert next(x for x in r["rows"] if x["label"] == "climate change: human health")["weight"] == 400
    # the categories of ecosystem quality do not add up to its total (on purpose here); those of human health do
    assert any("«Ökosystemqualität»" in n for n in r["notes"])
    assert not any("«Menschliche Gesundheit»" in n for n in r["notes"])
    hh_h = singlescore.compute(S, demand, st, "H/H")
    assert hh_h["weighting"] == "H/H" and hh_h["total"] == pytest.approx(points("H/H"), rel=1e-6)
    assert singlescore.compute(S, demand, st, "X/Y")["weighting"] == "H/A"  # unknown: the default


def test_ubp_total_and_categories(methods, climate):
    S, demand, c = climate
    r = singlescore.compute(S, demand, singlescore.find("es2021:" + "|".join(ES)))
    assert r["unit"] == "UBP" and r["total"] == pytest.approx(1500 * c, rel=1e-6) and not r["notes"]
    assert [x["label"] for x in r["rows"]] == ["climate change no LT", "water use no LT"]  # without "UBP"
    # the BAFU template: 21 categories, the total is LCA Wrench's derived method, which is their sum
    bafu = singlescore.find("es2021:Ecological Scarcity 2021")
    assert bafu["total"] == s.UBP_TOTAL_METHOD
    r = singlescore.compute(S, demand, bafu)
    assert len(r["rows"]) == 21 and not r["notes"]
    assert r["total"] == pytest.approx(S.score(demand, s.UBP_TOTAL_METHOD), rel=1e-6)
    assert sum(x["score"] for x in r["rows"]) == pytest.approx(r["total"], rel=1e-6)


def test_api(methods, electricity):
    bd.projects.set_current(TEST_PROJECT)  # as the user would choose it
    client = TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"})
    sets = client.get("/api/singlescore/sets").json()["sets"]
    assert {"ef31", "recipe2016", "es2021"} <= {x["kind"] for x in sets}
    sid = next(x["id"] for x in sets if x["kind"] == "recipe2016" and x["perspective"] == "H")
    one = client.post("/api/singlescore", json={"id": str(electricity.id), "set": sid}).json()
    two = client.post("/api/singlescore", json={"id": str(electricity.id), "amount": 2, "set": sid, "weighting": "E/E"}).json()
    assert one["weighting"] == "H/A" and two["weighting"] == "E/E" and two["amount"] == 2
    e = RECIPE["weighting"]["E/E"]
    assert two["total"] == pytest.approx(2 * sum(x["normalised"] * e[x["area"]] for x in one["rows"]), rel=1e-6)
    bad = client.post("/api/singlescore", json={"id": str(electricity.id), "set": "ef31:nothing"})
    assert bad.status_code == 404 and "Einzelwert" in bad.json()["detail"]
    # with a product, each set says whether it covers the product's elementary flows
    per_product = client.get("/api/singlescore/sets", params={"id": str(electricity.id)}).json()["sets"]
    assert {x["coverage"] for x in per_product} == {"native"} and "coverage" not in sets[0]


OTHER = "singlescore-test-flows"


@pytest.fixture
def other_flow_list():
    """A second list of elementary flows with one flow, and an EF family whose climate change has factors only there
    (as sentier's EF 3.1 on an ecoinvent product, for an impact the flow mapping does not fill)."""
    bd.Database(OTHER).write({(OTHER, "x"): {"name": "x", "unit": "kilogram", "type": "emission", "categories": ("air",)}})
    cfs = bd.Method(s.CLIMATE_METHOD).load()
    made = {("other-list", "EF v3.1", "Climate change"): [((OTHER, "x"), 1.0)],
            ("other-list", "EF v3.1", "Particulate matter"): [(key, cf * 1e-6) for key, cf in cfs]}
    for name, data in made.items():
        bd.Method(name).register(unit="test", description="test_singlescore.py")
        bd.Method(name).write(data)
    yield made
    for name in made:
        bd.Method(name).deregister()
    del bd.databases[OTHER]


def test_a_category_on_another_flow_list_is_flagged(methods, climate, electricity, other_flow_list):
    S, demand, _c = climate
    r = singlescore.compute(S, demand, singlescore.find("ef31:other-list|EF v3.1"))
    by = {x["label"]: x for x in r["rows"]}
    assert by["Climate change"]["coverage"] == "missing" and by["Climate change"]["result"] == 0
    assert by["Particulate matter"]["coverage"] == "native" and by["Particulate matter"]["result"] > 0
    assert r["incomplete"] == ["Climate change"] and "1 Kategorie(n)" in r["warning"] and "Climate change" in r["warning"]
    assert singlescore.compute(S, demand, singlescore.find("ef31:sentier|EF v3.1"))["warning"] is None
    sets = {x["id"]: x for x in s.single_score_sets(electricity.id)["sets"]}
    assert sets["ef31:other-list|EF v3.1"]["coverage"] == "missing"
    assert sets["ef31:sentier|EF v3.1"]["coverage"] == "native"
