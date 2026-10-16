// The club's tournament calendar as a month grid: days with a tournament carry dots, a tap on a day lists what is on
// (src/webui/data.py tournaments(), read from pc caddie's own calendar with the saved login).

import { html, t, useState, useMemo, Sheet, Status, Icon, useLoad, api, query, dayLabel, weekdayShort, language } from '/lib.js';

const pad = (n) => String(n).padStart(2, '0');
const iso = (year, month, day) => `${year}-${pad(month + 1)}-${pad(day)}`; // month is 0-based, like Date
const monday = (index) => weekdayShort(iso(2026, 9, 5 + index)); // 2026-10-05 is a Monday: only for the localized names

function stamp(date = new Date()) {
  return `${iso(date.getFullYear(), date.getMonth(), date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The weeks of a month, Monday first, as rows of ISO dates (null for the days outside it). */
export function monthWeeks(year, month) {
  const lead = (new Date(year, month, 1).getDay() + 6) % 7;
  const days = new Date(year, month + 1, 0).getDate();
  const cells = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => iso(year, month, i + 1))];
  while (cells.length % 7) cells.push(null);
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
    <span class="tn-chips">
      ${item.holes && html`<span class="chip">${t('tournaments.holes', { n: item.holes })}</span>`}
      <span class="chip">${item.guests ? t('tournaments.guests') : t('tournaments.members_only')}</span>
      <span class=${'chip' + (item.register_open ? ' mine' : '')}>${registration(item, now)}</span>
    </span>
    <span class="tn-actions">
      ${canShow && html`<button class="btn small" onClick=${() => onShow(item.date)}>${t('tournaments.tee_sheet')}</button>`}
      <a class="btn small" href=${item.url} target="_blank" rel="noopener noreferrer">${t('tournaments.details')}</a>
    </span>
  </li>`;
}

export function TournamentsSheet({ club, knownDays, onShowDay, onClose }) {
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const { data, error } = useLoad(() => api('/api/tournaments' + query(ref)), [club.id]);
  const today = new Date();
  const [shown, setShown] = useState({ year: today.getFullYear(), month: today.getMonth() });
  const [picked, setPicked] = useState(null);
  const list = (data && data.tournaments) || [];
  const byDay = useMemo(() => {
    const map = {};
    for (const item of list) (map[item.date] = map[item.date] || []).push(item);
    return map;
  }, [data]);
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
  return html`<${Sheet} title=${t('tournaments.title')} onClose=${onClose} size="medium">
    <p class="hint">${t('tournaments.intro')}</p>
    ${!data && !error && html`<${Status} kind="busy">${t('tournaments.loading')}<//>`}
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${data && data.problem && html`<${Status} kind="error">${t('tournaments.' + data.problem)}<//>`}
    ${data && html`
      <div class="tn-nav">
        <button class="btn small tn-step" aria-label=${t('tournaments.prev')} onClick=${() => step(-1)}><${Icon} name="chevron" size=${18} class="flip" /></button>
        <h3 class="tn-month" aria-live="polite">${monthName}</h3>
        <button class="btn small tn-step" aria-label=${t('tournaments.next')} onClick=${() => step(1)}><${Icon} name="chevron" size=${18} /></button>
      </div>
      <div class="tn-cal" role="group" aria-label=${monthName}>
        ${[0, 1, 2, 3, 4, 5, 6].map((i) => html`<span class="tn-wd" key=${i}>${monday(i)}</span>`)}
        ${monthWeeks(shown.year, shown.month).flat().map((day, i) => {
          if (!day) return html`<span class="tn-cell blank" key=${'b' + i}></span>`;
          const events = byDay[day] || [];
          const cls = 'tn-cell' + (events.length ? ' has' : '') + (day === picked ? ' on' : '') + (day === todayIso ? ' today' : '') + (day < todayIso ? ' past' : '');
          const label = dayLabel(day) + (events.length ? ': ' + events.map((item) => item.name).join(', ') : '');
          if (!events.length) return html`<span class=${cls} key=${day} aria-label=${label}>${Number(day.slice(8))}</span>`;
          return html`<button class=${cls} key=${day} aria-pressed=${day === picked} aria-label=${label} onClick=${() => setPicked(day === picked ? null : day)}>
            <span>${Number(day.slice(8))}</span><span class="tn-dots" aria-hidden="true">${events.slice(0, 3).map((_, d) => html`<i key=${d}></i>`)}</span></button>`;
        })}
      </div>
      <h3 class="tn-head">${picked ? dayLabel(picked) : monthName}</h3>
      <div class="tn-scroll">
      ${rows.length === 0 && html`<div class="empty small"><p>${list.length === 0 && !data.problem ? t('tournaments.none') : t('tournaments.none_month', { month: monthName })}</p></div>`}
      <ul class="tn-list">
        ${rows.map((item) => html`<${Item} key=${item.id} item=${item} now=${now} canShow=${(knownDays || []).includes(item.date)} onShow=${onShowDay} />`)}
      </ul></div>`}
  <//>`;
}
