// "My reservations": your upcoming bookings at every saved club, each with a cancel button (src/webui/data.py reservations()).

import { html, t, useState, useEffect, Sheet, Status, Icon, api, dayLabel, updatedText, calendarLink } from '/lib.js';

/** The list comes at once from what is known; pc caddie is then asked for the true state (bookings made on its
 *  own site appear, cancelled ones go) and the list is replaced -- unless it was read a few minutes ago, which the
 *  line under the list says, with a button to read it again now. */
export function ReservationsSheet({ onClose, onCancel, onScorecard, refreshKey, calendar }) {
  const [state, setState] = useState(null); // { reservations, refresh_problems, checked_at }
  const [checking, setChecking] = useState(true);
  const [force, setForce] = useState(0);
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
        const fresh = await api('/api/reservations?refresh=1' + (force ? '&force=1' : ''));
        if (live) setState(fresh);
      } catch (failure) {
        if (live) setState((current) => ({ reservations: (current && current.reservations) || [], refresh_problems: [{ club: '', reason: 'network' }] }));
      }
      if (live) setChecking(false);
    })();
    return () => { live = false; };
  }, [refreshKey, force]);

  const list = (state && state.reservations) || [];
  const past = (state && state.past) || [];
  const scorecardButton = (item) => html`<button class="icon-btn" onClick=${() => onScorecard(item)} aria-label=${t('scorecard.title')} title=${t('scorecard.title')}><${Icon} name="grid" size=${18} /></button>`;
  const problems = ((state && state.refresh_problems) || []).map((p) => p.club).filter(Boolean).join(', ');
  const failed = !!(state && state.refresh_problems && state.refresh_problems.length);
  return html`<${Sheet} title=${t('reservations.title')} onClose=${onClose} size="medium">
    ${checking && html`<${Status} kind="busy">${t('reservations.checking')}<//>`}
    ${!checking && failed && html`<${Status} kind="error">${t('reservations.check_failed', { clubs: problems || '…' })}<//>`}
    ${state && list.length === 0 && !checking && html`<div class="empty small"><h3>${t('reservations.empty_title')}</h3><p>${t('reservations.empty')}</p></div>`}
    <ul class="resv-list">
      ${list.map((item) => html`
        <li key=${item.club_id + item.course + item.date + item.time}>
          <span class="resv-when"><b>${dayLabel(item.date)}</b> <span class="num">${item.time}</span></span>
          <span class="resv-where">${item.club}<span class="dim"> · ${item.course}</span></span>
          <span class="resv-actions">${scorecardButton(item)}
          ${calendarLink(calendar, item) && html`<a class="icon-btn" href=${calendarLink(calendar, item)} target="_blank" rel="noopener noreferrer"
            aria-label=${t('reservations.calendar')} title=${t('reservations.calendar')}><${Icon} name="calendarplus" size=${18} /></a>`}
          <button class="icon-btn danger" onClick=${() => onCancel(item)} aria-label=${t('reservations.cancel')} title=${t('reservations.cancel')}><${Icon} name="trash" size=${18} /></button></span>
        </li>`)}
    </ul>
    ${past.length > 0 && html`<h3 class="resv-past">${t('reservations.past')}</h3>
    <ul class="resv-list past">
      ${past.map((item) => html`
        <li key=${'p' + item.club_id + item.course + item.date + item.time}>
          <span class="resv-when"><b>${dayLabel(item.date)}</b> <span class="num">${item.time}</span></span>
          <span class="resv-where">${item.club}<span class="dim"> · ${item.course}</span></span>
          <span class="resv-actions">${scorecardButton(item)}</span>
        </li>`)}
    </ul>`}
    ${!checking && state && state.checked_at && html`<p class="resv-checked dim">${updatedText(new Date(state.checked_at * 1000).toISOString())}
      <button class="icon-btn" onClick=${() => setForce((n) => n + 1)} aria-label=${t('reservations.check_now')} title=${t('reservations.check_now')}><${Icon} name="refresh" size=${16} /></button></p>`}
  <//>`;
}
