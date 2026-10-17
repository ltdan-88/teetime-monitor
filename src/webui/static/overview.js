// The Overview's day cards: header (weather, pick/booking/lock badge, occupancy), expandable slots.

import {
  html, t, useState, Icon, Condition, WeatherHeads, WeatherCells, tempTone, rainTone, windTone, dayLabel, opensText, temperature, windSpeed, amount, round, hcpText, quietOccupancyColor, occupancyState,
} from '/lib.js';

function pickTooltip(pick) {
  const parts = (pick.reasons || []).map((key) => t('reason.' + key)).filter((text, i) => text !== 'reason.' + pick.reasons[i]);
  if (pick.ai_reasons) parts.push(...pick.ai_reasons);
  return parts.length ? t('tip.pick_reasons', { reasons: parts.join(' · ') }) : t('tip.pick');
}

const HEAT_FROM = [8, 10, 12, 14, 16, 18]; // the six two-hour buckets of the strip
const hh = (n) => String(n).padStart(2, '0');
function heatPart(ratio, i) {
  return `${hh(HEAT_FROM[i])}–${hh(HEAT_FROM[i] + 2)} ${t('heat.' + occupancyState(ratio))}`;
}

export function Badge({ day, onAlternative }) {
  const pick = day.pick;
  if (day.booked_time) {
    return html`<span class="pill booked" title=${t('tip.booked')}><${Icon} name="flag" size=${16} style="fill:currentColor" />${day.booked_time}</span>`;
  }
  if (pick && pick.locked) {
    const when = opensText(pick.locked);
    return html`<span class="pill quiet" title=${t('tip.locked', { when })}><${Icon} name="lock" size=${15} />${when}</span>`;
  }
  if (pick && pick.time) {
    return html`<span class="pill pick" title=${pickTooltip(pick)}><${Icon} name="star" size=${16} style="fill:currentColor" />${pick.time}</span>`;
  }
  if (pick && pick.alternative) {
    const alt = pick.alternative;
    const tip = t('tip.alt', { time: alt.time, course: alt.course, holes: alt.holes });
    if (!onAlternative) return html`<span class="pill quiet" title=${tip}><${Icon} name="star" size=${15} />${alt.time} · ${t('holes.short', { n: alt.holes })}</span>`;
    // Inside the header button, so a click must not also toggle the day.
    const go = (event) => { event.stopPropagation(); onAlternative(day, alt); };
    return html`<span class="pill quiet link" title=${tip + ' ' + t('tip.pick_alternative_click')} onClick=${go}><${Icon} name="star" size=${15} />${alt.time} · ${t('holes.short', { n: alt.holes })}</span>`;
  }
  if (pick && pick.unplayable && pick.unplayable.length) {
    const reasons = [...pick.unplayable].sort();
    const dark = reasons.length === 1 && reasons[0] === 'daylight';
    const key = dark ? 'tip.no_pick_daylight' : reasons.length === 1 && reasons[0] === 'weather' ? 'tip.no_pick_weather' : 'tip.no_pick_both';
    const word = dark ? 'badge.dark' : reasons.length === 1 && reasons[0] === 'weather' ? 'badge.rain' : 'badge.rain_dark';
    return html`<span class="pill quiet word" title=${t(key)}>${t(word)}</span>`;
  }
  return null;
}

/** The slot an opened day scrolls to: its ★ pick, else the first slot at or after your window
 *  opens (the terminal app's and the Mac app's rule). null when neither is known. */
export function focusTime(day) {
  const wanted = (day.pick && day.pick.time) || (day.pick && day.pick.window && day.pick.window.after);
  if (!wanted) return null;
  const slot = day.slots.find((entry) => entry.time >= wanted);
  return slot ? slot.time : null;
}

/** Outside your own availability window: still there to read, just dimmed. */
function outsideWindow(day, slot) {
  const win = day.pick && day.pick.window;
  return !!win && ((win.after && slot.time < win.after) || (win.before && slot.time > win.before));
}

