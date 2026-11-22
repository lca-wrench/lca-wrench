// Rechnen: calculation setups (products × methods), shared with the Activity Browser.
'use strict';
import { S, esc, nf, explain, methodInfo, methodLabel, isModelDb, t } from '../core.js';
import { mcSection, sensSection } from './unsicherheit.js';

export function vRechnen() {
  const list = S.st.setups.length ? S.st.setups.map(c => `<button class="res" data-act="open-setup" data-k="${esc(c.name)}" aria-current="${S.setup && S.setup.name === c.name}"><span>${esc(c.name)}</span><span class="meta">${t('{f} Produkte · {m} Methoden', { f: c.fus, m: c.methods })}</span></button>`).join('')
    : `<p class="empty">${t('Noch keine Rechnung gespeichert.')}</p>`;
  const newForm = S.newSetup ? `<form id="newSetupForm" class="miniform"><label class="f">${t('Name der Rechnung')}<input type="text" id="newSetupName" required maxlength="120" placeholder="${t('z.B. Varianten Fassade')}"></label><div class="row"><button class="btn primary" type="submit">${t('Anlegen')}</button><button class="btn" type="button" data-act="new-setup-cancel">${t('Abbrechen')}</button></div></form>` : '';
  return `${explain(t('Eine <b>Rechnung</b> fasst mehrere Produkte und mehrere Wirkungsmethoden zusammen und rechnet alle Kombinationen auf einmal. Rechnungen werden im Projekt gespeichert, im selben Format wie im Activity Browser: Was du hier anlegst, siehst du dort auch, und umgekehrt.'))}
  <div class="dataview">
    <aside class="card plist" aria-label="${t('Rechnungen')}">
      <div class="row" style="justify-content:space-between;margin-bottom:4px"><span class="eyebrow">${t('Rechnungen')}</span><button class="btn small primary" data-act="new-setup">${t('+ Neu')}</button></div>
      ${newForm}
      <div class="reslist">${list}</div>
    </aside>
    <div class="detail">${S.setup ? editor(S.setup) + results() + mcSection() + (S.setup.fus.length && S.setup.methods.length ? sensSection() : '') : `<section class="card"><p class="empty">${t('Wähle eine Rechnung aus der Liste oder lege eine neue an.')}</p></section>`}</div>
  </div>`;
}

