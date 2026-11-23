"""Proxy sectors of an input-output table (EXIOBASE) for process datasets, for "Other database" (crosswalk.py).

A dataset of ecoinvent or BAFU has no counterpart of the same name in EXIOBASE: the table has 163 industries (ixi) or
200 products (pxp) per region, in million euro. Its proxy is the industry its activity belongs to, or that industry's
product, in the region of its location.

Industry, in this order:

1. ISIC: the ISIC rev.4 class of the dataset (ecoinvent: classification "ISIC rev.4 ecoinvent") through the sector
   matching of Peng & Pfister (2023), coarsened to 3 and 2 digits where a class is not listed.
2. Rules: words of the name and reference product, the dataset's category (BAFU 2025: EcoSpold01 category and
   subcategory, "natural gas / production") and sector (BAFU 2026: "electricity", "transport" ...). The first rule
   that applies gives the candidate industries ("electricity ... hydro" -> electricity by hydro). With ISIC
   candidates, a rule only narrows them ("market for electricity, low voltage", ISIC 3510 -> distribution and trade of
   electricity instead of electricity by coal).
3. Category or sector alone: the industries of that field (BAFU "chemicals" -> the four chemical industries).
4. Otherwise the industries whose names share most words with the dataset's name (unsure).

Several candidates are ranked by the words they share with the dataset (with a few synonyms: hydropower ~ hydro,
petrol ~ gasoline). In the product table each industry stands for its products (refinery -> "Gas/Diesel Oil",
"Motor Gasoline" ...), ranked the same way. A product table is recognised by its names.

Region: the location through the region matching of Peng & Pfister (2023), or the next region around it; a location
covering several EXIOBASE regions (GLO, RER, RoW) takes the one with the largest production of the sector.

Amount: the price of the product (ecoinvent's property "price" on the reference product, EUR per unit) converts the
physical amount into money; without a price the match waits for one entered by the user. ecoinvent's prices are in
EUR of 2005, EXIOBASE's in EUR of its year: no deflation, the factor stays the user's to check.

Tables in data/sectors (see its README): industry codes and names as in the EXIOBASE files.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from bw2data.backends.schema import ActivityDataset as AD
from bw2data.backends.schema import ExchangeDataset as ED

from . import regions

DATA = Path(__file__).parent / "data" / "sectors" / "ecoinvent-exiobase.json"
# money per unit of a target unit: EXIOBASE is in million euro
MONEY = {"million €": 1e6, "million euro": 1e6, "m.eur": 1e6, "meur": 1e6, "euro": 1.0, "eur": 1.0, "€": 1.0}


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def money(unit: str | None) -> float | None:
    """Euro per unit of a monetary unit ("million €": 1e6), None for any other unit."""
    return MONEY.get((unit or "").strip().lower())


# ---------- the dataset's own classification ----------

def isic(node_data: dict) -> str | None:
    """The ISIC rev.4 class of a dataset ("3510"), from its classifications as bw2io stores them."""
    for item in node_data.get("classifications") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and str(item[0]).strip().upper().startswith("ISIC"):
            code = str(item[1]).split(":")[0].strip()
            if code.isdigit():
                return code
    return None


def category(node_data: dict) -> str:
    """Category and sector as text: BAFU 2025 "natural gas / production", BAFU 2026 "electricity"."""
    cats = node_data.get("categories") or ()
    parts = [str(c) for c in cats] if isinstance(cats, (list, tuple)) else [str(cats)]
    if node_data.get("sector"):
        parts.append(str(node_data["sector"]))
    return " / ".join(p.replace("\\", " / ") for p in parts).lower()


def sectors_for_isic(code: str | None) -> list[str]:
    """EXIOBASE industry codes for an ISIC class: the class itself, else every class under its 3 or 2 first digits."""
    if not code:
        return []
    table = data()["isic_to_exiobase"]
    for n in (len(code), 3, 2):
        key = code[:n]
        if key in table:
            return list(table[key])
        hits = sorted({e for k, v in table.items() if k.startswith(key) for e in v})
        if hits:
            return hits
    return []


def regions_for(location: str | None) -> list[str]:
    """EXIOBASE regions of a location: its own match, else that of the nearest region containing it."""
    table, exio = data()["location_to_regions"], data()["exiobase_regions"]
    for loc in regions.chain(location) or []:
        if loc in table:
            return list(table[loc])
        if loc in exio:
            return [loc]
    return []


# ---------- rules: words of name, product, category -> EXIOBASE industries ----------

def _all(*prefixes: str) -> list[str]:
    """Industries under these codes, in the order of the prefixes: the first is the default among equals."""
    out: list[str] = []
    for p in prefixes:
        out += [c for c in data()["exiobase_sectors"] if (c == p or c.startswith(p + ".")) and c not in out]
    return out


ELEC = ["i40.11.a", "i40.11.b", "i40.11.c", "i40.11.d", "i40.11.e", "i40.11.f", "i40.11.g", "i40.11.h", "i40.11.i",
        "i40.11.j", "i40.11.k", "i40.11.l"]

# (where, pattern, industries): where "name" = name and reference product, "all" = also category and sector.
# The first rule that applies wins: specific ones first.
RULES: list[tuple[str, str, list[str] | str]] = [
    # electricity
    ("name", r"^electricity\b.*\b(biogas|biomethane|biomass|wood|bagasse|straw|sewage|waste|municipal)", ["i40.11.g"]),
    ("name", r"^electricity\b.*\b(hard coal|coal|lignite|peat)\b", ["i40.11.a"]),
    ("name", r"^electricity\b.*\b(natural gas|gas)\b", ["i40.11.b"]),
    ("name", r"^electricity\b.*\bnuclear", ["i40.11.c"]),
    ("name", r"^electricity\b.*\b(hydrogen|fuel cell)", ["i40.11.l"]),
    ("name", r"^electricity\b.*\b(hydro\b|hydropower|hydroelectric|run-of-river|pumped storage|reservoir)", ["i40.11.d"]),
    ("name", r"^electricity\b.*\bwind", ["i40.11.e"]),
    ("name", r"^electricity\b.*\b(oil|diesel|petroleum)\b", ["i40.11.f"]),
    ("name", r"^electricity\b.*\b(solar thermal|concentrated solar|solar tower|parabolic)", ["i40.11.i"]),
    ("name", r"^electricity\b.*\b(photovoltaic|pv|solar)\b", ["i40.11.h"]),
    ("name", r"^electricity\b.*\bgeothermal", ["i40.11.k"]),
    ("name", r"^electricity\b.*\b(tidal|wave|ocean)\b", ["i40.11.j"]),
    ("name", r"^(market for |market group for )?electricity\b.*\b(voltage|mix|grid|import|delivered|consumer|network)", ["i40.13"]),
    ("name", r"^(market for |market group for )?electricity\b", ELEC + ["i40.12", "i40.13"]),
    # heat, steam, compressed air
    ("name", r"^(market for |market group for )?(heat|steam|district heat|compressed air)\b", ["i40.3"]),
    # fuels burned: in power plants -> electricity, in boilers -> heat, in building machines -> construction
    ("name", r"\bburned in\b.*\b(power plant|cogen|chp|gas turbine|combined cycle)", ELEC),
    ("name", r"\bburned in\b.*\b(boiler|furnace|heating|stove)", ["i40.3"]),
    ("name", r"\bburned in (building )?machine|\bbuilding machine\b|\bexcavation\b", ["i45"]),
    ("name", r"\b(deconstruction|demolition|dismantling of building)", ["i45"]),
    ("name", r"\b(tillage|harvesting|sowing|fertilising, by|irrigat|mowing|baling|application of plant protection)", ["i01.h"]),
    # transport services
    ("name", r"^(market for )?transport\b.*\bpipeline", ["i60.3"]),
    ("name", r"^(market for )?transport\b.*\b(train|rail|tram)", ["i60.1"]),
    ("name", r"^(market for )?transport\b.*\b(barge|inland|river)", ["i61.2"]),
    ("name", r"^(market for )?transport\b.*\b(ship|vessel|tanker|ferry|sea|transoceanic|container)", ["i61.1"]),
    ("name", r"^(market for )?transport\b.*\b(air|aircraft|airplane|plane|helicopter|aviation)", ["i62"]),
    ("name", r"^(market for )?transport\b", ["i60.2"]),
    # fuels and their extraction
    ("name", r"\bpipeline\b", ["i60.3"]),
    ("name", r"\bnatural gas\b.*\b(liquefied|lng|regasif)", ["i11.c"]),
    ("name", r"\bnatural gas\b.*\b(consumer|pressure|distribution|network|regional storage|local)", ["i40.2"]),
    ("name", r"\bnatural gas\b", ["i11.b"]),
    ("name", r"\b(biogas|biomethane|coke oven gas|blast furnace gas|gas works)\b", ["i40.2"]),
    ("name", r"\b(crude oil|petroleum, (at|in)|oil field|oil well)", ["i11.a"]),
    ("name", r"\b(bioethanol|ethanol|biodiesel|methyl ester|charcoal|biofuel|hydrogen|methanol|methanation|electrolysis"
             r"|power-to|e-fuel|synthetic (fuel|gas|methane|diesel|kerosene))", ["i24.d"]),
    ("name", r"\b(diesel|petrol|gasoline|kerosene|naphtha|fuel oil|heating oil|bitumen|lubricat|refinery|liquefied petroleum|lpg|propane|butane|paraffin|petroleum coke|white spirit)\b", ["i23.2"]),
    ("name", r"\b(coke|coal tar)\b", ["i23.1"]),
    ("name", r"\b(hard coal|lignite|anthracite|coking coal|brown coal|briquette|peat)\b", ["i10"]),
    # waste
    ("name", r"\b(incinerat|municipal solid waste|hazardous waste)", _all("i90.1")),
    ("name", r"\b(landfill|final disposal|final repository|underground deposit|slag compartment|residual material)", _all("i90.5")),
    ("name", r"\b(wastewater|waste water|sewage|sludge)\b", ["i90.4.b", "i90.2.c"]),
    ("name", r"\bcompost", _all("i90.3")),
    ("name", r"\b(anaerobic digestion|biogasification|fermentation of biowaste)", _all("i90.2")),
    ("name", r"\b(recycling|sorting|dismantling|shredding|scrap preparation)\b", ["i37"]),
    ("name", r"^(disposal|treatment of)\b.*\b(equipment|system|device|appliance|unit|machine|module|installation)", ["i37"]),
    ("name", r"^(disposal|treatment of)\b.*\b(building|concrete|brick|gravel|inert|mineral|glass|metal)", ["i90.5.d"]),
    ("name", r"^(disposal|treatment of|waste)\b", _all("i90.5.d", "i90")),
    # nuclear fuel, metals
    ("name", r"\b(enriched uranium|uranium hexafluoride|fuel element|nuclear fuel|yellowcake)", ["i23.3"]),
    ("name", r"\b(uranium|thorium)\b", ["i12"]),
    ("name", r"\biron ore\b|\b(ore|mine|mining)\b.*\biron\b", ["i13.1"]),
    ("name", r"\b(ore|mine|mining|bauxite)\b|\b(copper|zinc|lead|nickel|molybdenum|gold|silver|tin|metal) concentrate",
     _all("i13.20")),
    ("name", r"\b(sheet rolling|section bar|wire drawing|welding|metal working|coating|anodis|galvani|zinc coating|turning|milling|drilling|deep drawing|impact extrusion|chromium plating)", ["i28"]),
    ("name", r"\b(aluminium|aluminum)\b.*\b(secondary|recycled|scrap|remelt)|\b(secondary|recycled) alumin", ["i27.42.w"]),
    ("name", r"\b(aluminium|aluminum|alumina)\b", ["i27.42"]),
    ("name", r"\bcopper\b.*\b(secondary|recycled|scrap)", ["i27.44.w"]),
    ("name", r"\bcopper\b", ["i27.44"]),
    ("name", r"\b(lead|zinc|tin)\b", ["i27.43"]),
    ("name", r"\b(gold|silver|platinum|palladium|rhodium|precious metal)\b", ["i27.41"]),
    ("name", r"\b(steel|iron|ferro|ferrochromium|ferronickel)\b.*\b(secondary|recycled|scrap|electric arc|converter)", ["i27.a.w"]),
    ("name", r"\b(steel|pig iron|cast iron|iron|reinforcing|ferrochromium|ferronickel|ferromanganese)\b", ["i27.a"]),
    ("name", r"\b(nickel|titanium|magnesium|silicon|chromium|manganese|cobalt|lithium|tantalum|molybdenum|tungsten|indium|gallium|germanium|cadmium|antimony)\b", ["i27.45"]),
    ("name", r"\bcasting\b", ["i27.5"]),
    # minerals, construction materials
    ("name", r"\b(cement|clinker|lime|quicklime|gypsum|plaster|stucco|anhydrite)\b", ["i26.d"]),
    ("name", r"\b(brick|roof tile|clay tile|expanded clay)\b", ["i26.c"]),
    ("name", r"\b(ceramic|porcelain|sanitary)\b", ["i26.b"]),
    ("name", r"\b(glass|glazing)\b.*\b(recycled|cullet|secondary)", ["i26.a.w"]),
    ("name", r"\b(glass|glazing|glass wool)\b", ["i26.a"]),
    ("name", r"\b(concrete|mortar|screed|fibre cement|fiber cement|stone wool|rock wool|asphalt|aerated)\b", ["i26.e"]),
    ("name", r"\b(gravel|sand|clay|kaolin|bentonite)\b", ["i14.2"]),
    ("name", r"\b(crushed stone|limestone|natural stone|marble|granite|slate|stone)\b", ["i14.1"]),
    ("name", r"\b(salt|potash|phosphate rock|sulfur|sulphur)\b", ["i14.3"]),
    # plastics, chemicals
    ("name", r"\b(injection mo|extrusion|blow mo|thermoforming|film|foam|eps|xps|pipe|tyre|tire|rubber|packaging, plastic|plastic (product|part|bag|sheet))", ["i25"]),
    ("name", r"\b(recycled|secondary)\b.*\b(plastic|polyethylene|polypropylene|pet)\b", ["i24.a.w"]),
    ("name", r"\b(polyethylene|polypropylene|polystyrene|polyvinyl|pvc|pet|polyurethane|polycarbonate|polyamide|nylon|abs|epoxy|resin|polymer|plastic|granulate|pmma|ptfe|polyester)\b", ["i24.a"]),
    ("name", r"\b(ammonia|urea|ammonium|nitrogen fertili|calcium ammonium|nitric acid)\b", ["i24.b"]),
    ("name", r"\b(phosph|potassium|potash|npk|fertili)", ["i24.c"]),
    # wood, paper
    ("name", r"\b(recycled|waste) paper|\bdeinked", ["i21.w.1"]),
    ("name", r"\bpulp\b", ["i21.1"]),
    ("name", r"\b(paper|cardboard|corrugated|carton|containerboard|tissue)\b", ["i21.2"]),
    ("name", r"\b(furniture|chair|table|sofa|bed|kitchen)\b", ["i36"]),
    ("name", r"\b(roundwood|logs?|felling|forwarding|skidding|forest|tree)\b", ["i02"]),
    ("name", r"\b(sawn|sawnwood|sawlogs?|bark|wood chips|chips|sawdust|shavings|pellets?|timber|lumber|plywood|particle ?board|osb|mdf|fibreboard|fiberboard|glulam|wood|wooden|parquet|beam)\b", ["i20"]),
    # textiles
    ("name", r"\b(textile|yarn|fabric|woven|knit|fibre|fiber)\b", ["i17"]),
    ("name", r"\b(garment|clothing|shirt|trousers|jacket)\b", ["i18"]),
    ("name", r"\b(leather|shoe|footwear)\b", ["i19"]),
    # vehicles and machines made
    ("name", r"\b(passenger car|lorry|truck|bus|van|motor scooter|motorbike|motorcycle|tractor|vehicle|trailer)\b", ["i34"]),
    ("name", r"\b(aircraft|airplane|ship|locomotive|train|bicycle|helicopter|railway car|tram)\b", ["i35"]),
    # electronics, machinery
    ("name", r"\b(computer|laptop|notebook|desktop|server|printer|data storage)\b", ["i30"]),
    ("name", r"\b(photovoltaic (cell|panel|laminate|module)|solar (cell|panel)|wafer|printed wiring board|integrated circuit|capacitor|resistor|transistor|diode|electronic component|television|tv|mobile phone|smartphone|telephone|router|modem|display|monitor)\b", ["i32"]),
    ("name", r"\b(battery|cable|electric motor|generator|transformer|inverter|lamp|led|luminaire|switchgear|charger)\b", ["i31"]),
    ("name", r"\b(heat pump|boiler|furnace|ventilation|ventilator|fan|pump|compressor|turbine|machine|machinery|excavator|crane|heating system|air handling|chiller|engine|gear)\b", ["i29"]),
    ("name", r"\b(watch|clock|instrument|sensor|meter)\b", ["i33"]),
    # buildings and infrastructure
    ("name", r"\b(building|house|hall|apartment|road|tunnel|bridge|railway track|dam|construction|installation|power plant|infrastructure)\b", ["i45"]),
    # water
    ("name", r"\b(tap water|drinking water|water supply|water, (deionised|decarbonised|completely softened|ultrapure|unspecified))", ["i41"]),
    # agriculture, food
    ("name", r"\bmanure\b", ["i01.w.1"]),
    ("name", r"\b(slaughter|meat|beef|pork|sausage|ham)\b.*\b(cattle|beef|cow)\b|\bbeef\b", ["i15.a"]),
    ("name", r"\b(pork|pig meat|sausage|ham)\b", ["i15.b"]),
    ("name", r"\b(chicken meat|poultry meat|broiler meat)\b", ["i15.c"]),
    ("name", r"\b(vegetable oil|rape oil|rapeseed oil|soybean oil|palm oil|sunflower oil|margarine|oil mill)\b", ["i15.e"]),
    ("name", r"\b(cheese|butter|yoghurt|cream|milk powder|dairy|whey)\b", ["i15.f"]),
    ("name", r"\b(sugar)\b(?!\s*(beet|cane))", ["i15.h"]),
    ("name", r"\b(beer|wine|juice|beverage|soft drink|spirits)\b", ["i15.j"]),
    ("name", r"\b(fish|salmon|trout|tuna|shrimp)\b", ["i05"]),
    ("name", r"\b(flour|bread|pasta|feed|fodder mix|starch|chocolate|coffee|tea|bakery)\b", ["i15.i"]),
    ("name", r"\brice\b", ["i01.a"]),
    ("name", r"\bwheat\b", ["i01.b"]),
    ("name", r"\b(maize|corn|barley|rye|oat|oats|sorghum|triticale|spelt|cereal|grain)\b", ["i01.c"]),
    ("name", r"\b(rape|rapeseed|soy|soya|soybean|sunflower|oil seed|palm fruit|olive)\b", ["i01.e"]),
    ("name", r"\b(vegetable|fruit|potato|tomato|apple|pear|nut|nuts|berr|grape|banana|orange|carrot|onion|lettuce|cabbage|bean|pea|peas)\b", ["i01.d"]),
    ("name", r"\b(sugar beet|sugar cane)\b", ["i01.f"]),
    ("name", r"\b(cotton|flax|hemp|jute|kenaf|sisal)\b", ["i01.g"]),
    ("name", r"\b(raw milk|cow milk|milk)\b", ["i01.n"]),
    ("name", r"\b(cattle|cow|calf|bull|heifer|suckler)\b", ["i01.i"]),
    ("name", r"\b(pig|piglet|sow|swine)\b", ["i01.j"]),
    ("name", r"\b(poultry|chicken|broiler|hen|laying hen|turkey|duck)\b", ["i01.k"]),
    ("name", r"\b(sheep|goat|lamb|horse|rabbit)\b", ["i01.l"]),
    ("name", r"\b(egg|eggs|honey)\b", ["i01.m"]),
    ("name", r"\b(wool|silk)\b", ["i01.o"]),
    ("name", r"\b(grass|hay|silage|clover|alfalfa|straw|crop|seed|seedling)\b", ["i01.h"]),
    # services
    ("name", r"\b(internet|data transmission|telecommunication|mobile network|access network|xdsl|ftth|postal|parcel)\b",
     ["i64"]),
    ("name", r"\b(data cent|computing|software|cloud|website|video streaming)\b", ["i72"]),
    ("name", r"\b(hotel|restaurant|meal|catering)\b", ["i55"]),
    ("name", r"\b(retail|shop|supermarket)\b", ["i52"]),
    ("name", r"\bwholesale\b", ["i51"]),
    ("name", r"\b(office|consulting|cleaning|advertising|legal|engineering service)\b", ["i74"]),
    ("name", r"\b(hospital|health|medical care)\b", ["i85"]),
    ("name", r"\b(school|education|university)\b", ["i80"]),
]

# a category or sector alone (BAFU 2025 top category, BAFU 2026 sector): the industries of that field
FIELDS: list[tuple[str, list[str] | tuple]] = [
    (r"\btransport", ("i60", "i61", "i62", "i63")),
    (r"\b(electricity|photovoltaic|wind power|power plants)\b", ("i40.13", "i40.11", "i40.12")),
    (r"\b(heat|heating|district heat|compressed air|heat pumps)\b", ("i40.3",)),
    (r"\bnatural gas\b", ("i11.b", "i40.2", "i60.3")),
    (r"\boil\b", ("i11.a", "i23.2")),
    (r"\b(fuels|energy|biomass)\b", ("i10", "i11", "i23", "i24.d", "i40.2", "i40.3")),
    (r"\b(waste|landfill|incineration|landfarming|underground deposit|recycling|impoundment)\b",
     ("i90.5.d", "i90", "i37")),
    (r"\bwater\b", ("i41", "i90.4")),
    (r"\b(chemicals|washing agents|pesticides|gases)\b", ("i24.d", "i24")),
    (r"\bplastics\b", ("i24.a", "i25")),
    (r"\bmetals\b", ("i28", "i27", "i13")),
    (r"\b(minerals|construction materials|construction|building components|flooring|insulation|ceramics|glass)\b",
     ("i45", "i26", "i14", "i20", "i25", "i28")),
    (r"\b(wood|paper|board|cardboard)\b", ("i02", "i20", "i21")),
    (r"\b(electronics|computers|private consumption)\b", ("i32", "i31", "i30", "i33")),
    (r"\b(ventilation|building-services|mechanical|machinery)\b", ("i29",)),
    (r"\b(agricultur|food)", ("i01", "i15")),
    (r"\btextiles\b", ("i17", "i18")),
]

# product table: the product of an industry the dataset names (refinery -> "Gas/Diesel Oil")
PRODUCT_HINTS = [
    (r"\b(light fuel oil|heating oil|diesel|gas oil)\b", "p23.20.f"), (r"\bheavy fuel oil\b", "p23.20.g"),
    (r"\b(petrol|gasoline)\b", "p23.20.a"), (r"\b(kerosene|jet fuel)\b", "p23.20.d"), (r"\bnaphtha\b", "p23.20.l"),
    (r"\b(lpg|liquefied petroleum|propane|butane)\b", "p23.20.i"), (r"\bbitumen\b", "p23.20.o"),
    (r"\blubricat", "p23.20.n"), (r"\bpetroleum coke\b", "p23.20.q"), (r"\brefinery gas\b", "p23.20.h"),
    (r"\banthracite\b", "p10.a"), (r"\bcoking coal\b", "p10.b"), (r"\b(hard coal|bituminous)\b", "p10.c"),
    (r"\b(lignite|brown coal)\b", "p10.f"), (r"\bbriquett", "p10.g"), (r"\bpeat\b", "p10.h"),
    (r"\bcoal tar\b", "p23.1.c"), (r"\bcoke\b", "p23.1.a"), (r"\bnatural gas liquids\b", "p11.b.1"),
    (r"\b(biogas|biomethane)\b", "p40.2.e"), (r"\bnatural gas\b", "p40.2.1"), (r"\bethanol\b", "p24.g"),
    (r"\b(biodiesel|methyl ester)\b", "p24.h"), (r"\bcharcoal\b", "p24.e"),
]

SYNONYMS = {"hydropower": "hydro", "petrol": "gasoline", "lorry": "truck", "aluminum": "aluminium", "pv": "photovoltaic",
            "photovoltaics": "photovoltaic", "polyethylene": "plastic", "polypropylene": "plastic", "polystyrene": "plastic",
            "pvc": "plastic", "plastics": "plastic", "biowaste": "food", "beef": "cattle", "pork": "pigs",
            "chicken": "poultry", "timber": "wood", "lumber": "wood", "concrete": "inert", "gravel": "inert",
            "brick": "inert", "slag": "inert", "radioactive": "hazardous", "lignite": "coal", "anthracite": "coal", "gold": "precious", "silver": "precious",
            "platinum": "precious", "palladium": "precious",
            "wastewater": "water"}
STOP = {"of", "and", "the", "by", "for", "from", "in", "to", "at", "with", "nec", "other", "production", "market", "group",
        "manufacture", "processing", "products", "product", "services", "service", "unspecified", "plant", "mix",
        "supply", "treatment", "waste", "excluding", "related", "activities", "incl", "land", "application", "into",
        "new", "secondary", "re", "type", "raw", "dried", "average", "conventional", "integrated", "organic",
        "large", "small", "medium", "high", "low", "total", "general", "basic", "primary"}


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        w = SYNONYMS.get(w, w)
        if len(w) > 2 and w not in STOP:
            out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def overlap(a: str, b: str) -> float:
    """Share of the words of `a` found in `b` (plural and singular alike, a few synonyms)."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa) if wa else 0.0


