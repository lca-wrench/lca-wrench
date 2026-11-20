"""Processes with several products, stored as the Activity Browser 3 stores them (bw_functional): process and
product nodes, each product with its `processor` and its `allocation_factor`. The engine splits every input and
emission of a process onto its products by these factors, as bw_functional does when it prepares the database for
bw2calc. Checked against a hand calculation.

A dairy farm makes 8 kg of milk and 1 kg of meat per operation, with 10 kWh of electricity (0.5 kg CO2 each) and
4 kg CO2 of its own: 9 kg CO2 per operation. Cheese making uses 10 kg of milk and emits 0.2 kg CO2 per kg of cheese.
"""

import bw2data as bd
import pytest

from conftest import TEST_PROJECT
from lca_wrench import engine, models
from lca_wrench import service as s

BIO, BG, MODEL = "Test MF biosphere", "Test MF background", "Test MF model"
GWP = ("Test MF", "GWP")
CO2 = (BIO, "co2")


def _drop(*names):
    for n in names:
        if n in bd.databases:
            del bd.databases[n]


def _product(code, name, processor, price, factor):
    return {(MODEL, code): {"name": processor[1], "product": name, "reference product": name, "type": "product",
                            "unit": "kilogram", "location": "CH", "processor": processor, "allocation_factor": factor,
                            "properties": {"price": {"unit": "EUR", "amount": price, "normalize": True},
                                           "mass": {"unit": "kg", "amount": 1.0, "normalize": True}},
                            "exchanges": []}}


@pytest.fixture()
def farm():
    bd.projects.set_current(TEST_PROJECT)
    _drop(MODEL, BG, BIO)
    bio = bd.Database(BIO)
    bio.register()
    bio.write({CO2: {"name": "Carbon dioxide, fossil", "categories": ("air",), "unit": "kilogram", "type": "emission"}})
    m = bd.Method(GWP)
    m.register(unit="kg CO2-Eq")
    m.write([(CO2, 1.0)])
    bg = bd.Database(BG)
    bg.register()
    bg.write({(BG, "elec"): {"name": "electricity", "reference product": "electricity", "unit": "kilowatt hour",
                             "location": "CH", "type": "process",
                             "exchanges": [{"input": (BG, "elec"), "amount": 1, "type": "production"},
                                           {"input": CO2, "amount": 0.5, "type": "biosphere"}]}})
    models.create_database(MODEL)
    data = {
        (MODEL, "farm"): {"name": "dairy farm", "type": "multifunctional", "location": "CH", "allocation": "price",
                          "exchanges": [{"input": (MODEL, "milk"), "amount": 8, "type": "production"},
                                        {"input": (MODEL, "meat"), "amount": 1, "type": "production"},
                                        {"input": (BG, "elec"), "amount": 10, "type": "technosphere"},
                                        {"input": CO2, "amount": 4, "type": "biosphere"}]},
        (MODEL, "dairy"): {"name": "cheese making", "type": "process", "location": "CH",
                           "exchanges": [{"input": (MODEL, "cheese"), "amount": 1, "type": "production"},
                                         {"input": (MODEL, "milk"), "amount": 10, "type": "technosphere"},
                                         {"input": CO2, "amount": 0.2, "type": "biosphere"}]},
        (MODEL, "cheese"): {"name": "cheese making", "product": "cheese", "reference product": "cheese",
                            "type": "product", "unit": "kilogram", "location": "CH", "processor": (MODEL, "dairy"),
                            "exchanges": []},
    }
    # by price: revenue 8 × 0.5 = 4 EUR for milk, 1 × 6 = 6 EUR for meat
    data.update(_product("milk", "raw milk", (MODEL, "farm"), 0.5, 0.4))
    data.update(_product("meat", "beef", (MODEL, "farm"), 6.0, 0.6))
    bd.Database(MODEL).write(data)
    engine.bump_background(TEST_PROJECT)
    engine.bump_foreground(TEST_PROJECT)
    yield {code: bd.get_node(database=MODEL, code=code).id for code in ("farm", "milk", "meat", "dairy", "cheese")}
    bd.projects.set_current(TEST_PROJECT)
    models.delete_database(MODEL)
    _drop(MODEL, BG, BIO)
    if GWP in bd.methods:
        bd.Method(GWP).deregister()
    engine.bump_background(TEST_PROJECT)
    engine.bump_foreground(TEST_PROJECT)


def _set_factors(milk: float, meat: float):
    for code, factor in (("milk", milk), ("meat", meat)):
        node = bd.get_node(database=MODEL, code=code)
        node["allocation_factor"] = factor
        node.save()
    engine.bump_foreground(TEST_PROJECT)


def test_products_carry_their_share(farm):
    S = models.system()
    # milk 0.4 × 9 / 8, meat 0.6 × 9 / 1, cheese 10 × milk + 0.2
    assert S.score({farm["milk"]: 1}, GWP) == pytest.approx(0.45, rel=1e-9)
    assert S.score({farm["meat"]: 1}, GWP) == pytest.approx(5.4, rel=1e-9)
    assert S.score({farm["cheese"]: 1}, GWP) == pytest.approx(4.7, rel=1e-9)
    # the two products together bear the whole farm, nothing counted twice
    assert 8 * S.score({farm["milk"]: 1}, GWP) + S.score({farm["meat"]: 1}, GWP) == pytest.approx(9.0, rel=1e-9)
    # a process with one product stands for that product; with several, one has to be chosen
    assert S.score({farm["dairy"]: 1}, GWP) == pytest.approx(4.7, rel=1e-9)
    with pytest.raises(KeyError, match="mehrere Produkte"):
        S.ref_row(farm["farm"])
    assert S.fg.functions[farm["farm"]] == sorted([(farm["milk"], 0.4), (farm["meat"], 0.6)])
    assert not S.fg.errors and not S.fg.notes


def test_other_allocation_changes_the_split(farm):
    _set_factors(8 / 9, 1 / 9)  # by mass: 8 kg and 1 kg
    S = models.system()
    assert S.score({farm["milk"]: 1}, GWP) == pytest.approx(1.0, rel=1e-9)
    assert S.score({farm["meat"]: 1}, GWP) == pytest.approx(1.0, rel=1e-9)
    assert S.score({farm["cheese"]: 1}, GWP) == pytest.approx(10.2, rel=1e-9)


def test_factors_that_do_not_add_up_are_noted(farm):
    _set_factors(0.4, 0.5)
    S = models.system()
    assert any("0.9" in t for t in S.fg.note_texts())
    assert S.score({farm["meat"]: 1}, GWP) == pytest.approx(4.5, rel=1e-9)  # calculated as given, as bw_functional does


def test_result_views_work_on_products(farm):
    res = s.calculate(farm["cheese"], 1.0, GWP)
    assert res["score"] == pytest.approx(4.7, rel=1e-9)
