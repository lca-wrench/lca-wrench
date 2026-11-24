# LCA Wrench, Activity Browser and Brightway compared

Compared: LCA Wrench 0.1.1, Activity Browser 3.0, Brightway 2.5 (bw2data 4.8, bw2calc 2.5.0). Feature rows describe
the documented feature sets as of November 2026.

All three work on the same thing: a **Brightway 2.5 project** (bw2data 4, bw2calc 2) in the Brightway folder on
your computer. Brightway is the library that stores the data and calculates. The Activity Browser and LCA Wrench
are two interfaces on top of it. A model built in one opens in the others.

## In one sentence each

| | |
|---|---|
| **Brightway 2.5** | A Python library. Everything is possible, all of it by writing code: import, modelling, calculation, analysis, plots. |
| **Activity Browser 3** | A desktop app that shows nearly all of Brightway with menus and tables, including scenarios, multifunctional data and method editing. |
| **LCA Wrench** | A local web app for building your own models on a fixed background database, getting results immediately, and explaining why two results differ. A server version with user accounts is planned. |

## Use cases: which one to pick

| You want to … | Brightway (Python) | Activity Browser | LCA Wrench |
|---|---|---|---|
| Build a product model on BAFU or ecoinvent and see its impacts | possible, in code | ✓ | ✓ search, copy, change amounts, result updates at once |
| Try variants (amounts, suppliers) and see the effect immediately | re-run the script | recalculate | ✓ every edit recalculates in milliseconds; undo for every step |
| Explain why two results differ (copy vs original, ecoinvent 3.10 vs 3.11, BAFU vs ecoinvent) | write it yourself | contributions side by side | ✓ "Why different?", "Versions", "Other database": exact splits down the supply chain |
| Compare many products × methods | `MultiLCA` | ✓ calculation setups | ✓ calculation setups (same format); all categories of one or two methods side by side, or one kind of impact (e.g. climate change) across all methods, for one product |
| Scenarios (e.g. future electricity mixes, premise) | ✓ datapackages, premise | ✓ scenario difference files | ✓ premise from the app (own environment, one database per year); the same model on today or a scenario by choosing the background, "With every background" in Compare |
| Several background databases in one project | ✓ | ✓ | ✓ one chosen (inputs taken from the counterpart there) or several combined; databases can be added to an existing project |
| Input-output data (EXIOBASE), hybrid LCA | ✓ bw2io importer | see its documentation | ✓ EXIOBASE 3 import (download or file), dense solver, models with inputs in euro next to process data |
| Multifunctional activities, allocation choices | ✓ `multifunctional` package | ✓ supported in version 3 | – not handled specially |
| Create or edit impact methods | ✓ | ✓ | – uses the methods in the project |
| Edit background data | ✓ | ✓ | only in a working copy |
| Uncertainty (Monte Carlo) | ✓ | ✓ | ✓ up to 10,000 coupled iterations |
| Sensitivity analysis | ✓ any method you code (e.g. SALib) | ✓ global sensitivity analysis | top 10 of the 250 most promising uncertain values: rank correlation, CTV (exact derivatives, all values) and Sobol S₁/S_T with intervals |
| Import ecoinvent, SimaPro CSV, Excel, other formats | ✓ bw2io, all formats | ✓ ecoinvent, Excel and more | ecoinvent, BAFU 2026, premise scenarios and EXIOBASE, into new or existing projects; Excel for own models |
| Reproducible pipelines, batch runs, papers | ✓ well suited: scripts, notebooks, version control | see its documentation | limited: CSV and Excel export |
| Teaching, first steps without code | – | ✓ | ✓ guided tour, English and German |

## How each one calculates

| | Brightway (bw2calc) | Activity Browser | LCA Wrench |
|---|---|---|---|
| Solver | builds A and B for the requested product, factorizes A, solves | calls bw2calc (`LCA`, `MultiLCA`) | own engine on top of bw2calc's matrices |
| What is reused between calculations | nothing by default; each `LCA` object rebuilds and factorizes | the same as bw2calc | background matrix factorized **once** when a project is opened; unit scores cached per method |
| Own models (foreground) | part of the same matrix | the same as bw2calc | solved separately and coupled through the background's unit scores; exact, because the background never uses foreground products |
| Accuracy | direct sparse solve | the same as bw2calc | direct solve plus 2 steps of iterative refinement |
| Time for one result | bw2calc builds and factorizes the matrix for each new LCA object: about 0.2 s for 1 kWh electricity on BAFU 2025 (11,747 activities, Apple silicon Mac, without scikit-umfpack); longer on ecoinvent | the same as bw2calc plus the interface | the first build when a project is opened takes seconds; each further result, edit, product × method cell or Sankey step is then answered from the stored factorization in milliseconds |

The two timings measure different things (a new solve versus a reused factorization) and are not a like-for-like
speed comparison. The formulas behind LCA Wrench's split are in [docs/calculation.md](docs/calculation.md).

## Are the numbers the same?

LCA Wrench's results are checked against plain bw2calc and against an independent solver by `scripts/validate.py`,
which anyone can rerun; results and conditions are in [docs/validation.md](docs/validation.md).

The Activity Browser calculates with bw2calc, so its totals and contribution tables rest on the same calculation.
A comparison with the Activity Browser's own contribution code was done once by hand during development (Activity
Browser 3.0, November 2026) and is not part of the repository, so no figures are given.

## The Sankey diagram: two definitions

- **Activity Browser** (bw_graph_tools graph traversal): a box is the largest single path to that activity above a
  cutoff.
- **Brightway** has no diagram of its own; bw_graph_tools gives the same traversal for you to plot.
- **LCA Wrench**: a bar is everything that passes through the activity, all paths together (unit score × total
  output), with no cutoff. With the option *Own contribution*, the bars show each activity's direct emissions, which
  add up to the total.

Both are valid views of the same supply chain. They agree along a single dominant chain and differ where an activity
is reached by many small paths.

## Data and files they share

| | Brightway | Activity Browser | LCA Wrench |
|---|---|---|---|
| Projects, databases, methods | the source | the same | the same |
| Calculation setups | `calculation_setups` | the same format | the same format |
| Parameters (project, database, activity) and formulas | ✓ | ✓ | ✓ the same tables; no uncertainty on parameters in Monte Carlo |
| Own settings | – | its own settings file | `lca-wrench.json` in the Brightway folder: working copies, own models, undo history, confirmed matches between databases |

**Close one tool before opening the same project in another.** They write to the same files; if two programs work on
one project at the same time, the last one to save wins.

## Installation

| | Brightway | Activity Browser | LCA Wrench |
|---|---|---|---|
| How | `pip` or `conda`, in a Python environment | `conda` or `pip` | zip packages for macOS and Windows (double-click installer), or from source with pip |
| Runs as | Python, Jupyter | desktop app | web page on your own computer (127.0.0.1), only you can reach it |
| Language | English | English | English and German |
