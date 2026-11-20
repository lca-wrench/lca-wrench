// Other database (e.g. BAFU ↔ ecoinvent, or another ecoinvent version): the product of the result view, once with this project's background data and once with another
// background database (another project or this one). Each background dataset the product uses directly gets a
// counterpart: saved, by code, or suggested by name; the user confirms or changes it.
'use strict';
import { S, esc, nf, pct, explain, methodLabel, api, spellingNote, t } from '../core.js';
import { locList } from './daten.js';

export async function loadCw() {
  const c = S.cw;
  const usable = p => p && S.st.projects.some(x => x.name === p && !x.legacy);
  if (!usable(c.project)) {
    // default: a project whose name says ecoinvent, else another background database here, else the first other project
    const others = S.st.projects.filter(p => !p.legacy && p.name !== S.st.project);
    const own = S.st.databases.filter(d => d.role === 'background');
    c.project = others.find(p => /ecoinvent/i.test(p.name))?.name || (own.length > 1 ? S.st.project : others[0]?.name || S.st.project);
    c.targets = null;
  }
  if (!c.targets) {
    c.targets = await api(`/api/crosswalk/targets?project=${encodeURIComponent(c.project)}`);
    const dbs = c.targets.databases.map(d => d.name);
    if (!dbs.includes(c.database)) c.database = dbs.find(n => /ecoinvent/i.test(n)) || dbs.find(n => n !== S.fu.database) || dbs[0] || null;
    if (c.method && !c.targets.methods.some(m => JSON.stringify(m) === c.method)) c.method = '';
  }
}

const sign = x => x > 0 ? '+' : x < 0 ? '−' : '';
const ORIGIN = {
  user: () => ['ok', t('bestätigt')], file: () => ['ok', t('aus Datei')], same: () => ['ok', t('derselbe Datensatz')],
  code: () => ['ok', t('gleicher Code')], exact: () => ['ok', t('gleicher Name, Ort und Einheit')], missing: () => ['bad', t('gespeichert, fehlt aber')], unit: () => ['bad', t('Einheit passt nicht')],
};

function originChip(r) {
  if (r.origin === 'auto') return r.quality === 'good' ? `<span class="chip">${t('Vorschlag')}</span>` : `<span class="chip hot">${t('Vorschlag, unsicher')}</span>`;
  if (!r.origin || (r.origin === 'user' && !r.match)) return `<span class="chip hot">${r.origin ? t('ohne Gegenstück') : t('kein Vorschlag')}</span>`;
  const [k, l] = ORIGIN[r.origin]();
  return `<span class="chip ${k === 'bad' ? 'hot' : 'acc'}">${l}</span>`;
}

// a sector of an input-output table: found by ISIC class or only by words, and the price that converts the amount
function proxyNote(r) {
  if (!r.proxy || r.origin === 'user' || r.origin === 'file') return r.price && r.match ? `<br><span class="muted" style="font-size:12.5px">${t('Preis {p} EUR', { p: nf(r.price) })}</span>` : '';
  const how = { isic: t('Sektor über ISIC-Klasse'), rule: t('Sektor über Name und Kategorie'), category: t('Sektor nur über die Kategorie') }[r.proxy] || t('Sektor nur über Wörter im Namen');
  return `<br><span class="muted" style="font-size:12.5px">${how}${r.price && r.match ? ' · ' + t('Preis {p} EUR', { p: nf(r.price) }) : ''}</span>`;
}

