"""One product with two background databases: e.g. a model built on BAFU 2026, calculated once with BAFU and once with
ecoinvent. The other database may be in another project (each in its own) or in the same one.

What the product takes from its background is fixed by the model. With x the supply in this project,

    d = f_b - A_bf x_f      amount of each background product the model takes directly
    g = B_f x_f             direct emissions of the model's own processes

    h_A = s_A . d + c_A . g                                   (the normal result, checked in the tests)
    h_B = sum_i d_i k_i s_B(m(i)) + sum_f g_f c_B(m(f))

m maps each background dataset to its counterpart in the other database and k converts its unit. For a product of the
background itself d is just that product. Datasets are matched in this order:

1. a choice the user made (or loaded from a mapping file), kept in the registry per pair of databases;
2. the same code in the other database (the same database twice, or versions that keep their codes);
3. the same name, reference product, location and unit (a premise scenario gives its datasets new codes);
4. a suggestion from name, reference product, location and unit, which the user can confirm or change.

Mapping files are randonneur JSON as in sentier-mappings (github.com/sentier-dev/sentier-mappings): "replace" entries
from a source code to a target {database, code}. sentier-mappings has bridges from BAFU 2026 to the EF 3.1 flows (used
by sentier-brightway) and the convention for bridges into ecoinvent: the target by code only, never its name, amounts
or flows, because ecoinvent is licensed. Exports follow the same rule, so a reviewed mapping can be shared there.

Elementary flows (direct emissions of the model): same code, else the same name and compartment after normalising
("Carbon dioxide, fossil" in "emissions to air" = "Carbon Dioxide (fossil)" in "Emissions / Emissions to air"). Methods: the same method, else the same EF 3.x category
(sentier's "Climate change-Biogenic" = ecoinvent's "climate change: biogenic").

The difference h_B - h_A splits exactly into one part per dataset, d_i (k_i s_B(m(i)) - s_A(i)), and one for the direct
emissions; ranked by size these are the datasets the comparison is most sensitive to (`_drivers`).
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict

import bw2data as bd
import numpy as np
from bw2data.backends.schema import ActivityDataset as AD

from . import engine, models, regions, registry, sectors
from .analysis import short_unit
from .i18n import _
from .versions import _node_attrs

# ---------- units ----------

UNITS = {
    "kilogram": ("mass", 1.0), "gram": ("mass", 1e-3), "ton": ("mass", 1e3), "metric ton": ("mass", 1e3),
    "megajoule": ("energy", 1.0), "kilojoule": ("energy", 1e-3), "kilowatt hour": ("energy", 3.6),
    "megawatt hour": ("energy", 3600.0), "gigajoule": ("energy", 1e3),
    # natural gas: ecoinvent counts cubic meters at normal conditions too
    "cubic meter": ("volume", 1.0), "normal cubic meter": ("volume", 1.0), "litre": ("volume", 1e-3), "liter": ("volume", 1e-3),
    "ton kilometer": ("freight", 1.0), "metric ton*km": ("freight", 1.0), "kilogram kilometer": ("freight", 1e-3),
    "person kilometer": ("passenger", 1.0), "meter": ("length", 1.0), "kilometer": ("length", 1e3),
    "square meter": ("area", 1.0), "hectare": ("area", 1e4), "square meter-year": ("area-time", 1.0),
    "hectare-year": ("area-time", 1e4), "meter-year": ("length-time", 1.0), "kilometer-year": ("length-time", 1e3),
    "cubic meter-year": ("volume-time", 1.0), "hour": ("time", 1.0), "minute": ("time", 1 / 60), "day": ("time", 24.0),
    "year": ("time", 8760.0), "unit": ("item", 1.0), "kilo becquerel": ("activity", 1.0),
}


def _unit_key(unit: str | None) -> str:
    """A method unit in any spelling: "kg CO2 eq", "kg CO2-Eq" and "kg CO2-eq." are the same."""
    return re.sub(r"[\s\-_.]+", "", (unit or "").lower())


def factor(src_unit: str | None, tgt_unit: str | None) -> float | None:
    """Amount in the target unit per amount in the source unit; None if they measure different things."""
    a, b = (src_unit or "").strip().lower(), (tgt_unit or "").strip().lower()
    if a == b:
        return 1.0
    ua, ub = UNITS.get(a), UNITS.get(b)
    if ua and ub and ua[0] == ub[0]:
        return ua[1] / ub[1]
    return None


# ---------- suggestions by name ----------

# ecoinvent 2 style qualifiers (BAFU): where the product is, not what it is
_QUALIFIERS = re.compile(r",\s*(at|from|to)\s+(plant|grid|regional storage|regional storehouse|consumer|farm|refinery|"
                         r"power plant|long-distance pipeline|service station|mine|warehouse|field|user|"
                         r"[a-z ]*plant)\b.*$")
_STOP = {"at", "and", "of", "the", "to", "in", "with", "for", "by", "on", "from", "market", "group", "production",
         "processing", "unspecified", "mix", "average", "xx"}
_REGIONS = {"RER": 0.6, "Europe without Switzerland": 0.6, "RoW": 0.4, "GLO": 0.4}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", (text or "").lower()) if w not in _STOP and len(w) > 1}


def _core(name: str) -> str:
    """A name without the obsolete mark (BAFU: "xx ") and without where the product is (", at plant")."""
    return _QUALIFIERS.sub("", re.sub(r"^xx\s+", "", (name or "").strip(), flags=re.I).lower()).strip()


def _src_text(name: str) -> tuple[set[str], set[str], bool]:
    """Tokens of a source name, of its head (before the first comma), and whether it means a market (at grid ...)."""
    lower = (name or "").lower()
    market = bool(re.search(r",\s*at (grid|regional storage|regional storehouse|consumer|service station)|production mix|"
                            r"supply mix|consumption mix", lower))
    core = _core(name)
    return _tokens(core), _tokens(core.split(",")[0]), market


class TargetIndex:
    """The datasets of one background database, searchable by word."""

    def __init__(self, database: str):
        from . import backgrounds

        self.database = database
        self.rows: dict[int, dict] = {}
        self.by_code: dict[str, int] = {}
        self.by_key: dict[tuple, int] = {}  # (name, product, location, unit): the same dataset under another code
        self.words: dict[str, set[int]] = defaultdict(set)
        for nid, code, data in AD.select(AD.id, AD.code, AD.data).where(AD.database == database,
                                                                        AD.type << list(engine.PROCESS_TYPES)).tuples():
            d = {"id": nid, "code": code, "name": data.get("name", ""), "product": data.get("reference product") or "",
                 "location": data.get("location") or "", "unit": data.get("unit") or "",
                 "volume": data.get("production volume")}
            d["p_words"], d["words"] = _tokens(d["product"]), _tokens(_core(d["product"]) + " " + _core(d["name"]))
            d["market"] = d["name"].lower().startswith("market")
            d["obsolete"] = d["name"].lower().startswith("xx ")
            self.rows[nid] = d
            self.by_code[code] = nid
            self.by_key.setdefault((d["name"], d["product"], d["location"], d["unit"]), nid)
            for w in d["words"]:
                self.words[w].add(nid)
        # an input-output table (EXIOBASE): datasets are matched to their proxy sector, not by name (sectors.py)
        self.sectors = sectors.Sectors(self.rows) if backgrounds.kind(database) == "mrio" else None

    def score(self, d: dict, words: set, head: set, market: bool, location: str, name: str = "") -> float:
        if not words:
            return 0.0
        exact = 0.1 if name and name.strip().lower() == d["name"].strip().lower() else 0.0
        jac = len(words & d["words"]) / len(words | d["words"])
        cover = len(words & d["words"]) / len(words)
        hd = len(head & d["p_words"]) / len(head) if head else 0.0
        loc = 1.0 if d["location"] == location else _REGIONS.get(d["location"], 0.0)
        return (0.35 * jac + 0.25 * cover + 0.25 * hd + 0.12 * loc + (0.03 if d["market"] == market else 0.0) + exact
                - (0.1 if d["obsolete"] else 0.0))

    def suggest(self, name: str, unit: str, location: str, n: int = 5) -> list[tuple[float, dict]]:
        words, head, market = _src_text(name)
        pool = set().union(*(self.words.get(w, set()) for w in (head or words))) if (head or words) else set()
        if len(pool) < n:
            pool |= set().union(*(self.words.get(w, set()) for w in words)) if words else set()
        out = []
        for nid in pool:
            d = self.rows[nid]
            if factor(unit, d["unit"]) is None:
                continue
            out.append((self.score(d, words, head, market, location, name), d))
        out.sort(key=lambda t: (-t[0], t[1]["name"], t[1]["location"]))
        return [(min(1.0, sc), d) for sc, d in out[:n]]

    def respell(self, words: set[str]) -> set[str]:
        """Each word this database does not have replaced by its shortest completion or the closest word ("steeel")."""
        import difflib

        out = set()
        for w in words:
            if w in self.words or len(w) < 4 or not w.isalpha():
                out.add(w)
                continue
            pool = [k for k in self.words if abs(len(k) - len(w)) <= 2 and k.isalpha()]
            whole = sorted((k for k in pool if k.startswith(w)), key=lambda k: (len(k), k))
            best = whole[:1] or difflib.get_close_matches(w, pool, n=1, cutoff=0.8)
            out.add(best[0] if best else w)
        return out

    def search(self, q: str, unit: str | None, n: int = 40, location: str | None = None) -> tuple[list[dict], str | None]:
        """Datasets with all words, in a convertible unit first, then nearest to `location` (CH → Europe → GLO → RoW),
        then shorter names; with a typo the closest known words, returned as the corrected search."""
        words = _tokens(q)
        if not words:
            return [], None
        fixed = self.respell(words)
        spelling = " ".join(sorted(fixed)) if fixed != words else None
        ids = set.intersection(*(self.words.get(w, set()) for w in fixed))
        rank = {c: i for i, c in enumerate(regions.chain(regions.resolve(location)))} if location else {}
        rows = sorted((self.rows[i] for i in ids), key=lambda d: (
            factor(unit, d["unit"]) is None, rank.get(d["location"], len(rank)), len(d["name"]), d["name"], d["location"]))
        return rows[:n], spelling


_indexes: dict = {}


def _index(project: str, database: str) -> TargetIndex:
    key = (project, database, engine.versions(project)[0])
    if key not in _indexes:
        if len(_indexes) > 4:
            _indexes.clear()
        _indexes[key] = TargetIndex(database)
    return _indexes[key]


# ---------- methods ----------

_CATEGORY_ALIASES = [
    (r"\bnon cancer\b", "non carcinogenic"), (r"\bcancer\b", "carcinogenic"),
    (r"^resource use fossils$", "energy resources non renewable"),
    (r"^resource use minerals and metals$", "material resources metals minerals"),
    (r"^ef particulate matter$|^particulate matter$", "particulate matter formation"),
    (r"^photochemical ozone formation", "photochemical oxidant formation"),
]


def _category(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    for pattern, repl in _CATEGORY_ALIASES:
        t = re.sub(pattern, repl, t)
    return t


def _ef_key(method: tuple) -> tuple[str, str] | None:
    """(EF version, category) of an EF 3.x method in any spelling, else None."""
    for i, part in enumerate(method):
        m = re.fullmatch(r"\s*EF\s*v?\s*(3\.\d)\s*(?:\(.*\))?\s*", str(part), re.I)
        if m and i + 1 < len(method):
            return m.group(1), _category(method[i + 1])
    return None


def match_method(method: tuple, candidates: list[tuple]) -> tuple | None:
    if method in candidates:
        return method
    key = _ef_key(method)
    if key is None:
        return None
    same = [c for c in candidates if _ef_key(c) == key]
    if not same:
        same = [c for c in candidates if (_ef_key(c) or (None, None))[1] == key[1]]
    # several indicators for one category (ecoinvent lists some twice): the shortest name is the main one
    return sorted(same, key=lambda c: (len(c), str(c)))[0] if same else None


# ---------- elementary flows ----------

def _flow_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


_COMPARTMENTS = (("resource", "resource"), ("land use", "land"), ("air", "air"), ("water", "water"), ("soil", "soil"),
                 ("biota", "resource"))


def _compartment(cats: tuple) -> str:
    """The same compartment in every spelling: ("air",), ("emissions to air", "low. pop."), ("Emissions",
    "Emissions to air", ...) are all "air"; resources stay apart from emissions ("natural resource", "in water")."""
    for c in cats:
        low = str(c).lower()
        for key, cls in _COMPARTMENTS:
            if key in low:
                return cls
    return str(cats[0]).lower() if cats else ""


def _match_flows(src: dict[int, dict], biosphere_dbs: list[str]) -> dict[int, int]:
    rows = []
    for dbname in biosphere_dbs:
        rows += list(AD.select(AD.id, AD.code, AD.data).where(AD.database == dbname).tuples())
    by_code = {code: nid for nid, code, _d in rows}
    by_name: dict[tuple, list] = defaultdict(list)
    for nid, _c, d in rows:
        cats = tuple(d.get("categories") or ())
        by_name[(_flow_name(d.get("name")), _compartment(cats))].append((cats, nid))
    out = {}
    for fid, d in src.items():
        if d["code"] in by_code:
            out[fid] = by_code[d["code"]]
            continue
        cats = tuple(d["categories"])
        hits = by_name.get((_flow_name(d["name"]), _compartment(cats)))
        if hits:
            # the same categories as written, else an unspecified sub-compartment, else any
            best = sorted(hits, key=lambda h: (h[0] != cats, "unspecified" not in " ".join(h[0][1:]).lower(), h[1]))
            out[fid] = best[0][1]
    return out


# ---------- saved choices and mapping files ----------

def _pair(src_db: str, tgt_db: str) -> str:
    return f"{src_db} → {tgt_db}"


def saved(src_db: str, tgt_db: str) -> dict[str, dict]:
    return registry.load().get("matches", {}).get(_pair(src_db, tgt_db), {})


def _save(src_db: str, tgt_db: str, entries: dict[str, dict | None]) -> None:
    reg = registry.load()
    pair = reg.setdefault("matches", {}).setdefault(_pair(src_db, tgt_db), {})
    for code, entry in entries.items():
        if entry is None:
            pair.pop(code, None)
        else:
            pair[code] = entry
    registry.save(reg)


def choose(source_database: str, source_code: str, target_database: str, target_code: str | None,
           reset: bool = False, price: float | None = None) -> None:
    """Keep the user's counterpart of one dataset (None: it has none); reset forgets it (back to the suggestion).
    price: euro per unit of the dataset's product, for a sector of an input-output table (in money)."""
    entry = {"code": target_code, "origin": "user", "date": time.strftime("%Y-%m-%d")}
    if price is not None:
        if not price > 0:
            raise ValueError(_("Der Preis muss grösser als 0 sein."))
        entry["price"] = float(price)
    _save(source_database, target_database, {source_code: None if reset else entry})


