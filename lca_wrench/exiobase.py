"""EXIOBASE 3 (multi-regional input-output table) as a background database, with bw2io's importer.

EXIOBASE describes the world economy as about 200 products (or 163 industries) in 49 regions: 9'800 sectors in
million euro, each with its emissions and resource use. In LCA Wrench it is a background database like ecoinvent:
calculated alone (single), or next to process data (combined), e.g. a model that buys services in euro from
EXIOBASE and materials in kg from ecoinvent (hybrid LCA). The table is dense (about a third of all entries are not
zero), so the engine solves it with a dense LU (engine.BlockSolver), about 0.8 GB of memory.

Source: the zip from Zenodo (IOT_<year>_pxp.zip or _ixi.zip, 0.6 to 1 GB), a downloaded file, or the unpacked
folder. bw2io links the emissions to the project's biosphere by name and compartment; flows without a counterpart
there go into a biosphere database of their own (`<name> biosphere`). Unlike bw2io's own import, an emission that
cannot be linked at all is left out and counted instead of breaking the import. bw2io adds the factors of two
EXIOBASE flows (PFC and HFC, given in CO2-eq) to every method in kg CO2-eq; this happens last, and is undone if the
import fails.

Runs as a separate process (python -m lca_wrench.exiobase, task as JSON on stdin), so the app stays usable.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

VERSIONS = {  # bw2io's Zenodo records
    "3.8.2": "https://zenodo.org/record/5589597/files/IOT_{year}_{system}.zip?download=1",
    "3.8.1": "https://zenodo.org/record/4588235/files/IOT_{year}_{system}.zip?download=1",
    "3.8": "https://zenodo.org/record/4277368/files/IOT_{year}_{system}.zip?download=1",
}
YEARS = list(range(1995, 2023))


def say(kind: str, text: str) -> None:
    print(f"@{kind} {text}", flush=True)


def default_name(version: str | None, year: int | None, system: str) -> str:
    return f"EXIOBASE {version or '3'} {year or ''} {'products' if system == 'pxp' else 'industries'}".replace("  ", " ")


def write(path, name: str, biosphere: str) -> dict:
    """Import the table at `path` (zip or folder) as database `name`, emissions linked to `biosphere`."""
    import bw2data as bd
    from bw2data.backends.iotable import IOTableBackend
    from bw2io.importers.exiobase3_monetary import Exiobase3MonetaryImporter
    from bw2io.strategies.exiobase import add_biosphere_ids, add_product_ids

    say("phase", "read")
    ex = Exiobase3MonetaryImporter(path, name)
    ex.apply_strategies()
    # re-read the metadata before writing: the app may have added databases while this process read the table
    bd.databases.load()
    new_bio = _new_biosphere(ex, name)
    add_biosphere_ids(ex.biosphere_correspondence, [new_bio, biosphere])
    ex.write_activities_as_database()
    add_product_ids(ex.products, name)
    products = {(o["name"], o["location"]): o["id"] for o in ex.products}
    flows = {o["exiobase name"]: o["id"] for o in ex.biosphere_correspondence if "id" in o}
    scales = {o["exiobase name"]: float(o["scale factor"]) for o in ex.biosphere_correspondence if "id" in o}
    left_out: dict[str, int] = {}

    renamed = {"PFC - air": "PFC (CO2-eq)", "HFC - air": "HFC (CO2-eq)"}  # as bw2io renames them in its table

    def biosphere_rows():
        for flow, col, amount in ex.biosphere_iterator:
            flow = renamed.get(flow, flow)
            if flow not in flows:
                left_out[flow] = left_out.get(flow, 0) + 1
                continue
            yield {"row": flows[flow], "col": products[col], "amount": amount * scales[flow], "flip": False,
                   "uncertainty_type": 0}

    technosphere = itertools.chain(
        ({"row": products[x], "col": products[y], "amount": z, "flip": True, "uncertainty_type": 0}
         for x, y, z in ex.techosphere_iterator),
        ({"row": i, "col": i, "amount": 1, "flip": False, "uncertainty_type": 0} for i in products.values()))
    say("phase", "write")
    IOTableBackend(name).write_exchanges(technosphere, biosphere_rows(), [new_bio, biosphere])
    bd.databases.load()
    meta = dict(bd.databases[name])
    meta["lca_wrench"] = {"kind": "mrio", "source": str(path)}
    bd.databases[name] = meta
    bd.databases.flush()
    say("phase", "methods")
    bd.methods.load()
    patched = _patch_methods(new_bio)
    return {"database": name, "biosphere": new_bio, "sectors": len(products), "flows": len(flows),
            "left_out": sorted(left_out), "patched_methods": patched}


def _new_biosphere(ex, name: str) -> str:
    """bw2io's database for the EXIOBASE flows ecoinvent does not have, with the node type set (emission), so that
    Brightway (and LCA Wrench) see it as a biosphere database."""
    import bw2data as bd

    bio = name + " biosphere"
    data = {(bio, o["exiobase name"]): {"name": o["exiobase name"], "unit": o["exiobase unit"],
                                        "categories": (o["ecoinvent category"],), "comment": o["comment"],
                                        "type": "emission", "exchanges": []}
            for o in ex.biosphere_correspondence if o["new flow"]}  # as bw2io: every flow of its table
    db = bd.Database(bio)
    if bio not in bd.databases:
        db.register(format="EXIOBASE 3 New Biosphere", filepath=str(ex.dirpath))
    db.write(data)
    return bio


_BACKUP: dict = {}


def _patch_methods(new_bio: str) -> int:
    """bw2io's step: the PFC and HFC flows of EXIOBASE (in kg CO2-eq) count 1 in every method in kg CO2-eq."""
    import bw2data as bd

    have = {a["code"] for a in bd.Database(new_bio)}
    add = [((new_bio, f), 1) for f in ("PFC (CO2-eq)", "HFC (CO2-eq)") if f in have]
    n = 0
    for mt, meta in list(bd.methods.items()):
        if meta.get("unit") == "kg CO2-Eq" and add:
            m = bd.Method(mt)
            data = m.load()
            _BACKUP[mt] = list(data)
            m.write(list(data) + add)
            n += 1
    return n


