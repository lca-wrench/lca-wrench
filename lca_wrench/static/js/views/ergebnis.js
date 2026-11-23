// Ergebnis: one product in depth. Contributions, Sankey, tree, inventory, profile.
'use strict';
import { S, esc, nf, pct, U, explain, bars, methodInfo, methodLabel, familyLabel, mKey, api, topicNames, t } from '../core.js';
import { treeSvg, sankeySvg } from '../charts.js';
import { loadCw, tCw } from './crosswalk.js';

export const tabs = () => [['beitraege', t('Beiträge')], ['kategorien', t('Alle Kategorien')], ['sankey', t('Sankey')], ['lieferkette', t('Lieferkette')], ['inventar', t('Inventar')], ['profil', t('Umweltprofil')], ['warum', t('Warum anders?')], ['versionen', t('Versionen')], ['crosswalk', t('Andere Datenbank')]];

export async function loadErgebnis() {
  if (!S.fu) return;
  const base = { id: S.fu.id, amount: S.fu.amount, method: S.method };
  if (!S.calc || S.calc._key !== key()) { S.calc = await api('/api/calc', base); S.calc._key = key(); S.fuVerify = null; }
  if (S.tab === 'sankey' && (!S.sankey || S.sankey._key !== key() + S.skCut + S.skMax)) {
    S.sankey = await api('/api/sankey', { ...base, cutoff: S.skCut, max_nodes: S.skMax }); S.sankey._key = key() + S.skCut + S.skMax;
  }
  if (S.tab === 'lieferkette' && (!S.graph || S.graph._key !== key() + S.cutoff + S.depth)) {
    S.graph = await api('/api/graph', { ...base, cutoff: S.cutoff, depth: S.depth }); S.graph._key = key() + S.cutoff + S.depth;
  }
  if (S.tab === 'warum' && (!S.why || S.why._key !== key())) { S.why = await api('/api/why', base); S.why._key = key(); }
  if (S.tab === 'kategorien') await loadCats();
  if (S.tab === 'versionen') await loadTargets();
  if (S.tab === 'crosswalk') await loadCw();
  if (S.tab === 'inventar' && (!S.inv || S.inv._key !== key())) {
    S.inv = await api('/api/inventory', { ...base }); S.inv._key = key();
  }
}
// product i of the last calculation; method j of it, else the current method if the calculation has it, else its first
export function fuFromSetup(i, j) {
  const res = S.setupRes, f = res.fus[i];
  if (j !== undefined) S.method = res.methods[j].id;
  else if (!res.methods.some(m => mKey(m.id) === mKey(S.method))) S.method = res.methods[0].id;
  S.fu = { id: f.id, amount: f.amount, name: f.name, location: f.location, unit: f.unit, database: f.database };
  resetErgebnis();
}
export const setupIndex = () => S.setupRes ? S.setupRes.fus.findIndex(f => String(f.id) === String(S.fu.id) && f.amount === S.fu.amount) : -1;

// all categories: family A (default: the family of the current method) and optionally B, side by side
export const families = () => [...new Set(S.st.methods.map(m => m.family))].sort((a, b) => a === 'Werkbank' ? -1 : b === 'Werkbank' ? 1 : a.localeCompare(b));
export async function loadCats() {
  const c = S.cats, fams = families();
  if (c.a !== '*' && !fams.includes(c.a)) c.a = methodInfo().family || fams[0];
  if (c.b && !fams.includes(c.b)) c.b = '';
  if (c.a !== '*' && c.topic && !S.st.methods.some(m => (m.family === c.a || m.family === c.b) && m.topic === c.topic)) c.topic = '';
  if (c.a === '*') { c.b = ''; if (!c.topic) c.topic = methodInfo().topic && methodInfo().topic !== 'other' ? methodInfo().topic : 'climate'; }
  const k = key() + c.a + '|' + c.b + '|' + (c.topic || '');
  if (!c.res || c.res._key !== k) {
    c.res = await api('/api/categories', { id: S.fu.id, amount: S.fu.amount, families: c.a === '*' ? ['*'] : [c.a, c.b].filter(Boolean), topic: c.topic || null }); c.res._key = k;
  }
}

const key = () => JSON.stringify([S.fu.id, S.fu.amount, S.method, S.st.journal.length, S.st.changes.length, S.st.completion?.enabled, S.st.flowmap?.enabled, S.st.regional?.enabled]);
export function resetErgebnis() { S.cats.res = null; S.calc = S.sankey = S.graph = S.inv = S.why = null; S.gsel = S.sksel = null; S.fuVerify = null; S.ver = { ...S.ver, res: null, detail: null, k: null, error: null }; S.cw = { ...S.cw, res: null, error: null, open: null, hits: null, trace: {} }; }

// what the method does not assess: inventory flows without a factor, and the switch for completed factors
function factorNotice(r) {
  const f = r.factors;
  const sw = f.completable ? `<label class="row" style="gap:6px;font-size:13.5px" title="${t('Die Methode hat für manche Stoffe nur einen Faktor auf dem Fluss ohne Subkompartiment. Ein Fluss ohne Faktor bekommt dann den Faktor des gleichnamigen Flusses ohne Subkompartiment im selben Kompartiment. Eigene Faktoren der Methode (auch 0) bleiben, Langzeit-Emissionen werden nie ergänzt. Gilt für alle Rechnungen.')}"><input type="checkbox" id="complChk" ${f.completion ? 'checked' : ''}> ${t('Fehlende Faktoren für Subkompartimente ergänzen ({n} in dieser Methode)', { n: nf(f.completable) })}</label>` : '';
  const g = r.regional || {};
  let rsw = g.available ? `<label class="row" style="gap:6px;font-size:13.5px" title="${t('Die Methode hat Faktoren, die vom Ort abhängen (Zeilen mit Ort oder Länderkopien von Flüssen). Ein Prozess bekommt den Faktor seines Orts, ein Teil eines Landes den des Landes, eine Region das Mittel ihrer Länder (nach Produktionsmenge der gleichen Datensätze dort, sonst gleich gewichtet). GLO, RoW und unbekannte Orte behalten den normalen Faktor. Gilt für alle Rechnungen.')}"><input type="checkbox" id="regChk" ${g.enabled ? 'checked' : ''}> ${t('Faktoren nach Ort anwenden ({k} Ort(e) in dieser Methode)', { k: nf(g.locations) })}</label>` : '';
  rsw += regFiles(g);
  if (!f.uncharacterized && !sw && !rsw) return '';
  // loud only where it matters: the namesakes would add more than 0.1 % of the result. Most flows of an inventory
  // have no factor in any one method (a climate method assesses a few dozen of some thousand), which is normal.
  const loud = f.namesakes > 0 && Math.abs(f.estimate) > 1e-3 * Math.abs(r.score || 0);
  const est = loud ? ' ' + t('Würden sie gleich bewertet, kämen etwa {v} {u} dazu (Schätzung).', { v: nf(f.estimate), u: esc(r.method_unit) }) : '';
  const txt = !f.uncharacterized ? ''
    : loud ? `<b>${t('{k} von {n} Flüssen haben keinen Faktor; {s} tragen denselben Namen wie ein bewerteter Fluss.', { k: nf(f.uncharacterized), n: nf(f.flows), s: nf(f.namesakes) })}</b>${est}`
      : t('{k} von {n} Flüssen des Inventars haben in dieser Methode keinen Faktor.', { k: nf(f.uncharacterized), n: nf(f.flows) });
  const link = f.uncharacterized ? ` <button class="linkbtn" data-act="inv-filter" data-k="none">${t('Liste zeigen')}</button>` : '';
  return `<div id="factorNotice" class="${loud ? 'warnbox' : 'row muted'}" style="${loud ? 'flex-direction:column;gap:6px' : 'font-size:13.5px;justify-content:space-between'}"><span>${txt}${link}</span>${sw}${rsw}</div>`;
}

