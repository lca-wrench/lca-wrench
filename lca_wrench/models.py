"""Own models: databases, processes and exchanges the user builds.

Model databases are ordinary Brightway databases (sqlite backend), so the
Activity Browser opens them too. Background databases are never written here.

Every change is logged with its inverse, so each step can be undone.
"""

from __future__ import annotations

import time
import uuid

import bw2data as bd
from bw2data.backends.proxies import Exchange
from bw2data.backends.schema import ActivityDataset as AD
from bw2data.backends.schema import ExchangeDataset

from . import engine, functional, registry
from .analysis import node_info, short_unit
from .i18n import _, msg, q, render

JOURNAL_MAX = 300


class ReadOnlyError(Exception):
    """Raised when an edit targets data that must stay unchanged."""


# ---------- which databases are models ----------

def model_databases() -> set[str]:
    reg = registry.load()
    return {d for d in reg.get("models", {}).get(bd.projects.current, []) if d in bd.databases}


def roles() -> dict[str, str]:
    return engine.database_roles(model_databases())


def is_own_copy(project: str | None = None) -> bool:
    """A project LCA Wrench copied (working copy or test copy): its original stays as it is."""
    reg = registry.load()
    project = project or bd.projects.current
    return project in reg["copies"] or project in reg.get("testcopies", {})


def writable_databases() -> set[str]:
    """Foreground databases LCA Wrench may change: the models made in it, and in its own copies every one.
    A database from somewhere else (Activity Browser, a supplier) is calculated live, but only changed in a copy."""
    mine = model_databases() | ({n for n in bd.databases} if is_own_copy() else set())
    return {n for n, r in roles().items() if r == "model" and n in mine}


def system(background: list[str] | None = None) -> engine.System:
    """The system to calculate with: the models on the chosen background (backgrounds.py), or on `background`."""
    from . import backgrounds

    mdbs = model_databases()
    if background:
        return engine.system(mdbs, background)
    ch = backgrounds.choice(engine.database_roles(mdbs))
    # automatic: the models keep their links (a model on a scenario stays on it); counterparts only when chosen
    return engine.system(mdbs, ch["databases"], substitute=ch["mode"] != "auto")


def system_for(node_id: int | str) -> engine.System:
    """The system to calculate this dataset with.

    Usually the system of the chosen background. In automatic mode (all process data, without scenarios and EXIOBASE)
    a dataset of a background database the calculation leaves out is calculated on its own database: a dataset of a
    premise scenario is that scenario's, not "the same dataset today" (it always has that counterpart in ecoinvent,
    which used to give today's result). With a background chosen, a dataset of another one is calculated with its
    counterpart there (today's electricity on the 2040 scenario); without one, again on its own database."""
    from . import backgrounds

    S = system()
    db = AD.select(AD.database).where(AD.id == int(node_id)).scalar()
    rl = roles()
    if db and rl.get(db) == "background":
        ch = backgrounds.choice(rl)
        if ch["mode"] == "auto" and db not in ch["databases"]:
            return engine.alone(db)
    try:
        S.ref_row(int(node_id))
        return S
    except KeyError:
        if db and rl.get(db) == "background":
            return engine.alone(db)
        raise


def _require_model_db(name: str) -> None:
    if roles().get(name) == "model" and name not in writable_databases():
        raise ReadOnlyError(_("«{name}» wurde nicht in LCA Wrench angelegt (z.B. im Activity Browser). Damit dort nichts "
                              "verloren geht, ändert LCA Wrench sie nur in einer Kopie des Projekts: oben in der "
                              "Projektauswahl eine Testkopie anlegen.", name=name))
    if roles().get(name) != "model":
        raise ReadOnlyError(_("«{name}» ist eine Hintergrund-Datenbank und bleibt unverändert. "
                              "Kopiere den Prozess in ein eigenes Modell, um ihn zu ändern.", name=name))
    if functional.is_functional(name):
        functional.ensure_current()  # bw_functional's data structure, before LCA Wrench writes into it


def _require_model_node(node) -> None:
    _require_model_db(node["database"])


def _entry(label: tuple, undo: dict) -> dict:
    """A journal step; the label is an i18n.msg (shown in the reader's language), "label" stays for older readers."""
    return {"label": label[0].format(**dict(label[1])), "msg": [label[0], dict(label[1])],
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "undo": undo}


def _changed(label: tuple, undo: dict) -> None:
    project = bd.projects.current
    engine.bump_foreground(project)
    reg = registry.load()
    j = reg.setdefault("journal", {}).setdefault(project, [])
    j.append(_entry(label, undo))
    del j[:-JOURNAL_MAX]
    registry.save(reg)


def squash_journal(since: int, label: tuple, undo: dict) -> None:
    """Replace all journal entries from position `since` by one step (e.g. a generated example)."""
    project = bd.projects.current
    reg = registry.load()
    j = reg.setdefault("journal", {}).setdefault(project, [])
    del j[since:]
    j.append(_entry(label, undo))
    registry.save(reg)


