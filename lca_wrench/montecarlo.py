"""Monte-Carlo uncertainty: coupled draws for all products and methods of a calculation.

Per iteration one sample of the technosphere and biosphere matrices is drawn
(bw2calc/matrix_utils, `use_distributions=True`) and used for every product
of the calculation. Differences between products are therefore real
differences, not sampling noise: "A is better than B in x % of the draws".
Every method gets its own characterization sample (usually the factors have
no uncertainty, then all draws are identical).

The work is split over worker processes (one chunk of iterations each, own
seed = seed + worker index). The same seed with the same number of workers
reproduces the result exactly. The reference test (tests/test_montecarlo.py)
compares a single worker against a plain bw2calc loop with the same seeds
(`mc_lca`: one independent seed per resource group, derived from the run seed).
"""

from __future__ import annotations

import contextvars
import multiprocessing as mp
import os
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor

import bw2calc as bc
import bw2data as bd
import numpy as np
from scipy.sparse.linalg import spsolve, splu

from . import functional  # noqa: F401  (worker processes open Activity Browser 3 databases too)
from .i18n import _, msg, render

MAX_ITERATIONS = 10000


def _factorize(A):
    """Fast LU for the sampled matrix, with a residual-checked fallback to the default solver."""
    A = A.tocsc()
    try:
        lu = splu(A, permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0, options={"SymmetricMode": True})
    except RuntimeError:
        lu = None

    def solve(b, trans="N"):
        """A x = b, or A^T x = b with trans="T" (same factorization)."""
        M = A if trans == "N" else A.T
        if lu is not None:
            x = lu.solve(b, trans=trans)
            r = b - M @ x
            if np.linalg.norm(r) <= 1e-9 * max(np.linalg.norm(b), 1e-300):
                x = x + lu.solve(r, trans=trans)  # one refinement step
                return x
        return np.asarray(spsolve(M.tocsr(), b)).ravel()

    return solve


def _reseed(lca, seed: int, labels=("technosphere_mm", "biosphere_mm", "characterization_mm")) -> None:
    """Give every resource group its own reproducible RNG seed and redraw the matrices.

    `seed_override` alone hands the same seed to every group, so the k-th uncertain value of every datapackage
    (two alternatives in separate databases, A and B, the factors) got the same variate: perfectly correlated.
    Values shared by several products (the background) stay common to all of them, as they sit once in the matrix.
    """
    from stats_arrays import MCRandomNumberGenerator

    for m, label in enumerate(labels):
        mm = getattr(lca, label, None)
        if mm is None:
            continue
        for g, group in enumerate(mm.groups):
            if isinstance(getattr(group, "rng", None), MCRandomNumberGenerator):
                sub = int(np.random.SeedSequence([seed, m, g]).generate_state(1)[0])
                group.rng = MCRandomNumberGenerator(params=group.data_original, seed=sub)
        mm.rebuild_matrix()
    lca.technosphere_matrix = lca.technosphere_mm.matrix
    lca.biosphere_matrix = lca.biosphere_mm.matrix
    if hasattr(lca, "characterization_mm"):
        lca.characterization_matrix = lca.characterization_mm.matrix


def mc_lca(demand: dict, method: tuple, seed: int):
    """bw2calc LCA with distributions, independent seeds per resource group (see _reseed), first draw solved."""
    lca = bc.LCA(demand, tuple(method), use_distributions=True, seed_override=seed)
    lca.lci()
    lca.lcia()
    _reseed(lca, seed)
    lca._delete_solver_state()
    lca.lci_calculation()
    lca.lcia_calculation()
    return lca


