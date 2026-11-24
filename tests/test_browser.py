"""Browser tests: the real UI in Chrome against a real server on port 8795.

The server runs in the test project `lca-wrench-test` with its own registry file.
Skip with LCA_WRENCH_SKIP_BROWSER=1 (check.sh --no-browser).
Uses the installed Google Chrome (no separate browser download); other browsers and the files kept when a test
fails: see browser_support.py.
"""

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

import browser_support  # noqa: E402
from conftest import TEST_PROJECT  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("LCA_WRENCH_SKIP_BROWSER") == "1", reason="browser tests skipped (LCA_WRENCH_SKIP_BROWSER=1)")

PORT = 8795
WINDOWS = sys.platform == "win32"
URL = f"http://127.0.0.1:{PORT}"
ROOT = Path(__file__).resolve().parent.parent


def num(text: str) -> float:
    """Parse a number as the UI formats it (Swiss thousands separators, minus signs)."""
    t = text.replace("’", "").replace("'", "").replace("−", "-").replace(" ", "").replace(" ", "")
    return float(re.search(r"-?[\d.]+(?:e[+-]?\d+)?", t, re.I).group(0))


@pytest.fixture(scope="module")
def server():
    import socket

    with socket.socket() as sock:  # a server left over from an earlier run would answer in place of this one
        if sock.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError(f"Port {PORT} is in use (an LCA Wrench test server left over?): stop it first")
    env = {**os.environ, "LCA_WRENCH_PROJECT": TEST_PROJECT, "PYTHONWARNINGS": "ignore"}
    # own process group (POSIX: session), so the server and its Monte-Carlo workers stop together
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "lca_wrench.api:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **group,
    )
    import urllib.request

    for _ in range(120):
        try:
            urllib.request.urlopen(f"{URL}/api/state", timeout=2).read()
            break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError(f"Server ist abgestürzt: {proc.stderr.read().decode()}")
            time.sleep(0.5)
    else:
        _stop(proc)
        raise RuntimeError("Server startet nicht")
    yield URL
    _stop(proc)


def _stop(proc: subprocess.Popen) -> None:
    """End the server and any Monte-Carlo workers it started. Windows has no process groups to signal (no os.killpg)
    and proc.kill() would end only the venv's python.exe, not the interpreter it starts: taskkill ends the whole tree.
    Left running, the server keeps the test project's files open and the next run fails on them."""
    if WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)
    proc.wait(timeout=15)


