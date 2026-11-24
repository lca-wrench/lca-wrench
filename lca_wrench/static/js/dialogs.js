// Modal dialogs: search picker, method picker, target chooser, new project / import.
'use strict';
import { S, $, api, esc, mKey, methodLabel, familyLabel, isModelDb, spellingNote, unitGroups, compartments, t } from './core.js';
import { locList } from './views/daten.js';

let onPick = null;
let onChoose = null;
let onConfirm = null;

export function openPicker({ kind, title, hint, withAmount = true, pick }) {
  S.picker = { kind, title, hint, withAmount, q: '', loc: '', unit: '', comp: '', results: [], amount: 1 };
  S.mpicker = null; S.chooser = null; S.confirm = null; onPick = pick;
  renderDialog(); showDlg(); setTimeout(() => $('pkQ')?.focus(), 30);
  // the unit and compartment lists come from the data
  if (!S.sopts && S.st?.databases?.length) api('/api/search/options').then(o => { S.sopts = o; if (S.picker) { const q = $('pkQ')?.value; renderDialog(); if (q != null) $('pkQ').value = q; } }).catch(() => {});
}
export function openMethodPicker(selected, apply) {
  S.mpicker = { sel: new Set(selected.map(mKey)), q: '', open: new Set() };
  S.picker = null; S.chooser = null; S.confirm = null; onPick = apply;
  renderDialog(); showDlg(); setTimeout(() => $('mpQ')?.focus(), 30);
}
export function openChooser({ title, text, options, newLabel, newPlaceholder, choose }) {
  S.chooser = { title, text, options, newLabel, newPlaceholder };
  S.picker = null; S.mpicker = null; S.confirm = null; onChoose = choose;
  renderDialog(); showDlg();
}
// a question with one action; while the action runs the dialog says so and cannot be closed
// alt/altRun: an optional second choice (e.g. «open the original anyway» next to «make a test copy»)
let onAlt = null;
// danger: something is deleted for good; the red button, and the focus starts on "Cancel" (Enter does not delete)
// busy: what the dialog says while it runs (default: a copy that takes minutes)
export function openConfirm({ title, text, ok, run, alt, altRun, danger = false, busy = null }) {
  S.confirm = { title, text, ok, alt, danger, busy, running: false };
  S.picker = S.mpicker = S.chooser = null; onConfirm = run; onAlt = altRun || null;
  renderDialog(); showDlg();
}
export async function confirmed() {
  if (!onConfirm || !S.confirm || S.confirm.running) return;
  S.confirm.running = true; renderDialog();
  try { await onConfirm(); } finally { closeDialog(); }
}
export async function confirmedAlt() {
  if (!onAlt || !S.confirm || S.confirm.running) return;
  S.confirm.running = true; renderDialog();
  try { await onAlt(); } finally { closeDialog(); }
}
export const picked = (item, amount) => onPick && onPick(item, amount);
export const chosen = (value, isNew) => onChoose && onChoose(value, isNew);
export const methodsApplied = () => onPick && onPick(S.st.methods.filter(m => S.mpicker.sel.has(mKey(m.id))).map(m => m.id));

// new project: empty, or with data (BAFU 2026, ecoinvent with an account or from files); while importing, its steps
export function openNewProject(np) {
  S.newp = np; S.picker = S.mpicker = S.chooser = S.confirm = null;
  renderDialog(); showDlg(); setTimeout(() => $('nprjName')?.focus(), 30);
}

function showDlg() { const d = $('dlg'); if (!d.open) d.showModal(); }
export function closeDialog() { const d = $('dlg'); if (d.open) d.close(); d.removeAttribute('role'); S.picker = S.mpicker = S.chooser = S.confirm = S.newp = null; onPick = onChoose = onConfirm = onAlt = null; }