def run_chunk(project: str, fus: list[tuple[int, float]], methods: list[tuple], n: int, seed: int,
              progress=None, slot: int = 0) -> np.ndarray:
    """n coupled iterations for all fus and methods. Returns an array (n, len(fus), len(methods))."""
    bd.projects.set_current(project)
    nodes = {nid: bd.get_node(id=nid) for nid, _ in fus}
    lca = mc_lca({node: 1 for node in nodes.values()}, methods[0], seed)
    cms = [lca.characterization_mm]
    for k, m in enumerate(methods[1:], start=1):
        lca.switch_method(tuple(m))
        _reseed(lca, seed + 100_003 * k, ("characterization_mm",))
        cms.append(lca.characterization_mm)
    demands = []
    for nid, amount in fus:
        lca.build_demand_array({nid: amount})
        demands.append(lca.demand_array.copy())
    adds = _mapped(methods, lca)
    regs = _regional(methods, lca, adds)
    out = np.empty((n, len(fus), len(methods)))
    for i in range(n):
        if i:
            lca._delete_solver_state()
            next(lca.technosphere_mm)
            next(lca.biosphere_mm)
            lca.technosphere_matrix = lca.technosphere_mm.matrix
            lca.biosphere_matrix = lca.biosphere_mm.matrix
            for cm in cms:
                next(cm)
        solve = _factorize(lca.technosphere_matrix)
        B = lca.biosphere_matrix
        # factors by location (regional.py) on this draw's B: fixed factors, the sampled normal factor elsewhere
        BV = [(np.asarray(B.multiply(r[0]).sum(axis=0)).ravel(), B.multiply(r[1]).tocsr()) if r else None for r in regs]
        for j, f in enumerate(demands):
            x = solve(f)
            g = np.asarray(B @ x).ravel()
            for k, cm in enumerate(cms):
                c = cm.matrix.diagonal() + adds[k]
                out[i, j, k] = float(c @ g)
                if BV[k] is not None:
                    out[i, j, k] += float(BV[k][0] @ x) - float(c @ (BV[k][1] @ x))
        if progress is not None:
            progress[slot] = i + 1
    return out


def _mapped(methods: list[tuple], lca) -> list:
    """Per method the factors it gets through the flow mapping (flowmap.py), over lca's biosphere rows; fixed, no
    uncertainty. 0 where none, so adding them keeps the method's own sampled factors."""
    from . import engine

    ids = _ids(lca.dicts.biosphere)
    return [a if (a := engine.extra_vector(tuple(m), ids)) is not None else 0.0 for m in methods]


def _regional(methods: list[tuple], lca, adds) -> list:
    """Per method (V, M) of regional.sampled_parts over lca's matrices, or None without factors by location. The
    factors by location have no uncertainty; for a region's countries without one the normal factor is taken as
    calculated (mean values), as in the engine."""
    from . import engine, regional

    out, places = [], None
    bio_ids, act_ids = _ids(lca.dicts.biosphere), _ids(lca.dicts.activity)
    for k, m in enumerate(methods):
        T = regional.active(tuple(m))
        if T is None:
            out.append(None)
            continue
        places = places or regional.places_for(act_ids)
        cf = engine.method_cfs(tuple(m))  # the stored values, not this draw's
        c = np.fromiter((cf.get(int(f), 0.0) for f in bio_ids), dtype=float, count=len(bio_ids)) + adds[k]
        out.append(regional.sampled_parts(T, bio_ids, places, lca.biosphere_matrix, c))
    return out


_progress = None


def _init_worker(shared):
    global _progress
    _progress = shared
    _exit_when_orphaned()


def _exit_when_orphaned() -> None:
    """A worker whose server process is gone (killed, crashed) ends itself instead of idling forever."""
    parent = os.getppid()

    def watch():
        while True:
            time.sleep(5)
            if os.getppid() != parent:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def _worker(args):
    project, fus, methods, n, seed, slot = args
    import warnings
    warnings.filterwarnings("ignore")
    return run_chunk(project, fus, methods, n, seed, _progress, slot)


def split(n: int, workers: int) -> list[int]:
    workers = max(1, min(workers, n))
    base, extra = divmod(n, workers)
    return [base + (1 if i < extra else 0) for i in range(workers)]


def simulate(project: str, fus: list[tuple[int, float]], methods: list[tuple], n: int, seed: int,
             workers: int, progress=None) -> np.ndarray:
    """Run all chunks in worker processes; `progress` is a shared integer array (one slot per worker).

    Always in worker processes, also for a single chunk: run_chunk switches the Brightway project, which in a
    thread of the server would disturb the requests running at the same time."""
    sizes = split(n, workers)
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=len(sizes), mp_context=ctx, initializer=_init_worker, initargs=(progress,)) as ex:
        parts = list(ex.map(_worker, [(project, fus, methods, size, seed + w, w) for w, size in enumerate(sizes)]))
    return np.concatenate(parts)


