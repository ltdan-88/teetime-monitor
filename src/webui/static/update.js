// Newer-version notice (every install) and, on a Raspberry Pi server, the update itself (src/webui/updates.py).

import { html, t, useState, useEffect, useRef, Icon, Sheet, Status, post, api } from '/lib.js';

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/** The banner above the days: "Version X is available", the way to update this install (the command, or a button on a Pi
 *  server) and the release notes; dismissed until a still newer version comes. */
export function UpdateNotice({ update, onUpdate, onDismiss }) {
  return html`<div class="banner update-banner" role="status">
    <${Icon} name="arrowup" size=${18} />
    <span class="update-text"><strong>${t('update.available', { version: update.latest })}</strong>
      ${update.command && html`<span class="dim"> · ${t('update.run')} <code>${update.command}</code></span>`}
      <span class="dim"> · </span><a href=${update.url} target="_blank" rel="noopener noreferrer">${t('update.notes')}</a></span>
    ${update.can_update && html`<button class="btn pri small" onClick=${onUpdate}>${t('update.now')}</button>`}
    <button class="icon-btn" onClick=${onDismiss} aria-label=${t('dismiss')} title=${t('dismiss')}><${Icon} name="close" size=${16} /></button>
  </div>`;
}

/** The morning after an automatic update (a Pi server): it worked, or it did not and the old version still runs.
 *  Dismissed for every device at once (the server forgets it). */
export function AutoUpdateNote({ result, current, url, onDismiss }) {
  return html`<div class="banner update-banner auto-note" role="status">
    <${Icon} name=${result.ok ? 'check' : 'info'} size=${18} />
    <span class="update-text">${result.ok ? t('update.auto_done', { version: result.to }) : t('update.auto_failed', { version: result.to, current })}
      ${result.ok && url && html`<span class="dim"> · </span><a href=${url} target="_blank" rel="noopener noreferrer">${t('update.notes')}</a>`}</span>
    <button class="icon-btn" onClick=${onDismiss} aria-label=${t('dismiss')} title=${t('dismiss')}><${Icon} name="close" size=${16} /></button>
  </div>`;
}

/** The footer's "Check for updates": looks now (the server asks GitHub) and says what it found, for a few seconds. */
export function CheckButton({ onResult }) {
  const [state, setState] = useState('idle'); // idle | checking | current | newer | failed | off
  async function check() {
    setState('checking');
    let next = 'failed';
    try {
      const result = await post('/api/update/check', {});
      onResult(result);
      next = result.check_disabled ? 'off' : !result.check_ok ? 'failed' : result.newer ? 'newer' : 'current';
    } catch (failure) {
      next = 'failed';
    }
    setState(next);
    setTimeout(() => setState('idle'), 6000);
  }
  const label = { idle: t('update.check'), checking: t('update.checking'), current: t('update.current'), newer: t('update.found'), failed: t('update.check_failed'), off: t('update.check_off') }[state];
  return html`<button class=${'link-btn check-update' + (state === 'failed' ? ' failed' : '')} onClick=${check} disabled=${state === 'checking'} aria-live="polite">${label}</button>`;
}

/** Confirm, install, wait for the restart, reload. */
export function UpdateSheet({ update, onClose }) {
  const [phase, setPhase] = useState('ask'); // ask | installing | restarting | failed
  const [error, setError] = useState(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  async function start() {
    setPhase('installing');
    try {
      const started = await post('/api/update/apply', {});
      if (started.error) throw new Error(started.error);
      // pip works for a minute or two; the server then restarts itself and the page waits for it to come back
      while (alive.current) {
        await sleep(2000);
        let state = null;
        try {
          state = (await api('/api/update')).install;
        } catch (failure) {
          state = { state: 'restarting' }; // the server is already going down
        }
        if (state.state === 'failed') {
          setError(state.error || '');
          setPhase('failed');
          return;
        }
        if (state.state === 'restarting') break;
      }
      setPhase('restarting');
      // The old process still answers (and already reports the new version, pip having replaced its files)
      // until it stops: only a process that has just started says "idle", so wait for that.
      for (let tries = 0; alive.current && tries < 120; tries += 1) {
        await sleep(3000);
        try {
          const fresh = await api('/api/update');
          if (fresh.install.state === 'idle') {
            location.reload();
            return;
          }
        } catch (failure) {
          /* still down */
        }
      }
      setError(t('update.slow'));
      setPhase('failed');
    } catch (failure) {
      setError(failure.message);
      setPhase('failed');
    }
  }

  const busy = phase === 'installing' || phase === 'restarting';
  return html`<${Sheet} title=${t('update.title', { version: update.latest })} onClose=${busy ? () => {} : onClose} size="small">
    <p>${t('update.explain')}</p>
    ${phase === 'installing' && html`<${Status} kind="busy">${t('update.installing')}<//>`}
    ${phase === 'restarting' && html`<${Status} kind="busy">${t('update.restarting')}<//>`}
    ${phase === 'failed' && html`<${Status} kind="error">${t('update.failed', { error: error || '' })}<//>`}
    <div class="actions">
      <span class="grow"></span>
      <button class="btn" onClick=${onClose} disabled=${busy}>${t('cancel')}</button>
      ${phase === 'ask' && html`<button class="btn pri" onClick=${start}>${t('update.now')}</button>`}
    </div>
  <//>`;
}
