// The Overview's day cards: header (weather, pick/booking/lock badge, occupancy), expandable slots.

import {
  html, t, Icon, Condition, dayLabel, opensText, temperature, windSpeed, amount, round, hcpText, occupancyColor,
} from '/lib.js';

function pickTooltip(pick) {
  const parts = (pick.reasons || []).map((key) => t('reason.' + key)).filter((text, i) => text !== 'reason.' + pick.reasons[i]);
  if (pick.ai_reasons) parts.push(...pick.ai_reasons);
  return parts.length ? t('tip.pick_reasons', { reasons: parts.join(' · ') }) : t('tip.pick');
}

export function Badge({ day }) {
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
    return html`<span class="pill quiet" title=${t('tip.alt', { time: alt.time, course: alt.course, holes: alt.holes })}><${Icon} name="star" size=${15} />${alt.time} · ${alt.holes}H</span>`;
  }
  if (pick && pick.unplayable && pick.unplayable.length) {
    const reasons = [...pick.unplayable].sort();
    const dark = reasons.length === 1 && reasons[0] === 'daylight';
    const key = dark ? 'tip.no_pick_daylight' : reasons.length === 1 && reasons[0] === 'weather' ? 'tip.no_pick_weather' : 'tip.no_pick_both';
    return html`<span class="pill quiet" title=${t(key)}><${Icon} name=${dark ? 'moon' : 'rain'} size=${16} /></span>`;
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

function DayHeader({ day, open, onToggle, units }) {
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
        ${w && w.temp_high != null && html`<${Icon} name="thermo" size=${16} class="dim" />${temperature(w.temp_high, units)}°/${temperature(w.temp_low, units)}°`}
      </span>
      <span class="small rain" title=${rainTip}>
        ${w && html`<${Icon} name="drop" size=${15} />${round(w.rain_avg)}%`}
      </span>
      <span class="small wind" title=${t('tip.wind')}>
        ${w && w.wind_peak != null && html`<${Icon} name="wind" size=${15} />${windSpeed(w.wind_peak, units)}`}
      </span>
      <span class="sun" title=${t('tip.sun')}>${day.sunrise && day.sunset ? `↑${day.sunrise} ↓${day.sunset}` : ''}</span>
      <span class="badge-slot"><${Badge} day=${day} /></span>
      <span class="heat" aria-hidden="true">${day.heat.map((ratio) => html`<span style=${{ background: occupancyColor(ratio) }}></span>`)}</span>
    </button>
    ${day.events.length > 0 && html`<div class="events">${day.events.join(' · ')}</div>`}
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

function SlotRow({ slot, day, units, showHandicaps, onPick }) {
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
  const clickable = !blocked && !slot.past;
  if (clickable) classes.push('clickable');
  const activate = () => clickable && onPick(day, slot);
  return html`
    <div class=${classes.join(' ')} data-slot=${day.date + ' ' + slot.time} role=${clickable ? 'button' : null} tabindex=${clickable ? 0 : null}
      title=${clickable ? t(slot.booked_by_you ? 'booking.cancel_hint' : 'booking.mark_hint') : null}
      onClick=${activate} onKeyDown=${(event) => (event.key === 'Enter' || event.key === ' ') && (event.preventDefault(), activate())}>
      <span class="time">
        <span style="width:1rem;display:inline-flex">
          ${slot.recommended ? html`<${Icon} name="star" size=${14} style="color:var(--accent);fill:var(--accent)" />` : slot.too_late ? html`<${Icon} name="moon" size=${14} class="dim" />` : null}
        </span>
        <span style=${slot.booked_by_you ? { fontWeight: 700 } : null}>${slot.time}</span>
      </span>
      ${blocked
        ? html`<span class="people blocked-note"><span class="dim" style="font-style:italic;font-size:0.8125rem">${slot.block_reason || t('not_bookable')}</span></span>`
        : html`
          <span class="seats" title=${t('tip.seats', { booked: slot.booked, capacity })}>${seats}</span>
          <span class="dim free">${t('free', { n: Math.max(0, capacity - slot.booked) })}</span>
          <span class="people">
            <${PlayerNames} slot=${slot} showHandicaps=${showHandicaps} />
            ${slot.booked_by_you && html`<span class="note" style="color:var(--accent)"><${Icon} name="flag" size=${14} style="fill:currentColor" />${t('you')}</span>`}
            ${slot.sunrise && html`<span class="note"><${Icon} name="sunrise" size=${16} />${t('sunrise', { time: day.sunrise })}</span>`}
            ${slot.sunset && html`<span class="note"><${Icon} name="sunset" size=${16} />${t('sunset', { time: day.sunset })}</span>`}
          </span>`}
      <span class="wx">${w && html`<${Condition} code=${w.code} size=${20} />`}</span>
      <span class="cell temp">${w && w.temp != null ? temperature(w.temp, units) + '°' : ''}</span>
      <span class="cell rain">${w && w.rain != null ? round(w.rain) + '%' + (w.rain_mm ? '/' + amount(w.rain_mm, units) : '') : ''}</span>
      <span class="cell wind">${w && w.wind != null ? windSpeed(w.wind, units) : ''}</span>
    </div>`;
}

export function DayCard({ day, open, onToggle, units, showHandicaps, onPick }) {
  return html`
    <section class=${'card' + (open ? ' open' : '')}>
      <${DayHeader} day=${day} open=${open} onToggle=${onToggle} units=${units} />
      ${open && html`<div class="slots">${day.slots.map((slot) => html`<${SlotRow} key=${slot.time} slot=${slot} day=${day} units=${units} showHandicaps=${showHandicaps} onPick=${onPick} />`)}</div>`}
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