# ---------- statistics ----------

def summarize(draws: np.ndarray) -> dict:
    """Location and spread per method and product, laid out [method][product] like the score table."""
    q = np.percentile(draws, [5, 25, 50, 75, 95], axis=0)
    std = draws.std(axis=0, ddof=1) if len(draws) > 1 else np.zeros(draws.shape[1:])
    t = lambda a: np.asarray(a).T.tolist()  # noqa: E731
    return {
        "mean": t(draws.mean(axis=0)), "std": t(std), "min": t(draws.min(axis=0)), "max": t(draws.max(axis=0)),
        "p5": t(q[0]), "p25": t(q[1]), "median": t(q[2]), "p75": t(q[3]), "p95": t(q[4]),
    }


def better_matrix(draws: np.ndarray) -> list:
    """Per method: share of draws where product i has a lower score than product j (lower impact = better).

    Ties count half. Result[k][i][j]; the diagonal is None."""
    n, nf, nm = draws.shape
    out = []
    for k in range(nm):
        m = []
        for i in range(nf):
            row = []
            for j in range(nf):
                if i == j:
                    row.append(None)
                else:
                    d = draws[:, j, k] - draws[:, i, k]
                    row.append(float(((d > 0).sum() + 0.5 * (d == 0).sum()) / n))
            m.append(row)
        out.append(m)
    return out


# ---------- background jobs ----------

class Job:
    def __init__(self, project, fus, methods, n, seed, workers):
        self.id = uuid.uuid4().hex[:12]
        self.project, self.fus, self.methods = project, fus, methods
        self.n, self.seed, self.workers = n, seed, workers
        self.state = "läuft"
        self.error = None
        self.result = None
        self.started = time.time()
        self.seconds = None
        self.progress = mp.get_context("spawn").Array("i", [0] * len(split(n, workers)), lock=False)

    def done_count(self) -> int:
        return int(sum(self.progress))

    phase = ""

    def status(self) -> dict:
        d = {"id": self.id, "state": self.state, "done": self.done_count(), "n": self.n, "error": self.error,
             "phase": render(self.phase) if self.phase else "",
             "seconds": self.seconds if self.seconds is not None else time.time() - self.started}
        if self.state == "fertig":
            d["result"] = self.result
        return d


JOBS: dict[str, Job] = {}


def default_workers() -> int:
    return max(1, min((os.cpu_count() or 2) - 2, 8))


def start(project: str, fus: list[tuple[int, float]], methods: list[tuple], n: int, seed: int,
          workers: int | None, describe) -> Job:
    """Start a job in a thread. `describe(draws)` builds the JSON result (labels, deterministic reference)."""
    if not 1 <= n <= MAX_ITERATIONS:
        raise ValueError(_("Die Anzahl Ziehungen muss zwischen {lo} und {hi} liegen.", lo=1, hi=MAX_ITERATIONS))
    for old in [j for j in JOBS.values() if j.state != "läuft" and time.time() - j.started > 3600]:
        JOBS.pop(old.id, None)
    job = Job(project, fus, methods, n, seed, workers or default_workers())

    def run():
        try:
            draws = simulate(project, fus, methods, n, seed, job.workers, job.progress)
            job.result = {**describe(draws), "n": n, "seed": seed, "workers": len(job.progress),
                          "draws": draws.transpose(2, 1, 0).tolist() if n <= 2000 else None}  # [method][product][draw]
            job.state = "fertig"
        except Exception as e:  # shown to the user, not swallowed
            job.error, job.state = str(e) or e.__class__.__name__, "fehler"
        finally:
            job.seconds = time.time() - job.started

    JOBS[job.id] = job
    threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True).start()  # keeps the language
    return job


