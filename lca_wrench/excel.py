"""Excel export and import of own models, in the format bw2io and the Activity Browser use.

Export is bw2io's `write_lci_excel`, plus database and reference product of every exchange's partner.
Import is bw2io's `ExcelImporter`; exchanges that carry database and reference product link exactly, others
(files from elsewhere) by name, unit and location (and categories where they help). Nothing is written unless
every exchange finds exactly one partner, so a half-linked model never lands in the project.

Parameters travel with the file (bw2io's sections «Project parameters», «Database parameters», «Parameters» per
activity, and the formula column of exchanges). On import they are checked in memory first and then written the
way the Parameter view writes them: groups are named after the new model (the file's group names carry the old
model name and would clash with the original in the same project), project parameters that already exist keep
their value here.
"""

from __future__ import annotations

import re
import tempfile
import warnings
from pathlib import Path
from unittest import mock

import bw2data as bd

from . import models, params
from .i18n import _, q

MAX_BYTES = 25 * 1024 * 1024

# Partner fields that identify a process or a flow exactly (database is one of bw2io's own exchange columns).
# Not the categories of processes: bw2io leaves list values out of the activity rows, so they would not match.
EXACT_PROCESS = ("name", "reference product", "unit", "location", "database")
EXACT_FLOW = ("name", "unit", "categories", "database")


def _formatter():
    """bw2io's formatter, plus database and reference product of each exchange's partner.

    bw2io writes only name, unit, location and categories of the partner. That is not unique for a background
    process copied into the model (same name) or for multi-product processes (ecoinvent)."""
    from bw2io.export.csv import CSVFormatter

    class Formatter(CSVFormatter):
        def exchange_as_dict(self, exc):
            data = super().exchange_as_dict(exc)
            data["database"] = exc.input["database"]
            if exc.input.get("reference product"):
                data["reference product"] = exc.input["reference product"]
            return data

    return Formatter


def export_model(db_name: str) -> tuple[bytes, str]:
    """The model database as .xlsx bytes plus a file name."""
    models._require_model_db(db_name)
    if models.functional.is_functional(db_name):
        raise ValueError(_("Für Modelle im Format des Activity Browser 3 (mehrere Produkte pro Prozess) geht das noch nicht."))
    import bw2io.export.excel as xl

    # write_lci_excel has no hook for the exchange columns; requests run one at a time (service.LOCK)
    with tempfile.TemporaryDirectory(prefix="lca-wrench-xlsx-") as d, warnings.catch_warnings(), \
            mock.patch.object(xl, "CSVFormatter", _formatter()):
        warnings.simplefilter("ignore")
        path = Path(xl.write_lci_excel(db_name, dirpath=d))
        data = path.read_bytes()
    return data, re.sub(r'[\\/:*?"<>|]+', "_", db_name) + ".xlsx"


