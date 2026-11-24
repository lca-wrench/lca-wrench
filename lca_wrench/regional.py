"""Location-dependent characterization factors (regionalized impact assessment).

Some impacts depend on where an emission or a resource use happens: a cubic metre of water taken in Spain deprives
more than one taken in Switzerland (EF 3.1 water use: 77.7 against 1.34 m³ world eq.), and a kilogram of ammonia
acidifies differently in each country. A method can carry such factors in two ways, both read here, and a file the
user loads can add more (factor_files.py: the JRC's EF 3.1 workbook):

- Rows with a location: Brightway's convention ``(flow, factor, location)``. bw2data stores them; bw2calc uses only
  the rows of the global location GLO (``consistent_global_index``), bw2regional the others.
- Country copies of a flow: a flow with a location of its own whose generic flow has a factor in the same method
  (same code before ``_<location>``, or same name before ``, <location>``, with the same compartment and unit). EF 3.1
  water use with the JRC country factors on country flows ("Water, AT") is such a case. With it, the generic water
  flows of every dataset get the factor of the dataset's country, also in data that never used the copies.

A method's own rows win over its country copies, and both over a loaded file.

The factor of a flow for an activity follows the activity's location; the first that applies wins:

1. the location's own factor, also under an old or new code (RS and ME read CS, CW, SX and BQ read AN …);
2. a part of a country (CA-QC, US-WECC, CN-SGCC): the country's factor;
3. a region (RER, ENTSO-E, RAS …) without a factor of its own: the average over its countries (regions.members),
   weighted by the production volumes of the datasets with the same name and product in those countries (ecoinvent
   records them), else by the output of the dataset's industry in each country from the project's EXIOBASE
   (sectors.OutputWeights), else equally. A country without a factor counts with the normal factor;
4. GLO, RoW and anything else: the method's normal factor, the result without this module.

The normal factor is the one the calculation uses anyway (the method's global factor, with the flow mapping and the
completed factors). Applied in the calculation (engine, cross-check, Monte Carlo), never written into the project. A
method without location-dependent factors gives exactly the result it gave before. On by default, can be switched off
(registry "regional").
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from . import regions

GLO, REST = "GLO", "RoW"
# codes that changed: a table with the old code serves the new one and the other way round (EF 3.1 still uses CS, AN)
ALIASES = {"RS": ("CS",), "ME": ("CS",), "XK": ("RS", "CS"), "CS": ("RS",), "CW": ("AN",), "SX": ("AN",),
           "BQ": ("AN",), "AN": ("CW",), "UK": ("GB",), "GB": ("UK",), "EL": ("GR",), "GR": ("EL",)}
# how a factor was found, per place and flow (the larger, the more specific)
NORMAL, REGION, COUNTRY, OWN = 0, 1, 2, 3

_lock = threading.RLock()
_tables: dict = {}  # flowmap._key(method) -> Table | None


def enabled() -> bool:
    from . import registry

    return registry.load().get("regional", True) is not False


def set_enabled(on: bool) -> None:
    from . import engine, registry

    reg = registry.load()
    reg["regional"] = bool(on)
    registry.save(reg)
    engine.bump_all()


def info() -> dict:
    from . import factor_files

    return {"enabled": enabled(), "files": factor_files.files()}


# ---------- the factors of a method ----------

@dataclass
class Table:
    """The location-dependent factors of one method."""
    factors: dict[int, dict[str, float]]  # flow id -> {location code: factor}
    # (flow, location) -> where it comes from: None a row with a location, an int the country copy (flow id), a str
    # the id of a loaded file (factor_files.py)
    source: dict[tuple[int, str], int | str | None]
    skipped: int = 0  # rows with a spatial unit this module cannot place (a geocollection's feature, e.g. ecoregions)

    def lookup(self, flow: int, code: str | None) -> float | None:
        own = self.factors.get(flow)
        if not own or not code:
            return None
        if code in own:
            return own[code]
        for alt in ALIASES.get(code, ()):
            if alt in own:
                return own[alt]
        return None

    def locations(self) -> set[str]:
        return {loc for f in self.factors.values() for loc in f}


def table(method: tuple) -> Table | None:
    """The method's location-dependent factors, whether switched on or not; None if it has none."""
    import bw2data as bd

    from . import flowmap

    m = bd.Method(tuple(method))
    try:  # a method written again with as many rows as before has another time stamp
        stamp = (bd.projects.dir / m._intermediate_dir / (m.filename + ".pickle")).stat().st_mtime_ns
    except OSError:
        stamp = None
    k = (*flowmap._key(method), stamp)
    with _lock:
        if k in _tables:
            return _tables[k]
    t = _build(tuple(method))
    with _lock:
        _tables[k] = t
    return t


