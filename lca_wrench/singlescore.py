"""Single scores: one number from the impact categories of a method family.

- EF 3.1: each of the 16 categories as result / normalisation x weighting / 100, summed, in mPt (x 1000); factors of
  the JRC EF 3.1 reference package (data/nw/ef31.json).
- ReCiPe 2016 endpoint (I, H, E): the three areas of protection, each as result / normalisation x weight, summed, in
  Pt (1000 Pt = the yearly impact of an average world citizen). Normalisation: RIVM, world 2010, per person, the
  sum of each area's categories. Weighting: the Eco-indicator 99 panel sets that SimaPro uses for ReCiPe; by default
  I/I for the Individualist, H/A for the Hierarchist and E/E for the Egalitarian perspective, H/H on request
  (data/nw/recipe2016-endpoint.json).
- Ecological Scarcity 2021: its eco-factors already weight, so the single score is the total in UBP: the family's
  total method where there is one (ecoinvent's "total", LCA Wrench's derived "Umweltbelastungspunkte gesamt"), else
  the sum of its categories.

Methods are found by their names in the usual spellings (sentier, ecoinvent, the BAFU template, with or without
long-term emissions); a set names the categories it could not find. All numbers come from one inventory of the
product, characterized with each method: the same results as calculating each method on its own.

A method implemented on another list of elementary flows than the product's (sentier's EF 3.1 on an ecoinvent
product) gives 0 where the flow mapping does not fill it (between ecoinvent and EF 3.1: toxicity, particulate matter,
water use, resources): the result names these categories and warns, and the list of sets says per product whether a
set covers it (flowmap.coverage).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import bw2data as bd
import numpy as np

from . import flowmap
from .i18n import _

DATA = Path(__file__).parent / "data" / "nw"
_EF = re.compile(r"^\s*EF\s*v?\s*3\.1\b", re.I)
_RECIPE = re.compile(r"recipe\s*2016.*endpoint\s*\(\s*([IHE])\s*\)", re.I)
_ES = re.compile(r"ecological\s+scarcity\s+2021", re.I)


@lru_cache(maxsize=None)
def factors(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def norm(text) -> str:
    """A name in a comparable form: lower case, punctuation as space, without "no LT" (ecoinvent's variant without
    long-term emissions, which is a family of its own)."""
    t = re.sub(r"[^a-z0-9+]+", " ", str(text).lower())
    t = re.sub(r"\bno lt\b", " ", t)
    return " ".join(t.split())


def _family_label(family: tuple) -> str:
    return " · ".join(str(x) for x in family)


def _sets_ef(methods: list[tuple]) -> list[dict]:
    cats = factors("ef31.json")["categories"]
    by_name = {norm(n): c for c in cats for n in c["names"]}
    fams: dict[tuple, dict] = {}
    for m in methods:
        i = next((k for k, part in enumerate(m) if _EF.match(str(part))), None)
        if i is None or i + 1 >= len(m):
            continue
        cat = by_name.get(norm(m[i + 1]))
        if cat is not None:
            fams.setdefault(tuple(m[:i + 1]), {}).setdefault(cat["label"], m)
    out = []
    for fam, found in fams.items():
        out.append({"kind": "ef31", "family": fam, "unit": "mPt",
                    "components": [{**c, "method": found[c["label"]]} for c in cats if c["label"] in found],
                    "missing": [c["label"] for c in cats if c["label"] not in found]})
    return out


def _sets_recipe(methods: list[tuple]) -> list[dict]:
    data = factors("recipe2016-endpoint.json")
    area_of = {norm(n): a for a, d in data["areas"].items() for n in d["names"]}
    fams: dict[tuple, dict] = {}
    for m in methods:
        i = next((k for k, part in enumerate(m) if _RECIPE.search(str(part))), None)
        if i is None or i + 1 >= len(m):
            continue
        f = fams.setdefault(tuple(m[:i + 1]), {"totals": {}, "categories": {}})
        head = norm(m[i + 1])
        if head.startswith("total"):
            area = area_of.get(head[len("total"):].strip())
            if area:
                f["totals"][area] = m
        elif head in area_of:
            f["categories"].setdefault(area_of[head], []).append(m)
    out = []
    for fam, f in fams.items():
        p = _RECIPE.search(str(fam[-1])).group(1).upper()
        areas = [a for a in data["areas"] if a in f["totals"] or f["categories"].get(a)]
        out.append({"kind": "recipe2016", "family": fam, "unit": "Pt", "perspective": p,
                    "weighting": data["default_weighting"][p], "weightings": list(data["weighting"]),
                    "totals": f["totals"], "categories": f["categories"],
                    "components": areas, "missing": [a for a in data["areas"] if a not in areas]})
    return out


def _sets_es(methods: list[tuple]) -> list[dict]:
    from .service import UBP_TOTAL_METHOD

    fams: dict[tuple, dict] = {}
    for m in methods:
        i = next((k for k, part in enumerate(m) if _ES.search(str(part))), None)
        if i is None or i + 1 >= len(m):
            continue
        f = fams.setdefault(tuple(m[:i + 1]), {"total": None, "categories": []})
        if norm(m[i + 1]) == "total":
            f["total"] = m
        else:
            f["categories"].append(m)
    out = []
    for fam, f in fams.items():
        total = f["total"]
        if total is None and fam == ("Ecological Scarcity 2021",) and UBP_TOTAL_METHOD in bd.methods:
            total = UBP_TOTAL_METHOD  # the BAFU 2025 template: LCA Wrench's sum of its 21 categories
        out.append({"kind": "es2021", "family": fam, "unit": "UBP", "total": total, "categories": f["categories"],
                    "components": f["categories"], "missing": []})
    return out


def sets() -> list[dict]:
    """The single scores the project's methods allow, each with its family of methods and what is missing."""
    methods = sorted(bd.methods)
    out = _sets_ef(methods) + _sets_recipe(methods) + _sets_es(methods)
    rank = {"ef31": 0, "recipe2016": 1, "es2021": 2}
    for s in out:
        s["id"] = f"{s['kind']}:{'|'.join(str(x) for x in s['family'])}"
        s["label"] = label(s)
    # EF, ReCiPe, UBP; with long-term emissions before ecoinvent's "no LT"; the Hierarchist perspective first
    return sorted(out, key=lambda s: (rank[s["kind"]], bool(re.search(r"\bno lt\b", " ".join(map(str, s["family"])), re.I)),
                                       s.get("perspective", "") != "H", s["label"]))


