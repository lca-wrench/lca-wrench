// Data sheet of one process. Read-only for background data, a live editor for own models.
'use strict';
import { S, esc, nf, pct, signedPct, U, methodInfo, methodLabel, shareBar, unitChoices, t } from './core.js';

const typeLabel = type => type === 'substitution' ? t('Gutschrift') : t('Input');

function delta(a) {
  if (S.prevScore === null || a.score === null || S.prevScore.id !== a.id || S.prevScore.v === a.score) return '';
  const d = S.prevScore.v ? (a.score - S.prevScore.v) / Math.abs(S.prevScore.v) : 0;
  return `<span class="chip ${d > 0 ? 'hot' : 'acc'} flash" title="${t('vorher {v}', { v: nf(S.prevScore.v) })}">${t('{d} gegenüber vorher', { d: signedPct(d) })}</span>`;
}

// uncertainty of an exchange: the 95 % range, the distribution, the pedigree scores as a tooltip
const UNC_EDIT = { 2: 'lognormal', 3: 'normal', 4: 'uniform', 5: 'triangular' };
export const uncEditType = u => (u && u.pedigree_scores ? 'pedigree' : u && UNC_EDIT[u.type]) || 'lognormal';
// pedigree matrix as in the Activity Browser 3: uncertainty factors (GSD²) of the scores 1 … 5 (as in models.PEDIGREE)
const PEDIGREE = {
  'reliability': [1, 1.54, 1.61, 1.69, 1.69],
  'completeness': [1, 1.03, 1.04, 1.08, 1.08],
  'temporal correlation': [1, 1.03, 1.1, 1.19, 1.29],
  'geographical correlation': [1, 1.04, 1.08, 1.11, 1.11],
  'further technological correlation': [1, 1.18, 1.65, 2.08, 2.8],
};
const pedLabel = k => ({ 'reliability': t('Zuverlässigkeit'), 'completeness': t('Vollständigkeit'), 'temporal correlation': t('Zeitliche Korrelation'),
  'geographical correlation': t('Geografische Korrelation'), 'further technological correlation': t('Weitere technologische Korrelation') })[k];
