"""Browser tests for the layout and the feedback of the UI: phones and narrow windows, the header between phone and
desktop, error notes, the loading line, one calculation per click, the delete dialog.

Same test server and project as test_browser.py (port 8795, `lca-wrench-test`). The module makes its own example model
through the API and removes it at the end. Skip with LCA_WRENCH_SKIP_BROWSER=1 (check.sh --no-browser).
"""

import json
import os
import urllib.request

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

import browser_support  # noqa: E402
from test_browser import URL, server  # noqa: E402, F401  (the server fixture of the other browser tests)

pytestmark = pytest.mark.skipif(os.environ.get("LCA_WRENCH_SKIP_BROWSER") == "1", reason="browser tests skipped (LCA_WRENCH_SKIP_BROWSER=1)")

VIEWS = ["start", "daten", "modell", "parameter", "rechnen", "ergebnis", "vergleich"]


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{URL}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-LCA-Wrench": "1", "X-Lang": "de"})
    return json.load(urllib.request.urlopen(req, timeout=120))


@pytest.fixture(scope="module")
def example(server):  # noqa: F811
    """The example model (5 activities) and its calculation setup; removed again at the end."""
    r = post("/api/beispiel", {})
    yield r
    post("/api/setups/delete", {"name": r["setup"]})
    post("/api/models/db/delete", {"name": r["database"]})
    st = json.load(urllib.request.urlopen(f"{URL}/api/state"))
    assert not [d for d in st["databases"] if d["role"] == "model"]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = browser_support.launch(p)
        b.devices = p.devices
        yield b
        b.close()


@pytest.fixture
def open_page(browser, example, request):
    """open_page(width) or open_page(device="iPhone 13"): the app in German, without the tour, no JavaScript errors."""
    made = []
    failed_before = request.session.testsfailed

    def make(width=1440, height=900, device=None):
        name = f"{request.node.name}-{device or width}"
        options = dict(browser.devices[device]) if device else {"viewport": {"width": width, "height": height}}
        ctx = browser_support.new_context(browser, name, **options)
        pg = ctx.new_page()
        pg.errors, pg.native = [], []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("dialog", lambda d: (pg.native.append(d.message), d.dismiss()))
        pg.set_default_timeout(60_000)
        pg.goto(URL)
        pg.evaluate("localStorage.setItem('wb-lang', 'de'); localStorage.setItem('wb-tour', 'done')")
        pg.reload()
        expect(pg.locator("#rail .nav")).to_have_count(7)
        made.append((ctx, pg))
        return pg

    yield make
    for ctx, pg in made:
        errors, native = pg.errors, pg.native
        browser_support.finish(ctx, request.session.testsfailed > failed_before)
        assert not errors, f"JavaScript-Fehler im Browser: {errors}"
        assert not native, f"Browser-Dialog statt eigenem Dialog: {native}"


def page_width(pg) -> int:
    return pg.evaluate("document.documentElement.scrollWidth")


def open_setup(pg, name):
    pg.click("#rail [data-k=rechnen]")
    pg.locator("[data-act=open-setup]", has_text=name).click()
    expect(pg.locator(".restbl")).to_be_visible()


def open_result(pg, name):
    open_setup(pg, name)
    pg.locator(".cellbtn").first.click()
    expect(pg.locator(".bars")).to_be_visible()


@pytest.mark.parametrize("width", [390, 360])
def test_phone_no_sideways_scrolling(open_page, example, width):
    """No view is wider than a phone; the header is compact and the row of views stays on top while scrolling."""
    pg = open_page(width, 800)
    for v in VIEWS:
        pg.click(f"#rail [data-k={v}]")
        expect(pg.locator(f"#rail [data-k={v}]")).to_have_attribute("aria-current", "page")
        pg.wait_for_timeout(300)
        assert page_width(pg) <= width, f"{v}: page {page_width(pg)} px wide at {width} px"
    # with content: an open activity, a calculation setup, a result
    pg.click("#rail [data-k=modell]")
    pg.locator("[data-act=open-proc]").first.click()
    expect(pg.locator(".kpi .big")).to_be_visible()
    assert page_width(pg) <= width
    open_result(pg, example["setup"])
    assert page_width(pg) <= width
    # the header is compact: its buttons in one row (a long label may wrap inside its button)
    tops = pg.evaluate("[...document.querySelectorAll('.topbtns .btn')].filter(b => !b.hidden).map(b => Math.round(b.getBoundingClientRect().top))")
    assert len(set(tops)) == 1, tops
    assert pg.evaluate("document.querySelector('.top').offsetHeight") < 220
    # the open view is in sight in its row, and the row stays at the top of the screen
    rail = pg.evaluate("""() => { const r = document.getElementById('rail').getBoundingClientRect(), c = document.querySelector('#rail [aria-current]').getBoundingClientRect();
        return { inside: c.left >= r.left - 1 && c.right <= r.right + 1 }; }""")
    assert rail["inside"]
    pg.evaluate("window.scrollTo(0, 1200)")
    pg.wait_for_timeout(200)
    assert abs(pg.evaluate("document.getElementById('railNav').getBoundingClientRect().top")) < 2


