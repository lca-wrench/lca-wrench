"""FastAPI layer: thin JSON wrapper around the service modules plus the static UI.

Runs only on 127.0.0.1. Requests with a foreign Host header are rejected so
that websites in the browser cannot talk to the local API (DNS rebinding), and
so are requests another website sends from the browser (cross-site: Origin
or Sec-Fetch-Site), which could otherwise trigger simple POSTs such as a copy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import bw2data as bd
from bw2data.backends.schema import ExchangeDataset
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import beispiel, crosswalk, ecoinvent, excel, i18n, imports, overview, params, reproject, versions
from . import models as mdl
from . import service as s
from . import setups as cs
from .i18n import _

STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

START_PROJECT = os.environ.get("LCA_WRENCH_PROJECT")

# LCA_WRENCH_LOG: a file for errors (the Mac start script sets it), so a problem on someone else's computer can be sent along
if os.environ.get("LCA_WRENCH_LOG"):
    _handler = logging.FileHandler(os.environ["LCA_WRENCH_LOG"], encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for _name in ("lca_wrench", "uvicorn.error"):
        logging.getLogger(_name).addHandler(_handler)
    logging.getLogger("lca_wrench").setLevel(logging.INFO)
log = logging.getLogger("lca_wrench")


def _warm_up():
    """Open the start project and build the matrix cache so the first click is fast."""
    with s.LOCK:
        version = Path(__file__).parent.parent / "VERSION"
        log.info("Start, version %s, Brightway folder %s, bw2data %s, bw2calc %s",
                 version.read_text().strip() if version.is_file() else "?", bd.projects._base_data_dir,
                 bd.__version__, getattr(__import__("bw2calc"), "__version__", "?"))
        start = s.open_start_project(START_PROJECT)
        if not start:
            return  # the user chooses a project on the start page
        try:
            st = s.state()
            if st["default_method"]:
                mdl.system().bg.unit_scores(tuple(st["default_method"]))
        except ValueError:
            pass
        except Exception:  # state() reports it to the UI; here only the log
            log.exception("Preparing %s failed", start)
        s.acknowledge()


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="LCA Wrench", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": _("Nur lokal erreichbar.")}, status_code=403)
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
            origin and origin != "null" and urlsplit(origin).hostname not in ALLOWED_HOSTS):
        return JSONResponse({"detail": _("Nur lokal erreichbar.")}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def revalidate_ui(request: Request, call_next):
    """The UI files are checked with the server on every load (cheap: 304 when unchanged), so that after an
    update the browser never mixes old and new JavaScript modules from its cache."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"  # the versioned /ui/ files set their own (immutable)
    return response


@app.middleware("http")
async def language(request: Request, call_next):
    """Messages in the language of the UI (registered last, so it runs first)."""
    lang = request.headers.get("x-lang") or request.query_params.get("lang")
    i18n.LANG.set(lang if lang in ("de", "en") else i18n.DEFAULT)
    return await call_next(request)


# what works before a project is open: the state, choosing a project, copying one
_WITHOUT_PROJECT = {s.state, s.poll, s.set_project, s.copy_project_files, s.copy_older_project, imports.create_project,
                    imports.start}


def run(fn, *args, **kwargs):
    with s.LOCK:
        try:
            s.sync_external()
            if fn not in _WITHOUT_PROJECT and not s.project_open():
                raise HTTPException(409, _("Bitte zuerst oben ein Projekt wählen."))
            try:
                return fn(*args, **kwargs)
            finally:
                s.acknowledge()
        except s.ReadOnlyError as e:
            raise HTTPException(409, str(e))
        except (KeyError, bd.errors.UnknownObject, ExchangeDataset.DoesNotExist) as e:
            raise HTTPException(404, str(e).strip("'\"") or _("Nicht gefunden."))
        except ValueError as e:
            raise HTTPException(400, str(e))


# ---------- request bodies ----------

class ProjectIn(BaseModel):
    name: str
    rebuild: bool = False  # open it even though Brightway converts it on opening


class ActIn(BaseModel):
    id: str  # Brightway ids are 64-bit, too large for JavaScript numbers
    method: list[str]


class CalcIn(ActIn):
    amount: float = Field(1.0, gt=0)


