"""Background choice (one database or several combined), premise scenarios and EXIOBASE.

A miniature "ecoinvent" world in the test project: a biosphere with two flows, a GWP method, three processes
(electricity, steel, heat), a "2040 scenario" of it and a model using all three. premise itself is replaced by a
stand-in with the same interface (tests/fake_premise), EXIOBASE by a 2-region, 2-sector table in its file format.
"""

import json
import os
import sys
import time
from pathlib import Path

import bw2calc as bc
import bw2data as bd
import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import backgrounds, engine, exiobase, flowmap, models, montecarlo, scenarios
from lca_wrench import service as s
from lca_wrench.api import app

BIO, EI, SC, MODEL = "Test EI biosphere", "ecoinvent-3.10-cutoff", "Test 2040 remind SSP2-NPi 2040", "Test Szenario Modell"
GWP = ("Test", "GWP")
CO2, CH4 = (BIO, "co2"), (BIO, "ch4")


def _proc(db, code, name, product, loc, unit, inputs=(), bio=()):
    exc = [{"input": (db, code), "amount": 1, "type": "production"}]
    exc += [{"input": (db, c), "amount": a, "type": "technosphere"} for c, a in inputs]
    exc += [{"input": f, "amount": a, "type": "biosphere"} for f, a in bio]
    return {(db, code): {"name": name, "reference product": product, "location": loc, "unit": unit, "type": "process",
                         "exchanges": exc}}


def _ei(db, elec_co2, steel_code="steel", heat=True):
    data = {}
    data.update(_proc(db, "elec", "market for electricity, low voltage", "electricity, low voltage", "CH", "kilowatt hour",
                      [(steel_code, 0.001)], [(CO2, elec_co2)]))
    data.update(_proc(db, steel_code, "steel production", "steel", "GLO", "kilogram", (), [(CO2, 2.0), (CH4, 0.01)]))
    if heat:
        data.update(_proc(db, "heat", "heat production", "heat", "CH", "megajoule", (), [(CO2, 0.07)]))
    return data


def _drop(*names):
    for n in names:
        if n in bd.databases:
            del bd.databases[n]


@pytest.fixture(scope="module")
def world():
    bd.projects.set_current(TEST_PROJECT)
    reg = models.registry.load()
    _drop(MODEL, SC, EI, BIO)
    b = bd.Database(BIO)
    b.register()
    b.write({CO2: {"name": "Carbon dioxide, fossil", "categories": ("air",), "unit": "kilogram", "type": "emission"},
             CH4: {"name": "Methane, fossil", "categories": ("air",), "unit": "kilogram", "type": "emission"}})
    m = bd.Method(GWP)
    m.register(unit="kg CO2-Eq")
    m.write([(CO2, 1.0), (CH4, 28.0)])
    for name, data in ((EI, _ei(EI, 0.1)), (SC, _ei(SC, 0.02, "steel-2040", heat=False))):
        d = bd.Database(name)
        d.register()
        d.write(data)
    meta = dict(bd.databases[SC])
    meta["lca_wrench"] = {"kind": "scenario"}
    bd.databases[SC] = meta
    bd.databases.flush()
    models.create_database(MODEL)
    dev = int(models.create_process(MODEL, "Device", "unit", "CH"))
    for code, amount in (("elec", 10.0), ("steel", 1.0), ("heat", 5.0)):
        models.add_exchange(dev, bd.get_node(database=EI, code=code).id, amount)
    engine.bump_background(TEST_PROJECT)
    yield dev
    bd.projects.set_current(TEST_PROJECT)
    backgrounds.set_choice("auto", [], models.roles())
    models.delete_database(MODEL)
    _drop(SC, EI, BIO, *[n for n in bd.databases if n.startswith(EI) or n.startswith("EXIOBASE")])
    if GWP in bd.methods:
        bd.Method(GWP).deregister()
    models.registry.save({**models.registry.load(), "backgrounds": reg.get("backgrounds", {})})
    engine.bump_background(TEST_PROJECT)


# Brightway keeps matrix values as float32: compared to about 1e-6
TODAY = 10 * (0.1 + 0.001 * 2.28) + 2.28 + 5 * 0.07  # 3.6528
Y2040 = 10 * (0.02 + 0.001 * 2.28) + 2.28 + 5 * 0.07  # heat has no counterpart: from today


def test_default_is_all_process_databases(world):
    roles = models.roles()
    assert backgrounds.kind(SC) == "scenario" and backgrounds.kind(EI) == "lci"
    ch = backgrounds.choice(roles)
    assert ch["mode"] == "auto" and EI in ch["databases"] and SC not in ch["databases"]
    S = models.system()
    assert S.score({world: 1}, GWP) == pytest.approx(TODAY, rel=1e-6) and S.substituted == 0
    # BAFU (sparse) and the small matrix (dense) side by side: one solver each
    assert S.bg.solver is not None and sorted(S.bg.solver.kinds) == ["dense", "sparse"]


def test_single_scenario_takes_the_counterparts(world):
    roles = models.roles()
    backgrounds.set_choice("single", [SC], roles)
    try:
        S = models.system()
        assert S.score({world: 1}, GWP) == pytest.approx(Y2040, rel=1e-6)
        assert S.substituted == 2 and S.pulled == [EI]  # electricity by code, steel by name; heat from today
        # a dataset of today, calculated on the scenario
        elec = bd.get_node(database=EI, code="elec")
        r = s.calculate(elec.id, 1, GWP)
        assert r["score"] == pytest.approx(0.02 + 0.001 * 2.28, rel=1e-6)
        assert r["counterpart"]["database"] == SC
        # the search shows the chosen background (and the models), not BAFU
        hits = s.search("steel production")
        assert hits and {h["database"] for h in hits} <= {SC, EI, MODEL}
        assert all(h["database"] != "BAFU-2025-v2" for h in s.search("electricity"))
        with pytest.raises(ValueError, match="Unsicherheitsrechnung"):
            s.monte_carlo_start([{"id": world, "amount": 1}], [GWP], n=20)
    finally:
        backgrounds.set_choice("auto", [], roles)