def industries(name: str, product: str, cat: str, isic_code: str | None) -> tuple[list[str], str, bool]:
    """Candidate EXIOBASE industries for a dataset, best first; how they were found ("isic", "rule", "category" or
    "name": words only); and whether the first is clear (the only one, or sharing more words than the second)."""
    sectors = data()["exiobase_sectors"]
    text = re.sub(r"^x+\s+", "", f"{name} {product}".lower())  # BAFU marks obsolete datasets "xx ", "xxx "
    full = f"{text} {cat}"
    cands = sectors_for_isic(isic_code)
    how = "isic" if cands else ""
    for where, pattern, codes in RULES:
        if re.search(pattern, text if where == "name" else full):
            hit = [c for c in codes if not cands or c in cands]
            if hit:
                cands, how = hit, how or "rule"
                break
    if not cands and cat:
        for pattern, prefixes in FIELDS:
            if re.search(pattern, cat):
                cands, how = _all(*prefixes), "category"
                break
    if not cands:
        cands, how = list(sectors), "name"

    def score(c: str) -> float:
        return overlap(sectors[c], text) + 0.5 * overlap(text, sectors[c])

    def nec(c: str) -> bool:
        return bool(re.search(r"\bnec\b|n\.e\.c", sectors[c]))

    # equals: a "nec" industry first (ISIC 2011 basic chemicals -> chemicals nec), then the order of the rule
    ranked = sorted(cands, key=lambda c: (-score(c), not nec(c), cands.index(c)))
    if how == "name":
        ranked = [c for c in ranked if score(c) > 0][:3]
    clear = len(ranked) == 1 or (len(ranked) > 1 and score(ranked[0]) > score(ranked[1]))
    return ranked, how, clear