def confirm_all(source_database: str, target_database: str, pairs: list[dict]) -> int:
    """Keep the suggestions shown (pairs of source and target code) as the user's choices."""
    done = saved(source_database, target_database)
    new = {p["source"]: {"code": p["target"], "origin": "user", "date": time.strftime("%Y-%m-%d")}
           for p in pairs if p.get("source") and p.get("target") and p["source"] not in done}
    _save(source_database, target_database, new)
    return len(new)


def export_mapping(source_database: str, target_database: str) -> dict:
    """The saved choices as a randonneur package in the form of sentier-mappings: the source (open data) with name,
    location and unit, the target by database and code only."""
    entries = saved(source_database, target_database)
    info = {}
    codes = [c for c in entries]
    for i in range(0, len(codes), 500):
        for code, data in AD.select(AD.code, AD.data).where(AD.database == source_database,
                                                             AD.code << codes[i:i + 500]).tuples():
            info[code] = data
    replace = []
    for code, e in sorted(entries.items()):
        if not e.get("code"):
            continue
        d = info.get(code, {})
        item = {"source": {"code": code, "name": d.get("name"), "location": d.get("location"), "unit": d.get("unit")},
                "target": {"database": target_database, "code": e["code"]}}
        if e.get("factor") not in (None, 1, 1.0):
            item["conversion_factor"] = e["factor"]
        elif e.get("price"):  # into an input-output table in million euro
            item["conversion_factor"] = e["price"] / 1e6
            item["comment"] = f"price {e['price']} EUR per {d.get('unit')}"
        replace.append(item)
    return {
        "name": f"{source_database}__{target_database}",
        "description": f"Datasets of {source_database} and their counterparts in {target_database}, reviewed in LCA Wrench.",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": "1.0.0",
        "source_id": source_database, "target_id": target_database, "graph_context": ["edges"],
        "mapping": {"source": {"expression language": "JSONPath", "labels": {"code": "code"}},
                    "target": {"expression language": "JSONPath", "labels": {"database": "database", "code": "code"}}},
        "target_proprietary": True,
        "replace": replace,
    }