@pytest.fixture(scope="module")
def page(server, request):
    failed_before = request.session.testsfailed
    with sync_playwright() as p:
        browser = browser_support.launch(p)
        ctx = browser_support.new_context(browser, "test_browser", viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        # the app is local: every request the page makes must go to its own server (checked in the last test)
        external = []
        pg.on("request", lambda r: None if r.url.startswith((server, "data:", "blob:")) else external.append(r.url))
        pg.external = external
        pg.set_default_timeout(60_000)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.errors = errors
        # questions use the app's own dialog; a native one (confirm, alert) would be a regression
        native = []
        pg.on("dialog", lambda d: (native.append(d.message), d.dismiss()))
        pg.goto(server)
        # the tests read the German texts; English is the default (test_11)
        pg.evaluate("localStorage.setItem('wb-lang', 'de')")
        pg.reload()
        yield pg
        browser_support.finish(ctx, request.session.testsfailed > failed_before)
        browser.close()
    assert not errors, f"JavaScript-Fehler im Browser: {errors}"
    assert not native, f"Browser-Dialog statt eigenem Dialog: {native}"


def test_01_start_and_tour(page):
    # the first-run tour opens by itself; walk through all ten steps
    tour = page.locator("#tourCard")
    expect(tour).to_contain_text("1 / 10")
    for n in range(2, 11):
        page.click("[data-tour=next]")
        expect(tour).to_contain_text(f"{n} / 10", timeout=30_000)  # a step can wait for the app (slow PCs)
    page.click("[data-tour=skip]")
    expect(tour).to_have_count(0)
    page.click("#rail [data-k=start]")
    expect(page.locator("h1")).to_contain_text("Modellieren und rechnen")
    expect(page.locator(".hero h2")).to_have_text(TEST_PROJECT)
    expect(page.locator("#rail .nav")).to_have_count(7)
    # the tour can be restarted and closed with Escape
    page.click("#tourBtn")
    expect(tour).to_be_visible()
    page.keyboard.press("Escape")
    expect(tour).to_have_count(0)


def test_02_example_model_edit_undo(page):
    page.click("[data-act=example-model]")
    expect(page.locator(".kpi .big")).to_be_visible()
    expect(page.locator("#main")).to_contain_text("Fahrt mit dem E-Bike")
    kpi = page.locator(".kpi .big").first
    before_text = kpi.inner_text()
    before = num(before_text)
    assert before > 0
    field = page.locator("input[data-ex]").first
    old = float(field.input_value())
    field.fill(str(old * 2))
    field.press("Tab")
    expect(page.locator("#undoBtn")).to_be_visible()
    # wait for the recalculation instead of a fixed time (slow CI runners)
    expect(kpi).not_to_have_text(before_text, timeout=15000)
    page.click("#undoBtn")
    expect(kpi).to_have_text(before_text, timeout=15000)
    assert num(kpi.inner_text()) == pytest.approx(before, rel=1e-6)
    assert float(page.locator("input[data-ex]").first.input_value()) == pytest.approx(old)


def test_02b_parameters_and_formula(page):
    """Project -> model -> process parameter, a formula for the steel of the bike, one change runs through all."""
    page.click("#rail [data-k=parameter]")

    def add(where, name, value):
        where.locator("[data-act=par-add]").first.click()
        page.fill("#parNewName", name)
        page.fill("#parNewValue", value)
        page.press("#parNewValue", "Enter")
        expect(page.locator("#parNewName")).to_have_count(0)

    cards = page.locator("main section.card")
    add(cards.nth(0), "km_jahr", "3000")
    add(cards.nth(1), "faktor", "km_jahr / 1000")
    page.select_option("#parProc", label="E-Bike, montiert · CH")
    page.click("[data-act=par-add-proc]")
    bike = page.locator(".pproc", has_text="E-Bike, montiert")
    page.fill("#parNewName", "stahl")
    page.fill("#parNewValue", "7 * faktor / 3")
    page.press("#parNewValue", "Enter")
    expect(bike).to_contain_text("= 7")
    bike.locator("[data-act=open-proc-from-par]").click()
    before = num(page.locator(".kpi .big").first.inner_text())
    page.locator("[data-act=ex-formula][aria-label*=Steel]").click()
    page.fill("input.formula", "stahl")
    page.press("input.formula", "Enter")
    expect(page.locator(".fcell .num")).to_have_text("= 7")
    assert num(page.locator(".kpi .big").first.inner_text()) == pytest.approx(before, rel=1e-6)
    page.click("#rail [data-k=parameter]")
    km = page.locator("input[data-pv*=km_jahr]")
    km.fill("6000")
    km.press("Enter")
    expect(page.locator(".pproc", has_text="E-Bike, montiert")).to_contain_text("= 14")
    page.locator(".pproc", has_text="E-Bike, montiert").locator("[data-act=open-proc-from-par]").click()
    expect(page.locator(".fcell .num")).to_have_text("= 14")
    assert num(page.locator(".kpi .big").first.inner_text()) > before
    # a formula with an unknown name is refused and changes nothing
    page.fill("input.formula", "stahl * nix")
    page.press("input.formula", "Enter")
    expect(page.locator("#toast")).to_contain_text("unbekannter Name nix")
    expect(page.locator(".fcell .num")).to_have_text("= 14")
    # five steps back: everything as before
    for _ in range(5):
        page.click("#undoBtn")
        page.wait_for_timeout(700)
    params = page.request.get(f"{URL}/api/params").json()
    assert params["project"] == []
    assert num(page.locator(".kpi .big").first.inner_text()) == pytest.approx(before, rel=1e-6)


def test_03_setup_result_and_crosscheck(page):
    page.click("#rail [data-k=rechnen]")
    page.locator(".reslist .res").first.click()
    expect(page.locator(".restbl")).to_be_visible()
    # the method picker filters while typing
    page.click("[data-act=pick-methods]")
    page.locator("#mpQ").press_sequentially("climate", delay=20)
    expect(page.locator("#mpQ")).to_have_value("climate")
    page.click("[data-act=dlg-close]")
    assert page.locator(".restbl tbody tr").count() >= 3
    page.click("[data-act=verify-setup]")
    expect(page.locator(".check")).to_contain_text("Gegenprobe mit bw2calc stimmt")
    assert "weicht" not in page.locator(".check").inner_text()
    # from the calculation straight to "Result": its first product, the others to choose from
    # (a product of the calculation that is already open stays open)
    n = page.locator(".restbl tbody tr").count()
    page.click("#rail [data-k=ergebnis]")
    choose = page.locator("#fuSetup")
    expect(choose.locator("option")).to_have_count(n)
    other = "0" if choose.input_value() != "0" else "1"
    name = choose.locator(f"option[value='{other}']").inner_text().split(" · ")[0]
    page.select_option("#fuSetup", other)
    expect(page.locator("#main h2").first).to_contain_text(name.rsplit(" ", 1)[0])
    expect(page.locator(".kpi .big")).to_be_visible()
    page.click("#rail [data-k=rechnen]")
    expect(page.locator(".restbl")).to_be_visible()


def test_04_result_sankey_inventory(page):
    page.locator(".restbl .cellbtn").first.click()
    expect(page.locator(".kpi .big")).to_be_visible()
    score = num(page.locator(".kpi .big").inner_text())
    assert score != 0
    page.click("[data-act=verify-fu]")
    expect(page.locator(".check")).to_contain_text("Gegenprobe mit bw2calc stimmt")
    page.click("[data-act=tab][data-k=sankey]")
    expect(page.locator(".gwrap.sankey svg")).to_be_visible()
    n = page.locator(".gwrap.sankey .sk-node").count()
    assert n >= 3
    cum = page.locator(".gwrap.sankey .sk-node rect").first.get_attribute("height")
    page.select_option("#skMode", "own")  # same activities, bars now show only their own emissions
    expect(page.locator("#main")).to_contain_text("Eigene Beiträge der gezeigten Prozesse")
    assert page.locator(".gwrap.sankey .sk-node").count() == n
    assert page.locator(".gwrap.sankey .sk-node rect").first.get_attribute("height") != cum
    page.select_option("#skMode", "cum")
    page.click("[data-act=tab][data-k=inventar]")
    expect(page.locator("#main table tbody tr").first).to_be_visible()
    assert page.locator("#main table tbody tr").count() > 10
    page.fill("#invQ", "carbon dioxide")
    page.wait_for_timeout(600)
    rows = page.locator("#main table tbody tr")
    assert rows.count() >= 1
    for t in rows.all_inner_texts()[:20]:
        assert "carbon dioxide" in t.lower()


def test_04c_flows_without_factor_and_completion(page):
    """The inventory says which flows the method assesses; the completion switch changes the result and marks it."""
    page.click("[data-act=tab][data-k=inventar]")
    page.fill("#invQ", "")
    page.wait_for_timeout(400)
    expect(page.locator("#invTbl tbody tr").first).to_be_visible()
    assert page.locator("#invTbl tbody tr[data-status=none]").count() > 0
    page.select_option("#invF", "none")
    statuses = page.locator("#invTbl tbody tr").evaluate_all("rs => rs.map(r => r.dataset.status)")
    assert statuses and set(statuses) == {"none"}
    expect(page.locator("#factorNotice")).to_be_visible()
    off = num(page.locator(".kpi .big").inner_text())
    assert page.locator("#complChip").count() == 0  # the tests run with the completion off (conftest.py)
    page.check("#complChk")
    expect(page.locator("#complChip")).to_be_visible()
    on = num(page.locator(".kpi .big").inner_text())
    assert on > off
    page.click("#complChip")  # the marker opens the list of completed factors
    expect(page.locator("#invF")).to_have_value("completed")
    statuses = page.locator("#invTbl tbody tr").evaluate_all("rs => rs.map(r => r.dataset.status)")
    assert statuses and set(statuses) == {"completed"}
    page.uncheck("#complChk")
    expect(page.locator("#complChip")).to_have_count(0)
    assert num(page.locator(".kpi .big").inner_text()) == off
    page.select_option("#invF", "")


def test_04b_bafu_ecoinvent_tab(page):
    """The product with another background database; here the same one, so every dataset is its own counterpart."""
    page.click("[data-act=tab][data-k=crosswalk]")
    page.select_option("#cwProj", TEST_PROJECT)
    page.select_option("#cwDb", "BAFU-2025-v2")
    page.click("[data-act=cw-run]")
    expect(page.locator("#main .tbl tbody tr").first).to_contain_text("derselbe Datensatz")
    kpis = page.locator("#main .kpi .big")
    expect(kpis).to_have_count(4)  # the result head, here, there, difference
    assert num(kpis.nth(1).inner_text()) == pytest.approx(num(kpis.nth(2).inner_text()), rel=1e-6)
    assert num(kpis.nth(3).inner_text()) == 0
    page.click("[data-act=cw-view][data-k=drivers]")
    expect(page.locator("#main")).to_contain_text("Kein Unterschied")
    page.click("[data-act=cw-view][data-k=datasets]")


def test_05_uncertainty(page):
    page.click("#rail [data-k=rechnen]")
    page.locator(".reslist .res").first.click()
    expect(page.locator(".restbl").first).to_be_visible()
    page.select_option("#mcN", "100")
    page.click("[data-act=mc-start]")
    expect(page.locator("#mcCard [role=progressbar]")).to_be_visible()
    expect(page.locator("#mcCard .mc-box")).to_have_count(4, timeout=180_000)
    card = page.locator("#mcCard")
    expect(card).to_contain_text("100 Ziehungen")
    assert card.locator("table").count() == 2  # statistics and \"A besser als B\"
    cells = card.locator(".mc-cell").all_inner_texts()
    assert len(cells) == 12 and all(c.endswith("%") for c in cells)
    # second method switches the plot without a new run
    if page.locator("[data-act=mc-method]").count() > 1:
        page.locator("[data-act=mc-method]").nth(1).click()
        expect(card.locator(".mc-box")).to_have_count(4)


def test_06_sensitivity(page):
    sens = page.locator("#sensCard")
    page.select_option("#sensFu", "0")
    page.click("[data-act=sens-start]")
    rows = sens.locator("tbody tr")
    expect(rows.first).to_be_visible(timeout=240_000)
    # top 10 by rank correlation, then possibly a heading row and up to 5 entries strong only by Sobol (random draws)
    n = rows.count()
    main = rows.evaluate_all("rs => { const i = rs.findIndex(r => r.querySelector('td[colspan]')); return i < 0 ? rs.length : i }")
    assert 1 <= main <= 10
    assert n - main <= 6
    expect(sens).to_contain_text("Rangkorrelation")


def test_07_outside_change_reloads(page):
    """Another program changes the model: the open page notices it and shows the new number."""
    import subprocess

    page.click("#rail [data-k=modell]")
    page.locator(".reslist .res", has_text="Fahrt mit dem E-Bike").click()
    expect(page.locator("[data-pf=name]")).to_have_value("Fahrt mit dem E-Bike")  # the sheet shown before may still be there
    field = page.locator("input[data-ex]").first
    old = float(field.input_value())
    eid = field.get_attribute("data-ex")
    script = (
        "import warnings; warnings.filterwarnings('ignore')\n"
        "import bw2data as bd\n"
        "from bw2data.backends.proxies import Exchange\n"
        "from bw2data.backends.schema import ExchangeDataset as ED\n"
        f"bd.projects.set_current('{TEST_PROJECT}')\n"
        f"e = Exchange(ED.get_by_id({int(eid)})); e['amount'] = {old * 3}; e.save()\n"
    )
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1500:]
    expect(page.locator("#toast")).to_contain_text("Ein anderes Programm hat das Projekt geändert", timeout=30_000)
    assert float(page.locator("input[data-ex]").first.input_value()) == pytest.approx(old * 3, rel=1e-6)


