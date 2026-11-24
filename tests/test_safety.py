"""Safety for real projects on someone else's computer (e.g. ecoinvent in the Activity Browser 3).

- Nothing is opened on its own; a project Brightway would convert on opening is opened only when asked, or as a
  test copy (copied file by file, original untouched).
- Databases not made in LCA Wrench are calculated, but changed only in a copy of the project.
- Undo never overwrites a change another program made in the meantime.
- Other websites in the browser cannot send requests; a project deleted from outside is not created again.
- A project left keeps no file open (Windows cannot delete open files).
"""

import os
import pickle
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bw2data as bd
import pytest
from bw2data.backends.proxies import Exchange
from bw2data.backends.schema import ExchangeDataset
from bw2data.parameters import DatabaseParameter, ProjectParameter
from bw2data.project import ProjectDataset
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import models, params, registry
from lca_wrench import service as s
from lca_wrench.api import app

PREFIX = "lca-wrench-test-safety"
FOREIGN = "lca-wrench-test-fremd"  # a database made elsewhere (Activity Browser), linked to the background


def _dir(name: str) -> Path:
    return Path(bd.projects._project_dir(ProjectDataset.get(ProjectDataset.name == name)))


def _files(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_mtime_ns, p.stat().st_size) for p in d.rglob("*")
            if p.is_file() and not p.name.endswith(("-wal", "-shm"))}


def _cleanup():
    bd.projects.set_current(TEST_PROJECT)
    for name in [p.name for p in bd.projects if p.name.startswith(PREFIX)]:
        bd.projects.delete_project(name, delete_dir=True)


def _electricity() -> int:
    return int([h for h in s.search("electricity low voltage", "CH") if h["unit"] == "kWh"][0]["id"])


@pytest.fixture()
def outdated():
    """A copy of the test project as an older Brightway 2.5 left it: the 4.7 update not yet applied."""
    _cleanup()
    name = f"{PREFIX}-alt"
    bd.projects.copy_project(name, switch=False)
    f = _dir(name) / "preferences.pickle"
    prefs = pickle.loads(f.read_bytes())
    prefs["updates"].pop("4.7 database dependencies in datapackage")
    f.write_bytes(pickle.dumps(prefs, protocol=4))
    yield name
    _cleanup()


def test_outdated_project_is_opened_only_when_asked(outdated, monkeypatch):
    monkeypatch.setattr(s, "TEST_PROJECT_PREFIX", "nicht-ausblenden")  # test projects are hidden from the list otherwise
    assert s.pending_updates(outdated) == ["4.7 database dependencies in datapackage"]
    assert s.pending_updates(TEST_PROJECT) == []
    before = _files(_dir(outdated))
    with pytest.raises(ValueError, match="Testkopie"):
        s.set_project(outdated)
    assert bd.projects.current == TEST_PROJECT
    assert next(p for p in s.state()["projects"] if p["name"] == outdated)["rebuild"] is True
    # never as the start project, never visited for a comparison
    reg = registry.load()
    reg["last_project"] = outdated
    registry.save(reg)
    assert s.pick_start_project(None) != outdated
    out = s.compare([{"project": outdated, "id": str(_electricity()), "amount": 1.0}], s.CLIMATE_METHOD)
    assert "Brightway baut" in out[0]["error"] and bd.projects.current == TEST_PROJECT
    with pytest.raises(ValueError, match="Brightway baut"):
        s.visit(outdated)
    assert _files(_dir(outdated)) == before and s.pending_updates(outdated)

    # asked for explicitly: Brightway applies its update, the project opens
    s.set_project(outdated, rebuild=True)
    assert bd.projects.current == outdated and s.project_open() and s.pending_updates(outdated) == []


def test_test_copy_leaves_the_original_as_it_is(outdated):
    before = _files(_dir(outdated))
    expected = s.unit_score(_electricity(), s.CLIMATE_METHOD)

    new = s.copy_project_files(outdated)

    assert new == f"{outdated} (LCA Wrench)" and bd.projects.current == new and s.project_open()
    assert s.pending_updates(new) == [] and registry.load()["testcopies"][new]["original"] == outdated
    assert s.unit_score(_electricity(), s.CLIMATE_METHOD) == pytest.approx(expected, rel=1e-9)
    st = s.state()
    assert st["is_testcopy"] and st["original"] == outdated and not st["is_copy"]
    # the original: not opened, not converted, not a single file touched
    assert _files(_dir(outdated)) == before and s.pending_updates(outdated)


