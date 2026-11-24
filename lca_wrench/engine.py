"""Fast LCA engine: cached background, live foreground.

Background = the big, self-contained databases (BAFU, ecoinvent, USEEIO ...).
Their technosphere matrix is built with bw2calc and factorized once per
project version; cumulative unit scores per method are cached.

Foreground = the user's own model databases. They are read straight from
SQLite on every change (they are small), solved on their own and coupled to
the background through the cached unit scores. Background never consumes
foreground products, so the system is block-triangular and the result is
exact, not an approximation:

    [A_bb  A_bf] [x_b]   [f_b]
    [ 0    A_ff] [x_f] = [f_f]

    x_f = A_ff^-1 f_f
    x_b = A_bb^-1 (f_b - A_bf x_f)
    h   = s_b . (f_b - A_bf x_f) + c . B_f x_f,   s_b = c B_b A_bb^-1 (cached)

Factors that depend on where an activity is (regional.py) enter as a matrix R of the shape of B: (factor at the
activity's place - normal factor) times B. The characterized biosphere matrix is diag(c) B + R, so the direct impacts
are B^T c + 1^T R; without such factors R is None and nothing changes.

tests/test_engine.py checks every quantity against plain bw2calc, tests/test_regional.py the factors by location.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

import bw2calc as bc
import bw2data as bd
import numpy as np
from bw2data.backends.schema import ActivityDataset as AD
from bw2data.backends.schema import ExchangeDataset as ED
from bw2data.configuration import labels
from fsspec.implementations.zip import ZipFileSystem
from scipy import sparse
from scipy.linalg import lu_factor, lu_solve
from scipy.sparse.linalg import splu

from . import completion, flowmap, i18n, regional
from . import functional  # noqa: F401  (registers the backend: Activity Browser 3 databases open at all)
from .i18n import msg, render

BIOSPHERE_NODE_TYPES = ("emission", "natural resource", "economic", "inventory indicator", "social")
NEGATIVE = set(labels.technosphere_negative_edge_types)
POSITIVE = set(labels.technosphere_positive_edge_types)
BIOSPHERE = set(labels.biosphere_edge_types)
PROCESS_TYPES = set(labels.process_node_types)
IMPLICIT_PRODUCTION = set(labels.implicit_production_allowed_node_types)
# Activity Browser 3 (bw_functional, backend "functional_sqlite"): the products of a process are nodes of their own
FUNCTION_TYPES = ("product", "waste")
# processes as listed for the user: also those with several products or none (their products are listed with them)
LISTED_PROCESS_TYPES = PROCESS_TYPES | {"multifunctional", "nonfunctional"}

_lock = threading.RLock()


class ModelError(ValueError):
    """The user's model cannot be solved (missing production, singular, broken link)."""


def close_files(lca: bc.LCA) -> None:
    """Close the matrix files (processed/*.zip) a bw2calc LCA has opened. bw_processing reads every array when it opens
    a file, so nothing reads them again, but bw2calc leaves them open as long as the LCA lives. Windows cannot delete
    an open file: with the cached backgrounds holding them, removing a background database or deleting a project failed
    there ("being used by another process")."""
    for pkg in lca.packages:
        fs = getattr(pkg, "fs", None)
        if isinstance(fs, ZipFileSystem):
            fs.close()  # the archive ...
            if hasattr(getattr(fs, "of", None), "close"):
                fs.of.close()  # ... and the file under it, which the archive leaves open


# ---------- database roles ----------

def _first_node_type(name: str) -> str | None:
    row = AD.select(AD.type).where(AD.database == name).limit(1).tuples().first()
    return row[0] if row else None


_roles_cache: dict = {}


def database_roles(model_dbs: set[str] | None = None) -> dict[str, str]:
    """Role per database: 'biosphere', 'background', 'model' or 'empty'.

    Background databases are self-contained (they link to no other process
    database). Everything that links into them, plus databases registered as
    models by this app, is foreground and can be edited live.
    """
    model_dbs = set(model_dbs or ())
    project = bd.projects.current
    key = (project, tuple(sorted(model_dbs)), tuple(sorted((n, tuple(m.get("depends") or ())) for n, m in bd.databases.items())),
           versions(project))
    if key not in _roles_cache:
        if len(_roles_cache) > 50:
            _roles_cache.clear()
        _roles_cache[key] = _database_roles(model_dbs)
    return dict(_roles_cache[key])


