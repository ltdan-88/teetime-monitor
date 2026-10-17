// Crowd heatmap: how full a course usually is at each hour, by weekday and for special days
// (tournament, public holiday, vacation), from your own scrape history.

import { html, t, useState, useEffect, Sheet, Select, Status, useLoad, api, query, weekdayShort, occupancyColor, round } from '/lib.js';
import { ClubPick } from '/search.js';

const SUNDAY_FIRST = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONDAY_FIRST = [...SUNDAY_FIRST.slice(1), 'Sunday'];  // the week as imperial (US) units count it starts on Sunday, otherwise on Monday
// Any Sunday: only to get the localized short weekday name.
const SUNDAY = '2026-10-04';

function weekdayLabel(name) {
  const index = SUNDAY_FIRST.indexOf(name);
  const date = new Date(2026, 9, 4 + index);
  return weekdayShort(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`) || SUNDAY;
}

function Cell({ bucket, minSamples, onPick, what }) {
  if (!bucket) return html`<span class="hm-cell none" aria-label=${t('heatmap.legend.no_data')}>—</span>`;
  const pct = round(bucket.average * 100);
  const thin = bucket.samples < minSamples;
  const text = t('heatmap.cell_tip', { pct, n: bucket.samples });
  return html`<span class=${'hm-cell' + (thin ? ' thin' : '')} style=${{ background: occupancyColor(bucket.average) }} onClick=${() => onPick(what + ' — ' + text)}
    title=${text} role="img" aria-label=${text}></span>`;
}

function Grid({ title, keys, labels, group, hours, minSamples, onPick }) {
  if (!keys.some((key) => group[key] && Object.keys(group[key]).length)) {
    return html`<div class="hm-grid"><p class="lab">${title}</p><p class="hm-none">${t('heatmap.no_data_yet')}</p></div>`;
  }
  return html`
    <div class="hm-grid">
      <p class="lab">${title}</p>
      <div class="hm-row hm-head" style=${{ gridTemplateColumns: `2.75rem repeat(${keys.length}, minmax(2.1rem, 1fr))` }}>
        <span></span>${labels.map((label) => html`<span class="hd">${label}</span>`)}
      </div>
      ${hours.map((hour) => html`
        <div class="hm-row" style=${{ gridTemplateColumns: `2.75rem repeat(${keys.length}, minmax(2.1rem, 1fr))` }}>
          <span class="num hour">${hour}</span>
          ${keys.map((key, index) => html`<${Cell} bucket=${group[key] && group[key][hour]} minSamples=${minSamples} onPick=${onPick} what=${labels[index] + ' ' + hour} />`)}
        </div>`)}
    </div>`;
}

export function HeatmapSheet({ club, clubs, course, units, onClose, onSlug, tabs }) {
  const weekdays = units === 'imperial' ? SUNDAY_FIRST : MONDAY_FIRST;
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const [chosen, setChosen] = useState(course);
  useEffect(() => { setChosen(course); }, [club.id]); // another club: its own course (the server falls back to the club's default)
  const { data, error } = useLoad(() => api('/api/heatmap' + query({ ...ref, course: chosen })), [club.id, chosen]);
  const [picked, setPicked] = useState(null); // the numbers of the cell last tapped (no hover on a touch screen)
  const swatch = (color, text, style) => html`<span><span class="sw" style=${{ background: color, ...style }}></span>${text}</span>`;
  return html`<${Sheet} title=${t('heatmap.title', { course: chosen || '' })} onClose=${onClose} size="wide" tall tabs=${tabs} tabsExtra=${html`<${ClubPick} clubs=${clubs} slug=${club.slug} onSlug=${onSlug} />`}>
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<p class="dim">${t('heatmap.loading')}</p>`}
    ${data && data.courses && data.courses.length > 1 && html`
      <div class="field-row inline"><label for="hm-course">${t('course')}</label>
        <${Select} id="hm-course" value=${data.course} options=${data.courses.map((name) => ({ value: name, label: name }))} onChange=${setChosen} /></div>`}
    ${data && data.hours.length === 0 && html`<div class="empty small"><h3>${t('heatmap.no_data_yet')}</h3><p>${t('heatmap.no_data_hint')}</p></div>`}
    ${data && data.hours.length > 0 && html`
      <p class="hint">${t('heatmap.intro', { n: data.history_days })}</p>
      <div class="hm-wrap">
        <${Grid} title=${t('heatmap.by_weekday')} keys=${weekdays} labels=${weekdays.map(weekdayLabel)}
          group=${data.by_weekday} hours=${data.hours} minSamples=${data.min_samples} onPick=${setPicked} />
        <${Grid} title=${t('heatmap.special_days')} keys=${data.special_day_types} labels=${data.special_day_types.map((key) => t('heatmap.' + key))}
          group=${data.special_days} hours=${data.hours} minSamples=${data.min_samples} onPick=${setPicked} />
      </div>
      <p class="hm-picked" role="status">${picked || t('heatmap.tap_hint')}</p>
      <div class="hm-legend">
        ${swatch('var(--green)', t('heatmap.legend.open'))}
        ${swatch('var(--orange)', t('heatmap.legend.mid'))}
        ${swatch('var(--red)', t('heatmap.legend.full'))}
        ${swatch('var(--seat)', t('heatmap.legend.thin'), { opacity: 0.35 })}
        <span class="dim">— ${t('heatmap.legend.no_data')}</span>
      </div>
`}
  <//>`;
}