_PLAIN = {"ef v3 1", "ef 3 1", "ecological scarcity 2021"}  # families named just like the method: no need to repeat


def label(s: dict) -> str:
    if s["kind"] == "ef31":
        base = _("EF 3.1, normalisiert und gewichtet")
    elif s["kind"] == "recipe2016":
        base = _("ReCiPe 2016 Endpoint ({p}), Punkte", p=s["perspective"])
    else:
        base = _("Ökologische Knappheit 2021, UBP gesamt")
    fam = _family_label(s["family"])
    return base if norm(fam) in _PLAIN else f"{base} ({fam})"


def area_label(area: str) -> str:
    """A ReCiPe area of protection in the reader's language."""
    return {"human health": _("Menschliche Gesundheit"), "ecosystem quality": _("Ökosystemqualität"),
            "natural resources": _("Natürliche Ressourcen")}.get(area, area)


def _missing(s: dict) -> list[str]:
    return [area_label(a) for a in s["missing"]] if s["kind"] == "recipe2016" else list(s["missing"])


def summary(s: dict) -> dict:
    """What the interface lists: no method tuples beyond what it shows."""
    found = len(s["components"])
    return {"id": s["id"], "kind": s["kind"], "label": s["label"], "unit": s["unit"],
            "perspective": s.get("perspective"), "weighting": s.get("weighting"), "weightings": s.get("weightings"),
            "found": found, "missing": _missing(s)}


def find(set_id: str) -> dict:
    for s in sets():
        if s["id"] == set_id:
            return s
    raise KeyError(_("Diesen Einzelwert gibt es in diesem Projekt nicht."))


def methods_of(s: dict) -> list[tuple]:
    """The methods a set calculates with (ReCiPe: an area's categories, else its total)."""
    if s["kind"] == "ef31":
        return [tuple(c["method"]) for c in s["components"]]
    if s["kind"] == "recipe2016":
        return [tuple(m) for a in s["components"] for m in (s["categories"].get(a) or [s["totals"][a]])]
    return [tuple(m) for m in s["categories"]] + ([tuple(s["total"])] if s["total"] else [])


def flow_lists(S, g) -> set[str]:
    """The lists of elementary flows (biosphere databases) an inventory draws on."""
    return flowmap.index().dbs_of(np.asarray(S.bio_ids)[np.asarray(g) != 0])


def _cover(method: tuple, lists: set[str]) -> str:
    """flowmap.coverage, except that a method without any factor (the BAFU template's noise) is on no other list."""
    method = tuple(method)
    return flowmap.coverage(method, lists)[0] if flowmap.method_dbs(method) else "native"


def coverage(s: dict, lists: set[str]) -> str:
    """How a set's methods cover these flow lists: "native", "mapped" (some through the flow mapping) or "missing"
    (a method implemented on another list, which the flow mapping does not fill: its category would count as 0)."""
    how = {_cover(m, lists) for m in methods_of(s)}
    return "missing" if "missing" in how else "mapped" if "mapped" in how else "native"