def import_mapping(source_database: str, target_database: str, raw: bytes) -> int:
    """Load the "replace" entries of a randonneur package (source code -> target code) as choices."""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(_("Die Datei ist kein JSON: {error}", error=e)) from e
    entries = data.get("replace") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(_("In der Datei fehlen die Einträge «replace» (Format randonneur, wie in sentier-mappings)."))
    new = {}
    for e in entries:
        src, tgt = (e or {}).get("source") or {}, (e or {}).get("target") or {}
        if not src.get("code") or not tgt.get("code"):
            continue
        if tgt.get("database") and tgt["database"] != target_database:
            continue
        new[src["code"]] = {"code": tgt["code"], "origin": "file", "date": time.strftime("%Y-%m-%d")}
        if e.get("conversion_factor") not in (None, 1, 1.0):
            new[src["code"]]["factor"] = float(e["conversion_factor"])
    if not new:
        raise ValueError(_("Die Datei enthält keine Zuordnung nach «{name}».", name=target_database))
    _save(source_database, target_database, new)
    return len(new)


# ---------- the comparison ----------

def targets(project: str) -> dict:
    """Background databases and methods of a project to compare with."""
    from . import service

    cur = bd.projects.current
    try:
        if project != cur:
            service.visit(project)
        return {"databases": [{"name": n, "count": len(bd.Database(n))} for n, r in sorted(models.roles().items())
                              if r == "background"],
                "methods": [list(m) for m in sorted(bd.methods)]}
    finally:
        service.leave(cur)