class Sectors:
    """The datasets of one input-output database by sector code and region, with their production."""

    def __init__(self, rows: dict[int, dict]):
        d = data()
        ind = {v.lower(): k for k, v in d["exiobase_sectors"].items()}
        prod = {v.lower(): k for k, v in d["exiobase_products"].items()}
        self.by_code: dict[str, dict[str, dict]] = {}  # code -> {location: dataset}
        self.names: set[str] = set()
        n_ind = n_prod = 0
        for r in rows.values():
            key = re.sub(r"\s*\(\d+(\.\d+)?\)\s*$", "", r["name"]).strip().lower()
            n_ind += key in ind and key not in prod
            n_prod += key in prod and key not in ind
            for code in (ind.get(key), prod.get(key)):  # "Chemicals nec" is the name of an industry and a product
                if code:
                    self.by_code.setdefault(code, {})[r["location"]] = r
            self.names.add(r["name"])
        self.system = "pxp" if n_prod > n_ind else "ixi" if n_ind else None
        self._fallback: dict[str, str | None] = {}
        self._rows = rows

    def _by_words(self, sector_name: str) -> str | None:
        """A table with names of its own (not EXIOBASE's): the name sharing most words with the sector's."""
        if sector_name not in self._fallback:
            scored = sorted(((overlap(sector_name, n) + 0.5 * overlap(n, sector_name), n) for n in self.names),
                            key=lambda t: (-t[0], len(t[1]), t[1]))
            self._fallback[sector_name] = scored[0][1] if scored and scored[0][0] >= 0.5 else None
        return self._fallback[sector_name]

    def _datasets(self, industry: str, text: str) -> list[dict[str, dict]]:
        """{location: dataset} per table entry standing for this industry, best first."""
        d = data()
        if self.system == "pxp":
            prods = d["industry_products"].get(industry, [])
            hint = next((c for pat, c in PRODUCT_HINTS if c in prods and re.search(pat, text.lower())), None)
            # a product the name points to, else the one sharing most of the dataset's words, else the main product
            prods = sorted(prods, key=lambda p: (p != hint, -overlap(text, d["exiobase_products"][p]),
                                                 p[1:] != industry[1:], p))
            return [self.by_code[p] for p in prods if p in self.by_code]
        if self.system == "ixi":
            return [self.by_code[industry]] if industry in self.by_code else []
        name = self._by_words(d["exiobase_sectors"][industry])
        return [{r["location"]: r for r in self._rows.values() if r["name"] == name}] if name else []

    @staticmethod
    def _in_regions(by_loc: dict[str, dict], regs: list[str]) -> list[dict]:
        rows = [r for loc, r in by_loc.items() if not regs or loc in regs]
        return sorted(rows, key=lambda r: (-(r.get("volume") or 0.0), r["location"]))

    def propose(self, name: str, product: str, location: str, isic_code: str | None, cat: str = "", n: int = 5
                ) -> tuple[list[tuple[float, dict]], str]:
        """Proxy datasets for a process dataset, best first, with a score; and how the sector was found."""
        cands, how, clear = industries(name, product, cat, isic_code)
        text = f"{name} {product}"
        regs = regions_for(location)
        # one clear industry is a good suggestion; several close ones, a field alone or words alone are unsure
        base = {"isic": 0.9, "rule": 0.9, "category": 0.65, "name": 0.35}[how] - (0.0 if clear else 0.35)
        out = []
        for rank, ind in enumerate(cands):
            for k, by_loc in enumerate(self._datasets(ind, text)[:2]):
                for j, r in enumerate(self._in_regions(by_loc, regs)[:2 if rank == k == 0 else 1]):
                    out.append((round(max(0.05, base - 0.05 * (rank + k + j)), 2), r))
                if len(out) >= n:
                    return out[:n], how
        return out[:n], how


