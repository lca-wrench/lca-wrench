// Modellieren: own model databases, their processes and the live editor.
'use strict';
import { S, esc, explain, unitChoices, t, LANG } from '../core.js';
import { sheet } from '../sheet.js';
import { locList } from './daten.js';

// a copy of the model (or of all models) with its background inputs from another region
function moveForm() {
  const m = S.move;
  if (!m) return '';
  const many = S.st.databases.filter(d => d.role === 'model').length > 1;
  const plan = m.plan ? m.plan.map(p => `<div><b>${esc(p.db)}</b> → ${esc(p.db)} [${esc(p.target)}]: ${p.swaps.length ? t('{n} Datensatz/Datensätze wechseln', { n: p.swaps.length }) : t('nichts zu wechseln')}
      ${p.swaps.length ? `<ul class="movelist">${p.swaps.map(x => `<li>${esc(x.name)}: ${esc(x.from_location || '?')} → <b>${esc(x.location)}</b></li>`).join('')}</ul>` : ''}
      ${p.missing.length ? `<p class="muted" style="font-size:12.5px;margin:4px 0 0">${t('Ohne Gegenstück in der Region, bleiben wie sie sind: {list}', { list: p.missing.map(x => esc(x.name)).join(', ') })}</p>` : ''}</div>`).join('') : '';
  const any = m.plan && m.plan.some(p => p.swaps.length);
  return `<form id="moveForm" class="miniform">
    <p class="muted" style="font-size:13px;margin:0">${t('Legt eine Kopie an, deren Inputs aus Hintergrunddaten aus der gewählten Region kommen (gleicher Datensatz, anderer Ort; sonst die nächste Region darum herum). Das Original bleibt.')}</p>
    <label class="f">${t('Region')}<input type="text" id="moveLoc" list="moveLocList" value="${esc(m.location)}" placeholder="${t('z.B. DE, France, Europe')}" autocomplete="off">${locList('moveLocList')}</label>
    <label class="f">${t('Was wechseln')}<select id="moveScope"><option value="electricity" ${m.scope === 'electricity' ? 'selected' : ''}>${t('Nur Strom (Strommix)')}</option><option value="all" ${m.scope === 'all' ? 'selected' : ''}>${t('Alle Inputs, die es dort gibt')}</option></select></label>
    ${many ? `<label class="f">${t('Welche Modelle')}<select id="moveWhich"><option value="this" ${m.which === 'this' ? 'selected' : ''}>${t('Dieses Modell')}</option><option value="all" ${m.which === 'all' ? 'selected' : ''}>${t('Alle Modelle')}</option></select></label>` : ''}
    ${plan}
    <div class="row"><button class="btn" type="button" data-act="move-preview">${t('Vorschau')}</button>${any ? `<button class="btn primary" type="button" data-act="move-run">${t('Kopie anlegen')}</button>` : ''}<button class="btn" type="button" data-act="move-cancel">${t('Abbrechen')}</button></div></form>`;
}