def forget() -> None:
    """Read every method again (a file with factors by location was loaded or removed)."""
    with _lock:
        _tables.clear()


def active(method: tuple) -> Table | None:
    """The table when switched on, else None: the calculation then uses the normal factors only."""
    return table(method) if enabled() else None


def _flow_id(key) -> int:
    import bw2data as bd

    return int(bd.get_id(tuple(key)) if isinstance(key, (list, tuple)) else key)


def _amount(cf) -> float:
    return float(cf.get("amount", 0.0) if isinstance(cf, dict) else cf)


def is_global(row) -> bool:
    """A row of the method without location, or with the global one: what bw2calc uses."""
    from bw2data import config

    return len(row) < 3 or row[2] is None or row[2] == config.global_location


def _build(method: tuple) -> Table | None:
    import bw2data as bd

    factors: dict[int, dict[str, float]] = {}
    source: dict[tuple[int, str], int | str | None] = {}
    normal: dict[int, float] = {}
    skipped = 0
    ids: dict = {}  # a flow key resolved once: rows by location repeat the same flow for every place
    for row in bd.Method(method).load():
        key = tuple(row[0]) if isinstance(row[0], list) else row[0]
        if key not in ids:
            ids[key] = _flow_id(key)
        fid, cf = ids[key], _amount(row[1])
        if is_global(row):
            normal[fid] = normal.get(fid, 0.0) + cf
            continue
        loc = row[2]
        if not isinstance(loc, str) or not loc.strip():
            skipped += 1  # (geocollection, feature): needs the spatial data (bw2regional)
            continue
        f = factors.setdefault(fid, {})
        f[loc.strip()] = f.get(loc.strip(), 0.0) + cf  # several rows for one place add up, as in bw2calc
        source[(fid, loc.strip())] = None
    for generic, loc, cf, copy in _copies(normal):
        if loc in factors.get(generic, {}):
            continue  # a row with a location wins over a country copy
        factors.setdefault(generic, {})[loc] = cf
        source[(generic, loc)] = copy
    from . import factor_files

    for fid, loc, cf, file_id in factor_files.factors_for(method, normal):
        if loc in factors.get(fid, {}):
            continue  # the method's own factors win over a loaded file
        factors.setdefault(fid, {})[loc] = cf
        source[(fid, loc)] = file_id
    return Table(factors, source, skipped) if factors else None


def _located_flows() -> frozenset[int]:
    """The elementary flows of the project that have a location of their own (other than GLO): one query per state
    of the databases, not one per method (EF toxicity methods have some 80'000 factors)."""
    import bw2data as bd
    from bw2data.backends import ActivityDataset as AD

    from .engine import BIOSPHERE_NODE_TYPES

    k = (bd.projects.current, "located", tuple(sorted((n, str(m.get("modified"))) for n, m in bd.databases.items())))
    with _lock:
        if k not in _tables:
            for old in [o for o in _tables if len(o) == 3 and o[1] == "located" and o[0] == k[0]]:
                del _tables[old]
            _tables[k] = frozenset(i for i, loc in AD.select(AD.id, AD.location).where(
                (AD.type << list(BIOSPHERE_NODE_TYPES)) & AD.location.is_null(False)).tuples() if loc and loc != GLO)
        return _tables[k]