// the JRC's EF 3.1 workbook with factors by country: which loaded file this method uses, else a button to load one
function regFiles(g) {
  const used = g.files || [], loaded = g.loaded_files || [];
  if (used.length) {
    return used.map(x => `<span class="row" style="gap:6px;font-size:13px">${t('Länderfaktoren aus «{file}», geladen am {date}', { file: esc(x.file), date: esc(x.loaded) })}<button class="linkbtn" data-act="reg-unload" data-k="${esc(x.id)}">${t('entfernen')}</button></span>`).join('');
  }
  if (!g.loadable) return '';
  const tip = t('Die JRC veröffentlicht die Faktoren von EF 3.1 als Excel-Datei («EF-LCIAMethod_CF», im EF reference package 3.1). LCA Wrench liest daraus die Faktoren nach Land für Wassernutzung, Landnutzung, Versauerung und terrestrische Eutrophierung und behält sie auf diesem Computer. Sie gelten in allen Projekten für die EF-3.1-Methoden auf der EF-Flussliste und über die Flusszuordnung für die von ecoinvent. Lesen dauert etwa eine halbe Minute.');
  if (loaded.length) {
    return `<span class="muted" style="font-size:13px">${t('Die geladenen Länderfaktoren ({files}) passen nicht zu dieser Methode: Sie gelten für Methoden, deren Faktoren den Standardfaktoren der Datei entsprechen.', { files: esc(loaded.map(x => x.file).join(', ')) })} ${loaded.map(x => `<button class="linkbtn" data-act="reg-unload" data-k="${esc(x.id)}">${t('«{file}» entfernen', { file: esc(x.file) })}</button>`).join(' ')}</span>`;
  }
  return `<label class="btn small" style="cursor:pointer" title="${tip}">${t('Länderfaktoren aus der EF-3.1-Datei laden …')}<input type="file" id="regFile" accept=".xlsx" hidden></label>`;
}

// impact by the location of the processes that cause it; with factors by location, what they change and how found
function locTable(r) {
  const rows = r.by_location || [], g = r.regional || {}, u = esc(r.method_unit);
  const withReg = g.available && g.enabled;
  const max = Math.max(...rows.map(x => Math.abs(x.value)), 1e-300);
  const sign = v => v > 0 ? '+' : v < 0 ? '−' : '';
  const num = v => Math.abs(v) >= 1e-4 || !v ? nf(v) : v.toExponential(2).replace('e', ' e');  // tiny changes readable
  const weighting = { volume: t('nach Produktionsmenge'), equal: t('gleich gewichtet'), mixed: t('nach Produktionsmenge oder gleich gewichtet') };
  const how = x => x.how === 'own' ? t('Faktor des Orts') : x.how === 'country' ? t('Faktor des Landes')
    : x.how === 'region' ? t('Mittel der Länder, {w}', { w: weighting[x.weighting] || weighting.equal })
      : x.kind === 'rest' || x.kind === 'global' ? t('normaler Faktor (Weltmittel)') : t('normaler Faktor');
  if (!rows.length) return `<p class="empty">${t('Kein Prozess trägt direkt zum Ergebnis bei.')}</p>`;
  return `<div class="tblwrap"><table class="tbl" id="locTbl"><thead><tr><th>${t('Ort')}</th><th style="text-align:right">${t('Wirkung')} (${u})</th><th>${t('Anteil')}</th>
    ${withReg ? `<th style="text-align:right" title="${t('Was die Faktoren nach Ort an diesem Ort gegenüber den normalen Faktoren ändern.')}">${t('davon Faktoren nach Ort')}</th><th>${t('Faktor')}</th>` : ''}<th style="text-align:right">${t('Anzahl Prozesse')}</th></tr></thead><tbody>
    ${rows.map(x => `<tr><td><b>${esc(x.location || '–')}</b>${x.name ? ` <span class="muted">${esc(x.name)}</span>` : ''}</td>
      <td class="num nw" style="text-align:right">${nf(x.value)}</td>
      <td style="width:22%"><div class="share"><div class="t"><i class="${x.value < 0 ? 'neg' : r.score && x.value / r.score >= 0.25 ? 'hot' : ''}" style="width:${Math.abs(x.value) / max * 100}%"></i></div><span>${pct(r.score ? x.value / r.score : 0)}</span></div></td>
      ${withReg ? `<td class="num nw" style="text-align:right">${x.regional ? sign(x.regional) + num(Math.abs(x.regional)) : ''}</td><td class="muted" style="font-size:13px">${how(x)}</td>` : ''}
      <td class="num" style="text-align:right">${nf(x.processes)}</td></tr>`).join('')}
  </tbody></table></div>`;
}

const busy = () => `<p class="busy">${t('Rechne …')}</p>`;