function editor(r) {
  const c = S.cw;
  const cand = (r.candidates || []).concat(c.hits || []);
  const seen = new Set();
  const list = cand.filter(x => !seen.has(x.code) && seen.add(x.code)).map(x => `<div class="row" style="justify-content:space-between;gap:8px">
      <span><b>${esc(x.name)}</b> <span class="muted">${esc(x.location || '')} · ${esc(x.unit || '')}${x.product && x.product !== x.name ? ' · ' + esc(x.product) : ''}${x.score !== undefined ? ' · ' + t('Treffer {s}', { s: pct(x.score) }) : ''}</span></span>
      <button class="btn small" data-act="cw-pick" data-k="${esc(x.code)}" ${x.convertible === false ? `disabled title="${t('Einheit passt nicht')}"` : ''}>${t('Wählen')}</button></div>`).join('');
  return `<tr class="sel"><td colspan="6"><div style="display:flex;flex-direction:column;gap:8px;padding:6px 0">
    <div class="row" style="align-items:flex-end"><label class="f" style="flex:1 1 320px">${t('In «{db}» suchen', { db: esc(c.database) })}<input id="cwQ" value="${esc(c.q || '')}" placeholder="${t('z.B. electricity low voltage')}"></label>
      <label class="f" style="width:130px">${t('Ort')}<input id="cwLoc" list="cwLocList" value="${esc(c.loc ?? r.location ?? '')}" autocomplete="off"></label>${locList('cwLocList')}
      <button class="btn small" data-act="cw-search">${t('Suchen')}</button>
      <button class="btn small" data-act="cw-none">${t('Kein Gegenstück')}</button>
      ${r.origin === 'user' || r.origin === 'file' ? `<button class="btn small" data-act="cw-reset">${t('Zurück zum Vorschlag')}</button>` : ''}
      <button class="btn small" data-act="cw-close">${t('Schliessen')}</button></div>
    ${r.proxy ? `<div class="row" style="align-items:flex-end;gap:8px"><label class="f" style="width:220px">${t('Preis (EUR pro {unit})', { unit: esc(r.unit || '') })}<input id="cwPrice" inputmode="decimal" value="${r.price ?? ''}"></label>
      ${r.match || r.pending ? `<button class="btn small" data-act="cw-price">${t('Mit diesem Preis übernehmen')}</button>` : ''}
      <span class="muted" style="font-size:12.5px">${t('Der Preis rechnet die Menge in Geld um (EXIOBASE: Mio. €). Vorgabe: der Preis im Datensatz, falls vorhanden.')}</span></div>` : ''}
    ${list ? `${spellingNote(c.hits || [])}<div class="reslist" style="max-height:260px;overflow:auto">${list}</div>` : `<p class="muted">${t('Keine Kandidaten. Suche nach einem anderen Begriff.')}</p>`}
  </div></td></tr>`;
}

// what to ask the server for one level below a row: top level "r<row>", below "<parent>/<part>"
export function traceSpec(path) {
  const c = S.cw, cut = path.lastIndexOf('/');
  if (cut < 0) {
    const r = c.res.rows[+path.slice(1)];
    return { source_id: r.id, target_code: r.match.code, scale_a: r.amount, scale_b: r.match.amount };
  }
  const x = c.trace[path.slice(0, cut)].res.parts[+path.slice(cut + 1)];
  return { source_id: x.a.id, target_code: x.b.code, scale_a: x.a.amount, scale_b: x.b.amount };
}

const HOW = { same: () => t('derselbe Datensatz'), code: () => t('gleicher Code'), user: () => t('bestätigt'), name: () => t('nach Name') };
const toggle = (path, open) => `<button class="btn small" data-act="cw-trace" data-k="${path}" aria-expanded="${open}" title="${t('Eigene Inputs zeigen: eine Stufe tiefer in der Lieferkette')}">${open ? '▾' : '▸'}</button> `;