def journal_length() -> int:
    return len(registry.load().get("journal", {}).get(bd.projects.current, []))


def journal() -> list[dict]:
    reg = registry.load()
    return [{"n": i, "label": render(e.get("msg") or e["label"]), "time": e["time"]}
            for i, e in enumerate(reg.get("journal", {}).get(bd.projects.current, []))][::-1]


# ---------- databases ----------

def create_database(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError(_("Bitte einen Namen eingeben."))
    if name in bd.databases:
        raise ValueError(_("Eine Datenbank «{name}» gibt es schon.", name=name))
    db = bd.Database(name)
    db.register(backend="sqlite", description="Own model, made in LCA Wrench")
    reg = registry.load()
    lst = reg.setdefault("models", {}).setdefault(bd.projects.current, [])
    if name not in lst:
        lst.append(name)
    registry.save(reg)
    engine.bump_foreground(bd.projects.current)
    return name


def add_model(name: str) -> None:
    """Mark an existing database as an own model of the current project."""
    reg = registry.load()
    lst = reg.setdefault("models", {}).setdefault(bd.projects.current, [])
    if name not in lst:
        lst.append(name)
    registry.save(reg)


def register_model(name: str, project_params=()) -> None:
    """Register an existing (e.g. imported) database as a model of the current project and log it for undo
    (undo deletes it again, and the project parameters it brought along if nothing else uses them)."""
    add_model(name)
    _changed(msg("Modell «{name}» importiert", name=name), {"op": "delete_database", "name": name, "project_params": list(project_params)})


def delete_database(name: str) -> None:
    _require_model_db(name)
    users = _external_users(name)
    if users:
        raise ValueError(_("«{name}» wird noch von {n} Prozess(en) in anderen Datenbanken verwendet.", name=name, n=len(users)))
    from . import params
    codes = [a["code"] for a in bd.Database(name)]
    del bd.databases[name]
    params.forget_database(name, codes)
    reg = registry.load()
    lst = reg.get("models", {}).get(bd.projects.current, [])
    if name in lst:
        lst.remove(name)
    registry.save(reg)
    engine.bump_foreground(bd.projects.current)


def _external_users(name: str) -> list[int]:
    q = ExchangeDataset.select(ExchangeDataset.output_database).where(
        ExchangeDataset.input_database == name, ExchangeDataset.output_database != name).distinct()
    return [r for (r,) in q.tuples()]


def database_overview() -> list[dict]:
    r = roles()
    out = []
    for name in sorted(bd.databases):
        out.append({"name": name, "role": r.get(name, "empty"), "count": len(bd.Database(name))})
    return out


def list_processes(name: str) -> list[dict]:
    db = bd.Database(name)
    rows = []
    for a in db:
        if a.get("type") not in engine.LISTED_PROCESS_TYPES:
            continue
        product, products = a.get("reference product"), []
        if isinstance(a, functional.Process):  # stored as in the Activity Browser 3: its products
            products = a.products()
            product = ", ".join(p.get("product") or p["name"] for p in products) or None
        rows.append({"id": str(a.id), "name": a["name"], "location": a.get("location"), "unit": short_unit(a.get("unit")),
                     "product": product, "products": [str(p.id) for p in products]})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


# ---------- processes ----------

def create_process(database: str, name: str, unit: str = "unit", location: str = "CH",
                   product: str | None = None, comment: str = "") -> str:
    _require_model_db(database)
    name = (name or "").strip()
    if not name:
        raise ValueError(_("Bitte einen Namen eingeben."))
    act = bd.Database(database).new_activity(
        code=uuid.uuid4().hex, name=name, unit=unit or "unit", location=location or "GLO",
        type="processwithreferenceproduct", comment=comment or "",
        **{"reference product": (product or name).strip()})
    act.save()
    act.new_exchange(input=act, amount=1.0, type="production").save()
    _changed(msg("Prozess «{name}» angelegt", name=name), {"op": "delete_process", "key": list(act.key)})
    return str(act.id)


def copy_process(node_id: int | str, database: str) -> str:
    """Copy any process (also from a background database) into a model, with all exchanges."""
    _require_model_db(database)
    src = bd.get_node(id=int(node_id))
    new = src.copy(database=database, code=uuid.uuid4().hex)
    if new.get("type") not in engine.PROCESS_TYPES:
        new["type"] = "processwithreferenceproduct"
        new.save()
    bd.databases.set_dirty(database)
    _changed(msg("«{name}» in «{database}» kopiert", name=src["name"], database=database), {"op": "delete_process", "key": list(new.key)})
    return str(new.id)


def update_process(node_id: int | str, fields: dict) -> None:
    act = bd.get_node(id=int(node_id))
    _require_model_node(act)
    allowed = {"name", "unit", "location", "reference product", "comment"}
    old = {k: act.get(k) for k in fields if k in allowed}
    changed = False
    for k, v in fields.items():
        if k in allowed and act.get(k) != v:
            act[k] = v
            changed = True
    if not changed:
        return
    act.save()
    _changed(msg("«{name}» umbenannt oder beschrieben", name=act["name"]),
             {"op": "update_process", "key": list(act.key), "fields": old, "now": {k: act.get(k) for k in old}})


def users_of(node_id: int | str) -> list[dict]:
    act = bd.get_node(id=int(node_id))
    out = []
    for e in act.upstream():
        if e.output.id != act.id:
            out.append({"id": str(e.output.id), "name": e.output["name"], "database": e.output["database"]})
    return out


def delete_process(node_id: int | str) -> None:
    act = bd.get_node(id=int(node_id))
    _require_model_node(act)
    users = users_of(act.id)
    if users:
        names = ", ".join(q(u["name"]) for u in users[:3])
        raise ValueError(_("Dieser Prozess wird noch verwendet von {names}. Entferne dort zuerst den Input.", names=names))
    from . import params  # Brightway deletes the process's parameters with it; undo brings them back

    snapshot = {"key": list(act.key), "data": _jsonable(dict(act._data)),
                "exchanges": [_exchange_snapshot(e) for e in act.exchanges()], "params": params._jsonable(params.state())}
    name = act["name"]
    act.delete()
    _changed(msg("Prozess «{name}» gelöscht", name=name), {"op": "restore_process", "snapshot": snapshot})


# ---------- exchanges ----------

def add_exchange(node_id: int | str, input_id: int | str, amount: float = 1.0, kind: str | None = None) -> str:
    act = bd.get_node(id=int(node_id))
    _require_model_node(act)
    inp = bd.get_node(id=int(input_id))
    if kind is None:
        kind = "biosphere" if roles().get(inp["database"]) == "biosphere" else "technosphere"
    if kind not in ("technosphere", "biosphere", "substitution"):
        raise ValueError(_("Unbekannte Art von Austausch."))
    _check_amount(amount)
    exc = act.new_exchange(input=inp, amount=float(amount), type=kind, unit=inp.get("unit"))
    exc.save()
    _changed(msg("«{input}» zu «{name}» hinzugefügt", input=inp["name"], name=act["name"]), {"op": "delete_exchange", "exchange": exc._document.id})
    return str(exc._document.id)


UNC_FIELDS = ("uncertainty type", "loc", "scale", "shape", "minimum", "maximum", "negative", "pedigree")
# Pedigree matrix as in the Activity Browser 3 (bwutils/pedigree.py, from Chris Mutel's pedigree-matrix package):
# for each indicator the uncertainty factor (as GSD²) of the scores 1 (best) to 5; the indicator "sample size" of
# ecoinvent 2 counts no more (factor 1). With a basic uncertainty U_b, also as GSD²:
#   σ = √(ln² U_b + Σ ln² U_i) / 2,   lognormal with this σ (scale), GSD² = exp(2σ)
PEDIGREE = {
    "reliability": (1.0, 1.54, 1.61, 1.69, 1.69),
    "completeness": (1.0, 1.03, 1.04, 1.08, 1.08),
    "temporal correlation": (1.0, 1.03, 1.1, 1.19, 1.29),
    "geographical correlation": (1.0, 1.04, 1.08, 1.11, 1.11),
    "further technological correlation": (1.0, 1.18, 1.65, 2.08, 2.8),
}
BASIC_UNCERTAINTY = "basic uncertainty"


def pedigree_sigma(scores: dict, basic: float = 1.0) -> float:
    """σ of the lognormal from the five pedigree scores (1 … 5) and the basic uncertainty (GSD², at least 1)."""
    import math

    values = [float(basic)] + [PEDIGREE[k][int(scores[k]) - 1] for k in PEDIGREE]
    return math.sqrt(sum(math.log(v) ** 2 for v in values)) / 2


def _pedigree_scores(ped) -> dict | None:
    """The five scores of a stored pedigree, or None when one is missing or not 1 … 5."""
    if not isinstance(ped, dict):
        return None
    try:
        scores = {k: int(ped[k]) for k in PEDIGREE}
    except (KeyError, TypeError, ValueError):
        return None
    return scores if all(1 <= v <= 5 for v in scores.values()) else None


def _pedigree_basic(ped: dict, scores: dict, scale) -> float | None:
    """The basic uncertainty: as stored, else from σ and the scores (ecoinvent stores only the scores)."""
    import math

    b = ped.get(BASIC_UNCERTAINTY)
    if isinstance(b, (int, float)) and math.isfinite(b) and b >= 1:
        return float(b)
    if scale is None:
        return None
    rest = (2 * float(scale)) ** 2 - sum(math.log(PEDIGREE[k][v - 1]) ** 2 for k, v in scores.items())
    return math.exp(math.sqrt(rest)) if rest >= -1e-12 else None
UNC_NAMES = {0: "undefined", 1: "none", 2: "lognormal", 3: "normal", 4: "uniform", 5: "triangular", 6: "bernoulli",
             7: "discrete uniform", 8: "weibull", 9: "gamma", 10: "beta", 11: "generalized extreme value",
             12: "student t"}


def uncertainty(e) -> dict | None:
    """The distribution of an exchange and its 95 % range (2.5 and 97.5 percentiles), or None without one.

    For lognormal also the squared geometric standard deviation (GSD², how ecoinvent states it: roughly 95 % of the
    values lie between amount ÷ GSD² and amount × GSD²) and the pedigree scores, when the data have them. A missing
    location parameter is the amount, as Brightway takes it when it samples (for lognormal: its logarithm)."""
    import math

    kind = int(e.get("uncertainty type") or 0)
    if kind in (0, 1):
        return None
    out = {"type": kind, "name": UNC_NAMES.get(kind, str(kind)), "lo": None, "hi": None}
    try:
        import numpy as np
        from stats_arrays import UncertaintyBase, uncertainty_choices

        d = {"uncertainty_type": kind, "amount": float(e["amount"]), "negative": bool(e.get("negative"))}
        for k in ("loc", "scale", "shape", "minimum", "maximum"):
            if e.get(k) is not None:
                d[k] = float(e[k])
        if "loc" not in d:
            d["loc"] = (math.log(abs(d["amount"])) if d["amount"] else 0.0) if kind == 2 else d["amount"]
        if kind == 2:
            d["negative"] = d["amount"] < 0
        params = UncertaintyBase.from_dicts(d)
        lo, hi = sorted(float(x) for x in uncertainty_choices[kind].ppf(params, np.array([[0.025, 0.975]]))[0])
        if math.isfinite(lo) and math.isfinite(hi):
            out["lo"], out["hi"] = lo, hi
    except Exception:  # an incomplete or unusual distribution: the type alone
        pass
    if kind == 2 and e.get("scale"):
        out["gsd2"] = math.exp(2 * float(e["scale"]))
    if kind == 3 and e.get("scale") is not None:
        out["sd"] = float(e["scale"])
    if kind in (4, 5, 7):
        out["min"], out["max"] = _plain(e.get("minimum")), _plain(e.get("maximum"))
    ped = e.get("pedigree")
    if isinstance(ped, dict) and ped:
        out["pedigree"] = {str(k): _plain(ped[k]) for k in ped}
        scores = _pedigree_scores(ped)
        if scores and kind == 2:  # for the editor: the scores and the basic uncertainty behind this σ
            out["pedigree_scores"] = scores
            out["pedigree_basic"] = _pedigree_basic(ped, scores, e.get("scale"))
    return out


def uncertainty_fields(amount: float, spec: dict | None) -> dict:
    """Exchange fields for a distribution the user gives: none, lognormal (gsd2), normal (sd, or pct of the amount),
    uniform or triangular (minimum, maximum), or pedigree (scores: the five indicators 1 … 5, basic: the basic
    uncertainty as GSD², 1 when empty), which gives a lognormal and keeps the scores with the exchange, as the Activity
    Browser does. Raises ValueError with a message for the user."""
    import math

    clear = {"uncertainty type": 0, "loc": None, "scale": None, "shape": None, "minimum": None, "maximum": None,
             "negative": None, "pedigree": None}
    kind = (spec or {}).get("type") or "none"

    def num(k):
        if spec.get(k) in (None, ""):
            return None
        try:
            v = float(spec[k])
        except (TypeError, ValueError):
            v = math.nan
        if not math.isfinite(v):
            raise ValueError(_("Bitte für die Verteilung Zahlen eingeben."))
        return v

    a = float(amount)
    if kind == "none":
        return clear
    if kind == "lognormal":
        g = num("gsd2")
        if g is None or not g > 1:
            raise ValueError(_("GSD² muss grösser als 1 sein, z.B. 1.5."))
        if a == 0:
            raise ValueError(_("Eine Lognormalverteilung braucht eine Menge, die nicht null ist."))
        return {**clear, "uncertainty type": 2, "loc": math.log(abs(a)), "scale": math.log(g) / 2, "negative": a < 0}
    if kind == "pedigree":
        given = spec.get("scores") or {}
        try:
            scores = {k: float(given[k]) for k in PEDIGREE}
        except (KeyError, TypeError, ValueError):
            scores = {}
        if len(scores) != len(PEDIGREE) or any(v not in (1, 2, 3, 4, 5) for v in scores.values()):
            raise ValueError(_("Die Pedigree-Werte müssen ganze Zahlen von 1 bis 5 sein."))
        scores = {k: int(v) for k, v in scores.items()}
        basic = num("basic")
        basic = 1.0 if basic is None else basic
        if not basic >= 1:
            raise ValueError(_("Die Basisunsicherheit (GSD²) muss mindestens 1 sein."))
        if a == 0:
            raise ValueError(_("Eine Lognormalverteilung braucht eine Menge, die nicht null ist."))
        sigma = pedigree_sigma(scores, basic)
        if not sigma > 0:
            raise ValueError(_("Lauter 1 und eine Basisunsicherheit von 1 ergeben keine Streuung."))
        return {**clear, "uncertainty type": 2, "loc": math.log(abs(a)), "scale": sigma, "negative": a < 0,
                "pedigree": {**scores, BASIC_UNCERTAINTY: basic}}
    if kind == "normal":
        sd = num("sd")
        if sd is None and num("pct") is not None:
            sd = abs(a) * num("pct") / 100
        if sd is None or not sd > 0:
            raise ValueError(_("Die Standardabweichung muss grösser als 0 sein."))
        return {**clear, "uncertainty type": 3, "loc": a, "scale": sd}
    if kind in ("uniform", "triangular"):
        lo, hi = num("minimum"), num("maximum")
        if lo is None or hi is None or not lo < hi:
            raise ValueError(_("Das Minimum muss kleiner als das Maximum sein."))
        if kind == "triangular" and not lo <= a <= hi:
            raise ValueError(_("Die Menge muss zwischen Minimum und Maximum liegen."))
        return {**clear, "uncertainty type": 4 if kind == "uniform" else 5, "loc": a, "minimum": lo, "maximum": hi}
    raise ValueError(_("Unbekannte Verteilung."))


def _same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        import math

        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-300)
    return a == b


