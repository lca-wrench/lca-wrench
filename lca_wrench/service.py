"""Service layer for LCA Wrench UI: projects, search, results, working copies.

Everything the web API needs lives here or in engine/analysis/models/setups,
without any web code, so it can be tested directly against plain Brightway.

Rules:
- Background databases (BAFU, ecoinvent ...) are never changed in an original
  project. Changing them needs a working copy of the project (tracked in the
  registry next to the Brightway projects).
- The user's own model databases can be edited directly; every change can be
  undone (models.py).
- All Brightway access goes through LOCK: bw2data keeps the current project
  as global state, so concurrent requests must not interleave.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
import shutil
import threading
import time
from pathlib import Path

import bw2calc as bc
import bw2data as bd
import numpy as np
from bw2data.backends.proxies import Exchange
from bw2data.backends.schema import ActivityDataset as AD
from bw2data.backends.schema import ExchangeDataset
from bw2data.project import ProjectDataset
from bw_processing import safe_filename

from . import (analysis, backgrounds, bafu2026, beispiel, completion, engine, flowmap, functional, models, montecarlo,
               overview, regions, registry, repair, setups)
from .analysis import short_unit
from .i18n import _
from .models import ReadOnlyError

LOCK = threading.RLock()

# Projects with this name prefix are test projects and never shown in the project list
TEST_PROJECT_PREFIX = "lca-wrench-test"

# Methods this app adds to projects via setup_daten.py
# "Werkbank" (the app's former name) is the stored family of these methods in existing projects; the UI shows it as
# "Recommended". Kept so projects set up before the rename still have them.
CLIMATE_METHOD = ("Werkbank", "Klimawandel", "kg CO2-eq, abgeleitet aus UBP 2021")
UBP_TOTAL_METHOD = ("Werkbank", "Umweltbelastungspunkte gesamt", "UBP 2021")
PROFILE_FAMILY = "Ecological Scarcity 2021"

__all__ = ["ReadOnlyError"]

log = logging.getLogger("lca_wrench")

# The project the user works in. None until one is chosen: nothing is opened on its own except the project the user
# had open last time (or LCA_WRENCH_PROJECT, or bafu-2025, or bafu-2026), so a first start never touches someone's real projects.
OPEN: dict = {"project": None}


def project_open() -> bool:
    return OPEN["project"] is not None and OPEN["project"] == bd.projects.current


def is_working_copy(project: str | None = None) -> bool:
    return (project or bd.projects.current) in registry.load()["copies"]


def unit_score(activity_id: int | str, method: tuple) -> float:
    return models.system_for(activity_id).score({int(activity_id): 1.0}, tuple(method))


# ---------- projects, methods, search ----------

def _has_databases(ds) -> bool:
    """Read without opening the project: does its database list name anything?"""
    try:
        return bool(json.loads((Path(bd.projects._project_dir(ds)) / "databases.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def _project_list(reg: dict) -> list[dict]:
    cur = OPEN["project"]
    out = []
    for p in sorted(bd.projects, key=lambda p: p.name):
        # "default" is the empty project Brightway makes on its own, unless someone worked in it (many AB users do)
        if p.name != cur and (p.name.startswith(TEST_PROJECT_PREFIX)
                              or p.name == "default" and len(bd.projects) > 1 and not _has_databases(p)):
            continue
        legacy = not _is_25(p)
        out.append({"name": p.name, "copy": p.name in reg["copies"], "testcopy": p.name in reg.get("testcopies", {}),
                    "legacy": legacy, "rebuild": not legacy and p.name != cur and bool(pending_updates(p.name))})
    return out


def state() -> dict:
    reg = registry.load()
    base = {"project": None, "projects": _project_list(reg), "is_copy": False, "is_testcopy": False, "original": None,
            "changes": [], "databases": [], "methods": [], "default_method": None, "profile_family": None, "examples": [],
            "setups": [], "journal": [], "model_errors": [], "example_available": False, "external": EXTERNAL["count"],
            "load_error": None,
            "bafu2026_import": bafu2026.available() and bafu2026.PROJECT not in bd.projects}
    if not project_open():
        return base
    cur = bd.projects.current
    try:
        return {**base, **_project_state(reg, cur)}
    except Exception as e:  # an unusual project must not leave the app hanging at «Lade …»: say what failed, offer the others
        log.exception("Project %s cannot be loaded", cur)
        if reg.get("last_project") == cur:  # the next start must not get stuck in it again
            reg.pop("last_project")
            registry.save(reg)
        return {**base, "project": cur, "load_error": f"{type(e).__name__}: {e}"}


def _project_state(reg: dict, cur: str) -> dict:
    roles = models.roles()
    writable = models.writable_databases()
    dbs = []
    for n in sorted(bd.databases):
        try:
            count = len(bd.Database(n))
            if functional.is_functional(n):  # Activity Browser 3 format: the processes, not also their product nodes
                count = AD.select().where((AD.database == n) & (AD.type << list(engine.LISTED_PROCESS_TYPES))).count()
        except Exception:  # e.g. a backend this Brightway does not know
            count = 0
        dbs.append({"name": n, "count": count, "role": roles.get(n, "empty"), "biosphere": roles.get(n) == "biosphere",
                    "writable": n in writable})
    # methods without any characterization factor (in BAFU: Noise, Biotic Resources) would always show 0
    ms = overview._method_list()
    multi = overview._multi_namespace(ms)
    methods = [{"id": list(mt), "family": overview.method_family(mt, multi), "name": overview.method_name(mt),
                "topic": overview.topic(mt), "unit": short_unit(bd.methods[mt].get("unit"))} for mt in ms]
    copy = reg["copies"].get(cur)
    testcopy = reg.get("testcopies", {}).get(cur)
    return {
        "project": cur,
        "is_copy": copy is not None,
        "is_testcopy": testcopy is not None,
        "original": copy["original"] if copy else testcopy["original"] if testcopy else None,
        "changes": [{**c, "exchange": str(c["exchange"])} for c in copy["changes"]] if copy else [],
        "databases": dbs,
        "methods": methods,
        "default_method": default_method([tuple(m["id"]) for m in methods]),
        "profile_family": PROFILE_FAMILY if any(mt[0] == PROFILE_FAMILY for mt in bd.methods) else None,
        "examples": examples(),
        "setups": setups.list_setups(),
        "journal": models.journal()[:30],
        "model_errors": models.system().fg.error_texts(),
        "example_available": beispiel.available(),
        "background": background_state(roles),
        "flowmap": flowmap.info(),
        "completion": completion.info(),
    }


# ---------- which background databases the calculation uses ----------

def background_state(roles: dict | None = None) -> dict:
    roles = roles or models.roles()
    ch = backgrounds.choice(roles)
    S = models.system()
    return {**ch, "options": backgrounds.options(roles), "used": list(S.bg.dbs), "substituted": S.substituted,
            "pulled": S.pulled}


def set_background(mode: str, databases: list[str]) -> dict:
    """One background database, several combined, or "auto" (all process databases, as before)."""
    backgrounds.set_choice(mode, databases, models.roles())
    return state()


def remove_background(name: str) -> dict:
    """Remove a background database LCA Wrench added itself: a premise scenario, or EXIOBASE with its own biosphere
    database and the factors its import added to the methods. Refused while models (or other databases) use it.
    Cannot be undone; the database can be imported again."""
    from . import imports

    roles = models.roles()
    if roles.get(name) != "background" or not backgrounds.removable(name):
        raise ValueError(_("«{name}» wurde nicht von LCA Wrench hinzugefügt (Szenario oder EXIOBASE) und bleibt, "
                           "wie sie ist.", name=name))
    if imports.running():
        raise ValueError(_("Es läuft ein Import. Bitte warten, bis er fertig ist."))
    bio = name + " biosphere"
    own_bio = backgrounds.kind(name) == "mrio" and str((bd.databases.get(bio) or {}).get("format", "")).startswith("EXIOBASE")
    users = set(models._external_users(name))
    if own_bio:
        users |= set(models._external_users(bio)) - {name}
    if users:
        raise ValueError(_("«{name}» wird noch von {n} Prozess(en) in anderen Datenbanken verwendet.", name=name, n=len(users)))
    project = bd.projects.current
    if own_bio:
        _strip_methods(bio)
    for db in ([name, bio] if own_bio else [name]):
        try:
            processed = bd.Database(db).filepath_processed()
        except Exception:  # never processed, or its file is gone already
            processed = None
        del bd.databases[db]
        if db in bd.databases:
            raise ValueError(_("«{name}» liess sich nicht löschen. Einzelheiten in lca-wrench.log.", name=db))
        if processed:
            Path(processed).unlink(missing_ok=True)  # Brightway leaves the matrix file (EXIOBASE: several hundred MB)
    backgrounds.forget(name)
    engine.bump_background(project)
    return state()


def _strip_methods(bio: str) -> int:
    """Take the flows of database `bio` out of every method (the reverse of the EXIOBASE import's last step)."""
    ids = {i for (i,) in AD.select(AD.id).where(AD.database == bio).tuples()}
    mine = lambda key: key in ids if isinstance(key, int) else tuple(key)[0] == bio  # noqa: E731
    n = 0
    for mt in list(bd.methods):
        m = bd.Method(mt)
        data = m.load()
        keep = [row for row in data if not mine(row[0])]
        if len(keep) != len(data):
            m.write(keep)
            n += 1
    return n


def _plain_links(S, what: str) -> None:
    """Monte Carlo and the cross-check use bw2calc, which follows the links as they are stored: with inputs taken from
    another background database, it would calculate something else."""
    if S.substituted:
        raise ValueError(_("{what} rechnet mit den Verknüpfungen, wie sie gespeichert sind. Die Modelle beziehen hier "
                           "{n} Inputs aus einem anderen Hintergrund ({dbs}); wähle unter Start die Hintergrunddaten, "
                           "mit denen die Modelle verknüpft sind, oder verschiebe die Modelle dorthin.",
                           what=what, n=S.substituted, dbs=", ".join(S.bg.dbs)))


def default_method(methods: list[tuple]) -> list | None:
    """The method a project opens with: this app's climate method (BAFU), else climate change GWP100 of the newest
    IPCC report as a total (ecoinvent, EF), else the first one. Users choose any other at the top."""
    if CLIMATE_METHOD in methods:
        return list(CLIMATE_METHOD)

    def score(m: tuple) -> float:
        t = " ".join(m).lower()
        if "climate change" not in t and "global warming" not in t:
            return -1
        s = 4 * ("gwp100" in t or "gwp 100" in t) + 3 * ("ipcc 2021" in t) + 2 * ("ipcc 2013" in t) + 1 * ("ef v3" in t)
        s += 1 * ("total" in t) - 5 * ("no lt" in t)
        s -= 2 * bool(re.search(r"climate change\s*[:,-]\s*(fossil|biogenic|land use|luluc)", t))  # a part, not the total
        return s - len(t) / 1000  # among equals the shorter, more general name

    best = max(methods, key=score, default=None)
    if best is not None and score(best) > 0:
        return list(best)
    return list(methods[0]) if methods else None

def set_project(name: str, rebuild: bool = False) -> None:
    """Open a project. One that Brightway would convert on opening (made with an older Brightway 2.5) is opened only
    when asked for explicitly (rebuild=True); the UI offers a test copy instead."""
    if name not in bd.projects:
        raise KeyError(_("Projekt «{name}» gibt es nicht.", name=name))
    _require_25(name)
    _require_readable(name)
    if not rebuild and pending_updates(name):
        raise ValueError(_("Brightway baut «{name}» beim ersten Öffnen um (alle Rechendaten neu). Lege lieber eine "
                           "Testkopie an oder bestätige das Öffnen des Originals.", name=name))
    bd.projects.set_current(name)
    OPEN["project"] = name
    reg = registry.load()
    if reg.get("last_project") != name:
        reg["last_project"] = name
        registry.save(reg)
    sync_external()  # the project may have been changed by another program while we were elsewhere


def pick_start_project(preferred: str | None = None) -> str | None:
    """The project to open at start: the one asked for (LCA_WRENCH_PROJECT), the last one chosen in the app, or bafu-2025, or
    bafu-2026 (imported with sentier-brightway).
    Otherwise none: the user chooses (so a first start on someone's computer never opens a real project on its own).
    Projects Brightway would convert on opening are never opened on their own either."""
    names = {p.name for p in bd.projects if _is_25(p)}  # older projects are never opened, see _require_25
    for cand in (preferred, registry.load().get("last_project"), "bafu-2025", bafu2026.PROJECT):
        if cand and cand in names and not pending_updates(cand) and not repair.damaged(cand):
            return cand
    return None


def _require_readable(name: str) -> None:
    if repair.damaged(name):
        raise ValueError(_("Die Liste der Datenbanken von «{name}» (databases.json) ist beschädigt, die Daten selbst "
                           "sind unversehrt. Reparieren mit: python -m lca_wrench.repair \"{name}\" --write "
                           "(im Ordner von LCA Wrench, mit dessen Python).", name=name))


def open_start_project(preferred: str | None = None) -> str | None:
    start = pick_start_project(preferred)
    if start:
        bd.projects.set_current(start)
        OPEN["project"] = start
    return start


def visit(name: str) -> None:
    """Switch to another project for reading it (compare, versions). Never one Brightway would convert on opening."""
    if name not in bd.projects:
        raise KeyError(_("Projekt «{name}» gibt es nicht.", name=name))
    _require_25(name)
    _require_readable(name)
    if pending_updates(name):
        raise ValueError(_("Brightway baut «{name}» beim ersten Öffnen um. Öffne es zuerst oben in der Projektauswahl.", name=name))
    bd.projects.set_current(name)


def leave(name: str) -> None:
    """Back to the project we came from (already opened, so no automatic updates)."""
    if bd.projects.current != name:
        bd.projects.set_current(name, update=False)


# ---------- projects in the older format, and projects Brightway would convert ----------
#
# Brightway 2.5 converts an older project automatically when it is opened (new processed format, new search index).
# The Activity Browser 2 cannot read such a project any more. So LCA Wrench never opens one: it copies the project
# directory file by file, without opening the original, and converts only the copy.
# A project made with an older Brightway 2.5 (e.g. by the Activity Browser 3) gets its automatic updates on opening
# too: all databases and methods are processed again. LCA Wrench asks first and offers the same test copy.

def _is_25(ds) -> bool:
    return bool((ds.data or {}).get("25"))


def project_is_25(name: str) -> bool:
    return _is_25(ProjectDataset.get(ProjectDataset.name == name))


def _require_25(name: str) -> None:
    if not project_is_25(name):
        raise ValueError(_("Das Projekt «{name}» hat das ältere Format von Brightway 2 (Activity Browser 2). LCA Wrench öffnet "
                           "es nicht direkt, sonst könnte der Activity Browser 2 es danach nicht mehr lesen. Lege eine Kopie an.",
                           name=name))


def pending_updates(name: str) -> list[str]:
    """The automatic updates Brightway would apply when opening this project, read without opening it."""
    from bw2data.updates import Updates

    try:
        ds = ProjectDataset.get(ProjectDataset.name == name)
        f = Path(bd.projects._project_dir(ds)) / "preferences.pickle"
        if not f.is_file():
            return []  # Brightway marks every update as done in a project without preferences (set_initial_updates)
        with open(f, "rb") as fh:
            done = pickle.load(fh).get("updates")
    except Exception:
        return []
    if done is None:
        return []
    return sorted(k for k, u in Updates.UPDATES.items() if u["automatic"] and not done.get(k))


def copy_project_files(name: str) -> str:
    """A test copy of any project: copied file by file without opening the original, then opened (and converted, if
    Brightway wants to) as the copy. Everything in a test copy may be changed; the original stays as it is."""
    if name not in bd.projects:
        raise KeyError(_("Projekt «{name}» gibt es nicht.", name=name))
    src = ProjectDataset.get(ProjectDataset.name == name)
    n, new = 1, _("{base} (LCA Wrench)", base=name)
    while new in bd.projects:
        n += 1
        new = _("{base} (LCA Wrench {n})", base=name, n=n)
    src_dir = bd.projects._project_dir(src)
    dst_dir = Path(bd.projects._base_data_dir) / safe_filename(new, full=src.full_hash)
    if dst_dir.exists():
        raise ValueError(_("Der Ordner für die Kopie gibt es schon: {path}", path=dst_dir))
    shutil.copytree(src_dir, dst_dir)  # files first: a failed copy leaves no half registered project
    before = OPEN["project"]
    try:
        ProjectDataset.create(data=dict(src.data or {}), name=new, full_hash=src.full_hash)
        bd.projects.set_current(new)  # the automatic updates run on the copy
        if not bd.projects.twofive:
            bd.projects.migrate_project_25()  # reprocesses every database and method in the 2.5 format
    except Exception:
        if bd.projects.current == new:
            # leave the copy first: deleting the current project would switch to "default" with its automatic updates
            bd.projects.set_current(before if before and before in bd.projects else "default", update=False)
        if new in bd.projects:
            bd.projects.delete_project(new, delete_dir=True)
        elif dst_dir.exists():
            shutil.rmtree(dst_dir)
        raise
    reg = registry.load()
    reg.setdefault("testcopies", {})[new] = {"original": name, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    reg.get("journal", {}).pop(new, None)
    registry.save(reg)
    set_project(new)
    return new


def copy_older_project(name: str) -> str:
    """Copy a Brightway 2 project and convert only the copy to Brightway 2.5. The original is only read."""
    if name not in bd.projects:
        raise KeyError(_("Projekt «{name}» gibt es nicht.", name=name))
    if project_is_25(name):
        raise ValueError(_("Das Projekt «{name}» hat schon das Format von LCA Wrench und braucht keine Kopie.", name=name))
    return copy_project_files(name)

EXAMPLE_NAMES = [
    ("Aluminium, primary, at plant", "RER"),
    ("Electricity, low voltage, at grid", "CH"),
    ("Transport, freight, lorry, 7.5t-16t gross weight, fleet average", "CH"),
    ("Concrete, normal, at plant, with resource correction", "CH"),
]

_examples: dict = {}


def examples() -> list[dict]:
    if bd.projects.current in _examples:
        return _examples[bd.projects.current]
    roles = models.roles()
    bg = [n for n, r in roles.items() if r == "background"]
    found = {}
    if bg:
        for nid, name, loc in AD.select(AD.id, AD.name, AD.location).where(
                AD.database << bg, AD.name << [n for n, _ in EXAMPLE_NAMES]).tuples():
            found.setdefault((name, loc), nid)
    out = [_act_summary(bd.get_node(id=found[k])) for k in EXAMPLE_NAMES if k in found]
    _examples[bd.projects.current] = out
    return out


def _act_summary(a) -> dict:
    return {"id": str(a.id), "name": a["name"], "product": a.get("reference product"), "location": a.get("location"),
            "unit": short_unit(a.get("unit")), "database": a["database"]}


# units the search can filter by, grouped by what they measure: "energy" finds kWh, MJ and MWh, and leaves out
# infrastructure (counted in units) and everything else
UNIT_GROUPS = {
    "energy": {"kilowatt hour", "megajoule", "megawatt hour", "kilojoule", "gigajoule", "watt hour", "terajoule"},
    "mass": {"kilogram", "ton", "gram", "metric ton", "tonne"},
    "volume": {"cubic meter", "litre", "liter", "normal cubic meter"},
    "area": {"square meter", "hectare"},
    "land": {"square meter-year", "hectare-year"},
    "freight": {"ton kilometer", "metric ton*km", "kilogram kilometer"},
    "passenger": {"person kilometer"},
    "vehicle": {"vehicle kilometer", "kilometer"},
    "length": {"meter", "kilometer"},
    "item": {"unit"},
    "time": {"hour", "year", "day"},
    "radioactivity": {"kilo Becquerel", "Becquerel", "kilobecquerel"},
    "currency": {"million €", "euro", "EUR", "€", "USD", "CHF", "million EUR"},  # input-output tables (EXIOBASE)
}
# the same named in the query ("electricity MWh"): taken out of the search words
_UNIT_WORDS = {"kwh": "energy", "mwh": "energy", "gwh": "energy", "mj": "energy", "gj": "energy", "kg": "mass",
               "tkm": "freight", "pkm": "passenger", "vkm": "vehicle", "m3": "volume", "m³": "volume", "m2": "area",
               "m²": "area"}


# emissions and resources by formula, short name or German name ("CO2", "PM2.5", "Kohlendioxid", "Feinstaub"):
# searched under the name the elementary flows have
FLOW_SYNONYMS = {
    "co2": "carbon dioxide", "ch4": "methane", "n2o": "dinitrogen monoxide", "nox": "nitrogen oxides",
    "no2": "nitrogen dioxide", "no": "nitrogen monoxide", "so2": "sulfur dioxide", "sox": "sulfur dioxide",
    "nh3": "ammonia", "nh4": "ammonium", "no3": "nitrate", "po4": "phosphate", "co": "carbon monoxide",
    "sf6": "sulfur hexafluoride", "pm2.5": "particulates 2.5", "pm25": "particulates 2.5", "pm10": "particulates 10",
    "voc": "nmvoc", "hg": "mercury", "pb": "lead", "cd": "cadmium", "cu": "copper", "zn": "zinc", "ni": "nickel",
    "cr": "chromium", "kohlendioxid": "carbon dioxide", "kohlenstoffdioxid": "carbon dioxide", "methan": "methane",
    "lachgas": "dinitrogen monoxide", "distickstoffmonoxid": "dinitrogen monoxide", "stickoxide": "nitrogen oxides",
    "stickoxid": "nitrogen oxides", "stickstoffoxide": "nitrogen oxides", "schwefeldioxid": "sulfur dioxide",
    "ammoniak": "ammonia", "kohlenmonoxid": "carbon monoxide", "feinstaub": "particulates", "staub": "particulates",
    "quecksilber": "mercury", "blei": "lead", "kupfer": "copper", "zink": "zinc", "chrom": "chromium",
    "arsen": "arsenic", "phosphat": "phosphate", "nitrat": "nitrate", "ammonium": "ammonium", "wasser": "water",
    "erdgas": "gas natural", "erdöl": "oil crude", "rohöl": "oil crude", "kohle": "coal", "braunkohle": "coal brown",
    "steinkohle": "coal hard", "uran": "uranium", "landnutzung": "occupation", "flächennutzung": "occupation",
    "biogen": "biogenic", "sulphur": "sulfur",
}
_FLOW_EXACT = {"pm10": "particulates, < 10 um", "pm2.5": "particulates, < 2.5 um", "pm25": "particulates, < 2.5 um"}
# compartments of elementary flows; also as the last word of the query ("co2 air", "nitrate soil")
COMPARTMENTS = {"air": "air", "water": "water", "soil": "soil", "resource": "resource"}
_COMP_WORDS = {"air": "air", "luft": "air", "soil": "soil", "boden": "soil", "gewässer": "water",
               "resource": "resource", "resources": "resource", "ressource": "resource", "ressourcen": "resource"}


def _flow_query(q: str) -> tuple[str, str | None]:
    """The query with formulas and German names replaced, and a compartment named at its end taken out."""
    words = q.split()
    comp = None
    if len(words) > 1 and words[-1].lower() in _COMP_WORDS:
        comp, words = _COMP_WORDS[words[-1].lower()], words[:-1]
    elif len(words) > 2 and " ".join(words[-2:]).lower() in ("to water", "in water"):
        comp, words = "water", words[:-2]
    return " ".join(FLOW_SYNONYMS.get(w.lower().strip(",;"), w) for w in words), comp


def _in_compartment(a, comp: str) -> bool:
    cat = ((a.get("categories") or ("",))[0] or "").lower()
    return comp in cat


def search_options() -> dict:
    """Units and locations for the search form: the unit groups present, and every location in the databases;
    for elementary flows the unit groups and compartments."""
    roles = models.roles()
    dbs = [n for n, r in roles.items() if r in ("background", "model")]
    units, locs = set(), {}
    for (data,) in AD.select(AD.data).where(AD.database << dbs).tuples():
        units.add(data.get("unit"))
        loc = data.get("location")
        if loc:
            locs[loc] = locs.get(loc, 0) + 1
    groups = [g for g, us in UNIT_GROUPS.items() if us & units]
    bio = [n for n, r in roles.items() if r == "biosphere"]
    funits, comps = set(), set()
    for (data,) in AD.select(AD.data).where(AD.database << bio).tuples():
        funits.add(data.get("unit"))
        cat = ((data.get("categories") or ("",))[0] or "").lower()
        comps.update(c for c in COMPARTMENTS if c in cat)
    return {"units": groups, "locations": sorted(locs, key=lambda x: (-locs[x], x)),
            "flow_units": [g for g, us in UNIT_GROUPS.items() if us & funits],
            "compartments": [c for c in COMPARTMENTS if c in comps]}


def search(q: str, location: str | None = None, limit: int = 60, database: str | None = None,
           kind: str = "process", unit: str | None = None, compartment: str | None = None) -> list[dict]:
    """Search processes (kind='process') or elementary flows (kind='flow').

    A word that occurs nowhere in these databases is read as a typo ("steeel"): the results for the closest word
    ("steel") follow those for the words as typed, each marked with the corrected search in "spelling".

    Without a database: the models, the background databases of the calculation and every input-output table.

    Processes can be narrowed by unit group ("energy": kWh, MJ, MWh …) and by location, given as code or name
    ("Switzerland"); a location or unit at the end of the query ("electricity low voltage CH", "heat MJ") counts
    too. With a location, the regions around it follow (CH → Europe → GLO → RoW), each process the nearest one it
    has; "region" in a result says that it stands in for the location asked for.

    Elementary flows can be narrowed by unit group and compartment (air, water, soil, resource, also as the last
    word: "co2 air"); formulas and German names ("CO2", "PM2.5", "Lachgas") find the flows' English names."""
    q = (q or "").strip()
    if not q:
        return []
    roles = models.roles()
    exact = None
    if kind == "flow":
        dbs = [n for n, r in roles.items() if r == "biosphere"]
        exact = _FLOW_EXACT.get(q.lower().strip())
        q, comp = _flow_query(q)
        compartment = compartment if compartment in COMPARTMENTS else comp
        words = q.split()
        if len(words) > 1 and words[-1].lower() in _UNIT_WORDS and not unit:
            unit, q = _UNIT_WORDS[words[-1].lower()], " ".join(words[:-1])
        if not q:
            return []
    else:
        dbs = [n for n, r in roles.items() if r in ("background", "model")]
        if not database:
            # the chosen background databases (and the models); another one when asked for by name. Input-output
            # tables (EXIOBASE) always: their sectors in money repeat no process data, and a model takes them as
            # inputs next to process data (hybrid LCA), which needs them found before any model links to them
            used = set(models.system().bg.dbs)
            dbs = [n for n in dbs if roles[n] == "model" or n in used or backgrounds.kind(n) == "mrio"]
        dbs.sort(key=lambda n: (roles[n] != "model", n))
        words = q.split()
        if len(words) > 1 and words[-1].lower() in _UNIT_WORDS and not unit:
            unit, q = _UNIT_WORDS[words[-1].lower()], " ".join(words[:-1])
        if not location:
            q, location = regions.find_in_query(q)
    if database:
        dbs = [d for d in dbs if d == database]
    loc = regions.resolve(location) if kind != "flow" else location
    comp = compartment if kind == "flow" else None
    out = _search_once(q, dbs, roles, loc, limit, kind, unit, comp)
    if exact:  # "PM10" means "Particulates, < 10 um", not "> 10 um"
        out.sort(key=lambda r: r["name"].lower() != exact)
    fixed = respell(q, dbs)
    if fixed and len(out) < limit:
        seen = {r["id"] for r in out}
        for row in _search_once(fixed, dbs, roles, loc, limit - len(out), kind, unit, comp):
            if row["id"] not in seen:
                row["spelling"] = fixed
                out.append(row)
    return out


def _search_once(q: str, dbs: list[str], roles: dict, location: str | None, limit: int, kind: str,
                 unit: str | None = None, compartment: str | None = None) -> list[dict]:
    allowed = UNIT_GROUPS.get(unit) if unit else None
    near = regions.chain(location) if location and kind != "flow" else []
    rank = {c: i for i, c in enumerate(near)}
    words = [w for w in re.findall(r"\w+", q.lower()) if len(w) > 1]
    hits = []
    for db in dbs:
        wide = location or allowed or compartment
        for pos, a in enumerate(bd.Database(db).search(q, limit=1000 if wide else max(limit * 2, 100))):
            if allowed is not None and a.get("unit") not in allowed:
                continue
            if compartment and not _in_compartment(a, compartment):
                continue
            if location and kind != "flow":
                if a.get("location") not in rank:
                    continue
            elif location and a.get("location") != location:
                continue
            name = (a.get("name") or "").lower()
            text = f"{name} {(a.get('reference product') or '').lower()}"
            # like the Activity Browser: the words as typed first (all of them in the name, then in name or product),
            # then the search engine's own order
            literal = 0 if words and all(w in name for w in words) else 1 if words and all(w in text for w in words) else 2
            # within that: BAFU's obsolete datasets ("xxx ") last, the words in a row at the start of the name first,
            # then in a row anywhere; then names with fewer other words ("electricity, low voltage, at grid" before
            # "electricity, low voltage, electric utility Obwalden, at grid")
            nw = re.findall(r"\w+", name)
            seq, flat = " ".join(words), " ".join(nw)
            phrase = 0 if seq and flat.startswith(seq) else 1 if seq and seq in flat else 2
            # elementary flows: the compartment without sub-compartment ("emissions to air") before "… / low. pop."
            depth = len(a.get("categories") or ()) if kind == "flow" else 0
            hits.append(((literal, name.startswith("xxx "), phrase), (len(nw) - len(words), depth, pos), a))
    if near:
        # one row per process and product: the nearest location it has
        best: dict[tuple, tuple] = {}
        for h in hits:
            a = h[2]
            # BAFU 2025 puts the location into the product ("… at grid {DE}"): the same product without it
            k = (a.get("name"), re.sub(r"\s*\{[^{}]*\}\s*$", "", a.get("reference product") or ""), a.get("unit"), a["database"])
            if k not in best or rank[a.get("location")] < rank[best[k][2].get("location")]:
                best[k] = h
        hits = sorted(best.values(), key=lambda h: (h[0], rank[h[2].get("location")], h[1]))
    else:
        hits.sort(key=lambda h: (h[0], h[1]))
    out = []
    for _l, _p, a in hits[:limit]:
        row = _act_summary(a)
        row["role"] = roles.get(a["database"])
        if kind != "flow" and a.get("comment"):
            text = " ".join(str(a["comment"]).split())
            row["comment"] = text if len(text) <= 400 else text[:400].rsplit(" ", 1)[0] + " …"
        if kind == "flow":
            row["categories"] = " / ".join(a.get("categories") or ())
        if near and a.get("location") != location:
            row["region"] = location
        out.append(row)
    return out


_vocab: dict = {}


def _vocabulary(dbs: list[str]) -> tuple[set[str], dict[int, list[str]]]:
    """The words of names and reference products in these databases, also by length (for the spelling check)."""
    project = bd.projects.current
    key = (project, tuple(sorted(dbs)), engine.versions(project))
    if key not in _vocab:
        if len(_vocab) > 8:
            _vocab.clear()
        words: set[str] = set()
        for (data,) in AD.select(AD.data).where(AD.database << list(dbs)).tuples():
            text = f"{data.get('name', '')} {data.get('reference product') or ''}".lower()
            words.update(w for w in re.findall(r"[^\W\d_]{3,}", text))
        by_len: dict[int, list[str]] = {}
        for w in words:
            by_len.setdefault(len(w), []).append(w)
        _vocab[key] = (words, by_len)
    return _vocab[key]


def respell(q: str, dbs: list[str]) -> str | None:
    """The search with each unknown word replaced by the closest known one ("steeel" → "steel"); None if nothing changes."""
    import difflib

    words, by_len = _vocabulary(dbs)
    changed, parts = False, []
    for token in q.split():
        lower = token.lower()
        if len(lower) < 4 or not lower.isalpha() or lower in words:
            parts.append(token)
            continue
        # a word cut short ("concret") becomes its shortest completion, a typo ("steeel") the closest word
        pool = [w for n in range(len(lower) - 2, len(lower) + 3) for w in by_len.get(n, ())]
        whole = sorted((w for w in pool if w.startswith(lower)), key=lambda w: (len(w), w))
        best = whole[:1] or difflib.get_close_matches(lower, pool, n=1, cutoff=0.8)
        if best:
            parts.append(best[0])
            changed = True
        else:
            parts.append(token)
    return " ".join(parts) if changed else None


# ---------- activity detail ----------

def activity(activity_id: int | str, method: tuple) -> dict:
    d = models.process_detail(activity_id, tuple(method))
    roles = models.roles()
    if d["editable"]:
        d["edit_mode"] = "model"
    elif is_working_copy() and roles.get(d["database"]) == "background":
        d["edit_mode"] = "copy"
        d["editable"] = True
    else:
        d["edit_mode"] = None
    d["role"] = roles.get(d["database"])
    return d


def allocation_compare(activity_id: int | str, method: tuple) -> dict:
    """The products of a process (or of the process of a product) under every way the process can be split, per unit
    of each product: equally, by each property all products have, as stored by hand. Nothing is saved: the models are
    rebuilt with those shares (engine.with_factors), the rest of the calculation stays as it is."""
    method = tuple(method)
    act = bd.get_node(id=int(activity_id))
    proc = functional.process_of(act)
    if proc is None or not proc.multifunctional:
        raise ValueError(_("«{name}» hat nur ein Produkt: eine Allokation ist nicht nötig.", name=act["name"]))
    if models.roles().get(proc["database"]) != "model":
        raise ValueError(_("Allokationen vergleichen geht für eigene Modelle; Hintergrunddaten sind schon alloziert."))
    S = models.system()
    products = proc.products()
    current = functional.strategy(proc)
    rows = []
    for label in functional.strategies(proc):
        try:
            factors = functional.factors(proc, label)
        except (KeyError, ValueError):
            continue  # a property that is zero for all products, or manual shares that add up to nothing
        S2 = engine.with_factors(S, factors)
        rows.append({"strategy": label, "current": label == current,
                     "factors": {str(k): v for k, v in factors.items()},
                     "scores": {str(p.id): S2.score({p.id: 1.0}, method) for p in products}})
    return {"process": str(proc.id), "name": proc["name"], "unit": short_unit(bd.methods[method].get("unit")),
            "products": [{"id": str(p.id), "name": p.get("product") or p["name"], "unit": short_unit(p.get("unit"))}
                         for p in products],
            "rows": rows}


# ---------- results ----------

def calculate(activity_id: int | str, amount: float, method: tuple, top: int = 12) -> dict:
    """Score, contributions and environmental profile for one product, from the engine."""
    method = tuple(method)
    S = models.system_for(activity_id)
    t = time.perf_counter()
    c = analysis.contributions(S, int(activity_id), amount, method, top)
    profile = []
    fam = [mt for mt in sorted(bd.methods) if mt[0] == PROFILE_FAMILY]
    for mt in fam:
        profile.append({"name": mt[1], "value": S.score({int(activity_id): amount}, mt)})
    profile.sort(key=lambda x: -x["value"])
    seconds = time.perf_counter() - t
    a = bd.get_node(id=int(activity_id))
    return {
        **_act_summary(a),
        **c,
        "amount": amount,
        "method": list(method),
        "method_unit": short_unit(bd.methods[method].get("unit")),
        "seconds": seconds,
        "profile": profile,
        "profile_unit": "UBP",
        "matrix_size": int(len(S.row_ids)),
        "model": models.roles().get(a["database"]) == "model",
        "background": list(S.bg.dbs),
        "counterpart": _counterpart_info(S, a),
        # how many inventory flows the method has no factor for, and how many factors were completed
        "factors": {**analysis.factor_summary(analysis.inventory(S, int(activity_id), amount, method)),
                    "completion": completion.enabled(), "completable": len(completion.candidates(method))},
    }


def _counterpart_info(S, a) -> dict | None:
    """The dataset actually calculated, when `a` is from a background database outside this calculation."""
    if a["database"] not in S.pulled and (a.id in S.col or a["database"] in S.bg.dbs):
        return None
    other = S.counterpart(a.id)
    if other is None:
        return None
    b = bd.get_node(id=other)
    return {"id": str(other), "database": b["database"], "name": b["name"], "location": b.get("location")}


def verify(fus: list[dict], methods: list[tuple]) -> dict:
    """Gegenprobe: recompute with plain bw2calc and report the largest deviation."""
    S = models.system()
    _plain_links(S, _("Die Gegenprobe mit bw2calc"))
    t = time.perf_counter()
    worst, checked = 0.0, 0
    for fu in fus:
        node = bd.get_node(id=int(fu["id"]))
        amount = float(fu["amount"])
        Sx = models.system_for(node.id)  # a sector of EXIOBASE outside the chosen background: on its table alone
        lca = bc.LCA({node: amount}, tuple(methods[0]))
        lca.lci()
        bio_ids = np.array([f for f, _ in sorted(lca.dicts.biosphere.items(), key=lambda kv: kv[1])], dtype=np.int64)
        g = np.asarray(lca.inventory.sum(axis=1)).ravel()
        for m in methods:
            m = tuple(m)
            lca.switch_method(m)
            lca.lcia()
            mine = Sx.score({node.id: amount}, m)
            # factors through the flow mapping and the completion (flowmap.py, completion.py) are not in bw2calc's
            # method: added to its inventory, so both sides use the same factors whether they are on or off
            add = engine.extra_vector(m, bio_ids)
            ref = float(lca.score) + (float(add @ g) if add is not None else 0.0)
            # measure against the gross impact, so results where credits and burdens cancel stay meaningful
            gross = float(abs(lca.characterized_inventory).sum()) + (float(abs(add * g).sum()) if add is not None else 0.0)
            worst = max(worst, abs(mine - ref) / gross if gross > 0 else abs(mine - ref))
            checked += 1
    return {"ok": bool(worst < 1e-6), "max_rel": worst, "checked": checked, "seconds": time.perf_counter() - t}


def graph(activity_id: int | str, amount: float, method: tuple, cutoff: float = 0.01, depth: int = 4,
          max_children: int = 5) -> dict:
    return analysis.tree(models.system_for(activity_id), int(activity_id), amount, tuple(method), cutoff, depth, max_children)


def sankey(activity_id: int | str, amount: float, method: tuple, cutoff: float = 0.02, max_nodes: int = 40) -> dict:
    return analysis.sankey(models.system_for(activity_id), int(activity_id), amount, tuple(method), cutoff, max_nodes)


def inventory(activity_id: int | str, amount: float, method: tuple | None = None) -> list[dict]:
    method = tuple(method) if method and tuple(method) in bd.methods else None
    return analysis.inventory(models.system_for(activity_id), int(activity_id), amount, method)


# ---------- working copies: changing background data ----------

def make_working_copy() -> str:
    reg = registry.load()
    cur = bd.projects.current
    base = reg["copies"].get(cur, {}).get("original", cur)
    n, name = 1, _("{base} – Arbeitskopie", base=base)
    while name in bd.projects:
        n += 1
        name = _("{base} – Arbeitskopie {n}", base=base, n=n)
    bd.projects.copy_project(name, switch=True)
    reg = registry.load()
    reg["copies"][name] = {"original": cur, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "changes": []}
    reg.get("journal", {}).pop(name, None)  # a reused name must not inherit the undo steps of a deleted copy
    OPEN["project"] = name
    models_of = reg.get("models", {}).get(cur)
    if models_of:
        reg.setdefault("models", {})[name] = list(models_of)
    registry.save(reg)
    return name


def edit_exchange(exchange_id: int, amount: float) -> dict:
    """Change an amount: in a model directly, in background data only inside a working copy."""
    exchange_id = int(exchange_id)
    exc = Exchange(ExchangeDataset.get_by_id(exchange_id))
    if models.roles().get(exc.output["database"]) == "model":
        models.update_exchange(exchange_id, amount=amount)
        return {"changed": True}
    cur = bd.projects.current
    reg = registry.load()
    if cur not in reg["copies"]:
        raise ReadOnlyError(_("Dieses Projekt ist ein Original und bleibt unverändert. Lege zuerst eine Arbeitskopie an "
                              "oder kopiere den Prozess in ein eigenes Modell."))
    if not np.isfinite(amount):
        raise ValueError(_("Die Menge muss eine Zahl sein."))
    old = float(exc["amount"])
    if old == amount:
        return {"changed": False}
    output, inp = exc.output, exc.input
    models.rescale_uncertainty(exc, old, float(amount))
    exc["amount"] = float(amount)
    exc.save()
    changes = reg["copies"][cur]["changes"]
    prior = next((c for c in changes if c["exchange"] == exchange_id), None)
    if prior:
        prior["new"] = float(amount)
        if prior["new"] == prior["old"]:
            changes.remove(prior)
    else:
        changes.append({"exchange": exchange_id, "activity_id": str(output.id), "activity": output["name"],
                        "location": output.get("location"), "input": inp["name"], "unit": short_unit(inp.get("unit")),
                        "old": old, "new": float(amount), "time": time.strftime("%Y-%m-%dT%H:%M:%S")})
    registry.save(reg)
    engine.bump_background(cur)
    return {"changed": True}


def undo_change(exchange_id: int) -> dict:
    exchange_id = int(exchange_id)
    cur = bd.projects.current
    change = next((c for c in registry.load()["copies"].get(cur, {}).get("changes", []) if c["exchange"] == exchange_id), None)
    if not change:
        raise KeyError(_("Diese Änderung gibt es nicht."))
    return edit_exchange(exchange_id, change["old"])


# ---------- comparison across projects ----------

def flow_lists(S, demand: dict) -> set[str]:
    """The lists of elementary flows (biosphere databases) a result draws on: those with flows in its inventory."""
    g = S.inventory(S.supply(demand))
    return flowmap.index().dbs_of(np.asarray(S.bio_ids)[g != 0])


def covering_methods(lists: set[str]) -> list[list]:
    """The methods with factors for all these flow lists, their own or through the flow mapping: [method, how]."""
    out = []
    for m in overview._method_list():
        how = flowmap.coverage(m, lists)[0]
        if how != "missing":
            out.append([list(m), how])
    return out


def set_flowmap(on: bool) -> dict:
    flowmap.set_enabled(on)
    return flowmap.info()


def set_completion(on: bool) -> dict:
    """Completed factors for sub-compartments (completion.py): on or off, for all calculations."""
    completion.set_enabled(on)
    return completion.info()


def completed_factors(method: tuple) -> dict:
    """Every factor the completion gives the method (whether switched on or not), for the list in the UI."""
    method = tuple(method)
    if method not in bd.methods:
        raise KeyError(_("Methode fehlt in diesem Projekt"))
    return {"enabled": completion.enabled(), "method": list(method),
            "unit": short_unit(bd.methods[method].get("unit")), "rows": completion.table(method)}


def compare(items: list[dict], method: tuple) -> list[dict]:
    """Score each item (project, activity id, amount). Restores the current project afterwards."""
    method = tuple(method)
    cur = bd.projects.current
    out = []
    try:
        for it in items:
            if bd.projects.current != it["project"]:
                if it["project"] in bd.projects and not project_is_25(it["project"]):
                    out.append({**it, "error": _("Projekt im älteren Format von Brightway 2")})
                    continue
                try:
                    visit(it["project"])
                except (KeyError, ValueError) as e:
                    out.append({**it, "error": str(e).strip("'\"")})
                    continue
            if method not in bd.methods:
                out.append({**it, "error": _("Methode fehlt in diesem Projekt")})
                continue
            try:
                a = bd.get_node(id=int(it["id"]))
                S = models.system(it["background"]) if it.get("background") else models.system_for(it["id"])
                score = S.score({a.id: it["amount"]}, method)
                lists = flow_lists(S, {a.id: it["amount"]})
                add = completion.addition(method, S.bio_ids)
                completed = add is not None and bool((add * S.inventory(S.supply({a.id: it["amount"]}))).any())
            except (bd.errors.UnknownObject, KeyError, engine.ModelError) as e:
                out.append({**it, "error": str(e).strip("'\"") or _("Nicht berechenbar")})
                continue
            how, missing = flowmap.coverage(method, lists)
            out.append({**it, "id": str(it["id"]), "name": a["name"], "location": a.get("location"),
                        "unit": short_unit(a.get("unit")), "score": score, "copy": is_working_copy(),
                        "used": list(S.bg.dbs), "flow_lists": sorted(lists), "coverage": how, "missing": missing, "completed": completed,
                        "covering": covering_methods(lists)})
    finally:
        leave(cur)
    return out


# ---------- why is the copy different? ----------

def explain_difference(activity_id: int | str, amount: float, method: tuple) -> dict:
    """Split the score difference between a working copy and its original onto the changed exchanges.

    Exact, not an approximation. With A0, B0, c0 of the original and x1 the supply of the copy:

        h1 - h0 = -s0 . dA x1  +  c0 . dB x1,        s0 = c0 B0 A0^-1  (unit scores of the original)

    Every changed exchange is one entry of dA (inputs) or dB (emissions), so each contributes one term and the
    terms add up to the difference. The other changes are already in x1, so a part reads "this change, with all
    other changes in place". What the listed changes do not explain (edits made outside the app) is shown as rest.
    """
    method = tuple(method)
    cur = bd.projects.current
    copy = registry.load()["copies"].get(cur)
    if not copy:
        raise ValueError(_("«Warum anders?» gibt es nur in einer Arbeitskopie: dort wird mit dem Original verglichen."))
    node_id, amount = int(activity_id), float(amount)
    S1 = models.system()
    x1 = S1.supply({node_id: amount})
    h1 = S1.score({node_id: amount}, method)
    parts = []
    for ch in copy["changes"]:
        exc = ExchangeDataset.get_by_id(int(ch["exchange"]))
        etype = exc.type
        delta = float(ch["new"]) - float(ch["old"])
        out_id = AD.select(AD.id).where(AD.database == exc.output_database, AD.code == exc.output_code).scalar()
        in_id = AD.select(AD.id).where(AD.database == exc.input_database, AD.code == exc.input_code).scalar()
        parts.append({"change": ch, "type": etype, "delta": delta, "out": out_id, "inp": in_id})
    original = copy["original"]
    try:
        visit(original)
        S0 = models.system()
        h0 = S0.score({node_id: amount}, method)
        s0, c0 = S0.unit_scores(method), S0.cvec(method)
        info = analysis.node_info([node_id] + [p["out"] for p in parts] + [p["inp"] for p in parts])
        # The matrices hold the values as stored (float32 in processed data), so the exact change of an entry is
        # taken from the two matrices, not from the typed amounts. Exchanges sharing one entry split it by their change.
        entries: dict[tuple, dict] = {}
        for p in parts:
            kind = "emission" if p["type"] in engine.BIOSPHERE else "input"
            key = (kind, p["inp"], p["out"])
            e = entries.setdefault(key, {"rows": [], "val": None, "total": 0.0})
            e["rows"].append(p)
            e["total"] += p["delta"]
            if len(e["rows"]) > 1:
                continue
            j0, j1 = S0.col.get(int(p["out"])), S1.col.get(int(p["out"]))
            if j0 is None or j1 is None:
                continue
            if kind == "emission":
                k0, k1 = S0.bio_row.get(int(p["inp"])), S1.bio_row.get(int(p["inp"]))
                if k0 is not None and k1 is not None:
                    d = float(S1.B[k1, j1] - S0.B[k0, j0])
                    e["val"], e["used"] = c0[k0] * d * x1[S1.col[int(p["out"])]], float(x1[j1])
            else:
                i0, i1 = S0.row.get(int(p["inp"])), S1.row.get(int(p["inp"]))
                if i0 is not None and i1 is not None:
                    d = float(S1.A[i1, j1] - S0.A[i0, j0])
                    e["val"], e["used"] = -s0[i0] * d * x1[j1], float(x1[j1])
        rows = []
        for (kind, *_entry), e in entries.items():  # not `_`: that is the translation function here
            for p in e["rows"]:
                ch = p["change"]
                w = p["delta"] / e["total"] if e["total"] else 1.0 / len(e["rows"])
                rows.append({"exchange": str(ch["exchange"]), "kind": kind, "activity": ch["activity"], "location": ch.get("location"),
                             "activity_id": str(p["out"]), "input": ch["input"], "unit": ch.get("unit"), "old": ch["old"], "new": ch["new"],
                             "used": e.get("used", 0.0), "contribution": e["val"] * w if e["val"] is not None else None})
    finally:
        leave(cur)
    explained = sum(r["contribution"] for r in rows if r["contribution"] is not None)
    for r in rows:
        r["share"] = (r["contribution"] / (h1 - h0)) if r["contribution"] is not None and h1 != h0 else None
    rows.sort(key=lambda r: -abs(r["contribution"] or 0.0))
    return {"product": {**info[node_id], "amount": amount}, "method": list(method), "unit": short_unit(bd.methods[method].get("unit")),
            "original": original, "score_original": h0, "score_copy": h1, "difference": h1 - h0, "explained": explained,
            "rest": (h1 - h0) - explained, "parts": rows}


# ---------- uncertainty (Monte-Carlo) ----------

def monte_carlo_start(fus: list[dict], methods: list[tuple], n: int = 500, seed: int | None = None,
                      workers: int | None = None) -> dict:
    """Start a coupled Monte-Carlo run in the background; returns the job status."""
    if not fus or not methods:
        raise ValueError(_("Für die Unsicherheitsrechnung braucht es mindestens ein Produkt und eine Methode."))
    S = models.system()
    S.fg.check()
    _plain_links(S, _("Die Unsicherheitsrechnung"))
    # own models are read from SQLite by the engine, but bw2calc in the workers needs their processed data
    for name in models.model_databases() & set(bd.databases):
        bd.Database(name).process()
    pairs = [(int(f["id"]), float(f["amount"])) for f in fus]
    methods = [tuple(m) for m in methods]
    info = analysis.node_info(i for i, _ in pairs)
    reference = analysis.score_table(S, pairs, methods)  # deterministic scores, [method][product]
    meta = {
        "fus": [{**info.get(i, {"id": str(i), "name": "?"}), "amount": a} for i, a in pairs],
        "methods": [{"id": list(m), "unit": short_unit(bd.methods[m].get("unit"))} for m in methods],
        "reference": reference,
    }

    def describe(draws):
        return {**meta, **montecarlo.summarize(draws), "better": montecarlo.better_matrix(draws)}

    job = montecarlo.start(bd.projects.current, pairs, methods, int(n), int(seed if seed is not None else time.time()) % 2**31,
                           workers, describe)
    return job.status()


def monte_carlo_status(job_id: str) -> dict:
    job = montecarlo.JOBS.get(job_id)
    if job is None:
        raise KeyError(_("Diese Unsicherheitsrechnung gibt es nicht (mehr)."))
    return job.status()


def sensitivity_start(fu: dict, method: tuple, n: int = 300, seed: int | None = None, workers: int | None = None) -> dict:
    """Start the analysis "which uncertain data drive the spread" for one product and method."""
    S = models.system()
    S.fg.check()
    _plain_links(S, _("Die Unsicherheitsrechnung"))
    for name in models.model_databases() & set(bd.databases):
        bd.Database(name).process()
    pair = (int(fu["id"]), float(fu["amount"]))
    method = tuple(method)
    info = analysis.node_info([pair[0]])
    meta = {"fu": {**info.get(pair[0], {"id": str(pair[0]), "name": "?"}), "amount": pair[1]},
            "method": {"id": list(method), "unit": short_unit(bd.methods[method].get("unit"))},
            "reference": float(S.score({pair[0]: pair[1]}, method))}

    def describe(raw):
        sc = raw["scores"]
        nodes = analysis.node_info([e[k] for e in raw["entries"] for k in ("supplier", "consumer")])
        entries = [{**e, "supplier": nodes.get(e["supplier"], {"name": "?"}), "consumer": nodes.get(e["consumer"], {"name": "?"})}
                   for e in raw["entries"]]
        return {**meta, "n": len(sc), "entries": entries, "candidates": raw["candidates"], "noise_floor": raw["noise_floor"],
                "linear_share": raw["linear_share"], "ctv_top": raw["ctv_top"], "sobol": raw["sobol"],
                "score": {"mean": float(sc.mean()), "std": float(sc.std(ddof=1)), "median": float(np.median(sc)),
                          "p5": float(np.percentile(sc, 5)), "p95": float(np.percentile(sc, 95))}}

    job = montecarlo.start_sensitivity(bd.projects.current, pair, method, int(n),
                                       int(seed if seed is not None else time.time()) % 2**31, workers, describe)
    return job.status()


# ---------- changes from outside (Activity Browser, scripts) ----------
#
# Another program can change the project while the app is open. Brightway writes every change to
# lci/databases.db and the database list (databases.json, with a "modified" time per database), so
# those files are compared before every request. Our own writes are acknowledged after each request.

_WATCHED = ("lci/databases.db", "lci/databases.db-wal", "databases.json", "methods.json", "setups.pickle")
_known: dict[str, dict] = {}  # project -> {"stamp", "mods", "roles"}
EXTERNAL: dict = {"count": 0, "what": []}


def _stamp() -> tuple:
    out = []
    for rel in _WATCHED:
        try:
            st = (Path(bd.projects.dir) / rel).stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _snapshot() -> dict:
    return {"stamp": _stamp(), "mods": {n: str(m.get("modified")) for n, m in bd.databases.items()},
            "roles": dict(models.roles())}


def acknowledge() -> None:
    """Remember the current state of the project files as our own (call after every request)."""
    if project_open():
        _known[bd.projects.current] = _snapshot()


def sync_external() -> bool:
    """If another program changed the project: reload it and drop the caches. True when that happened."""
    if not project_open():
        return False
    project = bd.projects.current
    known = _known.get(project)
    if known is None:
        _known[project] = _snapshot()
        return False
    if _stamp() == known["stamp"]:
        return False
    _require_readable(project)  # emptied by a failed write elsewhere (repair.py): say so, not a JSON error
    if project not in bd.projects:  # deleted by another program: set_current would create it again, empty
        OPEN["project"] = None
        _known.pop(project, None)
        EXTERNAL["count"] += 1
        EXTERNAL["what"] = [project]
        return True
    bd.projects.set_current(project, update=False)  # re-reads databases, methods and setups from disk
    engine.bump_foreground(project)
    snap = _snapshot()
    changed = sorted(n for n in set(known["mods"]) | set(snap["mods"]) if known["mods"].get(n) != snap["mods"].get(n))
    role = lambda n: snap["roles"].get(n) or known["roles"].get(n)  # noqa: E731
    in_use = engine.backgrounds_in_use(project)
    if any(role(n) != "model" and (n in in_use or known["roles"].get(n) != snap["roles"].get(n) and n in known["roles"])
           for n in changed):
        engine.bump_background(project)  # only a changed background database in use forces the slow rebuild
    if any(role(n) == "model" for n in changed):
        reg = registry.load()
        if reg.get("journal", {}).pop(project, None) is not None:  # old undo steps could overwrite the outside change
            registry.save(reg)
    _known[project] = _snapshot()
    EXTERNAL["count"] += 1
    EXTERNAL["what"] = changed
    return True


def poll() -> dict:
    return {"external": EXTERNAL["count"], "what": EXTERNAL["what"]}
