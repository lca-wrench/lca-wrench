// LCA Wrench UI: plain JS modules, talks to the local FastAPI service.
'use strict';
import { S, $, esc, nf, mKey, methodInfo, methodLabel, familyLabel, api, request, toast, guard, renderBusy, icon, views, loadPrefs, savePref, csvDownload, download, isModelDb, langHeader, t, LANG } from './core.js';
import { setLang } from './i18n.js';
import { vStart } from './views/start.js';
import { vDaten } from './views/daten.js';
import { uncEditType, pedigreeHint } from './sheet.js';
import { vModell } from './views/modell.js';
import { vRechnen } from './views/rechnen.js';
import { vErgebnis, loadErgebnis, resetErgebnis, invRows, loadTargets, fuFromSetup, setupIndex, loadCats } from './views/ergebnis.js';
import { loadCw, traceSpec } from './views/crosswalk.js';
import { vVergleich } from './views/vergleich.js';
import { vParameter } from './views/parameter.js';
import { mcSignature } from './views/unsicherheit.js';
import { openPicker, openMethodPicker, openChooser, openConfirm, confirmed, confirmedAlt, picked, chosen, methodsApplied, closeDialog, renderDialog, openNewProject } from './dialogs.js';
import { startTour, shouldAutoStart, positionTour, tourKey } from './tour.js';

// ---------- projects ----------
async function openProject(name, rebuild) {
  // a large project is prepared on first use (matrix factorization): say so when it takes a while
  const slow = setTimeout(() => toast(t('Öffne «{name}» … beim ersten Mal dauert das bei grossen Datenbanken (ecoinvent) eine bis zwei Minuten.', { name })), 1500);
  try { await loadState(await api('/api/project', { name, rebuild })); } finally { clearTimeout(slow); }
  await afterProjectChange();
}
async function copyProject(name) {
  const r = await api('/api/project/copy', { name });
  await loadState(r.state);
  await afterProjectChange();
  toast(t('Kopie «{name}» angelegt und geöffnet. Das Original ist unverändert.', { name: r.project }));
}
// new project and imports (BAFU 2026, ecoinvent): the import runs on the server, the dialog shows its steps
async function newProject({ source = 'empty', target = null, name = '', add = false } = {}) {
  const opts = await api('/api/import/options');
  const ps = (opts.premise_sources || []).find(x => (opts.premise?.ei_versions || []).includes(x.version)) || (opts.premise_sources || [])[0];
  openNewProject({ opts, target, source, name, add, username: '', password: '', remember: false, versions: null, version: '',
    system_model: 'cutoff', lci_path: '', lcia_path: '', job: null,
    source_db: ps?.name || '', model: opts.premise?.models?.[0] || 'remind', pathway: (opts.premise?.pathways || []).includes('SSP2-NPi') ? 'SSP2-NPi' : opts.premise?.pathways?.[0] || '',
    years: '2030, 2050', key: '', exio_mode: 'download', path: '', exio_version: opts.exiobase_versions?.[0] || '', exio_year: '2022', system: 'pxp',
    biosphere: opts.biospheres?.[0] || '', db_name: '' });
}
async function followImport(job) {
  S.importing = true;
  try {
    while (job.state === 'läuft') {
      if (S.newp) { S.newp.job = job; renderDialog(); }
      await new Promise(r => setTimeout(r, 1500));
      job = (await (await request(`/api/import/status?id=${job.id}`, { headers: langHeader() })).json()).job || { ...job, state: 'fehler', error: '?' };
    }
  } finally { S.importing = false; }
  if (job.state === 'fehler') { if (S.newp) { S.newp.job = job; renderDialog(); } else toast(t('Fehlgeschlagen: {error}', { error: job.error }), null, true); await loadState(); render(); return; }
  if (job.source === 'premise-setup') {  // set up: on to the scenario itself
    toast(t('premise {v} ist eingerichtet.', { v: job.result?.premise || '' }));
    if (S.newp) { closeDialog(); await newProject({ source: 'premise', target: S.st.project, add: true }); }
    return;
  }
  if (S.newp) closeDialog();
  await loadState();
  await afterProjectChange();
  if (job.source === 'premise') toast(t('Szenarien fertig: {list}. Unter Start als Hintergrund wählen.', { list: (job.result?.databases || []).join(', ') }));
  else if (job.source === 'exiobase') toast(t('EXIOBASE ist da: {n} Sektoren. Unter Start als Hintergrund wählen oder kombinieren.', { n: nf(job.result?.sectors ?? 0) }));
  else toast(t('«{name}» ist bereit: {n} Prozesse, {m} Wirkungsmethoden.', { name: job.project, n: nf(job.result?.processes ?? 0), m: job.result?.methods ?? 0 }));
}
// after a page reload during an import: show it until it is done
async function resumeImport() {
  let r; try { r = await (await fetch('/api/import/status', { headers: langHeader() })).json(); } catch (_) { return; }
  if (!r.job || r.job.state !== 'läuft') return;
  const opts = await (await fetch('/api/import/options', { headers: langHeader() })).json();
  openNewProject({ opts, target: r.job.project, source: r.job.source, name: '', username: '', password: '', remember: false, versions: null,
    version: '', system_model: 'cutoff', lci_path: '', lcia_path: '', job: r.job });
  await followImport(r.job);
}
async function submitNewProject() {
  const n = S.newp;
  if (n.source === 'empty') {
    const r = await api('/api/project/new', { name: n.name.trim() });
    closeDialog(); await loadState(r.state); await afterProjectChange();
    toast(t('Projekt «{name}» angelegt. Es ist leer: Daten importieren oder ein eigenes Modell anlegen.', { name: r.project }));
    return;
  }
  const years = String(n.years || '').split(/[^0-9]+/).filter(Boolean).map(Number);
  const job = await api('/api/import/start', { name: n.target || n.name.trim(), source: n.source, version: n.source === 'exiobase' ? n.exio_version : n.version.trim(), system_model: n.system_model,
    username: n.username || null, password: n.password || null, remember: n.remember, lci_path: n.lci_path.trim() || null, lcia_path: n.lcia_path.trim() || null,
    add: !!n.add, source_db: n.source_db || null, model: n.model || null, pathway: n.pathway || null, years, key: n.key || null,
    path: n.source === 'exiobase' && n.exio_mode === 'file' ? n.path.trim() || null : null, biosphere: n.biosphere || null, db_name: n.db_name.trim() || null,
    system: n.system, year: n.source === 'exiobase' && n.exio_mode !== 'file' ? +n.exio_year : null });
  n.password = ''; n.key = '';  // not kept in the page longer than needed
  await followImport(job);
}
async function afterProjectChange() {
  S.sopts = null; S.move = null; S.bgForm = null; S.cats = { a: null, b: '', topic: '', res: null };
  resetErgebnis(); S.setup = null; S.setupRes = null; S.msel = null; S.mact = null; S.mc = { ...S.mc, job: null, res: null, error: null }; S.sens = { j: 0, job: null, res: null, error: null };
  try { await loadView(); } catch (e) { S.act = S.sel = S.fu = null; toast(t('Der gewählte Prozess existiert in diesem Projekt nicht.'), null, true); }
  render();
}

