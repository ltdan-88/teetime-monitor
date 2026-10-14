// "My reservations": your upcoming bookings at every saved club, each with a cancel button (src/webui/data.py reservations()).

import { html, t, useState, useEffect, Sheet, Status, api, dayLabel } from '/lib.js';

/** The list comes at once from what is known; pc caddie is then asked for the true state (bookings made on its
 *  own site appear, cancelled ones go) and the list is replaced. */
export function ReservationsSheet({ onClose, onCancel, refreshKey }) {
  const [state, setState] = useState(null); // { reservations, refresh_problems }
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    let live = true;
    setChecking(true);
    (async () => {
      try {
        const known = await api('/api/reservations');
        if (live) setState(known);
      } catch (failure) {
        /* the check below tries again */
      }
      try {
        const fresh = await api('/api/reservations?refresh=1');
        if (live) setState(fresh);
      } catch (failure) {
        if (live) setState((current) => ({ reservations: (current && current.reservations) || [], refresh_problems: [{ club: '', reason: 'network' }] }));
      }
      if (live) setChecking(false);
    })();
    return () => { live = false; };
  }, [refreshKey]);

  const list = (state && state.reservations) || [];
  const problems = ((state && state.refresh_problems) || []).map((p) => p.club).filter(Boolean).join(', ');
  const failed = !!(state && state.refresh_problems && state.refresh_problems.length);
  return html`<${Sheet} title=${t('reservations.title')} onClose=${onClose} size="medium">
    <p class="hint">${t('reservations.intro')}</p>
    ${checking && html`<${Status} kind="busy">${t('reservations.checking')}<//>`}
    ${!checking && failed && html`<${Status} kind="error">${t('reservations.check_failed', { clubs: problems || '…' })}<//>`}
    ${state && list.length === 0 && !checking && html`<div class="empty small"><h3>${t('reservations.empty_title')}</h3><p>${t('reservations.empty')}</p></div>`}
    <ul class="resv-list">
      ${list.map((item) => html`
        <li key=${item.club_id + item.course + item.date + item.time}>
          <span class="resv-when"><b>${dayLabel(item.date)}</b> <span class="num">${item.time}</span></span>
          <span class="resv-where">${item.club}<span class="dim"> · ${item.course}</span></span>
          <button class="btn small danger" onClick=${() => onCancel(item)}>${t('reservations.cancel')}</button>
        </li>`)}
    </ul>
  <//>`;
}
