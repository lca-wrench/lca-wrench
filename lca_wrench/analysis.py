"""Results on top of the engine: scores, contributions, inventory, tree and Sankey.

All functions take a System from engine.system() and work for background
processes and the user's models alike.
"""

from __future__ import annotations

import heapq

import numpy as np
from bw2data.backends.schema import ActivityDataset as AD

from .engine import System
from . import completion, i18n, regional, regions

UNITS = {
    "kilogram": "kg",
    "kilowatt hour": "kWh",
    "megajoule": "MJ",
    "ton kilometer": "tkm",
    "cubic meter": "m³",
    "square meter": "m²",
    "meter": "m",
    "unit": "Stück",
    "kilometer": "km",
    "person kilometer": "pkm",
    "vehicle kilometer": "vkm",
    "litre": "l",
    "hour": "h",
    "square meter-year": "m²·a",
    "cubic meter-year": "m³·a",
    "kilo Becquerel": "kBq",
    "ton": "t",
    "Pt": "UBP",
}


def short_unit(unit: str | None) -> str:
    return i18n._(UNITS[unit]) if unit in UNITS else unit or ""


def node_info(ids) -> dict[int, dict]:
    """Name, location, unit, database and categories for many nodes in one query."""
    ids = list({int(i) for i in ids})
    out: dict[int, dict] = {}
    for i in range(0, len(ids), 500):
        for nid, db, data in AD.select(AD.id, AD.database, AD.data).where(AD.id << ids[i:i + 500]).tuples():
            out[nid] = {"id": str(nid), "name": data.get("name", ""), "location": data.get("location"),
                        "unit": short_unit(data.get("unit")), "database": db,
                        "product": data.get("reference product") or data.get("product"),
                        "categories": " / ".join(data.get("categories") or ())}
    return out


def _top(vec: np.ndarray, ids: np.ndarray, top: int) -> tuple[list[tuple[int, float]], float]:
    nz = np.flatnonzero(vec)
    order = nz[np.argsort(-np.abs(vec[nz]))]
    head = [(int(ids[i]), float(vec[i])) for i in order[:top]]
    rest = float(vec[order[top:]].sum()) if len(order) > top else 0.0
    return head, rest


def score_table(S: System, fus: list[tuple[int, float]], methods: list[tuple]) -> list[list[float]]:
    """Score for every functional unit (rows) and method (columns)."""
    F = np.column_stack([S.demand_vector({fid: amt}) for fid, amt in fus]) if fus else np.zeros((len(S.row_ids), 0))
    return [[float(v) for v in (S.unit_scores(m) @ F)] for m in methods] if fus else [[] for _ in methods]


def contributions(S: System, node_id: int, amount: float, method: tuple, top: int = 12) -> dict:
    x = S.supply({node_id: amount})
    by_col = S.direct(method) * x
    char = S.flow_impacts(method, x)  # c B x, plus the factors by location (regional.py)
    acts, acts_rest = _top(by_col, S.col_ids, top)
    flows, flows_rest = _top(char, S.bio_ids, top)
    info = node_info([a for a, _ in acts] + [f for f, _ in flows])
    return {
        # same quantity bw2calc reports (c B x), so the parts add up exactly
        "score": float(by_col.sum()),
        "by_activity": [{**_brief(info, a), "value": v} for a, v in acts],
        "by_activity_rest": acts_rest,
        "by_flow": [{**_brief(info, f, flow=True), "value": v} for f, v in flows],
        "by_flow_rest": flows_rest,
        **by_location(S, method, x, by_col),
    }


PLACE_HOW = {regional.OWN: "own", regional.COUNTRY: "country", regional.REGION: "region", regional.NORMAL: "normal"}


