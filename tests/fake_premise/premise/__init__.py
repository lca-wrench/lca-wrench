"""A stand-in for premise in the tests: same interface as premise 2.5 (NewDatabase, update,
write_db_to_brightway), but the "scenario" only scales electricity inputs by the factor in the pathway
name ("TEST-50" -> 0.5; "TEST-60-LATE" fails after writing). Lets the job, the worker and the cleanup run without
ecoinvent and without a key."""

import copy
import os
import time
from pathlib import Path

import bw2data as bd

__version__ = (2, 5, 2)


class NewDatabase:
    def __init__(self, scenarios, source_db, source_version, system_model="cutoff", key=None,
                 biosphere_name="biosphere3", **kw):
        if key != "x" * 44:
            raise ValueError("The key must be 44 bytes long")
        for s in scenarios:  # like premise: it adds to the scenario dicts it gets, a path among them
            s["filepath"] = Path(__file__).parent
            s["database"] = []
        self.scenarios, self.source_db = scenarios, source_db
        self.data = None

    def update(self, sectors=None):
        gate = os.environ.get("FAKE_PREMISE_GATE")
        if gate:  # a test changes the project while "premise" runs: say so, then wait for its go
            Path(gate, "ready").touch()
            for _ in range(600):
                if Path(gate, "go").exists():
                    break
                time.sleep(0.1)
        if any(s["pathway"] == "TEST-FAIL" for s in self.scenarios):
            raise RuntimeError("scenario failed on purpose")
        self.data = bd.Database(self.source_db).load()

    def write_db_to_brightway(self, name=None):
        for nm, sc in zip(name, self.scenarios):
            factor = int(sc["pathway"].split("-")[1]) / 100
            data = {}
            for (db, code), ds in copy.deepcopy(self.data).items():
                for exc in ds.get("exchanges", []):
                    if exc["input"][0] == self.source_db:
                        sup = self.data[tuple(exc["input"])]
                        if "electricity" in sup["name"] and exc["type"] == "technosphere":
                            exc["amount"] *= factor
                        if exc["type"] == "biosphere":
                            pass
                        exc["input"] = (nm, exc["input"][1])
                    if tuple(exc.get("output", ())) and exc["output"][0] == self.source_db:
                        exc["output"] = (nm, exc["output"][1])
                if "electricity" in ds["name"]:
                    for exc in ds["exchanges"]:
                        if exc["type"] == "biosphere":
                            exc["amount"] *= factor
                data[(nm, code)] = ds
            db = bd.Database(nm)
            db.register()
            db.write(data)
        for nm in name:  # something JSON cannot hold, left in the metadata unwritten: the worker must still cope
            bd.databases.data[nm]["scratch"] = Path(__file__).parent
        if any(sc["pathway"].endswith("-LATE") for sc in self.scenarios):
            raise RuntimeError("failed after writing, on purpose")