def test_combined_and_compare_per_item(world):
    roles = models.roles()
    st = backgrounds.set_choice("combined", [EI, SC], roles)
    assert st["mode"] == "combined" and st["databases"] == [EI, SC]
    assert models.system().score({world: 1}, GWP) == pytest.approx(TODAY, rel=1e-6)  # links as stored
    backgrounds.set_choice("auto", [], roles)
    # automatic: a model linked to the scenario stays on it (no counterpart taken from today)
    fut = int(models.create_process(MODEL, "Device 2040", "unit", "CH"))
    models.add_exchange(fut, bd.get_node(database=SC, code="elec").id, 10.0)
    S = models.system()
    assert S.score({fut: 1}, GWP) == pytest.approx(10 * (0.02 + 0.001 * 2.28), rel=1e-6)
    assert S.substituted == 0 and SC in S.pulled
    models.delete_process(fut)
    # automatic: a dataset of the scenario itself is the scenario's, not today's dataset of the same name (premise
    # keeps ecoinvent's datasets, so every one has that counterpart)
    sc_elec = bd.get_node(database=SC, code="elec").id
    assert models.system_for(sc_elec).score({sc_elec: 1}, GWP) == pytest.approx(0.02 + 0.001 * 2.28, rel=1e-6)
    assert s.activity(sc_elec, GWP)["calculated_alone"] == SC
    with TestClient(app, base_url="http://127.0.0.1") as c:
        items = [{"project": TEST_PROJECT, "id": str(world), "amount": 2},
                 {"project": TEST_PROJECT, "id": str(world), "amount": 2, "background": [SC]},
                 {"project": TEST_PROJECT, "id": str(sc_elec), "amount": 1}]
        r = c.post("/api/compare", json={"items": items, "method": list(GWP)}).json()
        assert [x["score"] for x in r] == pytest.approx([2 * TODAY, 2 * Y2040, 0.02 + 0.001 * 2.28], rel=1e-6)
        assert r[2]["used"] == [SC]
        st = c.post("/api/background", json={"mode": "single", "databases": [SC]}).json()
        assert st["background"]["mode"] == "single" and st["background"]["substituted"] == 2
        assert c.post("/api/background", json={"mode": "single", "databases": [EI, SC]}).status_code == 400
        c.post("/api/background", json={"mode": "auto"})


def _wait(c, job, limit=300):
    for _ in range(limit):
        st = c.get("/api/import/status", params={"id": job["id"]}).json()["job"]
        if st["state"] != "läuft":
            return st
        time.sleep(1)
    raise AssertionError("job did not end")


def test_premise_job_with_stand_in(world, monkeypatch):
    monkeypatch.setenv("LCA_WRENCH_PREMISE_PYTHON", sys.executable)
    monkeypatch.setenv("LCA_WRENCH_PREMISE_PATH", str(Path(__file__).parent / "fake_premise"))
    scenarios.forget_constants()
    names = [scenarios.scenario_name(EI, "remind", "TEST-50", y) for y in (2030, 2050)]
    try:
        with TestClient(app, base_url="http://127.0.0.1") as c:
            o = c.get("/api/import/options").json()
            assert o["premise"]["ei_versions"] == ["3.10"] and [x["name"] for x in o["premise_sources"]] == [EI]
            body = {"name": TEST_PROJECT, "source": "premise", "source_db": EI, "model": "remind", "pathway": "TEST-50",
                    "years": [2050, 2030], "key": "x" * 44}
            assert c.post("/api/import/start", json={**body, "key": ""}).status_code == 400  # no key
            assert c.post("/api/import/start", json={**body, "pathway": "nope"}).status_code == 400
            st = _wait(c, c.post("/api/import/start", json=body).json())
            assert st["state"] == "fertig", st
            assert all(n in bd.databases and backgrounds.kind(n) == "scenario" for n in names)
            # only what was asked for goes into the metadata, not what premise added to it (a path broke the
            # database list: bw2data then leaves databases.json empty)
            assert bd.databases[names[0]]["lca_wrench"]["scenario"] == {"model": "remind", "pathway": "TEST-50",
                                                                       "year": 2030, "source": EI}
            listing = json.loads((Path(bd.projects.dir) / "databases.json").read_text())
            assert names[0] in listing and listing[names[0]]["scratch"].endswith("premise")
            # the scenario halves electricity's emissions: the model on it
            roles = models.roles()
            backgrounds.set_choice("single", [names[1]], roles)
            elec = 10 * (0.05 + 0.001 * 2.28)
            assert models.system().score({world: 1}, GWP) == pytest.approx(elec + 2.28 + 0.35, rel=1e-6)
            backgrounds.set_choice("auto", [], roles)
            # a failing scenario leaves nothing behind
            n0 = set(bd.databases)
            st = _wait(c, c.post("/api/import/start", json={**body, "pathway": "TEST-FAIL"}).json())
            assert st["state"] == "fehler" and "on purpose" in st["error"] and set(bd.databases) == n0
            # failing after the databases are written: they are removed again, rows too, the list stays readable
            late = [scenarios.scenario_name(EI, "remind", "TEST-60-LATE", y) for y in (2030, 2050)]
            st = _wait(c, c.post("/api/import/start", json={**body, "pathway": "TEST-60-LATE"}).json())
            assert st["state"] == "fehler" and "after writing" in st["error"], st
            assert set(bd.databases) == n0
            assert set(json.loads((Path(bd.projects.dir) / "databases.json").read_text())) == n0
            from bw2data.backends import ActivityDataset
            assert not ActivityDataset.select().where(ActivityDataset.database << late).count()
    finally:
        _drop(*names)
        scenarios.forget_constants()



