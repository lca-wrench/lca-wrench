"""An own model moved to another region: a copy of the model whose background inputs come from that region.

Every input from background data is looked up again under the same name, reference product and unit, in the
target location or, if the data have none there, in the nearest region around it (DE → ENTSO-E/UCTE/RER → GLO →
RoW, see regions.py). This works because BAFU and ecoinvent name a dataset the same in every location ("Electricity,
low voltage, at grid" in 81 countries in BAFU 2026, "market for electricity, low voltage" in ecoinvent).

scope "electricity" swaps only electricity inputs (the grid mix, usually what matters most); "all" swaps every input
that exists in a nearer location. The original model stays as it is; the copy is a new own model, its processes get
the target location. Inputs that have no counterpart keep their supplier and are listed in the answer.
"""

from __future__ import annotations

import copy
import re

import bw2data as bd
from bw2data.backends.schema import ActivityDataset as AD

from . import engine, models, regions
from .i18n import _

_ELECTRICITY = re.compile(r"^(market (group )?for )?electricity\b|^electricity\b", re.I)


def is_electricity(data: dict) -> bool:
    text = data.get("reference product") or data.get("name") or ""
    return bool(_ELECTRICITY.search(text.strip())) or bool(_ELECTRICITY.search((data.get("name") or "").strip()))


def _product(d: dict) -> str:
    """The reference product without the location BAFU 2025 adds to it ("Electricity, low voltage, at grid {DE}")."""
    return re.sub(r"\s*\{[^{}]*\}\s*$", "", d.get("reference product") or "")


def _alternatives(database: str, data: dict) -> dict[str, tuple]:
    """Location → key of the datasets in `database` with the same name, reference product and unit."""
    out = {}
    for code, loc, d in AD.select(AD.code, AD.location, AD.data).where(
            (AD.database == database) & (AD.name == data.get("name"))).tuples():
        if _product(d) == _product(data) and d.get("unit") == data.get("unit"):
            out.setdefault(loc, (database, code))
    return out


def plan(db_name: str, location: str, scope: str = "electricity") -> dict:
    """What a move of model `db_name` to `location` would change, without changing anything."""
    if models.roles().get(db_name) != "model":  # any foreground database, also one from the Activity Browser
        raise ValueError(_("«{name}» ist kein Modell.", name=db_name))
    if models.functional.is_functional(db_name):
        raise ValueError(_("Für Modelle im Format des Activity Browser 3 (mehrere Produkte pro Prozess) geht das noch nicht."))
    target = regions.resolve(location)
    if not target:
        raise ValueError(_("Bitte einen Ort angeben, z.B. DE oder France."))
    near = regions.chain(target)
    rank = {c: i for i, c in enumerate(near)}
    background = {n for n, r in models.roles().items() if r == "background"}
    swaps, missing, cache = {}, [], {}
    for act in bd.Database(db_name):
        for exc in act.technosphere():
            key = tuple(exc["input"])
            if key[0] not in background or key in swaps or key in cache:
                continue
            sup = bd.get_node(database=key[0], code=key[1])
            data = sup._data
            if scope == "electricity" and not is_electricity(data):
                continue
            alts = _alternatives(key[0], data)
            best = min((loc for loc in alts if loc in rank), key=lambda loc: rank[loc], default=None)
            now = data.get("location")
            cache[key] = True
            if best is None:
                missing.append({"name": data.get("name"), "location": now})
            elif best != now and rank[best] < rank.get(now, len(near)):
                swaps[key] = {"to": alts[best], "name": data.get("name"), "from_location": now, "location": best}
    return {"target": target, "near": near, "swaps": swaps, "missing": missing}


def reproject(db_name: str, location: str, scope: str = "electricity", new_name: str | None = None,
              relink: dict[str, str] | None = None) -> dict:
    """Copy model `db_name` to a new own model with its background inputs from `location`.

    Any foreground model can be moved, also one made elsewhere (Activity Browser): it is only read, the copy is a new
    model of LCA Wrench. relink: other models moved together, {old name: new name}; inputs from them then come from
    their copies."""
    if models.functional.is_functional(db_name):
        raise ValueError(_("Für Modelle im Format des Activity Browser 3 (mehrere Produkte pro Prozess) geht das noch nicht."))
    from bw2data.parameters import ActivityParameter, DatabaseParameter

    if DatabaseParameter.select().where(DatabaseParameter.database == db_name).exists() or \
            ActivityParameter.select().where(ActivityParameter.database == db_name).exists():
        raise ValueError(_("«{name}» hat Parameter. Modelle mit Parametern lassen sich noch nicht in eine andere Region "
                           "verschieben; ändere den Strom dort von Hand.", name=db_name))
    p = plan(db_name, location, scope)
    target = p["target"]
    new_name = (new_name or f"{db_name} [{target}]").strip()
    if new_name in bd.databases:
        raise ValueError(_("Eine Datenbank «{name}» gibt es schon.", name=new_name))
    src = bd.Database(db_name)
    data = src.relabel_data(copy.deepcopy(src.load()), db_name, new_name)
    changed = 0
    for key, ds in data.items():
        if ds.get("type", "process") in ("process", "processwithreferenceproduct", "multifunctional"):
            ds["location"] = target
        for exc in ds.get("exchanges", []):
            swap = p["swaps"].get(tuple(exc["input"]))
            if swap and exc.get("type") == "technosphere":
                exc["input"] = swap["to"]
                exc.pop("location", None)
                changed += 1
            elif relink and exc.get("input") and exc["input"][0] in relink:
                exc["input"] = (relink[exc["input"][0]], exc["input"][1])
    db = bd.Database(new_name)
    db.register(backend="sqlite", description=f"{db_name}, moved to {target} in LCA Wrench")
    db.write(data)
    models.add_model(new_name)
    engine.bump_foreground(bd.projects.current)
    return {"database": new_name, "target": target, "changed": changed,
            "swaps": [{k: v for k, v in s.items() if k != "to"} for s in p["swaps"].values()],
            "missing": p["missing"]}


def reproject_many(db_names: list[str], location: str, scope: str = "electricity") -> list[dict]:
    """Several models moved together: each gets its copy, and inputs from one moved model come from its copy."""
    target = regions.resolve(location)
    if not target:
        raise ValueError(_("Bitte einen Ort angeben, z.B. DE oder France."))
    names = {d: f"{d} [{target}]" for d in db_names}
    taken = [n for n in names.values() if n in bd.databases]
    if taken:
        raise ValueError(_("Eine Datenbank «{name}» gibt es schon.", name=taken[0]))
    for d in db_names:  # check all first, so that nothing is half done
        plan(d, location, scope)
    return [reproject(d, location, scope, names[d], relink=names) for d in db_names]