def _plain(v):
    """numpy numbers as Python ones (for the journal, which is JSON)."""
    return v.item() if hasattr(v, "item") else v


def _apply_fields(exc, fields: dict) -> None:
    for k, v in fields.items():
        if v is None:
            exc._data.pop(k, None)
        else:
            exc[k] = v


def rescale_uncertainty(exc, old: float, new: float) -> None:
    """After a new amount: the distribution moves along, with the same relative spread."""
    kind = int(exc.get("uncertainty type") or 0)
    if kind == 2 and new:
        import math

        exc["loc"] = math.log(abs(new))
        exc["negative"] = new < 0
    elif kind in (3, 4, 5) and exc.get("loc") is not None:
        exc["loc"] = new
    if kind == 3 and old and exc.get("scale") is not None:
        exc["scale"] = abs(float(exc["scale"]) * new / old)
    if kind in (4, 5) and old and exc.get("minimum") is not None and exc.get("maximum") is not None:
        lo, hi = sorted((float(exc["minimum"]) * new / old, float(exc["maximum"]) * new / old))
        exc["minimum"], exc["maximum"] = lo, hi


def set_uncertainty(exchange_id: int, spec: dict | None) -> None:
    """Set the distribution of an exchange of an own model (used by the uncertainty analysis)."""
    exc = Exchange(ExchangeDataset.get_by_id(int(exchange_id)))
    out = exc.output
    _require_model_node(out)
    if exc["type"] == "production":
        raise ValueError(_("Der Referenzfluss hat keine Unsicherheit."))
    old = {k: _plain(exc.get(k)) for k in UNC_FIELDS}
    _apply_fields(exc, uncertainty_fields(exc["amount"], spec))
    now = {k: _plain(exc.get(k)) for k in UNC_FIELDS}
    if now == old:
        return
    exc.save()
    _changed(msg("Unsicherheit von «{input}» in «{name}»", input=exc.input["name"], name=out["name"]),
             {"op": "set_uncertainty", "exchange": int(exchange_id), "fields": old, "now": now})


