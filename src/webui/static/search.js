// Search: find the best open tee times in the coming days for criteria you set (prefilled from your
// Preferences), ranked by the same pipeline as the Overview's picks.

import {
  html, t, useState, useEffect, useRef, Sheet, Select, Switch, TimeSelect, Status, Icon, api, post, query,
  dayLabel, temperature, windSpeed, amount, round,
} from '/lib.js';
import { PlayerNames } from '/overview.js';

const BUFFERS = [0, 5, 10, 15, 20, 30, 45, 60].map((n) => ({ value: String(n), label: n ? `${n} min` : '0' }));
const SPOTS = [1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }));

/** "Reset filters": every field cleared to "no filter" (any time, one spot, no buffer, nobody in
 *  particular), deliberately not your saved Preferences, and it does not search again. */
const CLEARED = {
  min_open_spots: 1,
  weekday_window: { after: '', before: '' },
  weekend_window: { after: '', before: '' },
  buffer_before_minutes: 0,
  buffer_after_minutes: 0,
  friends_only: false,
  player: '',
};

/** "from [hh]:[mm] to [hh]:[mm]": one time window; a blank end is "no limit" on that side. */
function WindowFields({ label, value, onChange, idPrefix }) {
  const set = (key) => (time) => onChange({ ...value, [key]: time });
  return html`
    <div class="field-row">
      <label for=${idPrefix + '-after'}>${label}</label>
      <span class="time-pair">
        <span class="dim">${t('search.from')}</span>
        <${TimeSelect} id=${idPrefix + '-after'} label=${label + ' ' + t('search.after')} value=${value.after || ''} onChange=${set('after')} />
        <span class="dim">${t('search.to')}</span>
        <${TimeSelect} id=${idPrefix + '-before'} label=${label + ' ' + t('search.before')} value=${value.before || ''} onChange=${set('before')} />
      </span>
    </div>`;
}

function ResultRow({ match, units, showHandicaps, onMark }) {
  const w = match.weather;
  const open = Math.max(0, match.capacity - match.booked);
  return html`
    <div class="res">
      <span class="res-date">${dayLabel(match.date)}</span>
      <span class="num res-time">${match.time}</span>
      <span class="res-open">${t('search.open_spots', { n: open })}</span>
      <span class="res-people"><${PlayerNames} slot=${{ players: match.players, booked: match.booked }} showHandicaps=${showHandicaps} /></span>
      <span class="res-notes">
        ${match.flags.map((flag) => html`<span class="chip warn" title=${t('search.flag_tip.' + flag)}>${t('search.flag.' + flag)}</span>`)}
        ${w && html`<span class="num dim wx-sum" title=${t('tip.rain')}>${w.temp != null ? temperature(w.temp, units) + '°' : ''}${w.rain != null ? ' ' + round(w.rain) + '%' + (w.rain_mm ? '/' + amount(w.rain_mm, units) : '') : ''}${w.wind != null ? ' ' + windSpeed(w.wind, units) : ''}</span>`}
      </span>
      <span class="res-action">
        ${match.booked_by_you
          ? html`<span class="chip mine"><${Icon} name="flag" size=${13} style="fill:currentColor" />${t('search.booked')}</span>`
          : html`<button class="btn small" onClick=${() => onMark(match)}>${t('search.mark_booked')}</button>`}
      </span>
    </div>`;
}

export function SearchSheet({ club, course, units, showHandicaps, onClose, onMark, refreshKey }) {
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const [criteria, setCriteria] = useState(null);
  const [players, setPlayers] = useState([]);
  const [result, setResult] = useState(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState(null);
  const first = useRef(true);

  async function run(next) {
    setSearching(true);
    setError(null);
    try {
      setResult(await post('/api/search', { ...ref, course, criteria: next }));
    } catch (failure) {
      setError(t('error.title'));
    }
    setSearching(false);
  }

  useEffect(() => {
    (async () => {
      try {
        const loaded = await api('/api/search/defaults' + query(ref));
        setCriteria(loaded);
        const list = await api('/api/players' + query(ref));
        setPlayers(list.players.map((p) => p.name));
        await run(loaded);
      } catch (failure) {
        setError(t('error.title'));
      }
    })();
  }, []);

  // A booking marked from the results changes them (the booked row), so search again.
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (criteria) run(criteria);
  }, [refreshKey]);

  const set = (key) => (value) => setCriteria((current) => ({ ...current, [key]: value }));
  const matches = (result && result.matches) || [];
  return html`<${Sheet} title=${t('search.title')} onClose=${onClose} size="wide" fixed>
    ${criteria && html`
      <section class="criteria">
        <p class="lab">${t('search.criteria')} <span class="lab-note">${t('search.prefill_note')}</span></p>
        <form onSubmit=${(event) => { event.preventDefault(); run(criteria); }}>
          <div class="crit-cards">
            <div class="group">
              <h3>${t('search.time')}</h3>
              <${WindowFields} label=${t('search.weekday')} idPrefix="s-wd" value=${criteria.weekday_window} onChange=${set('weekday_window')} />
              <${WindowFields} label=${t('search.weekend')} idPrefix="s-we" value=${criteria.weekend_window} onChange=${set('weekend_window')} />
              <div class="field-row"><label for="s-before">${t('settings.field.buffer_before_minutes')}</label>
                <${Select} id="s-before" value=${String(criteria.buffer_before_minutes)} options=${BUFFERS} onChange=${(v) => set('buffer_before_minutes')(Number(v))} /></div>
              <div class="field-row"><label for="s-after">${t('settings.field.buffer_after_minutes')}</label>
                <${Select} id="s-after" value=${String(criteria.buffer_after_minutes)} options=${BUFFERS} onChange=${(v) => set('buffer_after_minutes')(Number(v))} /></div>
            </div>
            <div class="group">
              <h3>${t('search.group')}</h3>
              <div class="field-row"><label for="s-spots">${t('settings.field.min_open_spots')}</label>
                <${Select} id="s-spots" value=${String(criteria.min_open_spots)} options=${SPOTS} onChange=${(v) => set('min_open_spots')(Number(v))} /></div>
              <div class="field-row"><label for="s-player">${t('search.field.player')}</label>
                <${Select} id="s-player" value=${criteria.player || ''}
                  options=${[{ value: '', label: t('search.field.player.any') }, ...players.map((name) => ({ value: name, label: name }))]} onChange=${set('player')} /></div>
              <div class="field-row"><label for="s-friends">${t('search.friends_only_label')}</label>
                <${Switch} id="s-friends" checked=${criteria.friends_only} onChange=${set('friends_only')} /></div>
            </div>
          </div>
          <div class="actions">
            <${Status} kind="error">${error}<//>
            <span class="grow"></span>
            <button class="btn" type="button" disabled=${searching} onClick=${() => setCriteria(CLEARED)}>${t('search.reset')}</button>
            <button class="btn pri" type="submit" disabled=${searching}>${t(searching ? 'search.searching' : 'search.button')}</button>
          </div>
        </form>
      </section>`}
    ${result && html`
      <p class="lab results-head">${t('search.results', { n: matches.length })}</p>
      ${matches.length === 0
        ? html`<div class="empty small"><h3>${t('search.no_matches_title')}</h3><p>${t('search.no_matches_desc')}</p></div>`
        : html`<div class="results scroll">${matches.map((match) => html`<${ResultRow} key=${match.date + match.time} match=${match} units=${units} showHandicaps=${showHandicaps} onMark=${onMark} />`)}</div>`}`}
  <//>`;
}