def source_info(ids) -> dict[int, dict]:
    """{id: {"isic", "category", "price"}} for datasets of the current project; price in EUR per unit, or None."""
    ids = [int(i) for i in ids]
    out: dict[int, dict] = {}
    keys = {}
    for i in range(0, len(ids), 900):
        for nid, db, code, d in AD.select(AD.id, AD.database, AD.code, AD.data).where(AD.id << ids[i:i + 900]).tuples():
            out[nid] = {"isic": isic(d), "category": category(d), "price": None}
            keys[(db, code)] = nid
    codes = sorted({c for _, c in keys})
    for i in range(0, len(codes), 900):
        for db, code, d in (ED.select(ED.output_database, ED.output_code, ED.data)
                            .where((ED.output_code << codes[i:i + 900]) & (ED.type == "production")).tuples()):
            nid = keys.get((db, code))
            if nid is None or out[nid]["price"] is not None:
                continue
            price = ((d.get("properties") or {}).get("price") or {})
            if str(price.get("unit", "")).upper().startswith("EUR") and price.get("amount"):
                out[nid]["price"] = float(price["amount"])
    return out


# ---------- output by country: the weights of a region's countries (regional.py) ----------

REST = {"Europe": "WE", "Africa": "WF", "Latin America": "WL", "Northern America": "WL", "Western Asia": "WM",
        "Asia": "WA", "Oceania": "WA"}  # EXIOBASE's five rest-of-world regions, by continent