def update_exchange(exchange_id: int, amount: float | None = None, kind: str | None = None) -> None:
    exc = Exchange(ExchangeDataset.get_by_id(int(exchange_id)))
    out = exc.output
    _require_model_node(out)
    old = {"amount": float(exc["amount"]), "type": exc["type"]}
    unc = {k: _plain(exc.get(k)) for k in UNC_FIELDS} if int(exc.get("uncertainty type") or 0) > 1 else None
    if amount is not None:
        _check_amount(amount)
        if exc.get("formula"):
            raise ValueError(_("Diese Menge kommt aus der Formel «{formula}». Ändere die Formel oder entferne sie.",
                               formula=exc["formula"]))
        rescale_uncertainty(exc, float(exc["amount"]), float(amount))
        exc["amount"] = float(amount)
    if kind is not None:
        if exc["type"] == "production" or kind not in ("technosphere", "substitution"):
            raise ValueError(_("Diese Art lässt sich hier nicht ändern."))
        exc["type"] = kind
    if exc["amount"] == old["amount"] and exc["type"] == old["type"]:
        return
    exc.save()
    _reallocate_after(exc)
    _changed(msg("«{input}» in «{name}»: {old} → {new}", input=exc.input["name"], name=out["name"], old=_fmt(old["amount"]), new=_fmt(exc["amount"])),
             {"op": "update_exchange", "exchange": int(exchange_id), **old, "now": {"amount": float(exc["amount"]), "type": exc["type"]},
              **({"unc": unc} if unc and exc["amount"] != old["amount"] else {})})


