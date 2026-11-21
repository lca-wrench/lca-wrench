"""Why does a product differ between two versions of its background data (e.g. ecoinvent 3.10 and 3.11)?

Version 0 is a product in the current project, version 1 the same product in another database: in another project
(each version in its own project) or in the same project (two versions side by side). Both supply chains are put on
one index: datasets are matched by their code (ecoinvent keeps its UUIDs across versions), else by name, reference
product, location and unit. A dataset only one version has gets an empty placeholder in the other one (produces
itself, uses nothing, emits nothing). Then, exactly and without approximation,

    h1 - h0 = sum_j (c0 . dB_j - s0 . dA_j) x1_j   +   sum_k dc_k g1_k   +   s0 . (f1 - f0)

    s0 = c0 B0 A0^-1 (unit scores, version 0)      x1 = A1^-1 f1, g1 = B1 x1 (version 1)

Column j is one dataset: its part is what its changed inputs, outputs and emissions do, valued with the unit scores of
version 0 and used as much as version 1 needs it. New datasets carry their whole impact, removed ones show up in the
datasets that used them. dc are changed characterization factors. tests/test_versions.py checks the sum against two
independent bw2calc results.
"""

from __future__ import annotations

from collections import Counter

import bw2data as bd
import numpy as np
from bw2data.backends.schema import ActivityDataset as AD
from scipy import sparse
from scipy.sparse.csgraph import breadth_first_order

from . import models
from .analysis import short_unit
from .i18n import _

_last: dict = {}  # the last comparison, for the detail of one dataset


def _node_attrs(ids) -> dict[int, dict]:
    out = {}
    ids = [int(i) for i in ids]
    for i in range(0, len(ids), 900):
        for nid, db, code, data in AD.select(AD.id, AD.database, AD.code, AD.data).where(AD.id << ids[i:i + 900]).tuples():
            out[nid] = {"database": db, "code": code, "name": data.get("name", ""), "product": data.get("reference product"),
                        "location": data.get("location"), "unit": data.get("unit"),
                        "categories": tuple(data.get("categories") or ())}
    return out


def _side(node_id: int, amount: float, method: tuple) -> dict:
    """Supply chain of one product in the current project: matrices restricted to what it reaches."""
    bg = models.system().bg
    if node_id not in bg.act_col or node_id not in bg.prod_row:
        raise ValueError(_("Der Versionsvergleich geht für Hintergrunddaten (z.B. ecoinvent), nicht für eigene Modelle."))
    if method not in bd.methods:
        raise ValueError(_("Die Methode fehlt im Projekt «{name}».", name=bd.projects.current))
    A, B = bg.A, bg.B
    # graph over activity columns: column c uses the product of row r, that is the activity with the same id
    col_of_row = np.array([bg.act_col.get(int(p), -1) for p in bg.prod_ids])
    Acoo = A.tocoo()
    keep = (col_of_row[Acoo.row] >= 0) & (col_of_row[Acoo.row] != Acoo.col)
    n = A.shape[1]
    G = sparse.csr_matrix((np.ones(keep.sum()), (Acoo.col[keep], col_of_row[Acoo.row[keep]])), shape=(n, n))
    cols = np.sort(breadth_first_order(G, bg.act_col[node_id], directed=True, return_predecessors=False))
    ids = bg.act_ids[cols]
    rows = np.array([bg.prod_row[int(i)] for i in ids])
    f = np.zeros(A.shape[0])
    f[bg.prod_row[node_id]] = amount
    x = bg.solve(f)
    c = bg.cvec(method)
    s = bg.unit_scores(method)
    used = np.unique(B[:, cols].tocoo().row)
    # factors by location (regional.py): R = (factor at the dataset's place - c) x B, zero without
    part = bg.regional(method)
    R = part.R[used][:, cols].tocsc() if part is not None else sparse.csc_matrix((len(used), len(cols)))
    h = float(c @ (B @ x)) + (float((part.R @ x).sum()) if part is not None else 0.0)
    return {"ids": ids, "A": A[rows][:, cols].tocsc(), "B": B[used][:, cols].tocsc(), "R": R, "bio": bg.bio_ids[used],
            "c": c[used], "s": s[rows], "x": x[cols], "h": h, "node": node_id,
            "project": bd.projects.current}


