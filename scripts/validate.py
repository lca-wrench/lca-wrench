"""Validation anyone can rerun: LCA Wrench against plain bw2calc and against an independent solver.

    python scripts/validate.py                 # on the free BAFU 2025 data (project bafu-2025 from setup_daten.py)

Three calculations of the same numbers:

1. LCA Wrench, through its HTTP API: a real server is started and asked the way the browser asks it.
2. Plain bw2calc (`bw2calc.LCA`) on the same project.
3. An independent solver in this file: it reads the nodes and exchange rows straight from the project's SQLite
   file, builds the technosphere matrix A and the biosphere matrix B itself and solves with scipy. It shares no code
   with LCA Wrench's engine and does not use Brightway's processed matrices. Brightway stores those as float32;
   the solver runs once with the amounts as stored in SQLite (float64) and once rounded to float32, which shows
   where the remaining gap to bw2calc and LCA Wrench comes from.

The completed factors (lca_wrench/completion.py) are checked the same way: the rule is implemented a second time
here, from the SQLite rows, and LCA Wrench with the completion switched on is compared with the independent solver
using those factors.

Nothing is written to the project you name: the script works in a copy (`lca-wrench-validation`), which it deletes
at the end, and with its own registry file. Prints a Markdown report (docs/validation.md is written from it).
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import platform
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
COPY = "lca-wrench-validation"
FAMILY = "Ecological Scarcity 2021"
CLIMATE = ("Werkbank", "Klimawandel", "kg CO2-eq, abgeleitet aus UBP 2021")
UBP_TOTAL = ("Werkbank", "Umweltbelastungspunkte gesamt", "UBP 2021")
BIOSPHERE_TYPES = {"emission", "natural resource", "economic", "inventory indicator", "social"}
# (name, location, amount): products of the BAFU 2025 data
PRODUCTS = [
    ("Electricity, low voltage, at grid", "CH", 1.0),
    ("Aluminium, production mix, at plant", "RER", 3.7),
    ("Transport, freight, lorry, diesel, 26t gross weight, 2006, EURO-IV, long haul", "CH", 250.0),
    ("Heat, natural gas, at boiler condensing modulating 300kW", "CH", 100.0),
]


# ---------- the independent solver: SQLite rows -> A, B -> scipy ----------

class Independent:
    def __init__(self, sqlite_file: Path, single: bool):
        """`single`: round every amount to float32 first, as Brightway's processed matrices hold them."""
        con = sqlite3.connect(f"file:{sqlite_file}?mode=ro", uri=True)
        self.info = {}  # node id -> (name, categories, unit)
        key_id, bio, tech = {}, [], []
        for nid, db, code, typ, data in con.execute("select id, database, code, type, data from activitydataset"):
            d = pickle.loads(bytes(data))
            key_id[(db, code)] = nid
            self.info[nid] = (d.get("name") or "", tuple(d.get("categories") or ()), d.get("unit") or "")
            (bio if typ in BIOSPHERE_TYPES else tech).append(nid)
        self.tech, self.bio = sorted(tech), sorted(bio)
        col = {n: i for i, n in enumerate(self.tech)}
        row = {n: i for i, n in enumerate(self.bio)}
        cast = (lambda v: float(np.float32(v))) if single else float
        a_i, a_j, a_v, b_i, b_j, b_v, produced = [], [], [], [], [], [], set()
        for idb, icode, odb, ocode, typ, data in con.execute(
                "select input_database, input_code, output_database, output_code, type, data from exchangedataset"):
            amount = cast(pickle.loads(bytes(data))["amount"])
            i, j = key_id[(idb, icode)], key_id[(odb, ocode)]
            if typ == "biosphere":
                b_i.append(row[i]); b_j.append(col[j]); b_v.append(amount)  # noqa: E702
            else:
                sign = -1.0 if typ == "technosphere" else 1.0  # production and substitution count positive
                a_i.append(col[i]); a_j.append(col[j]); a_v.append(sign * amount)  # noqa: E702
                if typ == "production":
                    produced.add(j)
        for n in self.tech:  # an activity without a production exchange makes 1 of itself
            if n not in produced:
                a_i.append(col[n]); a_j.append(col[n]); a_v.append(1.0)  # noqa: E702
        con.close()
        n, m = len(self.tech), len(self.bio)
        self.A = sparse.coo_matrix((a_v, (a_i, a_j)), shape=(n, n)).tocsc()
        self.B = sparse.coo_matrix((b_v, (b_i, b_j)), shape=(m, n)).tocsr()
        self.lu = splu(self.A)
        self.col, self.row, self.single = col, row, single

    def inventory(self, node: int, amount: float) -> np.ndarray:
        b = np.zeros(len(self.tech))
        b[self.col[node]] = amount
        x = self.lu.solve(b)
        for _ in range(3):  # iterative refinement: the matrix is ill-conditioned
            x = x + self.lu.solve(b - self.A @ x)
        self.residual = float(np.linalg.norm(b - self.A @ x) / np.linalg.norm(b))
        return self.B @ x

    def cvec(self, factors: dict[int, float]) -> np.ndarray:
        c = np.zeros(len(self.bio))
        for flow, f in factors.items():
            if flow in self.row:
                c[self.row[flow]] += float(np.float32(f)) if self.single else f
        return c

    def completed(self, factors: dict[int, float]) -> dict[int, float]:
        """The completion rule, written a second time: a flow with a sub-compartment and no factor takes the factor
        of the flow with the same name, top-level compartment and unit without sub-compartment; not for long-term."""
        source = {}
        for flow, f in factors.items():
            name, cats, unit = self.info[flow]
            if len(cats) == 1 and f != 0:
                source[(name, cats[0], unit)] = f
        out = dict(factors)
        for flow in self.bio:
            name, cats, unit = self.info[flow]
            if len(cats) > 1 and flow not in factors and not any("long-term" in c for c in cats[1:]):
                f = source.get((name, cats[0], unit))
                if f is not None:
                    out[flow] = f
        return out