def _demand(node_id: int, amount: float, method: tuple) -> dict:
    """What the product takes from the background (d) and emits itself (g), in the current project."""
    sysm = models.system()
    nb = sysm.nb
    f = sysm.demand_vector({node_id: amount})
    x = sysm.supply({node_id: amount})
    d = f[:nb].copy()
    g = np.zeros(len(sysm.bio_ids))
    if sysm.nf:
        x_f = x[nb:]
        d -= np.asarray(sysm.fg.A_bf @ x_f).ravel()
        g = np.asarray(sysm.fg.B_f @ x_f).ravel()
    s = sysm.bg.unit_scores(method)
    c = sysm.cvec(method)
    if sysm.nf and sysm.regional(method) is not None:
        # factors by location (regional.py): the factor each flow gets on average over the model's processes
        char = sysm.flow_impacts(method, np.concatenate([np.zeros(nb), x[nb:]]))
        c = np.where(g != 0, char / np.where(g != 0, g, 1.0), c)
    rows = np.flatnonzero(np.abs(d) > 0)
    flows = np.flatnonzero(np.abs(g) > 0)
    return {"ids": [int(sysm.bg.prod_ids[r]) for r in rows], "d": d[rows], "s": s[rows],
            "flow_ids": [int(sysm.bio_ids[k]) for k in flows], "g": g[flows], "c": c[flows],
            "score": float(sysm.score({node_id: amount}, method))}