def _alias(db: str, compared: str) -> str:
    return "*" if db == compared else db


def _match(ids1, info1, db1, ids0, info0, db0) -> dict[int, int]:
    """Version-1 dataset id -> version-0 dataset id: same code first, else same name, product, location and unit."""
    by_code = {(_alias(info0[i]["database"], db0), info0[i]["code"]): i for i in ids0}
    attr = lambda d, a: (a, d["name"], d["product"], d["location"], d["unit"])  # noqa: E731
    counts = Counter(attr(info0[i], _alias(info0[i]["database"], db0)) for i in ids0)
    by_attr = {attr(info0[i], _alias(info0[i]["database"], db0)): i for i in ids0
               if counts[attr(info0[i], _alias(info0[i]["database"], db0))] == 1}
    out, taken = {}, set()
    for i in ids1:
        d = info1[i]
        a = _alias(d["database"], db1)
        j = by_code.get((a, d["code"]))
        if j is None or j in taken:
            j = by_attr.get(attr(d, a))
        if j is not None and j not in taken:
            out[i] = j
            taken.add(j)
    return out


def _match_flows(bio1, binfo1, bio0, binfo0) -> dict[int, int]:
    """Elementary flows: same code (ecoinvent UUID) in any biosphere database, else same name, compartment and unit."""
    by_code = {binfo0[i]["code"]: i for i in bio0}
    by_attr = {(binfo0[i]["name"], binfo0[i]["categories"], binfo0[i]["unit"]): i for i in bio0}
    out = {}
    for i in bio1:
        d = binfo1[i]
        j = by_code.get(d["code"]) or by_attr.get((d["name"], d["categories"], d["unit"]))
        if j is not None:
            out[i] = j
    return out


def find_counterpart(node_id: int, project: str, database: str) -> int:
    """The same product in `database` of `project` (the current project must be `project` when called)."""
    info = _node_attrs([node_id])[node_id]
    q = AD.select(AD.id).where(AD.database == database, AD.code == info["code"]).scalar()
    if q is not None:
        return int(q)
    hits = [i for i, d in _node_attrs([r for (r,) in AD.select(AD.id).where(AD.database == database, AD.name == info["name"]).tuples()]).items()
            if (d["product"], d["location"], d["unit"]) == (info["product"], info["location"], info["unit"])]
    if len(hits) != 1:
        raise KeyError(_("«{name}» ({location}) gibt es in «{database}» nicht eindeutig.", name=info["name"],
                         location=info["location"] or "–", database=database))
    return hits[0]