// ---------- data loading ----------
async function loadState(st) {
  S.st = st || await api('/api/state');
  if (!S.method || !S.st.methods.some(m => mKey(m.id) === mKey(S.method))) S.method = S.st.default_method;
  const models = S.st.databases.filter(d => d.role === 'model');
  if (!models.some(d => d.name === S.mdb)) { S.mdb = models[0]?.name || null; S.msel = null; S.mact = null; }
}
async function sheetFor(id) {
  try { return await api('/api/activity', { id, method: S.method }); }
  catch (e) { toast(e.message, null, true); return null; }
}
async function loadView() {
  if (['daten', 'modell', 'rechnen', 'ergebnis'].includes(S.view) && !S.sopts && S.st.databases.length) S.sopts = await api('/api/search/options');
  if (S.view === 'daten' && S.sel) { S.act = await sheetFor(S.sel); if (!S.act) S.sel = null; }
  if (S.view === 'modell') {
    S.mprocs = S.mdb ? await api(`/api/models/processes?db=${encodeURIComponent(S.mdb)}`) : [];
    if (S.msel && !S.mprocs.some(p => p.id === S.msel)) { S.msel = null; S.mact = null; }
    if (S.msel) S.mact = await sheetFor(S.msel);
  }
  if (S.view === 'rechnen' && S.setup) {
    try { S.setup = await api(`/api/setups/get?name=${encodeURIComponent(S.setup.name)}`); } catch (_) { S.setup = null; S.setupRes = null; }
    if (S.setup && S.setupRes) await runSetup();
  }
  if (S.view === 'ergebnis') await loadErgebnis();
  if (S.view === 'vergleich') await runCompare();
  if (S.view === 'parameter') S.par.data = await api(`/api/params${S.mdb ? '?db=' + encodeURIComponent(S.mdb) : ''}`);
}
async function runCompare() {
  S.cmpRes = S.cmp.length ? await api('/api/compare', { items: S.cmp.map(({ project, id, amount, background }) => ({ project, id, amount, background: background || null })), method: S.method }) : [];
  // the methods with factors for every product compared: their own ("native") or partly through the flow mapping
  const ok = S.cmpRes.filter(r => !r.error && r.covering);
  S.cmpCover = null;
  if (ok.length) {
    S.cmpCover = new Map(ok[0].covering.map(([m, how]) => [mKey(m), how]));
    for (const r of ok.slice(1)) {
      const mine = new Map(r.covering.map(([m, how]) => [mKey(m), how]));
      for (const [k, how] of S.cmpCover) {
        if (!mine.has(k)) S.cmpCover.delete(k);
        else if (mine.get(k) === 'mapped' || how === 'mapped') S.cmpCover.set(k, 'mapped');
      }
    }
  }
}
async function runSetup() {
  const cs = S.setup;
  if (!cs.fus.length || !cs.methods.length) { S.setupRes = null; return; }
  S.setupVerify = null;
  S.setupRes = await api('/api/results', { fus: cs.fus.map(f => ({ id: f.id, amount: f.amount })), methods: cs.methods });
}
async function saveSetup(oldName) {
  const cs = S.setup;
  const r = await api('/api/setups/save', { name: cs.name, old_name: oldName ?? cs.name, fus: cs.fus.map(f => ({ id: f.id, amount: f.amount })), methods: cs.methods });
  await loadState(r.state);
  S.setup = await api(`/api/setups/get?name=${encodeURIComponent(r.name)}`);
}
// the Parameter view is drawn only with fresh values: old ones would flash up, and typing into them would get lost
async function go(view) {
  // from a calculation to the result: its first product, unless one of its products is already open
  if (view === 'ergebnis' && S.setupRes?.fus.length && (!S.fu || (S.view === 'rechnen' && setupIndex() < 0))) fuFromSetup(0);
  S.view = view; if (view !== 'parameter') render(); await loadView(); render(); window.scrollTo({ top: 0 }); }
async function openNode(id, db) {
  if (db && isModelDb(db)) { S.mdb = db; S.msel = id; S.showAllTech = S.showAllBio = false; await go('modell'); }
  else { S.sel = id; S.showAllTech = S.showAllBio = false; if (!S.results.some(r => r.id === id)) S.results = []; await go('daten'); }
}
async function setFu(id, tab) {
  S.fu = { id, amount: 1, name: '', unit: '' }; resetErgebnis();
  if (tab) S.tab = tab;
  S.view = 'ergebnis'; render(); await loadErgebnis();
  if (S.calc) Object.assign(S.fu, { name: S.calc.name, location: S.calc.location, unit: S.calc.unit, database: S.calc.database });
  render(); window.scrollTo({ top: 0 });
}
const currentSheet = () => S.view === 'modell' ? S.mact : S.act;
async function refreshSheet() {
  if (S.view === 'modell') { S.mprocs = await api(`/api/models/processes?db=${encodeURIComponent(S.mdb)}`); if (S.msel) S.mact = await sheetFor(S.msel); }
  else if (S.sel) S.act = await sheetFor(S.sel);
}
async function afterModelChange(st) {
  await loadState(st);
  const a = currentSheet();
  if (a) S.prevScore = { id: a.id, v: a.score };
  await refreshSheet();
}

// ---------- render ----------
function renderTop() {
  document.title = t('LCA Wrench');
  // optional chaining: a page cached from an older version lacks some of these, the app must still work
  const text = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  text('brandName', t('LCA Wrench'));
  text('projLabel', t('Projekt'));
  text('famLabel', t('Methode'));
  text('methLabel', t('Wirkungskategorie'));
  $('railNav')?.setAttribute('aria-label', t('Ansichten'));
  text('tourBtn', t('Rundgang'));
  text('undoBtn', '↶\u00a0' + t('Rückgängig'));  // the arrow stays with the word when the text wraps
  const lb = $('langBtn');
  if (lb) { lb.textContent = LANG === 'en' ? 'Deutsch' : 'English'; lb.lang = LANG === 'en' ? 'de' : 'en'; lb.title = LANG === 'en' ? 'Oberfläche auf Deutsch' : 'Switch the interface to English'; }
  $('projSel').innerHTML = (S.st.project ? '' : `<option value="" selected disabled>${t('– Projekt wählen –')}</option>`)
    + S.st.projects.map(p => `<option value="${esc(p.name)}" ${p.name === S.st.project ? 'selected' : ''}>${esc(p.name)}${projectTag(p)}</option>`).join('');
  // in Compare only the methods with factors for every product there (the open one stays, marked)
  const cover = S.view === 'vergleich' ? S.cmpCover : null;
  const listed = cover ? S.st.methods.filter(m => cover.has(mKey(m.id)) || mKey(m.id) === mKey(S.method)) : S.st.methods;
  const mark = m => !cover ? '' : !cover.has(mKey(m.id)) ? ' ⚠' : cover.get(mKey(m.id)) === 'mapped' ? ' ≈' : '';
  const fams = [...new Set(listed.map(m => m.family))].sort((a, b) => a === 'Werkbank' ? -1 : b === 'Werkbank' ? 1 : a.localeCompare(b));
  // two steps: the method (EF v3.1, ReCiPe …), then one of its categories, or all of them side by side
  const fam = methodInfo().family || fams[0];
  const allCats = S.view === 'ergebnis' && S.tab === 'kategorien' && S.cats.a === fam && !S.cats.b && !S.cats.topic;
  $('famSel').innerHTML = fams.map(f => `<option value="${esc(f)}" ${f === fam ? 'selected' : ''}>${esc(familyLabel(f))}</option>`).join('');
  $('methSel').innerHTML = `<option value="*" ${allCats ? 'selected' : ''}>${t('Alle Kategorien')}</option>` + listed.filter(m => m.family === fam).map(m =>
    `<option value='${esc(mKey(m.id))}' ${!allCats && mKey(m.id) === mKey(S.method) ? 'selected' : ''}>${esc(methodLabel(m))} (${esc(m.unit)})${mark(m)}</option>`).join('');
  const bg = S.st.background, bgBox = $('bgBox');
  if (bgBox) {
    bgBox.hidden = !bg || bg.options.length < 2;
    text('bgLabel', t('Hintergrund'));
    if (bg && bg.options.length > 1) {
      const kindTag = k => k === 'scenario' ? ' · ' + t('Szenario') : k === 'mrio' ? ' · ' + t('Input-Output') : '';
      $('bgSel').innerHTML = `<option value="auto" ${bg.mode === 'auto' ? 'selected' : ''}>${t('Alle Prozessdaten (automatisch)')}</option>`
        + bg.options.map(o => `<option value="${esc(o.name)}" ${bg.mode === 'single' && bg.databases[0] === o.name ? 'selected' : ''}>${esc(o.name)}${kindTag(o.kind)}</option>`).join('')
        + (bg.mode === 'combined' ? `<option value="" selected>${t('Kombiniert: {n} Datenbanken', { n: bg.databases.length })}</option>` : '')
        + `<option value="*edit">${t('Kombinieren …')}</option>`;
    }
  }
  $('copyChip').innerHTML = S.st.is_copy
    ? `<span class="chip hot" title="${t('Kopie von {name}', { name: esc(S.st.original) })}">${S.st.changes.length === 1 ? t('Arbeitskopie · 1 Änderung') : t('Arbeitskopie · {n} Änderungen', { n: S.st.changes.length })}</span>`
    : S.st.is_testcopy ? `<span class="chip acc" title="${t('Kopie von {name}', { name: esc(S.st.original) })}">${t('Testkopie')}</span>` : '';
  const j = S.st.journal || [];
  $('undoBtn').hidden = !j.length;
  $('undoBtn').title = j.length ? t('Rückgängig: {label} (⌘Z / Ctrl+Z)', { label: j[0].label }) : '';
  const eb = $('explainBtn'); eb.setAttribute('aria-pressed', S.explain); eb.textContent = S.explain ? t('Erklärungen an') : t('Erklärungen aus');
  const rail = $('rail');
  rail.innerHTML = views().map(([k, l]) => `<button class="nav" data-act="view" data-k="${k}" ${S.view === k ? 'aria-current="page"' : ''}>${icon(k)}<span>${l}</span></button>`).join('');
  keepInSight(rail, '[aria-current]');
}
// on a narrow screen the views and the result tabs are rows that scroll sideways: keep the open one in sight
// (only sideways: the page itself must not move)
function keepInSight(row, sel) {
  const cur = row?.querySelector(sel);
  if (cur && row.scrollWidth > row.clientWidth) row.scrollLeft += cur.getBoundingClientRect().left - row.getBoundingClientRect().left - (row.clientWidth - cur.offsetWidth) / 2;
}
function projectTag(p) {
  return p.copy ? ' ' + t('(Arbeitskopie)') : p.testcopy ? ' ' + t('(Testkopie)') : p.legacy ? ' ' + t('(Activity Browser 2, nur als Kopie)')
    : p.rebuild ? ' ' + t('(wird beim Öffnen umgebaut)') : '';
}
function render() {
  if (!S.st.project || S.st.load_error) S.view = 'start';  // without a usable project there is only the project choice
  renderTop();
  // a text field the user is typing in keeps its text, focus and cursor when the view is drawn again
  const active = document.activeElement;
  const typing = active && active.id && $('main').contains(active) && /^(text|search)$/.test(active.type)
    ? { id: active.id, value: active.value, start: active.selectionStart, end: active.selectionEnd } : null;
  $('main').innerHTML = ({ start: vStart, daten: vDaten, modell: vModell, parameter: vParameter, rechnen: vRechnen, ergebnis: vErgebnis, vergleich: vVergleich })[S.view]();
  const el = typing && $(typing.id);
  if (el) { el.value = typing.value; el.focus(); el.setSelectionRange(typing.start, typing.end); }
  // the Sankey grows to the left; start at the product on the right
  keepInSight(document.querySelector('.tabs'), '[aria-selected="true"]');
  const sk = document.querySelector('.gwrap.sankey');
  if (sk) sk.scrollLeft = sk.scrollWidth;
  const ph = $('pedHint');
  if (ph) ph.textContent = pedigreeHint();  // what the pedigree scores give, kept current while they change
  positionTour();
}