def test_premise_offers_only_scenarios_in_its_archive(world, tmp_path, monkeypatch):
    """premise lists every pathway for every model, but its Zenodo archive has only some pairs (premise 2.5.2: no
    SSP2-Base at all, which failed with a 404). Offered are the pairs whose file is in the archive or on this computer."""
    pkg = tmp_path / "premise"
    (pkg / "iam").mkdir(parents=True)
    (pkg / "__init__.py").write_text("__version__ = (2, 5, 2)\n")
    (pkg / "utils.py").write_text(
        "def load_constants():\n"
        "    return {'SUPPORTED_EI_VERSIONS': ['3.10'], 'SUPPORTED_MODELS': ['remind', 'image', 'gcam'],\n"
        "            'SUPPORTED_PATHWAYS': ['SSP2-Base', 'SSP2-NPi', 'SSP2-M', 'SSP1-VLLO', 'SSP2-PkBudg500'],\n"
        "            'UNAVAILABLE_PATHWAYS': ['SSP2-PkBudg500']}\n")
    (pkg / "scenario_downloader.py").write_text(
        "ZENODO_IAM_SCENARIO_RECORD_ID = '123'\n"
        "def get_scenario_file_stems(model, pathway):\n"
        "    a, b = f'{model}_{pathway}', f\"{model}_{pathway.replace('-', '_')}\"\n"
        "    return (a, b) if model == 'image' and a != b else (a,)\n"
        "def get_scenario_url(model, pathway):\n"
        "    return f'https://zenodo.org/records/123/files/{get_scenario_file_stems(model, pathway)[-1]}.csv'\n")
    (pkg / "filesystem_constants.py").write_text(f"from pathlib import Path\nIAM_OUTPUT_DIR = Path({str(pkg / 'iam')!r})\n")
    (pkg / "iam" / "gcam_SSP2-Base.xlsx").write_text("")  # a scenario file of the user's own
    monkeypatch.setenv("LCA_WRENCH_PREMISE_PYTHON", sys.executable)
    monkeypatch.setenv("LCA_WRENCH_PREMISE_PATH", str(tmp_path))
    archive = {"remind_SSP2-NPi.csv", "remind_SSP1-VLLO.csv", "image_SSP2_M.csv", "image_SSP1_VLLO.csv",
               "image_SSP2-NPi.csv", "remind_SSP2-PkBudg500.csv"}  # image with hyphens: not premise's name for it
    monkeypatch.setattr(scenarios, "archive_files", lambda record: archive if record == "123" else None)
    scenarios.forget_constants()
    try:
        c = scenarios.constants()
        assert c["record"] == "123" and c["files"]["image"]["SSP2-M"] == "image_SSP2_M.csv"
        assert c["local"]["gcam"] == ["SSP2-Base"]
        assert scenarios.offered(c) == {"remind": ["SSP2-NPi", "SSP1-VLLO"], "image": ["SSP2-M", "SSP1-VLLO"],
                                        "gcam": ["SSP2-Base"]}
        with TestClient(app, base_url="http://127.0.0.1") as cl:
            o = cl.get("/api/import/options").json()
            assert o["premise_available"]["image"] == ["SSP2-M", "SSP1-VLLO"]
            body = {"name": TEST_PROJECT, "source": "premise", "source_db": EI, "model": "image", "pathway": "SSP2-Base",
                    "years": [2030], "key": "x" * 44}
            r = cl.post("/api/import/start", json=body)
            assert r.status_code == 400 and "SSP2-Base" in r.json()["detail"] and "SSP2-M, SSP1-VLLO" in r.json()["detail"]
        # archive not reachable: premise's own list, as before
        monkeypatch.setattr(scenarios, "archive_files", lambda record: None)
        assert scenarios.offered(c) is None
    finally:
        scenarios.forget_constants()
    err = "HTTPError: 404 Client Error: NOT FOUND for url: https://zenodo.org/records/22227290/files/image_SSP2_Base.csv"
    assert "image_SSP2_Base.csv" in scenarios.explain(err) and "Zenodo" in scenarios.explain(err)
    assert scenarios.explain("RuntimeError: other") == "RuntimeError: other"



# real UUIDs, matched in the flow mapping (lca_wrench/data/flowmaps): fossil CO2 and water, both to air
EI_CO2, EF_CO2 = "349b29d1-3e58-4c66-98b9-9d1a076efd2e", "08a91e70-3ddc-11dd-923d-0050c2490048"
EI_H2O, EF_H2O = "075e433b-4be4-448e-9510-9a5029c1ce94", "0342f5e5-b53e-4cec-9e67-fb197f24fff0"