/** What the badge says, as a sentence on the page itself (the badge's tooltip is not available on a touch screen). */
function dayNote(day) {
  const pick = day.pick;
  if (day.booked_time || !pick) return null;
  if (pick.locked) return { icon: 'lock', text: t('tip.locked', { when: opensText(pick.locked) }) };
  if (pick.time) return { icon: 'star', text: pickTooltip(pick) };
  if (pick.alternative) {
    const alt = pick.alternative;
    return { icon: 'star', text: t('tip.alt', { time: alt.time, course: alt.course, holes: alt.holes }), alt };
  }
  if (pick.unplayable && pick.unplayable.length) {
    const reasons = [...pick.unplayable].sort();
    const dark = reasons.length === 1 && reasons[0] === 'daylight';
    return { icon: dark ? 'moon' : 'rain', text: t(dark ? 'tip.no_pick_daylight' : reasons.length === 1 && reasons[0] === 'weather' ? 'tip.no_pick_weather' : 'tip.no_pick_both') };
  }
  return null;
}

/** How many of the day's times pass your Preferences: a tap opens Search on this day. Inside the header button, so a
 *  tap must not also open the day. Green, amber below half of the best day, grey for none (as in Search's strip). */
function MatchCount({ day, best, onSearch }) {
  if (day.matches == null || !onSearch) return null;
  const go = (event) => { event.stopPropagation(); onSearch(day.date); };
  const tone = day.matches === 0 ? ' z' : day.matches * 2 < best ? ' a' : '';
  return html`<span class=${'hits-link' + tone} role="link" tabindex="0" title=${t('search.day_tip', { n: day.matches })} aria-label=${t('search.day_tip', { n: day.matches })}
    onClick=${go} onKeyDown=${(event) => (event.key === 'Enter' || event.key === ' ') && go(event)}><${Icon} name="search" size=${13} />${day.matches}</span>`;
}

function DayHeader({ day, open, onToggle, units, onAlternative, best, onSearch }) {
  const w = day.weather;
  const label = dayLabel(day.date);
  const rainTip = t('tip.rain') + (w && w.rain_all_day ? ' — ' + t('rain_all_day') : '');
  return html`
    <div class="dh-wrap">
    <button class="dh" onClick=${onToggle} aria-expanded=${open} aria-label=${t(open ? 'collapse' : 'expand', { day: label })}>
      <${Icon} name="chevron" size=${18} class="chev" />
      <span class="day">${label}</span>
      <span>${w && html`<${Condition} code=${w.code} />`}</span>
      <span class="temp" title=${t('tip.temp')}>
        ${w && w.temp_high != null && html`<${Icon} name="thermo" size=${16} class="dim" /><span style=${tempTone(w.temp_high)}>${temperature(w.temp_high, units)}°</span><span class="lo">/<span style=${tempTone(w.temp_low)}>${temperature(w.temp_low, units)}°</span></span>`}
      </span>
      <span class="small rain" style=${w ? rainTone(w.rain_avg) : null} title=${rainTip}>
        ${w && html`<${Icon} name="drop" size=${15} />${round(w.rain_avg)}%`}
      </span>
      <span class="small wind" style=${w ? windTone(w.wind_peak) : null} title=${t('tip.wind')}>
        ${w && w.wind_peak != null && html`<${Icon} name="wind" size=${15} />${windSpeed(w.wind_peak, units)}`}
      </span>
      <span class="sun" title=${t('tip.sun')}>${day.sunrise && day.sunset ? `↑${day.sunrise} ↓${day.sunset}` : ''}</span>
      <span class="badge-slot"><${MatchCount} day=${day} best=${best} onSearch=${onSearch} /><${Badge} day=${day} onAlternative=${onAlternative} /></span>
      <span class="heat" role="img" aria-label=${t('heat.title') + ': ' + day.heat.map((ratio, i) => heatPart(ratio, i)).join(', ')}>${day.heat.map((ratio, i) => html`<span class=${'o-' + occupancyState(ratio)} style=${{ backgroundColor: quietOccupancyColor(ratio) }} title=${heatPart(ratio, i)}></span>`)}</span>
      ${day.events.length > 0 && html`<span class="events" title=${day.events.join(' · ')}>${day.events.join(' · ')}</span>`}
    </button>
    ${open && html`<div class="slots-head"><${WeatherHeads} units=${units} /></div>`}
    </div>
  `;
}