def _reallocate_after(exc) -> None:
    """A product's amount changed in a process with several products: the shares follow (a property per unit of
    product counts with the amount produced), as bw_functional does when its own edge class saves."""
    if exc["type"] != "production":
        return
    proc = functional.process_of(exc.output)
    if proc is not None and proc.multifunctional:
        proc.allocate()


def delete_exchange(exchange_id: int) -> None:
    exc = Exchange(ExchangeDataset.get_by_id(int(exchange_id)))
    out = exc.output
    _require_model_node(out)
    if exc["type"] == "production":
        raise ValueError(_("Den Referenzfluss kann man nicht entfernen, nur seine Menge ändern."))
    snap = _exchange_snapshot(exc)
    name = exc.input["name"]
    exc.delete()
    bd.databases.set_dirty(out["database"])
    _changed(msg("«{input}» aus «{name}» entfernt", input=name, name=out["name"]), {"op": "restore_exchange", "snapshot": snap})


def _check_amount(amount) -> None:
    try:
        ok = float(amount) == float(amount) and abs(float(amount)) != float("inf")
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ValueError(_("Die Menge muss eine Zahl sein."))


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def _jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if k == "id":
            continue
        out[k] = list(v) if isinstance(v, tuple) else v
    return out


def _exchange_snapshot(exc) -> dict:
    data = _jsonable({k: v for k, v in exc._data.items()})
    data["_id"] = exc._document.id
    return data