function needFu() {
  return `<section class="card" style="display:flex;flex-direction:column;gap:10px"><h2>${t('Noch nichts ausgewählt')}</h2><p class="muted">${t('Öffne einen Prozess im Datenblatt und klick auf «Ergebnis», oder öffne eine Zahl aus einer Rechnung.')}</p><div class="row"><button class="btn primary" data-act="view" data-k="daten">${t('Zu den Daten')}</button>${S.st.examples[0] ? `<button class="btn" data-act="calc-node" data-k="${S.st.examples[0].id}">${t('Beispiel: {name}', { name: esc(S.st.examples[0].name) })}</button>` : ''}</div></section>`;
}

export function vErgebnis() {
  if (!S.fu) return needFu();
  const r = S.calc;
  const v = S.fuVerify;
  const check = v === 'running' ? `<span class="busy">${t('Gegenprobe läuft …')}</span>`
    : v ? `<span class="check ${v.ok ? '' : 'bad'}" title="${t('Mit bw2calc nachgerechnet, relative Abweichung {d}', { d: v.max_rel.toExponential(1) })}">${v.ok ? t('Gegenprobe mit bw2calc stimmt') : t('Gegenprobe weicht ab')}</span>`
      : `<button class="btn small" data-act="verify-fu">${t('Gegenprobe mit bw2calc')}</button>`;
  const head = `<section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="align-items:flex-end">
      <div style="flex:1 1 300px;min-width:0"><span class="eyebrow">${t('Ergebnis für')}</span><h2>${esc(S.fu.name)} <span class="muted" style="font-size:15px">${esc(S.fu.location || '')}</span></h2></div>
      <label class="f">${t('Menge')}<input type="number" id="fuAmt" step="any" min="0" value="${S.fu.amount}"></label><span class="muted" style="padding-bottom:7px">${esc(S.fu.unit)}</span>
    </div>
    ${r ? `<div class="row" style="justify-content:space-between;align-items:flex-end">
      <div><span class="eyebrow">${esc(methodLabel(methodInfo()))}</span><div class="kpi"><span class="big">${nf(r.score)}</span><span class="u">${esc(r.method_unit)}</span></div></div>
      <div class="row">${check}<span class="chip" title="${t('Zeit für Rechnung und Auswertung')}">${t('{ms} ms · {n} Produkte', { ms: nf(r.seconds * 1000), n: nf(r.matrix_size) })}</span>${r.factors.completed ? `<button class="chip acc" id="complChip" data-act="inv-filter" data-k="completed" title="${t('{n} Flüsse dieses Inventars haben keinen eigenen Faktor in der Methode und rechnen mit dem Faktor des gleichnamigen Flusses ohne Subkompartiment. Das sind {v} {u} des Ergebnisses. Klick zeigt die Liste.', { n: nf(r.factors.completed), v: nf(r.factors.completed_value), u: esc(r.method_unit) })}">${t('mit {n} ergänzten Faktoren', { n: nf(r.factors.completed) })}</button>` : ''}${r.regional?.enabled && r.regional.processes ? `<button class="chip acc" id="regChip" data-act="contrib-loc" title="${t('{n} Prozesse rechnen mit dem Faktor ihres Orts statt dem normalen Faktor. Das ändert das Ergebnis um {v} {u}. Klick zeigt das Ergebnis nach Ort.', { n: nf(r.regional.processes), v: (r.regional.effect > 0 ? '+' : '') + nf(r.regional.effect), u: esc(r.method_unit) })}">${t('mit Faktoren nach Ort')}</button>` : ''}${r.model ? `<span class="chip acc">${t('eigenes Modell, live')}</span>` : ''}${r.counterpart ? `<span class="chip hot" title="${esc(r.counterpart.name)} · ${esc(r.counterpart.location || '')}">${t('gerechnet als {db}', { db: esc(r.counterpart.database) })}</span>` : ''}${S.st.background && S.st.background.options.length > 1 ? `<span class="chip" title="${t('Hintergrunddaten dieser Rechnung (unter Start wählen)')}">${esc(r.background.join(' + '))}</span>` : ''}</div>
    </div>${factorNotice(r)}` : busy()}
    ${setupIndex() >= 0 && S.setupRes.fus.length > 1 ? `<label class="f">${t('Produkt aus der Rechnung «{name}»', { name: esc(S.setup?.name || '') })}<select id="fuSetup">${S.setupRes.fus.map((f, i) => `<option value="${i}" ${i === setupIndex() ? 'selected' : ''}>${esc(f.name)} ${esc(f.location || '')} · ${nf(f.amount)} ${esc(f.unit || '')}</option>`).join('')}</select></label>` : ''}
    <div class="row"><button class="btn small" data-act="add-setup" data-k="${S.fu.id}">${t('Zur Rechnung')}</button><button class="btn small" data-act="add-cmp-fu">${t('Zum Vergleich')}</button><button class="btn small" data-act="open" data-k="${S.fu.id}" data-db="${esc(S.fu.database || '')}">${t('Datenblatt')}</button>
      <span class="row" style="margin-left:auto;gap:6px"><span class="muted" style="font-size:13px">${t('Exportieren')}</span><button class="btn small" data-act="export-result" data-k="xlsx" title="${t('Ergebnis, Beiträge, alle Kategorien und Inventar als Excel-Datei')}">Excel</button><button class="btn small" data-act="export-result" data-k="csv" title="${t('Dasselbe als eine CSV-Tabelle')}">CSV</button></span></div>
  </section>
  <nav class="tabs" role="tablist" aria-label="${t('Auswertungen')}">${tabs().filter(([k]) => (k !== 'profil' || S.st.profile_family) && (k !== 'warum' || (S.st.is_copy && S.st.changes.length)) && (k !== 'versionen' || !r?.model)).map(([k, l]) => `<button role="tab" aria-selected="${S.tab === k}" data-act="tab" data-k="${k}">${l}</button>`).join('')}</nav>`;
  if (!r) return head;
  return head + ({ beitraege: tBeitraege, kategorien: tKategorien, sankey: tSankey, lieferkette: tTree, inventar: tInventar, profil: tProfil, warum: tWarum, versionen: tVersionen, crosswalk: tCw })[S.tab]();
}