def _database_roles(model_dbs: set[str]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for name in bd.databases:
        t = _first_node_type(name)
        if name in model_dbs:
            roles[name] = "model"
        elif t is None:
            roles[name] = "empty"
        elif t in BIOSPHERE_NODE_TYPES:
            roles[name] = "biosphere"
        else:
            roles[name] = "?"
    tech = {n for n, r in roles.items() if r in ("?", "model")}
    for name, r in roles.items():
        if r != "?":
            continue
        deps = set(bd.databases[name].get("depends") or ()) - {name}
        roles[name] = "model" if deps & tech else "background"
    return roles


# ---------- background ----------

class Background:
    def __init__(self, dbs: list[str]):
        self.dbs = list(dbs)
        self.lca = None
        self._cvec: dict = {}
        self._direct: dict = {}
        self._unit: dict = {}
        self._reg: dict = {}
        self._places: dict = {}
        demand = {}
        for name in self.dbs:
            node_id = AD.select(AD.id).where(AD.database == name, AD.type << list(PROCESS_TYPES)).limit(1).scalar()
            if node_id is not None:
                demand[node_id] = 1
        if not demand:
            self.A = sparse.csc_matrix((0, 0))
            self.B = sparse.csc_matrix((0, 0))
            self.act_ids = self.prod_ids = self.bio_ids = np.zeros(0, dtype=np.int64)
            self.production = np.zeros(0)
            self.solve = self.solve_t = lambda b: np.zeros(0)
        else:
            lca = bc.LCA(demand)
            lca.load_lci_data()
            close_files(lca)  # all read; kept open, the cache would lock them (Windows)
            self.lca = lca
            self.A = lca.technosphere_matrix.tocsc()
            self.B = lca.biosphere_matrix.tocsc()
            self.act_ids = _ids_by_index(lca.dicts.activity)
            self.prod_ids = _ids_by_index(lca.dicts.product)
            self.bio_ids = _ids_by_index(lca.dicts.biosphere)
            AT = self.A.T.tocsr()
            blocks = BlockSolver.build(self.A, self.prod_ids, self.act_ids)
            if blocks is not None:  # several databases side by side, or a dense one (MRIO): one solver each
                self.solver = blocks
                self.solve = lambda b: refined(blocks.solve, self.A, b)
                self.solve_t = lambda b: refined(blocks.solve_t, AT, b)
            else:
                # one LU factorization serves both A x = b and A^T y = c
                lu = fast_lu(self.A)
                self.solver = None
                self.solve = lambda b: refined(lu.solve, self.A, b)
                self.solve_t = lambda b: refined(lambda v: lu.solve(v, trans="T"), AT, b)
            diag = self.A.diagonal()
            prod_row = dict(lca.dicts.product)
            self.production = np.array([self.A[prod_row[a], c] if a in prod_row else diag[c]
                                        for c, a in enumerate(self.act_ids)], dtype=float)
        self.act_col = {int(a): i for i, a in enumerate(self.act_ids)}
        self.prod_row = {int(p): i for i, p in enumerate(self.prod_ids)}
        self.bio_row = {int(f): i for i, f in enumerate(self.bio_ids)}

    def cvec(self, method: tuple) -> np.ndarray:
        if method not in self._cvec:
            if self.lca is None:
                self._cvec[method] = np.zeros(0)
            else:
                self.lca.switch_method(method)
                close_files(self.lca)  # the method's file, read now
                c = np.asarray(self.lca.characterization_matrix.diagonal()).ravel().copy()
                add = extra_vector(method, self.bio_ids)  # factors the method lacks: flow mapping, completion
                self._cvec[method] = c + add if add is not None else c
        return self._cvec[method]

    def places(self, volumes: bool = True) -> regional.Places:
        """Where each activity column is, for factors that depend on the location (regional.py). volumes=False: the
        locations only, regions weighted equally (enough to group a result by location, and much quicker)."""
        if volumes not in self._places:
            self._places[volumes] = regional.places_for(self.act_ids, volumes=volumes, databases=self.dbs)
        return self._places[volumes]

    def regional(self, method: tuple) -> regional.Part | None:
        """The location-dependent part of the characterized biosphere matrix; None when the method has none."""
        if method not in self._reg:
            T = regional.active(method) if self.lca is not None else None
            self._reg[method] = regional.matrix(T, self.bio_ids, self.places(), self.B, self.cvec(method)) if T else None
        return self._reg[method]

    def direct(self, method: tuple) -> np.ndarray:
        """Characterized direct emissions per activity column (for its production amount)."""
        if method not in self._direct:
            d = np.asarray(self.B.T @ self.cvec(method)).ravel()
            part = self.regional(method)
            self._direct[method] = d + np.asarray(part.R.sum(axis=0)).ravel() if part is not None else d
        return self._direct[method]

    def unit_scores(self, method: tuple) -> np.ndarray:
        """Cumulative score per unit of each product row (s_b)."""
        if method not in self._unit:
            self._unit[method] = self.solve_t(self.direct(method)) if self.A.shape[0] else np.zeros(0)
        return self._unit[method]


def fast_lu(A):
    """LU of the technosphere matrix, much faster and sparser than SuperLU's default.

    Symmetric-mode ordering (MMD on A + A^T, diagonal pivots) keeps the factors small: for BAFU (11'700 products)
    0.75 s instead of 4 s and 0.5 M instead of 6.8 M entries; a synthetic 23'500-product matrix with
    ecoinvent-like density 32 s instead of 250 s and 12 M instead of 106 M entries (see README, bench_gross.py).
    The price is that pivoting is off, so the result is checked: two test systems (A and its transpose) must have a
    residual below 1e-12 after the usual refinement, otherwise the default factorization is used. (The residual is
    the right measure; the error of x itself is limited by the condition of A, about 1e10 for BAFU, with any LU.)
    """
    A = A.tocsc()
    n = A.shape[0]
    try:
        lu = splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0, options={"SymmetricMode": True})
        x_true = np.linspace(1.0, 2.0, n)
        b, bt = A @ x_true, A.T @ x_true
        x = refined(lu.solve, A, b)
        xt = refined(lambda v: lu.solve(v, trans="T"), A.T.tocsr(), bt)
        ok = (np.all(np.isfinite(x)) and np.all(np.isfinite(xt))
              and np.linalg.norm(b - A @ x) <= 1e-12 * np.linalg.norm(b)
              and np.linalg.norm(bt - A.T @ xt) <= 1e-12 * np.linalg.norm(bt))
        if ok:
            return lu
    except RuntimeError:
        pass
    return splu(A)