def test_list_goes_to_detail_on_phone_only(open_page):
    """On a phone the list stands above the detail: choosing an activity scrolls down to it. Not on a desktop."""
    pg = open_page(390, 800)
    pg.click("#rail [data-k=modell]")
    expect(pg.locator(".detail .empty")).to_contain_text("aus der Liste")
    pg.locator("[data-act=open-proc]").last.click()
    expect(pg.locator(".kpi .big")).to_be_visible()
    pg.wait_for_timeout(300)
    assert pg.evaluate("scrollY") > 100
    top = pg.evaluate("document.querySelector('.detail').getBoundingClientRect().top")
    assert 0 <= top < 120, top  # just below the row of views
    desk = open_page(1440, 900)
    desk.click("#rail [data-k=modell]")
    desk.locator("[data-act=open-proc]").last.click()
    expect(desk.locator(".kpi .big")).to_be_visible()
    assert desk.evaluate("scrollY") == 0


def test_error_note_red_announced_and_closable(open_page, example):
    pg = open_page(1280, 800)
    toast = pg.locator("#toast")
    # an error from the server: a model name that exists
    pg.click("#rail [data-k=modell]")
    pg.locator("[data-act=new-db]").first.click()
    pg.fill("#newDbName", example["database"])
    pg.press("#newDbName", "Enter")
    expect(toast).to_be_visible()
    expect(toast).to_contain_text("gibt es schon")
    expect(toast).to_have_class("toast err")
    expect(toast).to_have_attribute("role", "alert")
    assert pg.evaluate("getComputedStyle(document.getElementById('toast')).backgroundColor") == pg.evaluate(
        "(() => { const e = document.createElement('i'); e.style.color = 'var(--hot)'; document.body.append(e); const c = getComputedStyle(e).color; e.remove(); return c; })()")
    pg.click("#toast .tclose")
    expect(toast).to_be_hidden()
    pg.click("[data-act=new-db-cancel]")
    # the server does not answer at all: a sentence instead of "Failed to fetch"
    pg.route("**/api/search*", lambda route: route.abort())
    pg.click("#rail [data-k=daten]")
    pg.fill("#q", "steel")
    pg.press("#q", "Enter")
    expect(toast).to_contain_text("LCA Wrench antwortet nicht")
    expect(toast).to_have_class("toast err")
    pg.unroute("**/api/search*")
    # a plain note is not an error
    pg.click("#rail [data-k=modell]")
    pg.locator("[data-act=open-proc]").first.click()
    pg.click("[data-act=dup-proc]")
    expect(toast).to_contain_text("dupliziert")
    expect(toast).to_have_class("toast")
    expect(toast).to_have_attribute("role", "status")
    pg.click("[data-act=del-proc]")  # the duplicate again
    expect(toast).to_contain_text("gelöscht")


def test_loading_line_and_one_calculation_per_click(open_page, example):
    """A slow calculation: the line at the top moves, the button says it works, the header does not move,
    and a second click does not start a second calculation."""
    pg = open_page(1280, 800)
    open_setup(pg, example["setup"])
    pg.evaluate("""() => { const f = window.fetch; window.nResults = 0;
        window.fetch = async (u, i) => { if (String(u).includes('/api/results')) { window.nResults++; await new Promise(r => setTimeout(r, 1500)); } return f(u, i); }; }""")
    left = pg.evaluate("document.getElementById('famSel').getBoundingClientRect().left")
    btn = pg.locator("[data-act=run-setup]")
    btn.click()
    btn.click()
    btn.dblclick()
    expect(btn).to_have_attribute("aria-busy", "true")
    expect(pg.locator("#busy")).to_contain_text("Rechne")
    assert pg.evaluate("getComputedStyle(document.getElementById('busy')).position") == "fixed"
    assert pg.evaluate("document.getElementById('famSel').getBoundingClientRect().left") == left
    expect(pg.locator("#busy")).to_have_text("", timeout=10_000)
    expect(pg.locator("[data-act=run-setup]")).not_to_have_attribute("aria-busy", "true")
    assert pg.evaluate("nResults") == 1


