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


# ---------- the same farm, written by bw_functional as the Activity Browser 3 writes it ----------

AB3 = "Test MF AB3"


@pytest.fixture()
def ab3(farm):
    """The farm as a functional_sqlite database, allocated by price, registered as an own model (writable)."""
    from bw_functional import FunctionalSQLiteDatabase

    _drop(AB3)
    db = FunctionalSQLiteDatabase(AB3)
    db.register(default_allocation="equal")  # as bw_functional; the farm itself is split by price

    def prod(code, name, processor, price):
        return {(AB3, code): {"type": "product", "name": name, "product": name, "unit": "kilogram",
                              "location": "CH", "processor": (AB3, processor),
                              "properties": {"price": {"unit": "EUR", "amount": price, "normalize": True},
                                             "mass": {"unit": "kg", "amount": 1.0, "normalize": True}}}}

    data = {
        (AB3, "farm"): {"name": "dairy farm", "type": "multifunctional", "location": "CH", "allocation": "price",
                        "exchanges": [{"input": (AB3, "milk"), "amount": 8, "type": "production"},
                                      {"input": (AB3, "meat"), "amount": 1, "type": "production"},
                                      {"input": (BG, "elec"), "amount": 10, "type": "technosphere"},
                                      {"input": CO2, "amount": 4, "type": "biosphere"}]},
        (AB3, "dairy"): {"name": "cheese making", "type": "process", "location": "CH",
                         "exchanges": [{"input": (AB3, "cheese"), "amount": 1, "type": "production"},
                                       {"input": (AB3, "milk"), "amount": 10, "type": "technosphere"},
                                       {"input": CO2, "amount": 0.2, "type": "biosphere"}]},
    }
    data.update(prod("milk", "raw milk", "farm", 0.5))
    data.update(prod("meat", "beef", "farm", 6.0))
    data.update({(AB3, "cheese"): {"type": "product", "name": "cheese", "product": "cheese", "unit": "kilogram",
                                   "location": "CH", "processor": (AB3, "dairy")}})
    db.write(data)
    for code in ("farm", "dairy"):
        bd.get_node(database=AB3, code=code).allocate()
    bd.databases.clean()
    models.add_model(AB3)
    engine.bump_background(TEST_PROJECT)
    engine.bump_foreground(TEST_PROJECT)
    yield {code: bd.get_node(database=AB3, code=code).id for code in ("farm", "milk", "meat", "dairy", "cheese")}
    bd.projects.set_current(TEST_PROJECT)
    models.delete_database(AB3)
    _drop(AB3)


def _bw2calc(node_id: int) -> float:
    import bw2calc as bc

    bd.databases.clean()  # bw_functional prepares the changed database for bw2calc
    lca = bc.LCA({bd.get_node(id=node_id): 1}, GWP)
    lca.lci()
    lca.lcia()
    return float(lca.score)


def test_ab3_database_same_as_bw2calc(ab3):
    """LCA Wrench's engine and bw2calc on bw_functional's own processing give the same results."""
    assert bd.get_node(id=ab3["farm"])["type"] == "multifunctional"
    S = models.system()
    for code, want in (("milk", 0.45), ("meat", 5.4), ("cheese", 4.7)):
        assert S.score({ab3[code]: 1}, GWP) == pytest.approx(want, rel=1e-9)
        assert _bw2calc(ab3[code]) == pytest.approx(want, rel=1e-6)


def test_ab3_data_sheet_and_allocation(ab3):
    sheet = s.activity(ab3["farm"], GWP)
    al = sheet["allocation"]
    assert al["strategy"] == "price" and al["strategies"] == ["equal", "mass", "price", "manual"] and al["editable"]
    by_name = {p["name"]: p for p in al["products"]}
    assert by_name["raw milk"]["factor"] == pytest.approx(0.4) and by_name["beef"]["score"] == pytest.approx(5.4)
    assert sheet["score"] is None  # several products: no single score
    milk = s.activity(ab3["milk"], GWP)
    assert milk["share"] == pytest.approx(0.4) and milk["process_id"] == str(ab3["farm"]) and milk["edit_mode"] is None
    assert milk["score"] == pytest.approx(0.45) and [e["amount"] for e in milk["technosphere"]] == [pytest.approx(4.0)]
    cheese_proc = s.activity(ab3["dairy"], GWP)  # a process with one product is calculated as that product
    assert cheese_proc["score"] == pytest.approx(4.7) and cheese_proc["allocation"] is None

    # by mass, then back with undo
    models.set_allocation(ab3["farm"], "mass")
    S = models.system()
    assert S.score({ab3["milk"]: 1}, GWP) == pytest.approx(1.0, rel=1e-9)
    assert _bw2calc(ab3["milk"]) == pytest.approx(1.0, rel=1e-6)
    models.undo()
    S = models.system()
    assert S.score({ab3["milk"]: 1}, GWP) == pytest.approx(0.45, rel=1e-9)
    assert bd.get_node(id=ab3["farm"])["allocation"] == "price"

    # by hand: 3 : 1 (scaled to add up to 1)
    models.set_allocation(ab3["farm"], "manual", {ab3["milk"]: 3, ab3["meat"]: 1})
    S = models.system()
    assert S.score({ab3["milk"]: 1}, GWP) == pytest.approx(0.75 * 9 / 8, rel=1e-9)
    with pytest.raises(ValueError):
        models.set_allocation(ab3["farm"], "energy")  # no product has this property
    with pytest.raises(ValueError):
        models.set_allocation(ab3["dairy"], "equal")  # one product: nothing to split


def test_ab3_compare_allocations(ab3):
    res = s.allocation_compare(ab3["milk"], GWP)
    rows = {r["strategy"]: r for r in res["rows"]}
    milk, meat = str(ab3["milk"]), str(ab3["meat"])
    assert set(rows) == {"equal", "mass", "price", "manual"} and rows["price"]["current"]
    assert rows["equal"]["scores"][milk] == pytest.approx(0.5 * 9 / 8) and rows["equal"]["scores"][meat] == pytest.approx(4.5)
    assert rows["mass"]["scores"][milk] == pytest.approx(1.0) and rows["mass"]["factors"][meat] == pytest.approx(1 / 9)
    assert rows["price"]["scores"][meat] == pytest.approx(5.4)
    assert rows["manual"]["scores"][milk] == pytest.approx(0.45)  # by hand = the shares stored now
    # nothing was saved
    assert models.system().score({ab3["milk"]: 1}, GWP) == pytest.approx(0.45, rel=1e-9)


def test_ab3_amount_change_moves_the_shares(ab3):
    """By price, revenue counts: 16 kg of milk at 0.5 EUR and 1 kg of meat at 6 EUR share 8 : 6."""
    farm = bd.get_node(id=ab3["farm"])
    edge = next(e for e in farm.exchanges() if e["type"] == "production" and e.input.id == ab3["milk"])
    models.update_exchange(edge._document.id, amount=16.0)
    assert bd.get_node(id=ab3["milk"])["allocation_factor"] == pytest.approx(8 / 14)
    S = models.system()
    assert S.score({ab3["milk"]: 1}, GWP) == pytest.approx(8 / 14 * 9 / 16, rel=1e-9)
    assert _bw2calc(ab3["milk"]) == pytest.approx(8 / 14 * 9 / 16, rel=1e-6)
