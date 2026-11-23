"""All impact categories of one or two method families side by side, and export of results as CSV or Excel.

A family is the first part of a method's name ("EF v3.1", "Ecological Scarcity 2021", "IPCC 2021"); its categories
are all methods that share it. Every category is one transposed solve of the factorized background (cached per
method by the engine), so a family of 25 categories takes milliseconds after the first time.

Exports hold the numbers the app shows, in the current language: CSV as one long table (section, item, value,
unit) that any program reads, Excel with one sheet per section.
"""

from __future__ import annotations

import csv
import io
import re

import bw2data as bd

from . import analysis, models
from .analysis import short_unit
from .i18n import _


_NAMESPACE = re.compile(r"^ecoinvent[-\s]", re.I)


def _method_list() -> list[tuple]:
    return sorted(m for m in bd.methods if bd.methods[m].get("num_cfs", 1) != 0)


def _multi_namespace(methods) -> bool:
    return len({m[0] for m in methods if _NAMESPACE.match(m[0])}) > 1


def method_family(mt, multi: bool = False) -> str:
    """The overarching method: "EF v3.1", "ReCiPe 2016 v1.03, midpoint (H)", "Ecological Scarcity 2021".

    ecoinvent ships its methods under its own name first (("ecoinvent-3.13", "EF v3.1", "climate change", …)); there
    the method is the second part (with the ecoinvent version if a project has methods of two versions)."""
    mt = tuple(mt)
    if len(mt) > 2 and _NAMESPACE.match(mt[0]):
        return f"{mt[1]} ({mt[0]})" if multi else mt[1]
    return mt[0]


def method_name(mt) -> str:
    """The category within the method: "climate change · global warming potential (GWP100)"."""
    mt = tuple(mt)
    rest = mt[2:] if len(mt) > 2 and _NAMESPACE.match(mt[0]) else mt[1:]
    return " · ".join(rest) or mt[-1]


# impact topics, to compare one kind of impact across methods; the first that matches counts
TOPICS = [
    ("climate", r"climate|klima|global warming|\bgwp|\bgtp|carbon footprint|greenhouse|\bghg"),
    ("ozone", r"ozone depletion|ozone layer|stratospheric ozone"),
    ("smog", r"photochemical|ozone formation|oxidant|smog"),
    ("particulates", r"particulate|\bpm\b|respiratory|air pollutants"),
    ("acidification", r"acidification"),
    ("eutrophication", r"eutrophication|nutrient"),
    ("toxicity", r"toxicity|carcinogen|heavy metals|\bpop\b|pesticide|endocrine|persistent organic"),
    ("radiation", r"ionising|ionizing|(?<!non )radioactiv|radiation"),
    ("land", r"land use|land occupation|land transformation|\bland\b"),
    ("water", r"water"),
    ("energy", r"fossil|energy|non-renewable|exergy|oil|natural gas|coal"),
    ("minerals", r"mineral|metal|abiotic|material resources|resource"),
    ("waste", r"waste"),
    ("total", r"^total\b|single score|gesamt|umweltbelastungspunkte|eco-points"),
]
_TOPIC_RES = [(k, re.compile(rx, re.I)) for k, rx in TOPICS]


def topic(mt) -> str:
    text = method_name(mt)
    return next((k for k, rx in _TOPIC_RES if rx.search(text)), "other")


def families() -> list[str]:
    ms = _method_list()
    multi = _multi_namespace(ms)
    return sorted({method_family(m, multi) for m in ms})


def family_of(method) -> str:
    return method_family(method, _multi_namespace(_method_list()))


