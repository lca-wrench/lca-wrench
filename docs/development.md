# Development

Setup and contribution rules: [../CONTRIBUTING.md](../CONTRIBUTING.md).

## Tests

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
./check.sh                 # ruff (lint) and pytest including browser tests
./check.sh --no-browser    # without the browser tests
```

Without the script: `python -m ruff check . && python -m pytest -q`. The GitHub workflow `.github/workflows/test.yml`
runs the same on Linux, Windows and macOS for every pull request and push to main, on an installation from the release
package, and checks a known result and the update from the last release ([ci.md](ci.md)).

On Windows a file that is still open cannot be deleted (WinError 32). The engine closes the processed datapackages of
a calculation once it has read them (`engine.close_files`), so its cache keeps no file open; a project is removed
with `service.remove_project` (it calls `engine.forget` first, then retries the folder), and tests clean up with it
too. Opening another project releases what the server's threads still hold of the project left
(`service.release_files`) and, on Windows, drops the cached calculations of the projects opened before, so the
Activity Browser can delete or change them.

The browser tests (`tests/test_browser.py`, Playwright) drive the installed Google Chrome and start their own local
process on port 8795 in the project `lca-wrench-test`. They go through the tour, create the example model, change an
amount live and undo it, run a calculation setup with cross-check (bw2calc), open result, Sankey and inventory, and
clean up at the end. Any JavaScript error in the browser makes the test fail. On Linux, another Chromium can be used
with `LCA_WRENCH_CHROME=<path to chrome> ./check.sh`.

The tests need the project `bafu-2025` (from `setup_daten.py`) and run in their own project `lca-wrench-test` (created on
the first run as a copy of `bafu-2025`, without own models). No test touches `bafu-2025` or `lca-wrench.json`:
`set_current("bafu-2025")` raises an error in the tests, and the registry points to a temporary file
(`LCA_WRENCH_REGISTRY`). Projects named `lca-wrench-test…` do not appear in the project selection. Tests run with German
texts (`LCA_WRENCH_LANG=de`).

- `tests/test_engine.py`: engine against an independent, refined full calculation and against bw2calc, on a test model
  with a loop, a credit and a biosphere flow known only to the model; supply vector, inventory, contributions, live
  change, undo, copying, write protection, broken models, tree, Sankey, calculation setups in the Activity Browser
  format and the example model.
- `tests/test_service.py`: unit scores and contributions against bw2calc, working copy.
- `tests/test_api.py`: API flows, write protection, protection against foreign hosts, 64-bit IDs for activities and
  exchanges.
- `tests/test_safety.py`, `tests/test_older_projects.py`: real projects (conversion only on request, test copy leaves the
  original unchanged, foreign databases protected, undo against changes from outside, start without a project,
  Activity Browser 2 projects).
- `tests/test_i18n.py`: every text has an English version with the same placeholders; no unused UI entry remains.
- Further files cover imports (`ecoinvent_mini.py`, `fake_premise/`), backgrounds, BAFU 2026, completion, crosswalk,
  Excel, parameters, Monte Carlo, versions, "Why different?", external changes and the lock file.

ecoinvent data cannot be redistributed, so the automated tests use the free BAFU data and a miniature ecoinvent-shaped
test database.

## Structure of the code

```text
lca_wrench/__main__.py   Cross-platform start (python -m lca_wrench)
lca_wrench/engine.py     Engine: roles of the databases, background (LU cache), foreground, system
lca_wrench/analysis.py   Contributions, inventory, supply chain tree, Sankey
lca_wrench/completion.py Completed factors for sub-compartments, factor status per inventory flow
lca_wrench/flowmap.py    Flow mapping between lists of elementary flows, method coverage
lca_wrench/models.py     Editing your own models, history and undo, data sheet
lca_wrench/params.py     Parameters and formulas (project, model, activity, amounts), checked before writing
lca_wrench/excel.py      Excel export and import of your own models (bw2io format, with parameters)
lca_wrench/setups.py     Calculation setups (products × methods) in the Activity Browser format
lca_wrench/montecarlo.py Uncertainty: coupled iterations, statistics, background jobs
lca_wrench/service.py    Projects, search, result, cross-check, working copies, comparison, Activity Browser 2 projects
lca_wrench/regions.py    Locations for search and moving: names to codes, the regions around a country (CH → Europe → GLO)
lca_wrench/overview.py   Methods grouped (EF, ReCiPe … also under ecoinvent's own name); all categories of one or two
                         methods, or one kind of impact across all; export of results as Excel or CSV
lca_wrench/reproject.py  Moving an own model to another region (electricity or all inputs)
lca_wrench/versions.py   Comparing versions: difference split exactly onto changed datasets and factors
lca_wrench/crosswalk.py  Other database: the same product with another background database, matching, mapping files
lca_wrench/beispiel.py   Example model e-bike
lca_wrench/bafu2026.py   Importing BAFU 2026 with EF 3.1 (sentier-brightway)
lca_wrench/ecoinvent.py  Importing ecoinvent as in the Activity Browser (account or files from ecoinvent.org)
lca_wrench/imports.py    New projects, imports as background jobs, databases added to the open project
lca_wrench/backgrounds.py Which background databases a calculation uses (one, combined), counterparts of datasets
lca_wrench/scenarios.py  premise: its own environment, options, the scenario job (premise_worker.py runs in it)
lca_wrench/premise_worker.py premise run in its own environment, as a separate process
lca_wrench/exiobase.py   EXIOBASE import (bw2io), run as a separate process
lca_wrench/repair.py     Rebuilding an empty or broken databases.json
lca_wrench/registry.py   lca-wrench.json (reads an older werkbank.json)
lca_wrench/i18n.py       Language of the server messages (English/German)
lca_wrench/api.py        FastAPI, only 127.0.0.1, language per request, versioned UI paths
lca_wrench/data/         Flow mapping (see data/flowmaps/README.md)
lca_wrench/static/       Interface (HTML, CSS, JavaScript modules without a build step; translation in js/i18n.js)
setup_daten.py           Setting up data and derived methods
bench_gross.py           Factorization benchmark (see calculation.md)
```
