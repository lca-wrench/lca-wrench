"""Processes with several products, stored as the Activity Browser 3 stores them (bw_functional, backend
"functional_sqlite").

A process and its products are nodes of their own. Each product names its process (`processor`), carries
properties (mass, price ... per unit of product; with `normalize`, multiplied by the amount produced) and the share
of the process's inputs and emissions it bears (`allocation_factor`). The process says how these shares are found
(`allocation`): "equal", the name of a property all its products have, or "manual". bw_functional splits the
inputs and emissions onto the products when it prepares the database for bw2calc; LCA Wrench's engine does the same
when it builds the model matrices (engine.Foreground), so both calculate the same.

Importing this module registers the backend with Brightway, so such databases open at all. bw_functional also brings
a project's databases to its current data structure whenever a project is opened, and records that in the project.
LCA Wrench changes no project without asking, so that hook is switched off here: the update runs only right before
LCA Wrench itself writes into such a database (`ensure_current`), as the Activity Browser 3 does on opening.
"""

from __future__ import annotations

import bw2data as bd
import bw_functional
from bw2data.signals import project_changed
from bw_functional import Process, Product
from loguru import logger

project_changed.disconnect(bw_functional._check_and_update)
logger.disable("bw_functional")  # its debug messages would fill the console window the app runs in

BACKEND = "functional_sqlite"
FIXED = ("equal", "manual")


def is_functional(database: str) -> bool:
    return (bd.databases.get(database) or {}).get("backend") == BACKEND


def ensure_current() -> None:
    """The update bw_functional runs when a project is opened, here only before LCA Wrench writes into a database."""
    ds = bd.projects.dataset
    if ds.data is None:
        ds.data = {}
    current = ds.data.get("bw_functional_version")
    if current != bw_functional.latest:
        ds.data["bw_functional_version"] = bw_functional.update(current)
        ds.save()


def process_of(node) -> Process | None:
    """The process of a product, or the process itself; None for anything not stored the bw_functional way."""
    if isinstance(node, Product):
        return node.processor
    if isinstance(node, Process):
        return node
    return None


def strategy(process: Process) -> str:
    return process.get("allocation") or (bd.databases.get(process["database"]) or {}).get("default_allocation") or "equal"


def strategies(process: Process) -> list[str]:
    """Ways to split this process: equally, by each property all its products have, or by hand."""
    return ["equal", *sorted(process.available_properties()), "manual"]


def _amount(product: Product) -> float:
    edge = product.processing_edge
    return float(edge["amount"]) if edge is not None else 0.0


def _property_value(product: Product, label: str) -> float:
    """As bw_functional's get_property_value: a normalized property is multiplied by the amount produced."""
    prop = (product.get("properties") or {}).get(label)
    if prop is None:
        raise KeyError(label)
    if isinstance(prop, (int, float)):
        return float(prop)
    amount = float(prop.get("amount") or 0.0)
    return abs(_amount(product)) * amount if prop.get("normalize", False) else amount


def factors(process: Process, label: str) -> dict[int, float]:
    """{product id: factor} the strategy `label` gives, without saving anything (bw_functional's generic_allocation:
    a product substituted elsewhere bears nothing)."""
    products = process.products()
    eligible = [p for p in products if p.get("substitution_factor", 0) <= 0]
    if label == "equal":
        values = {p.id: 1.0 for p in eligible}
    elif label == "manual":
        values = {p.id: float(p.get("allocation_factor", 1) or 0.0) for p in eligible}
    else:
        values = {p.id: _property_value(p, label) for p in eligible}
    total = sum(values.values())
    if not total:
        raise ValueError(f"{label}: sum is zero")
    out = {p.id: 0.0 for p in products}
    out.update({pid: v / total for pid, v in values.items()})
    return out


def info(process: Process) -> dict:
    """The products of a process with their amounts, properties and shares, for the data sheet."""
    products = []
    for p in process.products():
        products.append({"id": str(p.id), "name": p.get("product") or p.get("reference product") or p["name"],
                         "amount": _amount(p), "unit": p.get("unit"), "factor": p.get("allocation_factor"),
                         "waste": p.get("type") == "waste",
                         "properties": {k: (v if isinstance(v, dict) else {"amount": v})
                                        for k, v in (p.get("properties") or {}).items()}})
    return {"process": str(process.id), "process_name": process["name"], "strategy": strategy(process),
            "strategies": strategies(process), "products": products,
            "sum": sum(1.0 if x["factor"] is None else float(x["factor"]) for x in products)}


def set_allocation(process: Process, label: str, manual: dict[int, float] | None = None) -> None:
    """Split the process by `label`; with "manual", by the shares given (bw_functional scales them to add up to 1)."""
    if label not in strategies(process):
        raise ValueError(label)
    ensure_current()
    if label == "manual" and manual:
        for p in process.products():
            if p.id in manual:
                p["allocation_factor"] = float(manual[p.id])
                p.save()
    if process.get("allocation") != label:
        process["allocation"] = label
        process.save()  # bw_functional allocates when the strategy changes
    else:
        process.allocate()