// on a narrow screen the list stands above the detail: after choosing, go down to it
function showDetail() {
  if (window.matchMedia('(max-width:760px)').matches) document.querySelector('.dataview > .detail')?.scrollIntoView({ block: 'start' });
}

// the tour moves through the views and makes sure each one shows something
const tourHooks = {
  go,
  async prepare(what) {
    if (what === 'sheet' && !S.act && S.st.examples[0]) { S.sel = S.st.examples[0].id; S.act = await sheetFor(S.sel); render(); }
    if (what === 'editor' && !S.mact && S.mprocs.length) {
      const p = S.mprocs.find(x => x.name.startsWith('Fahrt')) || S.mprocs[0];
      S.msel = p.id; S.mact = await sheetFor(p.id); render();
    }
    if (what === 'setup' && !S.setup && S.st.setups.length) await A['open-setup'](S.st.setups[0].name);
    if (what === 'result' && !S.fu) {
      const id = S.mact?.id || S.st.examples[0]?.id;
      if (id) await setFu(id, 'beitraege');
    }
  },
  example: () => guard(() => A['example-model']()),
};

// follow a background job until it ends; `store` is the state object (S.mc or S.sens)
async function followJob(store, job, onDone) {
  try {
    while (store.job === job && job.state === 'läuft') {
      await new Promise(r => setTimeout(r, 700));
      const st = await (await request(`/api/mc/status?id=${job.id}`, { headers: langHeader() })).json();
      if (!st.state) throw new Error(typeof st.detail === 'string' ? st.detail : t('Der Hintergrundauftrag ist nicht mehr erreichbar.'));
      Object.assign(job, st);
      if (S.view === 'rechnen' && store.job === job) render();
    }
    if (store.job === job) {
      if (job.state === 'fertig') onDone(); else store.error = job.error || t('Die Rechnung ist fehlgeschlagen.');
      store.job = null;
    }
  } catch (e) { store.error = e.message; store.job = null; }
  render();
}

// ---------- actions ----------
const cwRow = () => S.cw.res?.rows.find(r => r.key === S.cw.open);
async function cwChoose(choice) {
  const r = cwRow(); if (!r) return;
  await api('/api/crosswalk/choose', { source_database: r.database, source_code: r.code, target_database: S.cw.database, ...choice });
  S.cw.open = null; S.cw.hits = null;
  await A['cw-run']();
}