def compute(S, demand: dict[int, float], s: dict, weighting: str | None = None) -> dict:
    """The single score of `demand` in system S, with its parts. One inventory, characterized per method."""
    g = S.inventory(S.supply(demand))
    lists = flow_lists(S, g)

    def h(method) -> float:
        return float(S.cvec(tuple(method)) @ g)

    def cov(method) -> str:
        return _cover(method, lists)

    notes: list[str] = []
    rows: list[dict] = []
    if s["missing"]:
        missing = _missing(s)
        notes.append(_("Ohne {n} Kategorie(n), die in diesem Projekt fehlen: {names}.", n=len(missing),
                       names=", ".join(missing)))
    if s["kind"] == "ef31":
        scale = factors("ef31.json")["scale"]
        for c in s["components"]:
            r = h(c["method"])
            n = r / c["normalisation"]
            rows.append({"label": c["label"], "group": None, "method": list(c["method"]), "unit": c["unit"], "result": r,
                         "normalisation": c["normalisation"], "normalised": n, "weight": c["weighting"],
                         "score": n * c["weighting"] / 100 * scale, "coverage": cov(c["method"])})
    elif s["kind"] == "recipe2016":
        data = factors("recipe2016-endpoint.json")
        p = s["perspective"]
        ws = weighting if weighting in data["weighting"] else s["weighting"]
        nf, wf = data["normalisation"][p], data["weighting"][ws]
        n_fam = len(s["family"])
        for area in s["components"]:
            cats = s["categories"].get(area) or []
            unit, group = data["areas"][area]["unit"], area_label(area)
            if cats:  # by category, so the parts show what drives the area
                for m in cats:
                    r = h(m)
                    rows.append({"label": " · ".join(str(x) for x in m[n_fam + 1:]) or str(m[-1]), "group": group,
                                 "area": area, "method": list(m), "unit": unit, "result": r, "normalisation": nf[area],
                                 "normalised": r / nf[area], "weight": wf[area], "score": r / nf[area] * wf[area],
                                 "coverage": cov(m)})
                if area in s["totals"]:  # the categories must add up to the area's total
                    t = h(s["totals"][area])
                    part = sum(x["result"] for x in rows if x.get("area") == area)
                    if abs(part - t) > 1e-4 * max(abs(t), 1e-300):
                        notes.append(_("Die Kategorien von «{area}» ergeben {part} statt {total}.", area=group,
                                       part=f"{part:.4g}", total=f"{t:.4g}"))
            else:
                r = h(s["totals"][area])
                rows.append({"label": group, "group": group, "area": area, "method": list(s["totals"][area]),
                             "unit": unit, "result": r, "normalisation": nf[area], "normalised": r / nf[area],
                             "weight": wf[area], "score": r / nf[area] * wf[area], "coverage": cov(s["totals"][area])})
        notes.append(_("Gewichtung {ws}: Menschliche Gesundheit {hh}, Ökosysteme {eq}, Ressourcen {res} (Panel von "
                       "Eco-indicator 99, wie in SimaPro). Normalisierung: RIVM, Welt 2010, pro Person.", ws=ws,
                       hh=wf["human health"], eq=wf["ecosystem quality"], res=wf["natural resources"]))
        notes.append(_("RIVMs Normalisierung enthält keine Landnutzung, und die mineralischen Ressourcen machen fast "
                       "die ganze Ressourcen-Normalisierung aus (bitte prüfen)."))
        s = {**s, "weighting": ws}
    else:
        for m in s["categories"]:
            r = h(m)
            parts = [str(x) for x in m[len(s["family"]):] if norm(x) != "ubp"]  # ecoinvent ends its names in "UBP"
            rows.append({"label": " · ".join(parts) or str(m[-1]), "group": None, "method": list(m),
                         "unit": "UBP", "result": r, "normalisation": None, "normalised": None, "weight": None,
                         "score": r, "coverage": cov(m)})
        if s["total"] is not None:
            t = h(s["total"])
            part = sum(x["score"] for x in rows)
            if rows and abs(part - t) > 1e-4 * max(abs(t), 1e-300):
                notes.append(_("Die Kategorien ergeben {part} UBP, die Methode «gesamt» {total} UBP.", part=f"{part:.4g}",
                               total=f"{t:.4g}"))
            total = t
        else:
            total = sum(x["score"] for x in rows)
        return _result(s, rows, total, notes)
    return _result(s, rows, sum(x["score"] for x in rows), notes)


def _result(s: dict, rows: list[dict], total: float, notes: list[str]) -> dict:
    for r in rows:
        r["share"] = r["score"] / total if total else None
    rows.sort(key=lambda r: -abs(r["score"]))
    # a method on another list of elementary flows gives 0 for this product where the flow mapping does not fill it
    incomplete = [r["label"] for r in rows if r.get("coverage") == "missing"]
    mapped = [r["label"] for r in rows if r.get("coverage") == "mapped"]
    warning = _("{n} Kategorie(n) ohne Faktoren für die Elementarflüsse dieses Produkts: {names}. Die Methode ist auf "
                "einer anderen Liste von Elementarflüssen umgesetzt, und die Flusszuordnung deckt diese Wirkungen nicht "
                "ab. Sie zählen als 0, der Einzelwert ist also zu tief: besser einen Einzelwert auf der Flussliste des "
                "Produkts wählen.", n=len(incomplete), names=", ".join(incomplete)) if incomplete else None
    if mapped:
        notes = notes + [_("Über die Flusszuordnung (ecoinvent ↔ EF 3.1) bewertet: {names}.", names=", ".join(mapped))]
    return {**summary(s), "total": total, "rows": rows, "notes": notes, "warning": warning, "incomplete": incomplete}
