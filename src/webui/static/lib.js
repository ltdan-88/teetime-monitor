// Shared pieces of the web UI: strings, formatting, API calls, icons and the small controls.
// Preact + htm are vendored (vendor/htm-preact.js); there is no build step.

import { html, render, useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from '/vendor/htm-preact.js';
export { html, render, useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo };

// ---------------------------------------------------------------- API

export async function api(path, options) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    /* not JSON */
  }
  if (!response.ok) {
    const error = new Error(payload && payload.error ? String(payload.error) : 'HTTP ' + response.status);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export const post = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

/** A query string from an object, leaving out empty values. */
export function query(params) {
  const parts = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
  return parts.length ? '?' + parts.join('&') : '';
}

// ---------------------------------------------------------------- strings (EN / DE)
// The page's own strings live in /strings.json; the app's catalog (i18n.py, the same words the
// terminal app uses: settings labels, heatmap legend, weekday names ...) fills in the rest.

let LANG = 'en';
let LOCAL = { en: {}, de: {} };
let SERVER = {};

export const language = () => LANG;

export async function loadStrings(code) {
  LANG = code === 'de' ? 'de' : 'en';
  const [local, server] = await Promise.all([api('/strings.json'), api('/api/strings')]);
  LOCAL = local;
  SERVER = server.strings || {};
}

export function t(key, vars) {
  let text = (LOCAL[LANG] && LOCAL[LANG][key]) || SERVER[key] || (LOCAL.en && LOCAL.en[key]) || key;
  if (vars) for (const name of Object.keys(vars)) text = text.split('{' + name + '}').join(String(vars[name]));
  return text;
}

// ---------------------------------------------------------------- formatting

export const round = (n) => Math.round(n);
export const temperature = (c, units) => round(units === 'imperial' ? (c * 9) / 5 + 32 : c);
export const windSpeed = (kph, units) => round(units === 'imperial' ? kph / 1.609344 : kph);
export const amount = (mm, units) => (units === 'imperial' ? (mm / 25.4).toFixed(2) + 'in' : mm.toFixed(1) + 'mm');
export const hcpText = (value) => (LANG === 'de' ? value.toFixed(1).replace('.', ',') : value.toFixed(1));

export function parseDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

const strip = (text) => text.replace(/\./g, '');

/** "Sat 3 Oct": weekday, day, month, in the app's language. */
export function dayLabel(iso) {
  const date = parseDate(iso);
  const weekday = strip(date.toLocaleDateString(LANG, { weekday: 'short' }));
  const month = strip(date.toLocaleDateString(LANG, { month: 'short' }));
  return `${weekday} ${date.getDate()} ${month}`;
}

export function weekdayShort(iso) {
  return strip(parseDate(iso).toLocaleDateString(LANG, { weekday: 'short' }));
}

/** The lock badge's "Wed 21:00", read as written (the club's own offset). */
export function opensText(locked) {
  const isoDate = locked.opens_at.slice(0, 10);
  const weekday = weekdayShort(isoDate);
  return locked.hour_known ? `${weekday} ${locked.opens_at.slice(11, 16)}` : `${weekday} ${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}.`;
}

export function updatedText(iso) {
  if (!iso) return t('updated_never');
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return t('updated_just_now');
  if (minutes < 60) return t('updated_minutes', { n: minutes });
  if (minutes < 60 * 48) return t('updated_hours', { n: Math.round(minutes / 60) });
  return t('updated_days', { n: Math.round(minutes / 1440) });
}

export function conditionKind(code) {
  if (code == null) return null;
  if (code === 0) return 'sun';
  if (code <= 2) return 'partly';
  if (code === 3) return 'cloud';
  if (code === 45 || code === 48) return 'fog';
  if (code >= 51 && code <= 57) return 'drizzle';
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return 'rain';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'snow';
  if (code >= 95) return 'storm';
  return null;
}

export const occupancyColor = (ratio) => (ratio == null ? 'var(--faint)' : ratio >= 1 ? 'var(--red)' : ratio >= 0.5 ? 'var(--orange)' : 'var(--green)');

// ---------------------------------------------------------------- scale
// Everything is sized in rem, so the whole page scales with the root font size. 80% is the default
// (the browser's own zoom, Ctrl +/-, works on top of it); Settings > Scale changes it, per browser.

export const SCALES = [70, 80, 90, 100, 110, 125];
export const DEFAULT_SCALE = 80;

export function getScale() {
  try {
    const saved = Number(localStorage.getItem('tm_scale'));
    return SCALES.includes(saved) ? saved : DEFAULT_SCALE;
  } catch (_) {
    return DEFAULT_SCALE;
  }
}

export function setScale(percent) {
  try {
    localStorage.setItem('tm_scale', String(percent));
  } catch (_) {
    /* private window: applies for this page only */
  }
  applyScale(percent);
}

export function applyScale(percent = getScale()) {
  document.documentElement.style.fontSize = (16 * percent) / 100 + 'px';
}

// ---------------------------------------------------------------- icons

const CLOUD = 'M7 17a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 8.2 3.9 3.9 0 0 1 17 17z';
const RAIN_CLOUD = 'M7 13a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 4.2 3.9 3.9 0 0 1 17 13z';
const ICONS = {
  chevron: html`<path d="M9 6l6 6-6 6" />`,
  down: html`<path d="M6 9l6 6 6-6" />`,
  refresh: html`<path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" />`,
  info: html`<circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8v.1" />`,
  star: html`<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 17l-5.2 2.7 1-5.9-4.3-4.1 5.9-.8z" />`,
  moon: html`<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />`,
  flag: html`<path d="M5 21V4M5 4h11l-2 4 2 4H5" />`,
  lock: html`<rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" />`,
  thermo: html`<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z" />`,
  drop: html`<path d="M12 3.5s6 6.2 6 10.5a6 6 0 0 1-12 0c0-4.3 6-10.5 6-10.5z" />`,
  wind: html`<path d="M3 9h10a3 3 0 1 0-3-3M3 15h14a3 3 0 1 1-3 3M3 12h7" />`,
  sunrise: html`<path d="M4 18h16M7 18a5 5 0 0 1 10 0M12 4v4M9.5 6.5L12 4l2.5 2.5" />`,
  sunset: html`<path d="M4 18h16M7 18a5 5 0 0 1 10 0M12 8V4M9.5 5.5L12 8l2.5-2.5" />`,
  sun: html`<circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />`,
  partly: html`<circle cx="8.5" cy="8" r="2.8" /><path d="M8.5 2.5v1.3M3 8h1.3M4.6 4.1l.9.9M12.4 4.1l-.9.9" /><path d="M8 19a3.6 3.6 0 0 1-.4-7.2A5 5 0 0 1 17 11a3.5 3.5 0 0 1 0 8z" />`,
  cloud: html`<path d=${CLOUD} />`,
  fog: html`<path d=${RAIN_CLOUD} /><path d="M5 16.5h14M7 20h10" />`,
  drizzle: html`<path d=${RAIN_CLOUD} /><path d="M9 16.5v.1M13 17.5v.1M16.5 16.5v.1M11 20.5v.1M15 21v.1" />`,
  rain: html`<path d=${RAIN_CLOUD} /><path d="M8 16l-1 3M12 16l-1 3M16 16l-1 3" />`,
  snow: html`<path d=${RAIN_CLOUD} /><path d="M8 17v.1M12 18.5v.1M16 17v.1M10 21v.1M14 21.5v.1" />`,
  storm: html`<path d=${RAIN_CLOUD} /><path d="M12.5 13l-2 4h3l-2 4" />`,
  search: html`<circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" />`,
  grid: html`<rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" />`,
  users: html`<circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.6-3.6 3.3-5.5 6.5-5.5s5.9 1.9 6.5 5.5" /><circle cx="17.5" cy="9" r="2.5" /><path d="M17 14.6c2.6.1 4.4 1.6 4.9 4.4" />`,
  sliders: html`<path d="M4 7h9M17 7h3M4 17h3M11 17h9" /><circle cx="15" cy="7" r="2" /><circle cx="9" cy="17" r="2" />`,
  gear: html`<circle cx="12" cy="12" r="3" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" />`,
  plus: html`<path d="M12 5v14M5 12h14" />`,
  close: html`<path d="M6 6l12 12M18 6L6 18" />`,
  check: html`<path d="M5 12.5l4.5 4.5L19 7.5" />`,
  trash: html`<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" />`,
  palette: html`<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.8 1.8-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.1 0-.9.8-1.7 1.7-1.7H17a4 4 0 0 0 4-4c0-4.4-4-8.3-9-8.3z" /><circle cx="7.5" cy="11" r="1" /><circle cx="10" cy="7.5" r="1" /><circle cx="14.5" cy="7.5" r="1" />`,
  alert: html`<path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17v.1" />`,
};

export function Icon({ name, size = 20, ...rest }) {
  // sized in rem, like everything else, so Settings > Scale scales the icons too
  const side = size / 16 + 'rem';
  return html`<svg width=${side} height=${side} viewBox="0 0 24 24" aria-hidden="true" ...${rest}>${ICONS[name]}</svg>`;
}

export function Condition({ code, size = 24 }) {
  const kind = conditionKind(code);
  if (!kind) return null;
  return html`<span class="cond" title=${t('cond.' + kind)}><${Icon} name=${kind} size=${size} /></span>`;
}

// ---------------------------------------------------------------- small controls

export function useEscape(handler) {
  useLayoutEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        handler();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handler]);
}