function tBeitraege() {
  const r = S.calc, mode = S.contrib;
  return `${explain(t('<b>Wo</b> entsteht die Wirkung? Nach Prozess: direkte Emissionen jedes Prozesses in der ganzen Lieferkette. Nach Stoff: welche Emissionen oder Ressourcen dahinterstecken. Nach Ort: an welchen Orten die Prozesse liegen, die ausstossen oder Ressourcen nutzen. Klick auf einen Prozess öffnet sein Datenblatt.'))}
  <section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="justify-content:space-between"><h3>${t('Wo entsteht die Wirkung?')}</h3>
      <div class="seg" role="group" aria-label="${t('Beiträge nach')}"><button data-act="contrib" data-k="act" aria-pressed="${mode === 'act'}">${t('nach Prozess')}</button><button data-act="contrib" data-k="flow" aria-pressed="${mode === 'flow'}">${t('nach Stoff')}</button><button data-act="contrib" data-k="loc" aria-pressed="${mode === 'loc'}">${t('nach Ort')}</button></div></div>
    ${mode === 'loc' ? locTable(r) : `<div class="bars">${mode === 'act' ? bars(r.by_activity, r.by_activity_rest, r.score, 'open') : bars(r.by_flow, r.by_flow_rest, r.score, null)}</div>`}
  </section>`;
}

function tKategorien() {
  const c = S.cats, fams = families(), all = c.a === '*', names = topicNames();
  const opt = (sel, none) => (none ? `<option value="">${t('— keine —')}</option>` : '') + fams.map(f => `<option value="${esc(f)}" ${f === sel ? 'selected' : ''}>${esc(familyLabel(f))}</option>`).join('');
  // the impact categories the chosen methods have (all methods: every one in the project)
  const inFam = S.st.methods.filter(m => all || m.family === c.a || m.family === c.b);
  const topics = Object.keys(names).filter(k => inFam.some(m => m.topic === k));
  const controls = `${explain(t('Alle Wirkungskategorien einer Methode auf einen Blick, auf Wunsch eine zweite Methode daneben (z.B. EF 3.1 und ökologische Knappheit). Mit «Alle Methoden» und einer Wirkungskategorie (z.B. Klimawandel oder Toxizität) stehen die Ergebnisse aller Methoden für diese Kategorie untereinander. Balken vergleichen nur Werte mit derselben Einheit. Klick auf eine Kategorie zeigt ihre Beiträge.'))}
  <section class="card row" style="justify-content:space-between">
    <span class="muted" style="font-size:13.5px">${c.res ? t('{n} Kategorien', { n: c.res.families.reduce((a, f) => a + f.rows.length, 0) }) : ''}</span>
    <div class="row"><label class="f">${t('Methode')}<select id="catA"><option value="*" ${all ? 'selected' : ''}>${t('Alle Methoden')}</option>${opt(c.a)}</select></label>
      ${all ? '' : `<label class="f">${t('Daneben')}<select id="catB">${opt(c.b, true)}</select></label>`}
      <label class="f">${t('Wirkungskategorie')}<select id="catTopic">${all ? '' : `<option value="">${t('Alle Kategorien')}</option>`}${topics.map(k => `<option value="${k}" ${k === c.topic ? 'selected' : ''}>${esc(names[k])}</option>`).join('')}</select></label></div></section>`;
  if (!c.res) return controls + busy();
  const cur = mKey(S.method);
  // bars compare values with the same unit only
  const rowsOf = list => {
    const max = {}, n = {}, u = r => (r.unit || '').toLowerCase();
    list.forEach(r => { max[u(r)] = Math.max(max[u(r)] || 1e-300, Math.abs(r.value)); n[u(r)] = (n[u(r)] || 0) + 1; });
    const bars = Object.values(n).some(x => x > 1);
    return { bars, html: (r, fi, i, fam) => `<tr ${mKey(r.method) === cur ? 'class="sel"' : ''}>${fam !== undefined ? `<td class="muted">${esc(familyLabel(fam))}</td>` : ''}<td><button class="linkbtn" data-act="cat-open" data-k="${fi}:${i}" title="${t('Beiträge zu dieser Kategorie zeigen')}">${esc(methodLabel(methodInfo(r.method)))}</button></td>
      <td class="num nw">${nf(r.value)}</td><td class="muted nw">${esc(r.unit)}</td>${bars ? `<td style="width:24%">${n[u(r)] > 1 ? `<span class="minibar"><i class="${r.value < 0 ? 'neg' : ''}" style="width:${Math.abs(r.value) / max[u(r)] * 100}%"></i></span>` : ''}</td>` : ''}</tr>` };
  };
  const head = (withFam, bars) => `<thead><tr>${withFam ? `<th>${t('Methode')}</th>` : ''}<th>${t('Kategorie')}</th><th>${t('Wert')}</th><th>${t('Einheit')}</th>${bars ? '<th></th>' : ''}</tr></thead>`;
  if (all) {  // one table: every method's categories of this kind
    const flat = c.res.families.flatMap((f, fi) => f.rows.map((r, i) => ({ r, fi, i, fam: f.family })));
    if (!flat.length) return controls + `<p class="empty">${t('Keine Methode hat diese Kategorie.')}</p>`;
    const R = rowsOf(flat.map(x => x.r));
    return `${controls}<section class="card" style="display:flex;flex-direction:column;gap:10px;min-width:0"><h3>${esc(names[c.topic] || '')} · ${t('{n} Methoden', { n: c.res.families.length })}</h3>
      <div class="tblwrap"><table class="tbl">${head(true, R.bars)}<tbody>${flat.map(x => R.html(x.r, x.fi, x.i, x.fam)).join('')}</tbody></table></div></section>`;
  }
  const card = (f, fi) => {
    const R = rowsOf(f.rows);
    return `<section class="card" style="display:flex;flex-direction:column;gap:10px;min-width:0"><h3>${esc(familyLabel(f.family))}</h3>
      ${f.rows.length ? `<div class="tblwrap"><table class="tbl">${head(false, R.bars)}<tbody>${f.rows.map((r, i) => R.html(r, fi, i)).join('')}</tbody></table></div>` : `<p class="muted">${t('Keine Kategorie dieser Art.')}</p>`}</section>`;
  };
  return `${controls}<div class="catgrid ${c.res.families.length > 1 ? 'two' : ''}">${c.res.families.map(card).join('')}</div>`;
}

