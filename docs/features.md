# Features

## Parameters and formulas

As in the Activity Browser, parameters are named values (number or formula), and amounts in your own models can have a
formula instead of a number (ƒ next to the amount in the data sheet). There are three scopes; the narrower one wins:
activity, then model, then project. They are stored in Brightway's tables (`ProjectParameter`, `DatabaseParameter`,
`ActivityParameter`, `ParameterizedExchange`, groups `model:code` as in bw2io and the Activity Browser); the formulas of
amounts are also stored in the exchange (`formula`, `original_amount`). The Activity Browser therefore sees the same
parameters.

Every change is first checked in memory (unknown names, syntax, cycles, result not a finite number); only then does
LCA Wrench write and recalculate. Only the project and your own models are recalculated, never parameters of the
background data. Renaming and deleting work only as long as no formula uses the name. Every step is in the history and can
be undone; a deleted activity comes back with its parameters. Excel export and import carry parameters and formulas.
Tested in `tests/test_params.py` and in the browser.

Limits: Monte Carlo does not sample uncertainty of parameters (only of the amounts themselves); dependencies between
activity groups (Brightway `Group.order`) are not managed.

## Excel: exchanging your own models

In "Model" (model chosen on the left): **Export Excel** downloads the model as `.xlsx` in the format of bw2io
(`write_lci_excel`), which the Activity Browser also understands via "Import, Excel". **Import Excel** reads such files as
a new model (bw2io `ExcelImporter`). If even one exchange finds no partner, nothing is imported; the message names the
first cases. If the model name already exists, the new model is called "… (Import)". The import appears in the undo
history.

**Linking.** bw2io writes only name, unit, location and category of the partner for each exchange. That is not unique
when a background activity was copied into the model (same name) or when an activity in ecoinvent has several products.
The export therefore also writes the partner's database (a column bw2io already knows) and reference product. The
import links such exchanges exactly: activities by name, reference product, unit, location and database; emissions by
name, unit, category and database. If a database has a different name in the target project, the reference product
still counts. Files without these columns (Activity Browser, older exports) are linked as before: activities by name,
unit, location (and categories), emissions by name, unit, category, references within the model by name. If an exchange
matches several datasets there, the import stops with a message naming these exchanges.

**Parameters.** Project, model and activity parameters and the formulas of the amounts are carried over (bw2io sections
"Project parameters", "Database parameters", "Parameters"). The import checks them in memory first; if they cannot be
calculated, nothing is created. The groups of the activity parameters are named after the new model (the file carries
the old name, which would conflict with the original in the same project). Project parameters that already exist keep
their value; the message names them. Undo removes the model and the project parameters it brought, unless something else
uses them.

Limits: only the bw2io layout (one sheet per database), at most 25 MB; comments of the activities are carried over,
uncertainty information of the exchanges is not checked. Tested in `tests/test_excel.py` (round trip of the example
model, random background activities as inputs, a background activity copied into the model next to the original,
activities with the same name and different products, files without the new columns, ambiguous and unlinkable files,
broken files, parameters and formulas, API) and in the browser.

## Why different? (working copy against original)

In a working copy with changes, the result shows the tab "Why different?": the difference between copy and original,
split onto the individual changed exchanges, as a list with contribution and share. The split is exact:

```text
h1 − h0 = − s0 · ΔA · x1  +  c0 · ΔB · x1        s0 = c0 B0 A0⁻¹ (unit scores of the original), x1 = scaling in the copy
```

Each changed exchange is an entry of ΔA (input) or ΔB (emission) and gives exactly one term. The other changes are already
contained in x1: a contribution therefore holds "with all other changes included". ΔA is read from the two matrices,
not from the typed amounts, because Brightway stores matrix values in float32. What the list does not explain (changes
outside the app) is shown as "Not explained". Tested in `tests/test_why.py` against two independent bw2calc calculations
(original and copy) and in the browser. Open: comparing two different products with a common origin is not implemented.

## Comparing versions (for example ecoinvent 3.10 against 3.11)

In the result of a background product, tab "Versions": choose the project and database of the other version (another
project or a second database in the same project), "Compare". LCA Wrench looks for the same product there (same code,
otherwise same name, product, location, unit) and splits the difference exactly (`lca_wrench/versions.py`):

```text
h1 − h0 = Σ_j (c0·ΔB_j − s0·ΔA_j)·x1_j  +  Σ_k Δc_k·g1_k  +  s0·(f1 − f0)
s0 = c0 B0 A0⁻¹ (unit scores of the old version), x1 = A1⁻¹ f1, g1 = B1 x1 (new version)
```

