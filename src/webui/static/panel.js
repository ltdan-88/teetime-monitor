// The tip cards at the bottom of the Overview: your next round, the best window this week, the best time with friends
// and the best weather. Each card carries its own little scene for the forecast it is about (scene.js); on a narrow
// screen they swipe, on a wide one they all sit in a row. Tapping a card opens that day.

import { html, t, useState, useEffect, useRef, Icon, api, query, dayLabel, temperature, windSpeed, round, conditionKind } from '/lib.js';
import { Scene, SceneDefs, seasonOf } from '/scene.js';

function conditionText(code) {
  const named = t('wmo.' + code);
  if (named !== 'wmo.' + code) return named;
  const kind = conditionKind(code);
  return kind ? t('cond.' + kind) : '';
}

/** "in 1 d 4 h", "in 3 h 20 min", "in 45 min", "now". */
export function countdownText(date, time, now = new Date()) {
  const minutes = Math.round((new Date(`${date}T${time}:00`) - now) / 60000);
  if (!(minutes > 0)) return t('panel.now');
  if (minutes >= 24 * 60) return t('panel.in_days', { d: Math.floor(minutes / 1440), h: Math.round((minutes % 1440) / 60) });
  if (minutes >= 60) return t('panel.in_hours', { h: Math.floor(minutes / 60), m: minutes % 60 });
  return t('panel.in_minutes', { m: minutes });
}

const firstName = (name) => (name.includes(',') ? name.split(',')[1] : name).trim().split(/\s+/)[0];

function names(list) {
  const first = list.map((p) => firstName(p.name));
  return first.length > 1 ? first.slice(0, -1).join(', ') + t('panel.and') + first[first.length - 1] : first[0];
}

const initials = (name) => {
  const parts = name.includes(',') ? name.split(',').reverse() : name.split(/\s+/);
  return parts.map((part) => part.trim()[0] || '').join('').slice(0, 2).toUpperCase();
};

/** A round avatar: the initials today, in the blue or pink of the player lists; a photo can take the same place later. */
function Avatar({ player }) {
  return html`<span class=${'tp-av ' + (player.gender === 'female' ? 'f' : 'm')} title=${player.name}>${initials(player.name)}</span>`;
}

function Chips({ weather, units }) {
  const mph = units === 'imperial';
  const high = weather.temp != null ? temperature(weather.temp, units) + '°' : null;
  const low = weather.temp_low != null ? ' / ' + temperature(weather.temp_low, units) + '°' : '';
  return html`<span class="tp-chips">
    ${high && html`<span class="tp-temp">${high}${low}</span>`}
    ${weather.rain != null && html`<span class="tp-rain">${round(weather.rain)} %</span>`}
    ${weather.wind != null && html`<span class="tp-wind">${windSpeed(weather.wind, units)} ${mph ? 'mph' : 'km/h'}</span>`}
  </span>`;
}

const VARIANT = { next_round: 'roll', best_window: 'chip', friends: 'trio', best_weather: 'wobble' };
const PHASE = { next_round: 0, best_window: 2.3, friends: 4.1, best_weather: 6.2 }; // seconds into the loop, so the cards never move in step

function Card({ card, units, onOpen, now, south }) {
  const w = card.weather;
  const kind = card.kind;
  let sub = '';
  if (kind === 'next_round') sub = `${card.course} · ${t('panel.done_about', { time: card.finish })}`;
  else if (kind === 'best_window') sub = `${t('free', { n: card.free })} · ${conditionText(w.code)}`;
  else if (kind === 'friends') sub = t(card.friends.length > 1 ? 'panel.friends_many' : 'panel.friends_one', { names: names(card.friends), n: card.free });
  else sub = conditionText(w.code);
  const title = kind === 'best_weather' ? dayLabel(card.date) : `${dayLabel(card.date)} · ${card.time}`;
  return html`<button class="tp-card" onClick=${() => onOpen(card)} aria-label=${t('panel.' + kind) + ': ' + title}>
    <${Scene} mood=${w.mood} wind=${w.wind} variant=${VARIANT[kind]} phase=${PHASE[kind]} friends=${(card.friends || []).map((p) => p.gender)} season=${seasonOf(card.date, south)} seed=${card.kind + '|' + card.date} />
    <span class="tp-text">
      <span class="tp-top"><span class="tp-label">${t('panel.' + kind)}</span>${kind === 'next_round' && html`<span class="tp-count">${countdownText(card.date, card.time, now)}</span>`}</span>
      <span class="tp-main"><span>${title}</span>
        ${kind === 'friends' ? html`<span class="tp-avs">${card.friends.slice(0, 3).map((p) => html`<${Avatar} key=${p.name} player=${p} />`)}</span>` : html`<${Icon} name="chevron" size=${18} />`}</span>
      <span class="tp-sub">${sub}</span>
      <${Chips} weather=${w} units=${units} />
    </span>
  </button>`;
}

/** `refQuery`: which club the cards are for ({slug} or {club_id, name}); `dataKey` changes when the days did. */
export function BottomPanel({ refQuery, course, dataKey, ready, units, onOpen }) {
  const [cards, setCards] = useState([]);
  const [south, setSouth] = useState(false); // the club lies south of the equator: the seasons run the other way
  const [index, setIndex] = useState(0);
  const [scrollable, setScrollable] = useState(false);
  const track = useRef(null);

  useEffect(() => {
    if (!ready || !course) return undefined;
    let cancelled = false;
    api('/api/panel' + query({ ...refQuery, course }))
      .then((result) => { if (cancelled) return; setCards(result.cards || []); setSouth(!!result.south); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [dataKey, ready, course]);

  useEffect(() => {
    const el = track.current;
    if (!el) return undefined;
    const measure = () => setScrollable(el.scrollWidth > el.clientWidth + 2);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [cards.length]);

  if (cards.length === 0) return null;
  const now = new Date();
  const scrolled = () => {
    const el = track.current;
    if (!el) return; // a scroll event that arrives as the cards are switched off
    const kids = el.children;
    const step = kids.length > 1 ? kids[1].offsetLeft - kids[0].offsetLeft : el.clientWidth;
    setIndex(Math.max(0, Math.min(cards.length - 1, Math.round(el.scrollLeft / step))));
  };
  return html`<section class="tp" role="region" aria-roledescription="carousel" aria-label=${t('panel.title')}>
    <${SceneDefs} />
    <div class="tp-track" ref=${track} onScroll=${scrolled}>
      ${cards.map((card) => html`<${Card} key=${card.kind} card=${card} units=${units} onOpen=${onOpen} now=${now} south=${south} />`)}
    </div>
    ${scrollable && html`<div class="tp-dots" aria-hidden="true">${cards.map((card, i) => html`<span key=${card.kind} class=${i === index ? 'on' : ''}></span>`)}</div>`}
  </section>`;
}