// the inputs of a pair of datasets, each with its part of the pair's difference; pairs open further
function traceRows(path, depth, max) {
  const n = S.cw.trace[path];
  if (!n) return '';
  const pad = `padding-left:${depth * 22}px`;
  if (n.loading) return `<tr><td></td><td colspan="6" style="${pad}"><span class="busy" role="status">${t('Lade die Inputs …')}</span></td></tr>`;
  if (n.error) return `<tr><td></td><td colspan="6" style="${pad}"><span class="muted">${esc(n.error)}</span></td></tr>`;
  const res = n.res, LIMIT = 10;
  const shown = n.all ? res.parts : res.parts.slice(0, LIMIT);
  const head = `<tr class="sub"><td></td><td colspan="6" style="${pad};font-size:12.5px" class="muted">${res.parts.length
    ? t('Inputs hier {a}, dort {b}, davon {p} gepaart. Die Anteile beziehen sich auf den Unterschied dieses Datensatzes.', { a: nf(res.counts.a), b: nf(res.counts.b), p: nf(res.counts.paired) })
    : t('Keine Unterschiede in den eigenen Inputs.')}</td></tr>`;
  const rows = shown.map((x, i) => {
    const p = `${path}/${i}`;
    const open = !!S.cw.trace[p];
    const name = s => `${esc(s.name)} <span class="muted">${esc(s.location || '')}</span>`;
    const what = x.kind === 'direct' ? t('<b>Eigene Emissionen</b> des Datensatzes')
      : x.kind === 'pair' ? `${name(x.a)}<br><span class="muted" style="font-size:12.5px">→ ${name(x.b)} · ${HOW[x.how]()}</span>`
      : x.kind === 'only_a' ? `${name(x.a)}<br><span class="muted" style="font-size:12.5px">→ ${t('nur hier, dort ohne Gegenstück')}</span>`
      : `<span class="muted">${t('nur dort:')}</span> ${name(x.b)}`;
    const ratio = x.ratio === null || x.ratio === undefined ? '–' : t('{x}×', { x: nf(x.ratio) });
    return `<tr class="sub">
      <td></td><td style="${pad}">${x.kind === 'pair' ? toggle(p, open) : ''}${what}</td>
      <td class="num nw" style="text-align:right">${sign(x.diff)}${nf(Math.abs(x.diff))}</td>
      <td><div class="share"><div class="t"><i class="${x.diff < 0 ? 'neg' : 'hot'}" style="width:${Math.abs(x.diff) / max * 100}%"></i></div><span>${x.share === null ? '' : pct(x.share)}</span></div></td>
      <td class="num nw" style="text-align:right">${ratio}</td>
      <td class="num nw" style="text-align:right">${pct(x.cumulative)}</td><td></td></tr>` + (open ? traceRows(p, depth + 1, max) : '');
  }).join('');
  const more = res.parts.length > shown.length
    ? `<tr class="sub"><td></td><td colspan="6" style="${pad}"><button class="btn small" data-act="cw-trace-all" data-k="${path}">${t('Alle {n} zeigen', { n: nf(res.parts.length) })}</button></td></tr>` : '';
  return head + rows + more;
}