def test_flow_mapping_fills_factors_across_flow_lists(world):
    """ecoinvent's methods are on its flow list, BAFU 2026 on EF 3.1's: on the other list a method finds no factor
    and gives 0. Through the flow mapping it gets the matched flows' factors, only for checked kinds of impact."""
    bd.projects.set_current(TEST_PROJECT)
    EIB, EFB, EIP, EFP = "Test flows ecoinvent", "Test flows EF", "Test process ecoinvent", "Test process EF"
    flow = lambda name, unit: {"name": name, "unit": unit, "type": "emission", "categories": ("air",)}  # noqa: E731
    GWP_EI, WATER_EI, GWP_EF = ("Test map", "climate change", "GWP100"), ("Test map", "water use", "m3"), ("Test EF", "Climate change")
    try:
        bd.Database(EIB).write({(EIB, EI_CO2): flow("Carbon dioxide, fossil", "kilogram"), (EIB, EI_H2O): flow("Water", "cubic meter")})
        bd.Database(EFB).write({(EFB, EF_CO2): flow("carbon dioxide (fossil)", "kilogram"), (EFB, EF_H2O): flow("Water", "cubic meter")})
        bd.Database(EIP).write(_proc(EIP, "p", "ei thing", "ei thing", "CH", "kilogram", bio=[((EIB, EI_CO2), 1.0), ((EIB, EI_H2O), 1.0)]))
        bd.Database(EFP).write(_proc(EFP, "p", "ef thing", "ef thing", "CH", "kilogram", bio=[((EFB, EF_CO2), 2.0), ((EFB, EF_H2O), 3.0)]))
        for m, data in ((GWP_EI, [((EIB, EI_CO2), 1.0)]), (WATER_EI, [((EIB, EI_H2O), 10.0)]), (GWP_EF, [((EFB, EF_CO2), 1.0)])):
            bd.Method(m).register(unit="x")
            bd.Method(m).write(data)
        engine.bump_background(TEST_PROJECT)
        assert (EIB, EFB) in [tuple(link[:2]) for link in flowmap.index().links]
        ei, ef = bd.get_node(database=EIP, code="p").id, bd.get_node(database=EFP, code="p").id
        assert models.system_for(ef).score({ef: 1}, GWP_EI) == pytest.approx(2.0)  # ecoinvent's factor on the EF flow
        assert models.system_for(ei).score({ei: 1}, GWP_EF) == pytest.approx(1.0)  # EF's factor on the ecoinvent flow
        assert models.system_for(ef).score({ef: 1}, WATER_EI) == 0.0  # water: never through the mapping
        assert models.system_for(ei).score({ei: 1}, GWP_EI) == pytest.approx(1.0)  # its own factors as they are
        with TestClient(app, base_url="http://127.0.0.1") as c:
            items = [{"project": TEST_PROJECT, "id": str(ef), "amount": 1}, {"project": TEST_PROJECT, "id": str(ei), "amount": 1}]
            r = c.post("/api/compare", json={"items": items, "method": list(GWP_EI)}).json()
            assert [x["coverage"] for x in r] == ["mapped", "native"] and r[0]["score"] == pytest.approx(2.0)
            cov = {tuple(m): how for m, how in r[0]["covering"]}
            assert cov[GWP_EI] == "mapped" and cov[GWP_EF] == "native" and WATER_EI not in cov
            r = c.post("/api/compare", json={"items": items, "method": list(WATER_EI)}).json()
            assert r[0]["coverage"] == "missing" and r[0]["missing"] == [EFB] and r[1]["coverage"] == "native"
            assert s.verify([{"id": ef, "amount": 1}], [GWP_EI, GWP_EF])["ok"]  # bw2calc plus the same factors
            draws = montecarlo.run_chunk(TEST_PROJECT, [(ef, 1.0)], [GWP_EI], 2, 1)  # no uncertainty: all alike
            assert draws[:, 0, 0] == pytest.approx([2.0, 2.0])
            assert c.get("/api/state").json()["flowmap"]["enabled"] is True
            assert c.post("/api/flowmap", json={"enabled": False}).json()["enabled"] is False
            r = c.post("/api/compare", json={"items": items, "method": list(GWP_EI)}).json()
            assert r[0]["coverage"] == "missing" and r[0]["score"] == 0.0
    finally:
        flowmap.set_enabled(True)
        for m in (GWP_EI, WATER_EI, GWP_EF):
            if m in bd.methods:
                bd.Method(m).deregister()
        _drop(EFP, EIP, EFB, EIB)
        engine.bump_background(TEST_PROJECT)


def test_flow_mapping_missing_file_does_not_stop_calculations(world, monkeypatch, tmp_path, caplog):
    """A new version copied over an older folder lost data/flowmaps on one PC: opening the default project then
    failed in engine.cvec. Without the file the mapping is empty and logged; methods and the index still work."""
    bd.projects.set_current(TEST_PROJECT)
    monkeypatch.setattr(flowmap, "MAPPING", tmp_path / "missing.json.gz")
    monkeypatch.setattr(flowmap, "_pairs", None)
    flowmap._index.clear()
    flowmap._dbs.clear()
    flowmap._added.clear()
    try:
        with caplog.at_level("ERROR", logger="lca_wrench"):
            assert flowmap.pairs() == []
        assert "Flow mapping not available" in caplog.text
        assert flowmap.index().links == []
        m = next(iter(bd.methods))
        assert flowmap.fills(m) == [] and flowmap.addition(m, [1, 2, 3]) is None
    finally:
        flowmap._pairs = None
        flowmap._index.clear()
        flowmap._dbs.clear()
        flowmap._added.clear()


