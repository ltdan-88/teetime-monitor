// The club's tournament calendar as a month grid: days with a tournament carry dots, a tap on a day lists what is on
// (src/webui/data.py tournaments(), read from pc caddie's own calendar with the saved login).

import { html, t, useState, useMemo, Sheet, Select, Status, Icon, useLoad, api, query, dayLabel, weekdayShort, language } from '/lib.js';

const pad = (n) => String(n).padStart(2, '0');
const iso = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`; // month is 0-based, like Date
const firstDay = (units) => (units === 'imperial' ? 0 : 1); // the week starts on Sunday with imperial units, else on Monday
const dayName = (index, units) => weekdayShort(iso(2026, 9, 4 + firstDay(units) + index)); // 2026-10-04 is a Sunday: only for the localized names

function stamp(date = new Date()) {
  return `${iso(date.getFullYear(), date.getMonth(), date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The weeks of a month, Monday first (Sunday first with `units` imperial), as rows of ISO dates (null for the days outside it). */
export function monthWeeks(year, month, units) {
  const lead = (new Date(year, month, 1).getDay() - firstDay(units) + 7) % 7;
  const days = new Date(year, month + 1, 0).getDate();
  const cells = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => iso(year, month, i + 1))];
  while (cells.length % 7) cells.push(null);
  while (cells.length < 42) cells.push(null);  // always six rows: the calendar keeps its height from month to month
  return Array.from({ length: cells.length / 7 }, (_, row) => cells.slice(row * 7, row * 7 + 7));
}

function registration(item, now) {
  if (item.register_open) {
    return item.deadline ? t('tournaments.reg_open_until', { when: `${dayLabel(item.deadline.slice(0, 10))} ${item.deadline.slice(11, 16)}`.trim() }) : t('tournaments.reg_open');
  }
  return item.deadline && item.deadline < now ? t('tournaments.reg_closed') : t('tournaments.reg_later');
}

function Item({ item, now, canShow, onShow }) {
  return html`<li class="tn-item">
    <span class="tn-when"><b>${dayLabel(item.date)}</b>${item.time && html` <span class="num">${item.time}</span>`}</span>
    <span class="tn-name">${item.name}${item.subtitle && html`<span class="dim"> · ${item.subtitle}</span>`}</span>
    <span class="tn-actions">
      ${canShow && html`<button class="icon-btn tn-act" aria-label=${t('tournaments.tee_sheet')} title=${t('tournaments.tee_sheet')} onClick=${() => onShow(item.date)}><${Icon} name="teesheet" size=${20} /></button>`}
      <a class="icon-btn tn-act" href=${item.url} target="_blank" rel="noopener noreferrer" aria-label=${t('tournaments.details')} title=${t('tournaments.details')}><${Icon} name="external" size=${20} /></a>
    </span>
    <span class="tn-chips">
      ${item.holes && html`<span class="chip">${t('tournaments.holes', { n: item.holes })}</span>`}
      <span class="chip">${item.guests ? t('tournaments.guests') : t('tournaments.members_only')}</span>
      <span class=${'chip' + (item.register_open ? ' mine' : '')}>${registration(item, now)}</span>
    </span>
  </li>`;
}

/** A labelled row of on/off chips; any number may be on, none on means no filter. `value` is the list that is on,
 *  `onFlip(v)` turns one on or off. */
function Choice({ label, value, options, onFlip }) {
  return html`<span class="tn-choice" role="group" aria-label=${label}>
    <span class="tn-choice-label">${label}</span>
    ${options.map((option) => html`<button key=${option.value} class="chip tn-pick" aria-pressed=${value.includes(option.value)} onClick=${() => onFlip(option.value)}>${option.label}</button>`)}
  </span>`;
}

const NO_FILTER = { holes: [], who: [], open: false };

