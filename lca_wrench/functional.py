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

import uuid

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


# ---------- building models in this format ----------

_NOT_COPIED = {"id", "database", "code", "type", "reference product", "product", "unit", "production amount",
               "exchanges", "processor", "allocation_factor", "properties", "allocation"}


def add_product(process: Process, name: str, unit: str | None, amount: float = 1.0) -> Product:
    """A further product of the process, with its own production; bw_functional saves the process again (its type:
    one product or several) and allocates it anew."""
    prod = process.new_product(code=uuid.uuid4().hex, product=(name or "").strip() or process["name"], unit=unit or "unit")
    prod.save()
    if float(amount) != 1.0:
        edge = prod.processing_edge
        edge["amount"] = float(amount)
        edge.save()
    return bd.get_node(id=prod.id)


def new_process(database: str, name: str, location: str, comment: str, product: str, unit: str) -> Process:
    """A process with one product, as the Activity Browser 3 makes it: a process node and a product node."""
    proc = bd.Database(database).new_node(code=uuid.uuid4().hex, name=name, location=location, comment=comment)
    proc.save()
    add_product(proc, product, unit)
    return bd.get_node(id=proc.id)


def copy_classic(src, database: str) -> Process:
    """A dataset stored the classic way (process and product in one node, e.g. from BAFU or ecoinvent) as process and
    product in a database of this format, with all its inputs and emissions."""
    proc = bd.Database(database).new_node(code=uuid.uuid4().hex, **{k: v for k, v in src.items() if k not in _NOT_COPIED})
    proc.save()
    production = [e for e in src.exchanges() if e["type"] == "production"]
    add_product(proc, src.get("reference product") or src["name"], src.get("unit"),
                float(production[0]["amount"]) if production else 1.0)
    for e in src.exchanges():
        if e["type"] != "production":
            proc.new_edge(**{k: v for k, v in e.as_dict().items() if k not in ("output", "id")}).save()
    return bd.get_node(id=proc.id)


def allocated(product: Product) -> dict:
    """The product's share of its process as one classic dataset (bw_functional's own conversion: every input and
    emission times the allocation factor, a formula times it too), for copying into a classic model."""
    proc = product.processor
    factor = product.get("allocation_factor")
    share = float(factor) if isinstance(factor, (int, float)) and not isinstance(factor, bool) else 1.0
    data = {k: v for k, v in proc.items() if k not in _NOT_COPIED}
    data.update({"type": "processwithreferenceproduct", "reference product": product.get("product") or product["name"],
                 "unit": product.get("unit")})
    exchanges = []
    for e in proc.exchanges():
        ex = {k: v for k, v in e.as_dict().items() if k not in ("output", "id")}
        if e["type"] == "production":
            if e.input.id != product.id:
                continue
            ex["input"] = None  # the copy itself
        elif share != 1.0:
            ex["amount"] = float(ex["amount"]) * share
            if ex.get("formula"):
                ex["formula"] = f"({ex['formula']}) * {share!r}"
        exchanges.append(ex)
    return {"data": data, "exchanges": exchanges, "share": share}


def copy_process(process: Process, database: str) -> Process:
    """A copy of a process with all its products, their properties and its allocation. Not bw_functional's own
    Process.copy: in version 0.1.1 it deletes the copied production edges one by one, and deleting a production edge
    deletes the product it points to, which is still the original's."""
    new = bd.Database(database).new_node(code=uuid.uuid4().hex, allocation=process.get("allocation"),
                                         **{k: v for k, v in process.items() if k not in _NOT_COPIED})
    new.save()
    manual = strategy(process) == "manual"
    for p in process.products():
        q = add_product(new, p.get("product") or p["name"], p.get("unit"), _amount(p))
        if p.get("properties") or manual:
            q["properties"] = dict(p.get("properties") or {})
            if manual and p.get("allocation_factor") is not None:
                q["allocation_factor"] = p["allocation_factor"]
            q.save()
    for e in process.exchanges():
        if e["type"] != "production":
            new.new_edge(**{k: v for k, v in e.as_dict().items() if k not in ("output", "id")}).save()
    new = bd.get_node(id=new.id)
    new.allocate()
    return new
