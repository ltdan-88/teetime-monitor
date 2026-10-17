// Search: every open tee time of the next two weeks at the club, narrowed down by chips. The page filters and counts
// itself (src/webui/tools_api.py search_slots() sends everything that can still be played, with your own rules as flags),
// so a tap on a chip answers at once. The day strip is the calendar: one chip per day with its number of matches.

import {
  html, t, useState, useEffect, useMemo, useRef, shortClub, Sheet, Select, Status, Icon, useLoad, api, query,
  dayLabel, weekdayShort, WeatherHeads, WeatherCells,
} from '/lib.js';
import { PlayerNames } from '/overview.js';

const minutes = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
const isWeekend = (iso) => [0, 6].includes(new Date(iso + 'T12:00:00').getDay());
const inWindow = (time, window) => (!window.after || time >= window.after) && (!window.before || time <= window.before);
const hasWindow = (window) => !!(window.after || window.before);
/** The time-of-day chips: the hours they cover are their names, and one only appears when some tee time falls in it. */
const BUCKETS = [
  { key: 'b1', from: 0, to: 660, label: () => t('search.before_h', { h: 11 }) },
  { key: 'b2', from: 660, to: 840, label: () => '11–14' },
  { key: 'b3', from: 840, to: 1020, label: () => '14–17' },
  { key: 'b4', from: 1020, to: 1440, label: () => t('search.after_h', { h: 17 }) },
];

/** The filters of the club Search was last open for, kept while Search and the Heatmap trade places (the page forgets them
 *  when the window closes). */
let kept = null;
export const forgetSearch = () => { kept = null; };

/** The chips as they stand when Search opens: the rules of your Preferences on, nothing else. */
function defaults(data) {
  const mine = data.mine;
  return {
    kind: '', days: [], tod: [], courses: [], friends: false, open: false,
    mine: hasWindow(mine.weekday_window) || hasWindow(mine.weekend_window),
    dry: mine.weather.length > 0,
    gap: mine.gap_before > 0 || mine.gap_after > 0,
    spots: Math.min(4, Math.max(1, mine.min_open_spots || 1)),
  };
}

function passes(slot, f, mine, ignoreDays) {
  const weekend = isWeekend(slot.date);
  if (f.kind === 'weekdays' && weekend) return false;
  if (f.kind === 'weekend' && !weekend) return false;
  if (!ignoreDays && f.days.length && !f.days.includes(slot.date)) return false;
  if (f.courses.length && !f.courses.includes(slot.course)) return false;
  if (slot.open < f.spots) return false;
  if (f.friends && !slot.players.some((player) => player.friend)) return false;
  if (f.dry && slot.wet) return false;
  if (f.gap && !slot.gap_ok) return false;
  if (f.mine && !inWindow(slot.time, weekend ? mine.weekend_window : mine.weekday_window)) return false;
  if (f.tod.length) {
    const at = minutes(slot.time);
    if (!f.tod.some((key) => { const bucket = BUCKETS.find((b) => b.key === key); return at >= bucket.from && at < bucket.to; })) return false;
  }
  return true;
}

const anyOn = (f) => !!(f.kind || f.days.length || f.mine || f.dry || f.gap || f.tod.length || f.spots > 1 || f.friends || f.courses.length);

function Chip({ on, onClick, children, className = '', ...rest }) {
  return html`<button type="button" class=${'chip sf-chip ' + className} aria-pressed=${on} onClick=${onClick} ...${rest}>${children}</button>`;
}

/** The club choice that sits beside the tabs of Search and Heatmap: both look at the same club. */
export function ClubPick({ clubs, slug, onSlug }) {
  if (!slug || clubs.length < 2) return null;
  return html`<${Select} id="tool-club" value=${slug} aria-label=${t('club')} onChange=${onSlug}
    options=${clubs.map((entry) => ({ value: entry.slug, label: shortClub(entry.name) }))} />`;
}

function ResultRow({ slot, units, showHandicaps, showCourse, onMark }) {
  return html`
    <div class=${'res' + (slot.players.length || slot.booked ? '' : ' solo')} data-slot=${slot.date + ' ' + slot.time}>
      <span class="num res-time">${slot.time}</span>
      <span class="res-open">${t('search.open_spots', { n: slot.open })}</span>
      <span class="res-people"><${PlayerNames} slot=${{ players: slot.players, booked: slot.booked }} showHandicaps=${showHandicaps} /></span>
      <${WeatherCells} weather=${slot.weather} units=${units} flags=${slot.flags} />
      <span class="res-course dim">${showCourse ? slot.course : ''}</span>
      <span class="res-action">
        ${slot.booked_by_you
          ? html`<span class="chip mine"><${Icon} name="flag" size=${13} style="fill:currentColor" />${t('search.booked')}</span>`
          : html`<button class="btn small mark" onClick=${() => onMark(slot)} title=${t('search.book')} aria-label=${t('search.book')}><${Icon} name="flag" size=${14} /><span class="mark-text">${t('search.book')}</span></button>`}
      </span>
    </div>`;
}

