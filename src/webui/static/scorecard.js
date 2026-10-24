// Your scorecard for a booking (src/webui/data.py scorecard_for, src/scorecard.py): the tee it is played from, how
// many points beat your handicap, and per hole your shots, the score that is par for you and where to pick up.

import { html, t, useState, useEffect, Sheet, Status, Select, api, post, query, dayLabel } from '/lib.js';

const TEE_NAMES = { gelb: 'yellow', rot: 'red', weiss: 'white', blau: 'blue', gruen: 'green', schwarz: 'black' };

export function teeLabel(choice) {
  const colour = TEE_NAMES[choice.color] ? t('scorecard.tee.' + TEE_NAMES[choice.color]) : choice.color;
  return `${choice.round.replace(/^Runde\s+/i, '')} · ${colour}`;
}

/** "Better than your handicap: 37+ points" (about, on nine holes): the one line the booking dialog shows too. */
export function targetText(card) {
  return t(card.approximate ? 'scorecard.target_about' : 'scorecard.target', { points: card.points_better });
}

export function ScorecardSheet({ booking, onClose }) {
  const [state, setState] = useState(null); // { card, choices, chosen } | { error }
  const ref = { slug: booking.slug, club_id: booking.slug ? null : booking.club_id };
  const load = () => api('/api/scorecard' + query({ ...ref, course: booking.course }))
    .then(setState).catch((failure) => setState((failure && failure.payload) || { error: 'network' }));
  useEffect(() => { load(); }, []);
  const choose = (key) => post('/api/scorecard/tee', { slug: booking.slug, course: booking.course, key }).then(load).catch(() => {});
  const card = state && state.card;
  return html`<${Sheet} title=${t('scorecard.title')} onClose=${onClose} size="medium">
    <p><b>${booking.course}</b> · ${dayLabel(booking.date)}, ${booking.time}</p>
    ${!state && html`<${Status} kind="busy">${t('scorecard.loading')}<//>`}
    ${state && state.error && html`<${Status} kind="error">${t('scorecard.error.' + state.error) === 'scorecard.error.' + state.error ? t('scorecard.error.network') : t('scorecard.error.' + state.error)}<//>`}
    ${card && html`
      <div class="field-row"><label for="sc-tee">${t('scorecard.tee')}</label>
        <${Select} id="sc-tee" value=${state.chosen} options=${state.choices.map((choice) => ({ value: choice.key, label: teeLabel(choice) }))} onChange=${choose} /></div>
      <p class="sc-target"><b>${targetText(card)}</b><span class="dim"> · ${t('scorecard.course_handicap', { n: card.course_handicap })}</span></p>
      <div class="sc-wrap"><table class="sc-table">
        <thead><tr><th>${t('scorecard.col.hole')}</th><th>${t('scorecard.col.par')}</th><th>${t('scorecard.col.index')}</th>
          <th>${t('scorecard.col.shots')}</th><th>${t('scorecard.col.aim')}</th><th>${t('scorecard.col.max')}</th></tr></thead>
        <tbody>${card.holes.map((hole) => html`<tr key=${hole.hole}><td>${hole.hole}</td><td>${hole.par}</td><td class="dim">${hole.index}</td>
          <td>${hole.shots}</td><td class="sc-aim">${hole.aim}</td><td class="dim">${hole.max}</td></tr>`)}</tbody>
      </table></div>
      <p class="hint">${t('scorecard.note')}</p>`}
  <//>`;
}