def test_08_excel_export_import(page, tmp_path):
    page.click("#rail [data-k=modell]")
    expect(page.locator("a[href^='/api/models/export']")).to_be_visible()
    with page.expect_download() as dl:
        page.click("a[href^='/api/models/export']")
    path = tmp_path / "modell.xlsx"
    dl.value.save_as(path)
    assert path.read_bytes()[:2] == b"PK"
    page.set_input_files("#xlsxIn", str(path))
    expect(page.locator("#toast")).to_contain_text("importiert", timeout=60_000)
    expect(page.locator("#mdbSel")).to_have_value(re.compile(r"\(Import\)"))
    expect(page.locator(".reslist .res", has_text="Fahrt mit dem E-Bike")).to_be_visible()


def test_09_cleanup_example(page):
    # remove the example database so the test project stays clean for the other tests
    page.click("#rail [data-k=modell]")
    expect(page.locator("[data-act=del-db]").first).to_be_visible()
    while page.locator("[data-act=del-db]").count():
        page.locator("[data-act=del-db]").first.click()
        page.click("#dlg [data-act=confirm-ok]")
        page.wait_for_timeout(1500)
        page.click("#rail [data-k=start]")
        page.click("#rail [data-k=modell]")
        page.wait_for_timeout(500)
        if not page.locator("[data-act=del-db]").count():
            break
    import json
    import urllib.request

    st = json.load(urllib.request.urlopen(f"{URL}/api/state"))
    assert not [d for d in st["databases"] if d["role"] == "model"]


