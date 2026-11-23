"""Locations for the search: free text to a location code, and the regions that contain it.

"Switzerland", "schweiz" or "CH" all become CH; the search then also accepts the regions around it, nearest first:
CH → Europe (ENTSO-E, UCTE, RER …) → GLO → RoW. ecoinvent and BAFU name the same regions differently (RER, "Europe
without Switzerland", ENTSO-E, UCTE, WEU …); all of them are listed here. RoW ("rest of the world") is specific to
each activity, so it comes last, as the generic fallback. A code this table does not know still matches exactly.
"""

from __future__ import annotations

import functools
import re

# code: (English name, German name, continent region)
COUNTRIES = {
    "CH": ("Switzerland", "Schweiz", "EU"), "DE": ("Germany", "Deutschland", "EU"), "AT": ("Austria", "Österreich", "EU"),
    "FR": ("France", "Frankreich", "EU"), "IT": ("Italy", "Italien", "EU"), "LI": ("Liechtenstein", "Liechtenstein", "EU"),
    "NL": ("Netherlands", "Niederlande", "EU"), "BE": ("Belgium", "Belgien", "EU"), "LU": ("Luxembourg", "Luxemburg", "EU"),
    "ES": ("Spain", "Spanien", "EU"), "PT": ("Portugal", "Portugal", "EU"), "GB": ("United Kingdom", "Grossbritannien", "EU"),
    "IE": ("Ireland", "Irland", "EU"), "DK": ("Denmark", "Dänemark", "EU"), "SE": ("Sweden", "Schweden", "EU"),
    "NO": ("Norway", "Norwegen", "EU"), "FI": ("Finland", "Finnland", "EU"), "IS": ("Iceland", "Island", "EU"),
    "PL": ("Poland", "Polen", "EU"), "CZ": ("Czechia", "Tschechien", "EU"), "SK": ("Slovakia", "Slowakei", "EU"),
    "HU": ("Hungary", "Ungarn", "EU"), "SI": ("Slovenia", "Slowenien", "EU"), "HR": ("Croatia", "Kroatien", "EU"),
    "RO": ("Romania", "Rumänien", "EU"), "BG": ("Bulgaria", "Bulgarien", "EU"), "GR": ("Greece", "Griechenland", "EU"),
    "EE": ("Estonia", "Estland", "EU"), "LV": ("Latvia", "Lettland", "EU"), "LT": ("Lithuania", "Litauen", "EU"),
    "RS": ("Serbia", "Serbien", "EU"), "BA": ("Bosnia and Herzegovina", "Bosnien und Herzegowina", "EU"),
    "ME": ("Montenegro", "Montenegro", "EU"), "MK": ("North Macedonia", "Nordmazedonien", "EU"),
    "AL": ("Albania", "Albanien", "EU"), "UA": ("Ukraine", "Ukraine", "EU"), "MT": ("Malta", "Malta", "EU"),
    "CY": ("Cyprus", "Zypern", "EU"), "TR": ("Turkey", "Türkei", "EU"), "RU": ("Russia", "Russland", "EU"),
    "US": ("United States", "USA", "NA"), "CA": ("Canada", "Kanada", "NA"), "MX": ("Mexico", "Mexiko", "LA"),
    "BR": ("Brazil", "Brasilien", "LA"), "AR": ("Argentina", "Argentinien", "LA"), "CL": ("Chile", "Chile", "LA"),
    "CO": ("Colombia", "Kolumbien", "LA"), "PE": ("Peru", "Peru", "LA"), "CN": ("China", "China", "AS"),
    "JP": ("Japan", "Japan", "AS"), "KR": ("South Korea", "Südkorea", "AS"), "IN": ("India", "Indien", "AS"),
    "ID": ("Indonesia", "Indonesien", "AS"), "TH": ("Thailand", "Thailand", "AS"), "VN": ("Vietnam", "Vietnam", "AS"),
    "MY": ("Malaysia", "Malaysia", "AS"), "PH": ("Philippines", "Philippinen", "AS"), "TW": ("Taiwan", "Taiwan", "AS"),
    "PK": ("Pakistan", "Pakistan", "AS"), "BD": ("Bangladesh", "Bangladesch", "AS"), "SG": ("Singapore", "Singapur", "AS"),
    "SA": ("Saudi Arabia", "Saudi-Arabien", "ME"), "AE": ("United Arab Emirates", "Vereinigte Arabische Emirate", "ME"),
    "IR": ("Iran", "Iran", "ME"), "IL": ("Israel", "Israel", "ME"), "QA": ("Qatar", "Katar", "ME"),
    "ZA": ("South Africa", "Südafrika", "AF"), "EG": ("Egypt", "Ägypten", "AF"), "NG": ("Nigeria", "Nigeria", "AF"),
    "MA": ("Morocco", "Marokko", "AF"), "KE": ("Kenya", "Kenia", "AF"), "AU": ("Australia", "Australien", "OC"),
    "NZ": ("New Zealand", "Neuseeland", "OC"),
}

