# Completed factors and flows without a factor

## The finding

The Brightway template `BAFU-2025-v2` (files.brightway.dev) ships the 21 Ecological Scarcity 2021 methods (UBP). In
these methods most factors are on elementary flows **without sub-compartment**, for example "Carbon dioxide, fossil"
in `('emissions to air',)`. The inventory of the same template emits these substances mostly into sub-compartments,
for example `('emissions to air', 'high. pop.')` and `('emissions to air', 'low. pop.')`, which have no factor.
Brightway matches factors to flows exactly, so those emissions count as zero.

Example: "Global warming" has 22 factors, 19 of them on flows without sub-compartment. 1 kWh "Electricity, low
voltage, at grid" (CH) emits fossil CO2 into 'high. pop.' and 'low. pop.'; with the method as stored, its climate
impact is 0.0142 kg CO2-eq. Every calculation that uses the stored method gives this value, including plain bw2calc
and the Activity Browser, because they use the same factors. The same pattern exists in other categories, for
example "Main air pollutants and PM" (82 of 93 factors without sub-compartment).

The cause is in the method data of the template, not in a calculation. LCA Wrench does not change the stored methods;
it completes the missing factors when it calculates, shows what it added and lets you switch it off.

## The rule

A flow without a factor takes the factor of the flow with

- the same name,
- the same top-level compartment (e.g. `emissions to air`),
- no sub-compartment,
- the same unit, in the same flow list (biosphere database),

and only where the method has a non-zero factor on that flow. Never changed:

- a factor the method has, including an explicit **zero** (Ecological Scarcity 2021 sets e.g. heavy metals into
  groundwater to 0) and special cases ("Carbon dioxide, fossil" in 'stratosphere + troposphere' keeps its 3100 UBP/kg,
  not the 1000 of the flow without sub-compartment);
- **long-term** sub-compartments ('low. pop., long-term', 'groundwater, long-term', 'river, long-term'): whether
  long-term emissions count is a decision of the method. They stay without a factor and appear in the list of flows
  without a factor.

The derived "UBP total" stays the sum of its 21 categories: it gets the sum of what each category gets.

## Which methods

Only a method family that carries its factors on the flows without sub-compartment is completed. For each method,
LCA Wrench takes the sub-compartment flows (not long-term) of the substances it has a top-level factor for, and the
share of them with a factor of their own. A family whose median share is below 0.5 is completed; a family that gives
most sub-compartments a factor of its own has decided which ones count, and a sub-compartment it leaves out stays
out. ecoinvent's LCIA methods are such families: a sub-compartment they leave without a factor (emissions to
groundwater, for instance) stays without one, instead of taking the factor of the unspecified compartment.