@pytest.fixture()
def foreign():
    """A database LCA Wrench did not make (as in the Activity Browser), using background data and a parameter."""
    bd.projects.set_current(TEST_PROJECT)
    if FOREIGN in bd.databases:
        del bd.databases[FOREIGN]
    el = bd.get_node(id=_electricity())
    db = bd.Database(FOREIGN)
    db.write({(FOREIGN, "lampe"): {"name": "Lampe", "unit": "unit", "location": "CH", "type": "process",
                                    "reference product": "Lampe",
                                    "exchanges": [{"input": (FOREIGN, "lampe"), "amount": 1, "type": "production"},
                                                  {"input": el.key, "amount": 2.5, "type": "technosphere"}]}})
    DatabaseParameter.create(database=FOREIGN, name="watt", amount=10)
    yield FOREIGN
    bd.projects.set_current(TEST_PROJECT)
    reg = registry.load()
    reg.get("testcopies", {}).pop(TEST_PROJECT, None)
    reg.get("journal", {}).pop(TEST_PROJECT, None)
    registry.save(reg)
    DatabaseParameter.delete().where(DatabaseParameter.database == FOREIGN).execute()
    if FOREIGN in bd.databases:
        del bd.databases[FOREIGN]


def test_foreign_database_is_calculated_but_not_changed(foreign):
    lampe = bd.get_node(database=foreign, code="lampe")
    exc = next(e for e in lampe.technosphere())
    assert models.roles()[foreign] == "model" and foreign not in models.writable_databases()
    st = s.state()
    assert next(d for d in st["databases"] if d["name"] == foreign)["writable"] is False
    assert s.unit_score(lampe.id, s.CLIMATE_METHOD) == pytest.approx(2.5 * s.unit_score(_electricity(), s.CLIMATE_METHOD), rel=1e-9)
    detail = models.process_detail(lampe.id, s.CLIMATE_METHOD)
    assert detail["editable"] is False

    for attempt in (lambda: s.edit_exchange(exc._document.id, 3.0), lambda: models.delete_database(foreign),
                    lambda: models.create_process(foreign, "Neu"), lambda: models.delete_exchange(exc._document.id),
                    lambda: params.set_parameter("project", "p_neu", "1")):
        with pytest.raises(models.ReadOnlyError, match="nicht in LCA Wrench angelegt|Testkopie"):
            attempt()
    assert foreign in bd.databases and float(Exchange(ExchangeDataset.get_by_id(exc._document.id))["amount"]) == 2.5

    # in a copy made by LCA Wrench everything may be changed
    reg = registry.load()
    reg.setdefault("testcopies", {})[TEST_PROJECT] = {"original": "x"}
    registry.save(reg)
    assert foreign in models.writable_databases()
    s.edit_exchange(exc._document.id, 3.0)
    assert float(Exchange(ExchangeDataset.get_by_id(exc._document.id))["amount"]) == 3.0
    models.undo()
    assert float(Exchange(ExchangeDataset.get_by_id(exc._document.id))["amount"]) == 2.5


@pytest.fixture()
def model():
    bd.projects.set_current(TEST_PROJECT)
    name = "lca-wrench-test-undo"
    if name in bd.databases:
        models.delete_database(name)
    models.create_database(name)
    pid = models.create_process(name, "Tisch")
    xid = int(models.add_exchange(pid, _electricity(), 2.0))
    yield name, int(pid), xid
    bd.projects.set_current(TEST_PROJECT)
    if name in bd.databases:
        models.delete_database(name)
    reg = registry.load()
    reg.get("journal", {}).pop(TEST_PROJECT, None)
    registry.save(reg)


def _amount(xid: int) -> float:
    return float(Exchange(ExchangeDataset.get_by_id(xid))["amount"])


def test_undo_never_overwrites_a_change_from_outside(model):
    _, pid, xid = model
    models.update_exchange(xid, amount=3.0)
    models.update_exchange(xid, amount=4.0)
    # another program (Activity Browser) changes the same amount
    exc = Exchange(ExchangeDataset.get_by_id(xid))
    exc["amount"] = 7.0
    exc.save()
    n = len(models.journal())
    with pytest.raises(models.UndoConflict, match="nicht rückgängig"):
        models.undo()
    assert _amount(xid) == 7.0 and models.journal() == []  # nothing overwritten, no old step left to do it later
    assert n == 4


def test_undo_stops_at_a_conflict_and_keeps_what_was_undone(model):
    _, pid, xid = model
    models.update_exchange(xid, amount=3.0)        # step 2 (0: model, 1: process, 2: input added ... see journal)
    models.update_process(pid, {"name": "Tisch, neu"})
    # outside: the process is renamed again, the amount stays
    act = bd.get_node(id=pid)
    act["name"] = "Tisch (AB)"
    act.save()
    models.update_exchange(xid, amount=5.0)
    j = models.journal()
    first = next(e["n"] for e in j if "3" in e["label"] and "2" in e["label"])
    with pytest.raises(models.UndoConflict):
        models.undo(first)  # amount 5 → 3 works, the rename conflicts
    assert _amount(xid) == 3.0 and bd.get_node(id=pid)["name"] == "Tisch (AB)"
    assert models.journal() == []
    models.update_exchange(xid, amount=6.0)  # the log works again afterwards
    models.undo()
    assert _amount(xid) == 3.0