// GSD² of the lognormal: σ = √(ln² basic + Σ ln² factor) / 2, GSD² = e^(2σ)
export function pedigreeGsd2(scores, basic) {
  const b = basic > 0 ? basic : 1;
  const ss = Math.log(b) ** 2 + Object.keys(PEDIGREE).reduce((x, k) => x + Math.log(PEDIGREE[k][(scores[k] || 1) - 1]) ** 2, 0);
  return Math.exp(Math.sqrt(ss));
}
export function pedigreeHint() {
  const scores = {}; document.querySelectorAll('#uncForm [data-ped]').forEach(el => { scores[el.dataset.ped] = +el.value; });
  const b = parseFloat(document.getElementById('uncBasic')?.value);
  const g = pedigreeGsd2(scores, isFinite(b) ? b : 1);
  return g > 1 + 1e-12 ? t('ergibt lognormal mit GSD² {g}', { g: g.toFixed(3) }) : t('ergibt noch keine Streuung');
}
function uncKind(u) {
  if (u.type === 2 && u.gsd2) return t('lognormal, GSD² {g}', { g: u.gsd2.toFixed(2) });
  if (u.type === 3 && u.sd !== undefined) return t('normal, SD {sd}', { sd: nf(u.sd) });
  return u.name;
}
function uncCell(e, model) {
  const u = e.uncertainty;
  const edit = model && e.type !== 'production';
  if (!u) return edit ? `<button class="linkbtn" data-act="unc-edit" data-k="${e.exchange}" style="font-size:12.5px">${t('festlegen')}</button>` : '<span class="muted">–</span>';
  const ped = u.pedigree ? t('Pedigree: {list}', { list: Object.entries(u.pedigree).map(([k, v]) => `${k} ${v}`).join(', ') }) : '';
  const range = u.lo !== null && u.hi !== null ? `<span class="num nw">${nf(u.lo)} – ${nf(u.hi)}</span>` : '';
  const kind = `<span class="muted unck">${esc(uncKind(u))}</span>`;
  const inner = `${range}${range ? '<br>' : ''}${kind}`;
  return edit ? `<button class="linkbtn uncbtn" data-act="unc-edit" data-k="${e.exchange}" title="${esc(ped || t('Unsicherheit ändern'))}">${inner}</button>`
    : `<span title="${esc(ped)}">${inner}</span>`;
}
function uncEditor(e, cols) {
  const u = e.uncertainty, ty = S.uncType;
  const num = (id, label, val, ph) => `<label class="f">${label}<input type="number" step="any" id="${id}" value="${val ?? ''}" placeholder="${ph}" style="width:120px"></label>`;
  const fields = ty === 'lognormal' ? num('uncGsd', t('GSD²'), u && u.gsd2 ? +u.gsd2.toPrecision(4) : '', '1.5') + `<span class="muted" style="font-size:12.5px;align-self:center">${t('etwa 95 % zwischen Menge ÷ GSD² und Menge × GSD²')}</span>`
    : ty === 'normal' ? num('uncSd', t('Standardabweichung'), u && u.sd !== undefined ? +(+u.sd).toPrecision(6) : '', nf(Math.abs(e.amount) * 0.1))
    : ty === 'none' ? ''
    : ty === 'pedigree' ? Object.keys(PEDIGREE).map(k => `<label class="f">${pedLabel(k)}<select data-ped="${k}">${[1, 2, 3, 4, 5].map(n => `<option ${(u && u.pedigree_scores ? u.pedigree_scores[k] : 1) === n ? 'selected' : ''}>${n}</option>`).join('')}</select></label>`).join('')
      + num('uncBasic', t('Basisunsicherheit (GSD²)'), u && u.pedigree_basic ? +u.pedigree_basic.toPrecision(4) : '', '1')
      + `<span class="muted" style="font-size:12.5px;align-self:center"><span id="pedHint"></span><br>${t('1 = beste Datenqualität; Faktoren wie im Activity Browser')}</span>`
    : num('uncMin', t('Minimum'), u && u.min !== undefined && u.min !== null ? u.min : '', nf(e.amount * 0.8)) + num('uncMax', t('Maximum'), u && u.max !== undefined && u.max !== null ? u.max : '', nf(e.amount * 1.2));
  const opt = (v, l) => `<option value="${v}" ${v === ty ? 'selected' : ''}>${l}</option>`;
  return `<tr class="uncrow"><td colspan="${cols}"><form id="uncForm" data-k="${e.exchange}" class="row" style="gap:10px;align-items:flex-end">
    <label class="f">${t('Verteilung von «{name}»', { name: esc(e.name) })}<select id="uncType">${opt('none', t('keine'))}${opt('lognormal', 'lognormal')}${opt('pedigree', t('lognormal aus Pedigree-Matrix'))}${opt('normal', 'normal')}${opt('uniform', t('gleichverteilt'))}${opt('triangular', t('dreiecksverteilt'))}</select></label>
    ${fields}
    <button class="btn primary" type="submit">${t('Übernehmen')}</button><button class="btn" type="button" data-act="unc-cancel">${t('Abbrechen')}</button></form></td></tr>`;
}

function description(a) {
  if (!a.comment) return `<p class="comment">${t('Dieser Datensatz hat keine Beschreibung.')}</p>`;
  const full = S.fullComment === a.id || a.comment.length <= 600;
  return `<div class="desc"><div class="eyebrow">${t('Beschreibung')}</div><p class="comment">${esc(full ? a.comment : a.comment.slice(0, 600).replace(/\s+\S*$/, '') + ' …')}</p>
    ${a.comment.length > 600 ? `<button class="linkbtn" data-act="full-comment" data-k="${a.id}" style="font-size:13px">${full ? t('Weniger anzeigen') : t('Ganze Beschreibung ({n} Zeichen)', { n: a.comment.length })}</button>` : ''}</div>`;
}

function uncSummary(a) {
  const all = [...a.technosphere, ...a.biosphere], n = all.filter(e => e.uncertainty).length;
  return all.length ? `<span class="chip" title="${t('Diese Posten gehen mit ihrer Verteilung in die Unsicherheitsrechnung ein.')}">${t('Unsicherheit bei {n} von {m} Posten', { n, m: all.length })}</span>` : '';
}

