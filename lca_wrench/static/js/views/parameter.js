// Parameter: named values for formulas in own models (project, model, process), as in the Activity Browser.
'use strict';
import { S, esc, nf, explain, t } from '../core.js';

// one parameter row: name and value or formula are edited in place, the result is shown next to it
function row(p, scope, extra) {
  const key = esc(JSON.stringify({ scope, ...extra, name: p.name }));
  return `<tr><td><input type="text" class="pname" data-pn='${key}' value="${esc(p.name)}" title="${esc(p.name)}" aria-label="${t('Name')}" spellcheck="false"></td>
    <td><input type="text" class="pval ${p.formula ? 'formula' : ''}" data-pv='${key}' value="${esc(p.formula ?? String(+Number(p.amount).toPrecision(12)))}" aria-label="${t('Wert oder Formel')}" spellcheck="false"></td>
    <td class="num nw muted" style="text-align:right">${p.formula ? '= ' + nf(p.amount) : ''}</td>
    <td><button class="iconbtn" data-act="par-del" data-k='${key}' aria-label="${t('{name} löschen', { name: esc(p.name) })}" title="${t('Löschen')}">×</button></td></tr>`;
}

function table(list, scope, extra, emptyText) {
  const key = esc(JSON.stringify({ scope, ...extra }));
  const adding = S.par.adding === JSON.stringify({ scope, ...extra });
  return `<div class="tblwrap"><table class="tbl ptbl"><thead><tr><th>${t('Name')}</th><th>${t('Wert oder Formel')}</th><th style="text-align:right">${t('Ergebnis')}</th><th></th></tr></thead><tbody>
    ${list.map(p => row(p, scope, extra)).join('') || (adding ? '' : `<tr><td colspan="4" class="muted">${emptyText}</td></tr>`)}
    ${adding ? `<tr><td><input type="text" id="parNewName" class="pname" placeholder="${t('z.B. distanz_km')}" spellcheck="false"></td>
      <td><input type="text" id="parNewValue" class="pval" placeholder="${t('z.B. 12 oder 2 * distanz_km')}" spellcheck="false"></td>
      <td colspan="2"></td></tr>` : ''}
    </tbody></table></div>
    <div class="row" style="gap:6px">${adding
      ? `<button class="btn small primary" data-act="par-add-save" data-k='${key}'>${t('Anlegen')}</button><button class="btn small" data-act="par-add-cancel">${t('Abbrechen')}</button>`
      : `<button class="btn small" data-act="par-add" data-k='${key}'>${t('+ Parameter')}</button>`}</div>`;
}

export function vParameter() {
  const d = S.par.data;
  const models = S.st.databases.filter(x => x.role === 'model');
  const intro = explain(t('<b>Parameter</b> sind benannte Werte, mit denen Mengen in deinen Modellen als <b>Formel</b> rechnen, zum Beispiel <span class="formula">distanz_km * 0.12</span>. Ändert sich ein Parameter, rechnen alle Formeln sofort neu. Ein Name gilt in seinem Bereich: Prozess, dann Modell, dann Projekt. Gespeichert wird in Brightway, der Activity Browser sieht dieselben Parameter.'));
  if (!d) return intro + `<p class="busy">${t('Rechne …')}</p>`;
  const help = `<p class="muted" style="font-size:12.5px">${t('In Formeln: + − * / ** (hoch), Klammern und Funktionen wie min(), max(), exp(), log(), sqrt(). Eine Zahl (auch mit Komma, z.B. 2,5) ist ein fester Wert.')}</p>`;
  const proj = `<section class="card" style="display:flex;flex-direction:column;gap:10px"><h3>${t('Projekt-Parameter')}</h3>
    <p class="muted" style="font-size:13px">${t('Gelten in allen eigenen Modellen dieses Projekts.')}</p>${table(d.project, 'project', {}, t('Noch keine Projekt-Parameter.'))}</section>`;
  if (!models.length) return intro + (d.problem ? problem(d.problem) : '') + proj + help;
  const db = d.database;
  const modelCard = db ? `<section class="card" style="display:flex;flex-direction:column;gap:10px"><h3>${t('Modell-Parameter · {name}', { name: esc(db.name) })}</h3>
    <p class="muted" style="font-size:13px">${t('Gelten in allen Prozessen dieses Modells.')}</p>${table(db.params, 'database', { database: db.name }, t('Noch keine Modell-Parameter.'))}</section>` : '';
  // only processes that have parameters or formulas; the others are offered in a list to add one
  const addingTo = p => S.par.adding === JSON.stringify({ scope: 'activity', database: db.name, activity: p.id });
  const shown = d.processes.filter(p => p.params.length || p.formulas || addingTo(p));
  const others = d.processes.filter(p => !shown.includes(p));
  const addProc = others.length ? `<div class="row" style="gap:6px"><select id="parProc" aria-label="${t('Prozess')}">${others.map(p => `<option value="${p.id}">${esc(p.name)}${p.location ? ' · ' + esc(p.location) : ''}</option>`).join('')}</select>
      <button class="btn small" data-act="par-add-proc">${t('+ Prozess-Parameter')}</button></div>` : '';
  const procs = shown.map(p => `<div class="pproc"><div class="row" style="justify-content:space-between"><b>${esc(p.name)} <span class="muted" style="font-weight:400">${esc(p.location || '')}</span></b>
      <span class="muted" style="font-size:12.5px">${p.formulas ? t('{n} Menge(n) mit Formel', { n: p.formulas }) : ''} <button class="linkbtn" data-act="open-proc-from-par" data-k="${p.id}">${t('Datenblatt')}</button></span></div>
      ${table(p.params, 'activity', { database: db.name, activity: p.id }, t('Keine Prozess-Parameter.'))}</div>`).join('');
  const procCard = db ? `<section class="card" style="display:flex;flex-direction:column;gap:12px"><h3>${t('Prozess-Parameter')}</h3>
    <p class="muted" style="font-size:13px">${t('Gelten nur in ihrem Prozess. Formeln für einzelne Mengen trägst du im Datenblatt des Prozesses ein (ƒ neben der Menge).')}</p>${d.processes.length ? (procs || `<p class="muted">${t('Noch keine Prozess-Parameter.')}</p>`) + addProc : `<p class="empty">${t('Dieses Modell hat noch keine Prozesse.')}</p>`}</section>` : '';
  return `${intro}${d.problem ? problem(d.problem) : ''}
    <div class="dataview">
      <aside class="card plist" aria-label="${t('Modelle')}">
        <label class="f">${t('Modell')}<select id="parDb">${models.map(m => `<option value="${esc(m.name)}" ${m.name === S.mdb ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}</select></label>
        ${help}
      </aside>
      <div class="detail">${proj}${modelCard}${procCard}</div>
    </div>`;
}

const problem = text => `<div class="warnbox"><b>${t('Hinweis')}</b><span>${esc(text)}</span></div>`;