DENSE = 0.05  # a block with more than 5 % non-zero entries is solved as a dense matrix (LAPACK)


class BlockSolver:
    """Separate solvers for databases that do not link to each other (ecoinvent next to a premise scenario next to
    EXIOBASE): the matrix is block-diagonal by database, and each block gets the solver that suits it. A sparse
    process database gets the sparse LU (fast_lu); a dense input-output table (EXIOBASE: about 10'000 sectors, a third
    of all entries non-zero) a dense LU, which is much faster there than a sparse one and needs n² numbers of memory
    (0.8 GB for EXIOBASE)."""

    def __init__(self, blocks):
        self.blocks = blocks  # [(rows, cols, kind, factor)]
        self.kinds = [k for _r, _c, k, _f in blocks]

    @classmethod
    def build(cls, A, prod_ids, act_ids) -> BlockSolver | None:
        n = A.shape[0]
        if n == 0 or A.shape[1] != n:
            return None
        db_of = _databases_of(np.concatenate([prod_ids, act_ids]))
        names = sorted({db_of.get(int(i), "") for i in act_ids})
        dense_one = len(names) == 1 and A.nnz > DENSE * n * n and n > 1
        if len(names) == 1 and not dense_one:
            return None
        rdb = np.array([db_of.get(int(i), "") for i in prod_ids], dtype=object)
        cdb = np.array([db_of.get(int(i), "") for i in act_ids], dtype=object)
        coo = A.tocoo()
        if np.any(rdb[coo.row] != cdb[coo.col]):
            return None  # linked to each other: one matrix
        blocks = []
        for d in names:
            r, c = np.flatnonzero(rdb == d), np.flatnonzero(cdb == d)
            if len(r) != len(c):
                return None
            M = A[r][:, c].tocsc()
            if M.nnz > DENSE * len(r) * len(r):
                blocks.append((r, c, "dense", lu_factor(M.toarray())))
            else:
                blocks.append((r, c, "sparse", fast_lu(M)))
        return cls(blocks)

    def solve(self, b: np.ndarray) -> np.ndarray:
        x = np.zeros(len(b))
        for r, c, kind, f in self.blocks:
            x[c] = lu_solve(f, b[r]) if kind == "dense" else f.solve(b[r])
        return x

    def solve_t(self, g: np.ndarray) -> np.ndarray:
        y = np.zeros(len(g))
        for r, c, kind, f in self.blocks:
            y[r] = lu_solve(f, g[c], trans=1) if kind == "dense" else f.solve(g[c], trans="T")
        return y


def _databases_of(ids) -> dict[int, str]:
    ids = sorted({int(i) for i in ids})
    out = {}
    for i in range(0, len(ids), 900):
        out.update(dict(AD.select(AD.id, AD.database).where(AD.id << ids[i:i + 900]).tuples()))
    return out


def refined(solve, M, b: np.ndarray, steps: int = 2) -> np.ndarray:
    """Solve M x = b with an existing LU, plus iterative refinement.

    SuperLU alone leaves relative errors up to ~1e-5 in single unit scores of
    BAFU (seen for "Packing, lime products"); one refinement step brings them
    to ~1e-15 for ~15 ms.
    """
    x = solve(b)
    for _ in range(steps):
        x = x + solve(b - M @ x)
    return x


def _ids_by_index(mapping) -> np.ndarray:
    items = sorted(dict(mapping).items(), key=lambda kv: kv[1])
    return np.array([k for k, _ in items], dtype=np.int64)


# ---------- foreground ----------