def _copies(cf: dict[int, float]):
    """(generic flow, location, factor, copy) for each flow of the method that is a country copy of another one."""
    from bw2data.backends import ActivityDataset as AD

    candidates = _located_flows()
    located = [i for i in cf if i in candidates]
    if not located:
        return
    info = {}
    for i in range(0, len(located), 900):
        for nid, code, name, loc, data in (AD.select(AD.id, AD.code, AD.name, AD.location, AD.data)
                                           .where(AD.id << located[i:i + 900]).tuples()):
            info[nid] = (code, name, loc, tuple(data.get("categories") or ()), data.get("unit"))
    codes, names = {}, {}  # the generic flow's code or name each copy points to
    for nid, (code, name, loc, cats, unit) in info.items():
        if code and code.endswith("_" + loc):
            codes.setdefault(code[:-len(loc) - 1], []).append(nid)
        if name and name.endswith(", " + loc):
            names.setdefault(name[:-len(loc) - 2], []).append(nid)
    found = set()
    for field, wanted in ((AD.code, codes), (AD.name, names)):
        keys = list(wanted)
        for i in range(0, len(keys), 500):
            for gid, gcode, gname, gloc, gdata in (AD.select(AD.id, AD.code, AD.name, AD.location, AD.data)
                                                   .where(field << keys[i:i + 500]).tuples()):
                if gid not in cf or (gloc and gloc != GLO):
                    continue  # the generic flow must have a factor in the method and no location of its own
                for nid in wanted.get(gcode if field is AD.code else gname, ()):
                    _code, _name, loc, cats, unit = info[nid]
                    if (gid, loc) in found or tuple(gdata.get("categories") or ()) != cats or gdata.get("unit") != unit:
                        continue
                    found.add((gid, loc))
                    yield gid, loc, cf[nid], nid


# ---------- where the activities are ----------

@dataclass(frozen=True)
class Place:
    """A column's location as far as the factors go: for a region its countries with their weights (summing to 1)."""
    location: str
    kind: str  # "country", "subnational", "region", "global", "rest", "unknown"
    weights: tuple[tuple[str, float], ...] = ()
    weighting: str | None = None  # region: "volume", "exiobase" or "equal"


def place_of(location: str | None, volumes: dict[str, float] | None = None,
             output: dict[str, float] | None = None) -> Place:
    """The place of an activity at `location`. For a region, its countries are weighted by `volumes` (production
    volume by country of the datasets with the same name and product), else by `output` (the output of the dataset's
    sector by country, from EXIOBASE), else equally."""
    loc = (location or "").strip()
    if not loc:
        return Place("", "unknown")
    if loc == GLO:
        return Place(loc, "global")
    if loc == REST:
        return Place(loc, "rest")
    if regions.is_country(loc):
        return Place(loc, "country")
    country = regions.country_of(loc)
    if country:
        return Place(loc, "subnational", ((country, 1.0),))
    members = regions.members(loc)
    if not members:
        return Place(loc, "unknown")
    w, how = {c: v for c, v in (volumes or {}).items() if c in members and v > 0}, "volume"
    if not w:
        w, how = {c: v for c, v in (output or {}).items() if c in members and v > 0}, "exiobase"
    if not w:
        w, how = {c: 1.0 for c in members}, "equal"
    total = sum(w.values())
    return Place(loc, "region", tuple(sorted((c, v / total) for c, v in w.items())), how)