function tSankey() {
  const sk = S.sankey;
  const own = S.skMode === 'own';
  const covered = sk && sk.total ? sk.nodes.reduce((a, n) => a + n.direct, 0) / sk.total : null;
  const controls = `${explain(own
    ? t('Jeder Prozess erscheint <b>einmal</b>. Die Höhe eines Balkens zeigt nur, was der Prozess <b>selbst</b> ausstösst, ohne seine Lieferkette. Über alle Prozesse zusammen ergibt das genau das Gesamtergebnis. Die dünnen Linien zeigen, wer wen beliefert. Orange: mehr als 25 %. Gutschriften erscheinen in Blau.')
    : t('Jeder Prozess erscheint <b>einmal</b>. Rechts steht dein Produkt, nach links geht es in die Lieferkette. Die Breite eines Bandes zeigt, wie viel Wirkung über diese Lieferbeziehung ins Produkt fliesst, die Höhe eines Balkens die gesamte Wirkung, die ein Prozess beisteuert. Orange: mehr als 25 %. Gutschriften erscheinen in Blau.'))}
  <section class="card row" style="justify-content:space-between">
    <span class="muted" style="font-size:13.5px">${sk ? t('{n} Prozesse, {m} Verbindungen', { n: sk.nodes.length, m: sk.links.length }) + (own && covered !== null ? ' · ' + t('Eigene Beiträge der gezeigten Prozesse: {p} des Ergebnisses', { p: pct(covered) }) : '') : ''}</span>
    <div class="row">
      <label class="f">${t('Balken zeigen')}<select id="skMode"><option value="cum" ${own ? '' : 'selected'}>${t('Summe bis hierher (mit Lieferkette)')}</option><option value="own" ${own ? 'selected' : ''}>${t('Eigener Beitrag (nur direkt)')}</option></select></label>
      <label class="f">${t('Ausblenden unter')}<select id="skCut">${[0.005, 0.01, 0.02, 0.05, 0.1].map(c => `<option value="${c}" ${c === S.skCut ? 'selected' : ''}>${pct(c)}</option>`).join('')}</select></label>
      <label class="f">${t('Höchstens')}<select id="skMax">${[15, 25, 40, 60, 90].map(c => `<option value="${c}" ${c === S.skMax ? 'selected' : ''}>${t('{n} Prozesse', { n: c })}</option>`).join('')}</select></label>
    </div></section>`;
  if (!sk) return controls + busy();
  const { svg, loops } = sankeySvg(sk, S.skMode);
  const sel = S.sksel !== null ? sk.nodes.find(n => n.key === S.sksel) : null;
  const panel = sel ? `<section class="card" style="display:flex;flex-direction:column;gap:8px"><span class="eyebrow">${t('Ausgewählt')}</span><h3>${esc(sel.name)} <span class="muted">${esc(sel.location)}</span></h3>
    <p style="font-size:14px">${t('In diesem Produktsystem gebraucht: <b class="num">{amount}</b>. Wirkung inklusive Lieferkette: <b class="num">{value}</b> ({share}), davon direkt: {direct}.', { amount: `${nf(sel.amount)} ${esc(sel.unit)}`, value: `${nf(sel.value)} ${esc(U())}`, share: pct(sel.value / sk.total), direct: `${nf(sel.direct)} ${esc(U())}` })}</p>
    <div class="row"><button class="btn" data-act="open" data-k="${sel.id}" data-db="${esc(sel.database || '')}">${t('Datenblatt')}</button><button class="btn" data-act="calc-node" data-k="${sel.id}">${t('Als neues Ergebnis')}</button></div></section>`
    : `<p class="muted" style="font-size:14px">${t('Klick auf einen Balken, um Details zu sehen.')}</p>`;
  return `${controls}<section class="card" style="padding:10px"><div class="gwrap sankey">${svg}</div>${loops ? `<p class="muted" style="font-size:12.5px;padding:6px 8px 0">${t('{n} Rückkopplung(en) in der Lieferkette sind nicht gezeichnet.', { n: loops })}</p>` : ''}</section>${panel}`;
}

function tTree() {
  const g = S.graph;
  const controls = `${explain(t('Links steht dein Produkt, nach rechts geht es tiefer in die Lieferkette. Hier ist jeder Weg ein eigener Ast, darum kann derselbe Prozess mehrmals vorkommen. Die <b>Liniendicke</b> zeigt den Anteil an der Wirkung.'))}
  <section class="card row" style="justify-content:space-between">
    <span class="muted num" style="font-size:13.5px">${g ? t('{v} gesamt', { v: `${nf(g.total)} ${esc(U())}` }) : ''}</span>
    <div class="row">
      <label class="f">${t('Ausblenden unter')}<select id="cutSel">${[0.005, 0.01, 0.02, 0.05, 0.1].map(c => `<option value="${c}" ${c === S.cutoff ? 'selected' : ''}>${pct(c)}</option>`).join('')}</select></label>
      <label class="f">${t('Tiefe')}<select id="depSel">${[2, 3, 4, 5, 6].map(c => `<option value="${c}" ${c === S.depth ? 'selected' : ''}>${t('{n} Stufen', { n: c })}</option>`).join('')}</select></label>
    </div></section>`;
  if (!g) return controls + busy();
  const sn = S.gsel !== null ? g.nodes[S.gsel] : null;
  const panel = sn ? `<section class="card" style="display:flex;flex-direction:column;gap:8px"><span class="eyebrow">${t('Ausgewählt')}</span><h3>${esc(sn.name)} <span class="muted">${esc(sn.location)}</span></h3>
    <p style="font-size:14px">${t('Auf diesem Ast braucht es <b class="num">{amount}</b> davon. Wirkung inklusive allem dahinter: <b class="num">{impact}</b> ({share}). Direkt in diesem Prozess: {direct}.', { amount: `${nf(sn.amount)} ${esc(sn.unit)}`, impact: `${nf(sn.impact)} ${esc(U())}`, share: pct(sn.share), direct: `${nf(sn.direct)} ${esc(U())}` })}</p>
    <div class="row"><button class="btn" data-act="open" data-k="${sn.id}" data-db="${esc(sn.database || '')}">${t('Datenblatt')}</button><button class="btn" data-act="calc-node" data-k="${sn.id}">${t('Als neues Ergebnis')}</button></div></section>`
    : `<p class="muted" style="font-size:14px">${t('Klick auf einen Kasten, um Details zu sehen.')}</p>`;
  return `${controls}<section class="card" style="padding:10px"><div class="gwrap">${treeSvg(g)}</div></section>${panel}`;
}