class Foreground:
    """Matrices of the model databases, read directly from SQLite."""

    def __init__(self, dbs: list[str], bg: Background, alias: dict | None = None, factors: dict | None = None):
        """alias: {(database, code): node id} for inputs from a background database that is not in the calculation,
        taken from its counterpart in the chosen background (e.g. a premise scenario instead of ecoinvent).
        factors: {product id: allocation factor} instead of the stored ones (comparing allocations, `with_factors`)."""
        self.dbs = list(dbs)
        self.alias_keys = dict(alias or {})
        self.factor_override = dict(factors or {})
        self.errors: list[tuple] = []  # i18n.msg, rendered in the reader's language
        self.notes: list[tuple] = []  # the same, for what calculates but deserves a look (allocation factors)
        self.functions: dict[int, list[tuple[int, float | None]]] = {}  # process id -> [(product id, factor)]
        self.nodes: dict[int, dict] = {}
        nb, nbio = bg.A.shape[0], len(bg.bio_ids)
        if not self.dbs:
            self._empty(nb, nbio)
            return

        key_id, kinds = {}, {}
        for nid, db, code, typ, name, loc in (AD.select(AD.id, AD.database, AD.code, AD.type, AD.name, AD.location)
                                              .where(AD.database << self.dbs).tuples()):
            key_id[(db, code)] = nid
            kinds[nid] = typ
            self.nodes[nid] = {"name": name, "location": loc, "database": db, "type": typ}
        rows = list(ED.select(ED.id, ED.data, ED.input_database, ED.input_code, ED.output_database,
                              ED.output_code, ED.type).where(ED.output_database << self.dbs).tuples())
        for k, nid in (alias or {}).items():
            key_id[k] = nid
            kinds.setdefault(nid, "process")
        missing: dict[str, set] = {}
        for _, _, idb, icode, *_ in rows:
            if (idb, icode) not in key_id:
                missing.setdefault(idb, set()).add(icode)
        for idb, codes in missing.items():
            codes = list(codes)
            for i in range(0, len(codes), 500):
                for nid, code, typ in (AD.select(AD.id, AD.code, AD.type)
                                       .where(AD.database == idb, AD.code << codes[i:i + 500]).tuples()):
                    key_id[(idb, code)] = nid
                    kinds[nid] = typ

        # Processes with products of their own (Activity Browser 3): as in bw_functional's processing, the products
        # are the columns. Every input, emission and credit of the process is split onto its products by their
        # allocation factors (a factor that is not set counts as 1); each product's own production edge goes to its
        # column unchanged.
        self.functions = self._functions(key_id)
        for pid, fs in self.functions.items():
            total = sum(1.0 if a is None else a for _, a in fs)
            if len(fs) > 1 and abs(total - 1.0) > 1e-6:
                self.notes.append(msg("Die Allokationsfaktoren von «{name}» ergeben zusammen {total} statt 1.",
                                      name=self.nodes.get(pid, {}).get("name", pid), total=f"{total:.4g}"))

        # columns: every process node of the model databases, or its products
        cols = [nid for nid, t in kinds.items() if t in PROCESS_TYPES and nid not in self.functions
                and self.nodes.get(nid, {}).get("database") in self.dbs]
        cols += [f for fs in self.functions.values() for f, _ in fs]
        cols.sort()
        col = {nid: i for i, nid in enumerate(cols)}

        tech, bio = [], []  # (row id, col index, value)
        has_production = set()
        broken = 0
        for _, data, idb, icode, odb, ocode, etype in rows:
            out_id = key_id.get((odb, ocode))
            in_id = key_id.get((idb, icode))
            if out_id is None:
                continue
            production = etype in POSITIVE and etype not in labels.substitution_edge_types
            if out_id in self.functions:
                fs = self.functions[out_id]
                if production:  # only to the column of the product it produces
                    targets = [(col[f], 1.0) for f, _ in fs if f == in_id]
                else:
                    targets = [(col[f], 1.0 if a is None else a) for f, a in fs]
            elif out_id in col:
                targets = [(col[out_id], 1.0)]
            else:
                continue
            if in_id is None:
                broken += 1
                continue
            amount = float(data.get("amount", 0) or 0)
            for c, share in targets:
                if etype in BIOSPHERE:
                    bio.append((in_id, c, amount * share))
                elif etype in NEGATIVE:
                    tech.append((in_id, c, -amount * share))
                elif etype in POSITIVE:
                    tech.append((in_id, c, amount * share))
                    if production:
                        has_production.add(cols[c])
        for nid in cols:
            if nid not in has_production:
                if kinds[nid] in IMPLICIT_PRODUCTION:
                    tech.append((nid, col[nid], 1.0))
                else:
                    self.errors.append(msg("«{name}» hat keinen Referenzfluss (Produktion).", name=self.nodes[nid]["name"]))
        if broken:
            self.errors.append(msg("{n} Austausch(e) verweisen auf Prozesse, die es nicht mehr gibt.", n=broken))

        fg_rows = sorted({r for r, _, _ in tech if r in self.nodes})
        row = {nid: i for i, nid in enumerate(fg_rows)}
        A_ff, A_bf = [], []
        for r, c, v in tech:
            if r in row:
                A_ff.append((row[r], c, v))
            elif r in bg.prod_row:
                A_bf.append((bg.prod_row[r], c, v))
            else:
                self.errors.append(msg("Ein Input verweist auf «{name}», das in keiner geladenen Datenbank liegt.", name=r))
        extra: dict[int, int] = {}
        B = []
        for f, c, v in bio:
            if f in bg.bio_row:
                B.append((bg.bio_row[f], c, v))
            else:
                if f not in extra:
                    extra[f] = nbio + len(extra)
                B.append((extra[f], c, v))

        nf = len(cols)
        self.act_ids = np.array(cols, dtype=np.int64)
        self.prod_ids = np.array(fg_rows, dtype=np.int64)
        self.act_col = col
        self.prod_row = row
        self.extra_bio = extra
        self.A_ff = _coo(A_ff, (len(fg_rows), nf))
        self.A_bf = _coo(A_bf, (nb, nf))
        self.B_f = _coo(B, (nbio + len(extra), nf))
        if len(fg_rows) != nf:
            self.errors.append(msg("Das Modell hat {n} Prozesse, aber {m} Produkte. Jeder Prozess braucht genau ein Referenzprodukt.",
                                   n=nf, m=len(fg_rows)))
        self.lu = None
        if nf and not self.errors:
            try:
                self.lu = splu(self.A_ff.tocsc())
            except RuntimeError:
                self.errors.append(msg("Das Modell ist nicht lösbar: Die Produktionsmengen heben sich gegenseitig auf (singuläre Matrix)."))
        diag = {}
        A = self.A_ff.tocsc()
        for c, nid in enumerate(cols):
            r = row.get(nid)
            diag[c] = A[r, c] if r is not None else 0.0
        self.production = np.array([diag[c] for c in range(nf)], dtype=float)

    def _empty(self, nb, nbio):
        self.act_ids = self.prod_ids = np.zeros(0, dtype=np.int64)
        self.act_col, self.prod_row, self.extra_bio = {}, {}, {}
        self.A_ff = sparse.csc_matrix((0, 0))
        self.A_bf = sparse.csc_matrix((nb, 0))
        self.B_f = sparse.csc_matrix((nbio, 0))
        self.lu = None
        self.production = np.zeros(0)

    def error_texts(self) -> list[str]:
        return [render(e) for e in dict.fromkeys(self.errors)]

    def note_texts(self) -> list[str]:
        return [render(e) for e in dict.fromkeys(self.notes)]

    def _functions(self, key_id: dict) -> dict[int, list[tuple[int, float | None]]]:
        """Process id -> its products [(product id, allocation factor or None)], from the products' `processor`."""
        out: dict[int, list[tuple[int, float | None]]] = {}
        for nid, data in (AD.select(AD.id, AD.data)
                          .where((AD.database << self.dbs) & (AD.type << list(FUNCTION_TYPES))).tuples()):
            out_key = data.get("processor")
            pid = key_id.get(tuple(out_key)) if isinstance(out_key, (list, tuple)) and len(out_key) == 2 else None
            if pid is None:
                continue
            factor = self.factor_override.get(nid, data.get("allocation_factor"))
            out.setdefault(pid, []).append((nid, float(factor) if _is_number(factor) else None))
        for fs in out.values():
            fs.sort()
        return out

    def check(self) -> None:
        if self.errors:
            raise ModelError(" ".join(self.error_texts()))