export function PlayerNames({ slot, showHandicaps, anonymousCount }) {
  const named = slot.players.length;
  const anonymous = anonymousCount != null ? anonymousCount : Math.max(0, slot.booked - named);
  if (!named && !anonymous) return null;
  const parts = [];
  slot.players.forEach((player, index) => {
    const classes = ['name'];
    if (player.friend) classes.push('f');
    if (player.gender === 'female') classes.push('alt');
    const hcp = showHandicaps && player.hcp != null ? ` (${hcpText(player.hcp)})` : '';
    parts.push(html`<span class=${classes.join(' ')}>${player.friend ? '★ ' : ''}${player.name}${hcp}</span>${index < named - 1 || anonymous ? ', ' : ''}`);
  });
  if (anonymous) parts.push(html`<span class="name anon">${t('anonymous')}${anonymous > 1 ? ` ×${anonymous}` : ''}</span>`);
  return html`<span class="names">${parts}</span>`;
}

/** On a phone the names would wrap over two lines of every row: a chip with the count (and a star when a friend is
 *  booked) opens them as a vertical list instead. Tablets and computers show the names inline, as always. */
export function WhoChip({ slot, open, onToggle }) {
  const named = slot.players.length;
  const anonymous = Math.max(0, slot.booked - named);
  const total = named + anonymous;
  if (!total) return null;
  const stop = (event) => event.stopPropagation(); // a tap here must not also mark the slot as booked
  return html`<button class="who-chip" aria-expanded=${open} aria-label=${t(open ? 'who.hide' : 'who.show', { n: total })}
    onClick=${(event) => { stop(event); onToggle(); }} onKeyDown=${stop}>
    ${slot.players.some((p) => p.friend) && html`<span class="fr">★</span>`}<${Icon} name="users" size=${14} />${total}</button>`;
}

export function WhoList({ slot, showHandicaps }) {
  const anonymous = Math.max(0, slot.booked - slot.players.length);
  return html`<span class="who-list">
    ${slot.players.map((player) => html`<div class=${'name' + (player.friend ? ' f' : '') + (player.gender === 'female' ? ' alt' : '')}>${player.friend ? '★ ' : ''}${player.name}${showHandicaps && player.hcp != null ? ` (${hcpText(player.hcp)})` : ''}</div>`)}
    ${anonymous > 0 && html`<div class="name anon">${t('anonymous')}${anonymous > 1 ? ` ×${anonymous}` : ''}</div>`}
  </span>`;
}

