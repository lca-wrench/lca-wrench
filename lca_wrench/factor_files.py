"""Factors by location from a file the user loads: the EF 3.1 characterization factors of the JRC.

The JRC publishes the EF 3.1 factors as an Excel workbook ("EF-LCIAMethod_CF(EF-v3.1).xlsx" in the EF reference
package 3.1), sheet `lciamethods_CF`, with a factor per country for some categories: water use (AWARE, 209
countries), land use (212 locations), acidification and terrestrial eutrophication (36 European countries). A blank
location is the default. Brightway implementations of EF 3.1 carry only the default. The licence of the reference
package does not say whether it may be redistributed, so LCA Wrench bundles none of it: the user loads their own copy
once, the factors by location are kept on this computer (next to lca-wrench.json, never in a project) and apply in
every project.

A loaded table applies to a method when the method's factors on the table's flows (matched by UUID, the code of the
EF 3.1 flow list) equal the table's defaults: the method is the category the table was made for. Only flows whose
factor differs between locations are kept. regional.py gives the method's own factors precedence: its rows with a
location, then its country copies, then a loaded table.
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import io
import json
import threading
from pathlib import Path

from .i18n import _

MAX_BYTES = 100 * 1024 * 1024
SHEET = "lciamethods_CF"
FORMAT = "lca-wrench factors by location 1"
TOLERANCE = 1e-3  # relative: the JRC default -42.955 against -42.95 in a Brightway implementation

_lock = threading.RLock()
_cache: dict = {}  # file id -> (mtime, table); (project, "ids", stamps) -> {uuid: [flow ids]}


def folder() -> Path:
    from . import registry

    return registry.path().parent / "lca-wrench-regional"


# ---------- reading the workbook ----------

def read_ef(data: bytes) -> dict:
    """The factors by location of the JRC's EF workbook: {"version", "methods": {name: {"uuid", "flows": {flow uuid:
    {"name", "compartment", "default", "locations": {code: factor}}}}}}, only flows whose factor varies by location."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - zipfile, XML or openpyxl errors: not a workbook
        raise ValueError(_("Das ist keine Excel-Datei, die sich lesen lässt ({error}).", error=type(e).__name__)) from e
    try:
        if SHEET not in wb.sheetnames:
            raise ValueError(_("In der Datei fehlt das Blatt «{sheet}». Erwartet wird die Excel-Datei der "
                               "EF-3.1-Faktoren der JRC (EF-LCIAMethod_CF).", sheet=SHEET))
        rows = wb[SHEET].iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
        col = {h: i for i, h in enumerate(header) if h}
        cf_col = next((h for h in header if h.upper().startswith("CF")), None)
        uuid_col = next((h for h in header if h.startswith("LCIAMethod_uuid")), None)
        need = ["FLOW_uuid", "LCIAMethod_name", "LCIAMethod_location"]
        if cf_col is None or any(h not in col for h in need):
            raise ValueError(_("Im Blatt «{sheet}» fehlen Spalten (FLOW_uuid, LCIAMethod_name, CF, LCIAMethod_location).",
                               sheet=SHEET))
        i_flow, i_name, i_cf, i_loc = col["FLOW_uuid"], col["LCIAMethod_name"], col[cf_col], col["LCIAMethod_location"]
        i_uuid = col.get(uuid_col)
        i_fname, i_c1, i_c2 = col.get("FLOW_name"), col.get("FLOW_class1"), col.get("FLOW_class2")
        defaults: dict[tuple, float] = {}
        located: dict[tuple, dict[str, float]] = {}
        info: dict[tuple, tuple] = {}
        uuids: dict[str, str] = {}
        width = max(i_flow, i_name, i_cf, i_loc) + 1
        for r in rows:
            if len(r) < width or r[i_flow] is None or r[i_name] is None or not isinstance(r[i_cf], (int, float)):
                continue
            k = (str(r[i_name]).strip(), str(r[i_flow]).strip())
            loc = str(r[i_loc]).strip() if r[i_loc] is not None else ""
            if loc in ("", "GLO"):
                defaults[k] = float(r[i_cf])
                continue
            located.setdefault(k, {})[loc] = float(r[i_cf])
            if k not in info:
                pick = lambda i: (str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else "")  # noqa: E731
                info[k] = (pick(i_fname), " / ".join(x for x in (pick(i_c1), pick(i_c2)) if x))
                if i_uuid is not None:
                    uuids.setdefault(k[0], pick(i_uuid))
    finally:
        wb.close()
    methods: dict[str, dict] = {}
    for k, locs in located.items():
        d = defaults.get(k)
        if d is None or all(abs(v - d) <= 1e-12 * max(abs(d), 1e-300) for v in locs.values()):
            continue  # no default to recognise the method by, or the same factor everywhere
        m = methods.setdefault(k[0], {"uuid": uuids.get(k[0], ""), "flows": {}})
        m["flows"][k[1]] = {"name": info[k][0], "compartment": info[k][1], "default": d, "locations": locs}
    if not methods:
        raise ValueError(_("In der Datei stehen keine Faktoren, die vom Ort abhängen."))
    version = cf_col[2:].strip().replace(" ", "") or "EF"  # "CF EF3.1" -> "EF3.1"
    return {"version": version, "methods": methods}