def with_factors(S: System, factors: dict[int, float]) -> System:
    """The same calculation with other allocation factors for some products, nothing saved (comparing allocations).
    Rebuilds only the models; the background and its factorization are shared. Not cached."""
    fg = Foreground(S.fg.dbs, S.bg, S.fg.alias_keys, factors={**S.fg.factor_override, **factors})
    out = System(S.bg, fg)
    out.substituted, out.pulled, out.pulled_ids = S.substituted, S.pulled, S.pulled_ids
    return out


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and np.isfinite(x)


def products_of(node_id: int) -> list[tuple[int, float | None]]:
    """The products of a process stored as in Activity Browser 3 [(product id, allocation factor)]; [] otherwise."""
    node = AD.get_or_none(AD.id == int(node_id))
    if node is None or node.type in FUNCTION_TYPES:
        return []
    out = []
    for nid, data in (AD.select(AD.id, AD.data)
                      .where((AD.database == node.database) & (AD.type << list(FUNCTION_TYPES))).tuples()):
        if tuple(data.get("processor") or ()) == (node.database, node.code):
            factor = data.get("allocation_factor")
            out.append((nid, float(factor) if _is_number(factor) else None))
    return sorted(out)


def _coo(entries, shape) -> sparse.csc_matrix:
    if not entries:
        return sparse.csc_matrix(shape)
    r, c, v = zip(*entries)
    return sparse.coo_matrix((np.array(v, dtype=float), (np.array(r), np.array(c))), shape=shape).tocsc()


# ---------- combined system ----------

