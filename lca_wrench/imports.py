"""New projects, and data imported into them as background jobs: BAFU 2026 (sentier-brightway), ecoinvent (bw2io,
like the Activity Browser), future scenarios of ecoinvent (premise, scenarios.py) and EXIOBASE (exiobase.py).

Target of an import: a new project, an existing one that has no databases yet (e.g. one just created empty, as in
the Activity Browser: new project, then import), or, with "add", the open project, which then gets one more
database next to the ones it has. Adding never overwrites: a database that exists already is refused, and ecoinvent's
methods are only written when the project does not have them yet. A failed import removes what it made: the whole
project if it created it, otherwise the databases and methods it added. Then Brightway is back on the project that
was open before.

premise and EXIOBASE run as separate processes and do not hold the lock: the app stays usable while they work
(10 to 60 minutes), and the new databases appear when they are done. Which background databases a calculation uses
is chosen separately (backgrounds.py); new scenarios and EXIOBASE are not used until chosen.

A job holds the service lock while it runs (Brightway has one current project per process); requests wait for it.
The UI follows it through `status`, which does not need the lock.
"""

from __future__ import annotations

import contextvars
import json
import logging
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import bw2data as bd
from bw2data.project import ProjectDataset

from . import bafu2026, ecoinvent, exiobase, scenarios
from . import service as s
from .i18n import _, msg, render

log = logging.getLogger("lca_wrench")

SOURCES = ("bafu2026", "ecoinvent-account", "ecoinvent-files", "premise", "premise-setup", "exiobase")
EXTERNAL = ("premise", "premise-setup", "exiobase")


@dataclass
class Job:
    project: str
    source: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: str = "läuft"  # läuft, fertig, fehler
    phase: tuple = field(default_factory=lambda: msg("Vorbereiten …"))
    started: float = field(default_factory=time.time)
    seconds: float = 0.0
    result: dict | None = None
    error: str | None = None

    def public(self) -> dict:
        return {"id": self.id, "project": self.project, "source": self.source, "state": self.state,
                "phase": render(self.phase), "result": self.result, "error": self.error,
                "seconds": round(time.time() - self.started if self.state == "läuft" else self.seconds)}


JOBS: dict[str, Job] = {}


def running() -> Job | None:
    return next((j for j in JOBS.values() if j.state == "läuft"), None)


def status(job_id: str | None = None) -> dict | None:
    job = JOBS.get(job_id) if job_id else running()
    if job_id and job is None:
        raise KeyError(_("Diesen Auftrag gibt es nicht (mehr)."))
    return job.public() if job else None


def options() -> dict:
    """What the dialog for a new project (or a database added to the open one) can offer on this computer."""
    out = {"bafu2026": bafu2026.available(), "ecoinvent": ecoinvent.available(),
           "ecoinvent_login": ecoinvent.saved_login(), "system_models": list(ecoinvent.SYSTEM_MODELS),
           "exiobase_versions": list(exiobase.VERSIONS), "exiobase_years": exiobase.YEARS}
    c = scenarios.constants()  # a separate process, the first time a few seconds: outside the lock
    av = scenarios.offered(c)  # asks Zenodo which scenario files there are: outside the lock too
    if not s.LOCK.acquire(timeout=1.0):  # an import holds it: the basic options are enough to show its progress
        return out
    try:
        if not s.project_open():
            return out
        roles = s.models.roles()
        out.update({
            "premise": c, "premise_available": av, "premise_sources": scenarios.sources(roles),
            "premise_key": bool(scenarios.saved_key()),
            "premise_setup": scenarios.uv() is not None,
            "biospheres": sorted((n for n, r in roles.items() if r == "biosphere"), key=lambda n: -len(bd.Database(n))),
            "databases": sorted(bd.databases)})
    finally:
        s.LOCK.release()
    return out


def _name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 100:
        raise ValueError(_("Bitte einen Projektnamen angeben (höchstens 100 Zeichen)."))
    return name


