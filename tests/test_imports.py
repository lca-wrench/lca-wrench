"""New projects and ecoinvent imports (lca_wrench/imports.py, lca_wrench/ecoinvent.py) with a tiny ecoinvent release in the
format of ecoinvent.org (tests/ecoinvent_mini.py, no licence needed).

Checked: an empty project, ecoinvent from the downloaded files (archive and unpacked folder, with and without the LCIA
file) gives the expected result in LCA Wrench and in bw2calc, the account path calls bw2io with the login and keeps
it only when asked, a failed import leaves nothing behind (new and existing empty project), a project with data is
never imported into, the API.
"""

import time

import bw2calc as bc
import bw2data as bd
import pytest
from fastapi.testclient import TestClient

import ecoinvent_mini as mini
from conftest import TEST_PROJECT
from lca_wrench import ecoinvent, imports
from lca_wrench import service as s
from lca_wrench.api import app

pytest.importorskip("ecoinvent_interface")

PREFIX = "lca-wrench-test-import"
DB = f"ecoinvent-{mini.VERSION}-{mini.SYSTEM_MODEL}"


def _drop_all():
    for p in [p.name for p in bd.projects if p.name.startswith(PREFIX)]:
        if bd.projects.current == p:
            bd.projects.set_current(TEST_PROJECT)
        s.remove_project(p)
    bd.projects.set_current(TEST_PROJECT)


@pytest.fixture(autouse=True)
def clean():
    _drop_all()
    yield
    _drop_all()


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    folder = tmp_path_factory.mktemp("ecoinvent")
    lci, lcia = mini.write_archives(folder)
    return {"lci": lci, "lcia": lcia, "unpacked": folder / "unpacked"}


def _wait(job: dict) -> dict:
    t0 = time.time()
    while imports.JOBS[job["id"]].state == "läuft":
        assert time.time() - t0 < 300, "Import hängt"
        time.sleep(0.2)
    return imports.status(job["id"])


def _opts(**kw):
    return {"version": mini.VERSION, "system_model": mini.SYSTEM_MODEL, **kw}


def _widget_scores():
    w = next(a for a in bd.Database(DB) if a["name"] == "widget production")
    lca = bc.LCA({w: 1.0}, mini.METHOD)
    lca.lci()
    lca.lcia()
    return s.unit_score(w.id, mini.METHOD), lca.score


def test_empty_project():
    name = imports.create_project(PREFIX + "-leer")
    assert bd.projects.current == name and s.OPEN["project"] == name and not bd.databases
    assert s.state()["project"] == name
    with pytest.raises(ValueError, match="gibt es schon"):
        imports.create_project(name)
    with pytest.raises(ValueError, match="Projektnamen"):
        imports.create_project("   ")


@pytest.mark.parametrize("kind", ["archive", "folder"])
def test_ecoinvent_from_files(files, kind):
    name = PREFIX + "-ei"
    lci = files["lci"] if kind == "archive" else files["unpacked"]
    job = _wait(imports.start(name, "ecoinvent-files", _opts(lci_path=str(lci), lcia_path=str(files["lcia"]))))
    assert job["state"] == "fertig", job["error"]
    assert job["result"]["processes"] == 2 and job["result"]["methods"] == 1
    assert s.OPEN["project"] == name == bd.projects.current
    assert set(bd.databases) == {DB, f"ecoinvent-{mini.VERSION}-biosphere"}
    assert s.state()["default_method"] == list(mini.METHOD)
    ours, ref = _widget_scores()
    assert ours == pytest.approx(mini.WIDGET_SCORE, rel=1e-6) and ours == pytest.approx(ref, rel=1e-9)
    if kind == "folder":
        assert (files["unpacked"] / "datasets").is_dir()  # the user's folder is only read


def test_ecoinvent_without_lcia_file(files):
    job = _wait(imports.start(PREFIX + "-ohne", "ecoinvent-files", _opts(lci_path=str(files["lci"]))))
    assert job["state"] == "fertig", job["error"]
    assert DB in bd.databases and not list(bd.methods)


def test_ecoinvent_with_account(files, monkeypatch):
    """The account path is bw2io's own; ecoinvent's server is replaced by the local files."""
    import ecoinvent_interface as ei

    seen = {}

    class FakeRelease:
        def __init__(self, settings):
            seen["login"] = (settings.username, settings.password)

        def list_versions(self):
            return ["3.9.1", mini.VERSION]

        def list_system_models(self, version, translate=True):
            return ["cutoff", "apos"]

        def get_release(self, **k):
            return files["unpacked"]

    monkeypatch.setattr(ei, "EcoinventRelease", FakeRelease)
    monkeypatch.setattr(ei, "get_excel_lcia_file_for_version",
                        lambda release, version: mini.write_lcia(files["lci"].parent / "lcia.xlsx"))
    saved = []
    monkeypatch.setattr(ei, "permanent_setting", lambda k, v: saved.append(k))
    phases = []
    monkeypatch.setattr(imports, "_set_phase", lambda job: lambda m: (phases.append(m[0]), setattr(job, "phase", m)))

    assert ecoinvent.versions("me", "secret") == [mini.VERSION, "3.9.1"]
    job = _wait(imports.start(PREFIX + "-konto", "ecoinvent-account", _opts(username="me", password="secret")))
    assert job["state"] == "fertig", job["error"]
    assert seen["login"] == ("me", "secret") and saved == []
    assert any("anmelden" in p for p in phases) and any("herunterladen" in p for p in phases)
    ours, ref = _widget_scores()
    assert ours == pytest.approx(mini.WIDGET_SCORE, rel=1e-6)

    _drop_all()
    job = _wait(imports.start(PREFIX + "-konto2", "ecoinvent-account", _opts(username="me", password="secret",
                                                                                 remember=True)))
    assert job["state"] == "fertig" and saved == ["username", "password"]


