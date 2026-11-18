"""German/English: every server text and every UI text has an English translation with the same placeholders."""

import ast
import re
from pathlib import Path

import bw2data as bd
from fastapi.testclient import TestClient

from conftest import TEST_PROJECT
from lca_wrench import i18n, registry, service as s
from lca_wrench.api import app

ROOT = Path(__file__).parent.parent / "lca_wrench"
FIELDS = re.compile(r"\{(\w+)\}")


def _server_templates():
    """First argument of every _(...), msg(...) and i18n._(...) call in the server code."""
    for path in ROOT.glob("*.py"):
        if path.name == "i18n.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name in ("_", "msg") and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                yield path.name, node.args[0].value


def test_every_server_text_has_english():
    found = list(_server_templates())
    assert len(found) > 40
    missing = [(f, t) for f, t in found if t not in i18n.EN]
    assert not missing, missing
    for _, t in found:
        assert set(FIELDS.findall(t)) == set(FIELDS.findall(i18n.EN[t])), t


def test_every_ui_text_has_english():
    """t('…') calls in the UI; the English table is in i18n.js."""
    js = {p: p.read_text(encoding="utf-8") for p in (ROOT / "static" / "js").rglob("*.js")}
    keys = set()
    for text in js.values():
        keys |= {k.replace("\\'", "'") for k in re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", text)}
    table = js[ROOT / "static" / "js" / "i18n.js"]
    entries = dict(re.findall(r"^\s*'((?:[^'\\]|\\.)*)':\s*'((?:[^'\\]|\\.)*)',?\s*$", table, re.M))
    entries = {k.replace("\\'", "'"): v.replace("\\'", "'") for k, v in entries.items()}
    assert len(keys) > 200
    missing = sorted(keys - set(entries))
    assert not missing, missing[:20]
    for k in keys:
        assert set(FIELDS.findall(k)) == set(FIELDS.findall(entries[k])), k
    unused = sorted(set(entries) - keys)
    assert not unused, unused[:20]


def test_rendered_later_in_the_readers_language():
    m = i18n.msg("Prozess «{name}» angelegt", name="Rahmen")
    token = i18n.LANG.set("en")
    try:
        assert i18n.render(m) == "Activity “Rahmen” created"
        assert i18n.render(list(m)) == "Activity “Rahmen” created"  # as read back from JSON
        assert i18n.render("alter Eintrag") == "alter Eintrag"
    finally:
        i18n.LANG.reset(token)
    assert i18n.render(m) == "Prozess «Rahmen» angelegt"


def test_api_answers_in_the_requested_language():
    bd.projects.set_current(TEST_PROJECT)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        r = c.post("/api/project", json={"name": "gibt-es-nicht"}, headers={"X-Lang": "en"})
        assert r.status_code == 404 and r.json()["detail"] == "There is no project “gibt-es-nicht”."
        r = c.post("/api/project", json={"name": "gibt-es-nicht"}, headers={"X-Lang": "de"})
        assert r.json()["detail"] == "Projekt «gibt-es-nicht» gibt es nicht."
    bd.projects.set_current(TEST_PROJECT)


def test_english_is_the_default(monkeypatch):
    """Without X-Lang the server answers in English (the tests set LCA_WRENCH_LANG=de for their German texts)."""
    monkeypatch.setattr(i18n, "DEFAULT", "en")
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        r = c.post("/api/project", json={"name": "gibt-es-nicht"})
        assert r.json()["detail"] == "There is no project “gibt-es-nicht”."
    bd.projects.set_current(TEST_PROJECT)
    js = (ROOT / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert "export let LANG = stored === 'de' ? 'de' : 'en';" in js


def test_ui_files_are_versioned():
    """After an update the browser must not mix cached old and new UI modules: the page names its files under
    /ui/<version>/ (a new version means new URLs), the page itself is always asked for again."""
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-LCA-Wrench": "1"}) as c:
        r = c.get("/")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        m = re.search(r'src="(/ui/([0-9a-f]{12})/js/main\.js)"', r.text)
        assert m and f'href="/ui/{m.group(2)}/app.css"' in r.text and "/static/" not in r.text
        js = c.get(m.group(1))
        assert js.status_code == 200 and "immutable" in js.headers["cache-control"] and "javascript" in js.headers["content-type"]
        assert c.get(f"/ui/{m.group(2)}/js/i18n.js").status_code == 200  # relative imports resolve inside the version
        assert c.get(f"/ui/{m.group(2)}/../api.py").status_code == 404
        assert c.get(f"/ui/{m.group(2)}/%2e%2e/api.py").status_code == 404
        assert c.get("/static/js/main.js").headers["cache-control"] == "no-cache"


def test_start_project_choice():
    names = {p.name for p in bd.projects}
    assert s.pick_start_project(TEST_PROJECT) == TEST_PROJECT
    reg = registry.load()
    old = reg.get("last_project")
    try:
        reg["last_project"] = TEST_PROJECT
        registry.save(reg)
        assert s.pick_start_project("gibt-es-nicht") == TEST_PROJECT
        reg["last_project"] = "gibt-es-auch-nicht"
        registry.save(reg)
        expected = "bafu-2025" if "bafu-2025" in names else None
        if expected:
            assert s.pick_start_project(None) == expected
        else:
            pick = s.pick_start_project(None)
            assert pick is None or (pick != "default" and not pick.startswith(s.TEST_PROJECT_PREFIX))
    finally:
        reg = registry.load()
        reg.pop("last_project", None) if old is None else reg.update(last_project=old)
        registry.save(reg)


def test_no_project_is_opened_on_its_own(monkeypatch):
    """On someone else's computer (no bafu-2025, nothing chosen yet) the app opens no project at all: the user chooses.
    Neither the empty default nor a real project (e.g. with ecoinvent) is opened on its own."""
    class P:
        def __init__(self, n, twofive=True):
            self.name, self.data = n, {"25": True} if twofive else {}

    monkeypatch.setattr(s, "pending_updates", lambda name: [])
    monkeypatch.setattr(type(bd.projects), "__iter__", lambda self: iter([P("default"), P("lca-wrench-test-x"), P("ecoinvent-3.11")]))
    assert s.pick_start_project(None) is None
    assert s.pick_start_project("ecoinvent-3.11") == "ecoinvent-3.11"  # asked for explicitly (LCA_WRENCH_PROJECT)
    # a project of the Activity Browser 2 is never opened on its own, not even when asked for
    monkeypatch.setattr(type(bd.projects), "__iter__", lambda self: iter([P("default"), P("ab2-ecoinvent", twofive=False)]))
    assert s.pick_start_project("ab2-ecoinvent") is None
    monkeypatch.setattr(type(bd.projects), "__iter__", lambda self: iter([P("default")]))
    assert s.pick_start_project(None) is None


def test_translation_function_not_shadowed():
    """`_` is the translation function; a loop or assignment target `_` in a function makes `_()` fail there."""
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not any(isinstance(n, ast.ImportFrom) and n.module == "i18n" and any(a.name == "_" for a in n.names) for n in tree.body):
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, (ast.For, ast.AsyncFor)):
                targets = [node.target]
            elif isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                targets = [node.optional_vars]
            for t in targets:
                names = [n.id for n in ast.walk(t) if isinstance(n, ast.Name)]
                assert "_" not in names, f"{path.name}:{node.lineno} uses _ as a variable"