/** A modal sheet over the page: Escape or a click on the dim area closes it. */
export function Sheet({ title, onClose, size = 'medium', fixed = false, children, footer }) {
  useEscape(onClose);
  const ref = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    if (ref.current) ref.current.focus();
    return () => previous && previous.focus && previous.focus();
  }, []);
  return html`
    <div class="scrim" onMouseDown=${(event) => event.target === event.currentTarget && onClose()}>
      <div class=${'sheet ' + size + (fixed ? ' tall' : '')} role="dialog" aria-modal="true" aria-label=${title} tabindex="-1" ref=${ref}>
        <header class="sheet-head">
          <h2>${title}</h2>
          <button class="icon-btn" onClick=${onClose} aria-label=${t('close')} title=${t('close')}><${Icon} name="close" size=${18} /></button>
        </header>
        <div class=${'sheet-body' + (fixed ? ' fixed' : '')}>${children}</div>
        ${footer && html`<footer class="sheet-foot">${footer}</footer>`}
      </div>
    </div>`;
}

export function Select({ id, value, options, onChange, ...rest }) {
  return html`
    <span class="select">
      <select id=${id} value=${value} onChange=${(event) => onChange(event.target.value)} ...${rest}>
        ${options.map((option) => html`<option value=${option.value} selected=${String(option.value) === String(value)}>${option.label}</option>`)}
      </select>
      <${Icon} name="down" size=${14} />
    </span>`;
}