class GraphIn(CalcIn):
    cutoff: float = Field(0.01, ge=0, le=0.5)
    depth: int = Field(4, ge=1, le=8)


class SankeyIn(CalcIn):
    cutoff: float = Field(0.02, ge=0.001, le=0.5)
    max_nodes: int = Field(40, ge=2, le=150)


class InvIn(BaseModel):
    id: str
    amount: float = Field(1.0, gt=0)
    method: list[str] | None = None


class FuIn(BaseModel):
    id: str
    amount: float


class ResultsIn(BaseModel):
    fus: list[FuIn] = Field(..., min_length=1, max_length=60)
    methods: list[list[str]] = Field(..., min_length=1, max_length=200)


BigId = int | str  # Brightway ids are 64-bit; JavaScript sends them as strings


class EditIn(BaseModel):
    exchange: BigId
    amount: float


class UndoIn(BaseModel):
    exchange: BigId


class CompareItem(BaseModel):
    project: str
    id: str
    amount: float = Field(1.0, gt=0)
    background: list[str] | None = None  # background databases to calculate it with (None: as chosen in the project)


class BackgroundIn(BaseModel):
    mode: str
    databases: list[str] = []


class CompareIn(BaseModel):
    items: list[CompareItem]
    method: list[str]


class FlowmapIn(BaseModel):
    enabled: bool


class NameIn(BaseModel):
    name: str


class ProcessIn(BaseModel):
    database: str
    name: str
    unit: str = "unit"
    location: str = "CH"
    product: str | None = None
    comment: str = ""


class CopyIn(BaseModel):
    id: str
    database: str


class ProcessUpdateIn(BaseModel):
    id: str
    fields: dict[str, str]


class IdIn(BaseModel):
    id: str


class AllocationIn(BaseModel):
    id: str
    strategy: str
    manual: dict[str, float] | None = None  # {product id: share}, for "manual"


class ExchangeAddIn(BaseModel):
    id: str
    input: str
    amount: float = 1.0
    kind: str | None = None


class ExchangeUpdateIn(BaseModel):
    exchange: BigId
    amount: float | None = None
    kind: str | None = None


class UncertaintyIn(BaseModel):
    exchange: BigId
    spec: dict | None = None


class ExchangeIn(BaseModel):
    exchange: BigId


class JournalUndoIn(BaseModel):
    n: int | None = None


class ReprojectIn(BaseModel):
    database: str
    location: str = Field(..., min_length=1, max_length=80)
    scope: str = Field("electricity", pattern="^(electricity|all)$")
    name: str | None = Field(None, max_length=120)
    databases: list[str] | None = Field(None, max_length=200)  # several models moved together


class CategoriesIn(BaseModel):
    id: str
    amount: float = Field(1.0, gt=0)
    families: list[str] = Field(..., min_length=1, max_length=2)  # ["*"]: all methods
    topic: str | None = Field(None, max_length=40)


class ExportResultIn(CalcIn):
    families: list[str] | None = Field(None, max_length=4)
    topic: str | None = Field(None, max_length=40)
    format: str = Field("xlsx", pattern="^(csv|xlsx)$")


class ExportSetupIn(ResultsIn):
    name: str = Field("LCA Wrench", max_length=120)
    format: str = Field("xlsx", pattern="^(csv|xlsx)$")


class MonteCarloIn(ResultsIn):
    n: int = Field(500, ge=1, le=10000)
    seed: int | None = None
    workers: int | None = Field(None, ge=1, le=16)


class SensitivityIn(BaseModel):
    id: str
    amount: float = Field(1.0, gt=0)
    method: list[str]
    n: int = Field(300, ge=20, le=5000)
    seed: int | None = None
    workers: int | None = Field(None, ge=1, le=16)


class SetupIn(BaseModel):
    name: str
    old_name: str | None = None
    fus: list[FuIn] = Field(default_factory=list, max_length=60)
    methods: list[list[str]] = Field(default_factory=list, max_length=200)


def _method(m: list[str]) -> tuple:
    t = tuple(m)
    if t not in bd.methods:
        raise HTTPException(404, _("Diese Wirkungsmethode gibt es in diesem Projekt nicht."))
    return t


# ---------- project and data ----------

@app.get("/api/poll")
def get_poll():
    return run(s.poll)


@app.get("/api/state")
def get_state():
    return run(s.state)


