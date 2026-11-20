"""Write the normalization and weighting factors LCA Wrench bundles for single scores (lca_wrench/data/nw).

    python scripts/nw_factors.py <ef31_nw.csv> <Normalization scores ReCiPe 2016.xlsx>

- EF 3.1: a CSV with the 16 categories, normalisation per person and weighting in %, from the JRC EF 3.1 reference
  package (identical to tables 61 and 62 of the dairy PEFCR); columns category, unit, normalisation_per_person,
  weighting_pct.
- ReCiPe 2016: RIVM's "Normalization scores ReCiPe 2016" (world 2010, per person), sheet "Final normalization
  scores": one row per impact category, endpoint values in the columns of the Individualist, Hierarchist and
  Egalitarian perspectives. The normalization of each area of protection is the sum of its categories.
  The weighting sets are those of the Eco-indicator 99 panel, reused by ReCiPe 2008 and, for ReCiPe 2016, by SimaPro.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "lca_wrench" / "data" / "nw"

# EF 3.1 categories: the name in the factor file -> other spellings of the same category (sentier, ecoinvent)
EF_NAMES = {
    "Climate change": ["climate change"],
    "Ozone depletion": ["ozone depletion"],
    "Ionising radiation, human health": ["ionising radiation: human health", "ionizing radiation, human health"],
    "Photochemical ozone formation - human health": ["photochemical oxidant formation: human health",
                                                     "photochemical ozone formation, human health"],
    "EF-particulate Matter": ["particulate matter", "particulate matter formation", "respiratory inorganics"],
    "Human toxicity, non-cancer": ["human toxicity: non-carcinogenic", "human toxicity, non-cancer effects"],
    "Human toxicity, cancer": ["human toxicity: carcinogenic", "human toxicity, cancer effects"],
    "Acidification": ["acidification"],
    "Eutrophication, freshwater": ["eutrophication: freshwater"],
    "Eutrophication marine": ["eutrophication, marine", "eutrophication: marine"],
    "Eutrophication, terrestrial": ["eutrophication: terrestrial"],
    "Ecotoxicity, freshwater": ["ecotoxicity: freshwater"],
    "Land use": ["land use"],
    "Water use": ["water use"],
    "Resource use, fossils": ["energy resources: non-renewable", "resource use, energy carriers"],
    "Resource use, minerals and metals": ["material resources: metals/minerals"],
}

# the official EF 3.1 name where the factor file spells a category otherwise
EF_LABELS = {
    "Photochemical ozone formation - human health": "Photochemical ozone formation, human health",
    "EF-particulate Matter": "Particulate matter",
    "Eutrophication marine": "Eutrophication, marine",
}

# ReCiPe 2016: the rows of the RIVM sheet that make up each area of protection
RECIPE_AREAS = {
    "human health": ["Global Warming - Human health", "Stratospheric ozone depletion - Human health",
                     "Ionzing Radiation - Human health", "Fine particulate matter formation - Human health",
                     "Photochemical ozone formation - Human health", "Toxicity - Human health (cancer)",
                     "Toxicity - Human health (non-cancer)", "Water consumption - human health"],
    "ecosystem quality": ["Global Warming - Terrestrial ecosystems", "Photochemical ozone formation - Terrestrial ecosystems",
                          "Acidification - Terrestrial ecosystems", "Toxicity - Terrestrial ecosystems",
                          "Water consumption - terrestrial ecosystems", "Global Warming - Freshwater ecosystems",
                          "Eutrophication - Freshwater ecosystems", "Toxicity - Freshwater ecosystems",
                          "Water consumption -aquatic ecosystems", "Toxicity - Marine ecosystems",
                          "Eutrophication - marine ecosystems"],
    "natural resources": ["Mineral resource scarcity", "Fossil resource scarcity"],
}
PERSPECTIVES = {"I": 7, "H": 8, "E": 9}  # columns of the endpoint values
WEIGHTING = {  # human health, ecosystem quality, natural resources (Pt; 1000 = one person's yearly impact)
    "I/I": {"human health": 550, "ecosystem quality": 250, "natural resources": 200},
    "H/A": {"human health": 400, "ecosystem quality": 400, "natural resources": 200},
    "H/H": {"human health": 300, "ecosystem quality": 400, "natural resources": 300},
    "E/E": {"human health": 300, "ecosystem quality": 500, "natural resources": 200},
}


def ef31(path: Path) -> dict:
    cats = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            label = EF_LABELS.get(r["category"], r["category"])
            names = list(dict.fromkeys([r["category"].lower(), label.lower(), *EF_NAMES[r["category"]]]))
            cats.append({"label": label, "unit": r["unit"], "normalisation": float(r["normalisation_per_person"]),
                         "weighting": float(r["weighting_pct"]), "names": names})
    assert len(cats) == 16 and abs(sum(c["weighting"] for c in cats) - 100) < 0.01
    return {
        "source": "EF 3.1 normalisation (global, per person) and weighting factors of the JRC EF 3.1 reference package; "
                  "identical to tables 61 and 62 of the PEFCR for dairy products.",
        "single_score": "sum over the 16 categories of result / normalisation x weighting / 100, in mPt (x 1000)",
        "unit": "mPt", "scale": 1000.0, "categories": cats,
    }


def recipe2016(path: Path) -> dict:
    import openpyxl

    ws = openpyxl.load_workbook(path, data_only=True, read_only=True)["Final normalization scores"]
    rows = {str(r[0]).strip(): r for r in ws.iter_rows(values_only=True) if r and r[0]}
    norm, detail = {}, {}
    for p, col in PERSPECTIVES.items():
        norm[p] = {}
        for area, names in RECIPE_AREAS.items():
            vals = {n: float(rows[n][col] or 0.0) for n in names}
            detail.setdefault(area, {})[p] = vals
            norm[p][area] = sum(vals.values())
    return {
        "source": "Normalization: RIVM, Normalization scores ReCiPe 2016, world 2010, per person (sheet 'Final "
                  "normalization scores'); the normalization of an area of protection is the sum of its categories. "
                  "Weighting: the Eco-indicator 99 panel sets (Goedkoop & Spriensma, PRe), reused by ReCiPe 2008 and, for "
                  "ReCiPe 2016, by SimaPro (method developers published only normalization factors).",
        "single_score": "sum over the three areas of result / normalization x weight, in Pt (1000 Pt = the yearly impact "
                        "of an average world citizen)",
        "unit": "Pt",
        "areas": {"human health": {"unit": "DALY", "names": ["human health"]},
                  "ecosystem quality": {"unit": "species.yr", "names": ["ecosystem quality", "ecosystems"]},
                  "natural resources": {"unit": "USD2013", "names": ["natural resources", "resources"]}},
        "normalisation": norm,
        "normalisation_categories": detail,
        "weighting": WEIGHTING,
        "default_weighting": {"I": "I/I", "H": "H/A", "E": "E/E"},
        "notes": [
            "RIVM's table has no land use row, while ecoinvent's ReCiPe 2016 endpoint counts land use under ecosystem "
            "quality: the ecosystem normalization leaves land use out.",
            "Mineral resource scarcity makes up most of the resource normalization (27,742 of 28,033 USD2013 per person, "
            "H); its midpoint value in the same table, 120,051 kg Cu-eq per person, looks implausibly high.",
            "Water consumption, terrestrial ecosystems is 0 for the Individualist perspective in RIVM's table.",
        ],
    }


def main() -> None:
    ef_csv, recipe_xlsx = Path(sys.argv[1]), Path(sys.argv[2])
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("ef31.json", ef31(ef_csv)), ("recipe2016-endpoint.json", recipe2016(recipe_xlsx))):
        (OUT / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("written", OUT / name)


if __name__ == "__main__":
    main()