const A = {
  async view(k) { await go(k); },
  explain() { S.explain = !S.explain; savePref('wb-explain', S.explain ? '1' : '0'); render(); },
  async lang() {
    setLang(LANG === 'en' ? 'de' : 'en');
    render();  // the UI texts at once; then what the server writes (history, model errors) in the new language
    await loadState(); try { await loadView(); } catch (_) { /* the view shows its own message */ }
    render();
  },
  async tour() { if (!S.st.project || S.st.load_error) { toast(t('Bitte zuerst oben ein Projekt wählen.')); return; } await startTour(tourHooks); },
  async open(k, el) { await openNode(k, el.dataset.db); },
  async 'open-here'(k) { S.sel = k; S.showAllTech = S.showAllBio = false; S.act = await sheetFor(k); render(); showDetail(); },
  async 'open-proc'(k) { S.msel = k; S.uncFor = null; S.prevScore = null; S.showAllTech = S.showAllBio = false; S.mact = await sheetFor(k); render(); showDetail(); },
  async 'open-db'(k) { S.mdb = k; S.msel = null; S.mact = null; await go('modell'); },
  'all-tech'() { S.showAllTech = !S.showAllTech; render(); },
  'all-bio'() { S.showAllBio = !S.showAllBio; render(); },
  async 'calc-act'() { const a = currentSheet(); await setFu(a.id, 'beitraege'); },
  async 'graph-act'() { const a = currentSheet(); await setFu(a.id, 'sankey'); },
  async 'calc-node'(k) { await setFu(k, S.view === 'ergebnis' ? S.tab : 'beitraege'); },
  async tab(k) { S.tab = k; render(); await loadErgebnis(); render(); },
  contrib(k) { S.contrib = k; render(); },
  gsel(k) { S.gsel = +k; render(); },
  sksel(k) { S.sksel = +k; render(); },
  async 'verify-fu'() {
    S.fuVerify = 'running'; render();
    try { S.fuVerify = await api('/api/verify', { fus: [{ id: S.fu.id, amount: S.fu.amount }], methods: [S.method] }); } catch (e) { S.fuVerify = null; throw e; } finally { render(); }
  },

  // working copy (background edits)
  async copy() { toast(t('Lege Arbeitskopie an, das dauert bis zu einer Minute …')); await loadState(await api('/api/copy', {})); await loadView(); render(); toast(t('Arbeitskopie «{name}» angelegt. Jetzt kannst du auch Hintergrunddaten ändern.', { name: S.st.project })); },
  async 'undo-copy'(k) { await loadState(await api('/api/undo', { exchange: k })); await loadView(); render(); },

  // own models
  async 'example-model'() {
    toast(t('Lege das Beispielmodell an …'));
    const r = await api('/api/beispiel', {});
    await loadState(r.state);
    S.mdb = r.database; S.msel = r.process; S.prevScore = null;
    await go('modell');
    toast(t('Beispiel «{name}» angelegt. Die Rechnung «{setup}» vergleicht es mit BAFU-Datensätzen.', { name: r.database, setup: r.setup }), { act: 'open-setup', k: r.setup, label: t('Rechnung öffnen') });
  },
  'new-db'() { S.newDb = true; if (S.view !== 'modell') S.view = 'modell'; render(); $('newDbName')?.focus(); },
  'new-db-cancel'() { S.newDb = false; render(); },
  'new-proc'() { S.newProc = true; render(); $('npName')?.focus(); },
  'new-proc-cancel'() { S.newProc = false; render(); },
  'del-db'(k) {
    openConfirm({
      title: t('Modell löschen'), ok: t('Löschen'), danger: true, busy: t('Wird gelöscht …'),
      text: t('Modell «{name}» mit allen Prozessen löschen? Das lässt sich nicht rückgängig machen.', { name: esc(k) }),
      run: async () => {
        await loadState(await api('/api/models/db/delete', { name: k }));
        S.msel = null; S.mact = null; await loadView(); render(); toast(t('«{name}» gelöscht.', { name: k }));
      },
    });
  },
  async 'copy-to-model'(k) {
    const dbs = S.st.databases.filter(d => d.role === 'model');
    openChooser({
      title: t('In welches Modell kopieren?'), text: t('Der Prozess wird mit allen Inputs und Emissionen kopiert. Das Original bleibt unverändert, die Kopie kannst du frei anpassen.'),
      options: dbs.map(d => ({ value: d.name, label: d.name, meta: t('{n} Prozesse', { n: d.count }) })), newLabel: t('In neues Modell'), newPlaceholder: t('Name des neuen Modells'),
      choose: async (db, isNew) => {
        if (isNew) await loadState(await api('/api/models/db', { name: db }));
        const r = await api('/api/models/copy', { id: k, database: db });
        closeDialog(); await loadState(); S.mdb = db; S.msel = r.id; S.prevScore = null; await go('modell');
        toast(t('Kopie angelegt. Änderungen hier wirken sofort auf das Ergebnis.'));
      },
    });
  },
  async 'dup-proc'(k) {
    const r = await api('/api/models/copy', { id: k, database: S.mdb });
    await loadState(); S.msel = r.id; S.prevScore = null; await loadView(); render(); toast(t('Prozess dupliziert.'));
  },
  async 'del-proc'(k) {
    await api('/api/models/process/delete', { id: k });
    await loadState(); S.msel = null; S.mact = null; await loadView(); render();
    toast(t('Prozess gelöscht.'), { act: 'undo', label: t('Rückgängig') });
  },
  async 'ex-del'(k) { await api('/api/models/exchange/delete', { exchange: k }); await afterModelChange(); render(); },
  'pick-input'() {
    const a = currentSheet();
    openPicker({
      kind: 'process', title: t('Input für «{name}»', { name: a.name }), hint: t('Menge pro {amount} {unit} {name}. Eigene Prozesse stehen zuoberst.', { amount: a.production, unit: esc(a.unit), name: esc(a.name) }),
      pick: async (item, amount) => { await api('/api/models/exchange/add', { id: a.id, input: item.id, amount }); closeDialog(); await afterModelChange(); render(); toast(t('«{name}» hinzugefügt.', { name: item.name })); },
    });
  },
  'pick-flow'() {
    const a = currentSheet();
    openPicker({
      kind: 'flow', title: t('Emission oder Ressource für «{name}»', { name: a.name }), hint: t('Direkte Emissionen in Luft, Wasser, Boden oder entnommene Ressourcen.'),
      pick: async (item, amount) => { await api('/api/models/exchange/add', { id: a.id, input: item.id, amount }); closeDialog(); await afterModelChange(); render(); toast(t('«{name}» hinzugefügt.', { name: item.name })); },
    });
  },
  async undo() {
    const r = await api('/api/models/undo', {});
    await afterModelChange(r.state); resetErgebnis(); await loadView(); render();
    toast(t('Rückgängig: {label}', { label: r.undone }));
  },
  async 'undo-to'(k) {
    const r = await api('/api/models/undo', { n: +k });
    await afterModelChange(r.state); resetErgebnis(); await loadView(); render();
    toast(t('Zurück bis vor: {label}', { label: r.undone }));
  },

  // calculation setups
  'new-setup'() { S.newSetup = true; render(); $('newSetupName')?.focus(); },
  'new-setup-cancel'() { S.newSetup = false; render(); },
  async 'open-setup'(k) {
    if (!S.setup || S.setup.name !== k) { S.mc = { ...S.mc, job: null, res: null, error: null }; S.sens = { j: 0, job: null, res: null, error: null }; }
    const same = S.setup && S.setup.name === k;  // the same setup again: keep its numbers until the new ones are there
    S.setup = await api(`/api/setups/get?name=${encodeURIComponent(k)}`); if (!same) S.setupRes = null; S.setupVerify = null;
    S.view = 'rechnen'; render(); showDetail(); if (S.setup.fus.length && S.setup.methods.length) { await runSetup(); render(); } else { S.setupRes = null; render(); }
  },
  'del-setup'() {
    const name = S.setup.name;
    openConfirm({
      title: t('Rechnung löschen'), ok: t('Löschen'), danger: true, busy: t('Wird gelöscht …'),
      text: t('Rechnung «{name}» löschen?', { name: esc(name) }),
      run: async () => { await loadState(await api('/api/setups/delete', { name })); S.setup = null; S.setupRes = null; render(); },
    });
  },
  async 'run-setup'() { await runSetup(); render(); },
  async 'mc-start'() {
    const cs = S.setup, mc = S.mc;
    mc.error = null; mc.res = null; mc.k = 0;
    const sig = mcSignature();
    const job = mc.job = await api('/api/mc/start', { fus: cs.fus.map(f => ({ id: f.id, amount: f.amount })), methods: cs.methods, n: mc.n });
    render();
    await followJob(mc, job, () => { mc.res = { ...job.result, seconds: job.seconds }; mc.sig = sig; });
  },
  async 'sens-start'() {
    const cs = S.setup, sn = S.sens, j = Math.min(sn.j, cs.fus.length - 1), k = Math.min(S.mc.k, cs.methods.length - 1);
    sn.error = null; sn.res = null;
    const job = sn.job = await api('/api/mc/sensitivity', { id: cs.fus[j].id, amount: cs.fus[j].amount, method: cs.methods[k], n: sn.n });
    render();
    await followJob(sn, job, () => { sn.res = job.result; });
  },
  'mc-method'(k) { S.mc.k = +k; render(); },
  async 'verify-setup'() {
    S.setupVerify = 'running'; render();
    try { S.setupVerify = await api('/api/verify', { fus: S.setup.fus.map(f => ({ id: f.id, amount: f.amount })), methods: S.setup.methods }); } catch (e) { S.setupVerify = null; throw e; } finally { render(); }
  },
  async 'export-setup'(k) {
    await download('/api/export/setup', { name: S.setup.name, format: k, fus: S.setup.fus.map(f => ({ id: f.id, amount: f.amount })), methods: S.setup.methods });
  },
  async 'export-result'(k) {
    const c = S.cats, cats = S.tab === 'kategorien';
    const fams = cats ? (c.a === '*' ? ['*'] : [c.a, c.b].filter(Boolean)) : null;
    await download('/api/export/result', { id: S.fu.id, amount: S.fu.amount, method: S.method, families: fams, topic: cats ? c.topic || null : null, format: k });
  },
  async 'cat-open'(k) {
    const [f, i] = k.split(':').map(Number);
    S.method = S.cats.res.families[f].rows[i].method; S.tab = 'beitraege'; render(); await loadView(); render();
  },
  'move-db'() { S.move = { location: '', scope: 'electricity', which: 'this', plan: null }; render(); $('moveLoc')?.focus(); },
  'move-cancel'() { S.move = null; render(); },
  async 'move-preview'() {
    const m = S.move; m.location = $('moveLoc').value.trim(); m.scope = $('moveScope').value; m.which = $('moveWhich')?.value || 'this';
    if (!m.location) { $('moveLoc').focus(); return; }
    const dbs = m.which === 'all' ? S.st.databases.filter(d => d.role === 'model').map(d => d.name) : [S.mdb];
    m.plan = await Promise.all(dbs.map(async db => ({ db, ...(await api('/api/models/reproject/plan', { database: db, location: m.location, scope: m.scope })) })));
    render();
  },
  async 'move-run'() {
    const m = S.move, dbs = m.plan.map(p => p.db);
    const r = await api('/api/models/reproject', { database: dbs[0], databases: dbs.length > 1 ? dbs : null, location: m.location, scope: m.scope });
    const made = r.made; await loadState(r.state);
    S.move = null; S.mdb = made[0].database; S.msel = null; S.mact = null; await loadView(); render();
    toast(made.length === 1 ? t('Kopie «{name}» angelegt: {n} Inputs aus {loc}. Das Original ist unverändert.', { name: made[0].database, n: made[0].changed, loc: made[0].target })
      : t('{m} Kopien für {loc} angelegt. Die Originale sind unverändert.', { m: made.length, loc: made[0].target }));
  },
  'csv-setup'() {
    const r = S.setupRes;
    csvDownload(`${S.setup.name}.csv`, [[t('Produkt'), t('Ort'), t('Menge'), t('Einheit'), ...r.methods.map(m => `${m.id.join(' | ')} [${m.unit}]`)],
      ...r.fus.map((f, i) => [f.name, f.location || '', f.amount, f.unit, ...r.scores.map(col => col[i])])]);
  },
  async 'fu-del'(k) { S.setup.fus.splice(+k, 1); await saveSetup(); await runSetup(); render(); },
  async 'm-del'(k) { S.setup.methods.splice(+k, 1); await saveSetup(); await runSetup(); render(); },
  'pick-fu'() {
    openPicker({
      kind: 'process', title: t('Produkt für «{name}»', { name: S.setup.name }), hint: t('Die Menge ist die funktionelle Einheit, zum Beispiel 1 km oder 1 Stück.'),
      pick: async (item, amount) => {
        S.setup.fus.push({ id: item.id, amount: amount || 1 }); closeDialog(); await saveSetup(); await runSetup(); render();
      },
    });
  },
  'pick-methods'() {
    openMethodPicker(S.setup.methods, async methods => { S.setup.methods = methods; closeDialog(); await saveSetup(); await runSetup(); render(); });
  },
  async 'open-result'(k) {
    const [i, j] = k.split(':').map(Number);
    fuFromSetup(i, j); S.tab = 'beitraege'; await go('ergebnis');
  },
  async 'add-setup'(k) {
    openChooser({
      title: t('Zu welcher Rechnung hinzufügen?'), options: S.st.setups.map(c => ({ value: c.name, label: c.name, meta: t('{f} Produkte · {m} Methoden', { f: c.fus, m: c.methods }) })),
      newLabel: t('Neue Rechnung'), newPlaceholder: t('Name der neuen Rechnung'),
      choose: async (name, isNew) => {
        if (isNew) S.setup = { name, fus: [], methods: [S.method] };
        else S.setup = await api(`/api/setups/get?name=${encodeURIComponent(name)}`);
        S.setup.fus.push({ id: k, amount: 1 });
        if (!S.setup.methods.length) S.setup.methods.push(S.method);
        await saveSetup(isNew ? null : name); closeDialog(); S.setupRes = null;
        toast(t('Zu «{name}» hinzugefügt ({n} Produkte).', { name: S.setup.name, n: S.setup.fus.length }), { act: 'open-setup', k: S.setup.name, label: t('Rechnung öffnen') });
        render();
      },
    });
  },

  // comparison (v1)
  'add-cmp-act'() { const a = currentSheet(); addCmp({ ...a, amount: 1 }); },
  'add-cmp-fu'() { addCmp(S.fu); },
  async 'cmp-del'(k) { S.cmp.splice(+k, 1); savePref('wb-compare', S.cmp); await runCompare(); render(); },
  async 'cmp-clear'() { S.cmp = []; savePref('wb-compare', S.cmp); await runCompare(); render(); },
  async 'cmp-orig-copy'() {
    S.cmp.push({ project: S.st.original, id: S.fu.id, amount: S.fu.amount, label: S.fu.name }, { project: S.st.project, id: S.fu.id, amount: S.fu.amount, label: S.fu.name });
    savePref('wb-compare', S.cmp); await runCompare(); render();
  },
  'csv-inv'() {
    const lab = { own: t('bewertet'), mapped: t('bewertet (Flusszuordnung)'), completed: t('bewertet (ergänzt)'), none: t('nicht bewertet') };
    csvDownload(`${t('Inventar')} ${S.fu.name}.csv`, [[t('Stoff'), t('Kompartiment'), t('Menge'), t('Einheit'), t('Methode'), t('Faktor'), t('Gleichnamiger Fluss mit Faktor'), t('Schätzung')],
      ...invRows().map(r => [r.name, r.categories, r.amount, r.unit, lab[r.status], r.factor ?? '', r.namesake ? r.namesake.categories : (r.source || ''), r.estimate ?? ''])]);
  },
  async 'csv-completed'() {
    const d = await api('/api/completion/factors', { method: S.method });
    csvDownload(`${t('Ergänzte Faktoren')} ${S.method.join(' - ')}.csv`, [[t('Stoff'), t('Kompartiment'), t('Einheit'), t('Faktor'), t('Übernommen von')], ...d.rows.map(r => [r.name, r.categories, r.unit, r.factor, r.source])]);
  },
  async 'inv-filter'(k) { S.tab = 'inventar'; S.invF = k; S.invQ = ''; render(); await loadErgebnis(); render(); document.getElementById('invTbl')?.scrollIntoView({ block: 'nearest' }); },

  // opening a project: one that Brightway would convert on opening (older Brightway 2.5, e.g. from the Activity Browser 3)
  // only after asking, with a test copy as the recommended way; one of the Activity Browser 2 only as a copy
  async 'open-project'(k) {
    const p = S.st.projects.find(x => x.name === k);
    if (!p) return;
    if (p.legacy) return A['copy-older'](k);
    if (p.rebuild) {
      openConfirm({
        title: t('Projekt «{name}» öffnen', { name: k }),
        text: t('Dieses Projekt wurde mit einer älteren Version von Brightway angelegt (z.B. im Activity Browser 3). Beim ersten Öffnen baut Brightway seine Rechendaten neu auf, das verändert Dateien im Projekt und dauert bei ecoinvent einige Minuten. Die Datenbanken selbst bleiben gleich, der Activity Browser 3 kann es weiter öffnen. <b>Empfohlen zum Ausprobieren: eine Testkopie.</b> Darin lässt sich alles ändern, das Original bleibt wie es ist. Schliesse vorher den Activity Browser.'),
        ok: t('Testkopie anlegen'),
        run: () => copyProject(k),
        alt: t('Original öffnen'),
        altRun: () => openProject(k, true),
      });
      return;
    }
    await openProject(k, false);
  },
  'copy-project'(k) {
    const p = S.st.projects.find(x => x.name === k);
    if (p?.legacy) return A['copy-older'](k);
    openConfirm({
      title: t('Testkopie von «{name}»', { name: k }),
      text: t('LCA Wrench kopiert das Projekt Datei für Datei, ohne das Original zu öffnen. In der Kopie lässt sich alles ändern, auch Datenbanken aus dem Activity Browser. <b>Das Original bleibt unverändert.</b> Schliesse vorher den Activity Browser. Bei ecoinvent dauert das einige Minuten und braucht etwa so viel Speicherplatz wie das Projekt.'),
      ok: t('Testkopie anlegen'),
      run: () => copyProject(k),
    });
  },
  // k: the content to preselect; «bafu-2026» is the usual name for that one
  async 'new-project'(k) { await newProject({ source: k || 'empty', name: k === 'bafu2026' ? 'bafu-2026' : '' }); },
  async 'import-here'(k) { await newProject({ source: k, target: S.st.project }); },
  async 'add-db'(k) { await newProject({ source: k || 'ecoinvent-account', target: S.st.project, add: true }); },
  async 'np-premise-setup'() {
    const job = await api('/api/import/start', { name: S.st.project, source: 'premise-setup' });
    S.newp.job = job; renderDialog(); await followImport(job);
  },
  async 'bg-apply'() {
    const f = S.bgForm, dbs = f.mode === 'single' ? [f.single] : f.mode === 'combined' ? [...f.multi] : [];
    await loadState(await api('/api/background', { mode: f.mode, databases: dbs })); S.bgForm = null;
    S.sopts = null; resetErgebnis(); S.setupRes = null; await loadView(); render();
    toast(t('Hintergrund: {list}', { list: S.st.background.used.join(', ') }));
  },
  'bg-remove'(k) {
    openConfirm({
      title: t('Datenbank entfernen'), ok: t('Entfernen'), danger: true, busy: t('Wird entfernt …'),
      text: t('Datenbank «{name}» aus dem Projekt entfernen? Das lässt sich nicht rückgängig machen; sie lässt sich aber neu importieren.', { name: esc(k) }),
      run: async () => {
        await loadState(await api('/api/background/remove', { name: k })); S.bgForm = null;
        S.cmp = S.cmp.filter(c => !(c.background || []).includes(k));
        S.sopts = null; resetErgebnis(); S.setupRes = null; await loadView(); render(); toast(t('«{name}» entfernt.', { name: k }));
      },
    });
  },
  async 'cmp-each-bg'() {  // the last product in the comparison, once with every process or scenario database
    const last = S.cmp[S.cmp.length - 1]; if (!last) return;
    for (const o of S.st.background.options.filter(o => o.kind !== 'mrio')) S.cmp.push({ project: S.st.project, id: last.id, amount: last.amount, label: last.label, background: [o.name] });
    savePref('wb-compare', S.cmp); await runCompare(); render();
  },
  'np-back'() { S.newp.job = null; renderDialog(); },
  async 'np-login'() {
    const n = S.newp;
    n.versions = (await api('/api/ecoinvent/versions', { username: n.username || null, password: n.password || null })).versions;
    if (!n.versions.includes(n.version)) n.version = n.versions[0] || '';
    renderDialog();
  },
  // projects of the Activity Browser 2: only as a converted copy, the original stays as it is
  'copy-older'(k) {
    openConfirm({
      title: t('Projekt aus dem Activity Browser 2'),
      text: t('«{name}» hat das ältere Format von Brightway 2. Würde LCA Wrench es direkt öffnen, baute Brightway es um, und der Activity Browser 2 könnte es danach nicht mehr lesen. Darum legt LCA Wrench eine Kopie an und wandelt nur die Kopie um. <b>Das Original bleibt unverändert.</b> Schliesse vorher den Activity Browser. Bei ecoinvent dauert das einige Minuten und braucht etwa so viel Speicherplatz wie das Projekt.', { name: esc(k) }),
      ok: t('Kopie anlegen'),
      run: () => copyProject(k),
    });
  },
  async 'confirm-alt'() { await confirmedAlt(); },
  async 'confirm-ok'() { await confirmed(); },

  // parameters (project, model, process) and formulas of amounts
  'par-add'(k) { S.par.adding = k; render(); $('parNewName')?.focus(); },
  'par-add-cancel'() { S.par.adding = null; render(); },
  'par-add-proc'() { A['par-add'](JSON.stringify({ scope: 'activity', database: S.par.data.database.name, activity: $('parProc').value })); },
  async 'par-add-save'(k) {
    const r = await api('/api/params/set', { ...JSON.parse(k), name: $('parNewName').value.trim(), value: $('parNewValue').value, view: S.mdb });
    S.par.adding = null; S.par.data = r.overview; await loadState(r.state); render();
  },
  async 'par-del'(k) {
    const r = await api('/api/params/delete', { ...JSON.parse(k), view: S.mdb });
    S.par.data = r.overview; await loadState(r.state); render(); toast(t('Parameter gelöscht.'), { act: 'undo', label: t('Rückgängig') });
  },
  async 'open-proc-from-par'(k) { S.msel = k; S.mact = null; S.prevScore = null; await go('modell'); },
  'unc-edit'(k) {
    const a = currentSheet(), e = a && [...a.technosphere, ...a.biosphere].find(x => x.exchange === k);
    S.uncFor = S.uncFor === k ? null : k; S.uncType = uncEditType(e && e.uncertainty); render();
  },
  'unc-cancel'() { S.uncFor = null; render(); },
  'full-comment'(k) { S.fullComment = S.fullComment === k ? null : k; render(); },
  'ex-formula'(k) { S.formulaFor = k; render(); const el = document.querySelector(`[data-exf="${k}"]`); el?.focus(); },

  // versions: the product in another version of the background data
  async 'ver-run'() {
    const v = S.ver;
    v.running = true; v.error = null; v.res = null; v.detail = null; v.k = null; render();
    try { v.res = await api('/api/versions', { id: S.fu.id, amount: S.fu.amount, method: S.method, project: v.project, database: v.database }); }
    catch (e) { v.error = e.message; }
    finally { v.running = false; render(); }
  },
  async 'ver-detail'(k) { S.ver.k = +k; S.ver.detail = await api(`/api/versions/detail?k=${+k}`); render(); },

  // BAFU <-> ecoinvent: the product with another background database
  async 'cw-run'() {
    const c = S.cw;
    c.running = true; c.error = null; c.trace = {}; render();
    try { c.res = await api('/api/crosswalk', { id: S.fu.id, amount: S.fu.amount, method: S.method, project: c.project, database: c.database, target_method: c.method ? JSON.parse(c.method) : null }); }
    catch (e) { c.error = e.message; c.res = null; }
    finally { c.running = false; render(); }
  },
  'cw-edit'(k) {
    const r = S.cw.res.rows[+k];
    S.cw.open = S.cw.open === r.key ? null : r.key; S.cw.hits = null; S.cw.loc = null;
    S.cw.q = r.name.replace(/^xx\s+/i, '').replace(/,\s*at\s+.*$/i, '');
    render(); $('cwQ')?.focus();
  },
  'cw-close'() { S.cw.open = null; S.cw.hits = null; render(); },
  'cw-view'(k) { S.cw.view = k; render(); },
  'cw-fix'(k) { S.cw.view = 'datasets'; S.cw.open = null; A['cw-edit'](k); },
  // one level down the supply chain of a pair of datasets; open again to close
  async 'cw-trace'(path) {
    const c = S.cw, tr = c.trace;
    if (tr[path]) { Object.keys(tr).filter(p => p === path || p.startsWith(path + '/')).forEach(p => delete tr[p]); render(); return; }
    tr[path] = { loading: true }; render();
    try {
      const res = await api('/api/crosswalk/trace', { ...traceSpec(path), method: c.res.a.method, project: c.res.b.project, database: c.res.b.database, target_method: c.res.b.method });
      if (tr[path]) tr[path] = { res };
    } catch (e) { if (tr[path]) tr[path] = { error: e.message }; }
    render();
  },
  'cw-trace-all'(path) { if (S.cw.trace[path]) S.cw.trace[path].all = true; render(); },
  async 'cw-search'() {
    const c = S.cw, r = cwRow();
    c.q = $('cwQ')?.value.trim() || ''; c.loc = $('cwLoc')?.value.trim() ?? null;
    c.hits = c.q ? await api('/api/crosswalk/search', { project: c.project, database: c.database, q: c.q, unit: r?.unit_long, location: c.loc || null }) : null;
    render(); $('cwQ')?.focus();
  },
  async 'cw-pick'(code) { await cwChoose({ target_code: code }); },
  async 'cw-none'() { await cwChoose({ target_code: null }); },
  async 'cw-reset'() { await cwChoose({ reset: true }); },
  async 'cw-ok'(k) {
    const r = S.cw.res.rows[+k];
    await api('/api/crosswalk/choose', { source_database: r.database, source_code: r.code, target_database: S.cw.database, target_code: r.match.code });
    await A['cw-run']();
  },
  async 'cw-ok-all'() {
    const c = S.cw, by = {};
    c.res.rows.filter(r => r.origin === 'auto' && r.quality === 'good' && r.match)
      .forEach(r => (by[r.database] = by[r.database] || []).push({ source: r.code, target: r.match.code }));
    let n = 0;
    for (const [db, pairs] of Object.entries(by)) n += (await api('/api/crosswalk/confirm', { source_database: db, target_database: c.database, pairs })).saved;
    toast(t('{n} Zuordnungen bestätigt.', { n }));
    await A['cw-run']();
  },

  // dialogs
  'dlg-close'() { closeDialog(); },
  'toast-close'() { /* the click on the toast hides it */ },
  async 'pk-pick'(k) { const amt = parseFloat($('pkAmt')?.value ?? '1'); await picked(S.picker.results[+k], isFinite(amt) ? amt : 1); },
  async 'ch-pick'(k) { await chosen(k, false); },
  'mp-all'(k, el, ev) {
    ev.preventDefault();
    const ms = S.st.methods.filter(m => m.family === k), all = ms.every(m => S.mpicker.sel.has(mKey(m.id)));
    ms.forEach(m => all ? S.mpicker.sel.delete(mKey(m.id)) : S.mpicker.sel.add(mKey(m.id))); S.mpicker.open.add(k); renderDialog();
  },
  async 'mp-apply'() { await methodsApplied(); },
};

