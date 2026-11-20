# Bundled sector and region matching (ecoinvent and BAFU → EXIOBASE)

`ecoinvent-exiobase.json` gives LCA Wrench the proxy sector of a process dataset in EXIOBASE ("Other database" with an
input-output table, `lca_wrench/sectors.py`).

- `isic_to_exiobase`: ISIC rev.4 class (4 digits, as in ecoinvent's classification "ISIC rev.4 ecoinvent") → EXIOBASE
  industry codes
- `exiobase_sectors`: EXIOBASE industry code → name (industry table, ixi)
- `exiobase_products`: EXIOBASE product code → name (product table, pxp)
- `industry_products`: industry → its products (the same code, and the industries with several products: coal
  mining, coke ovens, refineries, gas works, natural gas, chemicals nec with the biofuels)
- `exiobase_regions`: EXIOBASE region code → name
- `location_to_regions`: ecoinvent location → EXIOBASE regions (several for a location covering several, e.g. GLO, RER)

Sources:

- Sector matching (S3) and region matching (S2): Peng, S. & Pfister, S. (2023): Regionalizing the supply chain in
  process life cycle inventory with multiregional input-output data: an implementation for ecoinvent with EXIOBASE.
  Journal of Industrial Ecology, supporting information, between ecoinvent 3.7.1 and EXIOBASE 3.8.1. Code and
  matching: https://github.com/ecological-systems-design/regionalize_lcidb_with_mrio (BSD 3-Clause).
- EXIOBASE 3 industry and product codes and names: Stadler, K. et al. (2018), EXIOBASE 3, J Ind Ecol 22(3), 502–515,
  as in the EXIOBASE files (listed in pymrio, `mrio_models/exio3_ixi` and `exio3_pxp`).

Changes: converted to JSON. Peng & Pfister's industry codes for chemicals and waste follow another numbering
(i24.1 … i24.4, i90.3 … i90.6); they were converted to the codes of the EXIOBASE files (i24.a … i24.d, i90.2 … i90.5)
by name. The industry → product list is LCA Wrench's, from the codes. The file holds classification codes, location
codes and names only, no LCA data.

The rules for datasets without ISIC class (BAFU) are in `lca_wrench/sectors.py` (`RULES`, `FIELDS`), written for LCA
Wrench.