def compare(node_id: int, amount: float, method: tuple, project: str, database: str, top: int = 40) -> dict:
    """Split the score difference of a product between this version and the one in (project, database)."""
    from . import service

    method = tuple(method)
    node_id = int(node_id)
    cur = bd.projects.current
    db0 = _node_attrs([node_id])[node_id]["database"]
    if project == cur and database == db0:
        raise ValueError(_("Wähle eine andere Datenbank oder ein anderes Projekt als Vergleich."))
    v0 = _side(node_id, amount, method)
    info0 = _node_attrs(v0["ids"])
    binfo0 = _node_attrs(v0["bio"])
    try:
        if project != cur:
            service.visit(project)
        if database not in bd.databases:
            raise KeyError(_("Die Datenbank «{name}» gibt es in diesem Projekt nicht.", name=database))
        node1 = find_counterpart(node_id, project, database)
        v1 = _side(node1, amount, method)
        info1 = _node_attrs(v1["ids"])
        binfo1 = _node_attrs(v1["bio"])
    finally:
        service.leave(cur)

    # one index for both versions: version-0 datasets first, datasets only in version 1 after them
    n0 = len(v0["ids"])
    m = _match(v1["ids"], info1, database, v0["ids"], info0, db0)
    pos0 = {int(i): k for k, i in enumerate(v0["ids"])}
    idx1, new_ids = np.empty(len(v1["ids"]), dtype=int), []
    for k, i in enumerate(v1["ids"]):
        i = int(i)
        if i in m:
            idx1[k] = pos0[m[i]]
        else:
            idx1[k] = n0 + len(new_ids)
            new_ids.append(i)
    U = n0 + len(new_ids)
    only0 = np.setdiff1d(np.arange(n0), idx1[idx1 < n0])
    # flows
    nb0 = len(v0["bio"])
    fm = _match_flows([int(i) for i in v1["bio"]], binfo1, [int(i) for i in v0["bio"]], binfo0)
    bpos0 = {int(i): k for k, i in enumerate(v0["bio"])}
    bidx1, new_flows = np.empty(len(v1["bio"]), dtype=int), []
    for k, i in enumerate(v1["bio"]):
        i = int(i)
        if i in fm:
            bidx1[k] = bpos0[fm[i]]
        else:
            bidx1[k] = nb0 + len(new_flows)
            new_flows.append(i)
    F = nb0 + len(new_flows)

    def pad(M, shape, extra_diag=None):
        coo = M.tocoo()
        r, c, v = [coo.row], [coo.col], [coo.data]
        if extra_diag is not None and len(extra_diag):
            r.append(extra_diag), c.append(extra_diag), v.append(np.ones(len(extra_diag)))
        return sparse.csc_matrix((np.concatenate(v), (np.concatenate(r), np.concatenate(c))), shape=shape)

    A0 = pad(v0["A"], (U, U), np.arange(n0, U))
    a1 = v1["A"].tocoo()
    A1 = pad(sparse.coo_matrix((a1.data, (idx1[a1.row], idx1[a1.col])), shape=(U, U)), (U, U), only0)
    B0 = pad(v0["B"], (F, U))
    b1 = v1["B"].tocoo()
    B1 = sparse.csc_matrix((b1.data, (bidx1[b1.row], idx1[b1.col])), shape=(F, U))
    # the parts by location (regional.py) of both versions; with them the characterized B is diag(c) B + R
    R0 = pad(v0["R"], (F, U))
    r1 = v1["R"].tocoo()
    R1 = sparse.csc_matrix((r1.data, (bidx1[r1.row], idx1[r1.col])), shape=(F, U))
    c0 = np.concatenate([v0["c"], np.zeros(len(new_flows))])
    c1 = np.zeros(F)
    c1[bidx1] = v1["c"]
    s0 = np.concatenate([v0["s"], np.zeros(len(new_ids))])
    x1 = np.zeros(U)
    x1[idx1] = v1["x"]
    dA, dB, dc, dR = (A1 - A0).tocsc(), (B1 - B0).tocsc(), c1 - c0, (R1 - R0).tocsc()
    # h1 - h0 = (dB^T c0 + 1^T dR - dA^T s0) x1 + dc . B1 x1 (+ the demand term): a dataset's part holds its changed
    # exchanges and a changed factor by location (another place), the flows' part the changed normal factors
    per_act = (dB.T @ c0 + np.asarray(dR.sum(axis=0)).ravel() - dA.T @ s0) * x1
    g1 = B1 @ x1
    per_flow = dc * g1
    a0, a1_ = pos0[node_id], int(idx1[list(v1["ids"]).index(node1)])
    demand = float(s0[a1_] - s0[a0]) * amount
    diff = v1["h"] - v0["h"]
    explained = float(per_act.sum() + per_flow.sum() + demand)

    def name_of(k):
        d = info0[int(v0["ids"][k])] if k < n0 else info1[new_ids[k - n0]]
        return d

    def act_row(k):
        d = name_of(k)
        col = dA[:, k]
        bcol = dB[:, k]
        return {"k": int(k), "name": d["name"], "location": d["location"], "database": d["database"],
                "status": "new" if k >= n0 else "changed", "contribution": float(per_act[k]),
                "share": float(per_act[k] / diff) if diff else None, "used": float(x1[k]), "unit": short_unit(d["unit"]),
                "changes": int(col.nnz + bcol.nnz)}

    order = np.argsort(-np.abs(per_act))
    shown = [k for k in order[:top] if per_act[k] != 0]
    rest = float(per_act.sum() - sum(per_act[k] for k in shown))
    forder = np.argsort(-np.abs(per_flow))
    flows = []
    for k in forder[:10]:
        if per_flow[k] == 0:
            break
        d = binfo0[int(v0["bio"][k])] if k < nb0 else binfo1[new_flows[k - nb0]]
        flows.append({"name": d["name"], "categories": " / ".join(d["categories"]), "contribution": float(per_flow[k]),
                      "old_cf": float(c0[k]), "new_cf": float(c1[k])})
    changed_sets = int(np.count_nonzero(per_act))
    _last.clear()
    _last.update({"key": (node_id, amount, method, project, database), "dA": dA, "dB": dB, "A0": A0, "A1": A1, "B0": B0, "B1": B1,
                  "dR": dR, "s0": s0, "c0": c0, "x1": x1, "name_of": name_of, "n0": n0, "nb0": nb0, "bio0": v0["bio"], "binfo0": binfo0,
                  "binfo1": binfo1, "new_flows": new_flows, "diff": diff})
    p0 = info0[node_id]
    return {"product": {"id": str(node_id), "name": p0["name"], "location": p0["location"], "unit": short_unit(p0["unit"]),
                        "amount": amount},
            "version0": {"project": cur, "database": db0, "score": v0["h"], "datasets": n0},
            "version1": {"project": project, "database": database, "score": v1["h"], "datasets": len(v1["ids"]), "id": str(node1)},
            "unit": short_unit(bd.methods[method].get("unit")), "method": list(method), "difference": diff, "explained": explained,
            "rest": diff - explained, "parts": [act_row(k) for k in shown], "parts_rest": rest,
            "datasets_changed": changed_sets, "datasets_new": len(new_ids), "datasets_removed": int(len(only0)),
            "flows": flows, "flows_total": float(per_flow.sum()), "demand": demand}