# ---------- LCA Wrench over HTTP ----------

class App:
    def __init__(self, project: str, registry: Path):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        env = {**os.environ, "LCA_WRENCH_PROJECT": project, "LCA_WRENCH_REGISTRY": str(registry),
               "PYTHONWARNINGS": "ignore"}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "lca_wrench.api:app", "--host", "127.0.0.1", "--port", str(self.port),
             "--log-level", "warning"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(240):
            try:
                self.get("/api/state")
                return
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError("the LCA Wrench server did not start") from None
                time.sleep(0.5)
        raise RuntimeError("the LCA Wrench server did not answer")

    def get(self, path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=600) as r:
            return json.loads(r.read())

    def post(self, path: str, body: dict):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "X-LCA-Wrench": "1"})  # the UI header (api.local_only)
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())

    def stop(self):
        self.proc.terminate()
        self.proc.wait(timeout=30)


def rel(a: float, b: float) -> float:
    """Relative gap; 0 when both are exactly 0."""
    return 0.0 if a == b else abs(a - b) / max(abs(a), abs(b))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default="bafu-2025", help="Brightway project with the BAFU 2025 data (only read)")
    ap.add_argument("--output", help="write the Markdown report to this file instead of printing it")
    args = ap.parse_args()

    import bw2calc as bc
    import bw2data as bd

    if args.project not in bd.projects:
        sys.exit(f"Project {args.project} is missing: run setup_daten.py first.")
    if COPY in bd.projects:
        bd.projects.delete_project(COPY, delete_dir=True)
    bd.projects.set_current(args.project)
    bd.projects.copy_project(COPY, switch=True)
    tmp = Path(tempfile.mkdtemp(prefix="lca-wrench-validation-"))
    app = None
    rows = []  # (case, compared with, values, largest gap)

    def note(case, what, gaps):
        gaps = list(gaps)
        rows.append((case, what, len(gaps), max(gaps) if gaps else 0.0))

    try:
        for name in [n for n in bd.databases if n not in ("BAFU-2025-v2", "BAFU-2025-biosphere")]:
            del bd.databases[name]  # models of the source project are not part of the comparison
        family = sorted(m for m in bd.methods if m[0] == FAMILY)
        methods = [CLIMATE, UBP_TOTAL, *family]
        db = bd.Database("BAFU-2025-v2")
        nodes = []
        for pname, loc, amount in PRODUCTS:
            nodes.append((next(a for a in db if a["name"] == pname and a.get("location") == loc), amount))
        factors = {m: {int(k): float(v) for k, v in bd.Method(m).load()} for m in methods}
        sqlite_file = Path(bd.projects.dir) / "lci" / "databases.db"

        app = App(COPY, tmp / "registry.json")
        ind64, ind32 = Independent(sqlite_file, single=False), Independent(sqlite_file, single=True)

        # --- 1. scores of 4 products x 23 methods, with the methods as stored (completion off)
        app.post("/api/completion", {"enabled": False})
        g_bw, g_64, g_32, g_bw32, sums, residual = [], [], [], [], [], 0.0
        plain = {}
        for node, amount in nodes:
            lca = bc.LCA({node: amount}, methods[0])
            lca.lci()
            inv64, inv32 = ind64.inventory(node.id, amount), ind32.inventory(node.id, amount)
            residual = max(residual, ind64.residual, ind32.residual)
            for m in methods:
                lca.switch_method(m)
                lca.lcia()
                r = app.post("/api/calc", {"id": str(node.id), "amount": amount, "method": list(m)})
                plain[(node.id, m)] = r["score"]
                s64, s32 = float(ind64.cvec(factors[m]) @ inv64), float(ind32.cvec(factors[m]) @ inv32)
                g_bw.append(rel(r["score"], lca.score))
                g_64.append(rel(r["score"], s64))
                g_32.append(rel(r["score"], s32))
                g_bw32.append(rel(lca.score, s32))
                if r["score"]:
                    by_act = sum(x["value"] for x in r["by_activity"]) + r["by_activity_rest"]
                    by_flow = sum(x["value"] for x in r["by_flow"]) + r["by_flow_rest"]
                    sums += [rel(by_act, r["score"]), rel(by_flow, r["score"])]
        case = f"Scores: {len(nodes)} products × {len(methods)} methods, methods as stored"
        note(case, "LCA Wrench (HTTP) vs bw2calc", g_bw)
        note(case, "LCA Wrench vs independent solver, amounts rounded to float32", g_32)
        note(case, "bw2calc vs independent solver, amounts rounded to float32", g_bw32)
        note(case, "LCA Wrench vs independent solver, amounts as in SQLite (float64)", g_64)
        note("Contributions by activity and by flow add up to the score", "sum of the parts vs score", sums)

        # --- 2. the whole inventory of one product
        node, amount = nodes[2]
        lca = bc.LCA({node: amount}, methods[0])
        lca.lci()
        bw_inv = dict(zip((f for f, _ in sorted(lca.dicts.biosphere.items(), key=lambda kv: kv[1])),
                          np.asarray(lca.inventory.sum(axis=1)).ravel()))
        ours = {int(r["id"]): r["amount"] for r in app.post("/api/inventory", {"id": str(node.id), "amount": amount})}
        inv32 = ind32.inventory(node.id, amount)
        own = {f: inv32[i] for f, i in ind32.row.items() if inv32[i] != 0}
        top = max(abs(v) for v in ours.values())
        big = [f for f, v in ours.items() if abs(v) > 1e-12 * top]  # flows that are not rounding noise
        case = f"Inventory of {amount:g} tkm lorry transport: {len(ours)} flows"
        note(case, "LCA Wrench vs bw2calc", (rel(ours[f], float(bw_inv.get(f, 0.0))) for f in big))
        note(case, "LCA Wrench vs independent solver (float32)", (rel(ours[f], float(own.get(f, 0.0))) for f in big))

        # --- 3. a calculation setup, and the app's own cross-check
        setup_methods = [CLIMATE, UBP_TOTAL, (FAMILY, "Main air pollutants and PM"), (FAMILY, "Energy resources")]
        fus = [{"id": str(n.id), "amount": a} for n, a in nodes]
        table = app.post("/api/results", {"fus": fus, "methods": [list(m) for m in setup_methods]})["scores"]
        gaps = []
        for j, (n, a) in enumerate(nodes):
            lca = bc.LCA({n: a}, setup_methods[0])
            lca.lci()
            for k, m in enumerate(setup_methods):
                lca.switch_method(m)
                lca.lcia()
                gaps.append(rel(table[k][j], lca.score))
        note(f"Calculation setup, {len(nodes)} products × {len(setup_methods)} methods", "every cell vs bw2calc", gaps)
        v = app.post("/api/verify", {"fus": fus, "methods": [list(m) for m in setup_methods]})
        rows.append(("The app's own cross-check on that setup (relative to the gross impact)",
                     "ok" if v["ok"] else "NOT OK", v["checked"], v["max_rel"]))

        # --- 4. an own model on top of the background (the e-bike example the app creates)
        ex = app.post("/api/beispiel", {})
        st = ex["state"]
        model_db = next(d["name"] for d in st["databases"] if d.get("role") == "model")
        bd.projects.set_current(COPY)  # read what the server wrote
        bd.databases.__init__()
        bd.Database(model_db).process()
        top_model = max(bd.Database(model_db), key=lambda a: len(list(a.technosphere())))
        ind_m = Independent(sqlite_file, single=True)
        inv = ind_m.inventory(top_model.id, 1.0)
        gaps_bw, gaps_own = [], []
        for m in (CLIMATE, UBP_TOTAL):
            r = app.post("/api/calc", {"id": str(top_model.id), "amount": 1.0, "method": list(m)})
            lca = bc.LCA({top_model: 1.0}, m)
            lca.lci()
            lca.lcia()
            gaps_bw.append(rel(r["score"], lca.score))
            gaps_own.append(rel(r["score"], float(ind_m.cvec(factors[m]) @ inv)))
        case = f"Own model on the background (“{top_model['name']}”, {len(bd.Database(model_db))} activities)"
        note(case, "LCA Wrench vs bw2calc", gaps_bw)
        note(case, "LCA Wrench vs independent solver (float32)", gaps_own)

        # --- 5. completed factors: LCA Wrench with the completion on vs the rule written a second time
        app.post("/api/completion", {"enabled": True})
        gaps, completed = [], {}
        for node, amount in nodes:
            inv32 = ind32.inventory(node.id, amount)
            for m in [CLIMATE, *family]:
                r = app.post("/api/calc", {"id": str(node.id), "amount": amount, "method": list(m)})
                completed[(node.id, m)] = r["score"]
                gaps.append(rel(r["score"], float(ind32.cvec(ind32.completed(factors[m])) @ inv32)))
            total = app.post("/api/calc", {"id": str(node.id), "amount": amount, "method": list(UBP_TOTAL)})["score"]
            completed[(node.id, UBP_TOTAL)] = total
            gaps.append(rel(total, sum(completed[(node.id, m)] for m in family)))
        note(f"Completed factors: {len(nodes)} products × {len(family) + 1} methods, and UBP total = sum of the categories",
             "LCA Wrench vs independent solver with its own completion (float32)", gaps)
        n_added = {m: len(set(ind32.completed(factors[m])) - set(factors[m])) for m in [CLIMATE, *family]}

        # ---------- report ----------
        if args.output:
            sys.stdout = open(args.output, "w", encoding="utf-8")
        print("## Environment\n")
        print(f"- {time.strftime('%Y-%m-%d')}, {platform.system()} {platform.machine()}, Python {platform.python_version()}")
        import scipy

        import lca_wrench

        print(f"- LCA Wrench {lca_wrench.__version__}, bw2data {bd.__version__}, bw2calc {bc.__version__}, "
              f"numpy {np.__version__}, scipy {scipy.__version__}")
        print(f"- Data: {len(ind64.tech):,} activities, {len(ind64.bio):,} elementary flows, {ind64.A.nnz:,} entries in A, "
              f"{ind64.B.nnz:,} in B (BAFU-2025-v2 from files.brightway.dev)")
        print(f"- Independent solver: largest relative residual |b − A x| / |b| after refinement {residual:.1e}\n")
        print("## Results\n")
        print("| Case | Compared | Values | Largest relative gap |")
        print("|---|---|---:|---:|")
        for case, what, n, gap in rows:
            print(f"| {case} | {what} | {n} | {gap:.1e} |")
        print("\n## Completed factors: the figures\n")
        print("| Product | Method | As stored | With completed factors | Unit |")
        print("|---|---|---:|---:|---|")
        for (node, amount), (pname, loc, _a) in zip(nodes, PRODUCTS):
            for m, unit, label in ((CLIMATE, "kg CO2-eq", "Climate change (derived from UBP 2021)"), (UBP_TOTAL, "UBP", "UBP total")):
                print(f"| {amount:g} {node['unit']} {pname}, {loc} | {label} | {plain[(node.id, m)]:.6g} | "
                      f"{completed[(node.id, m)]:.6g} | {unit} |")
        print("\nFactors added per method (by the independent implementation; LCA Wrench reports the same counts):\n")
        print("| Method | Stored factors | Added |")
        print("|---|---:|---:|")
        for m in [CLIMATE, *family]:
            got = app.post("/api/completion/factors", {"method": list(m)})
            assert len(got["rows"]) == n_added[m], (m, len(got["rows"]), n_added[m])
            print(f"| {' / '.join(m[:2])} | {len(factors[m])} | {n_added[m]} |")
        return 0
    finally:
        if app:
            app.stop()
        try:
            bd.projects.set_current(args.project)
            bd.projects.delete_project(COPY, delete_dir=True)
        except Exception as e:  # noqa: BLE001
            print(f"Could not delete the project copy {COPY}: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