def _exio_files(root: Path) -> Path:
    """A 2-region, 2-sector EXIOBASE in its own file format (as on Zenodo, unpacked)."""
    d = root / "IOT_2022_pxp"
    (d / "satellite").mkdir(parents=True)
    regions, sectors = ["AT", "AT", "DE", "DE"], ["Coal power (01)", "Services (02)", "Coal power (01)", "Services (02)"]
    A = [[0.05, 0.02, 0.01, 0.0], [0.10, 0.04, 0.0, 0.03], [0.02, 0.0, 0.06, 0.01], [0.0, 0.05, 0.08, 0.02]]
    lines = ["region\tsector\t" + "\t".join(regions), "region\tsector\t" + "\t".join(sectors)]
    lines += [f"{regions[i]}\t{sectors[i]}\t" + "\t".join(str(v) for v in A[i]) for i in range(4)]
    (d / "A.txt").write_text("\n".join(lines) + "\n")
    (d / "unit.txt").write_text("region\tsector\tunit\n" + "".join(f"{r}\t{n}\tM.EUR\n" for r, n in zip(regions, sectors)))
    (d / "x.txt").write_text("region\tsector\tindout\n" + "".join(f"{r}\t{n}\t1000\n" for r, n in zip(regions, sectors)))
    S = {"CO2 - combustion - air": [9e5, 1e4, 7e5, 2e4], "CH4 - combustion - air": [100, 10, 80, 5],
         "PFC - air": [0, 50, 0, 40], "Unknown stressor X": [1, 1, 1, 1]}
    lines = ["stressor\t" + "\t".join(regions), "stressor\t" + "\t".join(sectors)]
    lines += [f"{k}\t" + "\t".join(str(v) for v in vals) for k, vals in S.items()]
    (d / "satellite" / "S.txt").write_text("\n".join(lines) + "\n")
    (d / "satellite" / "unit.txt").write_text("stressor\tunit\n" + "".join(
        f"{k}\t{'kg CO2-eq' if k == 'PFC - air' else 'kg'}\n" for k in S))
    return d, np.array(A), S



def test_repair_rebuilds_an_empty_database_list(world, tmp_path):
    """A failed write leaves databases.json empty (bw2data swaps the file in anyway) and the project cannot be opened.
    repair.py rebuilds the list from the data: backends (EXIOBASE an IO table), dependencies, LCA Wrench's tags."""
    bd.projects.set_current(TEST_PROJECT)
    folder, _, _ = _exio_files(tmp_path)
    name = "EXIOBASE repair"
    gwp = bd.Method(GWP).load()
    listing = Path(bd.projects.dir) / "databases.json"
    try:
        exiobase.write(folder, name, BIO)
        engine.bump_background(TEST_PROJECT)
        model_score = models.system().score({world: 1}, GWP)
        serv = next(a for a in bd.Database(name) if a["name"] == "Services" and a["location"] == "AT")
        io_score = models.system_for(serv.id).score({serv.id: 1}, GWP)
        before = {n: (m.get("backend"), sorted(m.get("depends") or [])) for n, m in bd.databases.items()}
        listing.write_bytes(b"")
        with pytest.raises(ValueError):
            bd.projects.set_current(TEST_PROJECT)
        # the app says what is wrong and how to repair it, and does not start on it
        with pytest.raises(ValueError, match="lca_wrench.repair"):
            s.set_project(TEST_PROJECT)
        assert s.pick_start_project(TEST_PROJECT) != TEST_PROJECT
        from lca_wrench import repair

        with pytest.raises(SystemExit):  # nothing written without --write, and only into a broken list
            repair.rebuild(TEST_PROJECT, write=True, drop=("nope",), out=lambda *a: None)
        assert listing.read_bytes() == b""
        repair.rebuild(TEST_PROJECT, write=True, out=lambda *a: None)
        after = {n: (m.get("backend"), sorted(m.get("depends") or [])) for n, m in bd.databases.items()}
        assert after == before and before[name][0] == "iotable"
        assert backgrounds.kind(name) == "mrio" and backgrounds.kind(SC) == "scenario"
        engine.bump_background(TEST_PROJECT)
        assert models.system().score({world: 1}, GWP) == pytest.approx(model_score, rel=1e-9)
        assert models.system_for(serv.id).score({serv.id: 1}, GWP) == pytest.approx(io_score, rel=1e-9)
        assert list(listing.parent.glob("databases.json.broken-*"))
        with pytest.raises(SystemExit):  # a readable list is never overwritten
            repair.rebuild(TEST_PROJECT, write=True, out=lambda *a: None)
    finally:
        for f in listing.parent.glob("databases.json.broken-*"):
            f.unlink()
        if repair_needed := not listing.read_bytes():
            listing.write_text("{}")
        bd.projects.set_current(TEST_PROJECT)
        _drop(name)
        bd.Method(GWP).write(gwp)
        engine.bump_background(TEST_PROJECT)
        assert not repair_needed