class Places:
    """The places of a matrix's activity columns; columns at the same place share one entry."""

    def __init__(self, act_ids, info: dict[int, tuple], volumes: dict[int, float] | None = None, output=None,
                 data: dict[int, dict] | None = None):
        """info: {activity id: (database, name, product, location)}; volumes: {activity id: production volume};
        output: sectors.OutputWeights of the project's EXIOBASE, with `data` (ISIC class, category) of the activities
        in a region."""
        by_product: dict[tuple, dict[str, float]] = {}  # (database, name, product) -> {country: production volume}
        for a, v in (volumes or {}).items():
            if not v or v <= 0 or a not in info:
                continue
            db, name, product, loc = info[a]
            c = loc if regions.is_country(loc) else regions.country_of(loc)
            if c:
                vol = by_product.setdefault((db, name, product), {})
                vol[c] = vol.get(c, 0.0) + float(v)
        self.places: list[Place] = []
        seen: dict[Place, int] = {}
        self.index = np.zeros(len(act_ids), dtype=np.int64)
        for j, a in enumerate(act_ids):
            db, name, product, loc = info.get(int(a)) or (None, None, None, None)
            vol, out = by_product.get((db, name, product)), None
            members = regions.members(loc) if output is not None else None
            if members and not any(c in members for c in (vol or ())):
                out = _output(output, (data or {}).get(int(a)) or {}, name, product, members)
            p = place_of(loc, vol, out)
            if p not in seen:
                seen[p] = len(self.places)
                self.places.append(p)
            self.index[j] = seen[p]

    def __len__(self) -> int:
        return len(self.index)

    def column(self, j: int) -> Place:
        return self.places[int(self.index[j])]


def _output(output, d: dict, name: str | None, product: str | None, members) -> dict[str, float] | None:
    """The output of the dataset's EXIOBASE industries in the region's countries; None without a sure industry."""
    from . import sectors

    industries = sectors.proxy_industries(name or "", product or "", sectors.category(d), sectors.isic(d))
    return output.weights(industries, members) if industries else None


def activity_info(act_ids, full: bool = True, databases=None) -> dict[int, tuple]:
    """(database, name, product, location) of many activities; full=False: the location only (the rest None).
    databases: the databases they are all in, read whole (one query each instead of one per 900 activities)."""
    from bw2data.backends import ActivityDataset as AD

    fields = (AD.id, AD.database, AD.name, AD.product, AD.location) if full else (AD.id, AD.location)
    row = (lambda r: r[1:]) if full else (lambda r: (None, None, None, r[1]))  # noqa: E731
    ids = sorted({int(i) for i in act_ids})
    out = {}
    if databases:
        wanted = set(ids)
        for db in databases:
            out.update((r[0], row(r)) for r in AD.select(*fields).where(AD.database == db).tuples().iterator()
                       if r[0] in wanted)
        return out
    for i in range(0, len(ids), 900):
        out.update((r[0], row(r)) for r in AD.select(*fields).where(AD.id << ids[i:i + 900]).tuples())
    return out


def production_volumes(databases) -> dict[int, float]:
    """Production volume per activity, as ecoinvent and premise record it on the reference product exchange."""
    from bw2data.backends import ActivityDataset as AD
    from bw2data.backends import ExchangeDataset as ED

    dbs = sorted(set(databases))
    if not dbs:
        return {}
    ids = {(db, code): i for i, db, code in AD.select(AD.id, AD.database, AD.code).where(AD.database << dbs).tuples()}
    out = {}
    for db, code, data in (ED.select(ED.output_database, ED.output_code, ED.data)
                           .where((ED.output_database << dbs) & (ED.type == "production")).tuples().iterator()):
        v = data.get("production volume")
        if isinstance(v, (int, float)) and v > 0 and (db, code) in ids:
            out[ids[(db, code)]] = out.get(ids[(db, code)], 0.0) + float(v)
    return out


def places_for(act_ids, info: dict[int, tuple] | None = None, volumes: bool = True, databases=None) -> Places:
    """The places of these activities. With volumes, a region's weights come from production volumes, read only for
    databases with an activity in a region; without, regions are weighted equally (enough to group by location).
    databases: the databases the activities are in, if known (quicker)."""
    info = info if info is not None else activity_info(act_ids, full=volumes, databases=databases)
    vol, output, data = {}, None, {}
    if volumes:
        dbs = {db for db, _n, _p, loc in info.values() if db and regions.members(loc)}
        vol = production_volumes(dbs) if dbs else {}
        if dbs:
            from . import sectors

            output = sectors.output_weights()
            if output is not None:  # the ISIC class and category of the datasets in a region, for their industry
                data = activity_data([a for a, (_db, _n, _p, loc) in info.items() if regions.members(loc)])
    return Places(act_ids, info, vol, output, data)