function addCmp(src) {
  S.cmp.push({ project: S.st.project, id: src.id, amount: src.amount, label: src.name }); savePref('wb-compare', S.cmp);
  toast(t('«{name}» ist im Vergleich ({n} Einträge).', { name: src.name, n: S.cmp.length }), { act: 'view', k: 'vergleich', label: t('Ansehen') });
}

// ---------- events ----------
// an action runs once at a time: a second click while it runs (impatient, or a double click) is ignored,
// and a button that takes a while says so
const running = new Set();
document.addEventListener('click', ev => {
  const b = ev.target.closest('[data-act]'); if (!b || b.disabled) return;
  const fn = A[b.dataset.act]; if (!fn) return;
  if (b.closest('#toast')) $('toast').hidden = true;
  const key = b.dataset.act + '|' + (b.dataset.k ?? '');
  if (running.has(key)) return;
  running.add(key);
  const slow = setTimeout(() => b.setAttribute('aria-busy', 'true'), 300);
  guard(() => fn(b.dataset.k, b, ev)).finally(() => { running.delete(key); clearTimeout(slow); b.removeAttribute('aria-busy'); });
});
document.addEventListener('keydown', ev => {
  if (tourKey(ev)) { ev.preventDefault(); return; }
  const g = ev.target.closest && ev.target.closest('.gnode, .sk-node');
  if (g && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); guard(() => A[g.dataset.act](g.dataset.k)); return; }
  if (/^parNew(Name|Value)$/.test(ev.target.id) && (ev.key === 'Enter' || ev.key === 'Escape')) {
    ev.preventDefault(); guard(() => ev.key === 'Enter' ? A['par-add-save'](S.par.adding) : A['par-add-cancel']()); return;
  }
  if (ev.key === 'Escape' && ev.target.dataset?.exf && S.formulaFor === ev.target.dataset.exf) { S.formulaFor = null; render(); return; }
  if ((ev.target.id === 'cwQ' || ev.target.id === 'cwLoc') && ev.key === 'Enter') { ev.preventDefault(); guard(() => A['cw-search']()); return; }
  const editing = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
  if ((ev.metaKey || ev.ctrlKey) && !ev.shiftKey && ev.key.toLowerCase() === 'z' && !editing && (S.st?.journal || []).length) {
    ev.preventDefault(); guard(() => A.undo());
  }
});
document.addEventListener('submit', ev => {
  const f = ev.target; ev.preventDefault();
  guard(async () => {
    if (f.id === 'moveForm') await A['move-preview']();
    else if (f.id === 'searchForm') {
      S.q = $('q').value; S.loc = $('loc').value.trim(); S.dbf = $('dbf').value; S.unit = $('unit').value;
      S.results = await api(`/api/search?q=${encodeURIComponent(S.q)}&loc=${encodeURIComponent(S.loc)}&db=${encodeURIComponent(S.dbf)}&unit=${encodeURIComponent(S.unit)}`); render(); $('q').focus();
    } else if (f.id === 'pkForm') {
      const p = S.picker; p.q = $('pkQ').value; p.loc = ($('pkLoc')?.value || '').trim(); p.amount = parseFloat($('pkAmt')?.value ?? '1') || 1;
      p.unit = $('pkUnit')?.value || ''; p.comp = $('pkComp')?.value || '';
      p.results = await api(`/api/search?q=${encodeURIComponent(p.q)}&loc=${encodeURIComponent(p.loc)}&kind=${p.kind}&unit=${encodeURIComponent(p.unit)}&comp=${encodeURIComponent(p.comp)}&limit=80`); renderDialog(); $('pkQ').focus();
    } else if (f.id === 'newDbForm') {
      const name = $('newDbName').value.trim();
      await loadState(await api('/api/models/db', { name })); S.newDb = false; S.mdb = name; S.msel = null; S.mact = null; await loadView(); render();
      toast(t('Modell «{name}» angelegt. Jetzt den ersten Prozess anlegen.', { name }));
    } else if (f.id === 'newProcForm') {
      const r = await api('/api/models/process', { database: S.mdb, name: $('npName').value.trim(), unit: $('npUnit').value, location: $('npLoc').value.trim() || 'GLO', comment: ($('npDesc')?.value || '').trim() });
      S.newProc = false; await loadState(); S.msel = r.id; S.prevScore = null; await loadView(); render();
      toast(t('Prozess angelegt. Füge jetzt Inputs hinzu.'));
    } else if (f.id === 'newSetupForm') {
      const name = $('newSetupName').value.trim();
      S.setup = { name, fus: [], methods: [S.method] }; S.setupRes = null; S.newSetup = false;
      await saveSetup(null); render();
    } else if (f.id === 'uncForm') {
      const v = id => $(id)?.value ?? null;
      const scores = {}; f.querySelectorAll('[data-ped]').forEach(x => { scores[x.dataset.ped] = +x.value; });
      const spec = { type: $('uncType').value, gsd2: v('uncGsd'), sd: v('uncSd'), minimum: v('uncMin'), maximum: v('uncMax'), scores, basic: v('uncBasic') };
      const a = currentSheet(); if (a) S.prevScore = { id: a.id, v: a.score };
      await api('/api/models/exchange/uncertainty', { exchange: f.dataset.k, spec }); S.uncFor = null;
      await afterModelChange(); render(); toast(t('Unsicherheit gespeichert. Sie gilt in der Unsicherheitsrechnung.'));
    } else if (f.id === 'chNewForm') {
      await chosen($('chNew').value.trim(), true);
    } else if (f.id === 'nprjForm') {
      await submitNewProject();
    }
  });
});
// every category of one method side by side: the "All categories" tab of the result
async function showAllCategories(fam) {
  S.cats.a = fam; S.cats.b = ''; S.cats.topic = ''; S.tab = 'kategorien';
  if (S.view === 'ergebnis') { render(); await loadView(); render(); } else await go('ergebnis');
}

