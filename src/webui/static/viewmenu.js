// The View menu in the toolbar: how the page looks and reads, one click from the Overview. Language, theme,
// scale, units and handicaps live here (not in Settings); each applies at once.

import { CheckButton } from '/update.js';
import {
  html, t, useState, useLayoutEffect, useRef, Select, Switch, Icon, post, SCALES, DEFAULT_SCALE, getScale, setScale,
  themeNames, themeLabel, applyTheme, systemTheme,
} from '/lib.js';

const LANGUAGES = [{ value: 'en', label: 'English' }, { value: 'de', label: 'Deutsch' }];

export function ViewMenu({ boot, units, showHandicaps, history, onHistory, tips, onTips, open, onToggle, onClose, onDisplay, onLanguage, onUpdate }) {
  const [scale, setScaleState] = useState(getScale());
  const [theme, setThemeState] = useState(boot.theme || systemTheme());
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

  // Units and handicaps only change how numbers are shown: the page applies them at once and saves in the
  // background (a failed save puts the old value back). The language needs the page's texts again: reload.
  const saveSetting = async (field, value, shown, previous) => {
    if (shown) onDisplay(shown);
    try {
      await post('/api/settings', { values: { [field]: value } });
      if (field === 'field-__language__') onLanguage();
    } catch (error) {
      if (shown && previous) onDisplay(previous);
    }
  };
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

  return html`
    <span class="view-wrap">
      <button class=${'tool' + (open ? ' on' : '')} data-view-button onClick=${onToggle} aria-expanded=${open} aria-haspopup="true"
        title=${t('action.view') + ' (v)'} aria-keyshortcuts="v"><${Icon} name="palette" /><span class="tool-label">${t('action.view')}</span></button>
      ${open && html`
        <div class="view-panel" ref=${panel} role="dialog" aria-label=${t('action.view')}>
          <div class="field-row"><label for="v-language">${t('settings.field.language')}</label>
            <${Select} id="v-language" value=${boot.language} options=${LANGUAGES} onChange=${(value) => saveSetting('field-__language__', value)} /></div>
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
              onChange=${(value) => saveSetting('field-units', value, { units: value }, { units })} /></div>
          <div class="field-row"><label for="v-hcp">${t('settings.field.show_handicaps')}</label>
            <${Switch} id="v-hcp" checked=${showHandicaps} onChange=${(value) => saveSetting('field-show_handicaps', value, { showHandicaps: value }, { showHandicaps })} /></div>
          <div class="field-row"><label for="v-tips">${t('panel.toggle')}</label>
            <${Switch} id="v-tips" checked=${tips} onChange=${onTips} /></div>
          <div class="field-row"><label for="v-history">${t('history.toggle')}</label>
            <${Switch} id="v-history" checked=${history} onChange=${onHistory} /></div>
          <div class="view-about"><span class="version">v${boot.version}</span><${CheckButton} onResult=${onUpdate} /></div>
          ${boot.serve && html`<div class="field-row"><span></span>
            <button class="btn small" onClick=${() => post('/api/auth/logout').then(() => location.assign('/login'))}>${t('view.logout')}</button></div>`}
        </div>`}
    </span>`;
}

/** On a phone the toolbar has room for seven buttons a finger can hit: the ones used less often (`items`, each
 *  { name, icon, label, key, onClick, disabled }) move into this menu there. Wider screens hide it (style.css). */
export function MoreMenu({ items, open, onToggle, onClose }) {
  const panel = useRef(null);
  useLayoutEffect(() => {
    if (!open) return undefined;
    const outside = (event) => panel.current && !panel.current.contains(event.target) && !event.target.closest('[data-more-button]') && onClose();
    const escape = (event) => event.key === 'Escape' && (event.stopPropagation(), onClose());
    document.addEventListener('mousedown', outside);
    window.addEventListener('keydown', escape, true);
    return () => {
      document.removeEventListener('mousedown', outside);
      window.removeEventListener('keydown', escape, true);
    };
  }, [open]);
  return html`
    <span class="view-wrap more-wrap">
      <button class=${'tool' + (open ? ' on' : '')} data-more-button onClick=${onToggle} aria-expanded=${open} aria-haspopup="menu" title=${t('action.more')} aria-label=${t('action.more')}>
        <${Icon} name="more" /></button>
      ${open && html`
        <div class="view-panel more-panel" ref=${panel} role="menu" aria-label=${t('action.more')}>
          ${items.map((item) => html`<button key=${item.name} class="more-item" role="menuitem" disabled=${item.disabled} onClick=${() => { onClose(); item.onClick(); }}>
            <${Icon} name=${item.icon} /><span>${item.label}</span><span class="kbd">${item.key}</span></button>`)}
        </div>`}
    </span>`;
}