def test_exiobase_import_dense_solver_and_hybrid(world, tmp_path):
    bd.projects.set_current(TEST_PROJECT)
    folder, A, S = _exio_files(tmp_path)
    name = "EXIOBASE test"
    before = bd.Method(GWP).load()
    try:
        info = exiobase.write(folder, name, BIO)
        assert info["sectors"] == 4 and info["left_out"] == ["Unknown stressor X"] and info["patched_methods"] >= 1
        assert backgrounds.kind(name) == "mrio" and models.roles()[name] == "background"
        engine.bump_background(TEST_PROJECT)
        roles = models.roles()
        backgrounds.set_choice("combined", [EI, name], roles)
        Sy = models.system()
        assert sorted(Sy.bg.solver.kinds) == ["dense", "dense"]
        serv = next(a for a in bd.Database(name) if a["name"] == "Services" and a["location"] == "AT")
        # by hand: h = c · S · (I - A)^-1 e  (CO2 1, CH4 28, PFC 1 after the patch)
        c = np.array([1.0, 28.0, 1.0])
        Sm = np.array([S["CO2 - combustion - air"], S["CH4 - combustion - air"], S["PFC - air"]])
        x = np.linalg.solve(np.eye(4) - A, np.eye(4)[1])
        want = float(c @ Sm @ x)
        assert Sy.score({serv.id: 1}, GWP) == pytest.approx(want, rel=1e-6)
        lca = bc.LCA({serv: 1}, GWP)
        lca.lci()
        lca.lcia()
        assert lca.score == pytest.approx(want, rel=1e-6)
        # before any model uses the table: search finds its sectors (also by "money"), and a sector outside the chosen
        # background is calculated on its table alone (data sheet, result)
        backgrounds.set_choice("auto", [], roles)
        assert name not in models.system().bg.dbs
        hits = {(h["database"], h["name"], h["location"]) for h in s.search("Services", unit="currency")}
        assert {(name, "Services", "AT"), (name, "Services", "DE")} <= hits
        sheet = s.activity(serv.id, GWP)
        assert sheet["calculated_alone"] == name and sheet["score"] == pytest.approx(want, rel=1e-6)
        assert sheet["technosphere"] and all(e["exchange"] is None for e in sheet["technosphere"])
        assert s.calculate(serv.id, 1.0, GWP)["score"] == pytest.approx(want, rel=1e-6)
        assert s.verify([{"id": serv.id, "amount": 1.0}], [GWP])["ok"]
        backgrounds.set_choice("combined", [EI, name], roles)
        assert s.activity(serv.id, GWP)["calculated_alone"] is None
        # hybrid: a model buying 0.001 million € of Austrian services and 1 kWh of electricity
        hyb = int(models.create_process(MODEL, "Hybrid", "unit", "CH"))
        models.add_exchange(hyb, serv.id, 0.001)
        models.add_exchange(hyb, bd.get_node(database=EI, code="elec").id, 1.0)
        assert models.system().score({hyb: 1}, GWP) == pytest.approx(0.001 * want + 0.10228, rel=1e-6)
        assert "currency" in s.search_options()["units"]
        # removing: refused while the model buys from it, and for databases LCA Wrench did not add
        with pytest.raises(ValueError):
            s.remove_background(name)
        with pytest.raises(ValueError):
            s.remove_background(EI)
        models.delete_process(hyb)
        backgrounds.set_choice("combined", [EI, name], roles)
        processed = Path(bd.Database(name).filepath_processed())
        st = s.remove_background(name)
        assert name not in bd.databases and name + " biosphere" not in bd.databases and not processed.exists()
        assert sorted(bd.Method(GWP).load()) == sorted(before)  # the factors the import added are gone again
        assert st["background"]["databases"] == [EI] and name not in st["background"]["used"]
        # databases from elsewhere (BAFU, ecoinvent) are never removable; SC only while it carries LCA Wrench's tag
        assert all(o["removable"] == backgrounds.removable(o["name"]) for o in st["background"]["options"])
        assert not any(o["removable"] for o in st["background"]["options"] if o["name"] != SC)
        backgrounds.set_choice("auto", [], models.roles())
        # the same as a job in its own process
        with TestClient(app, base_url="http://127.0.0.1") as cl:
            body = {"name": TEST_PROJECT, "source": "exiobase", "path": str(folder), "biosphere": BIO, "db_name": "EXIOBASE job"}
            assert cl.post("/api/import/start", json={**body, "biosphere": "nope"}).status_code == 400
            st = _wait(cl, cl.post("/api/import/start", json=body).json())
            assert st["state"] == "fertig", st
            assert st["result"]["sectors"] == 4 and "EXIOBASE job" in bd.databases
    finally:
        bd.Method(GWP).write(before)
        backgrounds.set_choice("auto", [], models.roles())
        _drop(name, name + " biosphere", "EXIOBASE job", "EXIOBASE job biosphere")
        os.environ.pop("LCA_WRENCH_PREMISE_PYTHON", None)


def test_other_database_scores_a_scenario_not_in_the_calculation(world):
    """"Other database" with a premise scenario: the scenario is not part of the calculation (automatic background),
    its datasets are scored on its own database, not as 0."""
    from lca_wrench import crosswalk as cw

    bd.projects.set_current(TEST_PROJECT)
    backgrounds.set_choice("auto", [], models.roles())
    assert SC not in models.system().bg.dbs
    res = cw.compare(world, 1.0, GWP, TEST_PROJECT, SC)
    rows = {r["code"]: r for r in res["rows"]}
    elec_2040 = 0.02 + 0.001 * 2.28
    assert rows["elec"]["origin"] == "code" and rows["elec"]["score_b"] == pytest.approx(10 * elec_2040, rel=1e-5)
    assert rows["steel"]["match"]["code"] == "steel-2040" and rows["steel"]["score_b"] == pytest.approx(2.28, rel=1e-5)
    assert res["b"]["score"] == pytest.approx(10 * elec_2040 + 2.28, rel=1e-5)  # heat has no counterpart there
    # one level down: the scenario's electricity, with its own inputs
    tr = cw.trace(bd.get_node(database=EI, code="elec").id, "elec", 10.0, 10.0, GWP, TEST_PROJECT, SC, list(GWP))
    assert tr["b"]["score"] == pytest.approx(10 * elec_2040, rel=1e-5)