// the datasets that make the difference between the two results, largest first
function drivers(w, ml) {
  const dr = w.drivers;
  if (!dr.parts.length) return `<p class="empty">${t('Kein Unterschied: beide Seiten geben dasselbe Ergebnis.')}</p>`;
  const max = Math.max(...dr.parts.map(x => Math.abs(x.diff)), 1e-300);
  const rows = dr.parts.map((x, n) => {
    const r = x.row === null ? null : w.rows[x.row];
    const what = x.kind === 'direct' ? t('<b>Direkte Emissionen</b> der eigenen Prozesse')
      : `<b>${esc(r.name)}</b> <span class="muted">${esc(r.location || '')}</span><br><span class="muted" style="font-size:12.5px">→ ${r.match ? `${esc(r.match.name)} ${esc(r.match.location || '')}` : t('ohne Gegenstück, zählt dort mit null')}</span>`;
    const ratio = x.ratio === null || x.ratio === undefined ? '–' : t('{x}×', { x: nf(x.ratio) });
    const path = `r${x.row}`, deeper = r && r.match && x.kind === 'dataset';
    return `<tr class="${x.cumulative - x.gross_share < 0.8 || S.cw.trace[path] ? '' : 'muted'}">
      <td class="num">${n + 1}</td><td>${deeper ? toggle(path, !!S.cw.trace[path]) : ''}${what}</td>
      <td class="num nw" style="text-align:right">${sign(x.diff)}${nf(Math.abs(x.diff))}</td>
      <td><div class="share"><div class="t"><i class="${x.diff < 0 ? 'neg' : 'hot'}" style="width:${Math.abs(x.diff) / max * 100}%"></i></div><span>${x.share === null ? '' : pct(x.share)}</span></div></td>
      <td class="num nw" style="text-align:right" title="${t('Wirkung pro Einheit dort geteilt durch hier')}">${ratio}</td>
      <td class="num nw" style="text-align:right">${pct(x.cumulative)}</td>
      <td class="nw">${r && r.origin !== 'same' ? `<button class="btn small" data-act="cw-fix" data-k="${x.row}">${t('Zuordnung prüfen')}</button>` : ''}</td></tr>`
      + (deeper ? traceRows(path, 1, max) : '');
  }).join('');
  return `<p class="muted" style="font-size:13px">${t('{n} von {all} Posten erklären 80 % der Unterschiede. Je grösser ein Posten, desto empfindlicher reagiert das Ergebnis auf die Wahl dieses Datensatzes: diese Zuordnungen zuerst prüfen. Mit ▸ siehst du, welche Inputs des Datensatzes den Unterschied machen, Stufe um Stufe.', { n: nf(dr.explain80), all: nf(dr.parts.length) })}</p>
    ${dr.offsetting ? `<p class="muted" style="font-size:13px">${t('Die Posten heben sich teilweise auf; ihre Anteile an der Differenz ergeben zusammen 100 %, einzelne können darüber liegen oder negativ sein.')}</p>` : ''}
    <div class="tblwrap"><table class="tbl"><thead><tr><th>#</th><th>${t('Datensatz hier → Gegenstück dort')}</th><th style="text-align:right">${t('Beitrag zur Differenz ({unit})', { unit: esc(w.b.unit || '') })}</th><th>${t('Anteil an der Differenz')}</th><th style="text-align:right">${t('Dort / hier')}</th><th style="text-align:right">${t('kumuliert')}</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

export function tCw() {
  const c = S.cw, w = c.res;
  const projects = S.st.projects.filter(p => !p.legacy);
  const methods = c.targets?.methods || [];
  const ml = m => methodLabel({ family: m[0], name: m.slice(1).join(' · ') });
  const form = `<section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="align-items:flex-end">
      <label class="f">${t('Projekt mit den anderen Daten')}<select id="cwProj" ${c.running ? 'disabled' : ''}>${projects.map(p => `<option value="${esc(p.name)}" ${p.name === c.project ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
      <label class="f">${t('Datenbank')}<select id="cwDb" ${c.running ? 'disabled' : ''}>${(c.targets?.databases || []).map(d => `<option value="${esc(d.name)}" ${d.name === c.database ? 'selected' : ''}>${esc(d.name)} · ${nf(d.count)}</option>`).join('')}</select></label>
      <label class="f" style="flex:1 1 260px;min-width:0">${t('Methode dort')}<select id="cwMethod" ${c.running ? 'disabled' : ''}><option value="">${t('passend zur Methode hier')}</option>${methods.map(m => `<option value="${esc(JSON.stringify(m))}" ${JSON.stringify(m) === c.method ? 'selected' : ''}>${esc(m.join(' · '))}</option>`).join('')}</select></label>
      <button class="btn primary" data-act="cw-run" ${c.database && !c.running ? '' : 'disabled'}>${w ? t('Neu rechnen') : t('Vergleichen')}</button>
    </div>
    ${c.targets && !c.targets.databases.length ? `<p class="empty">${t('In diesem Projekt gibt es keine Hintergrund-Datenbank. Lege eines mit ecoinvent an (Start → Neues Projekt) oder wähle ein anderes.')}</p>` : ''}
    ${c.running ? `<p class="busy" role="status">${t('Ordne zu und rechne … beim ersten Mal muss die andere Datenbank vorbereitet werden, bei ecoinvent eine bis zwei Minuten.')}</p>` : ''}
    ${c.error ? `<div class="warnbox"><b>${t('Hinweis')}</b><span>${esc(c.error)}</span></div>` : ''}
  </section>`;
  const intro = explain(t('Dasselbe Produkt, einmal mit den Hintergrunddaten dieses Projekts (z.B. BAFU 2026) und einmal mit einer anderen Datenbank (z.B. ecoinvent) gerechnet. Was das Produkt braucht, bleibt gleich: jeder Hintergrund-Datensatz, den es direkt verwendet, bekommt ein Gegenstück in der anderen Datenbank. Die Vorschläge kommen aus Name, Produkt, Ort und Einheit; prüfe sie, vor allem die grossen. Bestätigte Zuordnungen bleiben gespeichert und lassen sich als Datei im Format von sentier-mappings weitergeben.'));
  if (!w) return intro + form;
  const max = Math.max(...w.rows.map(r => Math.max(Math.abs(r.score_a), Math.abs(r.score_b || 0))), Math.abs(w.direct.score_a), Math.abs(w.direct.score_b), 1e-300);
  const bar = (x, cls) => `<div class="share"><div class="t"><i class="${cls}" style="width:${Math.abs(x) / max * 100}%"></i></div></div>`;
  const srcDb = w.rows[0]?.database;
  const rows = w.rows.map((r, i) => {
    const m = r.match;
    const line = `<tr class="${c.open === r.key ? 'sel' : ''}">
      <td><b>${esc(r.name)}</b> <span class="muted">${esc(r.location || '')}</span><br><span class="muted" style="font-size:12.5px">${nf(r.amount)} ${esc(r.unit || '')}${r.database !== srcDb ? ' · ' + esc(r.database) : ''}</span></td>
      <td class="num nw" style="text-align:right">${nf(r.score_a)}${bar(r.score_a, 'hot')}</td>
      <td>${m ? `<b>${esc(m.name)}</b> <span class="muted">${esc(m.location || '')}</span><br><span class="muted" style="font-size:12.5px">${nf(m.amount)} ${esc(m.unit || '')}${m.factor !== 1 ? ' · ' + t('Faktor {f}', { f: nf(m.factor) }) : ''}</span>` : r.pending ? `<b>${esc(r.pending.name)}</b> <span class="muted">${esc(r.pending.location || '')}</span><br><span class="chip hot">${t('Preis fehlt')}</span>` : `<span class="muted">${r.problem ? t('Einheit {u} passt nicht', { u: esc(r.problem) }) : '–'}</span>`} ${originChip(r)}${proxyNote(r)}</td>
      <td class="num nw" style="text-align:right">${m ? nf(r.score_b) : '–'}${m ? bar(r.score_b, '') : ''}</td>
      <td class="num nw" style="text-align:right">${m ? sign(r.score_b - r.score_a) + nf(Math.abs(r.score_b - r.score_a)) : ''}</td>
      <td class="nw">${r.origin === 'auto' && m ? `<button class="btn small" data-act="cw-ok" data-k="${i}" title="${t('Vorschlag bestätigen')}">✓</button> ` : ''}${r.origin !== 'same' ? `<button class="btn small" data-act="cw-edit" data-k="${i}">${t('Ändern')}</button>` : ''}</td></tr>`;
    return line + (c.open === r.key ? editor(r) : '');
  }).join('');
  const d = w.direct;
  const directRow = d.flows ? `<tr><td>${t('<b>Direkte Emissionen</b> der eigenen Prozesse ({n} Stoffe)', { n: d.flows })}${d.unmatched.length ? `<br><span class="muted" style="font-size:12.5px">${t('{n} Stoff(e) ohne Gegenstück: {names}', { n: d.unmatched.length, names: esc(d.unmatched.slice(0, 4).map(f => f.name).join(', ')) })}</span>` : ''}</td>
    <td class="num nw" style="text-align:right">${nf(d.score_a)}${bar(d.score_a, 'hot')}</td><td class="muted">${t('gleiche Stoffe, Faktoren der Methode dort')}</td>
    <td class="num nw" style="text-align:right">${nf(d.score_b)}${bar(d.score_b, '')}</td><td class="num nw" style="text-align:right">${sign(d.score_b - d.score_a)}${nf(Math.abs(d.score_b - d.score_a))}</td><td></td></tr>` : '';
  const good = w.rows.filter(r => r.origin === 'auto' && r.quality === 'good' && r.match).length;
  const warn = [
    !w.same_unit ? t('Die Methoden haben verschiedene Einheiten ({a} hier, {b} dort). Wähle oben die passende Methode.', { a: esc(w.a.unit || '?'), b: esc(w.b.unit || '?') }) : '',
    w.open_share > 0.0005 ? t('Ohne Gegenstück: Datensätze mit {p} des Ergebnisses hier. Dort zählen sie mit null.', { p: pct(w.open_share) }) : '',
    w.unsure_share > 0.0005 ? t('Unsichere Vorschläge: Datensätze mit {p} des Ergebnisses hier. Bitte prüfen.', { p: pct(w.unsure_share) }) : '',
  ].filter(Boolean);
  const pctDiff = w.a.score ? w.difference / Math.abs(w.a.score) : 0;
  const exp = `/api/crosswalk/export?source_database=${encodeURIComponent(srcDb || '')}&target_database=${encodeURIComponent(w.b.database)}`;
  return intro + form + `<section class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="row" style="justify-content:space-between;align-items:flex-end">
      <div><span class="eyebrow">${t('Hier')} · ${esc(srcDb || w.a.project)}</span><div class="kpi"><span class="big">${nf(w.a.score)}</span><span class="u">${esc(w.a.unit || '')}</span></div><span class="muted" style="font-size:12.5px">${esc(ml(w.a.method))}</span></div>
      <div><span class="eyebrow">${t('Dort')} · ${esc(w.b.database)}</span><div class="kpi"><span class="big">${nf(w.b.score)}</span><span class="u">${esc(w.b.unit || '')}</span></div><span class="muted" style="font-size:12.5px">${esc(ml(w.b.method))}</span></div>
      <div><span class="eyebrow">${t('Differenz')}</span><div class="kpi"><span class="big">${sign(w.difference)}${nf(Math.abs(w.difference))}</span><span class="u">${pct(pctDiff)}</span></div></div>
    </div>
    ${warn.map(x => `<div class="warnbox"><b>${t('Hinweis')}</b><span>${x}</span></div>`).join('')}
    <p class="muted" style="font-size:13px">${t('{n} Hintergrund-Datensätze direkt verwendet: {m} zugeordnet, davon {c} bestätigt oder eindeutig, {u} unsicher.', { n: nf(w.counts.inputs), m: nf(w.counts.matched), c: nf(w.counts.confirmed), u: nf(w.counts.unsure) })}</p>
    <div class="row">
      ${good ? `<button class="btn small" data-act="cw-ok-all">${t('Gute Vorschläge bestätigen ({n})', { n: good })}</button>` : ''}
      <a class="btn small" href="${exp}" download>${t('Zuordnung exportieren (JSON)')}</a>
      <label class="btn small" style="cursor:pointer">${t('Zuordnung laden (JSON)')}<input type="file" id="cwFile" accept=".json,application/json" hidden></label>
    </div>
    <nav class="tabs" role="tablist" aria-label="${t('Ansicht des Vergleichs')}">${[['datasets', t('Zuordnung')], ['drivers', t('Grösste Unterschiede')]].map(([k, l]) => `<button role="tab" aria-selected="${(c.view || 'datasets') === k}" data-act="cw-view" data-k="${k}">${l}</button>`).join('')}</nav>
    ${c.view === 'drivers' ? drivers(w, ml) : `<div class="tblwrap"><table class="tbl"><thead><tr><th>${t('Datensatz hier')}</th><th style="text-align:right">${t('Hier ({unit})', { unit: esc(w.a.unit || '') })}</th><th>${t('Gegenstück dort')}</th><th style="text-align:right">${t('Dort ({unit})', { unit: esc(w.b.unit || '') })}</th><th style="text-align:right">${t('Differenz')}</th><th></th></tr></thead>
    <tbody>${rows}${directRow}</tbody></table></div>`}
    <p class="muted" style="font-size:12.5px">${t('Hier gerechnet: {a}; Kontrolle mit der normalen Rechnung: {check}. Exportiert werden die bestätigten Zuordnungen, ecoinvent nur mit Code (wie in sentier-mappings).', { a: `<span class="num">${nf(w.a.score)}</span>`, check: `<span class="num">${nf(w.a.check)}</span>` })}</p>
  </section>`;
}