def test_undo_of_a_deleted_input_needs_its_process(model):
    name, pid, xid = model
    models.delete_exchange(xid)
    bd.get_node(id=pid).delete()  # outside: the whole process is gone
    with pytest.raises(models.UndoConflict):
        models.undo()
    assert not list(ExchangeDataset.select().where(ExchangeDataset.output_database == name, ExchangeDataset.type == "technosphere"))


@pytest.fixture()
def client():
    bd.projects.set_current(TEST_PROJECT)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    bd.projects.set_current(TEST_PROJECT)


def test_without_a_project_only_the_choice_works(client, monkeypatch):
    monkeypatch.setattr(s, "TEST_PROJECT_PREFIX", "nicht-ausblenden")
    s.OPEN["project"] = None
    st = client.get("/api/state").json()
    assert st["project"] is None and st["databases"] == [] and any(p["name"] == TEST_PROJECT for p in st["projects"])
    r = client.get("/api/search", params={"q": "electricity"})
    assert r.status_code == 409 and "Projekt wählen" in r.json()["detail"]
    assert client.post("/api/copy", json={}).status_code == 409
    st = client.post("/api/project", json={"name": TEST_PROJECT}).json()
    assert st["project"] == TEST_PROJECT and st["databases"]


def test_default_project_is_listed_when_someone_worked_in_it():
    from bw2data.project import ProjectDataset as PD

    default = PD.get(PD.name == "default")
    assert s._has_databases(PD.get(PD.name == TEST_PROJECT)) is True
    f = _dir("default") / "databases.json"
    keep = f.read_bytes() if f.exists() else None
    try:
        f.write_text("{}", encoding="utf-8")
        assert s._has_databases(default) is False
        f.write_text('{"meine": {"depends": []}}', encoding="utf-8")
        assert s._has_databases(default) is True
    finally:
        f.unlink() if keep is None else f.write_bytes(keep)


def test_a_project_that_fails_to_load_is_reported_and_not_reopened(client, monkeypatch):
    reg = registry.load()
    reg["last_project"] = TEST_PROJECT
    registry.save(reg)

    def broken():
        raise ValueError("Matrix ist nicht quadratisch")

    monkeypatch.setattr(models, "system", broken)
    st = client.get("/api/state").json()
    assert st["project"] == TEST_PROJECT and "nicht quadratisch" in st["load_error"] and st["projects"]
    assert registry.load().get("last_project") is None


def test_requests_from_other_websites_are_rejected(client):
    assert client.post("/api/copy", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/beispiel", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/state", headers={"Origin": "http://127.0.0.1:8787", "Sec-Fetch-Site": "same-origin"}).status_code == 200
    big = client.post("/api/models/import", content=b"x", headers={"Content-Length": str(30 * 1024 * 1024)})
    assert big.status_code == 413


def test_project_deleted_from_outside_is_not_created_again():
    _cleanup()
    name = f"{PREFIX}-weg"
    bd.projects.copy_project(name, switch=False)
    s.set_project(name)
    s.acknowledge()
    d = _dir(name)
    ProjectDataset.delete().where(ProjectDataset.name == name).execute()  # what another program's delete does
    # Windows deletes no open file: another program can delete the folder only once we have let go of its SQLite files
    for _, sqlite_db in bd.config.sqlite3_databases:
        sqlite_db.db.close()
    shutil.rmtree(d)
    assert s.sync_external() is True
    assert not s.project_open() and name not in bd.projects and not d.exists()
    _cleanup()


def test_project_left_keeps_no_file_open():
    """A request thread that read a project keeps its parameters database open after the switch until Python's cycle
    collector runs (Brightway). Opening another project lets go at once: on Windows the project left can be deleted."""
    psutil = pytest.importorskip("psutil")
    _cleanup()
    name = f"{PREFIX}-verlassen"
    bd.projects.set_current(name)  # new and empty
    d = os.path.normcase(str(bd.projects.dir))
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:  # the thread stays alive, like the server's
            ex.submit(lambda: ProjectParameter.select().count()).result()
            s.set_project(TEST_PROJECT)
            assert not [f.path for f in psutil.Process().open_files() if os.path.normcase(f.path).startswith(d)]
    finally:
        _cleanup()
