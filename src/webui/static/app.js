// Teetime Monitor web UI: the Overview (M1). Preact + htm, no build step.
// Data comes from /api/* (src/webui/server.py); weather arrives metric and is converted here.

import { html, render, useState, useEffect, useRef, useCallback } from '/vendor/htm-preact.js';

// ---------------------------------------------------------------- strings (EN / DE)

const STRINGS = {
  en: {
    'app.title': 'Teetime Monitor',
    'club': 'Club',
    'course': 'Course',
    'refresh': 'Refresh',
    'refreshing': 'Updating…',
    'legend': 'Legend',
    'close': 'Close',
    'free': '{n} free',
    'anonymous': 'anonymous',
    'not_bookable': 'not bookable',
    'sunrise': 'sunrise {time}',
    'sunset': 'sunset {time}',
    'you': 'you',
    'expand': 'Show times for {day}',
    'collapse': 'Hide times for {day}',
    'updated_never': 'never updated',
    'updated_just_now': 'updated just now',
    'updated_minutes': 'updated {n} min ago',
    'updated_hours': 'updated {n} h ago',
    'updated_days': 'updated {n} d ago',
    'rain_all_day': 'rain all day',
    'tip.pick': 'Recommended pick',
    'tip.pick_reasons': 'Picked for: {reasons}',
    'tip.alt': 'Too dark to finish here — a shorter round still fits: {time} on {course} ({holes} holes).',
    'tip.no_pick_daylight': 'No pick: too dark to finish a round from your window',
    'tip.no_pick_weather': 'No pick: no dry tee times in your window',
    'tip.no_pick_both': 'No pick: too dark or too wet in your window',
    'tip.locked': 'Not bookable yet — opens {when}',
    'tip.booked': 'Your booking',
    'tip.temp': 'High / low, 08:00–20:00',
    'tip.rain': 'Average rain chance, 08:00–20:00',
    'tip.wind': 'Peak wind, 08:00–20:00',
    'tip.sun': 'Sunrise and sunset',
    'tip.seats': '{booked} of {capacity} seats taken',
    'reason.dry': 'dry',
    'reason.calm': 'calm',
    'reason.mild': 'mild',
    'reason.room_around': 'room around you',
    'reason.quiet': 'quiet hour',
    'reason.daylight_spare': 'daylight to spare',
    'cond.sun': 'clear sky',
    'cond.partly': 'mostly clear / partly cloudy',
    'cond.cloud': 'overcast',
    'cond.fog': 'fog',
    'cond.drizzle': 'drizzle',
    'cond.rain': 'rain / rain showers',
    'cond.snow': 'snow / snow showers',
    'cond.storm': 'thunderstorm',
    'legend.title': 'Legend',
    'legend.day': 'Day row',
    'legend.occupancy': 'Occupancy bar (six two-hour blocks, 08–20)',
    'legend.occ.open': 'under half booked',
    'legend.occ.mid': 'half booked or more',
    'legend.occ.full': 'fully booked',
    'legend.occ.none': 'nothing to book',
    'legend.markers': 'Markers',
    'legend.pick': 'recommended pick for the day',
    'legend.booked': 'your booking',
    'legend.locked': 'not bookable yet, opens at the time shown',
    'legend.recommended': 'recommended time',
    'legend.too_late': 'too late to finish before dark',
    'legend.players': 'Player names',
    'legend.male': 'male',
    'legend.female': 'female',
    'legend.friend': 'friend (bold, ★)',
    'legend.anon': 'seat taken by someone whose name is not shown',
    'empty.no_clubs.title': 'No saved clubs yet',
    'empty.no_clubs.text': 'Add a club in the terminal app (teetime-monitor) for now; adding clubs here is coming next.',
    'empty.no_data.title': 'Nothing scraped for this course yet',
    'empty.no_data.text': 'Press Refresh to fetch the tee sheet, or pick another club or course.',
    'empty.updating': 'Fetching the tee sheet…',
    'error.title': 'Could not load',
    'error.text': 'The app answered with an error. Reload the page; if it keeps happening, run teetime-monitor-web --help in the terminal.',
    'error.gone.title': 'The app was closed',
    'error.gone.text': 'Start Teetime Monitor again to continue.',
    'error.refresh': 'Refresh failed: {error}',
    'hours': 'h',
  },
  de: {
    'app.title': 'Teetime Monitor',
    'club': 'Club',
    'course': 'Platz',
    'refresh': 'Aktualisieren',
    'refreshing': 'Aktualisiere…',
    'legend': 'Legende',
    'close': 'Schließen',
    'free': '{n} frei',
    'anonymous': 'anonym',
    'not_bookable': 'nicht buchbar',
    'sunrise': 'Sonnenaufgang {time}',
    'sunset': 'Sonnenuntergang {time}',
    'you': 'du',
    'expand': 'Startzeiten für {day} anzeigen',
    'collapse': 'Startzeiten für {day} ausblenden',
    'updated_never': 'noch nie aktualisiert',
    'updated_just_now': 'gerade aktualisiert',
    'updated_minutes': 'vor {n} Min. aktualisiert',
    'updated_hours': 'vor {n} Std. aktualisiert',
    'updated_days': 'vor {n} T. aktualisiert',
    'rain_all_day': 'ganztägig Regen',
    'tip.pick': 'Empfohlene Auswahl',
    'tip.pick_reasons': 'Ausgewählt wegen: {reasons}',
    'tip.alt': 'Zu dunkel zum Fertigspielen — eine kürzere Runde passt noch: {time} auf {course} ({holes} Loch).',
    'tip.no_pick_daylight': 'Keine Empfehlung: zu dunkel zum Fertigspielen in deinem Zeitfenster',
    'tip.no_pick_weather': 'Keine Empfehlung: keine trockenen Zeiten in deinem Zeitfenster',
    'tip.no_pick_both': 'Keine Empfehlung: zu dunkel oder zu nass in deinem Zeitfenster',
    'tip.locked': 'Noch nicht buchbar — öffnet {when}',
    'tip.booked': 'Deine Buchung',
    'tip.temp': 'Höchst-/Tiefstwert, 08:00–20:00',
    'tip.rain': 'Durchschnittliche Regenwahrscheinlichkeit, 08:00–20:00',
    'tip.wind': 'Spitzenwind, 08:00–20:00',
    'tip.sun': 'Sonnenaufgang und -untergang',
    'tip.seats': '{booked} von {capacity} Plätzen belegt',
    'reason.dry': 'trocken',
    'reason.calm': 'kaum Wind',
    'reason.mild': 'mild',
    'reason.room_around': 'viel Platz um dich',
    'reason.quiet': 'ruhige Stunde',
    'reason.daylight_spare': 'Tageslicht in Reserve',
    'cond.sun': 'klarer Himmel',
    'cond.partly': 'meist klar / teils bewölkt',
    'cond.cloud': 'bedeckt',
    'cond.fog': 'Nebel',
    'cond.drizzle': 'Nieselregen',
    'cond.rain': 'Regen / Schauer',
    'cond.snow': 'Schnee / Schneeschauer',
    'cond.storm': 'Gewitter',
    'legend.title': 'Legende',
    'legend.day': 'Tageszeile',
    'legend.occupancy': 'Belegungsbalken (sechs Zwei-Stunden-Blöcke, 08–20)',
    'legend.occ.open': 'weniger als halb gebucht',
    'legend.occ.mid': 'halb gebucht oder mehr',
    'legend.occ.full': 'ausgebucht',
    'legend.occ.none': 'nichts zu buchen',
    'legend.markers': 'Markierungen',
    'legend.pick': 'empfohlene Auswahl des Tages',
    'legend.booked': 'deine Buchung',
    'legend.locked': 'noch nicht buchbar, öffnet zur angezeigten Zeit',
    'legend.recommended': 'empfohlene Zeit',
    'legend.too_late': 'zu spät, um vor Dunkelheit fertig zu werden',
    'legend.players': 'Spielernamen',
    'legend.male': 'männlich',
    'legend.female': 'weiblich',
    'legend.friend': 'Freund (fett, ★)',
    'legend.anon': 'Platz belegt, Name wird nicht angezeigt',
    'empty.no_clubs.title': 'Noch keine gespeicherten Clubs',
    'empty.no_clubs.text': 'Lege einen Club vorerst in der Terminal-App an (teetime-monitor); das Hinzufügen hier folgt als Nächstes.',
    'empty.no_data.title': 'Für diesen Platz wurde noch nichts abgerufen',
    'empty.no_data.text': 'Drücke „Aktualisieren“, um die Startzeiten zu laden, oder wähle einen anderen Club oder Platz.',
    'empty.updating': 'Startzeiten werden geladen…',
    'error.title': 'Laden fehlgeschlagen',
    'error.text': 'Die App hat mit einem Fehler geantwortet. Lade die Seite neu; falls es bleibt, starte teetime-monitor-web --help im Terminal.',
    'error.gone.title': 'Die App wurde beendet',
    'error.gone.text': 'Starte Teetime Monitor erneut, um weiterzumachen.',
    'error.refresh': 'Aktualisieren fehlgeschlagen: {error}',
    'hours': 'Uhr',
  },
};