def test_10_why_different_in_working_copy(page):
    """Working copy, one change in the background data, tab «Warum anders?» explains the whole difference."""
    import bw2data as bd

    from lca_wrench import registry
    from lca_wrench import service as s

    page.click("#rail [data-k=daten]")
    page.locator("#q").press_sequentially("electricity low voltage", delay=20)  # right away: the redraw keeps the text
    page.fill("#loc", "CH")  # free text, with suggestions
    page.click("#searchForm button[type=submit]")
    expect(page.locator("#main .res").first).to_be_visible(timeout=30_000)
    page.locator("#main .res", has_text="kWh").first.click()
    expect(page.locator("[data-act=copy]")).to_be_visible()
    page.click("[data-act=copy]")
    expect(page.locator("#copyChip")).to_contain_text("Arbeitskopie", timeout=300_000)
    try:
        field = page.locator("input[data-ex]").first
        expect(field).to_be_visible()
        field.fill(str(float(field.input_value()) * 2))
        field.press("Tab")
        expect(page.locator("#copyChip")).to_contain_text("1 Änderung", timeout=60_000)
        page.click("[data-act=calc-act]")
        page.click("[data-act=tab][data-k=warum]")
        card = page.locator("main .card").nth(1)
        expect(card.locator("tbody tr").first).to_be_visible(timeout=120_000)
        assert page.locator("main tbody tr").count() == 1  # exactly the one change, no "not explained" row
        diff = num(page.locator("main .kpi .big").nth(3).inner_text())
        part = num(page.locator("main tbody tr td.num").first.inner_text())
        assert part == pytest.approx(diff, rel=2e-3)  # displayed values are rounded to 3 digits
        expect(page.locator("main")).to_contain_text("100 %")
    finally:
        copies = [p for p in registry.load()["copies"]]
        # let the server leave the copy before its folder is deleted
        page.request.post(f"{URL}/api/project", data={"name": TEST_PROJECT}, headers={"X-LCA-Wrench": "1"})
        bd.projects.set_current(TEST_PROJECT)
        for name in copies:
            if name in bd.projects:
                s.remove_project(name)
            reg = registry.load()
            reg["copies"].pop(name, None)
            registry.save(reg)