export function vModell() {
  const dbs = S.st.databases.filter(d => d.role === 'model');
  const locked = dbs.some(d => d.name === S.mdb && !d.writable);
  if (!dbs.length && !S.newDb) {
    return `${explain(t('Ein <b>Modell</b> ist eine eigene Datenbank mit deinen Prozessen. Deine Prozesse verwenden Hintergrunddaten (z.B. Strom, Aluminium, Transporte) als Inputs. Hintergrunddaten selbst bleiben unverändert.'))}
    <section class="card" style="display:flex;flex-direction:column;gap:12px;max-width:640px">
      <h2>${t('Noch kein eigenes Modell')}</h2>
      <p class="muted">${S.st.example_available ? t('Lege ein leeres Modell an oder starte mit dem Beispiel, einem vereinfachten E-Bike, das pro Kilometer gerechnet wird.') : t('Lege ein leeres Modell an oder lade eines aus einer Excel-Datei.')}</p>
      <div class="row">${S.st.example_available ? `<button class="btn primary" data-act="example-model">${t('Beispielmodell anlegen')}</button>` : ''}<button class="btn ${S.st.example_available ? '' : 'primary'}" data-act="new-db">${t('Leeres Modell anlegen')}</button>${importButton()}</div>
    </section>`;
  }
  const newDb = S.newDb ? `<form id="newDbForm" class="miniform"><label class="f">${t('Name des Modells')}<input type="text" id="newDbName" required maxlength="80" placeholder="${t('z.B. Gartenstuhl')}"></label><div class="row"><button class="btn primary" type="submit">${t('Anlegen')}</button><button class="btn" type="button" data-act="new-db-cancel">${t('Abbrechen')}</button></div></form>` : '';
  const newProc = S.newProc ? `<form id="newProcForm" class="miniform">
      <label class="f">${t('Name')}<input type="text" id="npName" required maxlength="160" placeholder="${t('z.B. Rahmen, Aluminium')}"></label>
      <div class="row"><label class="f">${t('Einheit')}<select id="npUnit">${unitChoices().map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select></label>
      <label class="f">${t('Ort')}<input type="text" id="npLoc" value="CH" maxlength="40" style="width:80px"></label></div>
      <label class="f">${t('Beschreibung')}<textarea id="npDesc" rows="3" placeholder="${t('Was der Prozess umfasst, Quellen, Annahmen')}"></textarea></label>
      <div class="row"><button class="btn primary" type="submit">${t('Anlegen')}</button><button class="btn" type="button" data-act="new-proc-cancel">${t('Abbrechen')}</button></div></form>` : '';
  const procs = S.mprocs.length ? S.mprocs.map(p => `<button class="res" data-act="open-proc" data-k="${p.id}" aria-current="${p.id === S.msel}"><span>${esc(p.name)}</span><span class="meta">${esc(p.location)} · ${esc(p.unit)}</span></button>`).join('')
    : `<p class="empty">${t('Noch keine Prozesse in diesem Modell.')}</p>`;
  const j = S.st.journal || [];
  const journal = `<details class="haube journal" ${j.length ? '' : 'hidden'}><summary>${t('Verlauf · {n}', { n: j.length })}</summary>
    <ol class="jlist">${j.map(e => `<li><span>${esc(e.label)}</span><button class="btn small" data-act="undo-to" data-k="${e.n}" title="${t('Diesen und alle späteren Schritte zurücknehmen')}">${t('zurück bis hier')}</button></li>`).join('')}</ol></details>`;
  const editor = S.mact ? sheet(S.mact, S) : `<section class="card"><p class="empty">${S.mprocs.length ? t('Wähle links einen Prozess oder lege einen neuen an.') : t('Lege links den ersten Prozess an.')}</p></section>`;
  return `${explain(t('Deine Prozesse verwenden Hintergrunddaten als Inputs. Jede Änderung wird <b>sofort</b> gerechnet: Die Zahl oben zeigt die Wirkung mit der ganzen Lieferkette, der Balken neben jedem Input seinen Anteil. Mit «Rückgängig» oder ⌘Z / Ctrl+Z nimmst du Schritte zurück.'))}
  ${(S.st.model_errors || []).length ? `<div class="warnbox"><b>${t('Modell nicht lösbar')}</b><span>${S.st.model_errors.map(esc).join(' ')}</span></div>` : ''}
  <div class="dataview">
    <aside class="card plist" aria-label="${t('Modelle')}">
      <label class="f">${t('Modell')}<select id="mdbSel">${dbs.map(d => `<option value="${esc(d.name)}" ${d.name === S.mdb ? 'selected' : ''}>${esc(d.name)} · ${d.count} ${d.count === 1 ? t('Prozess') : t('Prozesse')}${d.writable ? '' : ' · ' + t('geschützt')}</option>`).join('')}</select></label>
      <div class="row tools">${locked ? '' : `<button class="btn small primary" data-act="new-proc" ${S.mdb ? '' : 'disabled'}>${t('+ Prozess')}</button>`}<button class="btn small" data-act="new-db">${t('+ Modell')}</button>${S.mdb && !locked ? `<button class="btn small danger" data-act="del-db" data-k="${esc(S.mdb)}" title="${t('Modell löschen')}">${t('Löschen')}</button>` : ''}</div>
      ${locked ? `<p class="muted" style="font-size:13px;margin:0">${t('Nicht in LCA Wrench angelegt (z.B. im Activity Browser): hier nur ansehen und rechnen. Ändern lässt es sich in einer Testkopie des Projekts.')}</p>` : ''}
      <div class="row tools">${S.mdb ? `<a class="btn small" href="/api/models/export?db=${encodeURIComponent(S.mdb)}&lang=${LANG}" download title="${t('Als Excel-Datei im Format von bw2io und Activity Browser')}">${t('Excel exportieren')}</a>` : ''}${importButton()}</div>
      ${S.mdb ? `<div class="row tools"><button class="btn small" data-act="move-db" title="${t('Kopie des Modells mit Strom (oder allen Inputs) aus einem anderen Land')}">${t('In andere Region …')}</button></div>` : ''}
      ${newDb}${newProc}${moveForm()}
      <div class="reslist" style="margin-top:6px">${procs}</div>
      ${journal}
    </aside>
    <div style="display:flex;flex-direction:column;gap:18px;min-width:0">${editor}</div>
  </div>`;
}

const importButton = () => `<label class="btn small" title="${t('Excel-Datei im Format von bw2io und Activity Browser als neues Modell laden')}">${t('Excel importieren')}<input type="file" id="xlsxIn" accept=".xlsx" hidden></label>`;