def categories(activity_id: int | str, amount: float, fams: list[str], topic_key: str | None = None) -> dict:
    """Score of the product for every category of each family: {"families": [{"family", "rows": [...]}]}.

    fams ["*"]: all methods; topic_key: only the categories of one kind of impact ("climate", "toxicity" …), to
    compare it across methods."""
    S = models.system_for(activity_id)
    nid = int(activity_id)
    ms = _method_list()
    multi = _multi_namespace(ms)
    by_fam: dict[str, list] = {}
    for mt in ms:
        by_fam.setdefault(method_family(mt, multi), []).append(mt)
    wanted = sorted(by_fam, key=lambda f: (f != "Werkbank", f)) if fams == ["*"] else fams
    out = []
    for fam in wanted:
        if fam not in by_fam:
            raise KeyError(_("Methode fehlt in diesem Projekt"))
        rows = []
        for mt in by_fam[fam]:
            tp = topic(mt)
            if topic_key and tp != topic_key:
                continue
            rows.append({"method": list(mt), "name": method_name(mt), "topic": tp,
                         "unit": short_unit(bd.methods[mt].get("unit")), "value": S.score({nid: amount}, mt)})
        if rows or fams != ["*"]:
            out.append({"family": fam, "rows": rows})
    return {"families": out}


# ---------- export ----------

def _result_sections(activity_id: int | str, amount: float, method: tuple, fams: list[str],
                     topic_key: str | None = None) -> tuple[str, list]:
    """(file name stem, [(section title, header, rows)]) for one product."""
    S = models.system_for(activity_id)
    nid, method = int(activity_id), tuple(method)
    a = bd.get_node(id=nid)
    unit = short_unit(bd.methods[method].get("unit"))
    c = analysis.contributions(S, nid, amount, method, top=2000)
    head = [_("Produkt"), _("Ort"), _("Menge"), _("Einheit"), _("Datenbank"), _("Methode"), _("Ergebnis"), _("Einheit")]
    summary = [[a["name"], a.get("location") or "", amount, short_unit(a.get("unit")), a["database"], " | ".join(method),
                c["score"], unit]]
    by_act = [[r["name"], r.get("location") or "", r.get("database") or "", r["value"], unit] for r in c["by_activity"]]
    if c["by_activity_rest"]:
        by_act.append([_("Übrige"), "", "", c["by_activity_rest"], unit])
    by_flow = [[r["name"], r.get("categories") or "", r["value"], unit] for r in c["by_flow"]]
    if c["by_flow_rest"]:
        by_flow.append([_("Übrige"), "", c["by_flow_rest"], unit])
    how = {"own": _("Faktor des Orts"), "country": _("Faktor des Landes"), "region": _("Mittel der Länder"),
           "normal": _("normaler Faktor")}
    by_loc = [[r["location"], r["name"] or "", r["value"], unit, r["regional"], how[r["how"]], r["processes"]]
              for r in c["by_location"]]
    cats = []
    for f in categories(nid, amount, fams, topic_key)["families"]:
        cats += [[f["family"], r["name"], r["value"], r["unit"]] for r in f["rows"]]
    status = {"own": _("ja"), "mapped": _("ja, über Flusszuordnung"), "completed": _("ja, ergänzt"), "none": _("nein")}
    inv_rows = analysis.inventory(S, nid, amount, method)
    inv = [[r["name"], r["categories"], r["amount"], r["unit"], status[r["status"]],
            r["factor"] if r["factor"] is not None else "", (r.get("namesake") or {}).get("categories", ""),
            r.get("estimate", "")] for r in inv_rows]
    done = [[r["name"], r["categories"], r["factor"], r["source"], r["amount"] * r["factor"], unit]
            for r in inv_rows if r["status"] == "completed"]
    sections = [
        (_("Ergebnis"), head, summary),
        (_("Beiträge nach Prozess"), [_("Prozess"), _("Ort"), _("Datenbank"), _("Wert"), _("Einheit")], by_act),
        (_("Beiträge nach Stoff"), [_("Stofffluss"), _("Kompartiment"), _("Wert"), _("Einheit")], by_flow),
        (_("Beiträge nach Ort"), [_("Ort"), _("Land"), _("Wert"), _("Einheit"), _("davon Faktoren nach Ort"), _("Faktor"),
                                  _("Prozesse")], by_loc),
        (_("Alle Kategorien"), [_("Methode"), _("Kategorie"), _("Wert"), _("Einheit")], cats),
        (_("Inventar"), [_("Stofffluss"), _("Kompartiment"), _("Menge"), _("Einheit"), _("Charakterisiert"),
                         _("Faktor"), _("Gleichnamiger Fluss mit Faktor"), _("Schätzung, falls gleich bewertet")], inv),
    ]
    if done:
        sections.append((_("Ergänzte Faktoren"), [_("Stofffluss"), _("Kompartiment"), _("Faktor"), _("Übernommen von"),
                                                  _("Wert"), _("Einheit")], done))
    return f"{a['name']} {a.get('location') or ''}".strip(), sections


