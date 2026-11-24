"""Completing characterization factors a method lacks for sub-compartments.

Some method implementations carry a factor for a substance only on the flow without sub-compartment, e.g. "Carbon
dioxide, fossil" in ('emissions to air',), while the inventory data emit the same substance into ('emissions to air',
'high. pop.') or ('emissions to air', 'low. pop.'). Those emissions then count as zero, and the result looks like a
result. The Ecological Scarcity 2021 methods of the Brightway template BAFU-2025-v2 are such a case: 19 of the 22
factors of "Global warming" are on flows without sub-compartment (docs/completed-factors.md).

The completion gives a flow without a factor the factor of the flow with the same name in the same top-level
compartment without sub-compartment:

- only where the method has a non-zero factor on that flow, in the same flow list (database), with the same unit;
- never where the method has a factor of its own, including an explicit zero (Ecological Scarcity 2021 sets
  groundwater emissions of heavy metals to 0 on purpose) and special cases ("Carbon dioxide, fossil" in
  'stratosphere + troposphere');
- never for long-term sub-compartments: whether long-term emissions count is a choice of the method, and methods
  that count them list them. They stay without a factor and show up in the list of flows without a factor;
- only in a method family that carries its factors on the flows without sub-compartment. For each method, take the
  sub-compartment flows (not long-term) of the substances it has a top-level factor for, and the share of them with a
  factor of its own. The BAFU template's methods give few of them one (median share 0.01); a family that gives most
  of them a factor (median share 0.5 or more, as ecoinvent's LCIA methods) has chosen which sub-compartments count, and
  a sub-compartment it leaves out (emissions to groundwater, for instance) stays out. Families as in
  overview.method_family, with ecoinvent's version kept apart.

Applied in the calculation (engine.cvec, the cross-check, Monte Carlo), not written into the project: the stored
methods stay as they are. On by default, can be switched off (registry "completion"); the result names what was added.
"""

from __future__ import annotations

import threading

import numpy as np

SPARSE = 0.5  # a family whose methods specify fewer of their sub-compartments (median share) gets completed factors

_lock = threading.RLock()
_flows_cache: dict = {}  # (project, stamp, database) -> {flow id: (name, categories, unit)}
_added: dict = {}  # (project, stamp, method, num_cfs) -> {flow id: (factor, source flow id)}
_needs: dict = {}  # (project, stamp, family, members with num_cfs) -> bool


def enabled() -> bool:
    from . import registry

    return registry.load().get("completion", True) is not False


def set_enabled(on: bool) -> None:
    from . import engine, registry

    reg = registry.load()
    reg["completion"] = bool(on)
    registry.save(reg)
    with _lock:
        _added.clear()
    engine.bump_all()


def flows(database: str) -> dict[int, tuple[str, tuple, str]]:
    """Name, categories and unit of every node of a flow list."""
    import bw2data as bd
    from bw2data.backends import ActivityDataset as AD

    from . import flowmap

    k = (bd.projects.current, flowmap._stamp(), database)
    with _lock:
        if k not in _flows_cache:
            for old in [o for o in _flows_cache if o[0] == k[0] and o[1] != k[1]]:
                del _flows_cache[old]
            _flows_cache[k] = {
                i: (data.get("name") or "", tuple(data.get("categories") or ()), data.get("unit") or "")
                for i, data in AD.select(AD.id, AD.data).where(AD.database == database).tuples().iterator()}
        return _flows_cache[k]


def long_term(categories: tuple) -> bool:
    return any("long-term" in str(c) for c in categories[1:])


def candidates(method: tuple) -> dict[int, tuple[float, int]]:
    """What the rule gives, whether switched on or not: {flow id: (factor, id of the flow it is taken from)}."""
    from . import engine, flowmap

    k = flowmap._key(method)
    with _lock:
        if k in _added:
            return _added[k]
    out: dict[int, tuple[float, int]] = {}
    parts = _summed(tuple(method))
    if parts:
        # a method that is the sum of others (UBP total): the sum of what each part gets, so the total stays the sum
        # of its categories. Added on top of the stored total, where a flow has a factor in another category.
        for m in parts:
            for i, (f, src) in candidates(m).items():
                out[i] = (out[i][0] + f if i in out else f, src)
        with _lock:
            _added[k] = out
        return out
    if not needs_completion(tuple(method)):  # a family that specifies its sub-compartments: left as it is
        with _lock:
            _added[k] = out
        return out
    cf = engine.method_cfs(tuple(method))
    for db in sorted(flowmap.method_dbs(method)):
        fl = flows(db)
        source = {}  # (name, top-level compartment, unit) -> (factor, flow id), from flows without sub-compartment
        for i, (name, cats, unit) in fl.items():
            if len(cats) == 1 and cf.get(i):
                source[(name, cats[0], unit)] = (cf[i], i)
        if not source:
            continue
        for i, (name, cats, unit) in fl.items():
            if len(cats) > 1 and i not in cf and not long_term(cats):
                hit = source.get((name, cats[0], unit))
                if hit:
                    out[i] = hit
    with _lock:
        _added[k] = out
    return out


def sub_share(method: tuple) -> float | None:
    """Of the sub-compartment flows (not long-term) of the substances the method has a non-zero factor for on the flow
    without sub-compartment, the share with a factor of their own (an explicit zero counts); None if there are none."""
    from . import engine, flowmap

    cf = engine.method_cfs(tuple(method))
    covered = total = 0
    for db in sorted(flowmap.method_dbs(method)):
        fl = flows(db)
        tops = {(name, cats[0], unit) for i, (name, cats, unit) in fl.items() if len(cats) == 1 and cf.get(i)}
        if not tops:
            continue
        for i, (name, cats, unit) in fl.items():
            if len(cats) > 1 and not long_term(cats) and (name, cats[0], unit) in tops:
                total += 1
                covered += i in cf
    return covered / total if total else None