// several products, stored as in the Activity Browser 3: how the process's inputs and emissions are split
const allocLabel = s => s === 'equal' ? t('zu gleichen Teilen') : s === 'manual' ? t('von Hand') : t('nach «{p}»', { p: esc(s) });

function allocCompare(c) {
  const head = c.products.map(p => `<th style="text-align:right">${esc(p.name)} <span class="muted">${t('pro {u}', { u: esc(p.unit) })}</span></th>`).join('');
  const rows = c.rows.map(r => `<tr><td>${allocLabel(r.strategy)}${r.current ? ` <span class="chip acc">${t('gewählt')}</span>` : ''}</td>${c.products.map(p => `<td class="num" style="text-align:right">${nf(r.scores[p.id])} <span class="muted">(${pct(r.factors[p.id])})</span></td>`).join('')}</tr>`).join('');
  return `<div style="display:flex;flex-direction:column;gap:6px"><h4 style="margin:0">${t('Wirkung pro Produkt bei jeder Allokation ({unit})', { unit: esc(c.unit) })}</h4>
    <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Allokation')}</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted" style="font-size:12.5px">${t('In Klammern der Anteil des Produkts. Nichts wird gespeichert; alle übrigen Daten bleiben, wie sie sind.')}</p></div>`;
}

function allocationCard(a, amt, model) {
  const al = a.allocation;
  if (!al) return '';
  const manual = al.strategy === 'manual' && al.editable;
  const prodEx = id => (a.production_exchanges || []).find(e => e.id === id);
  const rows = al.products.map(p => `<tr><td><button class="linkbtn" data-act="open" data-k="${p.id}" data-db="${esc(a.database)}">${esc(p.name)}</button>${p.waste ? ` <span class="chip">${t('Abfall')}</span>` : ''}</td>
      <td>${model && prodEx(p.id) ? amt(prodEx(p.id)) : `<span class="num">${nf(p.amount)}</span>`} <span class="muted">${esc(p.unit || '')}</span></td>
      <td class="num">${manual ? `<input type="number" step="any" min="0" data-alloc="${p.id}" value="${+(p.factor ?? 1).toPrecision(6)}" aria-label="${t('Anteil von {name}', { name: esc(p.name) })}" style="width:90px">` : pct(p.factor ?? 1)}</td>
      <td class="num">${p.score === null || p.score === undefined ? '–' : `${nf(p.score)} <span class="muted">${esc(U())}</span>`}</td></tr>`).join('');
  const off = Math.abs(al.sum - 1) > 1e-6 ? `<div class="warnbox"><span>${t('Die Anteile ergeben zusammen {p} statt 100 %.', { p: pct(al.sum) })}</span></div>` : '';
  const sel = al.editable
    ? `<label class="f">${t('Allokation')}<select id="allocSel">${al.strategies.map(s => `<option value="${esc(s)}" ${s === al.strategy ? 'selected' : ''}>${allocLabel(s)}</option>`).join('')}</select></label>`
    : `<span class="chip">${t('Allokation')}: ${allocLabel(al.strategy)}</span>`;
  return `<section class="card" style="display:flex;flex-direction:column;gap:10px">
    <div class="row" style="justify-content:space-between;align-items:flex-end"><h3>${t('Produkte und Allokation · {n}', { n: al.products.length })}</h3>
      <div class="row" style="gap:8px;align-items:flex-end">${sel}${manual ? `<button class="btn" data-act="alloc-manual">${t('Anteile übernehmen')}</button>` : ''}<button class="btn" data-act="alloc-cmp">${t('Allokationen vergleichen')}</button></div></div>
    <p class="muted" style="font-size:13.5px">${t('Dieser Prozess stellt mehrere Produkte her. Seine Inputs und Emissionen werden nach den Anteilen auf die Produkte verteilt; jedes Produkt hat ein eigenes Datenblatt.')}</p>
    ${off}
    <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Produkt')}</th><th>${t('Menge')}</th><th>${t('Anteil')}</th><th>${t('Wirkung pro Einheit')}</th></tr></thead><tbody>${rows}</tbody></table></div>
    ${S.allocCmp && S.allocCmp.process === al.process ? allocCompare(S.allocCmp) : ''}
  </section>`;
}