def _restore_exchange(snap: dict) -> int:
    data = {k: v for k, v in snap.items() if k != "_id"}
    data["input"] = tuple(data["input"])
    data["output"] = tuple(data["output"])
    exc = Exchange(**data)
    exc.save()
    return exc._document.id


# ---------- several products: allocation (functional.py) ----------

def _allocation_state(proc) -> dict:
    return {"allocation": proc.get("allocation"), "factors": {p["code"]: p.get("allocation_factor") for p in proc.products()}}


def set_allocation(node_id: int | str, strategy: str, manual: dict | None = None) -> dict:
    """Split a process with several products: "equal", by a property all its products have, or "manual" with the
    shares given ({product id: share}, scaled to add up to 1). Stored as the Activity Browser 3 stores it."""
    act = bd.get_node(id=int(node_id))
    proc = functional.process_of(act)
    if proc is None or not proc.multifunctional:
        raise ValueError(_("«{name}» hat nur ein Produkt: eine Allokation ist nicht nötig.", name=act["name"]))
    _require_model_node(proc)
    if strategy not in functional.strategies(proc):
        raise ValueError(_("Eine Allokation von «{name}» nach «{strategy}» geht nicht: nicht alle Produkte haben "
                           "diese Eigenschaft.", strategy=strategy, name=proc["name"]))
    before = _allocation_state(proc)
    try:
        functional.set_allocation(proc, strategy, {int(k): float(v) for k, v in (manual or {}).items()})
    except (KeyError, ValueError, ZeroDivisionError):
        raise ValueError(_("Eine Allokation von «{name}» nach «{strategy}» geht nicht: die Werte ergeben zusammen null.",
                           strategy=strategy, name=proc["name"])) from None
    proc = bd.get_node(id=proc.id)
    _changed(msg("Allokation von «{name}» geändert", name=proc["name"]),
             {"op": "set_allocation", "key": list(proc.key), **before, "now": _allocation_state(proc)})
    return functional.info(proc)


# ---------- undo ----------

class UndoConflict(ValueError):
    """The data a step would undo was changed in the meantime (e.g. by the Activity Browser)."""


def undo(n: int | None = None) -> str:
    """Undo the last change (or change number n and everything after it).

    Each step first checks that the data is still as LCA Wrench left it. If another program changed it in the
    meantime, nothing more is undone: the step and all older ones are dropped from the log, so they can never
    overwrite that change. Steps already undone stay undone (the log is saved after each one)."""
    project = bd.projects.current
    reg = registry.load()
    j = reg.get("journal", {}).get(project, [])
    if not j:
        raise ValueError(_("Es gibt nichts rückgängig zu machen."))
    n = len(j) - 1 if n is None else int(n)
    if not 0 <= n < len(j):
        raise KeyError(_("Diesen Schritt gibt es nicht."))
    labels = []
    try:
        while len(j) > n:
            entry = j[-1]
            try:
                _check_undo(entry["undo"])
            except UndoConflict:
                label = render(entry.get("msg") or entry["label"])
                j.clear()
                raise UndoConflict(_("«{label}» lässt sich nicht rückgängig machen: die Daten wurden inzwischen anders "
                                     "geändert (z.B. im Activity Browser). Der Verlauf ist geleert, damit kein alter Schritt "
                                     "diese Änderung überschreibt.", label=label)) from None
            moved = _apply_undo(entry["undo"])
            j.pop()
            labels.append(render(entry.get("msg") or entry["label"]))
            # restored exchanges get new ids; keep older journal entries pointing at them
            for e in j:
                if e["undo"].get("exchange") in moved:
                    e["undo"]["exchange"] = moved[e["undo"]["exchange"]]
    finally:
        reg = registry.load()  # undoing may have changed the registry (e.g. a deleted model)
        reg.setdefault("journal", {})[project] = j
        registry.save(reg)
        engine.bump_foreground(project)
    return labels[-1]


