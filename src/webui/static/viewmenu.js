// Settings' Display and About groups, and the text size at the bottom of the page. The View menu that sat beside the
// Legend went 2026-10-18: its handicaps and tip-card switches are set once (Display, here), past days is a link under
// the days, and the text size -- the one thing changed often -- stays a tap away in the footer.

import { CheckButton } from '/update.js';
import {
  html, t, useState, useRef, useLayoutEffect, Select, Switch, post, SCALES, DEFAULT_SCALE, getScale, setScale,
  themeNames, themeLabel, applyTheme, systemTheme, WEATHER_SITE_NAMES,
} from '/lib.js';

const LANGUAGES = [{ value: 'en', label: 'English' }, { value: 'de', label: 'Deutsch' }];

/** Save one display setting in the background; `shown` applies at once and `previous` is put back if saving fails.
 *  The language needs the page's texts again: `onLanguage` reloads. */
async function saveSetting(field, value, onDisplay, onLanguage, shown, previous) {
  if (shown) onDisplay(shown);
  try {
    await post('/api/settings', { values: { [field]: value } });
    if (field === 'field-__language__') onLanguage();
  } catch (error) {
    if (shown && previous) onDisplay(previous);
  }
}

/** The text size (this device only), changed often: a quiet "Aa" at the bottom of the page that opens a small bubble
 *  with − and +. A tap elsewhere or Escape closes it. */
export function ScaleControl() {
  const [scale, setScaleState] = useState(getScale());
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  useLayoutEffect(() => {
    if (!open) return undefined;
    const outside = (event) => wrap.current && !wrap.current.contains(event.target) && setOpen(false);
    const escape = (event) => event.key === 'Escape' && (event.stopPropagation(), setOpen(false));
    document.addEventListener('pointerdown', outside);
    window.addEventListener('keydown', escape, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('keydown', escape, true);
    };
  }, [open]);
  const step = (direction) => {
    const index = SCALES.indexOf(scale);
    const next = SCALES[Math.min(SCALES.length - 1, Math.max(0, index + direction))];
    setScaleState(next);
    setScale(next);
  };
  const label = t('view.text_size', { n: scale });
  return html`<span class="scale-wrap" ref=${wrap}>
    <button class=${'tool small scale-btn' + (open ? ' on' : '')} onClick=${() => setOpen(!open)} aria-expanded=${open} aria-label=${label} title=${label}>Aa</button>
    ${open && html`<span class="stepper scale-pop" role="group" aria-label=${t('settings.scale')}>
      <button class="icon-btn" onClick=${() => step(-1)} disabled=${scale === SCALES[0]} aria-label=${t('view.smaller')} title=${t('view.smaller')}>−</button>
      <span class="num stepper-value" title=${scale === DEFAULT_SCALE ? t('settings.scale.default') : ''}>${scale} %</span>
      <button class="icon-btn" onClick=${() => step(1)} disabled=${scale === SCALES[SCALES.length - 1]} aria-label=${t('view.larger')} title=${t('view.larger')}>+</button>
    </span>`}
  </span>`;
}

/** Settings' Display group: language, theme, units, the weather site a day's icon opens, players' handicaps and the
 *  tip cards, each applied at once. (The text size is at the bottom of the page.) */
export function DisplaySection({ boot, units, weatherSite, showHandicaps, tips, onTips, onDisplay, onLanguage }) {
  const [theme, setThemeState] = useState(boot.theme || systemTheme());
  const chooseTheme = (name) => {
    setThemeState(name);
    applyTheme(name);
    post('/api/theme', { name }).catch(() => {});
  };
  return html`<section class="group display-group">
    <h3>${t('settings.group.display')}</h3>
    <div class="field-row"><label for="v-language">${t('settings.field.language')}</label>
      <${Select} id="v-language" value=${boot.language} options=${LANGUAGES} onChange=${(value) => saveSetting('field-__language__', value, onDisplay, onLanguage)} /></div>
    <div class="field-row"><label for="v-theme">${t('settings.field.theme')}</label>
      <${Select} id="v-theme" value=${theme} options=${themeNames().map((name) => ({ value: name, label: themeLabel(name) }))} onChange=${chooseTheme} /></div>
    <div class="field-row"><label for="v-units">${t('settings.field.units')}</label>
      <${Select} id="v-units" value=${units} options=${[{ value: 'metric', label: t('settings.units.metric') }, { value: 'imperial', label: t('settings.units.imperial') }]}
        onChange=${(value) => saveSetting('field-units', value, onDisplay, onLanguage, { units: value }, { units })} /></div>
    <div class="field-row"><label for="v-weather">${t('settings.weather_site')}</label>
      <${Select} id="v-weather" value=${weatherSite || ''}
        options=${[{ value: '', label: t('settings.weather_site.none') }, ...Object.entries(WEATHER_SITE_NAMES).map(([value, label]) => ({ value, label }))]}
        onChange=${(value) => { const previous = weatherSite; onDisplay({ weatherSite: value || null }); post('/api/weather-site', { name: value }).catch(() => onDisplay({ weatherSite: previous })); }} /></div>
    <div class="field-row"><label for="v-hcp">${t('settings.field.show_handicaps')}</label>
      <${Switch} id="v-hcp" checked=${showHandicaps} onChange=${(value) => saveSetting('field-show_handicaps', value, onDisplay, null, { showHandicaps: value }, { showHandicaps })} /></div>
    <div class="field-row"><label for="v-tips">${t('panel.toggle')}</label>
      <${Switch} id="v-tips" checked=${tips} onChange=${onTips} /></div>
  </section>`;
}

/** Settings' About group: the version, the update check, and on a served Pi the switch for updates at night
 *  (it saves at once) and logging out. */
export function AboutSection({ boot, onUpdate, update, onAuto }) {
  const [auto, setAuto] = useState(!!(update && update.auto));
  const flip = (on) => {
    setAuto(on);
    post('/api/update/auto', { on }).then(() => onAuto && onAuto(on)).catch(() => setAuto(!on));
  };
  return html`<section class="group about-group">
    <h3>${t('settings.group.about')}</h3>
    <div class="view-about"><span class="version">v${boot.version}</span><${CheckButton} onResult=${onUpdate} /></div>
    ${update && update.auto_available && html`<div class="field-row"><label for="v-auto">${t('update.auto')}</label>
      <${Switch} id="v-auto" checked=${auto} onChange=${flip} /></div>`}
    ${boot.serve && html`<div class="about-logout">
      <button class="btn small" onClick=${() => post('/api/auth/logout').then(() => location.assign('/login'))}>${t('view.logout')}</button></div>`}
  </section>`;
}