def import_model(data: bytes, name: str | None = None) -> dict:
    """Create a new model database from an .xlsx file. Returns {database, processes}."""
    if not data:
        raise ValueError(_("Die Datei ist leer."))
    if len(data) > MAX_BYTES:
        raise ValueError(_("Die Datei ist zu gross (höchstens 25 MB)."))
    if not data.startswith(b"PK"):
        raise ValueError(_("Das ist keine Excel-Datei (.xlsx)."))
    import bw2io

    with tempfile.TemporaryDirectory(prefix="lca-wrench-xlsx-") as d, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        path = Path(d) / "import.xlsx"
        path.write_bytes(data)
        try:
            imp = bw2io.ExcelImporter(str(path))
            imp.apply_strategies()
        except Exception as e:  # damaged or foreign layout
            raise ValueError(_("Die Excel-Datei lässt sich nicht lesen (erwartet wird das Format von bw2io / Activity Browser): {error}",
                               error=e)) from e
        old = imp.db_name
        new = _free_name((name or old or "Import").strip())
        _rename(imp, old, new)
        _drop_foreign_links(imp)
        roles = models.roles()
        background = [n for n, r in roles.items() if r == "background"]
        biosphere = [n for n, r in roles.items() if r == "biosphere"]
        with_ref = lambda e: bool(e.get("reference product"))  # noqa: E731
        without_ref = lambda e: not with_ref(e)  # noqa: E731
        # written by LCA Wrench: database and reference product of the partner are in the file
        _match(imp, new, [new] + background, EXACT_PROCESS, lambda e: bool(e.get("database")) and e.get("type") != "biosphere")
        _match(imp, new, biosphere, EXACT_FLOW, lambda e: bool(e.get("database")) and e.get("type") == "biosphere")
        # databases named differently here: an exchange that names its product links only to that product
        _match(imp, new, background + [new], ("name", "reference product", "unit", "location"), with_ref)
        # files from elsewhere (Activity Browser, older exports)
        for fields in (("name", "unit", "location", "categories"), ("name", "unit", "location")):
            _match(imp, new, background, fields, without_ref)
        for fields in (("name", "unit", "categories"), ("name", "categories")):
            _match(imp, new, biosphere, fields, without_ref)
        _match(imp, new, [new], ("name", "unit", "location"), without_ref)
        unlinked = _unlinked(imp)
        if unlinked:
            shown = "; ".join(f"{q(n)} ({u}, {loc})" for n, u, loc in unlinked[:8])
            raise ValueError(_("{n} Austausch(e) lassen sich keinem Datensatz im Projekt zuordnen, zum Beispiel: {shown}. "
                               "Das Modell wurde nicht importiert.", n=len(unlinked), shown=shown))
        for ds in imp.data:  # only needed for linking, the link itself is in "input"
            for e in ds.get("exchanges", []):
                e.pop("database", None)
                e.pop("reference product", None)
        plan = _parameters_from_file(imp, new)
        n = len(imp.data)
        imp.write_database(activate_parameters=False)
    models.add_model(new)
    try:
        added = _activate_parameters(new, plan)
    except Exception:
        models.delete_database(new)
        raise
    models.register_model(new, project_params=added)
    return {"database": new, "processes": n, "kept_project_parameters": plan["kept"]}


_NOT_DATA = {"name", "amount", "formula", "database", "code", "group"}


def _param(d: dict) -> dict:
    formula = d.get("formula")
    formula = str(formula).strip() if formula not in (None, "") else None
    amount = d.get("amount")
    return {"amount": float(amount) if isinstance(amount, (int, float)) else None, "formula": formula,
            "data": {k: v for k, v in d.items() if k not in _NOT_DATA and v is not None}}


def _parameters_from_file(imp, new: str) -> dict:
    """Take the parameters out of the import (bw2io would write them under the file's group names) and check them
    together with the parameters already in the project. Raises ValueError, nothing is written then."""
    have = params.state()
    project = {d["name"]: _param(d) for d in imp.project_parameters or [] if d.get("name")}
    kept = sorted(n for n in project if n in have["project"])
    database = {d["name"]: _param(d) for d in imp.database_parameters or [] if d.get("name")}
    imp.project_parameters = imp.database_parameters = None
    groups, formulas = {}, {}
    for ds in imp.data:
        g = params.group_of(new, ds["code"])
        ps = {d["name"]: _param(d) for d in ds.pop("parameters", None) or [] if d.get("name")}
        fs = [str(e["formula"]).strip() for e in ds.get("exchanges", [])
              if e.get("type") != "production" and e.get("formula") not in (None, "")]
        if fs and not ps:  # exchange formulas need a group; Brightway and the Activity Browser use a dummy
            ps[f"{params.DUMMY}{ds['code']}__"] = {"amount": 0.0, "formula": None, "data": {}}
        if ps:
            groups[g] = {"database": new, "code": ds["code"], "params": ps}
        formulas.update({(g, i): {"group": g, "formula": f} for i, f in enumerate(fs)})
    trial = {"project": {**project, **have["project"]}, "database": {**have["database"], new: database},
             "groups": {**have["groups"], **groups}, "exchanges": formulas}
    try:
        params._evaluate(trial)
    except ValueError as e:
        raise ValueError(_("Die Parameter in der Datei lassen sich nicht berechnen: {error} Das Modell wurde nicht importiert.",
                           error=e)) from None
    return {"project": {n: p for n, p in project.items() if n not in kept}, "database": database, "groups": groups,
            "kept": kept, "has_formulas": bool(formulas)}