def test_11_english_and_back(page):
    """English by default; the language switch changes the whole UI at once, the server answers in the UI's language,
    the choice is kept."""
    page.evaluate("localStorage.removeItem('wb-lang')")
    page.reload()
    page.click("#rail [data-k=start]")
    expect(page.locator("#langBtn")).to_have_text("Deutsch")
    expect(page.locator("#rail")).to_contain_text("Calculate")
    expect(page.locator("main h1")).to_have_text("Model and calculate without waiting")
    assert page.evaluate("document.documentElement.lang") == "en"
    page.click("#rail [data-k=rechnen]")
    expect(page.locator("main")).to_contain_text("Calculation setups")
    # a message written by the server: a second model with the same name
    page.click("#rail [data-k=modell]")
    page.locator("[data-act=new-db]").first.click()
    page.fill("#newDbName", "Sprachtest")
    page.press("#newDbName", "Enter")
    # wait until the model exists (a fixed pause was too short on a slow machine: the second try came first)
    expect(page.locator("#mdbSel option", has_text="Sprachtest")).to_have_count(1)
    page.locator("[data-act=new-db]").first.click()
    page.fill("#newDbName", "Sprachtest")
    page.press("#newDbName", "Enter")
    expect(page.locator("#toast")).to_contain_text("A database “Sprachtest” already exists.")
    page.click("[data-act=new-db-cancel]")
    page.click("[data-act=del-db]")
    page.click("#dlg [data-act=confirm-ok]")
    expect(page.locator("#mdbSel option", has_text="Sprachtest")).to_have_count(0)
    page.click("#langBtn")
    expect(page.locator("#rail")).to_contain_text("Rechnen")
    page.reload()
    expect(page.locator("#langBtn")).to_have_text("English")
    expect(page.locator("#rail")).to_contain_text("Rechnen")


def test_12_local_fonts_and_no_external_requests(page):
    """The bundled IBM Plex is used, and in all the tests above the page asked nothing from the internet."""
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.fonts.check('14px \"IBM Plex Sans\"') && document.fonts.check('14px \"IBM Plex Mono\"')")
    assert [f for f in page.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)")]
    assert page.external == [], page.external