# continent region: the names ecoinvent and BAFU use for it, nearest (smallest) first
REGIONS = {
    "EU": ["ENTSO-E", "ENTSO", "UCTE", "WEU", "RER w/o CH", "Europe without Switzerland", "Europe without Austria",
           "Europe, without Russia and Turkey", "RER w/o CH+DE", "RER"],
    "NA": ["RNA", "US-NPCC", "NAFTA"], "LA": ["RLA"], "AS": ["RAS"], "ME": ["RME"], "AF": ["RAF"], "OC": ["OCE"],
}
REGION_NAMES = {"europe": "RER", "europa": "RER", "global": "GLO", "world": "GLO", "welt": "GLO", "asia": "RAS",
                "asien": "RAS", "africa": "RAF", "afrika": "RAF", "north america": "RNA", "nordamerika": "RNA",
                "latin america": "RLA", "lateinamerika": "RLA", "middle east": "RME", "oceania": "OCE"}
# regions that do not contain a given country, although they are in its continent
_EXCLUDES = {"Europe without Switzerland": {"CH"}, "RER w/o CH": {"CH"}, "RER w/o CH+DE": {"CH", "DE"},
             "Europe without Austria": {"AT"}, "Europe, without Russia and Turkey": {"RU", "TR"}}
# grids that only part of Europe belongs to (UCTE/ENTSO-E: continental grid; NORDEL etc. are not listed)
_NOT_IN_UCTE = {"GB", "IE", "NO", "SE", "FI", "DK", "IS", "EE", "LV", "LT", "CY", "MT", "RU", "UA", "TR"}


def resolve(text: str | None) -> str | None:
    """A location code for free text: a code as it is ("CH", "RER", "ENTSO-E"), or a country or region name."""
    s = (text or "").strip()
    if not s:
        return None
    low = s.lower()
    if low in REGION_NAMES:
        return REGION_NAMES[low]
    for code, (en, de, _c) in COUNTRIES.items():
        if low in (en.lower(), de.lower(), code.lower()):
            return code
    for code, (en, de, _c) in COUNTRIES.items():  # a name started ("switz", "deutsch")
        if len(low) >= 4 and (en.lower().startswith(low) or de.lower().startswith(low)):
            return code
    return s.upper() if re.fullmatch(r"[A-Za-z]{2,3}", s) else s


def chain(code: str | None) -> list[str]:
    """The code and the regions containing it, nearest first, ending with GLO and RoW."""
    if not code:
        return []
    out = [code]
    cont = COUNTRIES.get(code, (None, None, None))[2]
    if cont is None:  # a region: itself, then the world
        for c, names in REGIONS.items():
            if code in names:
                out += names[names.index(code) + 1:]
    else:
        for r in REGIONS.get(cont, []):
            if code in _EXCLUDES.get(r, ()):
                continue
            if r in ("UCTE", "ENTSO", "WEU") and code in _NOT_IN_UCTE:
                continue
            out.append(r)
    for g in ("GLO", "RoW"):
        if g not in out:
            out.append(g)
    return out


