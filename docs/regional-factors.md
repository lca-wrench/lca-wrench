# Factors by location (regionalized impact assessment)

Some impacts depend on where an emission or a resource use happens. A cubic metre of water taken in Spain deprives
other users more than one taken in Switzerland (EF 3.1 water use, AWARE: 77.7 against 1.34 m³ world eq. per m³), and a
kilogram of ammonia acidifies differently in each European country. A method with such factors gives each activity the
factor of its own location. LCA Wrench applies them in its engine; plain bw2calc uses only the global factors of a
method. Code: `lca_wrench/regional.py`, region lists in `lca_wrench/regions.py`.

## Where the factors come from

Nothing is bundled. LCA Wrench reads the factors the method itself carries, in two forms, and a file you load can add
more (3.):

1. **Rows with a location**, Brightway's own convention: a method row `(flow, factor, location)`, for example
   `(water_flow, 1.34, "CH")`. bw2data stores such rows; bw2calc filters them out and keeps the rows of the global
   location `GLO` (`consistent_global_index`), and bw2regional uses the others. The same format as bw2regional,
   so a method written for one works in the other.
2. **Country copies of a flow**: a flow with a `location` of its own whose generic flow has a factor in the same method,
   matched by code (`<code of the generic flow>_<location>`) or by name (`<name of the generic flow>, <location>`),
   with the same compartment and unit. Projects prepared for the EF 3.1 PEF method carry the JRC country factors of water
   use this way (flows "Water, AT", "Ground Water, CH", …). LCA Wrench turns them into a table (generic flow, country) →
   factor, so the generic water flows of every dataset get the factor of the dataset's country, also in data that never
   used the copies. A flow counts as a copy only if it has a location of its own: the BAFU 2025 flow list names water
   flows by country ("Water, unspecified natural origin, IE") without a location field, and they stay as they are.

3. **The JRC's EF 3.1 workbook**, loaded once from your own copy (see below).

A row with a location wins over a country copy for the same flow and place, and both win over a loaded file, which
only adds the places the method has no factor for. Rows with a spatial unit of a geocollection
(`("ecoregions", "PA0101")`, bw2regional) need the spatial data and are not used.

## Loading the EF 3.1 country factors of the JRC

The JRC publishes the EF 3.1 characterization factors as an Excel workbook, `EF-LCIAMethod_CF(EF-v3.1).xlsx`, in the
EF reference package 3.1 (EPLCA, European Platform on LCA). Its sheet `lciamethods_CF` has a factor per location for
four categories: water use (AWARE, 209 countries), land use (212 locations), acidification and terrestrial
eutrophication (36 European countries); a blank location is the default. Brightway implementations of EF 3.1 carry only
the defaults. The JRC pages do not state whether the package may be redistributed, so LCA Wrench bundles none of it.

In Result, for a method on water, land use, acidification or eutrophication, **Load country factors from the EF 3.1
file …** reads your copy (about half a minute). LCA Wrench keeps only the flows whose factor differs between locations,
in a file next to `lca-wrench.json` on this computer (`lca-wrench-regional/ef3.1.json.gz`), never in a project, and
they apply in every project. Loading a file of the same version again replaces it; **remove** next to the file's name
takes it out. Code: `lca_wrench/factor_files.py`.

A loaded table applies to a method in one of two ways:

- **By flow.** The table's flows are found by their UUID (the code of the EF 3.1 flow list, as in sentier's BAFU 2026
  and EF 3.1 PEF projects) and, through the flow mapping ([flow-mapping.md](flow-mapping.md)), as the ecoinvent flows
  (biosphere3) matched to them. The table applies when the method's factors on those flows equal the table's defaults
  (relative tolerance 1e-3, at least 90 % of the shared flows); they get the table's factors by location. That picks
  the category the table was made for and leaves every other method alone. ecoinvent's EF 3.1 acidification,
  terrestrial eutrophication and land use match this way.
- **By ratio.** Where no flow is shared, a table whose factors are the default times one ratio per location, the same
  for all its flows, fits a method of the same kind of impact whose factors are all plus or minus the table's default.
  Each of the method's flows then gets its factor times the location's ratio. EF 3.1 water use is such a table (the
  country's AWARE factor over the world's 42.95, withdrawals positive and releases negative alike), and ecoinvent's EF
  3.1 water use such a method: it counts consumption as water evaporated to air, which the mapping does not connect
  to the JRC's withdrawals and releases. The kind of impact must be named the same (water use with water use), never
  "other".

A method that fits neither keeps its normal factors; the result then says that the loaded file does not fit it.
Projects that carry country copies of the water flows for only the countries their data use get the other countries
from the file, so region averages no longer count missing countries with the default.

## Which factor an activity gets

For each flow with factors by location, the activity's location decides; the first rule that applies wins:

1. **The location's own factor.** Codes that changed are read both ways: RS and ME read CS (EF 3.1 still uses Serbia
   and Montenegro), XK reads RS or CS, CW, SX and BQ read AN, UK reads GB and EL reads GR.
2. **A part of a country** (CA-QC, US-WECC, CN-SGCC, IN-Western grid): the factor of the country.
3. **A region** (RER, RAS, RLA, ENTSO-E, UCTE, NORDEL, "Europe without Switzerland", "RER w/o CH+DE" …) without a
   factor of its own: the average over its countries, **weighted by production volume**: the production volumes of
   the datasets with the same name and product in those countries, as ecoinvent and premise record them on the
   reference product exchange. Where there are none, the countries are weighted equally. BAFU records no production
   volumes, and ecoinvent avoids datasets that overlap a region (a country with its own dataset is cut out of the
   region: "Europe without Switzerland"), so few ecoinvent region datasets have national datasets of the same product
   inside their region; the others are averaged equally. A country of the region without a factor of its own counts
   with the method's normal factor.