def detail(k: int) -> dict:
    """The changed exchanges of one dataset of the last comparison, each with its share."""
    if not _last:
        raise KeyError(_("Diesen Vergleich gibt es nicht mehr. Bitte neu vergleichen."))
    L = _last
    k = int(k)
    x = L["x1"][k]
    rows = []
    col0, col1 = L["A0"][:, k].toarray().ravel(), L["A1"][:, k].toarray().ravel()
    for i in L["dA"][:, k].nonzero()[0]:
        d = L["name_of"](int(i))
        kind = "production" if i == k else "input"
        old, new = col0[i], col1[i]
        if kind == "input":
            old, new = -old, -new  # inputs are negative in the technosphere matrix
        rows.append({"kind": kind, "name": d["name"], "location": d["location"], "unit": short_unit(d["unit"]),
                     "old": float(old), "new": float(new), "contribution": float(-L["s0"][i] * L["dA"][i, k] * x)})
    b0, b1 = L["B0"][:, k].toarray().ravel(), L["B1"][:, k].toarray().ravel()
    dr = L["dR"][:, k].toarray().ravel()  # factors by location (regional.py): also where the dataset changed its place
    for f in sorted(set(L["dB"][:, k].nonzero()[0]) | set(np.flatnonzero(dr))):
        d = L["binfo0"][int(L["bio0"][f])] if f < L["nb0"] else L["binfo1"][L["new_flows"][f - L["nb0"]]]
        rows.append({"kind": "emission", "name": d["name"], "location": " / ".join(d["categories"]), "unit": short_unit(d["unit"]),
                     "old": float(b0[f]), "new": float(b1[f]), "contribution": float((L["c0"][f] * L["dB"][f, k] + dr[f]) * x)})
    rows.sort(key=lambda r: -abs(r["contribution"]))
    d = L["name_of"](k)
    return {"name": d["name"], "location": d["location"], "used": float(x), "rows": rows[:200], "more": max(0, len(rows) - 200),
            "total": float(sum(r["contribution"] for r in rows))}


def targets(project: str) -> list[dict]:
    """Background databases of a project that a product can be compared with."""
    from . import service

    cur = bd.projects.current
    try:
        if project != cur:
            service.visit(project)
        return [{"name": n, "count": len(bd.Database(n))} for n, r in sorted(models.roles().items()) if r == "background"]
    finally:
        service.leave(cur)