def test_failed_import_in_new_project_leaves_nothing(tmp_path):
    (tmp_path / "datasets").mkdir()  # no MasterData: not an ecoinvent release
    s.set_project(TEST_PROJECT)
    job = _wait(imports.start(PREFIX + "-kaputt", "ecoinvent-files", _opts(lci_path=str(tmp_path))))
    assert job["state"] == "fehler" and "MasterData" in job["error"]
    assert PREFIX + "-kaputt" not in bd.projects
    assert bd.projects.current == TEST_PROJECT == s.OPEN["project"]


def test_failed_import_in_empty_project_keeps_it_empty(files, monkeypatch):
    import bw2io.ecoinvent as bie

    name = imports.create_project(PREFIX + "-leer2")
    real = bie.SingleOutputEcospold2Importer.write_database

    def half(self, *a, **k):  # the biosphere is written, then the inventory fails
        raise RuntimeError("Abbruch beim Schreiben")

    monkeypatch.setattr(bie.SingleOutputEcospold2Importer, "write_database", half)
    job = _wait(imports.start(name, "ecoinvent-files", _opts(lci_path=str(files["lci"]),
                                                             lcia_path=str(files["lcia"]))))
    monkeypatch.setattr(bie.SingleOutputEcospold2Importer, "write_database", real)
    assert job["state"] == "fehler" and "Abbruch" in job["error"]
    bd.projects.set_current(name)
    assert name in bd.projects and not bd.databases and not list(bd.methods)


def test_project_with_data_is_never_imported_into(files):
    before = {n: len(bd.Database(n)) for n in bd.databases}
    with pytest.raises(ValueError, match="schon Daten"):
        imports.start(TEST_PROJECT, "ecoinvent-files", _opts(lci_path=str(files["lci"])))
    with pytest.raises(ValueError, match="schon Daten"):
        imports.start(TEST_PROJECT, "bafu2026", {})
    assert {n: len(bd.Database(n)) for n in bd.databases} == before


def test_checks_before_starting(files):
    with pytest.raises(ValueError, match="Version"):
        imports.start(PREFIX + "-x", "ecoinvent-files", _opts(version="neu", lci_path=str(files["lci"])))
    with pytest.raises(ValueError, match="Systemmodell"):
        imports.start(PREFIX + "-x", "ecoinvent-files", _opts(system_model="x", lci_path=str(files["lci"])))
    with pytest.raises(ValueError, match="Datenquelle"):
        imports.start(PREFIX + "-x", "excel", {})
    assert PREFIX + "-x" not in bd.projects
    assert ecoinvent.guess_from_filename(str(files["lci"])) == {"version": mini.VERSION, "system_model": "cutoff"}
    assert ecoinvent.guess_from_filename("ecoinvent 3.9.1_apos_ecoSpold02.7z") == {"version": "3.9.1",
                                                                                  "system_model": "apos"}


def test_api(files):
    c = TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"})
    o = c.get("/api/import/options").json()
    assert o["ecoinvent"] is True and "cutoff" in o["system_models"]
    r = c.post("/api/project/new", json={"name": PREFIX + "-api"})
    assert r.status_code == 200 and r.json()["state"]["project"] == PREFIX + "-api"
    assert c.get("/api/ecoinvent/guess", params={"path": str(files["lci"])}).json()["version"] == mini.VERSION
    r = c.post("/api/import/start", json={"name": PREFIX + "-api", "source": "ecoinvent-files", **_opts(
        lci_path=str(files["lci"]), lcia_path=str(files["lcia"]))})
    assert r.status_code == 200
    job = r.json()
    while job["state"] == "läuft":
        time.sleep(0.2)
        job = c.get("/api/import/status", params={"id": job["id"]}).json()["job"]
    assert job["state"] == "fertig", job["error"]
    assert c.get("/api/import/status").json()["job"] is None  # nothing running
    st = c.get("/api/state").json()
    assert st["project"] == PREFIX + "-api" and {d["name"] for d in st["databases"]} >= {DB}
    r = c.post("/api/import/start", json={"name": PREFIX + "-api", "source": "ecoinvent-files", **_opts(
        lci_path=str(files["lci"]))})
    assert r.status_code == 400 and "schon Daten" in r.json()["detail"]
    assert c.get("/api/import/status", params={"id": "gibtsnicht"}).status_code == 404
