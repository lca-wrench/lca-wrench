"""Build lca_wrench/data/regions/gdp.json: GDP by country from the World Bank (CC BY 4.0).

    python scripts/build_gdp.py                    # download from the World Bank API
    python scripts/build_gdp.py --from gdp.json    # or read a file the API gave earlier

GDP (current US$), indicator NY.GDP.MKTP.CD of the World Development Indicators, for every country of LCA Wrench's
region lists (lca_wrench/regions.py) and of the bundled region matching (data/sectors). The year is TARGET; a country
without a value then gets the nearest year with one (the earlier of two equally near). LCA Wrench uses it to share
the output of an EXIOBASE rest-of-world region among its countries (sectors.OutputWeights).
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lca_wrench import regions, sectors  # noqa: E402

TARGET = 2022
URL = ("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD"
       f"?format=json&date={TARGET - 10}:{TARGET + 1}&per_page=20000")
OUT = ROOT / "lca_wrench" / "data" / "regions" / "gdp.json"


def main() -> None:
    if "--from" in sys.argv:
        raw = json.loads(Path(sys.argv[sys.argv.index("--from") + 1]).read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(URL, timeout=120) as r:  # noqa: S310 - a fixed https URL
            raw = json.loads(r.read())
    wanted = regions.all_countries() | {k for k in sectors.data()["location_to_regions"] if regions.is_country(k)}
    by_country: dict[str, dict[int, float]] = {}
    for rec in raw[1]:
        code = (rec.get("country") or {}).get("id")
        if code in wanted and isinstance(rec.get("value"), (int, float)) and rec["value"] > 0:
            by_country.setdefault(code, {})[int(rec["date"])] = float(rec["value"])
    countries = {}
    for code, years in sorted(by_country.items()):
        year = min(years, key=lambda y: (abs(y - TARGET), y))
        countries[code] = {"gdp": round(years[year]), "year": year}
    missing = sorted(wanted - set(countries))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "World Bank, World Development Indicators: GDP (current US$), NY.GDP.MKTP.CD",
        "licence": "CC BY 4.0", "url": "https://data.worldbank.org/indicator/NY.GDP.MKTP.CD", "year": TARGET,
        "retrieved": datetime.date.today().isoformat(), "unit": "US$", "countries": countries,
        "missing": missing}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(countries)} countries, {sum(1 for c in countries.values() if c['year'] != TARGET)} from another year; "
          f"none for {', '.join(missing) or '-'}")


if __name__ == "__main__":
    main()