export function Switch({ id, checked, onChange }) {
  return html`<input type="checkbox" class="switch" id=${id} checked=${!!checked} onChange=${(event) => onChange(event.target.checked)} />`;
}

const HOURS = Array.from({ length: 17 }, (_, i) => String(i + 5).padStart(2, '0')); // 05-21, like the terminal app
const MINUTES = ['00', '15', '30', '45'];

/** A 24-hour time as two dropdowns (hour, minute); '' means "not set". Whatever the browser's own
 *  clock format is (12 or 24 hour), the app shows the same HH:MM everywhere. */
export function TimeSelect({ id, value, onChange, label }) {
  const [hh = '', mm = ''] = (value || '').split(':');
  const withCurrent = (list, current) => (current && !list.includes(current) ? [current, ...list] : list);
  const choose = (hour, minute) => onChange(hour ? `${hour}:${minute || '00'}` : '');
  return html`
    <span class="time-select">
      <${Select} id=${id} aria-label=${label ? label + ' (' + t('hour') + ')' : t('hour')} value=${hh}
        options=${[{ value: '', label: '--' }, ...withCurrent(HOURS, hh).map((h) => ({ value: h, label: h }))]} onChange=${(h) => choose(h, mm)} />
      <span class="dim">:</span>
      <${Select} aria-label=${label ? label + ' (' + t('minute') + ')' : t('minute')} value=${hh ? mm || '00' : ''}
        options=${[{ value: '', label: '--' }, ...withCurrent(MINUTES, mm).map((m) => ({ value: m, label: m }))]} onChange=${(m) => choose(hh, m)} />
    </span>`;
}

export function Status({ kind, children }) {
  if (!children) return null;
  return html`<p class=${'status-line ' + (kind || '')} role=${kind === 'error' ? 'alert' : 'status'}>${children}</p>`;
}

/** Fetch `loader()` when `deps` change; `{ data, error, loading, reload }`. */
export function useLoad(loader, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const counter = useRef(0);
  const run = useCallback(() => {
    const mine = ++counter.current;
    setState((current) => ({ ...current, loading: true, error: null }));
    loader()
      .then((data) => mine === counter.current && setState({ data, error: null, loading: false }))
      .catch((error) => mine === counter.current && setState({ data: null, error, loading: false }));
  }, deps);
  useEffect(run, [run]);
  return { ...state, reload: run };
}

// ---------------------------------------------------------------- themes
// The same eleven palettes as the terminal and Mac apps (themes.json), saved in the same THEME=
// setting. With none saved, the system decides: Catppuccin Mocha (dark) or Latte (light).

let THEMES = null;

export async function loadThemes() {
  if (!THEMES) {
    const all = await api('/themes.json');
    delete all._note;
    THEMES = all;
  }
  return THEMES;
}

export const themeNames = () => Object.keys(THEMES || {});
export const themeLabel = (name) => name.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export function systemTheme() {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'catppuccin-latte' : 'catppuccin';
}

export function applyTheme(name) {
  const palette = THEMES && (THEMES[name] || THEMES[systemTheme()]);
  if (!palette) return;
  const root = document.documentElement;
  root.style.setProperty('--bg', palette.background);
  root.style.setProperty('--surface', palette.surface);
  root.style.setProperty('--text', palette.foreground);
  root.style.setProperty('--accent', palette.accent);
  root.setAttribute('data-scheme', palette.dark ? 'dark' : 'light');
}