class System:
    """Background plus foreground with one index space.

    Product rows and activity columns: background first, then foreground.
    Biosphere rows: background flows, then flows used only by the models.
    """

    def __init__(self, bg: Background, fg: Foreground):
        self.bg, self.fg = bg, fg
        self.nb, self.nf = bg.A.shape[0], len(fg.act_ids)
        self.row_ids = np.concatenate([bg.prod_ids, fg.prod_ids])
        self.col_ids = np.concatenate([bg.act_ids, fg.act_ids])
        self.bio_ids = np.concatenate([bg.bio_ids, np.array(list(fg.extra_bio), dtype=np.int64)])
        self.row = {int(k): i for i, k in enumerate(self.row_ids)}
        self.col = {int(k): i for i, k in enumerate(self.col_ids)}
        self.bio_row = {int(k): i for i, k in enumerate(self.bio_ids)}
        self.production = np.concatenate([bg.production, fg.production])
        self.alias: dict[int, int | None] = {}  # node of a database not in this calculation -> its counterpart
        self.substituted = 0  # model inputs taken from the counterpart in the chosen background
        self.pulled: list[str] = []  # databases added because the chosen background lacks some model inputs
        self.pulled_ids: set[int] = set()
        self._unit: dict = {}
        self._cvec: dict = {}
        self._direct: dict = {}
        self._reg: dict = {}
        self._reg_f: dict = {}
        self._fg_places = None
        self._A = None
        self._B = None

    # matrices for traversal and inventories (built lazily)
    @property
    def A(self) -> sparse.csc_matrix:
        if self._A is None:
            nfr = len(self.fg.prod_ids)
            self._A = sparse.bmat([[self.bg.A, self.fg.A_bf],
                                   [sparse.csc_matrix((nfr, self.nb)), self.fg.A_ff]], format="csc") \
                if self.nf else self.bg.A
        return self._A

    @property
    def B(self) -> sparse.csc_matrix:
        if self._B is None:
            nbio = len(self.bio_ids)
            Bb = self.bg.B
            if Bb.shape[0] < nbio:
                Bb = sparse.vstack([Bb, sparse.csc_matrix((nbio - Bb.shape[0], Bb.shape[1]))]).tocsc()
            self._B = sparse.hstack([Bb, self.fg.B_f]).tocsc() if self.nf else Bb
        return self._B

    def cvec(self, method: tuple) -> np.ndarray:
        if method not in self._cvec:
            c = self.bg.cvec(method)
            if self.fg.extra_bio:
                cf, add = method_cfs(method), extra_cfs(method)
                c = np.concatenate([c, [cf.get(f, 0.0) + add.get(f, 0.0) for f in self.fg.extra_bio]])
            self._cvec[method] = c
        return self._cvec[method]

    def direct(self, method: tuple) -> np.ndarray:
        if method not in self._direct:
            d_b = self.bg.direct(method)
            d_f = np.asarray(self.fg.B_f.T @ self.cvec(method)).ravel() if self.nf else np.zeros(0)
            part = self._regional_fg(method)
            if part is not None:
                d_f = d_f + np.asarray(part.R.sum(axis=0)).ravel()
            self._direct[method] = np.concatenate([d_b, d_f])
        return self._direct[method]

    # ---------- factors that depend on the location (regional.py) ----------

    def fg_places(self) -> regional.Places:
        if self._fg_places is None:
            info = {int(i): (n["database"], n["name"], None, n["location"]) for i, n in self.fg.nodes.items()}
            self._fg_places = regional.places_for(self.fg.act_ids, info, volumes=False)
        return self._fg_places

    def _regional_fg(self, method: tuple) -> regional.Part | None:
        if method not in self._reg_f:
            T = regional.active(method) if self.nf else None
            self._reg_f[method] = regional.matrix(T, self.bio_ids, self.fg_places(), self.fg.B_f, self.cvec(method)) \
                if T else None
        return self._reg_f[method]

    def regional(self, method: tuple) -> sparse.csc_matrix | None:
        """R: the location-dependent part of the characterized biosphere matrix over all columns, so that the
        characterized B is diag(c) B + R (None when the method has no factors by location or they are off)."""
        if method not in self._reg:
            pb, pf = self.bg.regional(method), self._regional_fg(method)
            R = None
            if pb is not None or pf is not None:
                nbio = len(self.bio_ids)
                Rb = pb.R if pb is not None else sparse.csc_matrix((len(self.bg.bio_ids), self.nb))
                if Rb.shape[0] < nbio:
                    Rb = sparse.vstack([Rb, sparse.csc_matrix((nbio - Rb.shape[0], Rb.shape[1]))]).tocsc()
                Rf = pf.R if pf is not None else sparse.csc_matrix((nbio, self.nf))
                R = sparse.hstack([Rb, Rf]).tocsc() if self.nf else Rb
            self._reg[method] = R
        return self._reg[method]

    def flow_impacts(self, method: tuple, x: np.ndarray) -> np.ndarray:
        """Impact per elementary flow for the supply x: c ∘ (B x), plus the part by location."""
        out = self.cvec(method) * self.inventory(x)
        R = self.regional(method)
        return out + np.asarray(R @ x).ravel() if R is not None else out

    def place(self, col: int) -> regional.Place:
        return self.bg.places().column(col) if col < self.nb else self.fg_places().column(col - self.nb)

    def column_places(self, method: tuple) -> tuple[np.ndarray, list, np.ndarray]:
        """Per column the index of its place in `places`, the places (background ones first) and, per place, how a
        flow of the method got its factor there (regional.OWN … NORMAL)."""
        rb, rf = self.bg.regional(method), self._regional_fg(method)
        pb, pf = self.bg.places(volumes=rb is not None), self.fg_places()  # the production volumes only when needed
        idx = np.concatenate([pb.index, pf.index + len(pb.places)]) if self.nf else pb.index
        how = np.zeros(len(pb.places) + len(pf.places), dtype=np.int8)
        if rb is not None:
            how[:len(pb.places)] = rb.how
        if rf is not None:
            how[len(pb.places):] = rf.how
        return idx, pb.places + pf.places, how

    def column_factors(self, method: tuple, col: int) -> np.ndarray:
        """The factor of every flow for the activity in column `col`: the normal factors, with those of its place."""
        c = self.cvec(method)
        T = regional.active(method)
        return regional.factors_at(T, self.bio_ids, c, self.place(col)) if T is not None else c

    def unit_scores(self, method: tuple) -> np.ndarray:
        """Cumulative score per unit of every product row, background and models."""
        if method not in self._unit:
            s_b = self.bg.unit_scores(method)
            u_f = np.zeros(0)
            if self.nf:
                self.fg.check()
                rhs = self.direct(method)[self.nb:] - np.asarray(self.fg.A_bf.T @ s_b).ravel()
                u_f = refined(lambda v: self.fg.lu.solve(v, trans="T"), self.fg.A_ff.T.tocsr(), rhs)
            self._unit[method] = np.concatenate([s_b, u_f])
        return self._unit[method]

    def demand_vector(self, demand: dict[int, float]) -> np.ndarray:
        f = np.zeros(len(self.row_ids))
        for node_id, amount in demand.items():
            f[self.ref_row(node_id)] += amount
        return f

    def ref_row(self, node_id: int) -> int:
        node_id = int(node_id)
        if node_id in self.pulled_ids:  # a database only here for inputs the chosen one lacks: its counterpart first
            other = self.counterpart(node_id)
            if other is not None and other != node_id and other not in self.pulled_ids:
                return self.ref_row(other)
        if node_id in self.row:
            return self.row[node_id]
        c = self.col.get(node_id)
        if c is not None:
            colv = self.A[:, c]
            pos = colv.indices[colv.data > 0]
            if len(pos):
                return int(pos[0])
        # a process stored as in Activity Browser 3: its product; with several products the user has to choose one
        fs = self.fg.functions.get(node_id) or products_of(node_id)
        if len(fs) == 1:
            return self.ref_row(fs[0][0])
        if fs:
            name = AD.select(AD.name).where(AD.id == node_id).scalar()
            raise KeyError(i18n._("«{name}» hat mehrere Produkte. Wähle eines davon.", name=name))
        other = self.counterpart(node_id)
        if other is not None and other != node_id:
            return self.ref_row(other)
        raise KeyError(i18n._("Prozess {id} ist in diesem Projekt nicht berechenbar.", id=node_id))

    def counterpart(self, node_id: int) -> int | None:
        """The same dataset in this calculation's background, for a node of a database that is not part of it."""
        node_id = int(node_id)
        if node_id not in self.alias:
            from . import backgrounds

            chosen = [d for d in self.bg.dbs if d not in self.pulled]
            self.alias[node_id] = backgrounds.counterparts([node_id], chosen).get(node_id)
        return self.alias[node_id]

    def supply(self, demand: dict[int, float]) -> np.ndarray:
        """Scaling vector x over all activity columns."""
        f = self.demand_vector(demand)
        f_b, f_f = f[:self.nb], f[self.nb:]
        x_f = np.zeros(0)
        if self.nf:
            self.fg.check()
            x_f = refined(self.fg.lu.solve, self.fg.A_ff, f_f) if np.any(f_f) else np.zeros(self.nf)
            f_b = f_b - np.asarray(self.fg.A_bf @ x_f).ravel()
        x_b = self.bg.solve(f_b) if self.nb and np.any(f_b) else np.zeros(self.nb)
        return np.concatenate([x_b, x_f])

    def score(self, demand: dict[int, float], method: tuple) -> float:
        return float(self.unit_scores(method) @ self.demand_vector(demand))

    def inventory(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self.B @ x).ravel()