function shareNote(a) {
  if (a.share === null || a.share === undefined) return '';
  return `<div class="muted" style="font-size:13.5px">${t('Anteil an den Inputs und Emissionen des Prozesses: {p}. Die Mengen unten sind dieser Anteil; geändert werden sie im Prozess.', { p: pct(a.share) })} <button class="linkbtn" data-act="open" data-k="${a.process_id}" data-db="${esc(a.database)}">${t('Prozess öffnen')}</button></div>`;
}

export function sheet(a, { showAllTech, showAllBio }) {
  const model = a.edit_mode === 'model', copy = a.edit_mode === 'copy', ro = !a.edit_mode;
  const units = unitChoices();
  // own models: an amount is a number or a formula (ƒ); the result of a formula is shown next to it
  const amt = e => {
    if (model && e.type !== 'production' && (e.formula || S.formulaFor === e.exchange)) {
      return `<span class="fcell"><input type="text" class="formula" data-exf="${e.exchange}" value="${esc(e.formula || '')}" placeholder="${t('Formel, z.B. distanz_km * 0.1')}" aria-label="${t('Formel für {name}', { name: esc(e.name) })}" spellcheck="false">${e.formula ? `<span class="num muted nw">= ${nf(e.amount)}</span>` : ''}</span>`;
    }
    if (model || copy) {
      return `<span class="fcell"><input type="number" step="any" data-ex="${e.exchange}" value="${+e.amount.toPrecision(10)}" aria-label="${t('Menge von {name}', { name: esc(e.name) })}">${model && e.type !== 'production' ? `<button class="fbtn" data-act="ex-formula" data-k="${e.exchange}" title="${t('Formel statt Zahl')}" aria-label="${t('Formel für {name}', { name: esc(e.name) })}">ƒ</button>` : ''}${copy && S.st.changes.some(c => c.exchange === e.exchange) ? ` <span class="chip acc">${t('geändert')}</span>` : ''}</span>`;
    }
    return `<span class="num">${nf(e.amount)}</span>`;
  };
  const kind = e => model && e.type !== 'production'
    ? `<select data-extype="${e.exchange}" aria-label="${t('Art')}"><option value="technosphere" ${e.type !== 'substitution' ? 'selected' : ''}>${t('Input')}</option><option value="substitution" ${e.type === 'substitution' ? 'selected' : ''}>${t('Gutschrift')}</option></select>`
    : `<span class="muted">${typeLabel(e.type)}</span>`;
  const del = e => model ? `<button class="iconbtn" data-act="ex-del" data-k="${e.exchange}" aria-label="${t('{name} entfernen', { name: esc(e.name) })}" title="${t('Entfernen')}">×</button>` : '';
  const share = v => v === null || v === undefined || a.score === null ? '<span class="muted">–</span>' : shareBar(v, a.score);
  const tech = showAllTech ? a.technosphere : a.technosphere.slice(0, 30);
  const bio = showAllBio ? a.biosphere : a.biosphere.slice(0, 20);
  const m = methodInfo();

  const head = model ? `
    <div class="pform">
      <label class="f wide">${t('Name')}<input type="text" data-pf="name" value="${esc(a.name)}"></label>
      ${a.allocation ? '' : `<label class="f">${t('Referenzprodukt')}<input type="text" data-pf="reference product" value="${esc(a.product || '')}"></label>`}
      ${a.allocation ? '' : `<label class="f">${t('Einheit')}<select data-pf="unit">${units.map(([v, l]) => `<option value="${v}" ${v === a.unit_raw ? 'selected' : ''}>${l}</option>`).join('')}${units.some(([v]) => v === a.unit_raw) ? '' : `<option value="${esc(a.unit_raw)}" selected>${esc(a.unit)}</option>`}</select></label>`}
      <label class="f">${t('Ort')}<input type="text" data-pf="location" value="${esc(a.location || '')}" maxlength="40" style="width:90px"></label>
      <label class="f wide">${t('Beschreibung')}<textarea data-pf="comment" rows="2">${esc(a.comment)}</textarea></label>
    </div>`
    : `<h2>${esc(a.name)}</h2>${a.product && a.product !== a.name ? `<div class="muted" style="font-size:13.5px">${t('Referenzprodukt')}: ${esc(a.product)}</div>` : ''}${description(a)}${shareNote(a)}`;

  const errors = a.errors && a.errors.length ? `<div class="warnbox"><b>${t('Modell nicht lösbar')}</b><span>${a.errors.map(esc).join(' ')}</span></div>` : '';
  const roBox = ro && (a.share === null || a.share === undefined) ? `<div class="ro"><span>${t('Hintergrunddaten bleiben unverändert. Um diesen Prozess anzupassen, kopiere ihn in ein eigenes Modell.')}</span>
      <div class="row"><button class="btn primary" data-act="copy-to-model" data-k="${a.id}">${t('In eigenes Modell kopieren')}</button>${S.st.is_copy ? '' : `<button class="btn" data-act="copy" title="${t('Kopiert das ganze Projekt, ca. 420 MB')}">${t('Arbeitskopie des Projekts')}</button>`}</div></div>` : '';

  const prodRows = model ? a.production_exchanges.map(e => `<tr><td>${esc(a.product || a.name)}</td><td>${amt(e)}</td><td class="muted">${esc(a.unit)}</td></tr>`).join('') : '';
  const role = model || a.role === 'model' ? t('Eigenes Modell') : a.role === 'background' ? t('Hintergrunddaten') : esc(a.role || '');

  return `<section class="card sheethead" style="display:flex;flex-direction:column;gap:12px">
      <div class="row" style="gap:6px"><span class="chip ${model ? 'acc' : ''}">${role}</span><span class="chip">${esc(a.database)}</span>${model ? '' : `<span class="chip">${esc(a.location || '–')}</span><span class="chip">${esc(a.unit)}</span>`}${a.categories ? `<span class="chip">${esc(a.categories)}</span>` : ''}${uncSummary(a)}</div>
      ${head}
      ${errors}
      <div class="row" style="justify-content:space-between;align-items:flex-end">
        <div>${a.allocation && a.score === null ? '' : `<div class="eyebrow">${t('{method} pro 1 {unit}, mit ganzer Lieferkette', { method: esc(methodLabel(m)), unit: esc(a.unit) })}</div>`}
          ${a.allocation && a.score === null ? `<div class="muted" style="font-size:13.5px;max-width:52ch">${t('Mehrere Produkte: die Wirkung pro Produkt steht unten bei der Allokation.')}</div>` : ''}
          ${a.allocation && a.score === null ? '' : `<div class="kpi"><span class="big ${S.prevScore && S.prevScore.id === a.id && S.prevScore.v !== a.score ? 'flashnum' : ''}">${nf(a.score)}</span><span class="u">${esc(U())}</span>${delta(a)}</div>`}
          <div class="muted" style="font-size:13px">${a.score !== null ? t('davon direkt in diesem Prozess: {v} ({p})', { v: `${nf(a.direct)} ${esc(U())}`, p: pct(a.score ? a.direct / a.score : 0) }) : ''}</div>
          ${a.calculated_alone ? `<div class="muted" style="font-size:13px">${t('Allein mit «{db}» gerechnet: diese Datenbank gehört nicht zu den Hintergrunddaten der Rechnung (unter Start wählen).', { db: esc(a.calculated_alone) })}</div>` : ''}</div>
        ${a.allocation && a.score === null ? '' : `<div class="row" style="gap:8px"><button class="btn" data-act="add-cmp-act">${t('Zum Vergleich')}</button><button class="btn" data-act="add-setup" data-k="${a.id}">${t('Zur Rechnung')}</button><button class="btn" data-act="graph-act">${t('Lieferkette')}</button><button class="btn primary" data-act="calc-act">${t('Ergebnis')}</button></div>`}
      </div>
      ${roBox}
    </section>
    ${allocationCard(a, amt, model)}
    ${model && !a.allocation ? `<section class="card"><h3 style="margin-bottom:6px">${t('Referenzfluss')}</h3><p class="muted" style="font-size:13.5px;margin-bottom:6px">${t('Was dieser Prozess herstellt. Alle Mengen unten beziehen sich auf diese Menge.')}</p>
      <div class="tblwrap"><table class="tbl"><tbody>${prodRows}</tbody></table></div></section>` : ''}
    <section class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h3>${t('Inputs aus anderen Prozessen · {n}', { n: a.technosphere.length })}</h3>${model ? `<button class="btn" data-act="pick-input">${t('+ Input hinzufügen')}</button>` : ''}</div>
      <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Input')}</th><th>${a.allocation ? t('Menge (für die Produktmengen oben)') : t('Menge pro {v}', { v: `${nf(a.production)} ${esc(a.unit)}` })}</th><th>${t('Einheit')}</th>${model ? `<th>${t('Art')}</th>` : ''}<th title="${t('Bereich, in dem die Menge mit 95 % Wahrscheinlichkeit liegt, und die Verteilung')}">${t('Unsicherheit (95 %)')}</th><th>${t('Anteil an der Wirkung')}</th>${model ? '<th></th>' : ''}</tr></thead><tbody>
      ${tech.map(e => `<tr><td><button class="linkbtn" data-act="open" data-k="${e.id}" data-db="${esc(e.database)}">${esc(e.name)}</button> <span class="muted">${esc(e.location)}</span></td><td>${amt(e)}</td><td class="muted">${esc(e.unit)}</td>${model ? `<td>${kind(e)}</td>` : ''}<td>${uncCell(e, model)}</td><td>${share(e.contribution)}</td>${model ? `<td>${del(e)}</td>` : ''}</tr>${model && S.uncFor === e.exchange ? uncEditor(e, 7) : ''}`).join('') || `<tr><td colspan="7" class="muted">${model ? t('Noch keine Inputs. Füge Material, Energie oder Transporte hinzu.') : t('Keine Inputs.')}</td></tr>`}
      </tbody></table></div>
      ${a.technosphere.length > 30 ? `<button class="linkbtn" data-act="all-tech" style="margin-top:8px">${showAllTech ? t('Weniger anzeigen') : t('Alle {n} anzeigen', { n: a.technosphere.length })}</button>` : ''}
    </section>
    <section class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h3>${t('Emissionen und Ressourcen · {n}', { n: a.biosphere.length })}</h3>${model ? `<button class="btn" data-act="pick-flow">${t('+ Emission oder Ressource')}</button>` : ''}</div>
      <div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Stoff')}</th><th>${t('Menge')}</th><th>${t('Einheit')}</th><th title="${t('Bereich, in dem die Menge mit 95 % Wahrscheinlichkeit liegt, und die Verteilung')}">${t('Unsicherheit (95 %)')}</th><th>${t('Anteil an der Wirkung')}</th>${model ? '<th></th>' : ''}</tr></thead><tbody>
      ${bio.map(e => `<tr><td>${esc(e.name)} <span class="muted">${esc(e.categories)}</span></td><td>${amt(e)}</td><td class="muted">${esc(e.unit)}</td><td>${uncCell(e, model)}</td><td>${share(e.contribution)}</td>${model ? `<td>${del(e)}</td>` : ''}</tr>${model && S.uncFor === e.exchange ? uncEditor(e, 6) : ''}`).join('') || `<tr><td colspan="6" class="muted">${t('Keine direkten Emissionen.')}</td></tr>`}
      </tbody></table></div>
      ${a.biosphere.length > 20 ? `<button class="linkbtn" data-act="all-bio" style="margin-top:8px">${showAllBio ? t('Weniger anzeigen') : t('Alle {n} anzeigen', { n: a.biosphere.length })}</button>` : ''}
    </section>
    ${model ? `<section class="card row" style="justify-content:space-between">
      <div style="font-size:14px">${a.users.length ? t('Verwendet in: {list}', { list: a.users.map(u => `<button class="linkbtn" data-act="open" data-k="${u.id}" data-db="${esc(u.database)}">${esc(u.name)}</button>`).join(', ') }) : `<span class="muted">${t('Wird von keinem anderen Prozess verwendet.')}</span>`}</div>
      <div class="row" style="gap:8px"><button class="btn" data-act="dup-proc" data-k="${a.id}">${t('Duplizieren')}</button><button class="btn danger" data-act="del-proc" data-k="${a.id}">${t('Prozess löschen')}</button></div>
    </section>` : ''}`;
}