| Family | Median share | Completed |
|---|---:|---|
| Ecological Scarcity 2021 of the BAFU-2025-v2 template (16 methods with top-level factors) | 0.01 | yes |
| The climate method derived from it (LCA Wrench) | 0.03 | yes |
| Families that characterize their sub-compartments themselves (for example ecoinvent's) | 0.5 or more | no |

Families are those of the method list (`overview.method_family`), with ecoinvent's version kept apart, so the BAFU
template and ecoinvent's Ecological Scarcity 2021 are judged separately in one project. The rule is applied in the
engine, the cross-check with bw2calc (the same added factors on both sides, so the cross-check compares like with
like in both modes) and Monte Carlo. Code: `lca_wrench/completion.py` (`sub_share`, `needs_completion`); tests:
`tests/test_completion.py`.

## In the app

- **On by default.** A result calculated with completed factors carries the marker "with N completed factors"; its
  tooltip says how much of the result they contribute. Click it to see the list.
- **Switch:** above the result, "Complete missing factors for sub-compartments". It applies to all calculations and
  is remembered (`lca-wrench.json`, key `completion`).
- **List:** Result → Inventory, filter "only completed": flow, compartment, factor, the flow it was taken from and
  the contribution. "Completed factors as CSV" exports every factor the rule gives the selected method.
- **Export:** the Excel/CSV result export has a sheet "Completed factors" when any were used.

![Result with completed factors: marker and switch above the contributions](screenshots/result.png)

![Inventory filtered to the completed factors](screenshots/completed-factors.png)

## Flows without a factor

For the selected method, Result → Inventory shows for each flow whether it is characterized (by the method itself,
through the flow mapping, or completed) or **not characterized**. Above the result a notice gives the counts ("N of M
flows have no factor; K share their name with a characterized flow"), with a link to the filtered list.

The filter "only not characterized" ranks first the flows whose name has a factor in another sub-compartment of the
same compartment. For those, the column "Estimate" is the amount times that namesake's factor: a hint where the
method may have a gap, **not a result**. The same columns are in the Excel/CSV export.

![Completion switched off: notice and the list of flows without a factor](screenshots/not-characterized.png)

## Figures

From `scripts/validate.py` on BAFU 2025 (see [validation.md](validation.md)):

| Product | Method | As stored | With completed factors | Unit |
|---|---|---:|---:|---|
| 1 kilowatt hour Electricity, low voltage, at grid, CH | Climate change (derived from UBP 2021) | 0.0142065 | 0.097055 | kg CO2-eq |
| 1 kilowatt hour Electricity, low voltage, at grid, CH | UBP total | 308.554 | 464.045 | UBP |
| 3.7 kilogram Aluminium, production mix, at plant, RER | Climate change (derived from UBP 2021) | 5.03702 | 17.6876 | kg CO2-eq |
| 3.7 kilogram Aluminium, production mix, at plant, RER | UBP total | 20824.5 | 38182.9 | UBP |
| 250 ton kilometer Transport, freight, lorry, diesel, 26t gross weight, 2006, EURO-IV, long haul, CH | Climate change (derived from UBP 2021) | 28.7765 | 35.1544 | kg CO2-eq |
| 250 ton kilometer Transport, freight, lorry, diesel, 26t gross weight, 2006, EURO-IV, long haul, CH | UBP total | 40595.9 | 59655.8 | UBP |
| 100 megajoule Heat, natural gas, at boiler condensing modulating 300kW, CH | Climate change (derived from UBP 2021) | 0.401785 | 6.96228 | kg CO2-eq |
| 100 megajoule Heat, natural gas, at boiler condensing modulating 300kW, CH | UBP total | 753.515 | 7742.09 | UBP |


Factors the rule adds per method:

| Method | Stored factors | Added |
|---|---:|---:|
| Werkbank / Klimawandel | 22 | 29 |
| Ecological Scarcity 2021 / Biotic Resources | 0 | 0 |
| Ecological Scarcity 2021 / Carcinogenic substances into air | 16 | 20 |
| Ecological Scarcity 2021 / Energy resources | 18 | 5 |
| Ecological Scarcity 2021 / Global warming | 22 | 29 |
| Ecological Scarcity 2021 / Heavy metals into air | 8 | 23 |
| Ecological Scarcity 2021 / Heavy metals into soil | 14 | 6 |
| Ecological Scarcity 2021 / Heavy metals into water | 33 | 33 |
| Ecological Scarcity 2021 / Land use | 41 | 6 |
| Ecological Scarcity 2021 / Main air pollutants and PM | 93 | 135 |
| Ecological Scarcity 2021 / Mineral resources | 103 | 2 |
| Ecological Scarcity 2021 / Noise | 0 | 0 |
| Ecological Scarcity 2021 / Ozone layer depletion | 14 | 15 |
| Ecological Scarcity 2021 / POP into water | 18 | 10 |
| Ecological Scarcity 2021 / Pesticides into soil | 245 | 0 |
| Ecological Scarcity 2021 / Radioactive substances into air | 24 | 26 |
| Ecological Scarcity 2021 / Radioactive substances into water | 30 | 17 |
| Ecological Scarcity 2021 / Radioactive waste to deposit | 2 | 0 |
| Ecological Scarcity 2021 / Waste, non radioactive | 4 | 0 |
| Ecological Scarcity 2021 / Water pollutants | 40 | 32 |
| Ecological Scarcity 2021 / Water resources, evaporated | 58 | 6 |
| Ecological Scarcity 2021 / Water resources, net balance | 168 | 28 |