export function SearchSheet({ club, clubs, units, showHandicaps, onClose, onMark, onPreferences, onSlug, refreshKey, tabs }) {
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const { data: loaded, loading, error, reload } = useLoad(() => api('/api/search/slots' + query(ref)), [club.id]);
  const data = loading ? null : loaded;
  const [f, setF] = useState(null);
  const forClub = useRef(null);
  useEffect(() => {
    if (data && forClub.current !== club.id) { forClub.current = club.id; setF(kept && kept.id === club.id ? kept.f : defaults(data)); }
  }, [data]);
  useEffect(() => { forClub.current = null; setF(null); }, [club.id]);
  useEffect(() => { if (f) kept = { id: club.id, f }; }, [f]);
  const first = useRef(true);
  useEffect(() => {  // a booking made from the results (or in Preferences) changes them
    if (first.current) { first.current = false; return; }
    reload();
  }, [refreshKey]);

  const set = (change) => setF((current) => ({ ...current, ...change })); // from the state as it is, so quick taps all count
  const flip = (key, value) => setF((current) => ({ ...current, [key]: current[key].includes(value) ? current[key].filter((x) => x !== value) : [...current[key], value] }));
  const view = useMemo(() => {
    if (!data || !f) return null;
    const counts = {};
    for (const slot of data.slots) if (passes(slot, f, data.mine, true)) counts[slot.date] = (counts[slot.date] || 0) + 1;
    const kept = data.slots.filter((slot) => passes(slot, f, data.mine, false));
    const groups = [];
    for (const slot of kept) {
      const last = groups[groups.length - 1];
      if (last && last.date === slot.date) last.rows.push(slot);
      else groups.push({ date: slot.date, rows: [slot] });
    }
    const buckets = BUCKETS.filter((b) => data.slots.some((slot) => minutes(slot.time) >= b.from && minutes(slot.time) < b.to));
    const best = Math.max(1, ...data.dates.filter((d) => (f.kind === 'weekdays' ? !isWeekend(d.date) : f.kind === 'weekend' ? isWeekend(d.date) : true)).map((d) => counts[d.date] || 0));
    return { counts, kept, groups, buckets, best };
  }, [data, f]);

  const mine = data && data.mine;
  const hasMine = !!(f && data && (hasWindow(mine.weekday_window) || hasWindow(mine.weekend_window) || mine.weather.length || mine.gap_before > 0 || mine.gap_after > 0));
  const clear = () => set({ kind: '', days: [], tod: [], courses: [], friends: false, mine: false, dry: false, gap: false, spots: 1 });
  const rules = f && ['mine', 'dry', 'gap'].filter((key) => (key === 'mine' ? hasWindow(mine.weekday_window) || hasWindow(mine.weekend_window) : key === 'dry' ? mine.weather.length > 0 : mine.gap_before > 0 || mine.gap_after > 0));
  const allRules = f && rules.every((key) => f[key]);
  const noRules = f && rules.every((key) => !f[key]);
  const toggleRules = () => set(Object.fromEntries(rules.map((key) => [key, !allRules])));
  const overrides = f && (f.tod.length || f.friends || f.courses.length || f.spots !== defaults(data).spots);
  const showCourse = !!(data && f && data.courses.length > 1 && f.courses.length !== 1); // (f is set one render after the data arrives)
  const darkNote = data && f && f.mine && f.kind !== 'weekend' && data.last_start && mine.weekday_window.after > data.last_start;
  const gapText = mine && t('search.tip.gap', { before: mine.gap_before, after: mine.gap_after });
  const weatherLabel = mine && (mine.weather.length === 1 && mine.weather[0] === 'rain' ? t('search.dry') : t('search.weather_ok'));

  const days = html`<span class="sf-grp"><span class="lab">${t('search.days')}</span>
    <${Chip} on=${f && f.kind === 'weekdays'} onClick=${() => set({ kind: f.kind === 'weekdays' ? '' : 'weekdays' })}>${t('search.weekday')}<//>
    <${Chip} on=${f && f.kind === 'weekend'} onClick=${() => set({ kind: f.kind === 'weekend' ? '' : 'weekend' })}>${t('search.weekend')}<//></span>`;

  return html`<${Sheet} title=${t('search.title')} onClose=${onClose} size="wide" fixed tabs=${tabs}
    tabsExtra=${html`<${ClubPick} clubs=${clubs} slug=${club.slug} onSlug=${onSlug} />`}>
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<${Status} kind="busy">${t('loading')}<//>`}
    ${data && f && html`
      <div class="sf">
        <div class="sf-line">
          ${days}
          ${hasMine && html`<${Chip} className="sf-rules" on=${allRules ? true : noRules ? false : 'mixed'} onClick=${toggleRules} title=${t('search.tip.rules')}>${t('search.rules')}<//>`}
          <button type="button" class="chip sf-chip sf-more" aria-expanded=${f.open} onClick=${() => set({ open: !f.open })}>${t('search.filters')}${overrides ? html`<i class="dot"></i>` : ''}<${Icon} name="down" size=${12} /></button>
        </div>
        <div class=${'sf-panel' + (f.open ? ' open' : '')}>
          ${hasMine && html`<span class="sf-grp"><span class="lab">${t('action.preferences')}</span>
            ${(hasWindow(mine.weekday_window) || hasWindow(mine.weekend_window)) && html`<${Chip} on=${f.mine} onClick=${() => set({ mine: !f.mine, tod: f.mine ? f.tod : [] })}
              title=${t('search.tip.times', { weekday: hasWindow(mine.weekday_window) ? `${mine.weekday_window.after || '…'}–${mine.weekday_window.before || '…'}` : '–', weekend: hasWindow(mine.weekend_window) ? `${mine.weekend_window.after || '…'}–${mine.weekend_window.before || '…'}` : '–' })}>${t('search.mine_times')}<//>`}
            ${mine.weather.length > 0 && html`<${Chip} on=${f.dry} onClick=${() => set({ dry: !f.dry })} title=${t('search.tip.dry')}>${weatherLabel}<//>`}
            ${(mine.gap_before > 0 || mine.gap_after > 0) && html`<${Chip} on=${f.gap} onClick=${() => set({ gap: !f.gap })} title=${gapText}>${t('search.gap', { n: Math.max(mine.gap_before, mine.gap_after) })}<//>`}
            <button type="button" class="icon-btn sf-gear" onClick=${onPreferences} aria-label=${t('search.prefs')} title=${t('search.prefs')}><${Icon} name="clock" size=${16} /></button></span>`}
          ${view.buckets.length > 0 && html`<span class="sf-grp"><span class="lab">${t('search.time')}</span>
            ${view.buckets.map((bucket) => html`<${Chip} key=${bucket.key} on=${f.tod.includes(bucket.key)} onClick=${() => { flip('tod', bucket.key); if (!f.tod.includes(bucket.key)) set({ mine: false }); }}>${bucket.label()}<//>`)}</span>`}
          <span class="sf-grp"><span class="lab">${t('search.spots')}</span>
            ${[1, 2, 3, 4].map((n) => html`<${Chip} key=${n} on=${f.spots === n} onClick=${() => set({ spots: n })}>${n === 4 ? '4' : n + '+'}<//>`)}
            <${Chip} className="star" on=${f.friends} onClick=${() => set({ friends: !f.friends })}>★ ${t('search.friends')}<//></span>
          ${data.courses.length > 1 && html`<span class="sf-grp"><span class="lab">${t('course')}</span>
            ${data.courses.map((course) => html`<${Chip} key=${course} on=${f.courses.includes(course)} onClick=${() => flip('courses', course)}>${course}<//>`)}</span>`}
          <div class="sf-foot"><button type="button" class="btn" onClick=${clear}>${t('search.clear_all')}</button>
            <button type="button" class="btn pri" onClick=${() => set({ open: false })}>${t('search.show_n', { n: view.kept.length })}</button></div>
        </div>
      </div>
      <div class="strip" role="group" aria-label=${t('search.days')}>
        ${data.dates.map((day) => {
          const count = view.counts[day.date] || 0;
          const off = (f.kind === 'weekdays' && isWeekend(day.date)) || (f.kind === 'weekend' && !isWeekend(day.date));
          const cls = 'sday' + (isWeekend(day.date) ? ' we' : '') + (!day.loaded ? ' noday' : count === 0 ? ' zero' : count * 2 < view.best ? ' mid' : '') + (off ? ' off' : '') + (day.date === data.today ? ' today' : '');
          return html`<button type="button" key=${day.date} class=${cls} aria-pressed=${f.days.includes(day.date)} onClick=${() => flip('days', day.date)}
            title=${day.loaded ? t('search.day_n', { n: count }) : t('search.no_sheet')} aria-label=${dayLabel(day.date) + ', ' + (day.loaded ? t('search.day_n', { n: count }) : t('search.no_sheet'))}>
            <span class="wd">${weekdayShort(day.date)}</span><span class="n">${Number(day.date.slice(8))}</span><span class="c">${off || !day.loaded ? '–' : count}</span></button>`;
        })}
      </div>
      ${darkNote && html`<p class="why">${t('search.dark', { after: mine.weekday_window.after, last: data.last_start })}</p>`}
      <div class="results scroll">
        <div class="res res-head"><span class="lab rcount">${t('search.count', { n: view.kept.length })}</span><${WeatherHeads} units=${units} />
          <span class="rclear">${anyOn(f) && html`<button type="button" class="btn small" onClick=${clear}>${t('search.clear')}</button>`}</span></div>
        ${view.groups.length === 0
          ? html`<div class="none">${t('search.none')}${anyOn(f) && html`<div><button type="button" class="btn small" onClick=${clear}>${t('search.clear')}</button></div>`}</div>`
          : html`${view.groups.map((group) => html`
              ${view.groups.length > 1 && html`<div class="dayhead">${dayLabel(group.date)}<small>${group.rows.length}</small></div>`}
              ${group.rows.map((slot) => html`<${ResultRow} key=${slot.date + slot.course + slot.time} slot=${slot} units=${units} showHandicaps=${showHandicaps} showCourse=${showCourse}
                onMark=${(picked) => onMark({ ...picked, ref })} />`)}`)}`}
      </div>`}
  <//>`;
}