def needs_completion(method: tuple) -> bool:
    """Does the method's family carry its factors on the flows without sub-compartment? The median share (sub_share)
    over the family's methods is below SPARSE. A derived total follows its parts (candidates)."""
    import statistics

    import bw2data as bd

    from . import flowmap, overview

    fam = overview.method_family(tuple(method), multi=True)
    members = tuple(sorted((m, (bd.methods.get(m) or {}).get("num_cfs")) for m in bd.methods
                           if overview.method_family(m, multi=True) == fam and not _summed(m)))
    k = (bd.projects.current, flowmap._stamp(), fam, members)
    with _lock:
        if k in _needs:
            return _needs[k]
    shares = [x for m, _n in members if (x := sub_share(m)) is not None]
    out = bool(shares) and statistics.median(shares) < SPARSE
    with _lock:
        _needs[k] = out
    return out


def _summed(method: tuple) -> list[tuple]:
    """The methods a derived total is the sum of (setup_daten.py writes UBP total from the 21 UBP categories)."""
    import bw2data as bd

    from . import service

    if method != service.UBP_TOTAL_METHOD:
        return []
    return sorted(m for m in bd.methods if m[0] == service.PROFILE_FAMILY)


def added(method: tuple) -> dict[int, float]:
    """The factors the method gets through the completion, per flow id (empty when none or switched off)."""
    if not enabled():
        return {}
    return {i: f for i, (f, _src) in candidates(method).items()}


def addition(method: tuple, flow_ids) -> np.ndarray | None:
    """The completed factors over `flow_ids` (a matrix's biosphere rows), to add to the method's own; None if none."""
    add = added(method)
    if not add:
        return None
    vec = np.fromiter((add.get(int(f), 0.0) for f in flow_ids), dtype=float, count=len(flow_ids))
    return vec if vec.any() else None


def table(method: tuple) -> list[dict]:
    """The completed factors of a method for the UI and the export: flow, compartment, factor, source flow."""
    out = []
    names: dict[int, tuple] = {}
    from . import flowmap

    for db in flowmap.method_dbs(method):
        names.update(flows(db))
    for i, (factor, src) in candidates(method).items():
        name, cats, unit = names[i]
        out.append({"id": str(i), "name": name, "categories": " / ".join(cats), "unit": unit, "factor": factor,
                    "source": " / ".join(names[src][1]), "source_id": str(src)})
    out.sort(key=lambda r: (r["categories"], r["name"]))
    return out


def info() -> dict:
    return {"enabled": enabled()}


# ---------- which inventory flows have a factor ----------

def _namesakes(database: str) -> dict[tuple, list[int]]:
    """(name, top-level compartment, unit) -> the flows of the list with that name."""
    import bw2data as bd

    from . import flowmap

    k = (bd.projects.current, flowmap._stamp(), database, "names")
    with _lock:
        if k not in _flows_cache:
            idx: dict[tuple, list[int]] = {}
            for i, (name, cats, unit) in flows(database).items():
                if cats:
                    idx.setdefault((name, cats[0], unit), []).append(i)
            _flows_cache[k] = idx
        return _flows_cache[k]


def factor_status(method: tuple, flow_ids, amounts, databases: dict[int, str]) -> list[dict]:
    """For each inventory flow: where its factor comes from, and for a flow without one whether a flow of the same
    name in the same top-level compartment has one.

    "status" is "own" (the stored method, also an explicit zero), "mapped" (flow mapping), "completed" (this module)
    or "none". A flow with "none" and a namesake carries "namesake" (its compartment and factor) and "estimate":
    amount times that factor. That is an estimate of what the flow would add if it were assessed like its namesake,
    not a result; the namesake without sub-compartment is taken if it has a factor, else the one with the largest."""
    from . import engine, flowmap

    method = tuple(method)
    cf = engine.method_cfs(method)
    mapped = flowmap.added(method)
    cand = candidates(method)
    done = cand if enabled() else {}
    factor_of = lambda i: cf.get(i) or mapped.get(i) or (done[i][0] if i in done else 0.0)  # noqa: E731
    out = []
    for i, amount in zip(flow_ids, amounts):
        i = int(i)
        if i in cf:
            out.append({"status": "own", "factor": cf[i]})
        elif i in mapped:
            out.append({"status": "mapped", "factor": mapped[i]})
        elif i in done:
            src = flows(databases[i])[done[i][1]]
            out.append({"status": "completed", "factor": done[i][0], "source": " / ".join(src[1])})
        else:
            row: dict = {"status": "none", "factor": None}
            db = databases.get(i)
            me = flows(db).get(i) if db else None
            if me and me[1]:
                best = None
                for j in _namesakes(db).get((me[0], me[1][0], me[2]), ()):
                    f = factor_of(j)
                    if j == i or not f:
                        continue
                    cats = flows(db)[j][1]
                    rank = (len(cats) == 1, abs(f))
                    if best is None or rank > best[0]:
                        best = (rank, f, cats)
                if best:
                    row["namesake"] = {"categories": " / ".join(best[2]), "factor": best[1]}
                    row["estimate"] = float(amount) * best[1]
            out.append(row)
    return out