def activity_data(ids) -> dict[int, dict]:
    """The stored data (classifications, categories, sector) of some activities."""
    from bw2data.backends import ActivityDataset as AD

    ids = sorted({int(i) for i in ids})
    out = {}
    for i in range(0, len(ids), 900):
        out.update(AD.select(AD.id, AD.data).where(AD.id << ids[i:i + 900]).tuples())
    return out


# ---------- the factors of a matrix ----------

def resolve(T: Table, flows, normal: np.ndarray, places: list[Place]) -> tuple[np.ndarray, np.ndarray]:
    """Factor of each flow at each place (NaN: the normal factor applies) and how it was found (OWN … NORMAL).

    normal: the normal factor of each flow, for the countries of a region without a factor of their own."""
    flows = [int(f) for f in flows]
    val = np.full((len(places), len(flows)), np.nan)
    how = np.zeros((len(places), len(flows)), dtype=np.int8)
    for u, p in enumerate(places):
        for i, f in enumerate(flows):
            v = T.lookup(f, p.location)
            if v is None and p.kind == "subnational":
                v = T.lookup(f, p.weights[0][0])
                if v is not None:
                    val[u, i], how[u, i] = v, COUNTRY
                continue
            if v is not None:
                val[u, i], how[u, i] = v, OWN
    reg = [u for u, p in enumerate(places) if p.kind == "region"]
    if reg and flows:
        countries = sorted({c for u in reg for c, _w in places[u].weights})
        col = {c: k for k, c in enumerate(countries)}
        F = np.array([[np.nan if (v := T.lookup(f, c)) is None else v for c in countries] for f in flows])
        has = ~np.isnan(F)
        F = np.where(has, F, np.asarray(normal, dtype=float)[:, None])
        W = np.zeros((len(reg), len(countries)))
        for r, u in enumerate(reg):
            for c, w in places[u].weights:
                W[r, col[c]] = w
        avg = W @ F.T
        some = ((W > 0).astype(float) @ has.T.astype(float)) > 0  # at least one country has a factor of its own
        for r, u in enumerate(reg):
            take = some[r] & (how[u] == NORMAL)
            val[u, take], how[u, take] = avg[r, take], REGION
    return val, how


@dataclass
class Part:
    """The location-dependent part of a characterized biosphere matrix."""
    R: sparse.csc_matrix  # (factor at the column's place - normal factor) x B, same shape as B
    how: np.ndarray  # per place of `places`: the most specific way a flow of this method gets its factor there


def matrix(T: Table | None, bio_ids, places: Places, B, c: np.ndarray) -> Part | None:
    """(factor at the column's place - normal factor c) times B, for every entry of B whose flow gets a factor by
    location; None when nothing does. Characterized B is then diag(c) B + R."""
    if T is None or not len(places) or B.shape[1] == 0:
        return None
    rows = np.array([k for k, f in enumerate(bio_ids) if int(f) in T.factors], dtype=np.int64)
    if not len(rows):
        return None
    normal = np.asarray(c, dtype=float)[rows]
    val, how = resolve(T, np.asarray(bio_ids)[rows], normal, places.places)
    sub = sparse.csr_matrix(B)[rows].tocoo()
    u = places.index[sub.col]
    v = val[u, sub.row]
    keep = ~np.isnan(v)
    delta = np.where(keep, v - normal[sub.row], 0.0)
    keep &= delta != 0
    if not keep.any():
        return None
    # per place the most specific factor the method has there for any of these flows, emitted there or not
    used = how.max(axis=1).astype(np.int8)
    R = sparse.csc_matrix((delta[keep] * sub.data[keep], (rows[sub.row[keep]], sub.col[keep])), shape=B.shape)
    return Part(R, used)