def compare(node_id: int, amount: float, method: tuple, project: str, database: str,
            target_method: list | None = None) -> dict:
    from . import service

    node_id, method = int(node_id), tuple(method)
    cur = bd.projects.current
    side_a = _demand(node_id, amount, method)
    info = _node_attrs(side_a["ids"])
    finfo = _node_attrs(side_a["flow_ids"])
    extra = sectors.source_info(side_a["ids"])  # ISIC and price, for an input-output table on the other side
    unit_a = bd.methods[method].get("unit")
    try:
        if project != cur:
            service.visit(project)
        if database not in bd.databases or models.roles().get(database) != "background":
            raise KeyError(_("Die Datenbank «{name}» gibt es in diesem Projekt nicht.", name=database))
        method_b = tuple(target_method) if target_method else match_method(method, sorted(bd.methods))
        if method_b is None or method_b not in bd.methods:
            raise ValueError(_("Im Projekt «{name}» gibt es keine passende Methode. Wähle sie bei «Methode dort».", name=project))
        index = _index(project, database)
        bgb = _target_background(database)
        s_b = bgb.unit_scores(method_b)
        rows = []
        for k, sid in enumerate(side_a["ids"]):
            d = info[sid]
            row = {"key": f"{d['database']}|{d['code']}", "id": str(sid), "database": d["database"], "code": d["code"],
                   "name": d["name"], "location": d["location"], "unit": short_unit(d["unit"]), "unit_long": d["unit"],
                   "amount": float(side_a["d"][k]), "score_a": float(side_a["d"][k] * side_a["s"][k]),
                   "match": None, "origin": None, "quality": None, "candidates": []}
            choice = saved(d["database"], database).get(d["code"])
            target, origin, quality = None, None, None
            if d["database"] == database and d["code"] in index.by_code:
                target, origin = index.rows[index.by_code[d["code"]]], "same"
            elif choice is not None:
                origin = choice.get("origin", "user")
                target = index.rows.get(index.by_code.get(choice.get("code"))) if choice.get("code") else None
                if choice.get("code") and target is None:
                    origin = "missing"
            elif d["code"] in index.by_code:
                target, origin = index.rows[index.by_code[d["code"]]], "code"
            elif (key := (d["name"], d.get("product") or "", d["location"] or "", d["unit"] or "")) in index.by_key:
                # the same name, product, location and unit: e.g. a premise scenario, which gives new codes
                target, origin = index.rows[index.by_key[key]], "exact"
            elif index.sectors is not None:  # input-output table: the proxy sector in the region
                src = extra.get(sid, {})
                sugg, how = index.sectors.propose(d["name"], d.get("product") or "", d["location"], src.get("isic"),
                                                  src.get("category") or "")
                row["candidates"] = [{"code": c["code"], "name": c["name"], "product": c["product"],
                                      "location": c["location"], "unit": short_unit(c["unit"]), "score": sc}
                                     for sc, c in sugg]
                row["proxy"] = how  # isic, rule, category or name
                if sugg:
                    target, origin = sugg[0][1], "auto"
                    quality = "good" if sugg[0][0] >= 0.6 else "unsure"
            else:
                sugg = index.suggest(d["name"], d["unit"], d["location"])
                row["candidates"] = [{"code": c["code"], "name": c["name"], "product": c["product"],
                                      "location": c["location"], "unit": short_unit(c["unit"]), "score": round(sc, 2)}
                                     for sc, c in sugg]
                if sugg:
                    target, origin = sugg[0][1], "auto"
                    quality = "good" if sugg[0][0] >= 0.6 else "unsure"
            row["origin"], row["quality"] = origin, quality
            if target is not None:
                k_ = (choice or {}).get("factor") if origin in ("user", "file") else None
                k_ = k_ or factor(d["unit"], target["unit"])
                per = sectors.money(target["unit"])
                if k_ is None and per:  # physical amount into money: the price, the user's or the dataset's own
                    price = (choice or {}).get("price") if origin in ("user", "file") else None
                    price = price or extra.get(sid, {}).get("price")
                    row["price"] = price
                    k_ = price / per if price else None
                if k_ is None and per:  # the sector is found, but counts only once it has a price
                    row["problem"] = "price"
                    row["pending"] = {"code": target["code"], "name": target["name"], "location": target["location"],
                                      "unit": short_unit(target["unit"])}
                elif k_ is None:
                    row["origin"], row["problem"] = "unit", target["unit"]
                else:
                    s1 = float(s_b[bgb.prod_row[target["id"]]]) if target["id"] in bgb.prod_row else 0.0
                    amount_b = float(side_a["d"][k] * k_)
                    row["match"] = {"code": target["code"], "name": target["name"], "product": target["product"],
                                    "location": target["location"], "unit": short_unit(target["unit"]), "factor": k_,
                                    "amount": amount_b, "unit_score": s1}
                    row["score_b"] = amount_b * s1
            rows.append(row)
        # direct emissions of the model's own processes
        bio_dbs = [n for n, r in models.roles().items() if r == "biosphere"]
        fmatch = _match_flows({fid: finfo[fid] for fid in side_a["flow_ids"]}, bio_dbs)
        cf_b = engine.method_cfs(method_b)
        unit_b = bd.methods[method_b].get("unit")
    finally:
        service.leave(cur)

    direct_a = float(side_a["g"] @ side_a["c"]) if len(side_a["g"]) else 0.0
    direct_b = sum(float(side_a["g"][k]) * cf_b.get(fmatch[fid], 0.0) for k, fid in enumerate(side_a["flow_ids"]) if fid in fmatch)
    unmatched_flows = [{"name": finfo[fid]["name"], "categories": " / ".join(finfo[fid]["categories"]),
                        "score_a": float(side_a["g"][k] * side_a["c"][k])}
                       for k, fid in enumerate(side_a["flow_ids"]) if fid not in fmatch]
    rows.sort(key=lambda r: -abs(r["score_a"]))
    total_a = sum(r["score_a"] for r in rows) + direct_a
    total_b = sum(r.get("score_b", 0.0) for r in rows) + direct_b
    open_a = sum(abs(r["score_a"]) for r in rows if r["match"] is None)
    unsure_a = sum(abs(r["score_a"]) for r in rows if r["origin"] == "auto" and r["quality"] == "unsure")
    scale = sum(abs(r["score_a"]) for r in rows) + abs(direct_a) or 1.0
    drivers = _drivers(rows, direct_a, direct_b, total_b - total_a)
    p0 = _node_attrs([node_id])[node_id]
    return {"product": {"id": str(node_id), "name": p0["name"], "location": p0["location"], "unit": short_unit(p0["unit"]),
                        "amount": amount, "database": p0["database"]},
            "a": {"project": cur, "method": list(method), "unit": unit_a, "score": total_a, "check": side_a["score"]},
            "b": {"project": project, "database": database, "method": list(method_b), "unit": unit_b, "score": total_b},
            "difference": total_b - total_a, "same_unit": _unit_key(unit_a) == _unit_key(unit_b),
            "rows": rows, "direct": {"score_a": direct_a, "score_b": direct_b, "flows": len(side_a["flow_ids"]),
                                     "unmatched": unmatched_flows},
            "open_share": open_a / scale, "unsure_share": unsure_a / scale, "drivers": drivers,
            "counts": {"inputs": len(rows), "matched": sum(1 for r in rows if r["match"]),
                       "confirmed": sum(1 for r in rows if r["origin"] in ("user", "file", "same", "code", "exact") and r["match"]),
                       "unsure": sum(1 for r in rows if r["origin"] == "auto" and r["quality"] == "unsure")}}