export function renderDialog() {
  const body = $('dlgBody');
  if (S.picker) body.innerHTML = pickerHtml();
  else if (S.mpicker) body.innerHTML = methodHtml();
  else if (S.chooser) body.innerHTML = chooserHtml();
  else if (S.confirm) body.innerHTML = confirmHtml();
  else if (S.newp) body.innerHTML = newProjectHtml();
  // screen readers announce the dialog by its heading and, for a question, its text
  const d = $('dlg'), h = body.querySelector('h2'), p = body.querySelector('.dlgtext');
  if (h) { h.id = 'dlgTitle'; d.setAttribute('aria-labelledby', 'dlgTitle'); } else d.removeAttribute('aria-labelledby');
  if (p) { p.id = 'dlgText'; d.setAttribute('aria-describedby', 'dlgText'); } else d.removeAttribute('aria-describedby');
  if (S.confirm?.danger) d.setAttribute('role', 'alertdialog'); else d.removeAttribute('role');
}

const closeBtn = () => `<button class="iconbtn" data-act="dlg-close" aria-label="${t('Schliessen')}">×</button>`;

function pickerHtml() {
  const p = S.picker;
  const list = p.results.length ? spellingNote(p.results) + p.results.map((r, i) => `<button class="res" data-act="pk-pick" data-k="${i}"><span>${esc(r.name)}</span><span class="meta">${p.kind === 'flow' ? esc(r.categories) + ' · ' : esc(r.location) + (r.region ? ` <span class="chip">${t('statt {loc}', { loc: esc(r.region) })}</span>` : '') + ' · '}${esc(r.unit)}${isModelDb(r.database) ? ' · ' + t('Modell') : ''}</span>${r.comment ? `<span class="rdesc" title="${esc(r.comment)}">${esc(r.comment)}</span>` : ''}</button>`).join('')
    : `<p class="empty">${p.q ? t('Kein Treffer. Versuch einen englischen Begriff.') : p.kind === 'flow' ? t('Suche nach einem Stoff, z.B. «carbon dioxide», «CO2», «PM2.5» oder «Lachgas». Tippfehler werden korrigiert.') : t('Suche nach einem Prozess, z.B. «steel», «electricity» oder «transport».')}</p>`;
  return `<div class="dlghead"><h2>${esc(p.title)}</h2>${closeBtn()}</div>
    ${p.hint ? `<p class="muted" style="font-size:13.5px">${p.hint}</p>` : ''}
    <form id="pkForm" class="row" style="gap:8px">
      <input type="search" id="pkQ" value="${esc(p.q)}" placeholder="${p.kind === 'flow' ? t('z.B. carbon dioxide') : t('z.B. steel')}" style="flex:1 1 220px" aria-label="${t('Suchen')}">
      ${p.kind === 'flow'
        ? `<select id="pkComp" aria-label="${t('Kompartiment')}"><option value="">${t('Alle Kompartimente')}</option>${Object.entries(compartments()).filter(([k]) => !S.sopts || (S.sopts.compartments || []).includes(k)).map(([k, l]) => `<option value="${k}" ${k === p.comp ? 'selected' : ''}>${l}</option>`).join('')}</select>`
        : `<input type="text" id="pkLoc" list="pkLocList" value="${esc(p.loc || '')}" placeholder="${t('Ort')}" style="width:130px" aria-label="${t('Ort')}" autocomplete="off">${locList('pkLocList')}`}
      <select id="pkUnit" aria-label="${t('Einheit')}"><option value="">${t('Alle Einheiten')}</option>${Object.entries(unitGroups()).filter(([k]) => !S.sopts || (p.kind === 'flow' ? S.sopts.flow_units || [] : S.sopts.units).includes(k)).map(([k, l]) => `<option value="${k}" ${k === p.unit ? 'selected' : ''}>${l}</option>`).join('')}</select>
      ${p.withAmount ? `<label class="f" style="flex-direction:row;align-items:center;gap:6px">${t('Menge')}<input type="number" id="pkAmt" step="any" value="${p.amount}"></label>` : ''}
      <button class="btn primary" type="submit">${t('Suchen')}</button>
    </form>
    <div class="reslist pklist">${list}</div>`;
}