# ---------- loading, keeping, removing ----------

def _id(version: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "-" for ch in version.lower()) or "ef"


def load(data: bytes, filename: str) -> dict:
    """Read a workbook and keep its factors by location on this computer; replaces one of the same version."""
    if len(data) > MAX_BYTES:
        raise ValueError(_("Die Datei ist zu gross (höchstens {n} MB).", n=MAX_BYTES // (1024 * 1024)))
    table = read_ef(data)  # the slow part; it needs no Brightway project
    return store(table, filename, hashlib.sha256(data).hexdigest())


def store(table: dict, filename: str, sha256: str = "") -> dict:
    from . import registry

    fid = _id(table["version"])
    folder().mkdir(parents=True, exist_ok=True)
    path = folder() / f"{fid}.json.gz"
    tmp = path.with_suffix(".tmp")
    payload = {"format": FORMAT, "id": fid, "source": filename, "sha256": sha256, **table}
    tmp.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
    tmp.replace(path)
    entry = {"id": fid, "version": table["version"], "file": filename, "stored": path.name,
             "loaded": datetime.date.today().isoformat(), "sha256": sha256,
             "methods": {n: {"flows": len(m["flows"]),
                             "locations": len({loc for f in m["flows"].values() for loc in f["locations"]})}
                         for n, m in sorted(table["methods"].items())}}
    reg = registry.load()
    reg["factor_files"] = {**reg.get("factor_files", {}), fid: entry}
    registry.save(reg)
    _changed()
    return entry


def unload(fid: str) -> None:
    from . import registry

    reg = registry.load()
    entry = reg.get("factor_files", {}).pop(fid, None)
    if entry is None:
        raise KeyError(_("Diese Datei mit Faktoren nach Ort ist nicht geladen."))
    registry.save(reg)
    (folder() / entry["stored"]).unlink(missing_ok=True)
    _changed()


def files() -> list[dict]:
    """The loaded files, for the UI."""
    from . import registry

    return sorted(registry.load().get("factor_files", {}).values(), key=lambda e: e["id"])


def _changed() -> None:
    from . import engine, regional

    with _lock:
        _cache.clear()
    regional.forget()
    engine.bump_all()


def _table(entry: dict) -> dict | None:
    path = folder() / entry["stored"]
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None  # the registry names a file that is gone: nothing applies
    with _lock:
        hit = _cache.get(entry["id"])
        if hit and hit[0] == mtime:
            return hit[1]
    try:
        table = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError, EOFError):
        return None
    with _lock:
        _cache[entry["id"]] = (mtime, table)
    return table


# ---------- applying ----------

def _flow_ids(uuids: set[str]) -> dict[str, list[int]]:
    """Flow ids of the current project by code (the EF flow list uses the flow UUID as code)."""
    import bw2data as bd
    from bw2data.backends import ActivityDataset as AD

    k = (bd.projects.current, "ids", tuple(sorted((n, str(m.get("modified"))) for n, m in bd.databases.items())))
    with _lock:
        if k not in _cache:
            for old in [o for o in _cache if isinstance(o, tuple) and o[0] == k[0] and o[1] == "ids"]:
                del _cache[old]
            _cache[k] = {}
        known = _cache[k]
    todo = sorted(uuids - set(known))
    found: dict[str, list[int]] = {u: [] for u in todo}
    for i in range(0, len(todo), 500):
        for nid, code in AD.select(AD.id, AD.code).where(AD.code << todo[i:i + 500]).tuples():
            found[code].append(nid)
    with _lock:
        known.update(found)
        return {u: known.get(u, []) for u in uuids}


def factors_for(normal: dict[int, float]):
    """(flow id, location, factor, file id) of every loaded table that matches the method with these normal factors.

    A table matches when the method has factors on some of its flows and at least 90 % of them equal the table's
    default; the flows that do get the table's factors by location."""
    for entry in files():
        table = _table(entry)
        if not table:
            continue
        for m in table["methods"].values():
            ids = _flow_ids(set(m["flows"]))
            shared = [(fid, f) for u, f in m["flows"].items() for fid in ids.get(u, ()) if fid in normal]
            if not shared:
                continue
            same = [(fid, f) for fid, f in shared
                    if abs(normal[fid] - f["default"]) <= TOLERANCE * max(abs(f["default"]), 1e-12)]
            if len(same) < 0.9 * len(shared):
                continue
            for fid, f in same:
                for loc, v in f["locations"].items():
                    yield fid, loc, v, entry["id"]