def _target_background(database: str) -> engine.Background:
    """The background that calculates the datasets of `database` (current project): the calculation's own if it
    includes the database, else the database alone. A premise scenario or EXIOBASE is not part of the calculation
    until chosen under Start; taking the calculation's background regardless gave its datasets a score of 0."""
    bg = models.system().bg
    return bg if database in bg.dbs else engine.alone(database).bg


def _drivers(rows: list[dict], direct_a: float, direct_b: float, difference: float) -> dict:
    """Which datasets make the difference between the two results, largest first.

    The difference splits exactly into one part per dataset, d_i (k_i s_B(m(i)) - s_A(i)), plus the direct emissions
    (same flows, other factors). A dataset without counterpart counts with -its score here. "ratio" says how much more
    (or less) one unit costs there than here: the sensitivity of the result to the choice of that dataset."""
    parts = []
    for i, r in enumerate(rows):
        d = r.get("score_b", 0.0) - r["score_a"]
        r["diff"] = d
        ratio = r["score_b"] / r["score_a"] if r["match"] and r["score_a"] else None
        parts.append({"row": i, "kind": "dataset" if r["match"] else "missing", "diff": d, "ratio": ratio})
    if direct_a or direct_b:
        parts.append({"row": None, "kind": "direct", "diff": direct_b - direct_a,
                      "ratio": direct_b / direct_a if direct_a else None})
    return _rank(parts, difference)