def factors_at(T: Table, bio_ids, c: np.ndarray, place: Place) -> np.ndarray:
    """The factors of all flows of a matrix at one place: c, with the factors by location where they apply."""
    out = np.asarray(c, dtype=float).copy()
    rows = np.array([k for k, f in enumerate(bio_ids) if int(f) in T.factors], dtype=np.int64)
    if len(rows):
        val, _how = resolve(T, np.asarray(bio_ids)[rows], out[rows], [place])
        hit = ~np.isnan(val[0])
        out[rows[hit]] = val[0][hit]
    return out


def sampled_parts(T: Table | None, bio_ids, places: Places, B, c: np.ndarray):
    """For Monte Carlo: (V, M) over the entries of B whose flow gets a factor by location, V holding that factor and M
    a 1. With a sampled B and sampled normal factors c_s the location-dependent part is then
    sum(B∘V x) - c_s·(B∘M x): the factors by location are fixed, the method's sampled factor applies elsewhere."""
    if T is None or not len(places):
        return None
    rows = np.array([k for k, f in enumerate(bio_ids) if int(f) in T.factors], dtype=np.int64)
    if not len(rows):
        return None
    val, _how = resolve(T, np.asarray(bio_ids)[rows], np.asarray(c, dtype=float)[rows], places.places)
    sub = (sparse.csr_matrix(B)[rows] != 0).tocoo()
    v = val[places.index[sub.col], sub.row]
    keep = ~np.isnan(v)
    if not keep.any():
        return None
    r, j = rows[sub.row[keep]], sub.col[keep]
    V = sparse.csr_matrix((v[keep], (r, j)), shape=B.shape)
    M = sparse.csr_matrix((np.ones(int(keep.sum())), (r, j)), shape=B.shape)
    return V, M


def table_rows(method: tuple) -> list[dict]:
    """Every factor by location of a method, for the list in the UI and the CSV: flow, location, factor, source."""
    from . import analysis, engine

    T = table(method)
    if T is None:
        return []
    from . import factor_files

    cf = engine.method_cfs(tuple(method))
    ids = set(T.factors) | {s for s in T.source.values() if isinstance(s, int)}
    info = analysis.node_info(ids)
    names = {e["id"]: e["file"] for e in factor_files.files()}
    out = []
    for f, locs in T.factors.items():
        n = info.get(f, {})
        for loc, v in sorted(locs.items()):
            src = T.source.get((f, loc))
            kind = "row" if src is None else "file" if isinstance(src, str) else "copy"
            out.append({"id": str(f), "name": n.get("name", ""), "categories": n.get("categories", ""), "unit": n.get("unit", ""),
                        "location": loc, "place": regions.name(loc), "factor": v, "normal": cf.get(f, 0.0),
                        "source": kind, "copy": info.get(src, {}).get("name") if kind == "copy" else None,
                        "file": names.get(src, src) if kind == "file" else None})
    out.sort(key=lambda r: (r["name"], r["categories"], r["location"]))
    return out


# kinds of impact the JRC's EF 3.1 workbook has factors by country for: there the result offers to load it
LOADABLE = {"water", "land", "acidification", "eutrophication"}


def summary(method: tuple) -> dict:
    """For the result: does the method have factors by location, is it on, how many flows and places, which loaded
    files it uses, and whether loading the EF 3.1 workbook could add some."""
    from . import factor_files, overview

    T = table(method)
    used = {s for s in T.source.values() if isinstance(s, str)} if T else set()
    files = [{k: e[k] for k in ("id", "file", "loaded")} for e in factor_files.files()]
    return {"enabled": enabled(), "available": T is not None, "flows": len(T.factors) if T else 0,
            "locations": len(T.locations()) if T else 0, "skipped": T.skipped if T else 0,
            "files": [f for f in files if f["id"] in used], "loaded_files": files,
            "loadable": overview.topic(tuple(method)) in LOADABLE}