@lru_cache(maxsize=20000)
def proxy_industries(name: str, product: str, cat: str, isic_code: str | None) -> tuple[str, ...]:
    """The EXIOBASE industries of a dataset for weighting a region: found by ISIC class, a rule or the category; none
    when only the words of the name point to some (too unsure to weigh countries by)."""
    cands, how, _clear = industries(name or "", product or "", cat or "", isic_code)
    return tuple(cands) if how in ("isic", "rule", "category") else ()


class OutputWeights:
    """Country weights from EXIOBASE: the gross output of a dataset's industries in each country, in million euro.

    bw2io keeps the output of every EXIOBASE sector and region as "production volume" (from x.txt). A country EXIOBASE
    lists gets its own; a country of one of the five rest-of-world regions (RoW Europe, Africa, America, Asia and
    Pacific, Middle East; the region matching of Peng & Pfister, else the continent) a share of its region's by GDP
    (World Bank, regions.gdp). A member without a GDP value gets none; a region without any, equal shares. In a
    product table an industry's output is the sum of its products'."""

    def __init__(self, database: str, rows: dict[int, dict]):
        self.database = database
        sec = Sectors(rows)
        self.system = sec.system
        d = data()
        self.output: dict[tuple[str, str], float] = {}
        codes = ([(ind, p) for ind, prods in d["industry_products"].items() for p in prods] if sec.system == "pxp"
                 else [(c, c) for c in sec.by_code if c in d["exiobase_sectors"]])
        for ind, code in codes:
            for loc, r in sec.by_code.get(code, {}).items():
                v = r.get("volume")
                if isinstance(v, (int, float)) and v > 0:
                    self.output[(ind, loc)] = self.output.get((ind, loc), 0.0) + float(v)
        # every region of the table, also one where this or that sector produces nothing
        self.regions = {r["location"] for r in rows.values() if r.get("location")}
        self.rest = {r for r in REST.values() if r in self.regions}
        everyone = regions.all_countries() | {k for k in d["location_to_regions"] if regions.is_country(k)}
        self.members: dict[str, list[str]] = {}  # rest-of-world region -> its countries
        for c in sorted(everyone):
            r = self.region_of(c)
            if r in self.rest:
                self.members.setdefault(r, []).append(c)
        self.share: dict[str, float] = {}  # a country's share of its rest-of-world region's output
        for members in self.members.values():
            g = {c: regions.gdp(c) or 0.0 for c in members}
            total = sum(g.values())
            for c in members:
                self.share[c] = g[c] / total if total else 1.0 / len(members)
        self._memo: dict = {}

    def region_of(self, country: str) -> str | None:
        """The EXIOBASE region a country belongs to."""
        if country in self.regions and country not in self.rest:
            return country
        hit = data()["location_to_regions"].get(country)
        if hit and len(hit) == 1 and hit[0] in self.rest:
            return hit[0]
        r = REST.get(regions.continent(country) or "")
        return r if r in self.rest else None

    def weights(self, industries_: tuple[str, ...], countries) -> dict[str, float] | None:
        """{country: output} of these industries for the countries of a region; None when none of them produces."""
        k = (industries_, frozenset(countries))
        if k not in self._memo:
            out = {}
            for c in countries:
                r = self.region_of(c)
                if r is None:
                    continue
                v = sum(self.output.get((s, r), 0.0) for s in industries_)
                if r in self.rest:
                    v *= self.share.get(c, 0.0)
                if v > 0:
                    out[c] = v
            self._memo[k] = out or None
        return self._memo[k]


_weights: dict = {}


def output_weights() -> OutputWeights | None:
    """The country weights of the project's EXIOBASE (an industry table first, else a product table); None without
    one, or when its datasets carry no output."""
    import bw2data as bd

    from . import backgrounds

    k = (bd.projects.current, tuple(sorted((n, str(m.get("modified"))) for n, m in bd.databases.items())))
    if k in _weights:
        return _weights[k]
    _weights.clear()
    best = None
    for db in sorted((n for n in bd.databases if backgrounds.kind(n) == "mrio"), reverse=True):
        rows = {nid: {"name": d.get("name", ""), "location": d.get("location") or "", "volume": d.get("production volume")}
                for nid, d in AD.select(AD.id, AD.data).where(AD.database == db).tuples().iterator()}
        w = OutputWeights(db, rows)
        if w.output and (best is None or (w.system == "ixi" and best.system != "ixi")):
            best = w
    _weights[k] = best
    return best
