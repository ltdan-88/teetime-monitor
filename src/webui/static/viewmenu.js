// The View menu in the toolbar: how the page looks and reads, one click from the Overview. Language, theme,
// scale, units and handicaps live here (not in Settings); each applies at once.

import {
  html, t, useState, useLayoutEffect, useRef, Select, Switch, Icon, post, SCALES, DEFAULT_SCALE, getScale, setScale,
  themeNames, themeLabel, applyTheme, systemTheme,
} from '/lib.js';

const LANGUAGES = [{ value: 'en', label: 'English' }, { value: 'de', label: 'Deutsch' }];

export function ViewMenu({ boot, units, showHandicaps, open, onToggle, onClose, onChanged }) {
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

  const saveSetting = async (field, value) => {
    await post('/api/settings', { values: { [field]: value } });
    onChanged(field);
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
              onChange=${(value) => saveSetting('field-units', value)} /></div>
          <div class="field-row"><label for="v-hcp">${t('settings.field.show_handicaps')}</label>
            <${Switch} id="v-hcp" checked=${showHandicaps} onChange=${(value) => saveSetting('field-show_handicaps', value)} /></div>
        </div>`}
    </span>`;
}