def by_location(S: System, method: tuple, x: np.ndarray, by_col: np.ndarray | None = None) -> dict:
    """Impact by the location of the activities that cause it (their direct emissions and resource uses). Adds up to
    the score. Per location also the part the factors by location change (regional.py) and how the factor was found:
    "own" (the location's own factor), "country" (a part of a country: the country's), "region" (average over the
    region's countries), "normal" (the method's normal factor)."""
    if by_col is None:
        by_col = S.direct(method) * x
    R = S.regional(method)
    reg = np.asarray(R.sum(axis=0)).ravel() * x if R is not None else np.zeros(len(by_col))
    idx, places, how = S.column_places(method)
    # one group per location code (columns at the same location can have places with other weights)
    group: dict[str, int] = {}
    gid = np.array([group.setdefault(p.location, len(group)) for p in places], dtype=np.int64)
    nz = np.flatnonzero(by_col)
    pl = idx[nz]
    g = gid[pl]
    n = len(group)
    value = np.bincount(g, weights=by_col[nz], minlength=n)
    part = np.bincount(g, weights=reg[nz], minlength=n)
    count = np.bincount(g, minlength=n)
    best = np.zeros(n, dtype=np.int8)
    np.maximum.at(best, g, how[pl])
    weightings: dict[int, set] = {}
    for u in np.unique(pl):
        if places[u].weighting:
            weightings.setdefault(int(gid[u]), set()).add(places[u].weighting)
    first = {}
    for u, p in enumerate(places):
        first.setdefault(int(gid[u]), p)
    out = []
    for k in np.flatnonzero(count):
        p, w = first[int(k)], weightings.get(int(k), set())
        out.append({"location": p.location, "name": regions.name(p.location), "kind": p.kind, "value": float(value[k]),
                    "regional": float(part[k]), "processes": int(count[k]), "how": PLACE_HOW[int(best[k])],
                    "weighting": "mixed" if len(w) > 1 else (next(iter(w)) if w else None)})
    out.sort(key=lambda r: -abs(r["value"]))
    return {"by_location": out, "regional": {**regional.summary(method), "effect": float(reg.sum()),
                                             "processes": int(np.count_nonzero(reg))}}


def _brief(info: dict, nid: int, flow: bool = False) -> dict:
    n = info.get(nid, {"id": str(nid), "name": f"#{nid}", "location": None, "categories": ""})
    if flow:
        return {"id": n["id"], "name": n["name"], "categories": n["categories"]}
    return {"id": n["id"], "name": n["name"], "location": n["location"], "database": n.get("database")}


def inventory(S: System, node_id: int, amount: float, method: tuple | None = None) -> list[dict]:
    """Life cycle inventory: every elementary flow with a non-zero total. With a method, each flow also says whether
    the method has a factor for it and where the factor comes from (completion.factor_status)."""
    g = S.inventory(S.supply({node_id: amount}))
    nz = np.flatnonzero(np.abs(g) > 0)
    info = node_info(S.bio_ids[nz])
    rows = []
    for i in nz:
        n = info.get(int(S.bio_ids[i]), {})
        rows.append({"id": str(int(S.bio_ids[i])), "name": n.get("name", ""), "categories": n.get("categories", ""),
                     "unit": n.get("unit", ""), "amount": float(g[i])})
    if method is not None:
        dbs = {int(k): v["database"] for k, v in info.items()}
        for r, st in zip(rows, completion.factor_status(tuple(method), S.bio_ids[nz], g[nz], dbs)):
            r.update(st)
    rows.sort(key=lambda r: (r["categories"], r["name"]))
    return rows


def factor_summary(rows: list[dict]) -> dict:
    """Counts over an inventory with factor status: how many flows have no factor, how many of those share their
    name with a flow that has one (and what those would add, as an estimate), how many factors were completed."""
    none = [r for r in rows if r.get("status") == "none"]
    sus = [r for r in none if "estimate" in r]
    done = [r for r in rows if r.get("status") == "completed"]
    return {"flows": len(rows), "uncharacterized": len(none), "namesakes": len(sus),
            "estimate": float(sum(r["estimate"] for r in sus)),
            "completed": len(done), "completed_value": float(sum(r["amount"] * r["factor"] for r in done)),
            "mapped": sum(1 for r in rows if r.get("status") == "mapped")}


# ---------- supply chain ----------

def _producer_col(S: System, row: int) -> int | None:
    c = S.col.get(int(S.row_ids[row]))
    if c is not None:
        return c
    if not hasattr(S, "_row_producer"):
        A = S.A.tocsr()
        prod = {}
        for r in range(A.shape[0]):
            s, e = A.indptr[r], A.indptr[r + 1]
            pos = [A.indices[k] for k in range(s, e) if A.data[k] > 0]
            if pos:
                prod[r] = pos[0]
        S._row_producer = prod
    return S._row_producer.get(row)


def _inputs(S: System, col: int):
    """(row, amount per unit of the column's production) for every input of an activity column."""
    A = S.A
    own = S.ref_row(int(S.col_ids[col]))
    prod = S.production[col] or 1.0
    for k in range(A.indptr[col], A.indptr[col + 1]):
        r = A.indices[k]
        if r != own:
            yield r, float(-A.data[k] / prod)


