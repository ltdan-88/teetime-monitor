// Your scorecard for a booking (src/webui/data.py scorecard_for, src/scorecard.py): the tee it is played from, how
// many points beat your handicap, per hole your shots, the score that is par for you and where to pick up; and your
// own strokes, typed in during or after the round, with their Stableford points (kept in the app only).

import { html, t, useState, useEffect, useRef, Sheet, Status, Select, api, post, query, dayLabel } from '/lib.js';

const TEE_NAMES = { gelb: 'yellow', rot: 'red', weiss: 'white', blau: 'blue', gruen: 'green', schwarz: 'black' };

export function teeLabel(choice) {
  const colour = TEE_NAMES[choice.color] ? t('scorecard.tee.' + TEE_NAMES[choice.color]) : choice.color;
  return `${choice.round.replace(/^Runde\s+/i, '')} · ${colour}`;
}

/** "Better than your handicap: 37+ points" (about, on nine holes): the one line the booking dialog shows too. */
export function targetText(card) {
  return t(card.approximate ? 'scorecard.target_about' : 'scorecard.target', { points: card.points_better });
}

/** Stableford points for `strokes` on `hole`: 2 for par for you, one more or less a stroke, never below 0 (as
 *  src/scorecard.py points()); null for a hole not filled in. */
const pointsFor = (strokes, hole) => (strokes == null ? null : Math.max(0, 2 + hole.aim - strokes));

export function ScorecardSheet({ booking, onClose }) {
  const [state, setState] = useState(null); // { card, choices, chosen, strokes } | { error }
  const [strokes, setStrokes] = useState([]);
  const ref = { slug: booking.slug, club_id: booking.slug ? null : booking.club_id };
  const round = { ...ref, course: booking.course, date: booking.date, time: booking.time };
  const saving = useRef(null);
  const load = (keep) => api('/api/scorecard' + query(round))
    .then((found) => {
      setState(found);
      const mine = keep && keep.length === (found.strokes || []).length && keep.some((x) => x != null) ? keep : found.strokes || [];
      setStrokes(mine);
      if (mine !== found.strokes && found.chosen) save(mine, found.chosen); // the strokes go with the tee chosen now
    })
    .catch((failure) => setState((failure && failure.payload) || { error: 'network' }));
  const pending = useRef(null); // strokes typed but not sent yet: sent a moment after typing stops, or when the window closes
  const send = () => {
    clearTimeout(saving.current);
    if (pending.current) post('/api/scorecard/score', pending.current).catch(() => {});
    pending.current = null;
  };
  const save = (values, tee) => {
    pending.current = { ...round, tee, strokes: values };
    clearTimeout(saving.current);
    saving.current = setTimeout(send, 500);
  };
  useEffect(() => { load(null); return send; }, []);
  const choose = (key) => post('/api/scorecard/tee', { slug: booking.slug, course: booking.course, key }).then(() => load(strokes)).catch(() => {});
  const enter = (i) => (event) => {
    const value = parseInt(event.target.value, 10);
    setStrokes((now) => {  // from the strokes as they are now: quick typing must not undo the hole before
      const next = now.map((x, j) => (j === i ? (value >= 1 && value <= 20 ? value : null) : x));
      save(next, state.chosen);
      return next;
    });
  };
  const card = state && state.card;
  const filled = card ? card.holes.filter((_, i) => strokes[i] != null) : [];
  const totalStrokes = filled.reduce((sum, hole) => sum + strokes[hole.hole - 1], 0);
  const totalPoints = card ? card.holes.reduce((sum, hole, i) => sum + (pointsFor(strokes[i], hole) || 0), 0) : 0;
  const complete = card && filled.length === card.holes.length;
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
          <th>${t('scorecard.col.shots')}</th><th>${t('scorecard.col.aim')}</th><th>${t('scorecard.col.max')}</th>
          <th>${t('scorecard.col.score')}</th><th>${t('scorecard.col.points')}</th></tr></thead>
        <tbody>${card.holes.map((hole, i) => html`<tr key=${hole.hole}><td>${hole.hole}</td><td>${hole.par}</td><td class="dim">${hole.index}</td>
          <td>${hole.shots}</td><td class="sc-aim">${hole.aim}</td><td class="dim">${hole.max}</td>
          <td><input class="sc-in" type="text" inputmode="numeric" maxlength="2" value=${strokes[i] == null ? '' : strokes[i]} onInput=${enter(i)}
            aria-label=${t('scorecard.score_for', { hole: hole.hole })} /></td>
          <td class=${'sc-pts' + (pointsFor(strokes[i], hole) == null ? '' : pointsFor(strokes[i], hole) >= 2 ? ' good' : ' low')}>${pointsFor(strokes[i], hole) ?? ''}</td></tr>`)}</tbody>
        ${filled.length > 0 && html`<tfoot><tr><td colspan="6">${t('scorecard.total')}</td><td>${totalStrokes}</td><td class="sc-pts">${totalPoints}</td></tr></tfoot>`}
      </table></div>
      ${complete && html`<p class=${'sc-verdict ' + (totalPoints >= card.points_better ? 'good' : '')}>${totalPoints >= card.points_better
        ? t('scorecard.verdict.better', { points: totalPoints }) : t('scorecard.verdict.not', { points: totalPoints, needed: card.points_better })}</p>`}
      <p class="hint">${t('scorecard.note')}</p>`}
  <//>`;
}
