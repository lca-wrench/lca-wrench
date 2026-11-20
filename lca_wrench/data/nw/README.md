# Bundled normalization and weighting factors (single scores)

LCA Wrench reads these files to compute single scores (`lca_wrench/singlescore.py`, tab "Single score" in Result).
`scripts/nw_factors.py` writes them from the source tables:

    python scripts/nw_factors.py <ef31_nw.csv> "<Normalization scores ReCiPe 2016.xlsx>"

## `ef31.json`: EF 3.1

The 16 impact categories of the Environmental Footprint 3.1, each with its normalization factor (global, per person and
year) and its weighting factor in % (the weights add up to 100). The single score is

    sum over the categories of  result / normalization × weight / 100,  in mPt (× 1000)

`names` lists the spellings of each category in the method names of sentier's EF 3.1 (BAFU 2026), ecoinvent's
"EF v3.1" (with and without long-term emissions) and "EF v3.1 PEF"; the categories are matched on these names, and
their parts (for example "climate change: fossil") are left out.

Sources:

- Normalization: Andreasi Bassi, S. et al. (2023): Updated characterisation and normalisation factors for the
  Environmental Footprint 3.1 method. JRC Technical Report, Publications Office of the European Union.
- Weighting: Sala, S., Cerutti, A. K., Pant, R. (2018): Development of a weighting approach for the Environmental
  Footprint. Publications Office of the European Union. EF 3.1 keeps the weights of EF 3.0.
- The values are those of the JRC EF 3.1 reference package; checked against tables 61 and 62 of the PEFCR for dairy
  products.

## `recipe2016-endpoint.json`: ReCiPe 2016 endpoint

The three areas of protection: human health (DALY), ecosystem quality (species.yr) and natural resources (USD 2013).
For each perspective (Individualist, Hierarchist, Egalitarian) the normalization of an area is the sum of its impact
categories in RIVM's table (world 2010, per person); `normalisation_categories` keeps the rows. The single score is

    sum over the three areas of  result / normalization × weight,  in Pt (1000 Pt = the yearly impact of one person)

Weighting sets (human health / ecosystem quality / natural resources): I/I 550/250/200, H/A 400/400/200,
H/H 300/400/300, E/E 300/500/200. By default the Individualist perspective takes I/I, the Hierarchist H/A and the
Egalitarian E/E, as in SimaPro; any set can be chosen for any perspective.

Sources:

- Method: Huijbregts, M. A. J. et al. (2017): ReCiPe2016: a harmonised life cycle impact assessment method at
  midpoint and endpoint level. International Journal of Life Cycle Assessment 22, 138–147.
- Normalization: RIVM, "Normalization scores ReCiPe 2016" (spreadsheet, sheet "Final normalization scores").
- Weighting: the panel weighting of Eco-indicator 99 (Goedkoop, M. & Spriensma, R., The Eco-indicator 99, a damage
  oriented method for life cycle impact assessment, methodology report, PRé Consultants), reused by ReCiPe 2008 and,
  for ReCiPe 2016, by SimaPro. The ReCiPe 2016 developers published normalization factors only. The same sets are
  listed in Kalbar, P. P. et al. (2017): Weighting and aggregation in life cycle assessment: do present aggregated
  single scores provide correct decision support? Journal of Industrial Ecology 21, 1591–1600.

Points to check (also in `notes` in the file and in the result):

- RIVM's table has no land use row, while ecoinvent's ReCiPe 2016 endpoint counts land use under ecosystem quality. The
  normalization of ecosystem quality therefore leaves land use out, and the normalized ecosystem result comes out
  somewhat higher than it would with land use in the reference.
- Mineral resource scarcity makes up almost all of the resource normalization (27,742 of 28,033 USD 2013 per person,
  Hierarchist; fossil resources: 291). Its midpoint value in the same table, 120,051 kg Cu-eq per person, looks
  implausibly high, so the resource part of the single score may be too small. Worth comparing with another
  implementation (for example SimaPro's normalization set) before relying on it.
- Water consumption, terrestrial ecosystems is 0 for the Individualist perspective in RIVM's table.

## Ecological Scarcity 2021 (no file)

Its eco-factors already weight: the single score is the total in UBP (eco-points). LCA Wrench takes the total method of
the family where there is one (ecoinvent's "total", or LCA Wrench's derived "Umweltbelastungspunkte gesamt" for the 21
categories of the BAFU 2025 template), else the sum of the categories. Source: Federal Office for the Environment FOEN
(2021): Swiss Eco-Factors 2021 according to the Ecological Scarcity Method.

The two water categories of the BAFU template do not overlap: "Water resources, evaporated" (58 factors: withdrawals
in general, from fossil groundwater, cooling water and evaporation to air) and "Water resources, net balance" (168
factors: withdrawals by country with a positive factor, returns with a negative one) share no flow, so their sum in the
total counts no water twice. ecoinvent's Ecological Scarcity 2021 has only the evaporated water.
