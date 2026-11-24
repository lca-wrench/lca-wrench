// Shared state and helpers for LCA Wrench UI.
'use strict';
import { t, LANG, locale } from './i18n.js';

export { t, LANG };

export const S = {
  st: null, method: null, view: 'start', explain: true, busy: 0,
  // Daten
  q: '', loc: '', dbf: '', unit: '', sopts: null, results: [], sel: null, act: null, showAllTech: false, showAllBio: false,
  // Modellieren
  mdb: null, mprocs: [], msel: null, mact: null, newProc: false, newDb: false, prevScore: null, move: null,
  // Rechnen
  setup: null, setupRes: null, setupVerify: null, newSetup: false,
  mc: { n: 500, k: 0, job: null, res: null, sig: null, error: null },
  sens: { j: 0, n: 1000, job: null, res: null, error: null },
  // Ergebnis
  fu: null, tab: 'beitraege', calc: null, cats: { a: null, b: '', topic: '', res: null }, contrib: 'act', graph: null, cutoff: 0.01, depth: 4, gsel: null,
  par: { data: null, adding: null }, formulaFor: null,
  why: null, cw: { project: null, database: null, targets: null, method: '', res: null, running: false, error: null, open: null, q: '', hits: null, view: 'datasets', trace: {} },
  ss: { sets: null, setsKey: null, set: null, picked: false, w: null, res: null, error: null },
  ver: { project: null, database: null, targets: null, res: null, detail: null, k: null, running: false, error: null }, sankey: null, skCut: 0.02, skMax: 40, skMode: 'cum', sksel: null, inv: null, invQ: '', invF: '', fuVerify: null,
  // Vergleich
  cmp: [], cmpRes: null,
  // Dialoge
  picker: null, mpicker: null, copyTo: null,
};

export function loadPrefs() {
  try {
    S.explain = localStorage.getItem('wb-explain') !== '0';
    S.cmp = JSON.parse(localStorage.getItem('wb-compare') || '[]');
  } catch (_) { /* storage unavailable */ }
}
export function savePref(k, v) { try { localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); } catch (_) { } }

export const $ = id => document.getElementById(id);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function nf(v) {
  if (v === null || v === undefined || !isFinite(v)) return '–';
  const a = Math.abs(v); if (a < 1e-15) return '0';
  const o = a >= 1000 ? { maximumFractionDigits: 0 } : a >= 10 ? { maximumFractionDigits: 1 } : a >= 1 ? { maximumFractionDigits: 2 } : { maximumSignificantDigits: 3 };
  return v.toLocaleString(locale(), o);
}
export const pct = x => !isFinite(x) ? '–' : (x * 100).toLocaleString(locale(), { maximumFractionDigits: Math.abs(x) < 0.1 ? 1 : 0 }).replace('-', '−') + (LANG === 'en' ? '%' : ' %');
export const signedPct = x => !isFinite(x) ? '' : (x > 0 ? '+' : x < 0 ? '−' : '±') + pct(Math.abs(x));
export const mKey = m => JSON.stringify(m);
export const methodInfo = (m = S.method) => S.st.methods.find(x => mKey(x.id) === mKey(m)) || { id: m, name: (m || []).join(' · '), unit: '', family: '' };
// the methods this app adds to BAFU projects have German names
const LCA_WRENCH_METHODS = { Klimawandel: () => t('Klimawandel'), 'Umweltbelastungspunkte gesamt': () => t('Umweltbelastungspunkte gesamt') };
export const methodLabel = m => { if (m.family !== 'Werkbank') return m.name; const n = m.name.split(' · ')[0]; return LCA_WRENCH_METHODS[n] ? LCA_WRENCH_METHODS[n]() : n; };
export const familyLabel = f => f === 'Werkbank' ? t('Empfohlen') : f;
export const methodShort = id => methodLabel(methodInfo(id));
export const U = () => methodInfo().unit;
export const isModelDb = name => S.st.databases.some(d => d.name === name && d.role === 'model');

// the server answers in the language of the UI
// X-LCA-Wrench: the server accepts changes only with it (protection against other websites, see api.local_only)
export const langHeader = () => ({ 'X-Lang': LANG, 'X-LCA-Wrench': '1' });