# ---------- sensitivity: which uncertain inputs drive the spread ----------
#
# Two steps. (1) A short pilot run measures how much every matrix entry varies and, with the sensitivities
# dh/dA_ij = -s_i x_j and dh/dB_kj = c_k x_j (s = unit scores, x = supply), ranks entries by
# |dh/da * a * relative sd|. (2) The real run records the sampled values of the best K entries next to the
# score of every draw; the Spearman rank correlation per entry is the result.
#
# Three measures come out of it:
# - rank correlation (Spearman) of each tracked entry with the score;
# - CTV, the contribution to variance of the first-order Taylor expansion: (dh/da)^2 var(a) of each entry over
#   the sum for all entries (exact derivatives from step 1, all 100,000+ entries, no extra runs). The sum over the
#   variance of the draws says how much of the spread a linear model explains;
# - Sobol indices for the top SOBOL entries, by pick-freeze (Saltelli 2010, Jansen): the draws come in pairs
#   (a, b); the score with all values from a except entry i from b is exact by a rank-one update of the
#   factorization of a (Sherman-Morrison), so it needs one extra solve per entry, no new factorization.
#   S1 = variance from the entry alone, ST = including all interactions with other entries.

PILOT = 40
CANDIDATES = 250
SOBOL = 20
BOOTSTRAP = 200


def _matrices(lca):
    return lca.technosphere_mm.matrix.tocsr(), lca.biosphere_mm.matrix.tocsr()


def _sens_pilot_chunk(project, fu, method, n, seed):
    """n pilot draws: running mean and spread of every data value of A and B; chunk 0 also the sensitivities."""
    bd.projects.set_current(project)
    nid, amount = fu
    lca = mc_lca({nid: amount}, method, seed)
    A, B = _matrices(lca)
    stats = {"n": 0, "mA": np.zeros(A.nnz), "m2A": np.zeros(A.nnz), "mB": np.zeros(B.nnz), "m2B": np.zeros(B.nnz)}
    meta = None
    for i in range(n):
        if i:
            lca._delete_solver_state()
            next(lca.technosphere_mm)
            next(lca.biosphere_mm)
            A, B = _matrices(lca)
        stats["n"] += 1
        for key, M in (("A", A), ("B", B)):
            d = M.data - stats["m" + key]
            stats["m" + key] += d / stats["n"]
            stats["m2" + key] += d * (M.data - stats["m" + key])
        if i == 0:
            solve = _factorize(A)
            x = solve(lca.demand_array)
            c = lca.characterization_mm.matrix.diagonal() + _mapped([method], lca)[0]
            s = np.asarray(_factorize(A.T.tocsr())(np.asarray(B.T @ c).ravel())).ravel()
            Ac, Bc = A.tocoo(), B.tocoo()
            meta = {"Arow": Ac.row, "Acol": Ac.col, "Brow": Bc.row, "Bcol": Bc.col, "x": x, "s": s, "c": c,
                    "prod_ids": _ids(lca.dicts.product), "act_ids": _ids(lca.dicts.activity),
                    "bio_ids": _ids(lca.dicts.biosphere)}
    return stats, meta


def _ids(mapping):
    items = sorted(dict(mapping).items(), key=lambda kv: kv[1])
    return np.array([k for k, _ in items], dtype=np.int64)


def _merge(parts):
    """Combine running mean/M2 of several chunks (Chan et al.)."""
    out = {}
    for key in ("A", "B"):
        n, mean, m2 = 0, None, None
        for p in parts:
            if mean is None:
                n, mean, m2 = p["n"], p["m" + key].copy(), p["m2" + key].copy()
                continue
            d = p["m" + key] - mean
            tn = n + p["n"]
            m2 = m2 + p["m2" + key] + d * d * n * p["n"] / tn
            mean = mean + d * p["n"] / tn
            n = tn
        out[key] = (mean, np.sqrt(m2 / max(n - 1, 1)))
    return out


def importance(meta, merged):
    """|dh/da| * sd(a) for every entry of A and B: the first-order (Taylor) standard deviation it adds."""
    mA, sA = merged["A"]
    mB, sB = merged["B"]
    # dh/dA_ij = -s_i x_j, dh/dB_kj = c_k x_j
    impA = np.abs(meta["s"][meta["Arow"]] * meta["x"][meta["Acol"]]) * sA
    impB = np.abs(meta["c"][meta["Brow"]] * meta["x"][meta["Bcol"]]) * sB
    return np.nan_to_num(impA), np.nan_to_num(impB)


