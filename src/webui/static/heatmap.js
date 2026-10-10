// Crowd heatmap: how full a course usually is at each hour, by weekday and for special days
// (tournament, public holiday, vacation), from your own scrape history.

import { html, t, useState, Sheet, Select, Status, useLoad, api, query, weekdayShort, occupancyColor, round } from '/lib.js';

const WEEKDAY_ORDER = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
// Any Sunday: only to get the localized short weekday name.
const SUNDAY = '2026-10-04';

function weekdayLabel(name) {
  const index = WEEKDAY_ORDER.indexOf(name);
  const date = new Date(2026, 9, 4 + index);
  return weekdayShort(`${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`) || SUNDAY;
}

function Cell({ bucket, minSamples }) {
  if (!bucket) return html`<span class="hm-cell none" aria-label=${t('heatmap.legend.no_data')}>—</span>`;
  const pct = round(bucket.average * 100);
  const thin = bucket.samples < minSamples;
  return html`<span class=${'hm-cell' + (thin ? ' thin' : '')} style=${{ background: occupancyColor(bucket.average) }}
    title=${t('heatmap.cell_tip', { pct, n: bucket.samples })} role="img" aria-label=${t('heatmap.cell_tip', { pct, n: bucket.samples })}></span>`;
}

function Grid({ title, keys, labels, group, hours, minSamples }) {
  return html`
    <div class="hm-grid">
      <p class="lab">${title}</p>
      <div class="hm-row hm-head" style=${{ gridTemplateColumns: `44px repeat(${keys.length}, minmax(34px, 1fr))` }}>
        <span></span>${labels.map((label) => html`<span class="hd">${label}</span>`)}
      </div>
      ${hours.map((hour) => html`
        <div class="hm-row" style=${{ gridTemplateColumns: `44px repeat(${keys.length}, minmax(34px, 1fr))` }}>
          <span class="num hour">${hour}</span>
          ${keys.map((key) => html`<${Cell} bucket=${group[key] && group[key][hour]} minSamples=${minSamples} />`)}
        </div>`)}
    </div>`;
}

export function HeatmapSheet({ club, course, onClose }) {
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const [chosen, setChosen] = useState(course);
  const { data, error } = useLoad(() => api('/api/heatmap' + query({ ...ref, course: chosen })), [club.id, chosen]);
  const swatch = (color, text, style) => html`<span><span class="sw" style=${{ background: color, ...style }}></span>${text}</span>`;
  return html`<${Sheet} title=${t('heatmap.title', { course: chosen || '' })} onClose=${onClose} size="wide">
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<p class="dim">${t('heatmap.loading')}</p>`}
    ${data && data.courses && data.courses.length > 1 && html`
      <div class="field-row inline"><label for="hm-course">${t('course')}</label>
        <${Select} id="hm-course" value=${data.course} options=${data.courses.map((name) => ({ value: name, label: name }))} onChange=${setChosen} /></div>`}
    ${data && data.hours.length === 0 && html`<div class="empty small"><h3>${t('heatmap.no_data_yet')}</h3><p>${t('heatmap.no_data_hint')}</p></div>`}
    ${data && data.hours.length > 0 && html`
      <p class="hint">${t('heatmap.intro', { n: data.history_days })}</p>
      <div class="hm-wrap">
        <${Grid} title=${t('heatmap.by_weekday')} keys=${WEEKDAY_ORDER} labels=${WEEKDAY_ORDER.map(weekdayLabel)}
          group=${data.by_weekday} hours=${data.hours} minSamples=${data.min_samples} />
        <${Grid} title=${t('heatmap.special_days')} keys=${data.special_day_types} labels=${data.special_day_types.map((key) => t('heatmap.' + key))}
          group=${data.special_days} hours=${data.hours} minSamples=${data.min_samples} />
      </div>
      <div class="hm-legend">
        ${swatch('var(--green)', t('heatmap.legend.open'))}
        ${swatch('var(--orange)', t('heatmap.legend.mid'))}
        ${swatch('var(--red)', t('heatmap.legend.full'))}
        ${swatch('var(--seat)', t('heatmap.legend.thin'), { opacity: 0.35 })}
        <span class="dim">— ${t('heatmap.legend.no_data')}</span>
      </div>
      ${!data.has_country && html`<p class="hint">${t('heatmap.no_country')}</p>`}`}
  <//>`;
}