Both supply chains (everything the product reaches) are put on a common index; datasets are matched by their code
(ecoinvent keeps its UUIDs across versions), otherwise by name, reference product, location and unit; the databases of
the comparison count as the same, others (for example a shared biosphere) by their name. A dataset that only one
version has gets an empty placeholder in the other (produces itself, needs and emits nothing). Column j is a dataset: its
part is what its changed inputs, outputs and emissions cause, valued with the unit scores of the old version and used
as often as the new version uses it. New datasets carry their whole impact; removed ones show up at the datasets that
used them. Δc are changed characterization factors (flows by code, otherwise name, compartment, unit). Clicking a
dataset shows its individual changed exchanges (old, new, contribution).

Tested in `tests/test_versions.py`: version 2 as a copy of the test project with a changed amount, emission, removed
exchange, new dataset and changed factor; the parts are compared with two independent bw2calc calculations; matching by
code and by name; API. Limits: only background products (not your own models); Activity Browser 2 projects only as a
copy (see [data.md](data.md)).

## Other database (the same product with another background database)

In the result, tab "Other database": the same product, calculated once with the background data of this project (for
example BAFU 2026) and once with another background database (for example ecoinvent). The other database can be in
another project or in the same one ("Project with the other data"). Code: `lca_wrench/crosswalk.py`; interface:
`lca_wrench/static/js/views/crosswalk.js`.

What the product needs is fixed by the model and stays the same on both sides. With x the supply in this project:

```text
d = f_b − A_bf x_f      amount of each background product the model takes directly
g = B_f x_f             direct emissions of the model's own activities

h_A = s_A · d + c_A · g                                   (the normal result)
h_B = Σ_i d_i k_i s_B(m(i)) + Σ_f g_f c_B(m(f))
```

m maps each background dataset to its counterpart in the other database, and k converts its unit. For a product of the
background itself, d is just that product.

- **Datasets:** every background dataset the product uses directly gets a counterpart, in this order: (1) a choice the
  user made or loaded from a mapping file; (2) the same code in the other database (the same database twice, or versions
  that keep their codes); (3) the same name, reference product, location and unit (a premise scenario gives its
  datasets new codes), shown as "same name, location and unit" and counted as sure; (4) a suggestion from name,
  reference product, location and unit. The user confirms
  suggestions ("Confirm suggestion", "Confirm good suggestions (n)") or changes them ("Change", search in the other
  database). "No counterpart" counts as zero on the other side; the share of the result here that such datasets carry is
  shown, as is the share of unsure suggestions.
- **Units:** converted where both units measure the same thing (mass, energy, volume, freight, area, time …); otherwise
  the match is marked "Unit does not fit".
- **Scenarios and EXIOBASE on the other side:** the datasets there are scored on their own database when the
  calculation does not include it (a premise scenario or EXIOBASE is only part of it once chosen under Start).
- **EXIOBASE (proxy sectors):** an input-output table has no dataset of the same name. Each dataset gets the industry
  its activity belongs to, or that industry's product, in the region of its location (`lca_wrench/sectors.py`). Both
  tables work: industry by industry (163 industries) and product by product (200 products), recognised by their
  names. The industry, in this order:
  1. **ISIC** (ecoinvent): the dataset's ISIC rev.4 class through the sector matching of Peng & Pfister (2023),
     coarsened to 3 and 2 digits where a class is not listed;
  2. **name rules**: words of the name and reference product, with BAFU 2025's EcoSpold01 category and BAFU 2026's
     sector ("Electricity, hydropower, at power plant" → electricity by hydro, "Diesel, at regional storage" →
     petroleum refinery, "Transport, freight, lorry …" → other land transport). With ISIC candidates a rule only
     narrows them ("market for electricity, low voltage" → distribution and trade of electricity);
  3. **category or sector alone** (BAFU "chemicals" → the chemical industries), marked unsure;
  4. **words only**: the industries sharing most words with the name, marked unsure.

  Several candidates are ranked by the words they share with the dataset; among equals the "nec" industry comes first
  (ISIC 2011 → chemicals nec). In the product table each industry stands for its products, the one the name points to
  first ("Heavy fuel oil" → Heavy Fuel Oil, "Petrol" → Motor Gasoline), else its main product. Region: the region
  matching of Peng & Pfister (2023); a location covering several regions (GLO, RER, RoW) takes the one with the largest
  production of the sector. Checked on all datasets of BAFU 2025 (90 % by name rules, the rest by category), BAFU 2026
  (90 % by name rules) and ecoinvent 3.9.1 (by ISIC), and against the EXIOBASE 3.8.2 tables of 2022 (all 163
  industry and 200 product names recognised).

  The amount is converted into million euro with the price of the product: ecoinvent's property "price" (EUR 2005, not
  deflated to the table's year) or a price typed in under "Change" ("Use with this price"); without one, the sector is
  shown with "Price missing" and counts as zero. BAFU datasets have no price, so each needs one typed in. The tables are
  in `lca_wrench/data/sectors`.