def _setup_sections(name: str, fus: list[dict], methods: list[tuple]) -> tuple[str, list]:
    S = models.system()
    pairs = [(int(f["id"]), float(f["amount"])) for f in fus]
    info = analysis.node_info(i for i, _a in pairs)
    table = analysis.score_table(S, pairs, methods)  # [method][product]
    units = [short_unit(bd.methods[m].get("unit")) for m in methods]
    wide_head = [_("Produkt"), _("Ort"), _("Menge"), _("Einheit")] + [f"{' | '.join(m)} [{u}]" for m, u in zip(methods, units)]
    wide = [[info.get(i, {}).get("name", "?"), info.get(i, {}).get("location") or "", a, info.get(i, {}).get("unit", ""),
             *[table[k][j] for k in range(len(methods))]] for j, (i, a) in enumerate(pairs)]
    long_head = [_("Produkt"), _("Ort"), _("Menge"), _("Einheit"), _("Methode"), _("Wert"), _("Einheit")]
    long = [[r[0], r[1], r[2], r[3], " | ".join(m), table[k][j], units[k]]
            for j, r in enumerate(wide) for k, m in enumerate(methods)]
    return name, [(_("Ergebnis"), wide_head, wide), (_("Lang"), long_head, long)]


def _csv(sections: list) -> bytes:
    """One table for all sections: the section title in the first column (semicolon, UTF-8 with BOM for Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    for title, head, rows in sections:
        w.writerow([_("Teil"), *head])
        for r in rows:
            w.writerow([title, *r])
        w.writerow([])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _xlsx(sections: list) -> bytes:
    import xlsxwriter

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "nan_inf_to_errors": True})
    bold = wb.add_format({"bold": True, "bg_color": "#E8EEEA", "border": 0})
    num = wb.add_format({"num_format": "0.000E+00"})
    used = set()
    for title, head, rows in sections:
        name = re.sub(r"[\[\]:*?/\\]", " ", title)[:31] or "Sheet"
        while name in used:
            name = name[:28] + f" {len(used)}"
        used.add(name)
        ws = wb.add_worksheet(name)
        ws.write_row(0, 0, head, bold)
        for i, r in enumerate(rows, start=1):
            for j, v in enumerate(r):
                if isinstance(v, float):
                    ws.write_number(i, j, v, num)
                else:
                    ws.write(i, j, v)
        ws.freeze_panes(1, 0)
        for j, h in enumerate(head):
            width = max([len(str(h))] + [len(str(r[j])) for r in rows[:200] if j < len(r)])
            ws.set_column(j, j, min(max(10, width + 2), 60))
    wb.close()
    return buf.getvalue()


def _file(stem: str, sections: list, fmt: str) -> tuple[bytes, str, str]:
    stem = re.sub(r'[\\/:*?"<>|]+', " ", stem).strip()[:80] or "LCA Wrench"
    if fmt == "xlsx":
        return _xlsx(sections), f"{stem}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return _csv(sections), f"{stem}.csv", "text/csv; charset=utf-8"


def export_result(activity_id: int | str, amount: float, method: tuple, fams: list[str] | None, fmt: str,
                  topic_key: str | None = None):
    method = tuple(method)
    fams = fams or [family_of(method)]
    stem, sections = _result_sections(activity_id, amount, method, fams, topic_key)
    return _file(stem, sections, fmt)


def export_setup(name: str, fus: list[dict], methods: list[tuple], fmt: str):
    stem, sections = _setup_sections(name, fus, [tuple(m) for m in methods])
    return _file(stem, sections, fmt)