@app.post("/api/project")
def post_project(body: ProjectIn):
    run(s.set_project, body.name, body.rebuild)
    return run(s.state)


@app.post("/api/project/copy")
def post_project_copy(body: ProjectIn):
    """A test copy of a project (any format): the original is only read. Can take minutes (ecoinvent)."""
    return {"project": run(s.copy_project_files, body.name), "state": run(s.state)}


@app.post("/api/project/copy-older")
def post_project_copy_older(body: ProjectIn):
    """A Brightway 2 project (Activity Browser 2): copy it and convert only the copy. Can take minutes (ecoinvent)."""
    return {"project": run(s.copy_older_project, body.name), "state": run(s.state)}


@app.post("/api/project/new")
def post_project_new(body: ProjectIn):
    """A new, empty project, then opened."""
    return {"project": run(imports.create_project, body.name), "state": run(s.state)}


# ---------- importing data: BAFU 2026, ecoinvent (background jobs) ----------

class ImportIn(BaseModel):
    name: str = Field(max_length=100)
    source: str
    version: str = ""
    system_model: str = ""
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)
    remember: bool = False
    lci_path: str | None = Field(default=None, max_length=1000)
    lcia_path: str | None = Field(default=None, max_length=1000)
    add: bool = False  # one more database in the open project
    # premise
    source_db: str | None = None
    model: str | None = None
    pathway: str | None = None
    years: list[int] = []
    key: str | None = Field(default=None, max_length=200)
    # EXIOBASE
    path: str | None = Field(default=None, max_length=1000)
    biosphere: str | None = None
    db_name: str | None = Field(default=None, max_length=200)
    system: str = "pxp"
    year: int | None = None


class LoginIn(BaseModel):
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)


@app.get("/api/import/options")
def get_import_options():
    return imports.options()  # takes the lock itself, briefly: an import may hold it for long


@app.post("/api/import/start")
def post_import_start(body: ImportIn):
    """Starts the import into a new or empty project; follow it with /api/import/status. ecoinvent takes 10-30 min."""
    return run(imports.start, body.name, body.source, body.model_dump(exclude={"name", "source"}))


@app.get("/api/import/status")
def get_import_status(id: str | None = None):
    """No lock: answers while the import holds it. Without id: the running import, if any (after a page reload)."""
    try:
        return {"job": imports.status(id)}
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))