def _rank(parts: list[dict], difference: float) -> dict:
    """Parts largest first, with their signed share of the difference and the cumulative share of all changes."""
    parts.sort(key=lambda x: -abs(x["diff"]))
    gross = sum(abs(x["diff"]) for x in parts) or 1.0
    cum = 0.0
    for x in parts:
        cum += abs(x["diff"])
        x["share"] = x["diff"] / difference if difference else None  # signed: parts can offset each other
        x["gross_share"], x["cumulative"] = abs(x["diff"]) / gross, cum / gross
    top80 = next((n + 1 for n, x in enumerate(parts) if x["cumulative"] >= 0.8 - 1e-12), len(parts))
    return {"parts": [x for x in parts if x["diff"] != 0], "explain80": top80 if any(x["diff"] for x in parts) else 0,
            "offsetting": gross - abs(difference) > 1e-9 * gross}


# ---------- one level deeper ----------

def _inputs(node_id: int, method: tuple, bg: engine.Background | None = None) -> tuple[list[dict], float, float]:
    """Direct inputs of a background dataset per unit of its product, each with its share of the dataset's score.

    Column c of A: A_cc s_c = sum_(r != c) -A_rc s_r + direct_c, so the inputs and the own emissions add up exactly
    to the unit score. Returns (inputs, own emissions, unit score)."""
    bg = bg or models.system().bg
    if node_id not in bg.act_col or node_id not in bg.prod_row:
        raise KeyError(_("Prozess {id} ist in diesem Projekt nicht berechenbar.", id=node_id))
    c, own = bg.act_col[node_id], bg.prod_row[node_id]
    p = float(bg.production[c])
    s = bg.unit_scores(method)
    col = bg.A[:, c]
    ids = [int(bg.prod_ids[r]) for r in col.indices]
    info = _node_attrs(ids)
    out = []
    for r, v, nid in zip(col.indices, col.data, ids):
        if r == own or v == 0:
            continue
        amount = -float(v) / p
        d = info[nid]
        out.append({"id": nid, "database": d["database"], "code": d["code"], "name": d["name"], "location": d["location"],
                    "unit": d["unit"], "amount": amount, "score": amount * float(s[r])})
    return out, float(bg.direct(method)[c]) / p, float(s[own])