function editor(cs) {
  const fus = cs.fus.map((f, i) => `<tr><td><button class="linkbtn" data-act="open" data-k="${f.id}" data-db="${esc(f.database)}">${esc(f.name)}</button> <span class="muted">${esc(f.location)}</span>${isModelDb(f.database) ? ` <span class="chip acc">${t('Modell')}</span>` : ''}</td>
      <td><input type="number" step="any" data-fuamt="${i}" value="${f.amount}" aria-label="${t('Menge')}"></td><td class="muted">${esc(f.unit)}</td>
      <td><button class="iconbtn" data-act="fu-del" data-k="${i}" aria-label="${t('Entfernen')}">×</button></td></tr>`).join('');
  const ms = cs.methods.map((m, i) => { const mi = methodInfo(m); return `<span class="mchip" title="${esc(m.join(' · '))}">${esc(methodLabel(mi))} <span class="muted">${esc(mi.unit)}</span><button class="x" data-act="m-del" data-k="${i}" aria-label="${t('Methode entfernen')}">×</button></span>`; }).join('');
  return `<section class="card" style="display:flex;flex-direction:column;gap:14px">
    <div class="row" style="justify-content:space-between;align-items:flex-end">
      <label class="f" style="flex:1 1 280px">${t('Name')}<input type="text" id="csName" value="${esc(cs.name)}" maxlength="120"></label>
      <button class="btn primary" data-act="run-setup" ${cs.fus.length && cs.methods.length ? '' : 'disabled'}>${t('Rechnen')}</button>
    </div>
    ${cs.missing ? `<div class="warnbox"><b>${t('Hinweis')}</b><span>${t('{n} Produkt(e) dieser Rechnung gibt es im Projekt nicht mehr.', { n: cs.missing })}</span></div>` : ''}
    <div><div class="row" style="justify-content:space-between;margin-bottom:4px"><h3>${t('Produkte (funktionelle Einheiten) · {n}', { n: cs.fus.length })}</h3><button class="btn small" data-act="pick-fu">${t('+ Produkt')}</button></div>
      ${cs.fus.length ? `<div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Produkt')}</th><th>${t('Menge')}</th><th>${t('Einheit')}</th><th></th></tr></thead><tbody>${fus}</tbody></table></div>` : `<p class="empty">${t('Noch keine Produkte. Füge eines hinzu oder nimm es im Datenblatt mit «Zur Rechnung».')}</p>`}</div>
    <div><div class="row" style="justify-content:space-between;margin-bottom:6px"><h3>${t('Wirkungsmethoden · {n}', { n: cs.methods.length })}</h3><button class="btn small" data-act="pick-methods">${t('Methoden wählen')}</button></div>
      ${cs.methods.length ? `<div class="mchips">${ms}</div>` : `<p class="empty">${t('Noch keine Methode gewählt.')}</p>`}</div>
    <div class="row" style="justify-content:space-between"><p class="muted" style="font-size:12.5px;flex:1 1 280px">${t('Wird automatisch gespeichert und ist auch im Activity Browser unter «Calculation Setups» sichtbar.')}</p><button class="btn small danger" data-act="del-setup">${t('Rechnung löschen')}</button></div>
  </section>`;
}

function results() {
  const r = S.setupRes;
  if (!r) return '';
  const v = S.setupVerify;
  const check = v === 'running' ? `<span class="busy">${t('Gegenprobe mit bw2calc läuft …')}</span>`
    : v ? `<span class="check ${v.ok ? '' : 'bad'}" title="${t('{n} Werte mit bw2calc nachgerechnet, grösste relative Abweichung {d}', { n: v.checked, d: v.max_rel.toExponential(1) })}">${v.ok ? t('Gegenprobe mit bw2calc stimmt') : t('Gegenprobe weicht ab')} · ${t('{n} Werte', { n: v.checked })}</span>`
      : `<button class="btn small" data-act="verify-setup">${t('Gegenprobe mit bw2calc')}</button>`;
  const head = r.methods.map(m => { const mi = methodInfo(m.id); return `<th title="${esc(m.id.join(' · '))}">${esc(methodLabel(mi))}<br><span class="muted" style="font-weight:400">${esc(m.unit)}</span>${m.completed ? ` <span class="chip acc" title="${t('Ein Teil der Faktoren ist für Subkompartimente ergänzt (Schalter und Liste unter Ergebnis).')}">${t('mit ergänzten Faktoren')}</span>` : ''}</th>`; }).join('');
  const max = r.scores.map(col => Math.max(...col.map(Math.abs), 1e-300));
  const rows = r.fus.map((f, i) => `<tr><td>${esc(f.name)} <span class="muted">${esc(f.location)} · ${nf(f.amount)} ${esc(f.unit)}</span></td>${r.scores.map((col, j) =>
    `<td class="cell"><button class="cellbtn" data-act="open-result" data-k="${i}:${j}" title="${t('Details öffnen')}"><span class="num">${nf(col[i])}</span><span class="minibar"><i class="${col[i] < 0 ? 'neg' : col[i] === max[j] ? 'hot' : ''}" style="width:${Math.abs(col[i]) / max[j] * 100}%"></i></span></button></td>`).join('')}</tr>`).join('');
  return `<section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="justify-content:space-between"><h3>${t('Ergebnis · {f} × {m} in {ms} ms', { f: r.fus.length, m: r.methods.length, ms: nf(r.seconds * 1000) })}</h3><div class="row">${check}<button class="btn small" data-act="export-setup" data-k="xlsx" title="${t('Ergebnis als Excel-Datei, breit und lang')}">${t('Als Excel')}</button><button class="btn small" data-act="csv-setup">${t('Als CSV')}</button></div></div>
    <div class="tblwrap"><table class="tbl restbl"><thead><tr><th>${t('Produkt')}</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted" style="font-size:12.5px">${t('Balken: Anteil am grössten Wert derselben Methode. Klick auf eine Zahl öffnet die Details.')}</p>
  </section>`;
}