def label(code: str | None) -> str:
    c = COUNTRIES.get(code or "")
    return f"{code} ({c[0]})" if c else (code or "")


def name(code: str | None) -> str | None:
    """The country's name in the reader's language; None for codes this table does not name."""
    from . import i18n

    c = COUNTRIES.get(code or "")
    return (c[1] if i18n.LANG.get() == "de" else c[0]) if c else None


# ---------- the countries of a region (location-dependent characterization factors, regional.py) ----------

# UN M49 geographic regions (UN Statistics Division, "Standard country or area codes for statistical use"): sovereign
# states, plus Taiwan, Hong Kong, Macao and Kosovo, which have data of their own. Dependent territories are left out:
# in an equal-weighted average over a region they would count as much as a large country.
_M49 = {
    "Northern Africa": "DZ EG LY MA SD TN",
    "Eastern Africa": "BI KM DJ ER ET KE MG MW MU MZ RW SC SO SS UG TZ ZM ZW",
    "Middle Africa": "AO CM CF TD CG CD GQ GA ST",
    "Southern Africa": "BW SZ LS NA ZA",
    "Western Africa": "BJ BF CV CI GM GH GN GW LR ML MR NE NG SN SL TG",
    "Caribbean": "AG BS BB CU DM DO GD HT JM KN LC VC TT",
    "Central America": "BZ CR SV GT HN MX NI PA",
    "South America": "AR BO BR CL CO EC GY PY PE SR UY VE",
    "Northern America": "CA US",
    "Central Asia": "KZ KG TJ TM UZ",
    "Eastern Asia": "CN JP KP KR MN TW HK MO",
    "South-eastern Asia": "BN KH ID LA MY MM PH SG TH TL VN",
    "Southern Asia": "AF BD BT IN IR MV NP PK LK",
    "Western Asia": "AM AZ BH CY GE IQ IL JO KW LB OM QA SA PS SY TR AE YE",
    "Eastern Europe": "BY BG CZ HU PL MD RO RU SK UA",
    "Northern Europe": "DK EE FI IS IE LV LT NO SE GB",
    "Southern Europe": "AL AD BA HR GR IT MT ME MK PT SM RS SI ES VA XK",
    "Western Europe": "AT BE FR DE LI LU MC NL CH",
    "Australia and New Zealand": "AU NZ",
    "Melanesia": "FJ PG SB VU",
    "Micronesia": "KI MH FM NR PW",
    "Polynesia": "WS TO TV",
}


def _m49(*names: str) -> frozenset[str]:
    return frozenset(c for n in names for c in _M49[n].split())