function methodHtml() {
  const mp = S.mpicker;
  const q = mp.q.trim().toLowerCase();
  const fams = [...new Set(S.st.methods.map(m => m.family))].sort((a, b) => a === 'Werkbank' ? -1 : b === 'Werkbank' ? 1 : a.localeCompare(b));
  const groups = fams.map(f => {
    const ms = S.st.methods.filter(m => m.family === f && (!q || (m.family + ' ' + m.name).toLowerCase().includes(q)));
    if (!ms.length) return '';
    const nSel = ms.filter(m => mp.sel.has(mKey(m.id))).length;
    const open = q || mp.open.has(f) || f === 'Werkbank' || fams.length < 4;
    return `<details class="mfam" ${open ? 'open' : ''} data-fam="${esc(f)}"><summary><span>${esc(familyLabel(f))}</span><span class="muted">${nSel}/${ms.length}</span>
      <button class="linkbtn" data-act="mp-all" data-k="${esc(f)}">${nSel === ms.length ? t('keine') : t('alle')}</button></summary>
      ${ms.map(m => `<label class="mrow"><input type="checkbox" data-mp='${esc(mKey(m.id))}' ${mp.sel.has(mKey(m.id)) ? 'checked' : ''}> <span>${esc(methodLabel(m))}</span> <span class="muted">${esc(m.unit)}</span></label>`).join('')}</details>`;
  }).join('');
  return `<div class="dlghead"><h2>${t('Wirkungsmethoden wählen')}</h2>${closeBtn()}</div>
    <input type="search" id="mpQ" value="${esc(mp.q)}" placeholder="${t('Filtern, z.B. climate, water')}" aria-label="${t('Methoden filtern')}">
    <div class="mlist">${groups || `<p class="empty">${t('Keine Methode passt.')}</p>`}</div>
    <div class="row" style="justify-content:space-between"><span class="muted">${t('{n} gewählt', { n: mp.sel.size })}</span><div class="row" style="gap:8px"><button class="btn" data-act="dlg-close">${t('Abbrechen')}</button><button class="btn primary" data-act="mp-apply">${t('Übernehmen')}</button></div></div>`;
}

function chooserHtml() {
  const c = S.chooser;
  return `<div class="dlghead"><h2>${esc(c.title)}</h2>${closeBtn()}</div>
    ${c.text ? `<p class="muted" style="font-size:14px">${c.text}</p>` : ''}
    ${c.options.length ? `<div class="reslist">${c.options.map(o => `<button class="res" data-act="ch-pick" data-k="${esc(o.value)}"><span>${esc(o.label)}</span>${o.meta ? `<span class="meta">${esc(o.meta)}</span>` : ''}</button>`).join('')}</div>` : ''}
    ${c.newLabel ? `<form id="chNewForm" class="row" style="gap:8px"><input type="text" id="chNew" required maxlength="120" placeholder="${esc(c.newPlaceholder || '')}" style="flex:1 1 220px" aria-label="${esc(c.newLabel)}"><button class="btn primary" type="submit">${esc(c.newLabel)}</button></form>` : ''}`;
}

function confirmHtml() {
  const c = S.confirm;
  return `<div class="dlghead"><h2>${esc(c.title)}</h2>${c.running ? '' : closeBtn()}</div>
    <p class="dlgtext" style="font-size:14px">${c.text}</p>
    ${c.running ? `<p class="busy" role="status">${c.busy || t('Läuft … das kann einige Minuten dauern. Bitte dieses Fenster offen lassen.')}</p>`
      : `<div class="row" style="justify-content:flex-end;gap:8px"><button class="btn" data-act="dlg-close" ${c.danger ? 'autofocus' : ''}>${t('Abbrechen')}</button>${c.alt ? `<button class="btn" data-act="confirm-alt">${esc(c.alt)}</button>` : ''}<button class="btn ${c.danger ? 'danger' : 'primary'}" data-act="confirm-ok">${esc(c.ok)}</button></div>`}`;
}