export function TournamentsSheet({ club, clubs, units, knownDays, focusDate, onShowDay, onClose }) {
  const [slug, setSlug] = useState(club.slug); // the club shown: the open one to begin with, any saved club after
  const ref = { slug };
  const { data: loaded, loading, error } = useLoad(() => api('/api/tournaments' + query(ref)), [slug]);
  const data = loading ? null : loaded; // never the previous club's calendar under the new club's name
  const today = new Date();
  const start = focusDate ? new Date(Number(focusDate.slice(0, 4)), Number(focusDate.slice(5, 7)) - 1, 1) : today;
  const [shown, setShown] = useState({ year: start.getFullYear(), month: start.getMonth() });
  const [picked, setPicked] = useState(focusDate || null);
  const [filter, setFilter] = useState(NO_FILTER);
  const all = (data && data.tournaments) || [];
  const holeSizes = [...new Set(all.map((item) => item.holes).filter(Boolean))].sort((a, b) => a - b);
  const mixedWho = all.some((item) => item.guests) && all.some((item) => !item.guests);
  const list = all.filter((item) => (!filter.holes.length || filter.holes.includes(item.holes)) && (!filter.who.length || filter.who.includes(item.guests ? 'guests' : 'members')) && (!filter.open || item.register_open));
  const filtered = filter.holes.length > 0 || filter.who.length > 0 || filter.open;
  const byDay = useMemo(() => {
    const map = {};
    for (const item of list) (map[item.date] = map[item.date] || []).push(item);
    return map;
  }, [data, filter]);
  // the days with a tee sheet: for the open club the ones it loaded, for another club the same stretch of days
  const sheetDays = knownDays || [];
  const shown_ = (date) => (slug === club.slug ? sheetDays.includes(date) : sheetDays.length > 0 && date >= sheetDays[0] && date <= sheetDays[sheetDays.length - 1]);
  const chooseClub = (next) => { setSlug(next); setFilter(NO_FILTER); setPicked(null); };
  const now = stamp();
  const todayIso = now.slice(0, 10);
  const first = iso(shown.year, shown.month, 1);
  const monthName = new Date(shown.year, shown.month, 1).toLocaleDateString(language(), { month: 'long', year: 'numeric' });
  const inMonth = list.filter((item) => item.date.slice(0, 7) === first.slice(0, 7));
  const rows = picked ? byDay[picked] || [] : inMonth;
  const step = (by) => {
    const moved = new Date(shown.year, shown.month + by, 1);
    setShown({ year: moved.getFullYear(), month: moved.getMonth() });
    setPicked(null);
  };
  // from the state as it is now, not as it was drawn: two quick taps both count
  const flip = (key, v) => setFilter((current) => ({ ...current, [key]: current[key].includes(v) ? current[key].filter((x) => x !== v) : [...current[key], v] }));
  return html`<${Sheet} title=${t('tournaments.title')} onClose=${onClose} size="medium" tall>
    ${!data && !error && html`<${Status} kind="busy">${t('tournaments.loading')}<//>`}
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${data && data.problem && html`<${Status} kind="error">${t('tournaments.' + data.problem)}<//>`}
    <div class="tn-filters" role="group" aria-label=${t('tournaments.filters')}>
        ${clubs.length > 1 && html`<${Select} id="tn-club" value=${slug} aria-label=${t('club')} options=${clubs.map((entry) => ({ value: entry.slug, label: entry.name }))} onChange=${chooseClub} />`}
        ${data && holeSizes.length > 1 && html`<${Choice} label=${t('tournaments.holes_label')} value=${filter.holes} onFlip=${(v) => flip('holes', v)}
          options=${holeSizes.map((n) => ({ value: n, label: String(n) }))} />`}
        ${data && mixedWho && html`<${Choice} label=${t('tournaments.who_label')} value=${filter.who} onFlip=${(v) => flip('who', v)}
          options=${[{ value: 'guests', label: t('tournaments.guests') }, { value: 'members', label: t('tournaments.members_only') }]} />`}
        ${data && html`<button class="chip tn-pick" aria-pressed=${filter.open} onClick=${() => setFilter((current) => ({ ...current, open: !current.open }))}>${t('tournaments.reg_open')}</button>`}
        ${data && filtered && html`<button class="link-btn" onClick=${() => setFilter(NO_FILTER)}>${t('tournaments.clear_filters')}</button>`}
    </div>
    ${data && html`
      <div class="tn-split">
        <div class="tn-left">
          <div class="tn-nav">
            <button class="btn small tn-step" aria-label=${t('tournaments.prev')} onClick=${() => step(-1)}><${Icon} name="chevron" size=${18} /></button>
            <h3 class="tn-month" aria-live="polite">${monthName}</h3>
            <button class="btn small tn-step" aria-label=${t('tournaments.next')} onClick=${() => step(1)}><${Icon} name="chevron" size=${18} /></button>
          </div>
          <div class="tn-cal" role="group" aria-label=${monthName}>
            ${[0, 1, 2, 3, 4, 5, 6].map((i) => html`<span class="tn-wd" key=${i}>${dayName(i, units)}</span>`)}
            ${monthWeeks(shown.year, shown.month, units).flat().map((day, i) => {
              if (!day) return html`<span class="tn-cell blank" key=${'b' + i}></span>`;
              const events = byDay[day] || [];
              const cls = 'tn-cell' + (events.length ? ' has' : '') + (day === picked ? ' on' : '') + (day === todayIso ? ' today' : '') + (day < todayIso ? ' past' : '');
              const label = dayLabel(day) + (events.length ? ': ' + events.map((item) => item.name).join(', ') : '');
              if (!events.length) return html`<span class=${cls} key=${day} aria-label=${label}>${Number(day.slice(8))}</span>`;
              return html`<button class=${cls} key=${day} aria-pressed=${day === picked} aria-label=${label} onClick=${() => setPicked(day === picked ? null : day)}>
                <span>${Number(day.slice(8))}</span><span class="tn-dots" aria-hidden="true">${events.slice(0, 3).map((_, d) => html`<i key=${d}></i>`)}</span></button>`;
            })}
          </div>
        </div>
        <div class="tn-right">
          <div class="tn-scroll">
            ${rows.length === 0 && html`<div class="empty small"><p>${filtered ? t('tournaments.none_filtered') : all.length === 0 && !data.problem ? t('tournaments.none') : t('tournaments.none_month', { month: picked ? dayLabel(picked) : monthName })}</p></div>`}
            <ul class="tn-list">
              ${rows.map((item) => html`<${Item} key=${item.id} item=${item} now=${now} canShow=${shown_(item.date)} onShow=${(date) => onShowDay(date, slug)} />`)}
            </ul>
          </div>
        </div>
      </div>`}
  <//>`;
}