def _undo_methods() -> None:
    import bw2data as bd

    for mt, data in _BACKUP.items():
        if mt in bd.methods:
            bd.Method(mt).write(data)


def _download(version: str, year: int, system: str, into: Path) -> Path:
    from bw2io.download_utils import download_with_progressbar

    say("phase", "download")
    url = VERSIONS[version].format(year=year, system=system)
    return Path(download_with_progressbar(url, dirpath=into))


def main() -> int:
    cfg = json.loads(sys.stdin.read())
    parent = os.getppid()

    def watch():
        while True:
            time.sleep(5)
            if os.getppid() != parent:
                os._exit(1)

    threading.Thread(target=watch, daemon=True).start()
    import bw2data as bd

    bd.projects.set_current(cfg["project"], update=False)
    before = set(bd.databases)
    tmp = Path(tempfile.mkdtemp(prefix="lca-wrench-exiobase-"))
    try:
        path = Path(cfg["path"]).expanduser() if cfg.get("path") else _download(cfg["version"], int(cfg["year"]),
                                                                                  cfg["system"], tmp)
        info = write(path, cfg["name"], cfg["biosphere"])
        say("done", json.dumps(info))
        return 0
    except BaseException as e:  # noqa: BLE001 - reported to the app, then cleaned up
        traceback.print_exc(file=sys.stdout)
        try:
            bd.methods.load()
            _undo_methods()
            bd.databases.load()  # the app may have added databases meanwhile: keep them
            for name in {cfg["name"], cfg["name"] + " biosphere"} - before:
                if name in bd.databases:
                    del bd.databases[name]
        except Exception:
            traceback.print_exc(file=sys.stdout)
        say("error", f"{type(e).__name__}: {e}".replace("\n", " ")[:2000])
        return 1
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