def method_cfs(method: tuple) -> dict[int, float]:
    """The method's normal factors per flow id: its rows without location or with the global one, as bw2calc uses
    them. Rows with another location are factors by location (regional.py)."""
    out: dict[int, float] = {}
    for entry in bd.Method(method).load():
        if not regional.is_global(entry):
            continue
        key, cf = entry[0], entry[1]
        if isinstance(key, (list, tuple)):
            key = bd.get_id(tuple(key))
        out[int(key)] = out.get(int(key), 0.0) + float(cf if not isinstance(cf, dict) else cf.get("amount", 0.0))
    return out


def extra_cfs(method: tuple) -> dict[int, float]:
    """Factors that are not in the stored method: through the flow mapping (flowmap.py) for a flow list the method
    lacks, and completed for sub-compartments (completion.py). The two never meet on a flow."""
    return {**flowmap.added(method), **completion.added(method)}


def extra_vector(method: tuple, flow_ids) -> np.ndarray | None:
    """extra_cfs over `flow_ids` (a matrix's biosphere rows), to add to the method's own; None if there are none."""
    parts = [a for a in (flowmap.addition(method, flow_ids), completion.addition(method, flow_ids)) if a is not None]
    return sum(parts[1:], parts[0]) if parts else None


# ---------- cache ----------

