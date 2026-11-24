"""Runs premise in its own Python environment and writes the scenario databases into a project.

Started by scenarios.py with the Python of the premise environment (premise needs older numpy, pandas and scipy than
LCA Wrench, so it does not live in the app's environment). This file imports nothing from LCA Wrench: only the
standard library, bw2data and premise. The task comes as JSON on stdin (the decryption key must not show up in the
process list), progress goes to stdout as lines "@phase <step>", the end as "@done <json>" or "@error <text>".
Databases this run made are removed again when it fails.
"""

import copy
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path


def say(kind: str, text: str) -> None:
    print(f"@{kind} {text}", flush=True)


def _exit_when_orphaned() -> None:
    parent = os.getppid()

    def watch():
        while True:
            time.sleep(5)
            if os.getppid() != parent:
                os._exit(1)

    threading.Thread(target=watch, daemon=True).start()


# bw2data keeps the list of a project's databases in databases.json. When a value in it cannot be written as JSON,
# its "atomic" write still swaps the new file in: databases.json is then EMPTY and the whole project cannot be
# opened any more (by Brightway, the Activity Browser or LCA Wrench). premise adds paths and data to the scenario
# descriptions it is given, so nothing of those goes into the metadata, every write is checked first, and the list
# as it was before the run is put back should it ever be unreadable.

def _plain(value):
    """A copy of `value` that JSON can store (paths and other objects as text)."""
    return json.loads(json.dumps(value, default=str))


def _make_writable(bd) -> None:
    data = bd.databases.data
    try:
        json.dumps(bd.databases.pack(data))
    except (TypeError, ValueError):
        for name in list(data):
            data[name] = _plain(data[name])


def _restore_if_unreadable(listing: Path, saved: bytes) -> bool:
    try:
        json.loads(listing.read_bytes())
        return False
    except (OSError, ValueError):
        tmp = listing.with_name(listing.name + ".lca-wrench-tmp")
        tmp.write_bytes(saved)
        os.replace(tmp, listing)
        return True


def _reload(bd, names: list) -> None:
    """Re-read databases.json before writing it: the app may have added databases (the user's models) while premise
    ran, and bw2data writes its in-memory copy as it is. Only this run's own entries are kept from memory."""
    own = {n: bd.databases.data[n] for n in names if n in bd.databases.data}
    bd.databases.load()
    bd.databases.data.update(own)


def _clean_up(bd, listing: Path, saved: bytes, before: set, names: list) -> None:
    """Remove what this run made (also databases whose metadata got lost), and leave a readable database list.
    Only this run's databases: others that appeared meanwhile are the user's."""
    _restore_if_unreadable(listing, saved)
    _reload(bd, names)
    for name in sorted(set(names) - before):
        try:
            if name in bd.databases:
                _make_writable(bd)
                del bd.databases[name]
            else:
                bd.Database(name).delete(warn=False, signal=False)  # its rows, should premise have written them
        except Exception:
            traceback.print_exc(file=sys.stdout)
    _restore_if_unreadable(listing, saved)


def main() -> int:
    cfg = json.loads(sys.stdin.read())
    _exit_when_orphaned()
    import bw2data as bd

    bd.projects.set_current(cfg["project"], update=False)
    listing = Path(bd.projects.dir) / "databases.json"
    saved = listing.read_bytes()  # the database list before the run
    before = set(bd.databases)
    try:
        say("phase", "load")
        os.chdir(tempfile.mkdtemp(prefix="lca-wrench-premise-"))  # premise writes logs into the folder it starts in
        from premise import NewDatabase

        wanted = [{"model": s["model"], "pathway": s["pathway"], "year": int(s["year"])} for s in cfg["scenarios"]]
        # premise adds to the dicts it gets (the folder of its IAM files as a path, the database, the IAM data)
        ndb = NewDatabase(scenarios=copy.deepcopy(wanted), source_db=cfg["source_db"],
                          source_version=cfg["source_version"], system_model=cfg["system_model"],
                          key=cfg.get("key") or None, biosphere_name=cfg["biosphere"], generate_reports=False,
                          quiet=True)
        say("phase", "update")
        ndb.update()
        say("phase", "write")
        _reload(bd, cfg["names"])
        ndb.write_db_to_brightway(name=cfg["names"])
        _reload(bd, cfg["names"])
        for name, sc in zip(cfg["names"], wanted):
            bd.databases.data[name]["lca_wrench"] = {"kind": "scenario", "scenario": {**sc, "source": cfg["source_db"]}}
        _make_writable(bd)
        bd.databases.flush()
        if _restore_if_unreadable(listing, saved):
            raise RuntimeError("databases.json could not be written")
        say("done", json.dumps({"databases": cfg["names"]}))
        return 0
    except BaseException as e:  # noqa: BLE001 - reported to the app, then cleaned up
        traceback.print_exc(file=sys.stdout)
        try:
            _clean_up(bd, listing, saved, before, cfg["names"])
        except Exception:
            traceback.print_exc(file=sys.stdout)
        say("error", f"{type(e).__name__}: {e}".replace("\n", " ")[:2000])
        return 1


if __name__ == "__main__":
    sys.exit(main())