def tree(S: System, node_id: int, amount: float, method: tuple, cutoff: float = 0.01, depth: int = 4,
         max_children: int = 5) -> dict:
    """Supply chain as a tree, each visit a new node, pruned by share of the total."""
    u = S.unit_scores(method)
    d = S.direct(method)
    root_row = S.ref_row(node_id)
    total = float(u[root_row]) * amount
    nodes = []

    def build(row, amt, level, parent):
        col = _producer_col(S, row)
        imp = amt * float(u[row])
        idx = len(nodes)
        nodes.append({"i": idx, "parent": parent, "nid": int(S.col_ids[col]) if col is not None else int(S.row_ids[row]),
                      "amount": float(amt), "impact": float(imp), "share": float(imp / total) if total else 0.0,
                      "direct": float(amt * d[col] / (S.production[col] or 1.0)) if col is not None else 0.0,
                      "depth": level})
        if level >= depth or not total or col is None:
            return
        kids = []
        for r, per_unit in _inputs(S, col):
            child_amt = per_unit * amt
            child_imp = child_amt * float(u[r])
            if abs(child_imp) >= cutoff * abs(total):
                kids.append((child_imp, r, child_amt))
        kids.sort(key=lambda k: -abs(k[0]))
        for _, r, child_amt in kids[:max_children]:
            build(r, child_amt, level + 1, idx)

    build(root_row, amount, 0, None)
    info = node_info(n["nid"] for n in nodes)
    for n in nodes:
        meta = info.get(n["nid"], {})
        n.update({"id": str(n.pop("nid")), "name": meta.get("name", ""), "location": meta.get("location"),
                  "unit": meta.get("unit", ""), "database": meta.get("database")})
    return {"total": total, "nodes": nodes}


def sankey(S: System, node_id: int, amount: float, method: tuple, cutoff: float = 0.02, max_nodes: int = 40) -> dict:
    """Supply chain as a network: each process once, links weighted by the impact that flows along them.

    Node value = cumulative impact of everything the process delivers into this
    product system (unit score times its total output). Link value = impact of
    the amount one process supplies to another. Links below the cutoff share
    of the total are left out; what they carry shows up as "rest" of a node.
    """
    u = S.unit_scores(method)
    d = S.direct(method)
    x = S.supply({node_id: amount})
    root_row = S.ref_row(node_id)
    root = _producer_col(S, root_row)
    total = float(u[root_row]) * amount
    thr = cutoff * abs(total)

    def cum(col):
        return float(u[S.ref_row(int(S.col_ids[col]))] * x[col] * (S.production[col] or 1.0))

    chosen = {root: 0}
    heap = [(-abs(total), root)]
    while heap and len(chosen) < max_nodes:
        _, col = heapq.heappop(heap)
        for r, per_unit in _inputs(S, col):
            imp = per_unit * x[col] * (S.production[col] or 1.0) * float(u[r])
            if abs(imp) < thr:
                continue
            child = _producer_col(S, r)
            if child is None or child in chosen:
                continue
            chosen[child] = chosen[col] + 1
            heapq.heappush(heap, (-abs(cum(child)), child))
            if len(chosen) >= max_nodes:
                break

    links = []
    for col in chosen:
        for r, per_unit in _inputs(S, col):
            child = _producer_col(S, r)
            if child not in chosen:
                continue
            imp = per_unit * x[col] * (S.production[col] or 1.0) * float(u[r])
            if abs(imp) >= thr:
                links.append({"source": child, "target": col, "value": imp,
                              "amount": per_unit * x[col] * (S.production[col] or 1.0)})

    # layers: shortest distance from the product, loops point back and are flagged
    layer = {root: 0}
    frontier = [root]
    while frontier:
        nxt = []
        for col in frontier:
            for lk in links:
                if lk["target"] == col and lk["source"] not in layer:
                    layer[lk["source"]] = layer[col] + 1
                    nxt.append(lk["source"])
        frontier = nxt
    for lk in links:
        lk["loop"] = layer.get(lk["source"], 0) <= layer.get(lk["target"], 0)

    info = node_info(int(S.col_ids[c]) for c in chosen)
    nodes = []
    for col in chosen:
        meta = info.get(int(S.col_ids[col]), {})
        nodes.append({"key": int(col), "id": str(int(S.col_ids[col])), "name": meta.get("name", ""),
                      "location": meta.get("location"), "unit": meta.get("unit", ""), "database": meta.get("database"),
                      "layer": layer.get(col, 0), "value": cum(col) if col != root else total,
                      "direct": float(d[col] * x[col]), "amount": float(x[col] * (S.production[col] or 1.0))})
    for lk in links:
        lk["source"], lk["target"] = int(lk["source"]), int(lk["target"])
    return {"total": total, "nodes": nodes, "links": links, "cutoff": cutoff}