_backgrounds: OrderedDict = OrderedDict()  # (project, bg_version, dbs) -> Background
_systems: OrderedDict = OrderedDict()  # (project, bg_version, fg_version) -> System
_bg_version: dict = {}
_fg_version: dict = {}


def bump_background(project: str) -> None:
    with _lock:
        _bg_version[project] = _bg_version.get(project, 0) + 1


def bump_all() -> None:
    """Every project's backgrounds and models again (the characterization changed: flow mapping, completion)."""
    with _lock:
        for p in set(_bg_version) | {k[0] for k in _backgrounds} | {k[0] for k in _systems}:
            _bg_version[p] = _bg_version.get(p, 0) + 1


def bump_foreground(project: str) -> None:
    with _lock:
        _fg_version[project] = _fg_version.get(project, 0) + 1


def backgrounds_in_use(project: str) -> set[str]:
    """Background databases of the cached calculations of `project` (a new database elsewhere needs no rebuild)."""
    with _lock:
        return {d for (p, _v, dbs) in _backgrounds for d in dbs if p == project}


def versions(project: str) -> tuple[int, int]:
    return _bg_version.get(project, 0), _fg_version.get(project, 0)


def system(model_dbs: set[str] | None = None, active: list[str] | None = None, substitute: bool = True) -> System:
    """Current project's system. Background is reused across model edits.

    active: the background databases chosen for the calculation (None: all of them). Inputs of the models from
    another background database are taken from their counterpart in the chosen ones (same code, or same name,
    product, location and unit); a database whose inputs have no counterpart there is added, and named in `pulled`.
    substitute=False: no counterparts, every background database the models link to is added as it is."""
    with _lock:
        project = bd.projects.current
        bgv, fgv = versions(project)
        roles = database_roles(model_dbs)
        all_bg = sorted(n for n, r in roles.items() if r == "background")
        chosen = sorted(set(active) & set(all_bg)) if active is not None else all_bg
        if not chosen:
            chosen = all_bg
        fg_dbs = sorted(n for n, r in roles.items() if r == "model")
        skey = (project, bgv, fgv, tuple(chosen), tuple(fg_dbs), substitute)
        if skey in _systems:
            _systems.move_to_end(skey)
            return _systems[skey]
        alias, pulled = {}, []
        others = sorted(set(all_bg) - set(chosen))
        if others and fg_dbs:
            from . import backgrounds

            refs: dict[str, set] = {}
            for idb, icode in (ED.select(ED.input_database, ED.input_code)
                               .where((ED.output_database << fg_dbs) & (ED.input_database << others)).tuples()):
                refs.setdefault(idb, set()).add(icode)
            if substitute:
                alias, unmatched = backgrounds.counterparts_by_key(refs, chosen)
            else:
                unmatched = refs
            pulled = sorted(unmatched)
        bg_dbs = sorted(set(chosen) | set(pulled))
        bg = _background(project, bgv, bg_dbs)
        sysm = System(bg, Foreground(fg_dbs, bg, alias))
        sysm.substituted, sysm.pulled = len(alias), pulled
        if pulled:
            sysm.pulled_ids = {i for (i,) in AD.select(AD.id).where(AD.database << pulled).tuples()}
        return _keep(skey, sysm)


def alone(database: str) -> System:
    """One background database on its own, without the models: for a dataset of a database the calculation does not
    use and has no counterpart for (an input-output table, a scenario not chosen). Nothing else is factorized."""
    with _lock:
        project = bd.projects.current
        bgv, _fgv = versions(project)
        skey = (project, bgv, "alone", database)
        if skey in _systems:
            _systems.move_to_end(skey)
            return _systems[skey]
        bg = _background(project, bgv, [database])
        return _keep(skey, System(bg, Foreground([], bg)))


def _background(project: str, bgv: int, dbs: list[str]) -> Background:
    bkey = (project, bgv, tuple(dbs))
    if bkey not in _backgrounds:
        _backgrounds[bkey] = Background(list(dbs))
        while len(_backgrounds) > 3:
            _backgrounds.popitem(last=False)
    _backgrounds.move_to_end(bkey)
    return _backgrounds[bkey]


def _keep(skey: tuple, sysm: System) -> System:
    _systems[skey] = sysm
    while len(_systems) > 6:
        _systems.popitem(last=False)
    return sysm