const cfLabel = () => ({ own: t('bewertet'), mapped: t('bewertet (Flusszuordnung)'), completed: t('bewertet (ergänzt)'), none: t('nicht bewertet') });
export function invRows() {
  const q = S.invQ.trim().toLowerCase(), f = S.invF;
  let rows = (S.inv || []).filter(r => (!q || (r.name + ' ' + r.categories).toLowerCase().includes(q)) && (!f || r.status === f));
  // flows without a factor: first those whose name has a factor in another sub-compartment, by the size of the estimate
  if (f === 'none') rows = [...rows].sort((a, b) => Math.abs(b.estimate || 0) - Math.abs(a.estimate || 0) || ('estimate' in b) - ('estimate' in a));
  if (f === 'completed') rows = [...rows].sort((a, b) => Math.abs(b.amount * b.factor) - Math.abs(a.amount * a.factor));
  return rows;
}
function tInventar() {
  const inv = S.inv;
  if (!inv) return busy();
  const rows = invRows(), u = esc(S.calc.method_unit), lab = cfLabel(), f = S.invF;
  const shown = rows.slice(0, 400);
  const sci = v => v.toExponential(3).replace('e', ' e');
  const n = k => inv.filter(r => r.status === k).length;
  const extraHead = f === 'none' ? `<th>${t('Gleichnamiger Fluss mit Faktor')}</th><th style="text-align:right" title="${t('Menge mal Faktor des gleichnamigen Flusses. Eine Schätzung, kein Ergebnis: die Methode bewertet diesen Fluss nicht.')}">${t('Schätzung')} (${u})</th>`
    : f === 'completed' ? `<th style="text-align:right">${t('Faktor')}</th><th>${t('Übernommen von')}</th><th style="text-align:right">${t('Beitrag')} (${u})</th>` : '';
  const extra = r => f === 'none' ? `<td class="muted">${r.namesake ? esc(r.namesake.categories) + ' · ' + nf(r.namesake.factor) : ''}</td><td class="num nw" style="text-align:right">${'estimate' in r ? '≈ ' + sci(r.estimate) : ''}</td>`
    : f === 'completed' ? `<td class="num nw" style="text-align:right">${nf(r.factor)}</td><td class="muted">${esc(r.source)}</td><td class="num nw" style="text-align:right">${sci(r.amount * r.factor)}</td>` : '';
  return `${explain(t('Das <b>Sachbilanz-Inventar</b>: alle Stoffe, die über die ganze Lieferkette in die Umwelt gehen oder ihr entnommen werden, für die gewählte Menge. Die Spalte «Methode» zeigt, ob die gewählte Wirkungsmethode den Fluss bewertet: so sieht man, was in den Daten steht, aber nicht ins Ergebnis eingeht.'))}
  <section class="card" style="display:flex;flex-direction:column;gap:10px">
    <div class="row" style="justify-content:space-between"><h3>${t('Inventar · {n} Stoffflüsse', { n: nf(inv.length) })}</h3>
      <div class="row"><select id="invF" aria-label="${t('Nach Bewertung filtern')}"><option value="">${t('alle Flüsse')}</option><option value="none" ${f === 'none' ? 'selected' : ''}>${t('nur nicht bewertete ({n})', { n: nf(n('none')) })}</option>${n('completed') ? `<option value="completed" ${f === 'completed' ? 'selected' : ''}>${t('nur ergänzte ({n})', { n: nf(n('completed')) })}</option>` : ''}</select>
        <input type="search" id="invQ" placeholder="${t('Filtern, z.B. carbon dioxide')}" value="${esc(S.invQ)}" aria-label="${t('Inventar filtern')}"><button class="btn small" data-act="csv-inv">${t('Als CSV')}</button>${S.calc.factors.completable ? `<button class="btn small" data-act="csv-completed" title="${t('Alle Faktoren, die die Ergänzung dieser Methode gibt: Fluss, Kompartiment, Faktor, Herkunft')}">${t('Ergänzte Faktoren als CSV')}</button>` : ''}${S.calc.regional?.available ? `<button class="btn small" data-act="csv-regional" title="${t('Alle Faktoren nach Ort dieser Methode: Fluss, Ort, Faktor, normaler Faktor, Herkunft')}">${t('Faktoren nach Ort als CSV')}</button>` : ''}</div></div>
    ${f === 'none' ? `<p class="muted" style="font-size:13px">${t('Zuoberst die Flüsse, deren Name in einem anderen Subkompartiment desselben Kompartiments einen Faktor hat. Die Schätzung ist Menge mal dieser Faktor: ein Hinweis, wo die Methode eine Lücke haben könnte, kein Ergebnis.')}</p>` : ''}
    <div class="tblwrap"><table class="tbl" id="invTbl"><thead><tr><th>${t('Stoff')}</th><th>${t('Kompartiment')}</th><th style="text-align:right">${t('Menge')}</th><th>${t('Einheit')}</th><th>${t('Methode')}</th>${extraHead}</tr></thead><tbody>
      ${shown.map(r => `<tr data-status="${r.status}"><td>${esc(r.name)}</td><td class="muted">${esc(r.categories)}</td><td class="num nw" style="text-align:right">${sci(r.amount)}</td><td class="muted">${esc(r.unit)}</td><td><span class="chip ${r.status === 'none' ? ('estimate' in r ? 'hot' : '') : r.status === 'own' ? '' : 'acc'}">${lab[r.status]}</span></td>${extra(r)}</tr>`).join('')}
    </tbody></table></div>
    ${rows.length > shown.length ? `<p class="muted" style="font-size:13px">${t('{n} weitere. Filtere oder lade die CSV herunter.', { n: nf(rows.length - shown.length) })}</p>` : ''}
  </section>`;
}

function tProfil() {
  const r = S.calc;
  const prof = r.profile.filter(p => Math.abs(p.value) > 1e-12);
  const pTot = prof.reduce((a, p) => a + p.value, 0);
  return `${explain(t('Das Umweltprofil nach der Schweizer Methode der ökologischen Knappheit 2021: Alle Umweltbelastungen werden in Umweltbelastungspunkte (UBP) umgerechnet und lassen sich so vergleichen.'))}
  <section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="justify-content:space-between"><h3>${t('Umweltprofil · ökologische Knappheit 2021')}</h3><span class="num muted">${t('{v} UBP gesamt', { v: nf(pTot) })}</span></div>
    <div class="bars">${bars(prof.map(p => ({ name: p.name, value: p.value })), 0, pTot, null)}</div>
  </section>`;
}