def test_result_tabs_one_row_on_phone(open_page, example):
    pg = open_page(390, 800)
    open_result(pg, example["setup"])
    tabs = pg.locator(".tabs")
    assert pg.evaluate("document.querySelector('.tabs').offsetHeight") < 60  # one row
    assert pg.evaluate("(e => e.scrollWidth > e.clientWidth)(document.querySelector('.tabs'))")  # scrolls sideways
    tabs.locator("[data-k=inventar]").click()
    expect(tabs.locator("[data-k=inventar]")).to_have_attribute("aria-selected", "true")
    inside = pg.evaluate("""() => { const r = document.querySelector('.tabs').getBoundingClientRect(), c = document.querySelector('.tabs [aria-selected=true]').getBoundingClientRect();
        return c.left >= r.left - 1 && c.right <= r.right + 1; }""")
    assert inside
    assert page_width(pg) <= 390
    # redrawing keeps the page where it is (only the tab row scrolls)
    tabs.locator("[data-k=beitraege]").click()
    expect(pg.locator(".bars")).to_be_visible()
    pg.evaluate("window.scrollTo(0, 600)")
    y = pg.evaluate("scrollY")
    pg.click("[data-act=contrib][data-k=act]")
    pg.wait_for_timeout(300)
    assert pg.evaluate("scrollY") == y


@pytest.mark.parametrize("width", [1024, 1200, 1280, 1440])
def test_header_buttons_do_not_hang_on_a_second_line(open_page, width):
    """Between phone and desktop: the buttons sit at the right of the first row, the selectors are side by side."""
    pg = open_page(width, 800)
    r = pg.evaluate("""() => { const q = s => document.querySelector(s).getBoundingClientRect();
        return { btns: q('.topbtns'), brand: q('.brand'), sels: ['#projSel', '#famSel', '#methSel'].map(s => q(s).top) }; }""")
    assert r["btns"]["right"] > width - 40, r  # right-aligned
    assert r["btns"]["top"] < r["brand"]["bottom"], r  # in the first row, next to the name
    assert max(r["sels"]) - min(r["sels"]) < 2, r  # the selectors in one row
    assert page_width(pg) <= width


def test_no_zoom_into_fields_on_iphone(open_page, example):
    """iPhone Safari zooms into fields with text below 16 px; on touch screens they have 16 px, on a desktop not."""
    sizes = """() => [...document.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]), select, textarea')]
        .filter(e => e.offsetParent).map(e => parseFloat(getComputedStyle(e).fontSize))"""
    phone = open_page(device="iPhone 13")
    found = []
    for v in ["daten", "modell"]:
        phone.click(f"#rail [data-k={v}]")
        phone.wait_for_timeout(300)
        found += phone.evaluate(sizes)
    phone.locator("[data-act=open-proc]").first.click()
    expect(phone.locator(".kpi .big")).to_be_visible()
    found += phone.evaluate(sizes)
    assert len(found) > 10 and min(found) >= 16, found
    assert phone.evaluate("document.querySelector('meta[name=viewport]').content").find("user-scalable=no") < 0
    desk = open_page(1440, 900)
    desk.click("#rail [data-k=daten]")
    assert desk.evaluate("parseFloat(getComputedStyle(document.getElementById('q')).fontSize)") < 16


def test_delete_asks_in_own_dialog(open_page, example):
    """Deleting asks in the app's dialog: alertdialog with heading and text, focus on Cancel, Escape keeps it."""
    pg = open_page(1280, 800)
    open_setup(pg, example["setup"])
    pg.click("[data-act=del-setup]")
    dlg = pg.locator("#dlg")
    expect(dlg).to_be_visible()
    expect(dlg).to_have_attribute("role", "alertdialog")
    assert pg.evaluate("document.getElementById(document.getElementById('dlg').getAttribute('aria-labelledby')).textContent") == "Rechnung löschen"
    assert example["setup"] in pg.evaluate("document.getElementById(document.getElementById('dlg').getAttribute('aria-describedby')).textContent")
    assert pg.evaluate("document.activeElement.dataset.act") == "dlg-close"
    expect(dlg.locator("[data-act=confirm-ok]")).to_have_class("btn danger")
    pg.keyboard.press("Escape")
    expect(dlg).to_be_hidden()
    pg.click("[data-act=del-setup]")
    pg.keyboard.press("Enter")  # on Cancel
    expect(dlg).to_be_hidden()
    st = json.load(urllib.request.urlopen(f"{URL}/api/state"))
    assert example["setup"] in [c["name"] for c in st["setups"]]