def _check_undo(u: dict) -> None:
    """Raise UndoConflict if the step's data is no longer as LCA Wrench left it."""
    op = u["op"]

    def node(key):
        try:
            return bd.get_node(database=key[0], code=key[1])
        except bd.errors.UnknownObject:
            return None

    if op in ("delete_process", "update_process", "restore_process", "restore_exchange", "update_exchange", "delete_exchange",
              "set_uncertainty"):
        db = (u.get("key") or (u.get("snapshot") or {}).get("key") or (u.get("snapshot") or {}).get("output") or [None])[0]
        if op in ("update_exchange", "delete_exchange", "set_uncertainty"):
            try:
                db = ExchangeDataset.get_by_id(u["exchange"]).output_database
            except ExchangeDataset.DoesNotExist:
                if op in ("update_exchange", "set_uncertainty"):
                    raise UndoConflict() from None
                return  # an added input that is gone already: nothing to undo
        if db is not None and db not in writable_databases():
            raise UndoConflict()
    if op == "update_process":
        act = node(u["key"])
        if act is None or any(act.get(k) != v for k, v in (u.get("now") or {}).items()):
            raise UndoConflict()
    elif op == "restore_process":
        if node(u["snapshot"]["key"]) is not None:
            raise UndoConflict()
    elif op == "restore_exchange":
        snap = u["snapshot"]
        if node(snap["output"]) is None or node(snap["input"]) is None:
            raise UndoConflict()
    elif op == "restore_params" and u.get("now") is not None:
        from . import params

        if params.snapshot() != u["now"]:
            raise UndoConflict()
    elif op == "update_exchange" and u.get("now"):
        exc = ExchangeDataset.get_by_id(u["exchange"])
        if float(exc.data.get("amount")) != u["now"]["amount"] or exc.data.get("type") != u["now"]["type"]:
            raise UndoConflict()
    elif op == "set_uncertainty" and u.get("now"):
        data = ExchangeDataset.get_by_id(u["exchange"]).data
        if any(not _same(_plain(data.get(k)), v) for k, v in u["now"].items()):
            raise UndoConflict()
    elif op == "set_allocation":
        proc = node(u["key"])
        if proc is None or u["key"][0] not in writable_databases() or _allocation_state(proc) != u["now"]:
            raise UndoConflict()


def _apply_undo(u: dict) -> dict[int, int]:
    """Apply one inverse operation. Returns old -> new ids of exchanges that were recreated."""
    op = u["op"]
    moved: dict[int, int] = {}
    if op == "delete_process":
        try:
            bd.get_node(database=u["key"][0], code=u["key"][1]).delete()
        except bd.errors.UnknownObject:
            pass
    elif op == "restore_process":
        snap = u["snapshot"]
        data = dict(snap["data"])
        act = bd.Database(snap["key"][0]).new_activity(code=snap["key"][1], **{k: v for k, v in data.items()
                                                                                if k not in ("code", "database")})
        act.save()
        for e in snap["exchanges"]:
            moved[e.get("_id")] = _restore_exchange(e)
        bd.databases.set_dirty(snap["key"][0])
        if snap.get("params"):
            from . import params

            st = params.restore_ids(snap["params"], moved)
            params.restore(st)
    elif op == "update_process":
        act = bd.get_node(database=u["key"][0], code=u["key"][1])
        for k, v in u["fields"].items():
            act[k] = v
        act.save()
    elif op == "delete_exchange":
        try:
            exc = Exchange(ExchangeDataset.get_by_id(u["exchange"]))
            db = exc.output["database"]
            exc.delete()
            bd.databases.set_dirty(db)
        except ExchangeDataset.DoesNotExist:
            pass
    elif op == "restore_exchange":
        moved[u["snapshot"].get("_id")] = _restore_exchange(u["snapshot"])
        bd.databases.set_dirty(u["snapshot"]["output"][0])
    elif op == "delete_database":
        if u.get("setup") and u["setup"] in bd.calculation_setups:
            del bd.calculation_setups[u["setup"]]
            bd.calculation_setups.serialize()
        if u["name"] in bd.databases:
            delete_database(u["name"])
        if u.get("project_params"):
            from . import params
            params.drop_unused_project_parameters(u["project_params"])
    elif op == "restore_params":
        from . import params

        params.restore(u["state"])
    elif op == "update_exchange":
        exc = Exchange(ExchangeDataset.get_by_id(u["exchange"]))
        if u.get("unc"):
            _apply_fields(exc, u["unc"])  # the distribution exactly as before
        else:
            rescale_uncertainty(exc, float(exc["amount"]), float(u["amount"]))
        exc["amount"] = u["amount"]
        exc["type"] = u["type"]
        exc.save()
        _reallocate_after(exc)
    elif op == "set_uncertainty":
        exc = Exchange(ExchangeDataset.get_by_id(u["exchange"]))
        _apply_fields(exc, u["fields"])
        exc.save()
    elif op == "set_allocation":
        # the strategy first (bw_functional allocates when it changes), then exactly the shares there were
        proc = bd.get_node(database=u["key"][0], code=u["key"][1])
        if proc.get("allocation") != u["allocation"]:
            proc["allocation"] = u["allocation"]
            proc.save()
        for p in proc.products():
            if p["code"] in u["factors"] and p.get("allocation_factor") != u["factors"][p["code"]]:
                p["allocation_factor"] = u["factors"][p["code"]]
                p.save()
    return moved


