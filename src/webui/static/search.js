// Search: every open tee time of the overview's days at the club, narrowed down by chips. The page filters and counts
// itself (src/webui/tools_api.py search_slots() sends everything that can still be played, with your own rules as flags),
// so a tap on a chip answers at once. The day strip is the calendar: one chip per day with its number of matches.

import {
  html, t, useState, useEffect, useLayoutEffect, useMemo, useRef, Sheet, Status, Condition, Icon, useLoad, api, query,
  dayLabel, weekdayShort, WeatherHeads, WeatherCells, tempTone, temperature, WEATHER_SITE_NAMES,
} from '/lib.js';
import { PlayerNames, WhoChip, WhoList } from '/overview.js';

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
    days: [], tod: [], friends: false, open: false,
    mine: hasWindow(mine.weekday_window) || hasWindow(mine.weekend_window),
    dry: mine.weather.length > 0,
    gap: mine.gap_before > 0 || mine.gap_after > 0,
    spots: Math.min(4, Math.max(1, mine.min_open_spots || 1)),
  };
}

function passes(slot, f, mine, ignoreDays) {
  const weekend = isWeekend(slot.date);
  if (!ignoreDays && f.days.length && !f.days.includes(slot.date)) return false;
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

const sameChips = (a, b) => ['mine', 'dry', 'gap', 'spots', 'friends'].every((key) => a[key] === b[key])
  && ['days', 'tod'].every((key) => a[key].length === b[key].length && a[key].every((x) => b[key].includes(x)));
const anyOn = (f) => !!(f.days.length || f.mine || f.dry || f.gap || f.tod.length || f.spots > 1 || f.friends);

export function Chip({ on, onClick, children, className = '', ...rest }) {
  return html`<button type="button" class=${'chip sf-chip ' + className} aria-pressed=${on} onClick=${onClick} ...${rest}>${children}</button>`;
}

/** The seats as squares, as on the tee sheet: taken grey, a friend's yellow, yours in the accent, free ones empty. */
function seatSquares(slot) {
  const friend = slot.players.some((player) => player.friend);
  return Array.from({ length: slot.capacity > 0 ? slot.capacity : 4 }, (_, i) => {
    const taken = i < slot.booked;
    const cls = 'seat' + (taken ? (slot.booked_by_you && i === 0 ? ' mine' : friend && i === 0 ? ' friend' : ' taken') : '');
    return html`<span class=${cls}></span>`;
  });
}

/** A day's heading: its weather (icon, high and low, as in the days of the overview); its count is in the strip. */
function DayHead({ day, units, weatherUrl, weatherSite }) {
  const label = weatherUrl && t('weather_site.open', { name: WEATHER_SITE_NAMES[weatherSite] });
  const icon = day.code != null && html`<${Condition} code=${day.code} size=${18} />`;
  return html`<div class="dayhead">${dayLabel(day.date)}${icon && weatherUrl ? html`<a class="wx-link" href=${weatherUrl} target="_blank" rel="noopener noreferrer" title=${label} aria-label=${label}>${icon}</a>` : icon}
    ${day.high != null && html`<span class="dh-temp num" title=${t('tip.temp')}><span style=${tempTone(day.high)}>${temperature(day.high, units)}°</span> / <span style=${tempTone(day.low)}>${temperature(day.low, units)}°</span></span>`}
</div>`;
}

function ResultRow({ slot, units, showHandicaps, onMark }) {
  const [whoOpen, setWhoOpen] = useState(false); // where the names do not fit, a chip with the count opens them (as in the days)
  const who = { players: slot.players, booked: slot.booked };
  return html`
    <div class="res" data-slot=${slot.date + ' ' + slot.time}>
      <span class="num res-time">${slot.time}</span>
      <span class="res-open seats" role="img" title=${t('search.open_spots', { n: slot.open })} aria-label=${t('search.open_spots', { n: slot.open })}>${seatSquares(slot)}</span>
      <span class="res-people"><${PlayerNames} slot=${who} showHandicaps=${showHandicaps} /></span>
      <${WhoChip} slot=${who} open=${whoOpen} onToggle=${() => setWhoOpen((v) => !v)} />
      ${whoOpen && html`<${WhoList} slot=${who} showHandicaps=${showHandicaps} />`}
      <${WeatherCells} weather=${slot.weather} units=${units} flags=${slot.flags} wind=${false} />
      <span class="res-action">
        ${slot.booked_by_you
          ? html`<span class="chip mine"><${Icon} name="flag" size=${13} style="fill:currentColor" />${t('search.booked')}</span>`
          : html`<button class="btn small mark" onClick=${() => onMark(slot)} title=${t('search.book')} aria-label=${t('search.book')}><${Icon} name="flag" size=${16} /></button>`}
      </span>
    </div>`;
}

export function SearchSheet({ club, startDay, weatherUrl, weatherSite, course: tabCourse, pageCourse, onCourse, units, showHandicaps, onClose, onMark, onPreferences, refreshKey, tabs }) {
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const { data: loaded, loading, error, reload } = useLoad(() => api('/api/search/slots' + query({ ...ref, page_course: pageCourse || '' })), [club.id]);
  // one course at a time, the one of the course tab: the tab you chose, else where Search starts (Preferences)
  const course = loaded && (loaded.courses.includes(tabCourse) ? tabCourse : loaded.start_course);
  const data = loading ? null : loaded;
  const [f, setF] = useState(null);
  const fRef = useRef(null); // the filters as they are this instant: a tap, then straight to the Heatmap tab, must not lose it
  const commit = (next) => { fRef.current = next; kept = { id: club.id, f: next }; setF(next); };
  const forClub = useRef(null);
  useEffect(() => {
    if (data && forClub.current !== club.id) { forClub.current = club.id; const base = kept && kept.id === club.id ? kept.f : defaults(data); commit(startDay ? { ...base, days: [startDay] } : base); }
  }, [data]);
  useEffect(() => { forClub.current = null; fRef.current = null; setF(null); }, [club.id]);
  // A row whose names do not fit shows the player chip instead (the names stay in place, unseen, to be measured again)
  const resultsRef = useRef(null);
  const fitNames = () => {
    const box = resultsRef.current;
    if (!box) return;
    for (const row of box.querySelectorAll('.res:not(.res-head)')) {
      const people = row.querySelector('.res-people');
      row.classList.toggle('tight', !!people && people.scrollWidth > people.clientWidth + 1);
    }
  };
  useLayoutEffect(fitNames);
  useEffect(() => {
    const box = resultsRef.current;
    if (!box || !window.ResizeObserver) return undefined;
    const watch = new ResizeObserver(() => requestAnimationFrame(fitNames));
    watch.observe(box);
    return () => watch.disconnect();
  }, [!!(data && f)]);
  const first = useRef(true);
  useEffect(() => {  // a booking made from the results (or in Preferences) changes them
    if (first.current) { first.current = false; return; }
    reload();
  }, [refreshKey]);

  const set = (change) => commit({ ...fRef.current, ...change }); // from the filters as they are, so quick taps all count
  const flip = (key, value) => { const current = fRef.current; commit({ ...current, [key]: current[key].includes(value) ? current[key].filter((x) => x !== value) : [...current[key], value] }); };
  const view = useMemo(() => {
    if (!data || !f) return null;
    const counts = {};
    const here = data.slots.filter((slot) => !course || slot.course === course);
    for (const slot of here) if (passes(slot, f, data.mine, true)) counts[slot.date] = (counts[slot.date] || 0) + 1;
    const kept = here.filter((slot) => passes(slot, f, data.mine, false));
    const groups = [];
    for (const slot of kept) {
      const last = groups[groups.length - 1];
      if (last && last.date === slot.date) last.rows.push(slot);
      else groups.push({ date: slot.date, rows: [slot] });
    }
    const buckets = BUCKETS.filter((b) => here.some((slot) => minutes(slot.time) >= b.from && minutes(slot.time) < b.to));
    const best = Math.max(1, ...data.dates.map((d) => counts[d.date] || 0));
    return { counts, kept, groups, buckets, best };
  }, [data, f, course]);

  const mine = data && data.mine;
  const days = data ? Object.fromEntries(data.dates.map((day) => [day.date, day])) : {};
  const hasMine = !!(f && data && (hasWindow(mine.weekday_window) || hasWindow(mine.weekend_window) || mine.weather.length || mine.gap_before > 0 || mine.gap_after > 0));
  const clear = () => set({ days: [], tod: [], friends: false, mine: false, dry: false, gap: false, spots: 1 });
  const reset = () => commit({ ...defaults(data), open: f.open }); // back to your Preferences in one tap
  const atMine = !!(f && sameChips(f, defaults(data)));
  const clearButton = f && anyOn(f) && html`<button type="button" class="icon-btn danger sf-clear" onClick=${clear} aria-label=${t('search.clear')} title=${t('search.clear')}><${Icon} name="trash" size=${18} /></button>`;
  const resetButton = f && !atMine && html`<button type="button" class="icon-btn sf-reset" onClick=${reset} aria-label=${t('search.reset')} title=${t('search.reset')}><${Icon} name="reset" size=${18} /></button>`;
  const actions = html`<span class="sf-actions">${clearButton}${resetButton}</span>`; // after the last of the filters, wherever that is
  // how many of the filters behind the phone's Filter button are narrowing the list (days and weekdays are on the line itself)
  const hidden = f ? f.tod.length + [f.spots > 1, f.friends, f.mine, f.dry, f.gap].filter(Boolean).length : 0;
  const darkNote = data && f && f.mine && data.dates.some((d) => !isWeekend(d.date)) && data.last_start && mine.weekday_window.after > data.last_start;
  const gapText = mine && t('search.tip.gap', { before: mine.gap_before, after: mine.gap_after });
  const weatherLabel = mine && (mine.weather.length === 1 && mine.weather[0] === 'rain' ? t('search.dry') : t('search.weather_ok'));

  return html`<${Sheet} title=${t('search.title')} onClose=${onClose} size="wide" fixed tabs=${tabs}
    courseTabs=${loaded && loaded.courses.map((name) => ({ key: name, label: name, on: name === course, onSelect: () => onCourse(name) }))}>
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<${Status} kind="busy">${t('loading')}<//>`}
    ${data && f && html`
      <div class="sf">
        <div class="sf-line">
          <button type="button" class="chip sf-chip sf-more" aria-expanded=${f.open} onClick=${() => set({ open: !f.open })}>${t('search.filters')}${hidden > 0 && html`<span class="sf-count">${hidden}</span>`}<${Icon} name="down" size=${12} /></button>
          <span class="sf-line-actions">${clearButton}${resetButton}</span>
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
            ${[1, 2, 3, 4].map((n) => html`<${Chip} key=${n} on=${f.spots === n} disabled=${n === 4 && f.friends} onClick=${() => set({ spots: n })}>${n === 4 ? '4' : n + '+'}<//>`)}
            <${Chip} className="star" on=${f.friends} onClick=${() => set({ friends: !f.friends, ...(!fRef.current.friends && fRef.current.spots === 4 ? { spots: 1 } : {}) })}>★ ${t('search.friends')}<//>
            ${actions}</span>
          <div class="sf-foot">
            <button type="button" class="btn pri" onClick=${() => set({ open: false })}>${t('search.show_n', { n: view.kept.length })}</button></div>
        </div>
      </div>
      <div class=${'strip' + (data.dates.length > 7 ? ' many' : '')} role="group" aria-label=${t('search.days')} style=${{ '--n': data.dates.length }}>
        ${data.dates.map((day) => {
          const count = view.counts[day.date] || 0;
          const cls = 'sday' + (isWeekend(day.date) ? ' we' : '') + (!day.loaded ? ' noday' : count === 0 ? ' zero' : count * 2 < view.best ? ' mid' : '') + (day.date === data.today ? ' today' : '');
          return html`<button type="button" key=${day.date} class=${cls} aria-pressed=${f.days.includes(day.date)} onClick=${() => flip('days', day.date)}
            title=${day.loaded ? t('search.day_n', { n: count }) : t('search.no_sheet')} aria-label=${dayLabel(day.date) + ', ' + (day.loaded ? t('search.day_n', { n: count }) : t('search.no_sheet'))}>
            <span class="wd">${weekdayShort(day.date)}</span><span class="n">${Number(day.date.slice(8))}</span><span class="c">${!day.loaded ? '–' : count}</span></button>`;
        })}
      </div>
      ${darkNote && html`<p class="why">${t('search.dark', { after: mine.weekday_window.after, last: data.last_start })}</p>`}
      <div class="results scroll" ref=${resultsRef}>
        <div class="res res-head"><span class="lab rcount">${t('search.count', { n: view.kept.length })}</span><${WeatherHeads} units=${units} wind=${false} />
          </div>
        ${view.groups.length === 0
          ? html`<div class="none">${t('search.none')}<div class="none-actions">${clearButton}${resetButton}</div></div>`
          : html`${view.groups.map((group) => html`<section class="daygroup" key=${group.date}>
              <${DayHead} day=${days[group.date] || { date: group.date }} units=${units} weatherUrl=${weatherUrl} weatherSite=${weatherSite} />
              ${group.rows.map((slot) => html`<${ResultRow} key=${slot.date + slot.course + slot.time} slot=${slot} units=${units} showHandicaps=${showHandicaps}
                onMark=${(picked) => onMark({ ...picked, ref })} />`)}</section>`)}`}
      </div>`}
  <//>`;
}