function newProjectHtml() {
  const n = S.newp, o = n.opts;
  const title = n.add ? t('Datenbank zu «{name}» hinzufügen', { name: esc(n.target) })
    : n.target ? t('Daten in «{name}» importieren', { name: esc(n.target) }) : t('Neues Projekt');
  const j = n.job;
  if (j) {
    const running = j.state === 'läuft';
    return `<div class="dlghead"><h2>${title}</h2>${running ? '' : closeBtn()}</div>
      ${running ? `<p class="busy" role="status">${esc(j.phase)} <span class="num">${j.seconds} s</span></p>
        <p class="muted" style="font-size:13.5px">${['premise', 'premise-setup', 'exiobase'].includes(j.source)
          ? t('Das läuft in einem eigenen Prozess. Du kannst dieses Fenster schliessen und weiterarbeiten; die neuen Datenbanken erscheinen, wenn es fertig ist. premise braucht 15 bis 60 Minuten, EXIOBASE 10 bis 30.')
          : t('Bitte dieses Fenster offen lassen. Solange der Import läuft, wartet LCA Wrench mit allem anderen. ecoinvent braucht 10 bis 30 Minuten.')}</p>
        ${['premise', 'premise-setup', 'exiobase'].includes(j.source) ? `<div class="row" style="justify-content:flex-end"><button class="btn" data-act="dlg-close">${t('Im Hintergrund weiterlaufen lassen')}</button></div>` : ''}`
      : `<div class="warnbox" role="alert"><b>${t('Der Import ist fehlgeschlagen.')}</b><span>${esc(j.error)}</span></div>
        <p class="muted" style="font-size:13.5px">${t('Was der Import angelegt hatte, ist wieder entfernt. Die Datei lca-wrench.log im Ordner von LCA Wrench enthält die Einzelheiten.')}</p>
        <div class="row" style="justify-content:flex-end;gap:8px"><button class="btn" data-act="dlg-close">${t('Schliessen')}</button><button class="btn primary" data-act="np-back">${t('Zurück')}</button></div>`}`;
  }
  const src = (v, label, hint, ok = true) => `<label class="npsrc${ok ? '' : ' off'}"><input type="radio" name="nprjSrc" data-np="source" value="${v}" ${n.source === v ? 'checked' : ''} ${ok ? '' : 'disabled'}><span><b>${label}</b><span class="muted">${hint}</span></span></label>`;
  const ver = `<label class="f">${t('Version')}${n.versions ? `<select data-np="version">${n.versions.map(v => `<option ${v === n.version ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>`
    : `<input type="text" data-np="version" value="${esc(n.version)}" placeholder="3.10" style="width:90px">`}</label>`;
  const sm = `<label class="f">${t('Systemmodell')}<select data-np="system_model">${o.system_models.map(m => `<option value="${m}" ${m === n.system_model ? 'selected' : ''}>${m}</option>`).join('')}</select></label>`;
  let detail = '';
  if (n.source === 'ecoinvent-account') {
    detail = `<p class="muted" style="font-size:13.5px">${t('Mit dem eigenen Konto von ecoinvent.org, wie im Activity Browser. Benutzername und Passwort gehen nur an ecoinvent.')}${o.ecoinvent_login ? ' ' + t('Leer lassen, um die auf diesem Rechner gespeicherte Anmeldung von «{user}» zu nehmen.', { user: esc(o.ecoinvent_login) }) : ''}</p>
      <div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
        <label class="f">${t('Benutzername')}<input type="text" data-np="username" value="${esc(n.username)}" autocomplete="username"></label>
        <label class="f">${t('Passwort')}<input type="password" data-np="password" value="${esc(n.password)}" autocomplete="current-password"></label>
        <button class="btn small" type="button" data-act="np-login">${t('Anmelden und Versionen zeigen')}</button></div>
      <div class="row" style="gap:8px;align-items:flex-end">${ver}${sm}</div>
      <label class="row" style="gap:6px;font-size:13.5px"><input type="checkbox" data-np="remember" ${n.remember ? 'checked' : ''}> ${t('Anmeldung auf diesem Rechner speichern (wie der Activity Browser)')}</label>`;
  } else if (n.source === 'ecoinvent-files') {
    detail = `<p class="muted" style="font-size:13.5px">${t('Die Dateien, die du von ecoinvent.org heruntergeladen hast. Pfad einfügen: im Finder die Datei wählen und ⌥⌘C, unter Windows Shift + Rechtsklick → «Als Pfad kopieren».')}</p>
      <label class="f">${t('ecoSpold02-Datei (.7z) oder ausgepackter Ordner')}<input type="text" data-np="lci_path" data-np-guess="1" value="${esc(n.lci_path)}" placeholder="ecoinvent 3.10_cutoff_ecoSpold02.7z"></label>
      <label class="f">${t('LCIA-Datei für die Wirkungsmethoden (.7z oder .xlsx, freiwillig)')}<input type="text" data-np="lcia_path" value="${esc(n.lcia_path)}" placeholder="ecoinvent 3.10_LCIA_implementation.7z"></label>
      <div class="row" style="gap:8px;align-items:flex-end">${ver}${sm}</div>`;
  } else if (n.source === 'premise') {
    detail = premiseHtml(n, o);
  } else if (n.source === 'exiobase') {
    detail = exiobaseHtml(n, o);
  } else if (n.source === 'bafu2026') {
    detail = `<p class="muted" style="font-size:13.5px">${t('Die Ökoinventare der Bundesverwaltung (BAFU:2026, 11’947 Prozesse) mit den 25 Wirkungskategorien von EF 3.1, geladen mit sentier-brightway (ca. 36 MB von github.com, jede Datei mit Prüfsumme). Etwa eine Minute. Quelle: Ökoinventare der Bundesverwaltung, BAFU:2026.')}</p>`;
  }
  return `<div class="dlghead"><h2>${title}</h2>${closeBtn()}</div>
    <form id="nprjForm" style="display:flex;flex-direction:column;gap:12px">
      ${n.target ? '' : `<label class="f">${t('Name des Projekts')}<input type="text" id="nprjName" data-np="name" value="${esc(n.name)}" maxlength="100" required></label>`}
      <fieldset class="npsrcs"><legend class="eyebrow">${t('Inhalt')}</legend>
        ${n.target ? '' : src('empty', t('Leer'), t('Ein leeres Brightway-Projekt. Daten lassen sich später importieren.'))}
        ${src('bafu2026', t('BAFU 2026 mit EF 3.1'), t('Frei verfügbar, etwa eine Minute'), o.bafu2026)}
        ${src('ecoinvent-account', t('ecoinvent mit Konto'), t('Herunterladen mit deiner Anmeldung bei ecoinvent, 10 bis 30 Minuten'), o.ecoinvent)}
        ${src('ecoinvent-files', t('ecoinvent aus Dateien'), t('Von ecoinvent.org heruntergeladene Dateien, 10 bis 30 Minuten'), o.ecoinvent)}
        ${n.add ? src('premise', t('Zukunftsszenario mit premise'), t('ecoinvent des Projekts für ein Jahr und einen Klimapfad umgerechnet, 15 bis 60 Minuten'), true) : ''}
        ${n.add ? src('exiobase', t('EXIOBASE (Input-Output)'), t('Die Weltwirtschaft in 49 Regionen und 9800 Sektoren, in Euro, 10 bis 30 Minuten'), true) : ''}
      </fieldset>
      ${detail}
      <div class="row" style="justify-content:flex-end;gap:8px"><button class="btn" type="button" data-act="dlg-close">${t('Abbrechen')}</button>${n.source === 'premise' && !o.premise ? '' : `<button class="btn primary" type="submit">${n.source === 'empty' ? t('Anlegen') : n.source === 'premise' ? t('Szenarien rechnen') : t('Importieren')}</button>`}</div>
    </form>`;
}

// the pathway to start with: the current-policies one of SSP2 where there is one
function premisePathway(paths) {
  return ['SSP2-NPi', 'SSP2-M', 'SSP2-L'].find(p => paths.includes(p)) || paths[0] || '';
}

function premiseHtml(n, o) {
  const intro = `<p class="muted" style="font-size:13.5px">${t('premise rechnet eine ecoinvent-Datenbank des Projekts in die Zukunft um, entlang eines Szenarios eines integrierten Bewertungsmodells (IAM): Strommix und Kraftwerke, Stahl, Zement, Treibstoffe, Verkehr und mehr. Jedes Jahr wird eine eigene Datenbank; welche gerechnet wird, wählst du danach unter Start. Quelle: github.com/polca/premise.')}</p>`;
  if (!o.premise) {
    return `${intro}<div class="warnbox"><b>${t('premise ist noch nicht eingerichtet')}</b><span>${t('premise braucht ältere Versionen einiger Pakete als LCA Wrench und bekommt darum eine eigene Python-Umgebung neben der App (einmalig, etwa 1 GB, einige Minuten, aus dem Internet).')}</span></div>
      <div class="row"><button class="btn primary" type="button" data-act="np-premise-setup" ${o.premise_setup ? '' : 'disabled'}>${t('premise einrichten')}</button></div>`;
  }
  const c = o.premise, srcs = o.premise_sources || [];
  if (!srcs.length) return `${intro}<div class="warnbox"><b>${t('Kein ecoinvent im Projekt')}</b><span>${t('premise braucht eine ecoinvent-Datenbank (Version {v}, cut-off oder consequential) in diesem Projekt. Füge zuerst ecoinvent hinzu.', { v: esc((c.ei_versions || []).join(', ')) })}</span></div>`;
  const sel = (key, list, label, attrs = '') => `<label class="f">${label}<select data-np="${key}" ${attrs}>${list.map(v => `<option ${v === n[key] ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  const ok = srcs.filter(x => (c.ei_versions || []).includes(x.version));
  // only the pairs of model and pathway whose scenario file premise can get (null: archive not reachable, all of them)
  const av = o.premise_available;
  const models = av ? (c.models || []).filter(m => (av[m] || []).length) : (c.models || []);
  if (!models.includes(n.model)) n.model = models[0] || '';
  const paths = av ? (av[n.model] || []) : (c.pathways || []);
  if (!paths.includes(n.pathway)) n.pathway = premisePathway(paths);
  return `${intro}
    <div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
      <label class="f">${t('Ausgangsdaten')}<select data-np="source_db">${srcs.map(x => `<option value="${esc(x.name)}" ${x.name === n.source_db ? 'selected' : ''} ${(c.ei_versions || []).includes(x.version) ? '' : 'disabled'}>${esc(x.name)}</option>`).join('')}</select></label>
      ${sel('model', models, t('Modell (IAM)'), 'data-np-render="1"')}${sel('pathway', paths, t('Pfad'))}
      <label class="f">${t('Jahre')}<input type="text" data-np="years" value="${esc(n.years)}" placeholder="2030, 2050" style="width:120px"></label>
    </div>
    <p class="muted" style="font-size:12.5px">${av ? t('Angeboten sind die Pfade, deren Szenariodaten es für das gewählte Modell im Archiv von premise {v} gibt.', { v: esc(c.version || '') })
      : t('Das Archiv der Szenariodaten bei Zenodo war nicht erreichbar. Nicht jeden Pfad gibt es für jedes Modell.')}</p>
    ${ok.length < srcs.length ? `<p class="muted" style="font-size:12.5px">${t('premise {v} verarbeitet ecoinvent {list}.', { v: esc(c.version || ''), list: esc((c.ei_versions || []).join(', ')) })}</p>` : ''}
    <label class="f">${t('Schlüssel für die Szenariodaten')}<input type="password" data-np="key" value="${esc(n.key)}" autocomplete="off" placeholder="${o.premise_key ? t('gespeichert, leer lassen') : ''}"></label>
    <p class="muted" style="font-size:12.5px">${t('Die Szenariodaten von premise sind verschlüsselt. Den Schlüssel geben die Autoren von premise kostenlos ab (siehe github.com/polca/premise, «Get a key»). Er geht nur an premise auf diesem Rechner.')}</p>
    <label class="row" style="gap:6px;font-size:13.5px"><input type="checkbox" data-np="remember" ${n.remember ? 'checked' : ''}> ${t('Schlüssel auf diesem Rechner speichern')}</label>`;
}

function exiobaseHtml(n, o) {
  const local = n.exio_mode === 'file';
  return `<p class="muted" style="font-size:13.5px">${t('EXIOBASE 3 beschreibt die Weltwirtschaft als Input-Output-Tabelle: etwa 200 Produkte in 49 Regionen, in Millionen Euro, mit Emissionen und Ressourcen. Gerechnet allein, oder kombiniert mit Prozessdaten (hybride Ökobilanz): ein Modell kauft dann zum Beispiel Dienstleistungen in Euro aus EXIOBASE. Die Tabelle ist dicht und braucht beim Rechnen etwa 1 GB Arbeitsspeicher.')}</p>
    <div class="row" style="gap:14px;font-size:13.5px">
      <label class="row" style="gap:6px"><input type="radio" name="exioMode" data-np="exio_mode" data-np-render="1" value="download" ${local ? '' : 'checked'}> ${t('Herunterladen von Zenodo (0.6 bis 1 GB)')}</label>
      <label class="row" style="gap:6px"><input type="radio" name="exioMode" data-np="exio_mode" data-np-render="1" value="file" ${local ? 'checked' : ''}> ${t('Heruntergeladene Datei oder Ordner')}</label>
    </div>
    ${local ? `<label class="f">${t('Datei IOT_….zip oder ausgepackter Ordner')}<input type="text" data-np="path" value="${esc(n.path)}" placeholder="IOT_2022_pxp.zip"></label>`
      : `<div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
        <label class="f">${t('Version')}<select data-np="exio_version">${(o.exiobase_versions || []).map(v => `<option ${v === n.exio_version ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
        <label class="f">${t('Jahr')}<select data-np="exio_year">${(o.exiobase_years || []).slice().reverse().map(y => `<option ${String(y) === String(n.exio_year) ? 'selected' : ''}>${y}</option>`).join('')}</select></label>
        <label class="f">${t('Tabelle')}<select data-np="system"><option value="pxp" ${n.system === 'pxp' ? 'selected' : ''}>${t('Produkt × Produkt')}</option><option value="ixi" ${n.system === 'ixi' ? 'selected' : ''}>${t('Branche × Branche')}</option></select></label>
      </div>`}
    <div class="row" style="gap:8px;align-items:flex-end;flex-wrap:wrap">
      <label class="f">${t('Stoffflüsse verknüpfen mit')}<select data-np="biosphere">${(o.biospheres || []).map(b => `<option ${b === n.biosphere ? 'selected' : ''}>${esc(b)}</option>`).join('')}</select></label>
      <label class="f">${t('Name der Datenbank (freiwillig)')}<input type="text" data-np="db_name" value="${esc(n.db_name)}" placeholder="EXIOBASE 3.8.2 2022"></label>
    </div>
    <p class="muted" style="font-size:12.5px">${t('Emissionen werden nach Name und Kompartiment mit den Stoffflüssen verknüpft (am besten mit denen von ecoinvent). Zwei EXIOBASE-Flüsse (PFC und HFC, in CO2-Äquivalenten) zählen danach in allen Methoden in kg CO2-eq mit 1.')}</p>`;
}
