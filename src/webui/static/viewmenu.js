// The View menu at the bottom, beside the Legend: the three switches that change what the Overview shows right now
// (handicaps, tip cards, past days). How the page looks and reads -- language, theme, scale, units -- is set once,
// so it lives in Settings (DisplaySection below), together with the version and the update check (AboutSection).

import { CheckButton } from '/update.js';
import {
  html, t, useState, useLayoutEffect, useRef, Select, Switch, Icon, post, SCALES, DEFAULT_SCALE, getScale, setScale,
  themeNames, themeLabel, applyTheme, systemTheme,
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

export function ViewMenu({ showHandicaps, history, onHistory, tips, onTips, open, onToggle, onClose, onDisplay }) {
  const panel = useRef(null);

  // closes on a click elsewhere or Escape (set up as the panel is drawn, not a frame later)
  useLayoutEffect(() => {
    if (!open) return undefined;
    const outside = (event) => panel.current && !panel.current.contains(event.target) && !event.target.closest('[data-view-button]') && onClose();
    const escape = (event) => event.key === 'Escape' && (event.stopPropagation(), onClose());
    document.addEventListener('mousedown', outside);
    window.addEventListener('keydown', escape, true);
    return () => {
      document.removeEventListener('mousedown', outside);
      window.removeEventListener('keydown', escape, true);
    };
  }, [open]);

  return html`
    <span class="view-wrap">
      <button class=${'tool small' + (open ? ' on' : '')} data-view-button onClick=${onToggle} aria-expanded=${open} aria-haspopup="true"
        title=${t('action.view') + ' (v)'} aria-label=${t('action.view')} aria-keyshortcuts="v"><${Icon} name="palette" size=${16} /><span class="tool-label">${t('action.view')}</span></button>
      ${open && html`
        <div class="view-panel slim" ref=${panel} role="dialog" aria-label=${t('action.view')}>
          <div class="field-row"><label for="v-hcp">${t('settings.field.show_handicaps')}</label>
            <${Switch} id="v-hcp" checked=${showHandicaps} onChange=${(value) => saveSetting('field-show_handicaps', value, onDisplay, null, { showHandicaps: value }, { showHandicaps })} /></div>
          <div class="field-row"><label for="v-tips">${t('panel.toggle')}</label>
            <${Switch} id="v-tips" checked=${tips} onChange=${onTips} /></div>
          <div class="field-row"><label for="v-history">${t('history.toggle')}</label>
            <${Switch} id="v-history" checked=${history} onChange=${onHistory} /></div>
          <p class="view-more">${t('view.more_in_settings')}</p>
        </div>`}
    </span>`;
}

/** Settings' Display group: language, theme, scale (this device) and units, each applied at once. */
export function DisplaySection({ boot, units, onDisplay, onLanguage }) {
  const [scale, setScaleState] = useState(getScale());
  const [theme, setThemeState] = useState(boot.theme || systemTheme());
  const stepScale = (direction) => {
    const index = SCALES.indexOf(scale);
    const next = SCALES[Math.min(SCALES.length - 1, Math.max(0, index + direction))];
    setScaleState(next);
    setScale(next);
  };
  const chooseTheme = (name) => {
    setThemeState(name);
    applyTheme(name);
    post('/api/theme', { name }).catch(() => {});
  };
  return html`<section class="group display-group">
    <h3>${t('settings.group.display')}</h3>
    <p class="hint">${t('settings.display_hint')}</p>
    <div class="field-row"><label for="v-language">${t('settings.field.language')}</label>
      <${Select} id="v-language" value=${boot.language} options=${LANGUAGES} onChange=${(value) => saveSetting('field-__language__', value, onDisplay, onLanguage)} /></div>
    <div class="field-row"><label for="v-theme">${t('settings.field.theme')}</label>
      <${Select} id="v-theme" value=${theme} options=${themeNames().map((name) => ({ value: name, label: themeLabel(name) }))} onChange=${chooseTheme} /></div>
    <div class="field-row"><label id="v-scale-label">${t('settings.scale')}</label>
      <span class="stepper" role="group" aria-labelledby="v-scale-label">
        <button class="btn small" onClick=${() => stepScale(-1)} disabled=${scale === SCALES[0]} aria-label=${t('view.smaller')} title=${t('view.smaller')}>A−</button>
        <span class="num stepper-value" title=${scale === DEFAULT_SCALE ? t('settings.scale.default') : ''}>${scale} %</span>
        <button class="btn small" onClick=${() => stepScale(1)} disabled=${scale === SCALES[SCALES.length - 1]} aria-label=${t('view.larger')} title=${t('view.larger')}>A+</button>
      </span></div>
    <div class="field-row"><label for="v-units">${t('settings.field.units')}</label>
      <${Select} id="v-units" value=${units} options=${[{ value: 'metric', label: t('settings.units.metric') }, { value: 'imperial', label: t('settings.units.imperial') }]}
        onChange=${(value) => saveSetting('field-units', value, onDisplay, onLanguage, { units: value }, { units })} /></div>
  </section>`;
}

/** Settings' About group: the version, the update check and (on a served Pi) logging out. */
export function AboutSection({ boot, onUpdate }) {
  return html`<section class="group about-group">
    <h3>${t('settings.group.about')}</h3>
    <div class="view-about"><span class="version">v${boot.version}</span><${CheckButton} onResult=${onUpdate} /></div>
    ${boot.serve && html`<div class="about-logout">
      <button class="btn small" onClick=${() => post('/api/auth/logout').then(() => location.assign('/login'))}>${t('view.logout')}</button></div>`}
  </section>`;
}
