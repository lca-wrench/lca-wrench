<p align="center">
  <img src="lca_wrench/static/logo.svg" alt="LCA Wrench logo" width="96">
</p>

<h1 align="center">LCA Wrench</h1>

LCA Wrench is a local web interface for [Brightway](https://docs.brightway.dev) 2.5 with its own calculation engine
(Python 3.12, FastAPI, plain JavaScript). It builds product models, calculates several products and methods at once,
and shows results as contributions, Sankey diagram, supply chain tree and inventory. It runs in the browser on the
local computer only (127.0.0.1) and works on ordinary Brightway projects, so models and calculation setups can be
opened in the [Activity Browser](https://github.com/LCA-ActivityBrowser/activity-browser) as well. Version 0.1.0.

![Result view: climate impact of a product with contributions](docs/screenshots/result.png)

## Install

**Release packages.** From the [releases page](https://github.com/lca-wrench/lca-wrench/releases):

- **macOS:** download `LCA-Wrench-Mac.zip` and open **Install LCA Wrench**. The app is signed and notarized by Apple;
  macOS asks once whether to open an app downloaded from the internet. Choose the folder (default `~/LCA-Wrench`),
  then start **LCA Wrench** from the Desktop.
- **Windows:** download `LCA-Wrench-Windows.zip`, unpack, run **Install LCA Wrench**, then **Start LCA Wrench**.
  Windows warns the first time because the script is not signed ("More info" → "Run anyway").
- **Linux:** download `LCA-Wrench-Linux.tar.gz`, unpack it (e.g. `tar -xzf LCA-Wrench-Linux.tar.gz -C ~`), run
  `./install.sh` in the folder, then start **LCA Wrench** from the applications menu or with `./start.sh`.

The installers run only from these packages. "Source code (zip)" on the releases page and the `mac/`, `windows/`
and `linux/` folders of a clone are not installers; to run from a clone, see **From source** below.

The installer sets up its own Python and the packages inside the LCA Wrench folder (no administrator rights, internet
needed, 3 to 5 minutes). The Windows and Linux packages are less tested than the macOS one. Details:
[docs/install.md](docs/install.md).

**Which data with which installation.** With the release package, a project with BAFU 2026 (EF 3.1 methods) is
created in the app under "New project", and ecoinvent can be imported there with your own licence. BAFU 2025 with the
Ecological Scarcity 2021 methods and the example model, as in the screenshots, needs a Brightway project made from the
`BAFU-2025-v2` template; the derived climate method (kg CO2-eq) is added only by `setup_daten.py` from the source
installation, which also creates that project. Completed factors and the list of flows without a factor work in any
project.

**From source (macOS and Linux; Windows below).**

```bash
git clone https://github.com/lca-wrench/lca-wrench.git
cd lca-wrench
python3.12 -m venv .venv             # Windows: py -3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python setup_daten.py      # downloads the free BAFU 2025 data (about 62 MB) into a Brightway project
.venv/bin/python -m lca_wrench       # http://127.0.0.1:8787
```

Options: `python -m lca_wrench --port 8790 --no-browser`. `./start.sh` still works on macOS. On Windows use
`.venv\Scripts\python` instead of `.venv/bin/python`.

## Features

| Feature | What it does |
|---|---|
| Start | Project selection, databases by role (background, own models, biosphere flows), example model with one click, guided tour |
| Data | Search across all databases (typo-tolerant; filters for unit group and location), data sheet with description, share of each input in the impact, uncertainty, copy of an activity into your own model |
| Model | Own models (databases) and activities, inputs and emissions, amounts as numbers or formulas, credits, undo for every step, history, [moving a model to another region](docs/features.md#moving-a-model-to-another-region) |
| Parameters | Project, model and activity parameters with formulas, stored as in the Activity Browser ([docs](docs/features.md#parameters-and-formulas)) |
| Calculate | Calculation setups with several products × methods, stored in the Activity Browser format; cross-check with bw2calc; export as Excel or CSV |
| Result | Contributions by activity or flow; all categories of one or two methods, or one kind of impact across methods; Sankey; supply chain tree; inventory with filter and CSV; environmental profile in UBP; Excel/CSV export |
| Compare | Products across projects, for example original against working copy; calculation on every background database or scenario |
| Excel exchange | Export and import of own models in the bw2io format, with parameters, exact linking of partners ([docs](docs/features.md#excel-exchanging-your-own-models)) |
| Why different? | Difference between a working copy and its original, split exactly onto the changed exchanges |
| Versions | Same product in two versions of a background database (for example ecoinvent 3.10 and 3.11), difference split onto changed datasets and factors |
| Other database | Same product with another background database (for example BAFU and ecoinvent), with reviewable dataset matching and mapping files |
| Uncertainty | Coupled Monte Carlo over all products of a setup; pedigree matrix; sensitivity with rank correlation, contribution to variance and Sobol indices ([docs](docs/uncertainty.md)) |
| Background databases | BAFU 2025, BAFU 2026 with EF 3.1, ecoinvent, premise scenarios, EXIOBASE (hybrid models); one database, combined, or automatic ([docs](docs/data.md)) |
| Flow mapping | Methods on one list of elementary flows are applied to products on the other where this holds ([docs](docs/flow-mapping.md)) |
| Flows without a characterization factor | In Result, Inventory, each flow shows whether the method has a factor (characterized, characterized (flow mapping), characterized (completed), not characterized). A filter lists the not characterized flows, with a labelled estimate where the name has a factor in another sub-compartment; counts are shown above the result and the columns are in the export ([docs](docs/completed-factors.md)) |
| Completed factors | Some methods (the Ecological Scarcity 2021 methods of the BAFU-2025-v2 template) carry most factors only on the flow without sub-compartment. LCA Wrench completes them at calculation time, marks this in the result, and the list of added factors can be exported. On by default, can be switched off; stored methods are not modified ([docs](docs/completed-factors.md)) |
| Real projects | Projects are never opened or converted without asking; test copies; Activity Browser 2 projects only as a copy; foreign databases are protected; changes from other programs are detected |
| Language | English by default, German switchable in the interface |

## Data

Nothing is bundled except the flow mapping (CC BY 4.0, see `lca_wrench/data/flowmaps/README.md`). All LCA data are
downloaded or imported by the user: the BAFU 2025 template from files.brightway.dev, BAFU 2026 via sentier-brightway,
ecoinvent with the user's own licence, premise scenarios and EXIOBASE. Background data stays unchanged; changes happen in
your own models or in a working copy of the project. Details, licences and citation wording for data sources:
[docs/data.md](docs/data.md).

LCA Wrench has been tested with real ecoinvent data by one of the authors; ecoinvent data cannot be redistributed, so the
automated tests use the free BAFU data and a miniature ecoinvent-shaped test database.

## Validation

`scripts/validate.py` reruns the comparison on the free BAFU 2025 data: LCA Wrench, asked through its HTTP API,
against plain bw2calc and against an independent solver that builds the matrices from the SQLite exchange rows. For
this release, scores agree with bw2calc to within 2.3e-9 (relative), inventory flows to within 4e-8, and both agree
with the independent solver to within 6e-8, a gap that comes from Brightway storing matrix values in single precision
(float32). The test suite checks the engine against bw2calc on every change. Details, conditions and tolerances:
[docs/validation.md](docs/validation.md).

**Note on BAFU 2025 and Ecological Scarcity 2021.** The methods in the Brightway template carry most factors only on
flows without sub-compartment, so emissions into sub-compartments count as zero (1 kWh Swiss low-voltage electricity:
0.0142 kg CO2-eq). LCA Wrench completes these factors at calculation time and marks the result (same example:
0.0971 kg CO2-eq); it can be switched off. See [docs/completed-factors.md](docs/completed-factors.md).

## Known limits

- Scenarios are available through premise databases (one per year) and a key is needed (it can be requested from the premise authors); there are no scenario difference files (Activity
  Browser) and no superstructure databases. Monte Carlo and the cross-check do not work while inputs are taken from
  counterparts in another background database.
- Moving a model to another region swaps suppliers by name only, not consumption mixes or imports; models with
  parameters cannot be moved.
- EXIOBASE has no uncertainty; Monte Carlo on it would factorize the dense table per iteration. EXIOBASE was not run
  with the real tables here, only with a small table in its file format. The premise integration was checked with a
  stand-in for premise.
- Parameters: no uncertainty of parameters in Monte Carlo, no dependencies between activity groups.
- Changing background data (only in a working copy) rebuilds the matrix.
- Activities with several products (multifunctional) are not treated specially.
- The climate method derived from ecological scarcity (BAFU 2025) is not a standalone IPCC method; see
  [docs/data.md](docs/data.md).
- The Activity Browser and LCA Wrench working on the same project at the same time can overwrite each other's entries;
  close one of them first.

## Documentation

- [Installation](docs/install.md), [Data and imports](docs/data.md), [Calculation](docs/calculation.md)
- [Features](docs/features.md), [Uncertainty and sensitivity](docs/uncertainty.md), [Flow mapping](docs/flow-mapping.md)
- [Completed factors](docs/completed-factors.md), [Validation](docs/validation.md), [Comparison with other tools](COMPARISON.md)
- [Demo walkthrough](docs/demo.md), [Development](docs/development.md), [Contributing](CONTRIBUTING.md),
  [Security](SECURITY.md)

## Citation

See [CITATION.cff](CITATION.cff). In plain text:

Pfister, K. and Pfister, S. (2026). LCA Wrench (version 0.1.0). https://github.com/lca-wrench/lca-wrench

## Licence

BSD 3-Clause, see [LICENSE](LICENSE). Copyright (c) 2026 Kilian Pfister and Stephan Pfister.

## Authors

- Kilian Pfister
- Stephan Pfister (ETH Zurich, Institute of Environmental Engineering)

Maintainer: Kilian Pfister
([@misterpfister8](https://github.com/misterpfister8)). Questions and bug reports through
[GitHub Issues](https://github.com/lca-wrench/lca-wrench/issues).

## Acknowledgements

LCA Wrench builds on [Brightway](https://docs.brightway.dev) (bw2data, bw2calc, bw2io) and follows the conventions of the
[Activity Browser](https://github.com/LCA-ActivityBrowser/activity-browser). It uses
[sentier-brightway](https://github.com/sentier-dev/sentier-brightway), the flow mapping from
[randonneur_data](https://github.com/brightway-lca/randonneur_data) (UNEP GLAD mapping, CC BY 4.0),
[premise](https://github.com/polca/premise) and [EXIOBASE](https://www.exiobase.eu). The interface uses the IBM Plex
fonts (SIL Open Font License 1.1, bundled in `lca_wrench/static/fonts/`).

Stephan Pfister's work on LCA Wrench was supported by the [GreenGrocer](https://greengrocer.nilu.no/) project
(Horizon Europe, project no. 101182025), co-funded by the European Union and the Swiss Confederation. Views and
opinions expressed are those of the authors only and do not necessarily reflect those of the European Union or the
Swiss Confederation.