@app.post("/api/ecoinvent/versions")
def post_ecoinvent_versions(body: LoginIn):
    """Log in at ecoinvent with the user's account and list the releases it may download. Touches no project."""
    if not ecoinvent.available():
        raise HTTPException(400, _("Für den Import von ecoinvent fehlt das Paket ecoinvent_interface. Installiere "
                                   "LCA Wrench neu (Installationsskript), dann ist es dabei."))
    try:
        return {"versions": ecoinvent.versions(body.username, body.password)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/ecoinvent/guess")
def get_ecoinvent_guess(path: str = ""):
    """Version and system model from the name of a file downloaded from ecoinvent.org."""
    return ecoinvent.guess_from_filename(path)


@app.get("/api/search")
def get_search(q: str = "", loc: str | None = None, limit: int = 60, db: str | None = None, kind: str = "process",
               unit: str | None = None, comp: str | None = None):
    return run(s.search, q, loc or None, min(max(limit, 1), 200), db or None, "flow" if kind == "flow" else "process",
               unit or None, comp or None)


@app.get("/api/search/options")
def get_search_options():
    return run(s.search_options)


@app.post("/api/models/reproject/plan")
def post_reproject_plan(body: ReprojectIn):
    p = run(reproject.plan, body.database, body.location, body.scope)
    return {"target": p["target"], "near": p["near"], "missing": p["missing"],
            "swaps": [{k: v for k, v in x.items() if k != "to"} for x in p["swaps"].values()]}


@app.post("/api/models/reproject")
def post_reproject(body: ReprojectIn):
    if body.databases:
        made = run(reproject.reproject_many, body.databases, body.location, body.scope)
        return {**made[0], "made": made, "state": run(s.state)}
    r = run(reproject.reproject, body.database, body.location, body.scope, body.name)
    return {**r, "made": [r], "state": run(s.state)}


@app.post("/api/categories")
def post_categories(body: CategoriesIn):
    return run(overview.categories, body.id, body.amount, body.families, body.topic or None)


def _download(data: bytes, filename: str, media: str) -> Response:
    return Response(data, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@app.post("/api/export/result")
def post_export_result(body: ExportResultIn):
    return _download(*run(overview.export_result, body.id, body.amount, _method(body.method), body.families, body.format,
                            body.topic or None))


@app.post("/api/export/setup")
def post_export_setup(body: ExportSetupIn):
    methods = [_method(m) for m in body.methods]
    return _download(*run(overview.export_setup, body.name, [f.model_dump() for f in body.fus], methods, body.format))


@app.post("/api/activity")
def post_activity(body: ActIn):
    return run(s.activity, body.id, _method(body.method))


# ---------- results ----------

@app.post("/api/calc")
def post_calc(body: CalcIn):
    return run(s.calculate, body.id, body.amount, _method(body.method))


@app.post("/api/graph")
def post_graph(body: GraphIn):
    return run(s.graph, body.id, body.amount, _method(body.method), body.cutoff, body.depth)


@app.post("/api/sankey")
def post_sankey(body: SankeyIn):
    return run(s.sankey, body.id, body.amount, _method(body.method), body.cutoff, body.max_nodes)


@app.post("/api/inventory")
def post_inventory(body: InvIn):
    return run(s.inventory, body.id, body.amount, tuple(body.method) if body.method else None)


@app.post("/api/results")
def post_results(body: ResultsIn):
    methods = [_method(m) for m in body.methods]
    return run(cs.calculate, [f.model_dump() for f in body.fus], methods)


@app.post("/api/verify")
def post_verify(body: ResultsIn):
    methods = [_method(m) for m in body.methods]
    return run(s.verify, [f.model_dump() for f in body.fus], methods)


@app.post("/api/mc/start")
def post_mc_start(body: MonteCarloIn):
    methods = [_method(m) for m in body.methods]
    return run(s.monte_carlo_start, [f.model_dump() for f in body.fus], methods, body.n, body.seed, body.workers)


@app.post("/api/mc/sensitivity")
def post_mc_sensitivity(body: SensitivityIn):
    return run(s.sensitivity_start, {"id": body.id, "amount": body.amount}, _method(body.method), body.n, body.seed, body.workers)


@app.get("/api/mc/status")
def get_mc_status(id: str):
    return run(s.monte_carlo_status, id)


# ---------- working copies and comparison ----------

@app.post("/api/copy")
def post_copy():
    run(s.make_working_copy)
    return run(s.state)


@app.post("/api/edit")
def post_edit(body: EditIn):
    run(s.edit_exchange, int(body.exchange), body.amount)
    return run(s.state)


@app.post("/api/undo")
def post_undo(body: UndoIn):
    run(s.undo_change, int(body.exchange))
    return run(s.state)


@app.post("/api/why")
def post_why(body: CalcIn):
    return run(s.explain_difference, body.id, body.amount, _method(body.method))


class ParamIn(BaseModel):
    scope: str = Field(pattern="^(project|database|activity)$")
    name: str = Field(max_length=80)
    value: str = Field("", max_length=1000)
    database: str | None = None
    activity: str | None = None
    old_name: str | None = None
    view: str | None = None  # the model shown in the Parameter view


class FormulaIn(BaseModel):
    exchange: str
    formula: str = Field("", max_length=1000)


@app.get("/api/params")
def get_params(db: str | None = None):
    return run(params.overview, db or None)


@app.post("/api/params/set")
def post_params_set(body: ParamIn):
    run(params.set_parameter, body.scope, body.name, body.value, body.database, body.activity, body.old_name)
    return {"overview": run(params.overview, body.view or body.database), "state": run(s.state)}


@app.post("/api/params/delete")
def post_params_delete(body: ParamIn):
    run(params.delete_parameter, body.scope, body.name, body.database, body.activity)
    return {"overview": run(params.overview, body.view or body.database), "state": run(s.state)}


@app.post("/api/models/exchange/formula")
def post_exchange_formula(body: FormulaIn):
    run(params.set_exchange_formula, int(body.exchange), body.formula)
    return run(s.state)


class VersionsIn(BaseModel):
    id: str
    amount: float = Field(1.0, gt=0)
    method: list[str]
    project: str
    database: str


@app.get("/api/versions/targets")
def get_versions_targets(project: str):
    return run(versions.targets, project)


@app.post("/api/versions")
def post_versions(body: VersionsIn):
    return run(versions.compare, int(body.id), body.amount, _method(body.method), body.project, body.database)


@app.get("/api/versions/detail")
def get_versions_detail(k: int):
    return run(versions.detail, k)


# ---------- the same product with another background database (BAFU <-> ecoinvent) ----------

class CrosswalkIn(VersionsIn):
    target_method: list[str] | None = None


class CrosswalkTraceIn(BaseModel):
    source_id: str
    target_code: str
    scale_a: float
    scale_b: float
    method: list[str]
    project: str
    database: str
    target_method: list[str]


class CrosswalkSearchIn(BaseModel):
    project: str
    database: str
    q: str = Field(max_length=200)
    unit: str | None = None
    location: str | None = Field(None, max_length=80)


class CrosswalkChoiceIn(BaseModel):
    source_database: str
    source_code: str
    target_database: str
    target_code: str | None = None
    reset: bool = False
    price: float | None = None  # euro per unit of the product, for a sector of an input-output table


class CrosswalkConfirmIn(BaseModel):
    source_database: str
    target_database: str
    pairs: list[dict]


@app.get("/api/crosswalk/targets")
def get_crosswalk_targets(project: str):
    return run(crosswalk.targets, project)


@app.post("/api/crosswalk")
def post_crosswalk(body: CrosswalkIn):
    return run(crosswalk.compare, int(body.id), body.amount, _method(body.method), body.project, body.database,
               body.target_method)


@app.post("/api/crosswalk/trace")
def post_crosswalk_trace(body: CrosswalkTraceIn):
    return run(crosswalk.trace, int(body.source_id), body.target_code, body.scale_a, body.scale_b, _method(body.method),
               body.project, body.database, body.target_method)


@app.post("/api/crosswalk/search")
def post_crosswalk_search(body: CrosswalkSearchIn):
    return run(crosswalk.search, body.project, body.database, body.q, body.unit, body.location or None)


@app.post("/api/crosswalk/choose")
def post_crosswalk_choose(body: CrosswalkChoiceIn):
    run(crosswalk.choose, body.source_database, body.source_code, body.target_database, body.target_code, body.reset,
        body.price)
    return {"ok": True}


@app.post("/api/crosswalk/confirm")
def post_crosswalk_confirm(body: CrosswalkConfirmIn):
    return {"saved": run(crosswalk.confirm_all, body.source_database, body.target_database, body.pairs)}


@app.get("/api/crosswalk/export")
def get_crosswalk_export(source_database: str, target_database: str):
    data = run(crosswalk.export_mapping, source_database, target_database)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", data["name"]) + ".json"
    return Response(json.dumps(data, indent=1, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/crosswalk/import")
async def post_crosswalk_import(request: Request, source_database: str, target_database: str):
    if int(request.headers.get("content-length") or 0) > excel.MAX_BYTES:
        raise HTTPException(413, _("Die Datei ist zu gross (höchstens 25 MB)."))
    data = await request.body()
    return {"saved": run(crosswalk.import_mapping, source_database, target_database, data)}


@app.post("/api/background")
def post_background(body: BackgroundIn):
    return run(s.set_background, body.mode, body.databases)


@app.post("/api/background/remove")
def post_background_remove(body: NameIn):
    return run(s.remove_background, body.name)


@app.post("/api/completion")
def post_completion(body: FlowmapIn):
    """Completed factors for sub-compartments (completion.py): on or off."""
    return run(s.set_completion, body.enabled)


class MethodIn(BaseModel):
    method: list[str]


@app.post("/api/completion/factors")
def post_completion_factors(body: MethodIn):
    return run(s.completed_factors, tuple(body.method))


@app.post("/api/compare")
def post_compare(body: CompareIn):
    return run(s.compare, [i.model_dump() for i in body.items], tuple(body.method))


@app.post("/api/flowmap")
def post_flowmap(body: FlowmapIn):
    """Factors across flow lists through the flow mapping (flowmap.py): on or off."""
    return run(s.set_flowmap, body.enabled)


# ---------- own models ----------

@app.get("/api/models/processes")
def get_model_processes(db: str):
    return run(mdl.list_processes, db)


@app.post("/api/models/db")
def post_model_db(body: NameIn):
    run(mdl.create_database, body.name)
    return run(s.state)


@app.get("/api/models/export")
def get_model_export(db: str):
    data, filename = run(excel.export_model, db)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@app.post("/api/models/import")
async def post_model_import(request: Request, name: str | None = None):
    if int(request.headers.get("content-length") or 0) > excel.MAX_BYTES:  # before reading it all into memory
        raise HTTPException(413, _("Die Datei ist zu gross (höchstens 25 MB)."))
    data = await request.body()
    r = run(excel.import_model, data, name)
    return {**r, "state": run(s.state)}


@app.post("/api/models/db/delete")
def post_model_db_delete(body: NameIn):
    run(mdl.delete_database, body.name)
    return run(s.state)


@app.post("/api/models/process")
def post_model_process(body: ProcessIn):
    return {"id": run(mdl.create_process, body.database, body.name, body.unit, body.location, body.product, body.comment)}


@app.post("/api/models/copy")
def post_model_copy(body: CopyIn):
    return {"id": run(mdl.copy_process, body.id, body.database)}


@app.post("/api/models/process/update")
def post_model_process_update(body: ProcessUpdateIn):
    run(mdl.update_process, body.id, body.fields)
    return {"ok": True}


@app.post("/api/models/allocation")
def post_model_allocation(body: AllocationIn):
    return run(mdl.set_allocation, body.id, body.strategy, body.manual)


@app.post("/api/allocation/compare")
def post_allocation_compare(body: ActIn):
    return run(s.allocation_compare, body.id, _method(body.method))


@app.post("/api/models/process/delete")
def post_model_process_delete(body: IdIn):
    run(mdl.delete_process, body.id)
    return {"ok": True}


@app.post("/api/models/exchange/add")
def post_exchange_add(body: ExchangeAddIn):
    return {"exchange": run(mdl.add_exchange, body.id, body.input, body.amount, body.kind)}


@app.post("/api/models/exchange/update")
def post_exchange_update(body: ExchangeUpdateIn):
    run(mdl.update_exchange, int(body.exchange), body.amount, body.kind)
    return {"ok": True}


@app.post("/api/models/exchange/uncertainty")
def post_exchange_uncertainty(body: UncertaintyIn):
    run(mdl.set_uncertainty, int(body.exchange), body.spec)
    return {"ok": True}


@app.post("/api/models/exchange/delete")
def post_exchange_delete(body: ExchangeIn):
    run(mdl.delete_exchange, int(body.exchange))
    return {"ok": True}


@app.post("/api/models/undo")
def post_model_undo(body: JournalUndoIn):
    label = run(mdl.undo, body.n)
    return {"undone": label, "state": run(s.state)}


@app.post("/api/beispiel")
def post_beispiel():
    r = run(beispiel.create)
    return {**r, "state": run(s.state)}


# ---------- calculation setups ----------

@app.get("/api/setups/get")
def get_setup(name: str):
    return run(cs.get, name)


@app.post("/api/setups/save")
def post_setup_save(body: SetupIn):
    name = run(cs.save, body.name, [f.model_dump() for f in body.fus], body.methods, body.old_name)
    return {"name": name, "state": run(s.state)}


@app.post("/api/setups/delete")
def post_setup_delete(body: NameIn):
    run(cs.delete, body.name)
    return run(s.state)


def ui_version() -> str:
    """Changes whenever any UI file changes. The page loads its files under /ui/<version>/, so a browser never
    combines a cached old module with a new one (relative imports stay inside the same versioned path)."""
    h = hashlib.sha1()
    for p in sorted(STATIC.rglob("*")):
        if p.is_file():
            st = p.stat()
            h.update(f"{p.relative_to(STATIC)}:{st.st_mtime_ns}:{st.st_size}".encode())
    return h.hexdigest()[:12]


@app.get("/")
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace('"/static/', f'"/ui/{ui_version()}/')
    return Response(html, media_type="text/html; charset=utf-8")


@app.get("/ui/{version}/{path:path}")
def ui_file(version: str, path: str):
    f = (STATIC / path).resolve()
    if STATIC.resolve() not in f.parents or not f.is_file():
        raise HTTPException(404, _("Nicht gefunden."))
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