def test_other_database_exiobase_proxy_sectors(world, tmp_path):
    """"Other database" with EXIOBASE: a dataset gets its proxy sector through its ISIC class (Peng & Pfister 2023)
    in the region of its location, and its amount in money through its price; without a price it waits for one."""
    from lca_wrench import crosswalk as cw
    from lca_wrench import sectors

    bd.projects.set_current(TEST_PROJECT)
    folder, _, _ = _exio_files(tmp_path)
    exio, src = "EXIOBASE proxy", "Test ISIC db"
    gwp = bd.Method(GWP).load()
    isic = [("ISIC rev.4 ecoinvent", "3510:Electric power generation, transmission and distribution")]
    try:
        exiobase.write(folder, exio, BIO)
        _drop(src)
        db = bd.Database(src)
        db.register()
        db.write({
            (src, "coal-de"): {"name": "electricity production, hard coal", "reference product": "electricity, high voltage",
                               "location": "DE", "unit": "kilowatt hour", "type": "process", "classifications": isic,
                               "exchanges": [{"input": (src, "coal-de"), "amount": 1, "type": "production",
                                              "properties": {"price": {"amount": 0.08, "unit": "EUR2005"}}},
                                             {"input": CO2, "amount": 1.0, "type": "biosphere"}]},
            (src, "coal-at"): {"name": "electricity production, hard coal", "reference product": "electricity, high voltage",
                               "location": "AT", "unit": "kilowatt hour", "type": "process", "classifications": isic,
                               "exchanges": [{"input": (src, "coal-at"), "amount": 1, "type": "production"},
                                             {"input": CO2, "amount": 1.0, "type": "biosphere"}]},
        })
        engine.bump_background(TEST_PROJECT)
        backgrounds.set_choice("auto", [], models.roles())
        assert sectors.regions_for("DE") == ["DE"] and "DE" in sectors.regions_for("RER")
        assert sectors.sectors_for_isic("35101") == sectors.sectors_for_isic("3510")  # coarsened
        unit = engine.alone(exio)
        coal = {a["location"]: a.id for a in bd.Database(exio) if a["name"] == "Coal power"}
        s_coal_de = unit.score({coal["DE"]: 1}, GWP)
        assert s_coal_de > 0

        node = bd.get_node(database=src, code="coal-de").id
        res = cw.compare(node, 1000.0, GWP, TEST_PROJECT, exio)
        (row,) = res["rows"]
        assert row["proxy"] == "isic" and row["origin"] == "auto" and row["quality"] == "good"
        assert (row["match"]["name"], row["match"]["location"]) == ("Coal power", "DE")
        assert row["match"]["factor"] == pytest.approx(0.08e-6) and row["price"] == pytest.approx(0.08)
        assert row["score_b"] == pytest.approx(1000 * 0.08e-6 * s_coal_de, rel=1e-6)

        # no price in the dataset: the sector is shown, the score waits for the user's price
        node_at = bd.get_node(database=src, code="coal-at").id
        (row,) = cw.compare(node_at, 1000.0, GWP, TEST_PROJECT, exio)["rows"]
        assert row["match"] is None and row["problem"] == "price" and row["pending"]["location"] == "AT"
        assert "score_b" not in row
        with pytest.raises(ValueError):
            cw.choose(src, "coal-at", exio, row["pending"]["code"], price=0)
        cw.choose(src, "coal-at", exio, row["pending"]["code"], price=0.1)
        (row,) = cw.compare(node_at, 1000.0, GWP, TEST_PROJECT, exio)["rows"]
        s_coal_at = unit.score({coal["AT"]: 1}, GWP)
        assert row["origin"] == "user" and row["score_b"] == pytest.approx(1000 * 0.1e-6 * s_coal_at, rel=1e-6)
        exported = cw.export_mapping(src, exio)["replace"]
        assert exported[0]["conversion_factor"] == pytest.approx(0.1e-6)
        # search: the sectors in money can be picked for a dataset in kWh
        hits = cw.search(TEST_PROJECT, exio, "coal power", unit="kilowatt hour")
        assert hits and all(h["convertible"] for h in hits)
    finally:
        reg = models.registry.load()
        reg.get("matches", {}).pop(cw._pair(src, exio), None)
        models.registry.save(reg)
        bd.projects.set_current(TEST_PROJECT)
        _drop(src, exio, exio + " biosphere")
        bd.Method(GWP).write(gwp)
        engine.bump_background(TEST_PROJECT)


def _exio_named(root: Path, system: str, names: list[str], volumes: dict | None = None) -> Path:
    """An EXIOBASE table in its file format with real sector names (industries or products), regions CH and DE."""
    d = root / f"IOT_2022_{system}"
    (d / "satellite").mkdir(parents=True)
    regions = [r for r in ("CH", "DE") for _ in names]
    sectors = names * 2
    n = len(sectors)
    A = [[0.01 if i != j else 0.02 for j in range(n)] for i in range(n)]
    lines = ["region\tsector\t" + "\t".join(regions), "region\tsector\t" + "\t".join(sectors)]
    lines += [f"{regions[i]}\t{sectors[i]}\t" + "\t".join(str(v) for v in A[i]) for i in range(n)]
    (d / "A.txt").write_text("\n".join(lines) + "\n")
    (d / "unit.txt").write_text("region\tsector\tunit\n" + "".join(f"{r}\t{s}\tM.EUR\n" for r, s in zip(regions, sectors)))
    vol = volumes or {}
    (d / "x.txt").write_text("region\tsector\tindout\n" + "".join(
        f"{r}\t{s}\t{vol.get((r, s), 1000)}\n" for r, s in zip(regions, sectors)))
    co2 = [1e5 * (k + 1) for k in range(n)]
    (d / "satellite" / "S.txt").write_text("stressor\t" + "\t".join(regions) + "\nstressor\t" + "\t".join(sectors)
                                           + "\nCO2 - combustion - air\t" + "\t".join(str(v) for v in co2) + "\n")
    (d / "satellite" / "unit.txt").write_text("stressor\tunit\nCO2 - combustion - air\tkg\n")
    return d


