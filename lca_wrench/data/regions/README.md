# GDP by country

`gdp.json` holds the GDP of every country of LCA Wrench's region lists (`lca_wrench/regions.py`) and of the bundled
region matching (`../sectors`), in current US$, for 2022, or the nearest year where 2022 has no value (the file names
the year of each country, and lists the countries without any value).

- Source: World Bank, World Development Indicators, "GDP (current US$)", indicator NY.GDP.MKTP.CD,
  https://data.worldbank.org/indicator/NY.GDP.MKTP.CD (retrieved through the World Bank API on the date in the file)
- Licence: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
- Changes: only the countries LCA Wrench uses, one value each (the year as above), rounded to whole dollars.
- Built with `scripts/build_gdp.py`.

LCA Wrench uses it for one thing: an EXIOBASE rest-of-world region (RoW Europe, Africa, America, Asia and Pacific,
Middle East) stands for several countries, and when a region dataset's countries are weighted by EXIOBASE output
(factors by location, `docs/regional-factors.md`), the rest-of-world region's output is shared among its countries
by GDP. Suggested attribution: World Bank, World Development Indicators: GDP (current US$), CC BY 4.0.
