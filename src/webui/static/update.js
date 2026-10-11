// Newer-version notice (every install) and, on a Raspberry Pi server, the update itself (src/webui/updates.py).

import { html, t, useState, useEffect, useRef, Sheet, Status, post, api } from '/lib.js';

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/** The footer line: "Version X is available · Release notes", the command that updates this install, or the button. */
export function UpdateNotice({ update, onUpdate }) {
  return html`<span class="update-note">
    <a href=${update.url} target="_blank" rel="noopener noreferrer">${t('update.available', { version: update.latest })}</a>
    ${update.command && html`<span class="dim"> · ${t('update.run')} <code>${update.command}</code></span>`}
    ${update.can_update && html` <button class="link-btn" onClick=${onUpdate}>${t('update.now')}</button>`}
  </span>`;
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