def _pairs(ins_a: list[dict], ins_b: list[dict], database: str, index: TargetIndex) -> list[tuple]:
    """Pairs each input here with an input of the counterpart: saved choice, same dataset or code, else by name.

    Returns (a or None, b or None, how)."""
    by_code = {b["code"]: b for b in ins_b}
    used, out, rest = set(), [], []
    for a in ins_a:
        choice = saved(a["database"], database).get(a["code"])
        code = choice.get("code") if choice else a["code"]
        b = by_code.get(code) if code else None
        if b is not None and b["code"] not in used:
            used.add(b["code"])
            out.append((a, b, "user" if choice else ("same" if a["database"] == database else "code")))
        else:
            rest.append(a)
    cands = []
    for a in rest:
        words, head, market = _src_text(a["name"])
        for b in ins_b:
            if b["code"] in used or factor(a["unit"], b["unit"]) is None or b["id"] not in index.rows:
                continue
            sc = index.score(index.rows[b["id"]], words, head, market, a["location"], a["name"])
            if sc >= 0.3:
                cands.append((sc, a["id"], b["code"]))
    cands.sort(key=lambda t: -t[0])
    a_by_id, done = {a["id"]: a for a in rest}, set()
    for sc, aid, code in cands:
        if aid in done or code in used:
            continue
        done.add(aid)
        used.add(code)
        out.append((a_by_id[aid], by_code[code], "name"))
    out += [(a, None, None) for a in rest if a["id"] not in done]
    out += [(None, b, None) for b in ins_b if b["code"] not in used]
    return out


def trace(source_id: int, target_code: str, scale_a: float, scale_b: float, method: tuple, project: str,
          database: str, target_method: list) -> dict:
    """The difference of one pair of datasets, split by their own inputs: one level down the supply chain.

    scale_a and scale_b are how much of each the product needs (here, there), so the parts add up exactly to the
    pair's part of the difference, scale_b s_B(target) - scale_a s_A(source). Every pair of inputs can be split again."""
    from . import service

    source_id, method, method_b = int(source_id), tuple(method), tuple(target_method)
    cur = bd.projects.current
    ins_a, own_a, s_a = _inputs(source_id, method)
    head_a = _node_attrs([source_id])[source_id]
    try:
        if project != cur:
            service.visit(project)
        if database not in bd.databases or method_b not in bd.methods:
            raise KeyError(_("Die Datenbank «{name}» gibt es in diesem Projekt nicht.", name=database))
        index = _index(project, database)
        if target_code not in index.by_code:
            raise KeyError(_("Das Gegenstück gibt es in «{name}» nicht mehr. Rechne den Vergleich neu.", name=database))
        target_id = index.by_code[target_code]
        ins_b, own_b, s_b = _inputs(target_id, method_b, _target_background(database))
        pairs = _pairs(ins_a, ins_b, database, index)
    finally:
        service.leave(cur)

    def side(x, scale):
        if x is None:
            return None
        return {"id": str(x["id"]), "code": x["code"], "database": x["database"], "name": x["name"],
                "location": x["location"], "unit": short_unit(x["unit"]), "amount": x["amount"] * scale,
                "score": x["score"] * scale}

    parts = []
    for a, b, how in pairs:
        pa, pb = side(a, scale_a), side(b, scale_b)
        sa, sb = (pa or {}).get("score", 0.0), (pb or {}).get("score", 0.0)
        parts.append({"kind": "pair" if a and b else ("only_a" if a else "only_b"), "how": how, "a": pa, "b": pb,
                      "diff": sb - sa, "ratio": sb / sa if a and b and sa else None})
    if own_a or own_b:
        parts.append({"kind": "direct", "how": None, "a": None, "b": None, "diff": scale_b * own_b - scale_a * own_a,
                      "ratio": own_b / own_a if own_a else None, "score_a": scale_a * own_a, "score_b": scale_b * own_b})
    total_a, total_b = scale_a * s_a, scale_b * s_b
    ranked = _rank(parts, total_b - total_a)
    return {"a": {"name": head_a["name"], "location": head_a["location"], "score": total_a},
            "b": {"name": index.rows[target_id]["name"], "location": index.rows[target_id]["location"], "score": total_b},
            "difference": total_b - total_a, **ranked,
            "counts": {"a": len(ins_a), "b": len(ins_b), "paired": sum(1 for x in parts if x["kind"] == "pair")}}


def search(project: str, database: str, q: str, unit: str | None = None, location: str | None = None) -> list[dict]:
    """Datasets of the other database for a free text; those in a convertible unit first, then the nearest to
    `location`; words this database does not have are corrected ("spelling" in each row)."""
    from . import service

    cur = bd.projects.current
    try:
        if project != cur:
            service.visit(project)
        if database not in bd.databases:
            raise KeyError(_("Die Datenbank «{name}» gibt es in diesem Projekt nicht.", name=database))
        rows, spelling = _index(project, database).search(q, unit, location=location)
        return [{"code": d["code"], "name": d["name"], "product": d["product"], "location": d["location"],
                 "unit": short_unit(d["unit"]),
                 "convertible": factor(unit, d["unit"]) is not None or sectors.money(d["unit"]) is not None,
                 **({"spelling": spelling} if spelling else {})} for d in rows]
    finally:
        service.leave(cur)