let LANG = 'en';
function t(key, vars) {
  let text = (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.en[key] || key;
  if (vars) for (const name of Object.keys(vars)) text = text.replaceAll('{' + name + '}', vars[name]);
  return text;
}

// ---------------------------------------------------------------- formatting

const round = (n) => Math.round(n);
const temperature = (c, units) => round(units === 'imperial' ? (c * 9) / 5 + 32 : c);
const windSpeed = (kph, units) => round(units === 'imperial' ? kph / 1.609344 : kph);
const amount = (mm, units) =>
  units === 'imperial' ? (mm / 25.4).toFixed(2) + 'in' : mm.toFixed(1) + 'mm';

function parseDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/** "Sat 3 Oct": weekday, day, month, in the app's language. */
function dayLabel(iso) {
  const date = parseDate(iso);
  const weekday = date.toLocaleDateString(LANG, { weekday: 'short' }).replace(/\./g, '');
  const month = date.toLocaleDateString(LANG, { month: 'short' }).replace(/\./g, '');
  return `${weekday} ${date.getDate()} ${month}`;
}

/** The lock badge's "Wed 21:00" from an ISO string with the club's own offset: read as written,
 *  so it names the club's local opening time whatever time zone this browser is in. */
function opensText(locked) {
  const isoDate = locked.opens_at.slice(0, 10);
  const weekday = parseDate(isoDate).toLocaleDateString(LANG, { weekday: 'short' }).replace(/\./g, '');
  return locked.hour_known ? `${weekday} ${locked.opens_at.slice(11, 16)}` : `${weekday} ${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}.`;
}

function updatedText(iso) {
  if (!iso) return t('updated_never');
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return t('updated_just_now');
  if (minutes < 60) return t('updated_minutes', { n: minutes });
  if (minutes < 60 * 48) return t('updated_hours', { n: Math.round(minutes / 60) });
  return t('updated_days', { n: Math.round(minutes / 1440) });
}

function conditionKind(code) {
  if (code == null) return null;
  if (code === 0) return 'sun';
  if (code <= 2) return 'partly';
  if (code === 3) return 'cloud';
  if (code === 45 || code === 48) return 'fog';
  if (code >= 51 && code <= 57) return 'drizzle';
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return 'rain';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'snow';
  if (code >= 95) return 'storm';
  return null;
}

const occupancyColor = (ratio) => (ratio == null ? 'var(--faint)' : ratio >= 1 ? 'var(--red)' : ratio >= 0.5 ? 'var(--orange)' : 'var(--green)');

// ---------------------------------------------------------------- icons

const CLOUD = 'M7 17a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 8.2 3.9 3.9 0 0 1 17 17z';
const ICONS = {
  chevron: html`<path d="M9 6l6 6-6 6" />`,
  down: html`<path d="M6 9l6 6 6-6" />`,
  refresh: html`<path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" />`,
  info: html`<circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8v.1" />`,
  star: html`<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 17l-5.2 2.7 1-5.9-4.3-4.1 5.9-.8z" />`,
  moon: html`<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />`,
  flag: html`<path d="M5 21V4M5 4h11l-2 4 2 4H5" />`,
  lock: html`<rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" />`,
  thermo: html`<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z" />`,
  drop: html`<path d="M12 3.5s6 6.2 6 10.5a6 6 0 0 1-12 0c0-4.3 6-10.5 6-10.5z" />`,
  wind: html`<path d="M3 9h10a3 3 0 1 0-3-3M3 15h14a3 3 0 1 1-3 3M3 12h7" />`,
  sunrise: html`<path d="M4 18h16M7 18a5 5 0 0 1 10 0M12 4v4M9.5 6.5L12 4l2.5 2.5" />`,
  sunset: html`<path d="M4 18h16M7 18a5 5 0 0 1 10 0M12 8V4M9.5 5.5L12 8l2.5-2.5" />`,
  sun: html`<circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" />`,
  partly: html`<circle cx="8.5" cy="8" r="2.8" /><path d="M8.5 2.5v1.3M3 8h1.3M4.6 4.1l.9.9M12.4 4.1l-.9.9" /><path d="M8 19a3.6 3.6 0 0 1-.4-7.2A5 5 0 0 1 17 11a3.5 3.5 0 0 1 0 8z" />`,
  cloud: html`<path d=${CLOUD} />`,
  fog: html`<path d="M7 13a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 4.2 3.9 3.9 0 0 1 17 13z" /><path d="M5 16.5h14M7 20h10" />`,
  drizzle: html`<path d="M7 13a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 4.2 3.9 3.9 0 0 1 17 13z" /><path d="M9 16.5v.1M13 17.5v.1M16.5 16.5v.1M11 20.5v.1M15 21v.1" />`,
  rain: html`<path d="M7 13a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 4.2 3.9 3.9 0 0 1 17 13z" /><path d="M8 16l-1 3M12 16l-1 3M16 16l-1 3" />`,
  snow: html`<path d="M7 13a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 4.2 3.9 3.9 0 0 1 17 13z" /><path d="M8 17v.1M12 18.5v.1M16 17v.1M10 21v.1M14 21.5v.1" />`,
  storm: html`<path d="M7 13a4 4 0 0 1-.5-7.97A5.5 5.5 0 0 1 17.2 4.2 3.9 3.9 0 0 1 17 13z" /><path d="M12.5 13l-2 4h3l-2 4" />`,
};

function Icon({ name, size = 20, ...rest }) {
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" aria-hidden="true" ...${rest}>${ICONS[name]}</svg>`;
}

function Condition({ code, size = 24 }) {
  const kind = conditionKind(code);
  if (!kind) return null;
  return html`<span class="cond" title=${t('cond.' + kind)}><${Icon} name=${kind} size=${size} /></span>`;
}

// ---------------------------------------------------------------- API

async function api(path, options) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  if (!response.ok) {
    const error = new Error('HTTP ' + response.status);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
const post = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

// ---------------------------------------------------------------- day card

function pickTooltip(pick) {
  const known = (pick.reasons || []).map((key) => 'reason.' + key).filter((key) => STRINGS.en[key]);
  const parts = known.map((key) => t(key));
  if (pick.ai_reasons) parts.push(...pick.ai_reasons);
  return parts.length ? t('tip.pick_reasons', { reasons: parts.join(' · ') }) : t('tip.pick');
}

function Badge({ day }) {
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

function DayHeader({ day, open, onToggle, units }) {
  const w = day.weather;
  const label = dayLabel(day.date);
  return html`
    <button class="dh" onClick=${onToggle} aria-expanded=${open} aria-label=${t(open ? 'collapse' : 'expand', { day: label })}>
      <${Icon} name="chevron" size=${18} class="chev" />
      <span class="day">${label}</span>
      <span>${w && html`<${Condition} code=${w.code} />`}</span>
      <span class="temp" title=${t('tip.temp')}>
        ${w && w.temp_high != null && html`<${Icon} name="thermo" size=${16} class="dim" />${temperature(w.temp_high, units)}°/${temperature(w.temp_low, units)}°`}
      </span>
      <span class="small rain" title=${t('tip.rain')}>
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
  `;
}

function PlayerNames({ slot }) {
  const named = slot.players.length;
  const anonymous = Math.max(0, slot.booked - named);
  if (!named && !anonymous) return null;
  const parts = [];
  slot.players.forEach((player, index) => {
    const classes = ['name'];
    if (player.friend) classes.push('f');
    if (player.gender === 'female') classes.push('alt');
    parts.push(html`<span class=${classes.join(' ')}>${player.friend ? '★ ' : ''}${player.name}</span>${index < named - 1 || anonymous ? ', ' : ''}`);
  });
  if (anonymous) parts.push(html`<span class="name anon">${t('anonymous')}${anonymous > 1 ? ` ×${anonymous}` : ''}</span>`);
  return html`<span class="names">${parts}</span>`;
}

function SlotRow({ slot, units }) {
  const capacity = slot.capacity > 0 ? slot.capacity : 4;
  const friendSeat = slot.players.some((player) => player.friend);
  const seats = Array.from({ length: capacity }, (_, i) => {
    let cls = 'seat';
    if (i < slot.booked) cls += friendSeat && i === 0 && !slot.booked_by_you ? ' friend' : ' taken';
    return html`<span class=${cls} style=${slot.booked_by_you && i === 0 ? { background: 'var(--blue)' } : null}></span>`;
  });
  const w = slot.weather;
  const classes = ['slot'];
  if (slot.past) classes.push('past');
  if (slot.booked_by_you) classes.push('mine');
  if (slot.block_reason !== null && slot.block_reason !== undefined) classes.push('blocked');
  const blocked = classes.includes('blocked');
  return html`
    <div class=${classes.join(' ')}>
      <span class="time">
        <span style="width:16px;display:inline-flex">
          ${slot.recommended ? html`<${Icon} name="star" size=${14} style="color:var(--blue);fill:var(--blue)" />` : slot.too_late ? html`<${Icon} name="moon" size=${14} class="dim" />` : null}
        </span>
        <span style=${slot.booked_by_you ? { fontWeight: 700 } : null}>${slot.time}</span>
      </span>
      ${blocked
        ? html`<span class="people blocked-note"><span class="dim" style="font-style:italic;font-size:13px">${slot.block_reason || t('not_bookable')}</span></span>`
        : html`
          <span class="seats" title=${t('tip.seats', { booked: slot.booked, capacity })}>${seats}</span>
          <span class="dim free">${t('free', { n: Math.max(0, capacity - slot.booked) })}</span>
          <span class="people">
            <${PlayerNames} slot=${slot} />
            ${slot.booked_by_you && html`<span class="note" style="color:var(--blue)"><${Icon} name="flag" size=${14} style="fill:currentColor" />${t('you')}</span>`}
            ${slot.sunrise && html`<span class="note"><${Icon} name="sunrise" size=${16} />${t('sunrise', { time: slot.sunrise_time })}</span>`}
            ${slot.sunset && html`<span class="note"><${Icon} name="sunset" size=${16} />${t('sunset', { time: slot.sunset_time })}</span>`}
          </span>`}
      <span class="wx">${w && html`<${Condition} code=${w.code} size=${20} />`}</span>
      <span class="cell temp">${w && w.temp != null ? temperature(w.temp, units) + '°' : ''}</span>
      <span class="cell rain">${w && w.rain != null ? round(w.rain) + '%' + (w.rain_mm ? '/' + amount(w.rain_mm, units) : '') : ''}</span>
      <span class="cell wind">${w && w.wind != null ? windSpeed(w.wind, units) : ''}</span>
    </div>`;
}

function DayCard({ day, open, onToggle, units }) {
  const slots = open ? day.slots.map((slot) => ({ ...slot, sunrise_time: day.sunrise, sunset_time: day.sunset })) : [];
  return html`
    <section class=${'card' + (open ? ' open' : '')}>
      <${DayHeader} day=${day} open=${open} onToggle=${onToggle} units=${units} />
      ${open && html`<div class="slots">${slots.map((slot) => html`<${SlotRow} key=${slot.time} slot=${slot} units=${units} />`)}</div>`}
    </section>`;
}

// ---------------------------------------------------------------- chrome

function Picker({ label, value, options, onChange }) {
  return html`
    <label class="picker">
      <span class="sr-only">${label}</span>
      <select value=${value} onChange=${(event) => onChange(event.target.value)}>
        ${options.map((option) => html`<option value=${option.value} selected=${option.value === value}>${option.label}</option>`)}
      </select>
      <${Icon} name="down" size=${16} />
    </label>`;
}

function Legend({ onClose }) {
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const swatch = (color) => html`<span class="swatch" style=${{ background: color }}></span>`;
  return html`
    <div class="scrim" onClick=${(event) => event.target === event.currentTarget && onClose()}>
      <div class="sheet" role="dialog" aria-modal="true" aria-label=${t('legend.title')}>
        <h2>${t('legend.title')}</h2>
        <dl>
          <dt>${swatch('var(--green)')}</dt><dd>${t('legend.occ.open')}</dd>
          <dt>${swatch('var(--orange)')}</dt><dd>${t('legend.occ.mid')}</dd>
          <dt>${swatch('var(--red)')}</dt><dd>${t('legend.occ.full')}</dd>
          <dt>${swatch('var(--faint)')}</dt><dd>${t('legend.occ.none')}</dd>
        </dl>
        <dl>
          <dt><span class="pill pick"><${Icon} name="star" size=${14} style="fill:currentColor" />09:10</span></dt><dd>${t('legend.pick')}</dd>
          <dt><span class="pill booked"><${Icon} name="flag" size=${14} style="fill:currentColor" />11:00</span></dt><dd>${t('legend.booked')}</dd>
          <dt><span class="pill quiet"><${Icon} name="lock" size=${14} />Wed 21:00</span></dt><dd>${t('legend.locked')}</dd>
          <dt><${Icon} name="star" size=${16} style="color:var(--blue);fill:var(--blue)" /></dt><dd>${t('legend.recommended')}</dd>
          <dt><${Icon} name="moon" size=${16} class="dim" /></dt><dd>${t('legend.too_late')}</dd>
        </dl>
        <dl>
          <dt><span class="name">Max</span></dt><dd>${t('legend.male')}</dd>
          <dt><span class="name alt">Erika</span></dt><dd>${t('legend.female')}</dd>
          <dt><span class="name f">★ Ben</span></dt><dd>${t('legend.friend')}</dd>
          <dt><span class="name anon">${t('anonymous')}</span></dt><dd>${t('legend.anon')}</dd>
        </dl>
        <button class="btn" onClick=${onClose}>${t('close')}</button>
      </div>
    </div>`;
}

function Empty({ title, text }) {
  return html`<div class="empty"><h2>${title}</h2><p>${text}</p></div>`;
}

// ---------------------------------------------------------------- app

function App() {
  const [boot, setBoot] = useState(null);
  const [slug, setSlug] = useState(null);
  const [course, setCourse] = useState(null);
  const [overview, setOverview] = useState(null);
  // The open day lives in the address (#2026-10-12), so a day can be linked to.
  const [openDate, setOpenDate] = useState(() => location.hash.slice(1) || null);
  const [refresh, setRefresh] = useState({ running: false, error: null });
  const [showLegend, setShowLegend] = useState(false);
  const [failure, setFailure] = useState(null); // 'gone' | 'error'
  const [, tick] = useState(0);
  const selection = useRef({ slug: null, course: null });
  selection.current = { slug, course };

  useEffect(() => {
    history.replaceState(null, '', openDate ? '#' + openDate : location.pathname);
  }, [openDate]);

  // Page title and language follow the app's language once known.
  useEffect(() => {
    document.documentElement.lang = LANG;
    document.title = t('app.title');
  });

  const handleError = useCallback((error) => {
    setFailure(error && error.status === 403 ? 'gone' : error && error.name === 'TypeError' ? 'gone' : 'error');
  }, []);

  const loadOverview = useCallback(async (nextSlug, nextCourse) => {
    try {
      const result = await api(`/api/overview?slug=${encodeURIComponent(nextSlug)}${nextCourse ? `&course=${encodeURIComponent(nextCourse)}` : ''}`);
      if (selection.current.slug !== nextSlug) return;
      setOverview(result);
      setCourse((current) => (nextCourse || current === result.course ? current : result.course));
      setOpenDate((current) => (current && result.days.some((day) => day.date === current) ? current : result.days.length ? result.days[0].date : null));
      setFailure(null);
    } catch (error) {
      handleError(error);
    }
  }, []);

  // First load.
  useEffect(() => {
    api('/api/bootstrap')
      .then((result) => {
        LANG = result.language === 'de' ? 'de' : 'en';
        setBoot(result);
        const last = result.last && result.clubs.find((club) => club.slug === result.last.slug);
        const first = last || result.clubs[0];
        if (first) {
          setSlug(first.slug);
          setCourse(last ? result.last.course : first.default_course || null);
        }
      })
      .catch(handleError);
  }, []);

  // Selection changed: load, remember it, and let the scraper fetch what is due.
  useEffect(() => {
    if (!slug) return;
    setOverview(null);
    loadOverview(slug, course);
    startRefresh(false);
  }, [slug]);

  useEffect(() => {
    if (!slug || !course) return;
    loadOverview(slug, course);
    post('/api/last', { slug, course }).catch(() => {});
  }, [course]);

  // Keep-alive for the server, a gentle re-read of the data, and a relative-time tick.
  useEffect(() => {
    const ping = setInterval(() => post('/api/ping', {}).catch(handleError), 5000);
    post('/api/ping', {}).catch(() => {});
    const reload = setInterval(() => {
      const { slug: s, course: c } = selection.current;
      if (s) loadOverview(s, c);
    }, 30000);
    const clock = setInterval(() => tick((n) => n + 1), 30000);
    return () => [ping, reload, clock].forEach(clearInterval);
  }, []);

  // While a refresh runs, poll it; when it ends, re-read the overview.
  useEffect(() => {
    if (!refresh.running || !slug) return;
    const poll = setInterval(async () => {
      try {
        const status = await api(`/api/refresh/status?slug=${encodeURIComponent(slug)}`);
        if (!status.running) {
          setRefresh({ running: false, error: status.error });
          loadOverview(slug, selection.current.course);
        }
      } catch (error) {
        handleError(error);
      }
    }, 1200);
    return () => clearInterval(poll);
  }, [refresh.running, slug]);

  function startRefresh(force) {
    const target = selection.current.slug || slug;
    if (!target) return;
    post('/api/refresh', { slug: target, force })
      .then((status) => setRefresh({ running: !!status.running, error: null }))
      .catch(handleError);
  }

  if (failure === 'gone') return html`<${Empty} title=${t('error.gone.title')} text=${t('error.gone.text')} />`;
  if (failure === 'error' && !overview) return html`<${Empty} title=${t('error.title')} text=${t('error.text')} />`;
  if (!boot) return null;
  if (boot.clubs.length === 0) return html`<${Empty} title=${t('empty.no_clubs.title')} text=${t('empty.no_clubs.text')} />`;

  const units = (overview && overview.units) || boot.units;
  const clubOptions = boot.clubs.map((club) => ({ value: club.slug, label: club.name }));
  const courseOptions = ((overview && overview.courses) || []).map((name) => ({ value: name, label: name }));
  const freshness = overview && overview.freshness;
  const empty = overview && overview.days.length === 0;

  return html`
    <div class="app">
      <header class="toolbar">
        <${Picker} label=${t('club')} value=${slug} options=${clubOptions} onChange=${(value) => { setCourse(null); setSlug(value); }} />
        ${courseOptions.length > 0 && html`<${Picker} label=${t('course')} value=${(overview && overview.course) || course} options=${courseOptions} onChange=${setCourse} />`}
        <span class="grow"></span>
        <button class="tool" onClick=${() => startRefresh(true)} disabled=${refresh.running}>
          <${Icon} name="refresh" class=${refresh.running ? 'spin' : ''} />${t(refresh.running ? 'refreshing' : 'refresh')}
        </button>
      </header>
      <main class="main">
        ${!overview && html`<${Empty} title=${t('empty.updating')} text="" />`}
        ${empty && html`<${Empty} title=${refresh.running ? t('empty.updating') : t('empty.no_data.title')} text=${refresh.running ? '' : t('empty.no_data.text')} />`}
        ${overview && overview.days.map((day) => html`
          <${DayCard} key=${day.date} day=${day} open=${openDate === day.date} units=${units}
            onToggle=${() => setOpenDate(openDate === day.date ? null : day.date)} />`)}
      </main>
      <footer class="footer">
        <div class="status">
          <span class=${'dot' + (freshness && freshness.warning ? ' warn' : refresh.running ? ' busy' : '')}></span>
          <span>${refresh.running ? t('refreshing') : updatedText(freshness && freshness.last_success_at)}</span>
          ${refresh.error && html`<span class="warning">${t('error.refresh', { error: refresh.error })}</span>`}
          ${freshness && freshness.warning && html`<span class="warning">${freshness.warning}</span>`}
        </div>
        <button class="tool" style="height:32px;font-size:13px" onClick=${() => setShowLegend(true)}><${Icon} name="info" size=${16} />${t('legend')}</button>
      </footer>
      ${showLegend && html`<${Legend} onClose=${() => setShowLegend(false)} />`}
    </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
