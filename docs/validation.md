# Validation

Every number LCA Wrench shows comes from its own engine (see [calculation.md](calculation.md)). Two things check it:

1. **`scripts/validate.py`**, which anyone can rerun on the free BAFU 2025 data. It starts the app, asks it through
   its HTTP API the way the browser does, and compares the answers with
   - plain **bw2calc** on the same project, and
   - an **independent solver** in the script itself: it reads the nodes and exchange rows straight from the project's
     SQLite file, builds the technosphere matrix A and the biosphere matrix B and solves with scipy (with iterative
     refinement). It shares no code with LCA Wrench's engine and does not use Brightway's processed matrices.
2. **The test suite** (`tests/`), which runs in CI on every change. It compares the engine with bw2calc on samples of
   activities and methods, own models, calculation setups, working copies and Monte Carlo runs with the same seed.

```bash
.venv/bin/python scripts/validate.py --output validation-report.md
```

The script works in a temporary copy of the project (`lca-wrench-validation`, deleted at the end) and never writes to
`bafu-2025`.

## Results

Output of `scripts/validate.py` as run for this release (relative gap = |a − b| / max(|a|, |b|)):

### Environment

- 2026-11-17, Darwin arm64, Python 3.12.11
- LCA Wrench 0.1.0, bw2data 4.7, bw2calc 2.5.0, numpy 2.5.4, scipy 1.18.1
- Data: 11,747 activities, 2,678 elementary flows, 113,945 entries in A, 274,766 in B (BAFU-2025-v2 from files.brightway.dev)
- Independent solver: largest relative residual |b − A x| / |b| after refinement 2.2e-15

### Results

| Case | Compared | Values | Largest relative gap |
|---|---|---:|---:|
| Scores: 4 products × 23 methods, methods as stored | LCA Wrench (HTTP) vs bw2calc | 92 | 2.3e-09 |
| Scores: 4 products × 23 methods, methods as stored | LCA Wrench vs independent solver, amounts rounded to float32 | 92 | 4.5e-08 |
| Scores: 4 products × 23 methods, methods as stored | bw2calc vs independent solver, amounts rounded to float32 | 92 | 4.5e-08 |
| Scores: 4 products × 23 methods, methods as stored | LCA Wrench vs independent solver, amounts as in SQLite (float64) | 92 | 1.9e-07 |
| Contributions by activity and by flow add up to the score | sum of the parts vs score | 168 | 1.7e-15 |
| Inventory of 250 tkm lorry transport: 2147 flows | LCA Wrench vs bw2calc | 1242 | 4.0e-08 |
| Inventory of 250 tkm lorry transport: 2147 flows | LCA Wrench vs independent solver (float32) | 1242 | 5.6e-08 |
| Calculation setup, 4 products × 4 methods | every cell vs bw2calc | 16 | 6.1e-11 |
| The app's own cross-check on that setup (relative to the gross impact) | ok | 16 | 6.1e-11 |
| Own model on the background (“E-bike, assembled”, 5 activities) | LCA Wrench vs bw2calc | 2 | 2.1e-08 |
| Own model on the background (“E-bike, assembled”, 5 activities) | LCA Wrench vs independent solver (float32) | 2 | 2.1e-08 |
| Completed factors: 4 products × 22 methods, and UBP total = sum of the categories | LCA Wrench vs independent solver with its own completion (float32) | 92 | 2.2e-08 |

## Reading the results

- **LCA Wrench against bw2calc** agrees to about 1e-9 on scores and 4e-8 on single inventory flows. Both read the
  same processed matrices; the small differences come from the solvers (LCA Wrench refines every solution
  iteratively, bw2calc solves once).
- **Against the independent solver**, gaps of up to about 6e-8 remain whether the amounts are rounded to float32 or
  not, and they are the same for bw2calc and LCA Wrench. Brightway stores exchange amounts and characterization
  factors in its processed matrices as **float32** (about 7 significant digits); the independent solver reads the
  amounts from SQLite in full precision. With the amounts in full precision (float64) the gap is larger (1.9e-7), which
  shows that it comes from the stored precision, not from the solvers. Results are therefore meaningful to about 6–7
  significant digits; where large flows cancel, fewer digits are meaningful.
- **Contributions** by activity and by flow add up to the score to rounding (1.7e-15).
- **Completed factors** (see [completed-factors.md](completed-factors.md)): the completion rule is implemented a
  second time in the script, from the SQLite rows; LCA Wrench with the completion switched on agrees with it, and the
  UBP total stays the sum of its 21 categories. The number of factors added per method is the same in both
  implementations.

## What the test suite enforces

Tolerances in `tests/` against plain bw2calc (relative unless noted):

| What | Test | Tolerance |
|---|---|---|
| Unit scores of sampled BAFU 2025 activities, 3 methods | `tests/test_service.py` | 1e-9 |
| Engine against a refined full solve, own models with loops and credits | `tests/test_engine.py` | 1e-12 of the gross impact |
| Engine against bw2calc, own models | `tests/test_engine.py` | 1e-7 of the gross impact |
| BAFU 2026 with EF 3.1 against bw2calc's solution refined to a zero residual | `tests/test_bafu2026.py` | 1e-9 |
| BAFU 2026 with EF 3.1 against bw2calc's single solve | `tests/test_bafu2026.py` | 1e-6 (see below) |
| Monte Carlo iterations against a bw2calc loop with the same seed | `tests/test_montecarlo.py` | 1e-8 |
| Contributions add up to the score | `tests/test_service.py`, `tests/test_engine.py` | 1e-9 |
| Completed factors: cross-check in both modes | `tests/test_completion.py` | 1e-8 of the gross impact |
| Factors by location against an independent calculation from bw2calc's inventory | `tests/test_regional.py` | 1e-9 of the gross impact |
| Factors by location in Monte Carlo against a bw2calc loop with the same seed | `tests/test_regional.py` | 1e-8 |
| Methods without factors by location: switch on and off | `tests/test_regional.py` | identical |

**Why BAFU 2026 has two tolerances.** bw2calc solves once (scipy's SuperLU with the pinned packages) and without iterative
refinement. The BAFU 2026 technosphere matrix is ill-conditioned, so a single solve is accurate to about
1e-8, depending on the platform's solver: the CI run on Linux (x86-64) of the previous development state failed with a
relative gap of 1.2e-8 against a tolerance of 1e-8, while the same test passed on macOS (arm64). The test
therefore compares LCA Wrench with bw2calc's own solution refined until its residual vanishes (1e-9), and with the
plain single solve only within what one solve can deliver (1e-6).

## Activity Browser

The Activity Browser calculates with bw2calc, so its totals and contribution tables rest on the same calculation as
the bw2calc column above. A comparison with the Activity Browser's own contribution and Sankey code (Activity
Browser 3.0) was done once by hand during development in November 2026; it is not part of this repository and no
figures from it are given. The Sankey diagrams differ by definition: see [../COMPARISON.md](../COMPARISON.md).

## Real ecoinvent data

LCA Wrench has been tested with real ecoinvent data by one of the authors. ecoinvent data cannot be redistributed, so
the automated tests and this script use the free BAFU data, and the ecoinvent import is tested with a miniature
ecoinvent-shaped test database.