- **Direct emissions** of the model's own activities: same code, otherwise the same name and compartment after
  normalizing the spelling ("Carbon dioxide, fossil" in "emissions to air" = "Carbon Dioxide (fossil)" in
  "Emissions / Emissions to air").
- **Methods:** the same method, otherwise the same EF 3.x category (sentier's "Climate change-Biogenic" = ecoinvent's
  "climate change: biogenic"); otherwise chosen by hand ("Method there"). Methods with different units are not compared.
- **Saved and shared:** confirmed matches are kept in `lca-wrench.json` per pair of databases. "Export matches (JSON)"
  and "Load matches (JSON)" use randonneur JSON in the format of
  [sentier-mappings](https://github.com/sentier-dev/sentier-mappings): "replace" entries from a source code to a target
  `{database, code}`. Targets in ecoinvent are written by code only, never with name, amounts or flows, and marked
  `target_proprietary: true`, because ecoinvent is licensed. sentier-mappings has bridges from BAFU 2026 to the EF 3.1
  flows (used by sentier-brightway), but no bridge from BAFU to ecoinvent processes.
- **Largest differences:** the second view of the tab splits the difference exactly into one part per dataset,
  d_i (k_i s_B(m(i)) − s_A(i)), plus one for the direct emissions (a dataset without counterpart counts with minus its
  score here). Ranked by size, with each part's share of the difference, the running total and the ratio "there / here"
  per unit: these are the datasets the result is most sensitive to, so their matches are the ones to check first
  ("Check match" jumps to them). Parts can offset each other; their shares add up to 100 %.
- **Down the supply chain:** ▸ on a matched dataset splits its part again by its own inputs. Each input here is paired
  with an input of the counterpart there: a saved match, the same dataset or code, else the best name match among the
  counterpart's inputs (same scoring as the suggestions, unit must convert). From the technosphere column,
  s_c = Σ (−A_rc / A_cc) s_r + direct_c / A_cc, so the parts (pairs, inputs only here or only there, own emissions) add up
  to the pair's part. Every pair opens further, level by level.
- **API:** `GET /api/crosswalk/targets`, `POST /api/crosswalk` (compare), `POST /api/crosswalk/trace` (one level down),
  `POST /api/crosswalk/search`, `POST /api/crosswalk/choose`, `POST /api/crosswalk/confirm`,
  `GET /api/crosswalk/export`, `POST /api/crosswalk/import`.

Tested in `tests/test_crosswalk.py` (a model on the BAFU data of the test project, calculated against a small
ecoinvent-shaped database in another project): side A equals the normal result; side B equals a hand calculation from
the matched datasets, the unit conversion and the direct emissions; suggestions, the user's choice, "No counterpart"
and going back; export in the format of sentier-mappings (ecoinvent by code only) and loading it again; the same
database twice gives the same result; method and unit matching; API. The first calculation against another database
prepares it, which takes some time. `tests/test_backgrounds.py`: a premise-like scenario outside the calculation is
scored on its own data (also one level down); EXIOBASE proxy sectors by ISIC class and region, the price from the
dataset and typed in, and its export as a conversion factor; both tables (industries and products, with EXIOBASE's
names) for datasets with ISIC class (ecoinvent), with a category (BAFU 2025) and with a sector only (BAFU 2026).

## Several products and allocation

A process with several products (milk and meat from one farm, boards and chips from one sawmill) is stored as the
[Activity Browser 3](https://github.com/LCA-ActivityBrowser/activity-browser) stores it, with
[bw_functional](https://github.com/LCA-ActivityBrowser/bw-functional) (database backend `functional_sqlite`): the
process and each of its products are nodes of their own. A product names its process (`processor`), carries
properties per unit of product (mass, price …; with `normalize`, multiplied by the amount produced) and the share of
the process's inputs and emissions it bears (`allocation_factor`). The process says how the shares are found
(`allocation`): in equal parts, by a property all its products have, or by hand. Code: `lca_wrench/functional.py`,
the engine in `lca_wrench/engine.py` (`Foreground`).

- **Calculation:** every input, emission and credit of the process is split onto its products by their shares; each
  product's own production goes to its own column. This is what bw_functional does when it prepares the database for
  bw2calc, and the tests check that both give the same result. A process with one product stands for that product; a
  process with several asks which product to calculate. Shares that do not add up to 1 are calculated as given (as
  bw_functional does) and noted at the process.
- **Data sheet of the process:** the card "Products and allocation" lists the products with their amount (editable in
  own models), share and impact per unit, and the allocation in use. Changing it (in equal parts, by a property, by
  hand) recalculates at once and is a step in the history that can be undone. By hand, the shares typed in are scaled
  to add up to 100 %. When the allocation uses a property per unit (price), changing a product's amount moves the
  shares (revenue = price × amount).
- **Data sheet of a product:** the process's inputs and emissions, scaled by the product's share, and its result.
  The amounts are changed in the process ("Open activity").
- **Compare allocations:** every way the process can be split, side by side: the impact per unit of each product, with
  its share. Nothing is saved; only the models are recalculated with those shares, the background stays as it is.
  Choosing an allocation is a modelling choice, so the spread belongs in the result.
- **Own models only:** as everywhere, LCA Wrench changes only models made in it, or anything in a working copy.
  Databases made in the Activity Browser 3 are calculated live and changed only in a copy of the project.
- **bw_functional** is loaded without one part: when a project is opened, it brings the project's databases to its
  current data structure and writes a version mark into the project. LCA Wrench does not change projects without being
  asked, so this update runs only right before LCA Wrench itself writes into such a database.
- **Building such models in LCA Wrench:** there is no format to choose when a model is made. Every process of an own
  model has "+ Product" on its data sheet, with a note on what a co-product does. The first co-product in a classic
  model stores the whole model as the Activity Browser 3 stores it, in place: each process gets its product as a node
  of its own (name and unit of its reference product), and process ids, exchange ids, parameters and formulas,
  uncertainties, inputs from other models and calculation setups stay (inputs and setups now name the product). The
  allocation starts in equal parts. "Undo" stores the model in the classic format again. A model with a process that
  has several production exchanges, or one naming another dataset, is refused with a message. Afterwards the model
  needs bw_functional to be read, as in the Activity Browser 3.
- **Allocation only from two products:** the card "Products and allocation" appears once a process has a second
  product, with a note on ISO 14044: avoid allocation where possible, by splitting the process or by crediting the
  co-product for what it replaces (system expansion, LCA Wrench's credits); otherwise split by a physical relationship
  (mass, energy), only then by price; "Compare allocations" shows how much the choice moves the result.
- **Products and properties:** "+ Product" adds more products, each with its amount and unit, and × removes one again
  (not the last, and not while another process uses it). "+ Property" gives every product of the process a property
  (price, mass …, per unit of product, 1 until set); its values are typed into the table, and the allocation can then
  use it. A property the allocation uses cannot be removed. Every step can be undone; deleting a process deletes its
  products with it, and undo brings both back. (The API can also make a model in this format from the start:
  `several_products` in `POST /api/models/db`.)
- **Inputs:** a process of this format is an input only through one of its products: choosing a process with several
  products as input is refused, one with a single product stands for that product.
- **Copying:** a dataset of BAFU or ecoinvent copied into such a model becomes a process with one product (with all
  inputs and emissions); a process of such a model is copied with all its products, their properties and its
  allocation. A product copied into a classic model becomes one dataset with its share of the process (every input
  and emission times its allocation factor). LCA Wrench copies these itself: bw_functional 0.1.1's own copy of a
  process deletes the original's products.
- **Not yet:** storing a model back in the classic format other than by undo, Excel exchange and "Move to another
  region" for such models (both refuse with a message), system expansion in bw_functional's terms (LCA Wrench's
  credits remain the way to substitute), and the Circular Footprint Formula of PEF.

Tested in `tests/test_multifunctional.py`: a dairy farm (8 kg milk, 1 kg meat, 9 kg CO2 per run) and cheese made from
its milk, by hand calculation; the same farm written by bw_functional as the Activity Browser 3 writes it, with LCA
Wrench's results equal to bw2calc's on bw_functional's processing for allocation by price, by mass, by hand and after
a changed amount; the data sheets, undo and the comparison; the farm built step by step in LCA Wrench (new model,
process, second product, price property, allocation, inputs, removing and restoring a product, copies both ways,
deleting the process and undoing it), again equal to bw2calc; and a classic model with a parameter formula, an input
from another model and a calculation setup, stored in this format by its first co-product and back by undo, with the
same ids and formulas and results equal to bw2calc both ways.

## Search

Type English words; a location and a unit group narrow the result:

- **Location** as code or name ("CH", "Switzerland", "Schweiz", "Europe"), in the field or at the end of the search
  ("electricity low voltage germany"). Activities from the regions around it follow, nearest first: a country, then the
  European grids and regions (ENTSO-E, UCTE, RER …), then GLO and RoW. Each activity appears once, with the nearest
  location it has; a stand-in is marked "in place of CH".
- **Unit group** ("Energy (kWh, MJ)", "Mass", "Freight (tkm)" …), or the unit at the end of the search ("heat MJ"):
  energy leaves out power plants and grids, which are counted in units.
- **Order:** activities whose name holds all words come first (the words in a row at the start of the name before the
  rest, names with fewer other words before longer ones), BAFU's obsolete datasets ("xxx …") last; then the search
  engine's order. As in the Activity Browser 3, the words as typed count before the fuzzy hits.
- **Typos** ("steeel", "carbn dioxde") are corrected: the hits for the closest known word follow, marked as such.
- **Databases:** "All databases" means the models, the background databases of the calculation (Start, "Background data
  for calculating") and every input-output table (EXIOBASE), also when the calculation does not use it yet: its sectors
  in money repeat no process data, and a model has to find them to buy them (hybrid LCA). Other databases, for example
  a premise scenario not chosen, are searched by name in the database list.

The same search, with location and unit fields, picks inputs in a model and products in Calculate. Emissions and
resources are searched the same way, with a unit field (mass, volume, land use, radioactivity …) and a compartment field
(air, water, soil, resources; also as the last word: "nitrate soil"). Formulas and German names find the flows too:
"CO2", "PM2.5", "NOx", "SO2", "Lachgas", "Feinstaub"; flows without a sub-compartment come first.

## Moving a model to another region

In "Model", "Move to another region …" makes a copy of the model (or of all your models) whose background inputs come
from another country: "Electricity only" swaps the grid mix, "All inputs that exist there" every input that the data
have in a nearer location. Each input is looked up under the same name, product and unit; if the country has none, the
nearest region (DE → ENTSO-E/UCTE/RER → GLO). "Preview" lists every switch and the inputs without a counterpart, which
stay as they are. The copy is called "Model [DE]", its activities get the new location; the original stays. Models with
parameters cannot be moved yet. Suppliers are swapped by name only, not consumption mixes or imports.

## Sankey definition

A bar in the Sankey shows either the sum up to that activity (everything that passes through it, with its whole supply
chain) or, with "Own contribution", only the activity's direct emissions, which over all activities add up to the
result. Each activity appears once. This differs by definition from the Activity Browser's Sankey, where a box shows
the largest single path to the activity. See [../COMPARISON.md](../COMPARISON.md).

## Language

The interface is in English by default. "Deutsch" at the top right switches the whole interface to German ("English"
switches back); the choice is remembered in the browser. `LCA_WRENCH_LANG=de` makes German the default of the local
process. German is the source: the German text is the key, and the English translations are in `lca_wrench/i18n.py`
(server messages) and `lca_wrench/static/js/i18n.js` (interface); see [../CONTRIBUTING.md](../CONTRIBUTING.md). The
interface sends the language with every request (`X-Lang`). Stored texts such as the history are translated when read;
older entries stay German. Terms as in the Activity Browser: activity, exchange, reference flow, calculation setup,
working copy. Data (names of activities, methods, the example model) is not translated. The page loads its files under
`/ui/<version>/` (an identifier from modification time and size of all files), and the page itself is never cached, so
after an update the browser does not mix old and new JavaScript modules.

## Flows without a characterization factor

In Result, Inventory, each inventory flow shows whether the selected method has a factor for it: characterized,
characterized (flow mapping), characterized (completed) or not characterized. A filter shows only the not characterized
flows, ranked first those whose name has a factor in another sub-compartment of the same compartment, together with an
estimate (amount × that factor), clearly labelled as an estimate. A notice above the result gives the counts. The same
columns are in the Excel and CSV export. Details: [completed-factors.md](completed-factors.md).

## Completed factors

Some method implementations (the Ecological Scarcity 2021 methods of the Brightway template BAFU-2025-v2) carry most
factors only on the flow without sub-compartment. LCA Wrench completes them at calculation time: a flow without a factor
takes the factor of the flow with the same name, the same top-level compartment, no sub-compartment and the same
unit. Existing factors, including explicit zeros, are never overwritten; long-term sub-compartments are never completed;
stored methods are not modified. The completion is on by default, visibly marked in the result, and can be switched off.
The list of added factors is shown and can be exported. Details: [completed-factors.md](completed-factors.md).