document.addEventListener('change', ev => {
  const el = ev.target;
  guard(async () => {
    if (el.id === 'methSel' && el.value === '*') { await showAllCategories(methodInfo().family); }
    else if (el.id === 'methSel') { S.method = JSON.parse(el.value); render(); await loadView(); render(); }
    else if (el.id === 'famSel') {
      // the same kind of impact in the new method if it has one (climate change → climate change), else its first category
      const pool = S.view === 'vergleich' && S.cmpCover ? S.st.methods.filter(m => S.cmpCover.has(mKey(m.id))) : S.st.methods;
      const ms = pool.filter(m => m.family === el.value), tp = methodInfo().topic;
      S.method = (ms.find(m => m.topic === tp && tp !== 'other') || ms[0]).id; render(); await loadView(); render();
    }
    else if (el.id === 'complChk') {
      S.st.completion = await api('/api/completion', { enabled: el.checked });
      if (S.invF === 'completed') S.invF = '';
      resetErgebnis(); S.setupRes = null; await loadView(); render();
    }
    else if (el.id === 'invF') { S.invF = el.value; render(); }
    else if (el.id === 'flowmapChk') { S.st.flowmap = await api('/api/flowmap', { enabled: el.checked }); await runCompare(); render(); }
    else if ((el.id === 'pkUnit' || el.id === 'pkComp') && S.picker) { if ($('pkQ').value.trim()) $('pkForm').requestSubmit(); }
    else if (el.id === 'projSel') {
      const name = el.value;
      el.value = S.st.project || '';  // the select shows the open project until the new one is really open
      await A['open-project'](name);
    }
    else if (el.dataset.ex) {
      const v = parseFloat(el.value); if (!isFinite(v)) { toast(t('Bitte eine Zahl eingeben.'), null, true); render(); return; }
      const a = currentSheet(); if (a) S.prevScore = { id: a.id, v: a.score };
      await loadState(await api('/api/edit', { exchange: el.dataset.ex, amount: v }));
      await refreshSheet(); render();
    }
    else if (el.id === 'uncType') { S.uncType = el.value; render(); document.querySelector('#uncForm input')?.focus(); }
    else if (el.dataset.extype) {
      await api('/api/models/exchange/update', { exchange: el.dataset.extype, kind: el.value }); await afterModelChange(); render();
    }
    else if (el.dataset.pf) {
      const a = currentSheet();
      await api('/api/models/process/update', { id: a.id, fields: { [el.dataset.pf]: el.value } }); await afterModelChange(); render();
    }
    else if (el.id === 'xlsxIn') {
      const f = el.files[0]; el.value = ''; if (!f) return;
      toast(t('Lese «{name}» …', { name: f.name }));
      const r = await request('/api/models/import', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', ...langHeader() }, body: await f.arrayBuffer() });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : t('Der Import ist fehlgeschlagen.'));
      await loadState(d.state); S.mdb = d.database; S.msel = null; S.mact = null; S.view = 'modell'; await loadView(); render();
      const kept = d.kept_project_parameters || [];
      toast(t('Modell «{name}» importiert ({n} Prozesse). Alle Austausche sind mit den Daten im Projekt verknüpft.', { name: d.database, n: d.processes })
        + (kept.length ? ' ' + t('Die Projekt-Parameter {names} gab es schon; es gelten die Werte dieses Projekts.', { names: kept.join(', ') }) : ''));
    }
    else if (el.dataset.pv || el.dataset.pn) {
      // a parameter row: new value or formula, or a new name (rename keeps the value)
      const key = JSON.parse(el.dataset.pv || el.dataset.pn);
      const list = key.scope === 'project' ? S.par.data.project : key.scope === 'database' ? S.par.data.database.params
        : S.par.data.processes.find(p => p.id === key.activity).params;
      const p = list.find(x => x.name === key.name);
      const body = el.dataset.pv ? { ...key, value: el.value } : { ...key, name: el.value.trim(), old_name: key.name, value: p.formula ?? String(p.amount) };
      try { const r = await api('/api/params/set', { ...body, view: S.mdb }); S.par.data = r.overview; await loadState(r.state); }
      finally { render(); }
    }
    else if (el.dataset.exf) {
      const a = currentSheet(); if (a) S.prevScore = { id: a.id, v: a.score };
      S.formulaFor = null;
      try { await afterModelChange(await api('/api/models/exchange/formula', { exchange: el.dataset.exf, formula: el.value })); }
      finally { render(); }
    }
    else if (el.id === 'parDb') { S.mdb = el.value; S.msel = null; S.mact = null; S.par.adding = null; await loadView(); render(); }
    else if (el.id === 'verProj') { S.ver.project = el.value; S.ver.targets = null; S.ver.res = S.ver.detail = null; await loadTargets(); render(); }
    else if (el.id === 'verDb') { S.ver.database = el.value; S.ver.res = S.ver.detail = null; render(); }
    else if (el.id === 'cwProj') { S.cw.project = el.value; S.cw.targets = null; S.cw.res = null; S.cw.open = null; await loadCw(); render(); }
    else if (el.id === 'cwDb') { S.cw.database = el.value; S.cw.res = null; S.cw.open = null; render(); }
    else if (el.id === 'cwMethod') { S.cw.method = el.value; S.cw.res = null; render(); }
    else if (el.id === 'cwFile') {
      const f = el.files[0]; el.value = ''; if (!f || !S.cw.res) return;
      const src = S.cw.res.rows[0]?.database || S.fu.database;
      const r = await request(`/api/crosswalk/import?source_database=${encodeURIComponent(src)}&target_database=${encodeURIComponent(S.cw.database)}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', ...langHeader() }, body: await f.arrayBuffer() });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : t('Der Import ist fehlgeschlagen.'));
      toast(t('{n} Zuordnungen aus «{name}» geladen.', { n: d.saved, name: f.name }));
      await A['cw-run']();
    }
    else if (el.id === 'mcN') { S.mc.n = +el.value; render(); }
    else if (el.id === 'catA') { S.cats.a = el.value; render(); await loadCats(); render(); }
    else if (el.id === 'catB') { S.cats.b = el.value; render(); await loadCats(); render(); }
    else if (el.id === 'catTopic') { S.cats.topic = el.value; render(); await loadCats(); render(); }
    else if (['moveLoc', 'moveScope', 'moveWhich'].includes(el.id) && S.move) {
      Object.assign(S.move, { location: $('moveLoc').value.trim(), scope: $('moveScope').value, which: $('moveWhich')?.value || 'this', plan: null }); render();
    }
    else if (el.id === 'sensFu') { S.sens.j = +el.value; }
    else if (el.id === 'sensN') { S.sens.n = +el.value; }
    else if (el.id === 'bgSel') {
      if (el.value === '*edit') { S.view = 'start'; S.bgForm = null; render(); $('bgCard')?.scrollIntoView({ behavior: 'smooth' }); return; }
      if (!el.value) return;
      S.bgForm = { mode: el.value === 'auto' ? 'auto' : 'single', single: el.value, multi: new Set() };
      await A['bg-apply']();
    }
    else if (el.name === 'bgMode' && S.bgForm) { S.bgForm.mode = el.value; render(); }
    else if (el.id === 'bgSingle' && S.bgForm) { S.bgForm.single = el.value; }
    else if (el.dataset.bgdb !== undefined && S.bgForm) { el.checked ? S.bgForm.multi.add(el.dataset.bgdb) : S.bgForm.multi.delete(el.dataset.bgdb); }
    else if (el.id === 'mdbSel') { S.mdb = el.value; S.msel = null; S.mact = null; await loadView(); render(); }
    else if (el.id === 'fuSetup') { fuFromSetup(+el.value); render(); await loadErgebnis(); render(); }
    else if (el.id === 'fuAmt') { const v = parseFloat(el.value); if (isFinite(v) && v > 0) { S.fu.amount = v; resetErgebnis(); await loadErgebnis(); } render(); }
    else if (el.id === 'cutSel') { S.cutoff = +el.value; await loadErgebnis(); render(); }
    else if (el.id === 'depSel') { S.depth = +el.value; await loadErgebnis(); render(); }
    else if (el.id === 'skMode') { S.skMode = el.value; render(); }
    else if (el.id === 'skCut') { S.skCut = +el.value; S.sksel = null; await loadErgebnis(); render(); }
    else if (el.id === 'skMax') { S.skMax = +el.value; S.sksel = null; await loadErgebnis(); render(); }
    else if (el.id === 'csName') { const old = S.setup.name; S.setup.name = el.value.trim() || old; await saveSetup(old); render(); }
    else if (el.dataset.fuamt !== undefined) {
      const v = parseFloat(el.value); if (!isFinite(v)) { render(); return; }
      S.setup.fus[+el.dataset.fuamt].amount = v; await saveSetup(); await runSetup(); render();
    }
    else if (el.dataset.mp) { const k = el.dataset.mp; el.checked ? S.mpicker.sel.add(k) : S.mpicker.sel.delete(k); renderDialog(); }
    else if (el.dataset.np && S.newp) {
      S.newp[el.dataset.np] = el.type === 'checkbox' ? el.checked : el.value;
      if (el.dataset.npGuess && el.value.trim()) Object.assign(S.newp, await api(`/api/ecoinvent/guess?path=${encodeURIComponent(el.value.trim())}`));
      if (el.dataset.np === 'source' || el.dataset.npGuess || el.dataset.npRender) renderDialog();
    }
  });
});
let invT;
document.addEventListener('input', ev => {
  const el = ev.target;
  if (el.id === 'invQ') { clearTimeout(invT); invT = setTimeout(() => { S.invQ = el.value; render(); }, 160); }
  else if (el.dataset.np && S.newp && el.type !== 'radio' && el.type !== 'checkbox') S.newp[el.dataset.np] = el.value;
  else if (el.id === 'mpQ') { S.mpicker.q = el.value; const pos = el.selectionStart; renderDialog(); const box = $('mpQ'); box.focus(); box.setSelectionRange(pos, pos); }
  else if (el.dataset.ped || el.id === 'uncBasic') { const h = $('pedHint'); if (h) h.textContent = pedigreeHint(); }
});
document.addEventListener('toggle', ev => {
  const d = ev.target; if (d.classList?.contains('mfam') && S.mpicker) { d.open ? S.mpicker.open.add(d.dataset.fam) : S.mpicker.open.delete(d.dataset.fam); }
}, true);
$('dlg').addEventListener('close', () => { S.picker = S.mpicker = S.chooser = S.confirm = S.newp = null; });
// Esc must not hide a running copy or import
$('dlg').addEventListener('cancel', ev => { if (S.confirm?.running || (S.newp?.job?.state === 'läuft' && !['premise', 'premise-setup', 'exiobase'].includes(S.newp.job.source))) ev.preventDefault(); });

loadPrefs();
renderBusy();
window.addEventListener('resize', positionTour);
window.addEventListener('scroll', positionTour, { passive: true });
$('main').innerHTML = `<section class="card" style="display:flex;flex-direction:column;gap:8px;max-width:640px"><p class="busy">${t('Lade Brightway-Projekt …')} <span class="num" id="loadSecs"></span></p>
  <p class="muted" style="font-size:13.5px">${t('Beim ersten Öffnen eines grossen Projekts (ecoinvent) bereitet LCA Wrench die Rechnung vor. Das dauert eine bis zwei Minuten, danach geht jede Rechnung schnell.')}</p></section>`;
const loadStart = Date.now();
const loadTick = setInterval(() => { const el = $('loadSecs'); if (el) el.textContent = `${Math.round((Date.now() - loadStart) / 1000)} s`; else clearInterval(loadTick); }, 1000);
guard(async () => { await resumeImport(); await loadState(); clearInterval(loadTick); render(); if (S.st.project && !S.st.load_error && shouldAutoStart()) await startTour(tourHooks); });

// Changes from outside (e.g. Activity Browser): the server compares the project files, we reload when it saw one
async function pollExternal() {
  if (!S.st || S.busy || S.importing || document.hidden) return;
  let p;
  try { p = await (await fetch('/api/poll', { headers: langHeader() })).json(); } catch (_) { return; }
  if (typeof p.external !== 'number' || p.external === S.st.external) return;
  await loadState();
  resetErgebnis();
  try { await loadView(); } catch (_) { S.act = S.sel = S.fu = null; }
  render();
  toast(p.what?.length ? t('Ein anderes Programm hat das Projekt geändert. Die Ansicht ist neu geladen ({what}).', { what: p.what.join(', ') })
    : t('Ein anderes Programm hat das Projekt geändert. Die Ansicht ist neu geladen.'));
}
setInterval(() => guard(pollExternal), 3000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) guard(pollExternal); });