# ---------- detail for the editor ----------

def process_detail(node_id: int | str, method: tuple) -> dict:
    """Process with all exchanges and each one's share of the impact (live, from the engine)."""
    act = bd.get_node(id=int(node_id))
    S = system_for(act.id) if roles().get(act["database"]) == "background" else system()
    alone = act["database"] if S is not system() else None  # calculated on its own database (system_for)
    editable = act["database"] in writable_databases()
    # stored as in the Activity Browser 3: a product shows its process's inputs and emissions, scaled by its share
    # (edited on the process); a process with one product is calculated as that product
    proc = functional.process_of(act)
    products = proc.products() if proc is not None else []
    share = None
    target = act.id
    if proc is not None and proc.id != act.id:
        f = act.get("allocation_factor")
        share = float(f) if engine._is_number(f) else 1.0
        editable = False
    elif proc is not None and len(products) == 1:
        target = products[0].id
    errors = S.fg.error_texts() if editable else []
    u = None
    if not errors:
        try:
            u = S.unit_scores(method)
        except engine.ModelError as e:
            errors.append(str(e))
    col = S.col.get(target)
    prod = float(S.production[col]) if col is not None else 1.0
    cvec = S.cvec(method) if u is not None else None
    excs = []
    for e in (proc if share is not None else act).exchanges():
        try:
            if share is not None and e["type"] == "production" and e.input.id != act.id:
                continue  # the production of another product of the process
            excs.append((e, e.input.id))
        except bd.errors.UnknownObject:
            continue
    info = node_info(i for _, i in excs)
    production, tech, bio = [], [], []
    for e, inp_id in excs:
        meta = info.get(inp_id, {"name": "?", "location": None, "unit": "", "database": "", "categories": ""})
        amt = float(e["amount"]) * (share if share is not None and e["type"] != "production" else 1.0)
        doc = getattr(e, "_document", None)  # input-output tables (EXIOBASE) give read-only exchanges without one
        row = {"exchange": str(doc.id) if doc is not None else None, "id": str(inp_id), "name": meta["name"], "location": meta["location"],
               "unit": meta["unit"], "database": meta["database"], "amount": amt, "type": e["type"],
               "uncertainty": uncertainty(e), "formula": e.get("formula")}
        if e["type"] == "production":
            production.append(row)
        elif e["type"] in engine.BIOSPHERE:
            row["categories"] = meta["categories"]
            r = S.bio_row.get(inp_id)
            row["contribution"] = amt / prod * float(cvec[r]) if (cvec is not None and r is not None) else None
            bio.append(row)
        else:
            sign = 1.0 if e["type"] in engine.NEGATIVE else -1.0
            try:
                r = S.ref_row(inp_id)
            except KeyError:
                r = None
            row["contribution"] = sign * amt / prod * float(u[r]) if (u is not None and r is not None) else None
            tech.append(row)
    key = lambda x: -abs(x["contribution"] or 0)
    tech.sort(key=key)
    bio.sort(key=lambda x: (-abs(x["contribution"] or 0), x["name"]))
    total = direct = None
    if u is not None and col is not None:
        total = float(u[S.ref_row(target)])
        direct = float(S.direct(method)[col]) / (prod or 1.0)
    allocation = None
    if proc is not None and len(products) > 1:
        allocation = functional.info(proc)
        allocation["editable"] = proc["database"] in writable_databases()
        for p in allocation["products"]:
            try:
                p["score"] = float(u[S.ref_row(int(p["id"]))]) if u is not None else None
            except KeyError:
                p["score"] = None
    return {
        "allocation": allocation, "share": share, "process_id": str(proc.id) if share is not None else None,
        "id": str(act.id), "name": act["name"], "product": act.get("reference product") or act.get("product"),
        "location": act.get("location"), "unit": short_unit(act.get("unit")), "unit_raw": act.get("unit"),
        "database": act["database"], "comment": act.get("comment") or "",
        "categories": " / ".join(act.get("categories") or ()),
        "production": prod, "score": total, "direct": direct,
        "production_exchanges": production, "technosphere": tech, "biosphere": bio,
        "editable": editable, "errors": errors, "calculated_alone": alone,
        "users": users_of(act.id) if editable else [],
    }