def _activate_parameters(new: str, plan: dict) -> list[str]:
    """Write the checked parameters of an imported model; returns the project parameters that were added."""
    if not (plan["project"] or plan["database"] or plan["groups"]):
        return []
    st = params.state()
    st["project"].update(plan["project"])
    st["database"][new] = plan["database"]
    st["groups"].update(plan["groups"])
    for act in bd.Database(new):
        g = params.group_of(new, act["code"])
        for exc in act.exchanges():
            if exc["type"] != "production" and exc.get("formula") not in (None, ""):
                st["exchanges"][exc._document.id] = {"group": g, "formula": str(exc["formula"]).strip(),
                                                     "amount": exc["amount"], "original_amount": exc.get("original_amount")}
    params._write(st)
    return sorted(plan["project"])


def _free_name(name: str) -> str:
    if name not in bd.databases:
        return name
    i = 1
    while True:
        cand = f"{name} (Import{'' if i == 1 else ' ' + str(i)})"
        if cand not in bd.databases:
            return cand
        i += 1


def _rename(imp, old: str, new: str) -> None:
    """Point the activities and all internal links to the new database name (strategies linked them to the old one)."""
    imp.db_name = new
    for ds in imp.data:
        ds["database"] = new
        for exc in ds.get("exchanges", []):
            inp = exc.get("input")
            if inp and inp[0] == old:
                exc["input"] = (new, inp[1])
            if exc.get("database") == old:
                exc["database"] = new


def _drop_foreign_links(imp) -> None:
    """Undo links bw2io made inside the file to a process of another database than the exchange names.

    bw2io links within the file by name, reference product, unit and location. A background process copied into
    the model keeps all of these, so an input of the background original would end up at the copy."""
    for ds in imp.data:
        for e in ds.get("exchanges", []):
            if e.get("input") and e.get("database") and e["input"][0] != e["database"]:
                del e["input"]


def _match(imp, new: str, dbs: list[str], fields: tuple, select=lambda e: True) -> None:
    """Link the still unlinked exchanges chosen by `select` against `dbs` (`new` is the imported model itself)."""
    from bw2io.errors import StrategyError
    from bw2io.strategies import link_iterable_by_fields

    # same exchange dicts, so links land in imp.data
    view = [{"exchanges": [e for e in ds.get("exchanges", []) if not e.get("input") and select(e)]} for ds in imp.data]
    for db in dbs:
        if not any(not e.get("input") for ds in view for e in ds["exchanges"]):
            return
        # called directly: bw2io's match_database only prints a StrategyError and then leaves every exchange unlinked
        try:
            link_iterable_by_fields(view, other=imp.data if db == new else bd.Database(db), fields=fields)
        except StrategyError:
            raise ValueError(_ambiguous_message(view, imp.data if db == new else bd.Database(db), fields)) from None


def _ambiguous_message(view, other, fields: tuple) -> str:
    """Name the exchanges that fit several datasets (same name, unit and location, e.g. multi-product processes)."""
    from bw2io.utils import activity_hash

    seen, dup = set(), set()
    for ds in other:
        key = activity_hash(ds, fields)
        (dup if key in seen else seen).add(key)
    hits = list(dict.fromkeys((e.get("name"), e.get("unit"), e.get("location") or "–") for ds in view
                              for e in ds["exchanges"] if not e.get("input") and activity_hash(e, fields) in dup))
    shown = "; ".join(f"{q(n)} ({u}, {loc})" for n, u, loc in hits[:8])
    return _("{n} Austausch(e) passen auf mehrere Datensätze im Projekt (gleicher Name, gleiche Einheit, gleicher Ort, "
             "z. B. bei Prozessen mit mehreren Produkten), zum Beispiel: {shown}. Das Modell wurde nicht importiert.",
             n=len(hits), shown=shown)


def _unlinked(imp) -> list[tuple]:
    out, seen = [], set()
    for ds in imp.data:
        for e in ds.get("exchanges", []):
            if not e.get("input"):
                key = (e.get("name"), e.get("unit"), e.get("location") or "–")
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


__all__ = ["export_model", "import_model"]