def rank_candidates(meta, merged, k: int = CANDIDATES):
    """Entries ranked by the first-order contribution to the spread. Returns [(matrix, index, score)]."""
    cands = []
    impA, impB = importance(meta, merged)
    imp = np.concatenate([impA, impB])
    order = np.argsort(-imp)[:k]
    for o in order:
        if imp[o] <= 0:
            break
        cands.append(("A", int(o), float(imp[o])) if o < len(impA) else ("B", int(o - len(impA)), float(imp[o])))
    return cands


def _sens_main_chunk(project, fu, method, n, seed, a_idx, b_idx, sobol=()):
    """n draws: score of the product and the sampled values of the tracked entries.

    The draws are also taken as pairs (draw 2p = sample a, 2p+1 = sample b). For every entry in `sobol`
    (("A"|"B", index into the matrix data)) the score with all values from a but this entry from b is returned
    too, as an array (pairs, len(sobol))."""
    bd.projects.set_current(project)
    nid, amount = fu
    lca = mc_lca({nid: amount}, method, seed)
    scores = np.empty(n)
    xa, xb = np.empty((n, len(a_idx))), np.empty((n, len(b_idx)))
    fab = np.empty((n // 2, len(sobol)))
    cm = lca.characterization_mm
    add = _mapped([method], lca)[0]
    keep = None
    for i in range(n):
        if i:
            lca._delete_solver_state()
            next(lca.technosphere_mm)
            next(lca.biosphere_mm)
            next(cm)
        A, B = _matrices(lca)
        solve = _factorize(A)
        c = cm.matrix.diagonal() + add
        x = solve(lca.demand_array)
        scores[i] = float(c @ np.asarray(B @ x).ravel())
        xa[i], xb[i] = A.data[a_idx], B.data[b_idx]
        if not len(sobol):
            continue
        if i % 2 == 0 and i + 1 < n:  # sample a: keep what the rank-one updates need
            Ac = A.tocoo()
            Bc = B.tocoo()
            s = solve(np.asarray(B.T @ c).ravel(), trans="T")
            u, vals = {}, []
            for kind, idx in sobol:
                if kind == "A":
                    r = int(Ac.row[idx])
                    if r not in u:
                        e = np.zeros(A.shape[0])
                        e[r] = 1.0
                        u[r] = solve(e)
                    vals.append((A.data[idx], r, int(Ac.col[idx])))
                else:
                    vals.append((B.data[idx], int(Bc.row[idx]), int(Bc.col[idx])))
            keep = (scores[i], s, x, c, u, vals)
        elif i % 2 == 1:  # sample b: the score of a with one entry from b
            h, s, xk, ck, u, vals = keep
            for k, ((kind, idx), (va, r, col)) in enumerate(zip(sobol, vals)):
                d = (A.data[idx] if kind == "A" else B.data[idx]) - va
                if kind == "A":  # Sherman-Morrison: h' = h - d s_r x_c / (1 + d (A^-1)_cr)
                    fab[i // 2, k] = h - d * s[r] * xk[col] / (1.0 + d * u[r][col])
                else:
                    fab[i // 2, k] = h + ck[r] * d * xk[col]
    return scores, xa, xb, fab


def sobol_indices(fa: np.ndarray, fb: np.ndarray, fab: np.ndarray, n_boot: int = BOOTSTRAP, seed: int = 0) -> dict:
    """First-order (Saltelli 2010, centred) and total (Jansen) Sobol indices with 95 % bootstrap intervals."""

    def est(ia):
        a, b, ab = fa[ia], fb[ia], fab[ia]
        both = np.concatenate([a, b])
        v = np.var(both, ddof=1)
        if v <= 0:
            return np.zeros(ab.shape[1]), np.zeros(ab.shape[1])
        # centred: same expectation, but stable when the mean is large against the spread (LCA scores)
        s1 = np.mean((b - both.mean())[:, None] * (ab - a[:, None]), axis=0) / v
        st = 0.5 * np.mean((a[:, None] - ab) ** 2, axis=0) / v
        return s1, st

    m = len(fa)
    s1, st = est(np.arange(m))
    rng = np.random.default_rng(seed)
    boot = [est(rng.integers(0, m, m)) for _ in range(n_boot)]
    b1, bt = np.array([b[0] for b in boot]), np.array([b[1] for b in boot])
    return {"s1": s1, "st": st, "s1_lo": np.percentile(b1, 2.5, axis=0), "s1_hi": np.percentile(b1, 97.5, axis=0),
            "st_lo": np.percentile(bt, 2.5, axis=0), "st_hi": np.percentile(bt, 97.5, axis=0)}


def _pool(workers, n_tasks):
    return ProcessPoolExecutor(max_workers=max(1, min(workers, n_tasks)), mp_context=mp.get_context("spawn"),
                               initializer=_init_worker, initargs=(None,))


def spearman(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Rank correlation of every column of x with y (ties get their mean rank)."""
    from scipy.stats import rankdata

    ry = rankdata(y)
    ry = ry - ry.mean()
    out = np.zeros(x.shape[1])
    for k in range(x.shape[1]):
        rx = rankdata(x[:, k])
        rx = rx - rx.mean()
        den = np.sqrt((rx @ rx) * (ry @ ry))
        out[k] = (rx @ ry) / den if den > 0 else 0.0
    return out


def sensitivity(project: str, fu: tuple[int, float], method: tuple, n: int, seed: int, workers: int,
                top: int = 10, progress_job=None) -> dict:
    """Ranks the uncertain inputs of one product/method by their rank correlation with the score."""
    sizes = split(PILOT, workers)
    with _pool(workers, len(sizes)) as ex:
        futs = [ex.submit(_sens_pilot_chunk, project, fu, method, size, seed + 7919 + w) for w, size in enumerate(sizes)]
        res = [f.result() for f in futs]
    meta = res[0][1]
    merged = _merge([r[0] for r in res])
    cands = rank_candidates(meta, merged)
    a_idx = np.array([i for m, i, _ in cands if m == "A"], dtype=int)
    b_idx = np.array([i for m, i, _ in cands if m == "B"], dtype=int)
    if not len(cands):
        raise ValueError(_("Für dieses Produkt gibt es keine Daten mit Unsicherheit."))
    sobol = [(m, i) for m, i, _ in cands[:SOBOL]]
    if progress_job is not None:
        progress_job.phase = msg("Schritt 2 von 2: {n} Ziehungen mit {k} verfolgten Datenwerten", n=n, k=len(cands))
    sizes = split(n, workers)
    with _pool(workers, len(sizes)) as ex:
        futs = [ex.submit(_sens_main_chunk, project, fu, method, size, seed + w, a_idx, b_idx, sobol)
                for w, size in enumerate(sizes)]
        parts = [f.result() for f in futs]
    scores = np.concatenate([p[0] for p in parts])
    xa = np.concatenate([p[1] for p in parts])
    xb = np.concatenate([p[2] for p in parts])
    # pairs of each chunk: a = even, b = odd draws of that chunk
    fa = np.concatenate([p[0][0:2 * len(p[3]):2] for p in parts])
    fb = np.concatenate([p[0][1:2 * len(p[3]):2] for p in parts])
    fab = np.concatenate([p[3] for p in parts])
    sob = sobol_indices(fa, fb, fab, seed=seed) if len(fa) >= 10 else None
    sob_at = {key: k for k, key in enumerate(sobol)}
    mA, sA = merged["A"]
    mB, sB = merged["B"]
    # the spread of the tracked entries from all draws, not only the pilot (heavy-tailed lognormals need many)
    if len(scores) > 2:
        sA, sB = sA.copy(), sB.copy()
        sA[a_idx], sB[b_idx] = xa.std(axis=0, ddof=1), xb.std(axis=0, ddof=1)
    impA, impB = importance(meta, {"A": (mA, sA), "B": (mB, sB)})
    lin_var = float((impA ** 2).sum() + (impB ** 2).sum())
    # inputs are stored as negative technosphere values; correlate the magnitude, so that "more input" is positive
    xa = xa * np.where(mA[a_idx] < 0, -1.0, 1.0)
    xb = xb * np.where(mB[b_idx] < 0, -1.0, 1.0)
    rho_a, rho_b = spearman(xa, scores), spearman(xb, scores)
    rows = []

    def extra(key, imp):
        r = {"ctv": float(imp ** 2 / lin_var) if lin_var > 0 else 0.0}
        k = sob_at.get(key)
        if sob is not None and k is not None:
            r["sobol"] = {f: float(sob[f][k]) for f in ("s1", "st", "s1_lo", "s1_hi", "st_lo", "st_hi")}
        return r

    for j, i in enumerate(a_idx):
        rows.append({"kind": "input", "supplier": int(meta["prod_ids"][meta["Arow"][i]]), "consumer": int(meta["act_ids"][meta["Acol"][i]]),
                     "rho": float(rho_a[j]), "value": float(abs(mA[i])), "rel_sd": float(sA[i] / abs(mA[i])),
                     **extra(("A", int(i)), impA[i])})
    for j, i in enumerate(b_idx):
        rows.append({"kind": "emission", "supplier": int(meta["bio_ids"][meta["Brow"][i]]), "consumer": int(meta["act_ids"][meta["Bcol"][i]]),
                     "rho": float(rho_b[j]), "value": float(abs(mB[i])), "rel_sd": float(sB[i] / abs(mB[i])),
                     **extra(("B", int(i)), impB[i])})
    rows.sort(key=lambda r: -abs(r["rho"]))
    # With n draws an unrelated entry still shows rho^2 of about 1/(n-1); that noise floor is subtracted
    floor = 1.0 / max(len(scores) - 1, 1)
    signal = [max(r["rho"] ** 2 - floor, 0.0) for r in rows]
    total = sum(signal) or 1.0
    for r, sg in zip(rows, signal):
        r["share"] = sg / total
        r["significant"] = bool(abs(r["rho"]) > 2.0 / np.sqrt(len(scores)))
    var = float(np.var(scores, ddof=1)) if len(scores) > 1 else 0.0
    by_st = sorted((r for r in rows if "sobol" in r), key=lambda r: -r["sobol"]["st"])
    # entries strong by Sobol but not by rank correlation (non-monotonic or interacting) are added after them
    shown = {id(r) for r in rows[:top]}
    extras = [r for r in by_st if id(r) not in shown and r["sobol"]["st_lo"] >= 0.05][:5]  # clearly above noise
    top_rows = rows[:top] + [{**r, "extra": True} for r in extras]
    return {"scores": scores, "entries": top_rows, "candidates": len(rows), "noise_floor": floor,
            "linear_share": lin_var / var if var > 0 else None,
            "ctv_top": float(sum(r["ctv"] for r in rows[:top])),
            "sobol": None if sob is None else {"pairs": len(fa), "k": len(sobol),
                                               "s1_sum": float(sob["s1"].sum()), "st_sum": float(sob["st"].sum())}}


def start_sensitivity(project: str, fu: tuple[int, float], method: tuple, n: int, seed: int, workers: int | None,
                       describe) -> Job:
    """Background job for `sensitivity`; `describe(result)` adds labels. Progress is shown per phase."""
    if not 20 <= n <= MAX_ITERATIONS:
        raise ValueError(_("Die Anzahl Ziehungen muss zwischen {lo} und {hi} liegen.", lo=20, hi=MAX_ITERATIONS))
    job = Job(project, [fu], [method], n, seed, workers or default_workers())
    job.kind = "sensitivity"

    def run():
        try:
            job.phase = msg("Schritt 1 von 2: Streuung der Daten messen und die wichtigsten Kandidaten auswählen")
            raw = sensitivity(project, fu, method, n, seed, job.workers, progress_job=job)
            job.result = describe(raw)
            job.state = "fertig"
        except Exception as e:
            job.error, job.state = str(e) or e.__class__.__name__, "fehler"
        finally:
            job.seconds = time.time() - job.started

    JOBS[job.id] = job
    threading.Thread(target=contextvars.copy_context().run, args=(run,), daemon=True).start()
    return job