function tWarum() {
  const w = S.why;
  if (!w) return busy();
  const max = Math.max(...w.parts.map(p => Math.abs(p.contribution || 0)), Math.abs(w.rest), 1e-300);
  const sign = v => v > 0 ? '+' : v < 0 ? '−' : '';
  const row = (label, sub, v, share) => `<tr><td>${label}${sub ? `<br><span class="muted" style="font-size:13px">${sub}</span>` : ''}</td>
    <td class="num nw" style="text-align:right">${v === null ? '–' : sign(v) + nf(Math.abs(v))}</td>
    <td><div class="share"><div class="t"><i class="${v < 0 ? 'neg' : 'hot'}" style="width:${v === null ? 0 : Math.abs(v) / max * 100}%"></i></div><span>${share === null ? '' : pct(share)}</span></div></td></tr>`;
  const rows = w.parts.map(p => row(
    p.kind === 'input' ? t('<b>{input}</b> <span class="muted">als Input von</span> {activity} <span class="muted">{location}</span>', { input: esc(p.input), activity: esc(p.activity), location: esc(p.location || '') })
      : t('<b>{input}</b> <span class="muted">Emission von</span> {activity} <span class="muted">{location}</span>', { input: esc(p.input), activity: esc(p.activity), location: esc(p.location || '') }),
    t('{old} → {new} {unit} pro Einheit; im Produktsystem gebraucht: {used}×', { old: nf(p.old), new: nf(p.new), unit: esc(p.unit || ''), used: nf(p.used) }), p.contribution, p.share)).join('');
  const restRow = Math.abs(w.rest) > 1e-9 * Math.max(Math.abs(w.score_original), 1e-300)
    ? row(t('<b>Nicht erklärt</b> <span class="muted">(Änderungen, die nicht in dieser App gemacht wurden)</span>'), '', w.rest, w.difference ? w.rest / w.difference : null) : '';
  return `${explain(t('Die Arbeitskopie gibt ein anderes Ergebnis als das Original. Hier steht, <b>welche deiner Änderungen wie viel davon ausmacht</b>. Die Teile summieren sich <b>exakt</b> zur Differenz (kein Näherungswert). Jeder Teil gilt «mit allen anderen Änderungen schon eingerechnet».'))}
  <section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="justify-content:space-between;align-items:flex-end">
      <div><span class="eyebrow">${t('Original ({name})', { name: esc(w.original) })}</span><div class="kpi"><span class="big">${nf(w.score_original)}</span><span class="u">${esc(w.unit)}</span></div></div>
      <div><span class="eyebrow">${t('Arbeitskopie')}</span><div class="kpi"><span class="big">${nf(w.score_copy)}</span><span class="u">${esc(w.unit)}</span></div></div>
      <div><span class="eyebrow">${t('Differenz')}</span><div class="kpi"><span class="big">${sign(w.difference)}${nf(Math.abs(w.difference))}</span><span class="u">${pct(w.score_original ? w.difference / Math.abs(w.score_original) : 0)}</span></div></div>
    </div>
    <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Änderung')}</th><th style="text-align:right">${t('Beitrag ({unit})', { unit: esc(w.unit) })}</th><th>${t('Anteil an der Differenz')}</th></tr></thead><tbody>${rows}${restRow}</tbody></table></div>
    <p class="muted" style="font-size:12.5px">${t('Summe der Teile: {sum}, Differenz: {diff}.', { sum: `<span class="num">${nf(w.explained)}</span> ${esc(w.unit)}`, diff: `<span class="num">${nf(w.difference)}</span> ${esc(w.unit)}` })}</p>
  </section>`;
}

// ---------- versions: the same product in another version of the background data ----------

export async function loadTargets() {
  const v = S.ver;
  if (!v.project || !S.st.projects.some(p => p.name === v.project && !p.legacy)) {
    // default: another database of this project if there is one, else the first other project
    const own = S.st.databases.filter(d => d.role === 'background' && d.name !== S.fu.database);
    v.project = own.length ? S.st.project : (S.st.projects.find(p => !p.legacy && p.name !== S.st.project)?.name || S.st.project);
    v.targets = null;
  }
  if (!v.targets) {
    v.targets = (await api(`/api/versions/targets?project=${encodeURIComponent(v.project)}`))
      .filter(d => !(v.project === S.st.project && d.name === S.fu.database));
    if (!v.targets.some(d => d.name === v.database)) v.database = v.targets[0]?.name || null;
  }
}