def test_exiobase_proxies_industries_and_products_for_ecoinvent_and_bafu(world, tmp_path):
    """Both EXIOBASE tables: industries (ixi) and products (pxp), recognised by their names. Datasets with an ISIC
    class (ecoinvent) and without, with a category (BAFU 2025) or a sector (BAFU 2026), get their proxy."""
    from lca_wrench import crosswalk as cw
    from lca_wrench import sectors

    bd.projects.set_current(TEST_PROJECT)
    gwp = bd.Method(GWP).load()
    ixi = ["Production of electricity by coal", "Petroleum Refinery", "Manufacture of gas; distribution of gaseous fuels "
           "through mains", "Other land transport", "Chemicals nec"]
    pxp = ["Electricity by coal", "Gas/Diesel Oil", "Motor Gasoline", "Distribution services of gaseous fuels through mains",
           "Other land transportation services", "Chemicals nec"]
    src = "Test proxy sources"

    def ds(code, name, loc, unit, **extra):
        return {(src, code): {"name": name, "reference product": name, "location": loc, "unit": unit,
                              "type": "process", **extra,
                              "exchanges": [{"input": (src, code), "amount": 1, "type": "production"}]}}

    sources = {}
    # ecoinvent: ISIC class (refined petroleum products), narrowed by name
    sources.update(ds("ei-diesel", "market for diesel, low-sulfur", "DE", "kilogram",
                      classifications=[("ISIC rev.4 ecoinvent", "1920:Manufacture of refined petroleum products")]))
    # BAFU 2025: EcoSpold01 category, no ISIC
    sources.update(ds("bafu-coal", "Electricity, hard coal, at power plant", "CH", "kilowatt hour",
                      categories=["electricity by fuel", "coal"]))
    sources.update(ds("bafu-petrol", "Petrol, unleaded, at regional storage", "CH", "kilogram",
                      categories=["oil", "fuels"]))
    sources.update(ds("bafu-lorry", "Transport, freight, lorry 16-32 metric ton, EURO5", "RER", "ton kilometer",
                      categories=["transport systems", "road"]))
    # BAFU 2026: a sector only
    sources.update(ds("b26-gas", "Natural gas, low pressure, at consumer", "CH", "megajoule", sector="energy"))
    sources.update(ds("b26-edta", "EDTA, ethylenediaminetetraacetic acid, at plant", "CH", "kilogram", sector="chemicals"))
    want = {  # code -> (industry table, product table)
        "ei-diesel": ("Petroleum Refinery", "Gas/Diesel Oil"),
        "bafu-coal": ("Production of electricity by coal", "Electricity by coal"),
        "bafu-petrol": ("Petroleum Refinery", "Motor Gasoline"),
        "bafu-lorry": ("Other land transport", "Other land transportation services"),
        "b26-gas": ("Manufacture of gas; distribution of gaseous fuels through mains",
                    "Distribution services of gaseous fuels through mains"),
        "b26-edta": ("Chemicals nec", "Chemicals nec"),
    }
    how = {"ei-diesel": "isic", "bafu-coal": "rule", "bafu-petrol": "rule", "bafu-lorry": "rule", "b26-gas": "rule",
           "b26-edta": "category"}
    names = {"ixi": ixi, "pxp": pxp}
    made = []
    try:
        _drop(src)
        db = bd.Database(src)
        db.register()
        db.write(sources)
        info = sectors.source_info([bd.get_node(database=src, code=c).id for c in want])
        for k, system in enumerate(("ixi", "pxp")):
            name = f"EXIOBASE {system} proxy"
            # RER covers CH and DE: the region with the larger production of the sector is taken
            big = {("DE", "Other land transport"): 5000, ("DE", "Other land transportation services"): 5000}
            exiobase.write(_exio_named(tmp_path / system, system, names[system], big), name, BIO)
            made.append(name)
            engine.bump_background(TEST_PROJECT)
            index = cw._index(TEST_PROJECT, name)
            assert index.sectors.system == system
            for code, (ind, prod) in want.items():
                node = bd.get_node(database=src, code=code)
                extra = info[node.id]
                sugg, found = index.sectors.propose(node["name"], node["reference product"], node["location"],
                                                    extra["isic"], extra["category"])
                assert found == how[code], (system, code, found)
                top = sugg[0][1]
                assert top["name"] == (ind, prod)[k], (system, code, top["name"])
                assert top["location"] == ("DE" if node["location"] in ("DE", "RER") else "CH"), (system, code)
                assert (sugg[0][0] >= 0.6) == (found != "category"), (system, code, sugg[0][0])
            # end to end: the comparison shows the proxy, waiting for a price (these datasets have none)
            node = bd.get_node(database=src, code="ei-diesel")
            (row,) = cw.compare(node.id, 1.0, GWP, TEST_PROJECT, name)["rows"]
            assert row["proxy"] == "isic" and row["problem"] == "price"
            assert row["pending"]["name"] == want["ei-diesel"][k] and row["pending"]["location"] == "DE"
    finally:
        bd.projects.set_current(TEST_PROJECT)
        _drop(src, *made, *[m + " biosphere" for m in made])
        bd.Method(GWP).write(gwp)
        engine.bump_background(TEST_PROJECT)