function SlotRow({ slot, day, units, showHandicaps, onPick, onTournament }) {
  const [whoOpen, setWhoOpen] = useState(false);
  const dimmed = outsideWindow(day, slot);
  const capacity = slot.capacity > 0 ? slot.capacity : 4;
  const friendSeat = slot.players.some((player) => player.friend);
  const seats = Array.from({ length: capacity }, (_, i) => {
    let cls = 'seat';
    if (i < slot.booked) cls += friendSeat && i === 0 && !slot.booked_by_you ? ' friend' : ' taken';
    return html`<span class=${cls} style=${slot.booked_by_you && i === 0 ? { background: 'var(--accent)' } : null}></span>`;
  });
  const w = slot.weather;
  const blocked = slot.block_reason !== null && slot.block_reason !== undefined;
  const classes = ['slot'];
  if (slot.past) classes.push('past');
  if (slot.booked_by_you) classes.push('mine');
  if (blocked) classes.push('blocked');
  if (dimmed) classes.push('dimmed');
  const clickable = !blocked && !slot.past && !day.history && (slot.booked_by_you || capacity - slot.booked > 0); // a full time cannot be booked
  if (clickable) classes.push('clickable');
  const activate = () => clickable && onPick(day, slot);
  return html`
    <div class=${classes.join(' ')} data-slot=${day.date + ' ' + slot.time} role=${clickable ? 'button' : null} tabindex=${clickable ? 0 : null}
      title=${clickable ? t(slot.booked_by_you ? 'booking.cancel_hint' : 'booking.book_hint') : null}
      onClick=${activate} onKeyDown=${(event) => (event.key === 'Enter' || event.key === ' ') && (event.preventDefault(), activate())}>
      <span class="time">
        <span style="width:1rem;display:inline-flex">
          ${slot.recommended ? html`<${Icon} name="star" size=${14} style="color:var(--accent);fill:var(--accent)" />` : slot.too_late ? html`<${Icon} name="moon" size=${14} class="dim" />` : null}
        </span>
        <span style=${slot.booked_by_you ? { fontWeight: 700 } : null}>${slot.time}</span>
      </span>
      ${blocked
        ? html`<span class="people blocked-note">${onTournament && day.tournament_day && slot.block_reason && day.events.includes(slot.block_reason)
          ? html`<button class="blocked-text tourn-link" title=${t('tournaments.open_day')} onClick=${(event) => { event.stopPropagation(); onTournament(day.date); }}><${Icon} name="trophy" size=${14} />${slot.block_reason}</button>`
          : html`<span class="dim blocked-text" title=${slot.block_reason || t('not_bookable')}>${slot.block_reason || t('not_bookable')}</span>`}</span>`
        : html`
          <span class="seats" title=${t('tip.seats', { booked: slot.booked, capacity })}>${seats}</span>
          <${WhoChip} slot=${slot} open=${whoOpen} onToggle=${() => setWhoOpen((v) => !v)} />
          <span class="people">
            <${PlayerNames} slot=${slot} showHandicaps=${showHandicaps} />
            ${slot.booked_by_you && html`<span class="note" style="color:var(--accent)"><${Icon} name="flag" size=${14} style="fill:currentColor" />${t('you')}</span>`}
            ${slot.sunrise && html`<span class="note"><${Icon} name="sunrise" size=${16} />${t('sunrise', { time: day.sunrise })}</span>`}
            ${slot.sunset && html`<span class="note"><${Icon} name="sunset" size=${16} />${t('sunset', { time: day.sunset })}</span>`}
          </span>`}
      <span class="wx">${w && html`<${Condition} code=${w.code} size=${20} />`}</span>
      <${WeatherCells} weather=${w} units=${units} />
      ${whoOpen && !blocked && html`<${WhoList} slot=${slot} showHandicaps=${showHandicaps} />`}
    </div>`;
}

export function DayCard({ day, open, onToggle, units, showHandicaps, onPick, onTournament, onAlternative, best, onSearch }) {
  return html`
    <section class=${'card' + (open ? ' open' : '')}>
      <${DayHeader} day=${day} open=${open} onToggle=${onToggle} units=${units} onAlternative=${onAlternative} best=${best} onSearch=${onSearch} />
      ${open && html`<div class="slots">
        ${(() => {
          const note = dayNote(day);
          return note && html`<p class="day-why"><${Icon} name=${note.icon} size=${16} />${note.text}
            ${note.alt && onAlternative && html` <button class="link-btn" onClick=${() => onAlternative(day, note.alt)}>${t('overview.switch_course', { course: note.alt.course })}</button>`}</p>`;
        })()}
        ${day.slots.map((slot) => html`<${SlotRow} key=${slot.time} slot=${slot} day=${day} units=${units} showHandicaps=${showHandicaps} onPick=${onPick} onTournament=${onTournament} />`)}</div>`}
    </section>`;
}

export function Banners({ banners, onAcknowledge }) {
  if (!banners || !banners.length) return null;
  return html`<div class="banners">${banners.map((banner) => html`
    <div class="banner" role="status">
      <${Icon} name="info" size=${18} />
      <span>${banner.text}</span>
      <button class="icon-btn" onClick=${() => onAcknowledge(banner)} aria-label=${t('dismiss')} title=${t('dismiss')}><${Icon} name="close" size=${16} /></button>
    </div>`)}</div>`;
}