// fetch, with a message a person understands when the server does not answer at all (stopped, computer asleep)
export async function request(path, init) {
  try { return await fetch(path, init); }
  catch (_) { throw new Error(t('LCA Wrench antwortet nicht. Läuft das Programm noch? Sonst neu starten und die Seite neu laden.')); }
}
// the error text of a failed answer: the server's own message, else the HTTP status
export function failure(r, data) {
  const d = data?.detail;
  return new Error(typeof d === 'string' ? d : Array.isArray(d) ? t('Eingabe ungültig: {list}', { list: d.map(x => x.msg).join(', ') }) : t('Die Anfrage ist fehlgeschlagen (Fehler {status}).', { status: r.status }));
}

export async function api(path, body) {
  S.busy++; renderBusy();
  try {
    const r = await request(path, body === undefined ? { headers: langHeader() } : { method: 'POST', headers: { 'Content-Type': 'application/json', ...langHeader() }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw failure(r, data);
    return data;
  } finally { S.busy--; renderBusy(); }
}

// a short note at the bottom; errors look different, are read out at once and stay until read (10 s or closed)
let toastT;
export function toast(msg, action, error = false) {
  const el = $('toast');
  el.classList.toggle('err', error);
  el.setAttribute('role', error ? 'alert' : 'status');
  el.innerHTML = `<span>${esc(msg)}</span>` + (action ? ` <button class="linkbtn tlink" data-act="${action.act}" ${action.k !== undefined ? `data-k="${esc(action.k)}"` : ''}>${esc(action.label)}</button>` : '')
    + `<button class="tclose" data-act="toast-close" aria-label="${t('Schliessen')}" title="${t('Schliessen')}">×</button>`;
  el.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => el.hidden = true, error ? 10000 : action ? 8000 : 5000);
}
export async function guard(fn) { try { await fn(); } catch (e) { toast(e.message, null, true); console.error(e); } }
// "Rechne …" only for requests that take noticeably long: on fast ones it would just flash for a few milliseconds
let busyTimer = null;
export function renderBusy() {
  const b = $('busy'); if (!b) return;
  if (!S.busy) { clearTimeout(busyTimer); busyTimer = null; b.innerHTML = ''; return; }
  if (b.innerHTML || busyTimer) return;
  busyTimer = setTimeout(() => { busyTimer = null; if (S.busy) b.innerHTML = `<span class="busy">${t('Rechne …')}</span>`; }, 350);
}

const IC = {
  start: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
  daten: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  modell: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><path d="M10 6.5h4.5a2 2 0 0 1 2 2V14"/>',
  rechnen: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h2M12 11h2M16 11h0M8 15h2M12 15h2M8 18h2M12 18h2"/>',
  ergebnis: '<path d="M4 20h16"/><path d="M7 17v-5M12 17V7M17 17v-8"/>',
  vergleich: '<path d="M4 7h16M4 12h9M4 17h13"/>',
  parameter: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
};
export const views = () => [['start', t('Start')], ['daten', t('Daten')], ['modell', t('Modellieren')], ['parameter', t('Parameter')], ['rechnen', t('Rechnen')], ['ergebnis', t('Ergebnis')], ['vergleich', t('Vergleich')]];
export const icon = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[k]}</svg>`;
// search results carry "spelling" where the server corrected a word ("steeel" -> "steel")
export const spellingNote = rows => { const f = rows.find(r => r.spelling)?.spelling; return f ? `<p class="muted" role="status" style="font-size:13px;margin:2px 4px 6px">${t('Auch Treffer für «{q}»', { q: esc(f) })}</p>` : ''; };
export const explain = t => S.explain ? `<div class="explain"><span class="i" aria-hidden="true">i</span><p>${t}</p></div>` : '';

export const unitChoices = () => [['unit', t('Stück')], ['kilogram', 'kg'], ['kilometer', 'km'], ['kilowatt hour', 'kWh'], ['megajoule', 'MJ'],
  ['cubic meter', 'm³'], ['square meter', 'm²'], ['meter', 'm'], ['ton kilometer', 'tkm'], ['person kilometer', 'pkm'], ['litre', 'l'], ['hour', 'h']];

export function shareBar(v, total) {
  const s = total ? v / total : 0;
  const w = Math.max(0, Math.min(100, Math.abs(s) * 100));
  return `<div class="share"><div class="t"><i class="${s >= 0.25 ? 'hot' : s < 0 ? 'neg' : ''}" style="width:${w}%"></i></div><span>${pct(s)}</span></div>`;
}

export function bars(items, rest, total, act) {
  const all = items.map(x => ({ ...x }));
  // the rest: many small items together, not a hotspot, so never in the warning colour
  if (Math.abs(rest) > 1e-15) all.push({ name: t('Übrige'), value: rest, rest: true });
  const max = Math.max(...all.map(x => Math.abs(x.value)), 1e-15);
  return all.map(x => `<button class="bar" ${act && x.id ? `data-act="${act}" data-k="${x.id}"` : 'tabindex="-1"'} title="${esc(x.name)}"><span>${esc(x.name)}${x.location ? ` <span class="muted">${esc(x.location)}</span>` : ''}${x.categories ? ` <span class="muted">${esc(x.categories)}</span>` : ''}${x.database && isModelDb(x.database) ? ` <span class="chip acc">${t('Modell')}</span>` : ''}</span><span class="t"><i class="${x.rest ? 'rest' : x.value < 0 ? 'neg' : total && x.value / total >= 0.25 ? 'hot' : ''}" style="width:${Math.abs(x.value) / max * 100}%"></i></span><span class="v"><span>${nf(x.value)}</span><span class="p">${pct(total ? x.value / total : 0)}</span></span></button>`).join('');
}

// a file the server makes (CSV, Excel): POST the request, save the answer under the name the server gives
export async function download(path, body) {
  S.busy++; renderBusy();
  try {
    const r = await request(path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...langHeader() }, body: JSON.stringify(body) });
    if (!r.ok) throw failure(r, await r.json().catch(() => ({})));
    const m = /filename\*=UTF-8''([^;]+)/.exec(r.headers.get('Content-Disposition') || '');
    const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob());
    a.download = m ? decodeURIComponent(m[1]) : 'LCA Wrench'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } finally { S.busy--; renderBusy(); }
}

// unit groups of the search (service.UNIT_GROUPS)
export const unitGroups = () => ({ energy: t('Energie (kWh, MJ)'), mass: t('Masse (kg, t)'), volume: t('Volumen (m³, l)'), area: t('Fläche (m²)'),
  land: t('Landnutzung (m²·a)'), freight: t('Gütertransport (tkm)'), passenger: t('Personenverkehr (pkm)'), vehicle: t('Fahrzeug (km)'),
  length: t('Länge (m, km)'), item: t('Stück (Geräte, Infrastruktur)'), time: t('Zeit (h)'), radioactivity: t('Radioaktivität (kBq)'), currency: t('Geld (Mio. €, Input-Output)') });
// kinds of impact, to compare one across methods (overview.TOPICS)
export const topicNames = () => ({ climate: t('Klimawandel'), ozone: t('Ozonabbau'), smog: t('Sommersmog'), particulates: t('Feinstaub'),
  acidification: t('Versauerung'), eutrophication: t('Überdüngung'), toxicity: t('Toxizität (Mensch und Ökosysteme)'), radiation: t('Ionisierende Strahlung'),
  land: t('Landnutzung'), water: t('Wasser'), energy: t('Energieressourcen'), minerals: t('Mineralische Ressourcen'), waste: t('Abfall'),
  total: t('Gesamtbewertung (Einzelwert)'), other: t('Übrige') });
// compartments of elementary flows (service.COMPARTMENTS)
export const compartments = () => ({ air: t('Luft'), water: t('Wasser'), soil: t('Boden'), resource: t('Ressourcen') });

export function csvDownload(name, rows) {
  const q = v => typeof v === 'number' ? String(v) : '"' + String(v ?? '').replace(/"/g, '""') + '"';
  const blob = new Blob(['﻿' + rows.map(r => r.map(q).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