function tVersionen() {
  const v = S.ver, w = v.res;
  const projects = S.st.projects.filter(p => !p.legacy);
  const sign = x => x > 0 ? '+' : x < 0 ? '−' : '';
  const form = `<section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="align-items:flex-end">
      <label class="f">${t('Projekt der anderen Version')}<select id="verProj" ${v.running ? 'disabled' : ''}>${projects.map(p => `<option value="${esc(p.name)}" ${p.name === v.project ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
      <label class="f">${t('Datenbank')}<select id="verDb" ${v.running ? 'disabled' : ''}>${(v.targets || []).map(d => `<option value="${esc(d.name)}" ${d.name === v.database ? 'selected' : ''}>${esc(d.name)} · ${nf(d.count)}</option>`).join('')}</select></label>
      <button class="btn primary" data-act="ver-run" ${v.database && !v.running ? '' : 'disabled'}>${w ? t('Neu vergleichen') : t('Vergleichen')}</button>
    </div>
    ${v.targets && !v.targets.length ? `<p class="empty">${t('In diesem Projekt gibt es keine andere Hintergrund-Datenbank. Wähle ein Projekt mit der anderen Version.')}</p>` : ''}
    ${v.running ? `<p class="busy" role="status">${t('Vergleiche … beim ersten Mal muss die andere Version vorbereitet werden, bei ecoinvent eine bis zwei Minuten.')}</p>` : ''}
    ${v.error ? `<div class="warnbox"><b>${t('Hinweis')}</b><span>${esc(v.error)}</span></div>` : ''}
  </section>`;
  const intro = explain(t('Dasselbe Produkt in einer anderen Version der Hintergrunddaten, zum Beispiel ecoinvent 3.10 gegen 3.11. Die Differenz wird <b>exakt</b> auf die Datensätze aufgeteilt, die sich geändert haben, und auf geänderte Charakterisierungsfaktoren. Ein Teil gilt «mit den Mengen der neuen Version und den Einheitswerten der alten». Datensätze werden über ihren Code zugeordnet, sonst über Name, Produkt, Ort und Einheit.'));
  if (!w) return intro + form;
  const max = Math.max(...w.parts.map(p => Math.abs(p.contribution)), Math.abs(w.parts_rest), Math.abs(w.flows_total), 1e-300);
  const bar = (x, share) => `<div class="share"><div class="t"><i class="${x < 0 ? 'neg' : 'hot'}" style="width:${Math.abs(x) / max * 100}%"></i></div><span>${share === null || share === undefined ? '' : pct(share)}</span></div>`;
  const rows = w.parts.map(p => `<tr class="${v.k === p.k ? 'sel' : ''}"><td><button class="linkbtn" data-act="ver-detail" data-k="${p.k}">${esc(p.name)}</button> <span class="muted">${esc(p.location || '')}</span>${p.status === 'new' ? ` <span class="chip acc">${t('neu')}</span>` : ''}<br><span class="muted" style="font-size:12.5px">${t('{n} Änderung(en); gebraucht: {used} {unit}', { n: p.changes, used: nf(p.used), unit: esc(p.unit || '') })}</span></td>
    <td class="num nw" style="text-align:right">${sign(p.contribution)}${nf(Math.abs(p.contribution))}</td><td>${bar(p.contribution, p.share)}</td></tr>`).join('');
  const extra = [
    Math.abs(w.parts_rest) > 0 ? `<tr><td class="muted">${t('Übrige geänderte Datensätze')}</td><td class="num nw" style="text-align:right">${sign(w.parts_rest)}${nf(Math.abs(w.parts_rest))}</td><td>${bar(w.parts_rest, w.difference ? w.parts_rest / w.difference : null)}</td></tr>` : '',
    Math.abs(w.flows_total) > 0 ? `<tr><td>${t('<b>Charakterisierungsfaktoren</b> der Methode geändert')}</td><td class="num nw" style="text-align:right">${sign(w.flows_total)}${nf(Math.abs(w.flows_total))}</td><td>${bar(w.flows_total, w.difference ? w.flows_total / w.difference : null)}</td></tr>` : '',
    Math.abs(w.demand) > 0 ? `<tr><td>${t('Referenzfluss des Produkts zugeordnet zu einem anderen Datensatz')}</td><td class="num nw" style="text-align:right">${sign(w.demand)}${nf(Math.abs(w.demand))}</td><td>${bar(w.demand, w.difference ? w.demand / w.difference : null)}</td></tr>` : '',
  ].join('');
  const d = v.detail;
  const detail = d ? `<section class="card" style="display:flex;flex-direction:column;gap:10px"><span class="eyebrow">${t('Geänderte Austausche')}</span>
    <h3>${esc(d.name)} <span class="muted">${esc(d.location || '')}</span></h3>
    <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Austausch')}</th><th style="text-align:right">${t('alte Version')}</th><th style="text-align:right">${t('neue Version')}</th><th style="text-align:right">${t('Beitrag ({unit})', { unit: esc(w.unit) })}</th></tr></thead><tbody>
    ${d.rows.map(r => `<tr><td>${r.kind === 'emission' ? t('Emission') : r.kind === 'production' ? t('Referenzfluss') : t('Input')}: <b>${esc(r.name)}</b> <span class="muted">${esc(r.location || '')}</span></td>
      <td class="num nw" style="text-align:right">${nf(r.old)} ${esc(r.unit || '')}</td><td class="num nw" style="text-align:right">${nf(r.new)} ${esc(r.unit || '')}</td><td class="num nw" style="text-align:right">${sign(r.contribution)}${nf(Math.abs(r.contribution))}</td></tr>`).join('')}
    </tbody></table></div>${d.more ? `<p class="muted" style="font-size:12.5px">${t('{n} weitere kleinere Änderungen.', { n: nf(d.more) })}</p>` : ''}</section>` : '';
  const flows = w.flows.length ? `<section class="card" style="display:flex;flex-direction:column;gap:10px"><h3>${t('Geänderte Charakterisierungsfaktoren')}</h3>
    <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Stoff')}</th><th style="text-align:right">${t('alter Faktor')}</th><th style="text-align:right">${t('neuer Faktor')}</th><th style="text-align:right">${t('Beitrag ({unit})', { unit: esc(w.unit) })}</th></tr></thead><tbody>
    ${w.flows.map(f => `<tr><td>${esc(f.name)} <span class="muted">${esc(f.categories)}</span></td><td class="num nw" style="text-align:right">${nf(f.old_cf)}</td><td class="num nw" style="text-align:right">${nf(f.new_cf)}</td><td class="num nw" style="text-align:right">${sign(f.contribution)}${nf(Math.abs(f.contribution))}</td></tr>`).join('')}
    </tbody></table></div></section>` : '';
  const pctDiff = w.version0.score ? w.difference / Math.abs(w.version0.score) : 0;
  return intro + form + `<section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="justify-content:space-between;align-items:flex-end">
      <div><span class="eyebrow">${t('Diese Version')} · ${esc(w.version0.database)}</span><div class="kpi"><span class="big">${nf(w.version0.score)}</span><span class="u">${esc(w.unit)}</span></div></div>
      <div><span class="eyebrow">${t('Andere Version')} · ${esc(w.version1.database)}</span><div class="kpi"><span class="big">${nf(w.version1.score)}</span><span class="u">${esc(w.unit)}</span></div></div>
      <div><span class="eyebrow">${t('Differenz')}</span><div class="kpi"><span class="big">${sign(w.difference)}${nf(Math.abs(w.difference))}</span><span class="u">${pct(pctDiff)}</span></div></div>
    </div>
    <p class="muted" style="font-size:13px">${t('{changed} Datensätze tragen zur Differenz bei (neu: {new}, nicht mehr vorhanden: {removed}). Lieferkette: {n0} gegen {n1} Datensätze.', { changed: nf(w.datasets_changed), new: nf(w.datasets_new), removed: nf(w.datasets_removed), n0: nf(w.version0.datasets), n1: nf(w.version1.datasets) })}</p>
    <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Datensatz')}</th><th style="text-align:right">${t('Beitrag ({unit})', { unit: esc(w.unit) })}</th><th>${t('Anteil an der Differenz')}</th></tr></thead><tbody>${rows}${extra}</tbody></table></div>
    <p class="muted" style="font-size:12.5px">${t('Summe der Teile: {sum}, Differenz: {diff}. Klick auf einen Datensatz zeigt seine geänderten Austausche.', { sum: `<span class="num">${nf(w.explained)}</span> ${esc(w.unit)}`, diff: `<span class="num">${nf(w.difference)}</span> ${esc(w.unit)}` })}</p>
  </section>${detail}${flows}`;
}