_AFRICA = _m49("Northern Africa", "Eastern Africa", "Middle Africa", "Southern Africa", "Western Africa")
_LATIN_AMERICA = _m49("Caribbean", "Central America", "South America")
_ASIA = _m49("Central Asia", "Eastern Asia", "South-eastern Asia", "Southern Asia", "Western Asia")
_EUROPE = _m49("Eastern Europe", "Northern Europe", "Southern Europe", "Western Europe")
_OCEANIA = _m49("Australia and New Zealand", "Melanesia", "Micronesia", "Polynesia")
_EU27 = frozenset("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
_EFTA = frozenset("CH IS LI NO".split())
_GCC = frozenset("BH KW OM QA SA AE".split())
# ecoinvent's Europe also holds Cyprus and Turkey (it has a region "Europe, without Russia and Turkey")
_RER = _EUROPE | {"CY", "TR"}
# electricity grids: ENTSO-E members (as in ecoinvent 3), the former continental UCTE area, the Nordic and central
# European grids; the North American NERC regions by the country that holds most of them
_ENTSOE = frozenset("AL AT BA BE BG CH CY CZ DE DK EE ES FI FR GB GR HR HU IE IS IT LT LU LV ME MK NL NO PL PT RO RS SE "
                    "SI SK".split())
_UCTE = frozenset("AL AT BA BE BG CH CZ DE ES FR GR HR HU IT LU ME MK NL PL PT RO RS SI SK".split())
_NERC = {"ASCC": "US", "ERCOT": "US", "FRCC": "US", "HICC": "US", "MRO": "US", "NPCC": "US CA", "RFC": "US",
         "SERC": "US", "SPP": "US", "TRE": "US", "WECC": "US"}

MEMBERS: dict[str, frozenset[str]] = {
    "RER": _RER, "RAS": _ASIA, "RAF": _AFRICA, "RLA": _LATIN_AMERICA, "RNA": _m49("Northern America"),
    "RME": frozenset("BH IR IQ IL JO KW LB OM PS QA SA SY AE YE".split()),
    "SAS": _m49("Southern Asia"), "WEU": _m49("Western Europe"), "EEU": _m49("Eastern Europe"),
    "APAC": _m49("Eastern Asia", "South-eastern Asia", "Southern Asia", "Australia and New Zealand", "Melanesia",
                 "Micronesia", "Polynesia"),
    "CPA": frozenset("CN HK KH KP LA MN MO VN".split()),  # Centrally Planned Asia (IEA, IIASA)
    "ENTSO-E": _ENTSOE, "ENTSO": _ENTSOE, "UCTE": _UCTE, "NORDEL": frozenset("DK FI IS NO SE".split()),
    "CENTREL": frozenset("CZ HU PL SK".split()), "NAFTA": frozenset("CA MX US".split()),
    "UN-AFRICA": _AFRICA, "UN-AMERICAS": _LATIN_AMERICA | _m49("Northern America"), "UN-ASIA": _ASIA,
    "UN-EUROPE": _EUROPE, "UN-OCEANIA": _OCEANIA,
    **{"UN-" + k: _m49(v) for k, v in {
        "NAFRICA": "Northern Africa", "EAFRICA": "Eastern Africa", "MAFRICA": "Middle Africa", "SAFRICA": "Southern Africa",
        "WAFRICA": "Western Africa", "CARIBBEAN": "Caribbean", "CAMERICA": "Central America", "SAMERICA": "South America",
        "NAMERICA": "Northern America", "CASIA": "Central Asia", "EASIA": "Eastern Asia", "SEASIA": "South-eastern Asia",
        "SASIA": "Southern Asia", "WASIA": "Western Asia", "EEUROPE": "Eastern Europe", "NEUROPE": "Northern Europe",
        "SEUROPE": "Southern Europe", "WEUROPE": "Western Europe", "AUSTRALIANZ": "Australia and New Zealand",
        "MELANESIA": "Melanesia", "MICRONESIA": "Micronesia", "POLYNESIA": "Polynesia"}.items()},
    "RoE": _RER,  # rest of Europe: specific to each dataset, like RoW; taken as Europe
    "Asia without China": _ASIA - {"CN"}, "Russia (Asia)": frozenset({"RU"}),
    "IAI Area, Africa": _AFRICA, "IAI Area, North America": _m49("Northern America"),
    "IAI Area, South America": _m49("South America"), "IAI Area, EU27 & EFTA": _EU27 | _EFTA,
    "IAI Area, Gulf Cooperation Council": _GCC, "IAI Area, Asia, without China and GCC": _ASIA - {"CN"} - _GCC,
    "IAI Area, Russia & RER w/o EU27 & EFTA": (_RER - _EU27 - _EFTA) | {"RU"},
    "IAI Area, Russia and Eastern Europe": frozenset("BY MD RU UA".split()),
    "IAI Area, Western and Central Europe": _RER - {"BY", "MD", "RU", "UA"},
    "Canada without Quebec": frozenset({"CA"}), "North America without Quebec": _m49("Northern America"),
    **{k: frozenset(v.split()) for k, v in _NERC.items()},
}
# "Europe without Switzerland", "RER w/o CH+DE", "UCTE without Germany", "Europe, without Russia and Turkey" …
_WITHOUT = re.compile(r"^(Europe|RER|UCTE|ENTSO-E),?\s+(?:without|w/o)\s+(.+)$")
_SUBNATIONAL = re.compile(r"^([A-Z]{2})-.+$")  # CA-QC, US-WECC, CN-SGCC, BR-Mid-western grid


_CONTINENTS = [("Europe", _EUROPE), ("Africa", _AFRICA), ("Latin America", _LATIN_AMERICA),
               ("Northern America", _m49("Northern America")), ("Western Asia", _m49("Western Asia")), ("Asia", _ASIA),
               ("Oceania", _OCEANIA)]


def continent(code: str | None) -> str | None:
    """The UN M49 continent of a country (Western Asia apart from the rest of Asia); None for other codes."""
    return next((name for name, members_ in _CONTINENTS if code in members_), None)


def all_countries() -> frozenset[str]:
    """Every country of the region lists (UN M49 sovereign states, TW, HK, MO, XK)."""
    return frozenset().union(*(m for _n, m in _CONTINENTS))


@functools.lru_cache(maxsize=1)
def _gdp() -> dict[str, float]:
    import json
    from pathlib import Path

    path = Path(__file__).parent / "data" / "regions" / "gdp.json"
    try:
        return {c: float(v["gdp"]) for c, v in json.loads(path.read_text(encoding="utf-8"))["countries"].items()}
    except (OSError, ValueError, KeyError):
        return {}  # the file is missing (an incomplete copy): shares fall back to equal


def gdp(code: str | None) -> float | None:
    """GDP of a country in US$ (World Bank, 2022 or the nearest year; data/regions/gdp.json); None without a value."""
    return _gdp().get(code or "")


def is_country(code: str | None) -> bool:
    """A country code (ISO 3166 alpha-2, also old ones such as CS and AN)."""
    return bool(code) and len(code) == 2 and code.isalpha() and code.isupper()


def country_of(code: str | None) -> str | None:
    """The country of a sub-national location (CA-QC → CA, US-WECC → US); None for anything else."""
    m = _SUBNATIONAL.match(code or "")
    return m.group(1) if m and not (code or "").startswith("UN-") else None


@functools.lru_cache(maxsize=4096)
def members(code: str | None) -> frozenset[str] | None:
    """The countries of a region code (RER, ENTSO-E, "Europe without Switzerland" …); None for a country, a part of
    one, GLO, RoW and codes this table does not know. BAFU uses OCE for the oceans (ships), so it is not Oceania."""
    if not code:
        return None
    if code in MEMBERS:
        return MEMBERS[code]
    m = _WITHOUT.match(code)
    if m:
        base = MEMBERS.get("RER" if m.group(1) == "Europe" else m.group(1))
        out = set(base or ())
        for part in re.split(r"\s*(?:,|\+|&|\band\b)\s*", m.group(2)):
            part = re.sub(r"\s*\(.*\)$", "", part).strip()  # "NORDEL (NCPA)"
            if not part:
                continue
            if part in MEMBERS:
                out -= MEMBERS[part]
                continue
            c = resolve(part)
            if not is_country(c):
                return None
            out.discard(c)
        return frozenset(out) if out else None
    return None


def find_in_query(q: str) -> tuple[str, str | None]:
    """A location named at the end of the query ("electricity low voltage switzerland") taken out of it."""
    words = q.split()
    for n in (3, 2, 1):
        if len(words) > n:
            tail = " ".join(words[-n:])
            low = tail.lower()
            if low in REGION_NAMES or any(low in (en.lower(), de.lower()) for en, de, _c in COUNTRIES.values()) \
                    or (n == 1 and tail.isupper() and tail in COUNTRIES):
                return " ".join(words[:-n]), resolve(tail)
    return q, None
