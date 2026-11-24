# Data and imports

Nothing is bundled except the flow mapping (see [flow-mapping.md](flow-mapping.md)), the sector matching for EXIOBASE
(`lca_wrench/data/sectors`, see [features.md](features.md#other-database-the-same-product-with-another-background-database))
and GDP by country from the World Bank (`lca_wrench/data/regions`, CC BY 4.0, for the weights of factors by location,
see [regional-factors.md](regional-factors.md)). All LCA data are downloaded or
imported by the user, under the terms of their publisher. A new project is made from the start page or the project
selection (**New project**): an empty Brightway project, or one with background data right away. An empty open project
shows "This project is still empty" with the same imports. Code: `lca_wrench/imports.py` (projects, jobs),
`lca_wrench/ecoinvent.py`.

| Content | How |
|---|---|
| Empty | `bd.projects.create_project`, Brightway 2.5 format |
| BAFU 2025 | `setup_daten.py`, template from files.brightway.dev |
| BAFU 2026 with EF 3.1 | sentier-brightway, see below |
| ecoinvent with account | bw2io `import_ecoinvent_release` as in Activity Browser 3: log in with your own ecoinvent account; "Log in and show versions" lists what the account may download; download (about 1 GB, then in the cache of ecoinvent_interface), biosphere, datasets, methods from the LCIA file of the version |
| ecoinvent from files | the same bw2io function with files downloaded from ecoinvent.org: `ecoinvent 3.x_<model>_ecoSpold02.7z` (or the unpacked folder) and, for the methods, `ecoinvent 3.x_LCIA_implementation.7z` (or the `.xlsx` from it). LCA Wrench reads version and system model from the file name |
| premise, EXIOBASE | "Add a database", see below |

LCA Wrench has been tested with real ecoinvent data by one of the authors; ecoinvent data cannot be redistributed, so
the automated tests use the free BAFU data and a miniature ecoinvent-shaped test database (`tests/ecoinvent_mini.py`).

## BAFU 2025

`setup_daten.py` downloads `BAFU-2025-v2` from the official Brightway template (files.brightway.dev; about 62 MB) into
the project `bafu-2025`. Methods: the 21 categories of ecological scarcity 2021 from the template, plus two that
`setup_daten.py` derives:

- *Climate change, kg CO₂-eq*: the UBP factors for "Global warming" divided by 1000 UBP per kg CO₂. This is not a
  standalone IPCC method: the factors are rounded (CH₄ 30, N₂O 270, SF₆ 24,000), and fossil CO₂ emitted in
  "stratosphere + troposphere" (aviation) counts 3.1 times, as in ecological scarcity 2021. EF 3.1 in BAFU 2026 uses the
  IPCC AR6 values (CH₄ 29.8, N₂O 273, SF₆ 25,200) and counts fossil CO₂ once.
- *UBP total*: the sum of all 21 categories.

In Brightway they are stored as `("Werkbank", "Klimawandel", "kg CO2-eq, abgeleitet aus UBP 2021")` and
`("Werkbank", "Umweltbelastungspunkte gesamt", "UBP 2021")` (`CLIMATE_METHOD`, `UBP_TOTAL_METHOD` in
`lca_wrench/service.py`). "Werkbank" is an earlier name of the app, kept so that existing projects still find these
methods.

The example model (e-bike) is a simplified teaching example with estimated amounts, not a validated dataset.
Background data stays unchanged: changes happen only in your own models or in a working copy of the project
(`projects.copy_project`, about 420 MB).

## BAFU 2026 with EF 3.1

Besides BAFU 2025, LCA Wrench can set up BAFU 2026 with the 25 categories of EF 3.1 via
[sentier-brightway](https://github.com/sentier-dev/sentier-brightway) (`lca_wrench/bafu2026.py`). In the app: start page
(or project selection), "Import BAFU 2026", as long as the project `bafu-2026` does not exist yet. By hand:
`.venv/bin/python setup_daten.py --bafu-2026`.

- sentier-brightway loads the inventory, the EF 3.1 biosphere, the methods and the mapping of the BAFU flows to EF 3.1
  from fixed versions of the Sentier data repositories (about 36 MB, each file checked against its sha256, then cached)
  and writes with bw2data: `bafu-2026` (11,947 activities, background), `ef-3.1-biosphere` (biosphere flows),
  `bafu-2026-residual` (113 BAFU flows without an EF counterpart, without a factor) and the methods
  `("sentier", "EF v3.1", …)`. 95.8 % of the flows and 96.8 % of the emission exchanges are mapped to EF 3.1.
- Like the ecoinvent import, it goes into a new or empty project; a project with data is never touched. If it fails,
  LCA Wrench removes what it created and returns to the previous project.
- The start method is EF 3.1 *Climate change*. The two derived UBP methods and the environmental profile in UBP are not
  available there (no ecological scarcity in this project).
- Packages: `sentier-brightway` as a GitHub archive of a fixed commit in the requirements (no git needed), plus `pyarrow`;
  for ecoinvent `ecoinvent_interface` (with `py7zr` for the 7z files).
- Tested in `tests/test_bafu2026.py`: import into a separate test project, roles, existing installation unchanged, a
  failed import leaves nothing behind, API.

## ecoinvent

- **Same function as in the Activity Browser:** in both routes bw2io `import_ecoinvent_release` itself runs. For files it
  gets a replacement for ecoinvent_interface that supplies the local files. Linking, biosphere (`ecoinvent-3.x-biosphere`),
  database (`ecoinvent-3.x-cutoff` …) and methods (`("ecoinvent-3.x", …)`) are named as in the Activity Browser.
- **Login:** user name and password go only to ecoinvent (via ecoinvent_interface) and appear in no log. They are
  saved only with the checkbox "Save the login on this computer (like the Activity Browser)", in the same place as the
  Activity Browser. LCA Wrench uses a login already saved there if the fields are left empty.
- **New, empty, or added to the open project.** Start, "Background data for calculating", "Add a database" puts one
  more database into the open project (ecoinvent, BAFU 2026, a premise scenario, EXIOBASE). Adding never overwrites: an
  existing database of the same name is refused, and ecoinvent's methods are written only when the project does not
  have those of that version yet. If something goes wrong, LCA Wrench removes the new project entirely or, in an
  existing project, the databases and methods the import created.
- **Background job:** the dialog shows the steps (log in, download, read datasets, write, methods, prepare the
  calculation). The import takes a long time. While it runs, LCA Wrench holds all other requests (Brightway has one
  current project per process). Reloading the page shows the running job again. At the end the project is open and the
  matrix factorized.
- bw2io reads the datasets with several processes; LCA Wrench switches this on only if the worker processes can load
  the main program (otherwise they would restart endlessly) and there are more than 200 datasets.
- Tests (`tests/test_imports.py`) use a small release in the format of ecoinvent.org (`tests/ecoinvent_mini.py`: two
  datasets, biosphere flows from bw2io, an LCIA file): empty project; from archive and from folder, with and without
  LCIA file; path with account (login service replaced); failed imports leave nothing behind; a project with data is
  refused; API.

## Real projects (for example ecoinvent in Activity Browser 3)

- **Nothing is opened by itself.** Without a last chosen project (and without `bafu-2025`) the app starts without a
  project and asks. Everything except project selection and copying then answers with 409 "Please choose a project at the
  top first."
- **Test copy** (`service.copy_project_files`, `/api/project/copy`): copies a project of any format file by file, without
  opening the original, and opens the copy ("… (LCA Wrench)", in `lca-wrench.json` under `testcopies`). In a copy made
  by LCA Wrench (test copy or working copy) all foreground databases can be changed.
- **Conversion on opening:** a project created with an older Brightway 2.5 version gets the automatic updates of bw2data
  when it is first opened (for example "4.7 database dependencies": all databases and methods are reprocessed, which
  takes minutes for ecoinvent). `service.pending_updates` reads this from `preferences.pickle` without opening the
  project. Such projects are marked in the selection; the app asks ("Make a test copy" recommended, or "Open the
  original") and never opens them by itself, not even for Compare or Versions.
- **Projects from Activity Browser 2** (Brightway 2, without the 2.5 marker) are never opened by LCA Wrench: Brightway
  2.5 would convert them on opening, and afterwards Activity Browser 2 could no longer read them. They are marked in the
  selection; choosing one explains this and offers a copy (`service.copy_older_project`: the folder is copied file by
  file, and only the copy is converted). If the app starts in an empty project, the start page offers the copies.
  Projects in the 2.5 format (Activity Browser 3) are opened directly; Brightway may rebuild its processed data.
- **Foreign databases are protected:** a database that refers to background data but was not created in LCA Wrench is
  calculated live, but not changed or deleted in the original (`models.writable_databases`). Project parameters are
  locked as soon as such databases have parameters.
- **Undo checks first:** every step remembers the state after it. If another program has changed the data in the
  meantime, nothing is overwritten: the app reports it and clears the history. Steps already undone stay undone.
- **A project that cannot be loaded** (for example an unknown database backend) shows the error and the project
  selection instead of staying at "Loading Brightway project …"; it is not opened again at the next start. A project
  deleted from outside is not recreated.
- **Other websites** in the browser cannot send requests (`Origin` and `Sec-Fetch-Site` are checked).

Tested in `tests/test_safety.py` and `tests/test_older_projects.py`. Limit: the Activity Browser and LCA Wrench working
on the same project at the same time can overwrite each other's entries in `databases.json` or calculation setups (the
last writer wins); close the Activity Browser first.

What the app manages itself is stored in `lca-wrench.json` in the Brightway folder (an older `werkbank.json` is still
read): working copies, which databases are your own models, the history for "Undo", and confirmed matches of "Other
database".

## Several background databases: one, or combined

A project can hold several background databases: BAFU and ecoinvent, two ecoinvent versions, premise scenarios, or
EXIOBASE. Start, **Background data for calculating** (and the "Background" list in the header, as soon as there are
two) chooses what a calculation uses (`lca_wrench/backgrounds.py`):

| Choice | What is calculated |
|---|---|
| **One database** | Everything on exactly this database. Inputs of the models from another background database are taken from their counterpart in the chosen one: the same code (premise and newer ecoinvent versions keep the codes), otherwise the same name, reference product, location and unit, otherwise the nearest location (DE → RER → GLO → RoW). An input without counterpart keeps its database, which then joins the calculation; the card says so. The same model can thus be calculated on ecoinvent today or on a scenario for 2040 without copying it |
| **Combine several** | Several databases at once, with the links as stored: for example ecoinvent for materials and EXIOBASE for services in euro (hybrid LCA), or BAFU next to ecoinvent |
| **Automatic** (default) | All process databases, without scenarios and input-output tables |

The choice is kept per project in LCA Wrench's registry, not in the project. Search shows the chosen databases (and the
models). With one database or several chosen, a dataset of another database (opened from a model, or added to Compare)
is calculated as its counterpart there ("calculated as …" in the result). In automatic mode a dataset of a database it
leaves out (a premise scenario, EXIOBASE) is calculated on its own database instead. **Compare**, "With every
background", calculates the last product once per process and scenario database (today against 2030, 2050 …). Monte
Carlo and the bw2calc cross-check follow the links as stored, so they refuse to run while inputs are taken from
counterparts, and say why. How the databases are solved: [calculation.md](calculation.md).

## Future scenarios with premise

"Add a database", **Future scenario (premise)**: [premise](https://github.com/polca/premise) recalculates an ecoinvent
database of the project (3.5 to 3.12, cut-off or consequential) along a scenario of an integrated assessment model
(REMIND, REMIND-EU, IMAGE, MESSAGE, TIAM-UCL; pathways such as SSP2-NPi, SSP2-PkBudg1000, SSP2-M) for one or more
years between 2005 and 2100. Each year becomes a database of its own, for example
`ecoinvent-3.10-cutoff remind SSP2-NPi 2040`, marked as a scenario.

- **Only scenarios that exist:** premise lists every pathway for every model, but its archive of scenario files on
  Zenodo has only some pairs (premise 2.5.2 uses record 22227290, which has no "SSP2-Base" and nothing for GCAM or
  WITCH; asking for another pair fails with a 404). The dialog asks Zenodo which files the archive holds and offers for
  each model only the pathways whose file premise would find there or already on this computer. If Zenodo cannot be
  reached, it shows premise's full list with a note.
- **Own environment:** premise 2.5.2 needs numpy 1.26, pandas 2.x and scipy 1.13, older than LCA Wrench. It therefore
  gets a Python environment of its own next to the app (`.premise-venv`, set up once from the dialog with uv from
  `lca_wrench/premise-requirements.txt`, about 1 GB) with the same Brightway versions as the app, so both read and
  write the project alike. It runs as a separate process (`lca_wrench/premise_worker.py`); the app stays usable.
- **Key:** premise's scenario data are encrypted; the premise authors give out the key for free. It goes to the worker
  on stdin (not visible in the process list) and is stored only with "Save the key on this computer"
  (`premise-key.txt` next to `lca-wrench.json`). The scenario data may not be passed on.
- **Run:** a run takes a long time and several GB of memory. A failed run removes the databases it made.
- **The database list is protected:** bw2data keeps the list of a project's databases in `databases.json`. If a value in
  it cannot be written as JSON, bw2data's atomic write still swaps in the new file, which is then empty, and no program
  can open the project. The worker therefore gives premise copies of the scenario descriptions, checks the list before
  every write, and puts back the list from before the run should it be unreadable.
- **Tests:** the job, the worker, the cleanup and the use of the result are tested with a stand-in for premise with
  the same interface (`tests/fake_premise`, which also adds a path to the scenario descriptions and can fail after
  writing), in `tests/test_backgrounds.py` and in the browser. A real premise 2.5.2 run with ecoinvent 3.12 (IMAGE
  SSP2-M) wrote its databases; it is not part of the automated tests.

## EXIOBASE (multi-regional input-output)

"Add a database", **EXIOBASE**: downloaded from Zenodo (versions 3.8 to 3.8.2, a year, product × product or
industry × industry, 0.6 to 1 GB) or from a file or folder already downloaded (`lca_wrench/exiobase.py`, bw2io's
importer, as a separate process). About 200 products in 49 regions in million euro, with emissions and resources.

- Emissions are linked to a biosphere database of the project chosen in the dialog (best ecoinvent's) by name and
  compartment; bw2io's table of EXIOBASE flows becomes `<name> biosphere`. Unlike bw2io's own import, a flow that cannot
  be linked at all is left out and counted instead of breaking the import, the PFC and HFC flows (given in CO₂-eq) are
  linked under the names bw2io gives them, and the new biosphere is marked as such.
- bw2io's step that adds those two flows to every method in kg CO₂-eq (factor 1) runs last and is undone if the import
  fails. This changes existing methods of the project.
- **Hybrid LCA:** a model can take inputs in million euro from EXIOBASE next to inputs in kg or kWh from ecoinvent
  (search with the unit filter "Money"; EXIOBASE is always searched). The table then joins the calculation of the model,
  also in "Automatic", as a database the model links to; "Combine several" makes it explicit. The model is solved on its
  own and buys from both backgrounds. Score = sum over the model's purchases of amount × unit score of the bought dataset in
  its own database, plus the model's direct emissions. There is no correction for double counting between the two (a
  tiered hybrid, not an integrated one): what a model buys in euro must not repeat what it buys in kg.
- A sector opened when EXIOBASE is not in the calculation (data sheet, result, Sankey, cross-check) is calculated on its
  table alone, and the data sheet says so.
- **Tests:** a 2-region, 2-sector table in EXIOBASE's file format: import in the app and as a job, dense solver against a
  hand calculation and bw2calc, a hybrid model. Not run with the real EXIOBASE tables here.

## Removing an added database

Under Start, "Remove an added database" lists the databases LCA Wrench added itself: premise scenarios and EXIOBASE
(marked in the database's metadata). Removing one is refused while a model or another database uses it. EXIOBASE takes
its own biosphere database (`<name> biosphere`), the two factors its import added to the methods, and its matrix file
along. It cannot be undone; the database can be imported again. ecoinvent, BAFU and databases from elsewhere cannot be
removed in the app. Checked in `tests/test_backgrounds.py`.

## Repairing an empty database list

If a project cannot be opened because its `databases.json` is empty or broken, LCA Wrench says so and does not start on
it. The data themselves (activities and exchanges in `lci/databases.db`, matrices in `processed/`) are intact, and
`lca_wrench/repair.py` rebuilds the list from them:

```bash
.venv/bin/python -m lca_wrench.repair "<project>"            # shows the rebuilt list, writes nothing
.venv/bin/python -m lca_wrench.repair "<project>" --write    # writes it, then reprocesses the databases
```

The rebuilt list contains every database with activities, plus LCA Wrench's empty model databases; backend `iotable`
for EXIOBASE (its exchanges live only in its datapackage), else `sqlite`; dependencies from the exchanges (EXIOBASE:
from the rows of its matrices); LCA Wrench's tags for premise scenarios (from the name) and EXIOBASE. Only descriptive
fields such as "format" are lost. The broken file is kept as `databases.json.broken-<time>`, a readable list is never
overwritten, and `--drop "<database>"` removes a database left by a failed run. On Windows use
`.venv\Scripts\python.exe`. Tested in `tests/test_backgrounds.py` (a project with models, a scenario and EXIOBASE: same
backends and dependencies after the repair).

## Licences and citing data

LCA Wrench is BSD 3-Clause licensed (see [LICENSE](../LICENSE)). The installers download Python, uv and the packages of
`requirements-lock.txt` when they run; none of them is part of this repository or of the zip files. Each comes under its
own open licence: mostly MIT, BSD or Apache 2.0 (Brightway, FastAPI, sentier-brightway, premise), LGPL for py7zr and
pyxlsb (used unchanged by bw2io), MPL 2.0 for certifi and tqdm, the PSF licence for Python. The fonts IBM Plex Sans and
Mono (SIL Open Font License 1.1) are bundled in `lca_wrench/static/fonts/`.

ecoinvent needs a licence of its own; premise's scenario data need a key from its authors and may not be passed on.
The test data in `tests/` are made up. When publishing results, cite what was used:

| Used | Cite |
|---|---|
| BAFU:2026 (required wording) | "Source: Life Cycle Inventory database of the Swiss Federal Administration, BAFU:2026." |
| BAFU:2025 | "Source: Life Cycle Inventory database of the Swiss Federal Administration, BAFU:2025." |
| EF 3.1 | European Commission, Joint Research Centre (2023): Updated characterisation and normalisation factors for the Environmental Footprint 3.1 method. Publications Office of the EU. https://doi.org/10.2760/798894 |
| Ecological scarcity 2021 (UBP) | FOEN (2021): Swiss Eco-Factors 2021 according to the Ecological Scarcity Method. Federal Office for the Environment, Bern, Environmental studies no. 2121. |
| ecoinvent | Wernet, G. et al. (2016): The ecoinvent database version 3 (part I): overview and methodology. Int J Life Cycle Assess 21(9), 1218–1230. https://doi.org/10.1007/s11367-016-1087-8 |
| EXIOBASE 3 (CC BY-SA 4.0) | Stadler, K. et al. (2018): EXIOBASE 3: Developing a time series of detailed environmentally extended multi-regional input-output tables. J Ind Ecol 22(3), 502–515. https://doi.org/10.1111/jiec.12715 |
| premise | Sacchi, R. et al. (2022): PRospective EnvironMental Impact asSEment (premise). Renew Sustain Energy Rev 160, 112311. https://doi.org/10.1016/j.rser.2022.112311 |
| Flow mapping ecoinvent ↔ EF 3.1 (CC BY 4.0) | Mutel, C. and the UNEP Economy Division GLAD mapping task force (2025): ecoinvent-3.11-biosphere-EF-3.1-biosphere, version 1.0.0, randonneur_data. https://github.com/brightway-lca/randonneur_data (based on https://github.com/UNEP-Economy-Division/GLAD-ElementaryFlowResources) |
| Brightway | Mutel, C. (2017): Brightway: An open source framework for Life Cycle Assessment. J Open Source Softw 2(12), 236. https://doi.org/10.21105/joss.00236 |
| Activity Browser | Steubing, B. et al. (2020): The Activity Browser — An open source LCA software building on top of the brightway framework. Software Impacts 3, 100012. https://doi.org/10.1016/j.simpa.2019.100012 |