def _project_has_data(name: str) -> bool:
    ds = ProjectDataset.get(ProjectDataset.name == name)
    try:
        return bool(json.loads((Path(bd.projects._project_dir(ds)) / "databases.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def check_target(name: str, add: bool = False) -> str:
    name = _name(name)
    if add:  # one more database in the open project
        if not s.project_open() or name != bd.projects.current:
            raise ValueError(_("Datenbanken lassen sich nur dem offenen Projekt hinzufügen."))
        return name
    if name in bd.projects:
        if not s.project_is_25(name):
            raise ValueError(_("«{name}» ist ein Projekt des Activity Browsers 2. Importiere in ein neues Projekt.",
                               name=name))
        if _project_has_data(name):
            raise ValueError(_("Das Projekt «{name}» hat schon Daten. Importiert wird nur in ein neues oder leeres "
                               "Projekt; wähle einen anderen Namen.", name=name))
    return name


def create_project(name: str) -> str:
    """A new, empty Brightway 2.5 project, then opened (like «New project» in the Activity Browser)."""
    name = _name(name)
    if name in bd.projects:
        raise ValueError(_("Das Projekt «{name}» gibt es schon.", name=name))
    bd.projects.create_project(name)
    s.set_project(name)
    return name


def start(name: str, source: str, opts: dict) -> dict:
    """Check everything that can be checked at once, then run the import in a background thread."""
    if running():
        raise ValueError(_("Es läuft schon ein Import. Bitte warten, bis er fertig ist."))
    if source not in SOURCES:
        raise ValueError(_("Unbekannte Datenquelle."))
    add = bool(opts.get("add")) or source in EXTERNAL
    name = check_target(name, add)
    if source in EXTERNAL:
        return _start_external(name, source, opts)
    if add and source.startswith("ecoinvent"):
        db = ecoinvent.database_name(opts.get("version", ""), opts.get("system_model", ""))
        if db in bd.databases:
            raise ValueError(_("Eine Datenbank «{name}» gibt es schon.", name=db))
    if add and source == "bafu2026" and any(n.startswith("bafu-2026") for n in bd.databases):
        raise ValueError(_("Das Projekt «{name}» hat schon Daten von BAFU 2026.", name=name))
    if source == "bafu2026" and not bafu2026.available():
        raise ValueError(_("Für den Import von BAFU 2026 fehlt das Paket sentier-brightway. Installiere LCA Wrench "
                           "neu (Installationsskript), dann ist es dabei."))
    if source.startswith("ecoinvent"):
        if not ecoinvent.available():
            raise ValueError(_("Für den Import von ecoinvent fehlt das Paket ecoinvent_interface. Installiere "
                               "LCA Wrench neu (Installationsskript), dann ist es dabei."))
        ecoinvent.check(opts.get("version", ""), opts.get("system_model", ""))
        if source == "ecoinvent-files" and not opts.get("lci_path"):
            raise ValueError(_("Bitte den Pfad zur ecoSpold02-Datei von ecoinvent angeben."))
        if source == "ecoinvent-account" and not (opts.get("username") and opts.get("password")) \
                and not ecoinvent.saved_login():
            raise ValueError(_("Bitte Benutzername und Passwort von ecoinvent angeben."))
    job = Job(project=name, source=source)
    for old in [j for j in JOBS.values() if j.state != "läuft" and time.time() - j.started > 3600]:
        JOBS.pop(old.id, None)
    JOBS[job.id] = job
    threading.Thread(target=contextvars.copy_context().run, args=(_run, job, dict(opts)), daemon=True).start()
    return job.public()


def _set_phase(job: Job):
    def phase(m: tuple) -> None:
        job.phase = m
    return phase


def _run(job: Job, opts: dict) -> None:
    with s.LOCK:
        before = s.OPEN["project"]
        name = job.project
        created = name not in bd.projects
        dbs0: set = set()
        methods0: set = set()
        state = "fehler"
        try:
            phase = _set_phase(job)
            if created:
                bd.projects.create_project(name)
            bd.projects.set_current(name)
            dbs0, methods0 = set(bd.databases), set(bd.methods)
            if job.source == "bafu2026":
                phase(msg("BAFU 2026 laden und schreiben (etwa eine Minute) …"))
                info = bafu2026.install(name)
            elif job.source == "ecoinvent-account":
                info = ecoinvent.install_remote(opts["version"], opts["system_model"], opts.get("username"),
                                                opts.get("password"), bool(opts.get("remember")), phase,
                                                lcia=None if not _has_ei_methods(opts["version"]) else False)
            else:
                info = ecoinvent.install_local(opts["version"], opts["system_model"], opts["lci_path"],
                                               None if _has_ei_methods(opts["version"]) else opts.get("lcia_path"), phase)
            phase(msg("Projekt öffnen und die Rechnung vorbereiten …"))
            s.set_project(name)
            st = s.state()
            if st["default_method"]:  # the matrix is factorized here, not on the first click
                s.models.system().bg.unit_scores(tuple(st["default_method"]))
            job.result = {**{k: v for k, v in info.items() if isinstance(v, (str, int, float, bool))},
                          "processes": sum(d["count"] for d in st["databases"] if d["role"] == "background"),
                          "methods": len(st["methods"])}
            state = "fertig"
        except Exception as e:
            log.exception("Import of %s into %s failed", job.source, name)
            job.error, state = str(e) or e.__class__.__name__, "fehler"
            _undo(name, created, before, dbs0, methods0)
        finally:
            s.acknowledge()
            # the state last: whoever waits for the job sees the project cleaned up (or opened) and the lock free soon
            job.seconds = time.time() - job.started
            job.state = state


def _has_ei_methods(version: str) -> bool:
    return any(m[0] == f"ecoinvent-{version}" for m in bd.methods)


# ---------- premise and EXIOBASE: separate processes ----------

_PHASES = {
    "load": msg("premise starten und ecoinvent lesen (mehrere Minuten) …"),
    "update": msg("Szenario anwenden: Strom, Stahl, Zement, Treibstoffe, Verkehr … (10 bis 40 Minuten)"),
    "write": msg("Szenario-Datenbanken schreiben …"),
    "download": msg("EXIOBASE herunterladen (Zenodo, 0.6 bis 1 GB) …"),
    "read": msg("EXIOBASE lesen (mehrere Minuten) …"),
    "methods": msg("Wirkungsmethoden um die EXIOBASE-Flüsse ergänzen …"),
}


def _start_external(name: str, source: str, opts: dict) -> dict:
    """Check the request, then run premise (or its setup) or the EXIOBASE import as a separate process."""
    roles = s.models.roles()
    if source == "premise-setup":
        cmds = scenarios.setup_command()
        task, env = None, None
    elif source == "premise":
        task = scenarios.plan(opts, roles)
        if opts.get("remember") and opts.get("key"):
            scenarios.remember_key(opts["key"])
        cmds = [[str(scenarios.env_python()), str(scenarios.WORKER)]]
        env = scenarios._env()
    else:
        task = _exiobase_task(name, opts, roles)
        cmds = [[sys.executable, "-m", "lca_wrench.exiobase"]]
        env = None
    job = Job(project=name, source=source)
    JOBS[job.id] = job
    threading.Thread(target=contextvars.copy_context().run, args=(_run_external, job, cmds, task, env),
                     daemon=True).start()
    return job.public()


def _exiobase_task(name: str, opts: dict, roles: dict) -> dict:
    bio = opts.get("biosphere") or ""
    if roles.get(bio) != "biosphere":
        raise ValueError(_("Bitte die Datenbank der Stoffflüsse wählen, mit der EXIOBASE verknüpft wird."))
    path = (opts.get("path") or "").strip()
    system = "pxp" if opts.get("system", "pxp") == "pxp" else "ixi"
    if path:
        if not Path(path).expanduser().exists():
            raise ValueError(_("Datei oder Ordner nicht gefunden: {path}", path=path))
        version, year = None, None
    else:
        version, year = opts.get("version") or "", int(opts.get("year") or 0)
        if version not in exiobase.VERSIONS or year not in exiobase.YEARS:
            raise ValueError(_("Bitte eine Version und ein Jahr von EXIOBASE wählen, oder eine Datei angeben."))
    db = (opts.get("db_name") or "").strip() or exiobase.default_name(version, year, system)
    for n in (db, db + " biosphere"):
        if n in bd.databases:
            raise ValueError(_("Eine Datenbank «{name}» gibt es schon.", name=n))
    return {"project": name, "path": path or None, "version": version, "year": year, "system": system, "name": db,
            "biosphere": bio}


def _run_external(job: Job, cmds: list[list[str]], task: dict | None, env: dict | None) -> None:
    from pathlib import Path as _P

    with s.LOCK:
        before = set(bd.databases) if s.project_open() else set()
        methods0 = set(bd.methods) if s.project_open() else set()
    tail: deque = deque(maxlen=60)
    result, error = None, None
    try:
        for cmd in cmds:
            if job.source == "premise-setup":
                job.phase = msg("premise einrichten: eigene Python-Umgebung mit premise (einmalig, etwa 1 GB) …")
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env, cwd=str(_P(__file__).resolve().parent.parent), bufsize=1)
            if task is not None:
                proc.stdin.write(json.dumps(task))
            proc.stdin.close()
            for line in proc.stdout:
                line = line.rstrip()
                if line.startswith("@phase "):
                    job.phase = _PHASES.get(line[7:].strip(), job.phase)
                elif line.startswith("@done "):
                    result = json.loads(line[6:])
                elif line.startswith("@error "):
                    error = line[7:]
                elif line:
                    tail.append(line)
            if proc.wait() != 0:
                error = error or (tail[-1] if tail else _("Abgebrochen."))
                break
        if job.source == "premise-setup" and not error:
            scenarios.forget_constants()
            if scenarios.constants() is None:
                error = _("premise liess sich nicht starten. Einzelheiten in lca-wrench.log.")
            else:
                result = {"premise": scenarios.constants().get("version")}
    except Exception as e:
        error = str(e) or e.__class__.__name__
    if error:
        log.error("%s failed: %s\n%s", job.source, error, "\n".join(tail))
        if job.source == "premise":
            error = scenarios.explain(error)
    with s.LOCK:
        try:
            if task is not None:
                s.sync_external()  # the worker wrote into the project: read it again
                if error and s.project_open() and bd.projects.current == task["project"]:
                    for n in set(bd.databases) - before:
                        del bd.databases[n]
                    for m in set(bd.methods) - methods0:
                        bd.Method(m).deregister()
                s.acknowledge()
        except Exception:
            log.exception("Cleaning up after %s failed", job.source)
        job.result = result if not error else None
        job.error = error
        job.seconds = time.time() - job.started
        job.state = "fehler" if error else "fertig"


def _undo(name: str, created: bool, before: str | None, dbs0: set, methods0: set) -> None:
    """Remove what a failed import made and go back to the project that was open before."""
    try:
        if name not in bd.projects:
            pass
        elif created:
            if bd.projects.current == name:
                # leave it first: deleting the current project would switch to "default" with its automatic updates
                back = before if before and before in bd.projects and before != name else "default"
                bd.projects.set_current(back, update=False)
            s.release_files()  # Windows: what other threads opened of it would keep the folder from being deleted
            bd.projects.delete_project(name, delete_dir=True)
        else:
            bd.projects.set_current(name)
            for db in set(bd.databases) - dbs0:
                del bd.databases[db]
            for m in set(bd.methods) - methods0:
                bd.Method(m).deregister()
        if before and before in bd.projects:
            bd.projects.set_current(before)
        s.OPEN["project"] = before if before in bd.projects else None
    except Exception:
        log.exception("Cleaning up after the import into %s failed", name)