4. **GLO, RoW and unknown locations** keep the method's **normal factor**: the result without factors by location.
   For RoW this is the world average; BAFU uses OCE for the oceans (ships), so OCE is not taken as Oceania.

The normal factor is the one the calculation uses anyway: the method's global factor, together with the flow mapping
and the completed factors where those apply. Factors by location apply to the flows they are given for; a flow that
gets its factor through the flow mapping or the completion keeps that normal factor everywhere.

### Countries of a region

`regions.members` lists the countries of the regions ecoinvent and BAFU use, from the UN M49 geographic regions
(UN Statistics Division), sovereign states plus Taiwan, Hong Kong, Macao and Kosovo; dependent territories are left
out so that they do not weigh like countries in an equal average.

| Code | Countries |
|---|---|
| RER | M49 Europe, plus Cyprus and Turkey (ecoinvent has "Europe, without Russia and Turkey") |
| RAS, RAF, RLA, RNA | M49 Asia, Africa, Latin America and the Caribbean, Northern America (US, CA) |
| RME | Middle East: BH IR IQ IL JO KW LB OM PS QA SA SY AE YE |
| SAS, WEU, EEU | M49 Southern Asia, Western Europe, Eastern Europe |
| APAC | M49 Eastern, South-eastern and Southern Asia, and Oceania |
| CPA | Centrally Planned Asia (IEA, IIASA): CN HK KH KP LA MN MO VN |
| ENTSO-E, UCTE, NORDEL, CENTREL | Members of the grids (ENTSO-E as in ecoinvent 3, UCTE the continental area) |
| NAFTA | CA MX US |
| ASCC, ERCOT, FRCC, HICC, MRO, RFC, SERC, SPP, TRE, WECC; NPCC | US; US and CA (NERC regions) |
| UN-AFRICA, UN-AMERICAS, UN-ASIA, UN-EUROPE, UN-OCEANIA; UN-EASIA, UN-SEASIA, UN-SAMERICA … | The M49 regions and sub-regions |
| RoE | Rest of Europe, specific to each dataset like RoW: taken as Europe (RER) |
| IAI areas (aluminium) | Africa, North America, South America, EU27 & EFTA, Gulf Cooperation Council, Asia without China and GCC, Russia & RER w/o EU27 & EFTA; Russia and Eastern Europe (BY MD RU UA); Western and Central Europe (RER without those) |
| "Europe without …", "RER w/o …", "UCTE without …", "ENTSO-E without …"; "Asia without China" | The base region without the named countries or regions |

A code that is not in the table is "unknown" and keeps the normal factor.

## Where it applies

Everywhere the engine calculates: scores, unit scores, contributions by activity and by flow, the supply chain tree
and Sankey, the comparison of products, calculation setups, the data sheet of an activity (its emissions with the
factors of its location), "Why different?", the comparison of versions (a dataset that moved to another place shows
the change of its factor as part of its contribution), "Other database" (on this side the factor each flow gets on
average over the model's processes; the model's own emissions on the other side still use the normal factors of the
method there), the cross-check with bw2calc and Monte Carlo. In Monte Carlo the factors by location are fixed values;
elsewhere the method's sampled factor applies.

The engine keeps a matrix R of the shape of the biosphere matrix B, R = (factor at the activity's place − normal
factor) × B, so the characterized biosphere matrix is diag(c) B + R and the direct impacts are Bᵀc + 1ᵀR. A method
without factors by location has no R, and every number stays exactly what it was before.

## In the interface

- **Result, Contributions, by location**: the impact by the location of the activities that cause it (their direct
  emissions and resource uses), with share, number of activities, and with factors by location what they change there
  and how the factor was found (factor of the location, of the country, average of the countries by production volume
  or weighted equally, normal factor). The rows add up to the score. Also in the Excel and CSV export.
- **Switch**: "Apply factors by location" above the result, shown when the method has such factors. On by default;
  it applies to all calculations (registry key `regional`).
- **Chip** "with factors by location" next to the score: how many activities use the factor of their location and by
  how much this changes the result.
- **Result, Inventory**: "Factors by location as CSV" lists every factor by location of the method: flow, location,
  factor, normal factor and whether it comes from a row with a location, a country copy or a loaded file.
- **Load country factors from the EF 3.1 file …** above the result of a method on water, land use, acidification or
  eutrophication; once loaded, the result names the file the method uses, with **remove**.

## Validation

`tests/test_regional.py` checks on the BAFU 2025 data, against an independent calculation from bw2calc's inventory
(supply and biosphere matrix, each entry with the factor of its activity's location by the rules above written out a
second time): the scores of two products to 1e-9 of the gross impact, the production volume weights on a small
database, country copies, an own model process, the data sheet, Monte Carlo draws against bw2calc with the same seed
(1e-8), the cross-check with bw2calc, and that methods without factors by location give bit-identical results with
the switch on and off and agree with bw2calc. A small workbook in the form of the JRC's checks reading, matching by
the defaults (a method with other factors gets nothing), the precedence of the method's own rows, the result against
the same independent calculation, removing the file and the API. Contributions by activity, by flow and by location add up to the score,
and the parts by location add up to the difference the factors by location make.

## Not yet

- A map of the result by location (the location picker for activities is designed separately).
- AWARE 2.0 basin factors with a point for each activity.
- RoW as the countries the sibling datasets leave out, instead of the world average.
