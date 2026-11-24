// Daten: search all databases and show a data sheet.
'use strict';
import { S, esc, explain, isModelDb, spellingNote, unitGroups, t } from '../core.js';
import { sheet } from '../sheet.js';

// free text with suggestions: the locations of the open databases, most frequent first
export const locList = id => `<datalist id="${id}">${(S.sopts?.locations || []).slice(0, 300).map(l => `<option value="${esc(l)}">`).join('')}</datalist>`;

export function vDaten() {
  const tech = S.st.databases.filter(d => d.role === 'background' || d.role === 'model');
  const list = S.results.length ? spellingNote(S.results) + S.results.map(r => `<button class="res" data-act="open-here" data-k="${r.id}" aria-current="${r.id === S.sel}"${r.comment ? ` title="${esc(r.comment)}"` : ''}><span>${esc(r.name)}</span><span class="meta">${esc(r.location)}${r.region ? ` <span class="chip" title="${t('Für {loc} gibt es diesen Datensatz nicht, das ist der nächste', { loc: esc(r.region) })}">${t('statt {loc}', { loc: esc(r.region) })}</span>` : ''} · ${esc(r.unit)}${isModelDb(r.database) ? ' · ' + t('Modell') : ''}</span></button>`).join('')
    : `<p class="empty">${S.q ? t('Kein Treffer. Versuch einen englischen Begriff.') : t('Suche auf Englisch, zum Beispiel «electricity», «concrete», «transport» oder «aluminium». Mit Ort sucht LCA Wrench auch in den Regionen darum herum (CH → Europa → global), mit Einheit nur Prozesse in dieser Einheit, z.B. Energie ohne Kraftwerke.')}</p>`;
  const detail = S.act ? sheet(S.act, S) : `<section class="card"><p class="empty">${t('Wähle einen Prozess aus der Liste.')}</p></section>`;
  return `${explain(t('Links suchst du in allen Datenbanken. Rechts siehst du einen Prozess: <b>Inputs</b> kommen aus anderen Prozessen, <b>Emissionen</b> gehen direkt in die Umwelt. Die Balken zeigen, wie viel jeder Posten zur Wirkung beiträgt, inklusive allem, was dahinter in der Lieferkette steckt.'))}
  <div class="dataview">
    <aside class="card plist" aria-label="${t('Suche')}">
      <form id="searchForm" class="reslist" style="gap:6px">
        <input type="search" id="q" placeholder="${t('z.B. electricity')}" value="${esc(S.q)}" aria-label="${t('Prozess suchen')}">
        <select id="dbf" aria-label="${t('Datenbank')}"><option value="">${t('Alle Datenbanken')}</option>${tech.map(d => `<option value="${esc(d.name)}" ${d.name === S.dbf ? 'selected' : ''}>${esc(d.name)}</option>`).join('')}</select>
        <input type="text" id="loc" list="locList" value="${esc(S.loc)}" placeholder="${t('Ort, z.B. CH oder Germany')}" aria-label="${t('Ort')}" autocomplete="off">${locList('locList')}
        <select id="unit" aria-label="${t('Einheit')}"><option value="">${t('Alle Einheiten')}</option>${Object.entries(unitGroups()).filter(([k]) => !S.sopts || S.sopts.units.includes(k)).map(([k, l]) => `<option value="${k}" ${k === S.unit ? 'selected' : ''}>${l}</option>`).join('')}</select>
        <button class="btn primary" type="submit">${t('Suchen')}</button>
      </form>
      <div class="reslist" style="margin-top:8px">${list}</div>
    </aside>
    <div class="detail">${detail}</div>
  </div>`;
}
