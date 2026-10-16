// The little course scene behind a tip card and on the welcome screen: sky for the weather, a green with a hole and a
// flag, and a golf ball that rolls in and drops into the hole. One drawing per mood (clear, partly, overcast, rain,
// snow); the flag and the clouds move as fast as the wind blows. Everything is CSS animation, so a reader who
// asks for reduced motion gets a still picture (style.css, "tip cards").

import { html } from '/lib.js';

/** The shared gradients, patterns and the sun, defined once per page; the scenes refer to them by id. */
export function SceneDefs() {
  return html`<svg width="0" height="0" aria-hidden="true" style="position: absolute; stroke: none">
    <defs>
      <linearGradient id="tp-rain" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#232838" /><stop offset="1" stop-color="#454c66" /></linearGradient>
      <linearGradient id="tp-partly" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#27477a" /><stop offset="1" stop-color="#6a8fc0" /></linearGradient>
      <linearGradient id="tp-overcast" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#343a52" /><stop offset="1" stop-color="#636a86" /></linearGradient>
      <linearGradient id="tp-clear" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b4f8f" /><stop offset="1" stop-color="#5a9bd8" /></linearGradient>
      <linearGradient id="tp-snow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b3856" /><stop offset="1" stop-color="#7f91b2" /></linearGradient>
      <linearGradient id="tp-scrim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0a0e1e" stop-opacity=".5" /><stop offset=".78" stop-color="#0a0e1e" stop-opacity=".46" /><stop offset="1" stop-color="#0a0e1e" stop-opacity="0" /></linearGradient>
      <radialGradient id="tp-glow"><stop offset="0" stop-color="#ffd60a" stop-opacity=".55" /><stop offset="1" stop-color="#ffd60a" stop-opacity="0" /></radialGradient>
      <pattern id="tp-drops" width="30" height="40" patternUnits="userSpaceOnUse"><path d="M6 2l-3 10M21 22l-3 10" stroke="#a9c4ff" stroke-opacity=".5" stroke-width="1.1" stroke-linecap="round" fill="none" /></pattern>
      <pattern id="tp-flakes-near" width="70" height="70" patternUnits="userSpaceOnUse"><circle cx="14" cy="12" r="2.2" fill="#fff" fill-opacity=".95" /><circle cx="52" cy="30" r="1.9" fill="#fff" fill-opacity=".85" /><circle cx="30" cy="58" r="2.4" fill="#fff" fill-opacity=".95" /></pattern>
      <pattern id="tp-flakes-far" width="50" height="50" patternUnits="userSpaceOnUse"><circle cx="8" cy="6" r="1.5" fill="#fff" fill-opacity=".9" /><circle cx="33" cy="20" r="1.2" fill="#fff" fill-opacity=".8" /><circle cx="18" cy="38" r="1.7" fill="#fff" fill-opacity=".9" /><circle cx="44" cy="44" r="1.1" fill="#fff" fill-opacity=".7" /></pattern>
      <clipPath id="tp-above"><rect x="-14" y="-24" width="28" height="26" /></clipPath>
      <g id="tp-rays" fill="#ffd60a">
        <path d="M0-14L2.2-27L-2.2-27Z" /><path d="M0-14L1.8-22L-1.8-22Z" transform="rotate(30)" /><path d="M0-14L2.2-27L-2.2-27Z" transform="rotate(60)" /><path d="M0-14L1.8-22L-1.8-22Z" transform="rotate(90)" />
        <path d="M0-14L2.2-27L-2.2-27Z" transform="rotate(120)" /><path d="M0-14L1.8-22L-1.8-22Z" transform="rotate(150)" /><path d="M0-14L2.2-27L-2.2-27Z" transform="rotate(180)" /><path d="M0-14L1.8-22L-1.8-22Z" transform="rotate(210)" />
        <path d="M0-14L2.2-27L-2.2-27Z" transform="rotate(240)" /><path d="M0-14L1.8-22L-1.8-22Z" transform="rotate(270)" /><path d="M0-14L2.2-27L-2.2-27Z" transform="rotate(300)" /><path d="M0-14L1.8-22L-1.8-22Z" transform="rotate(330)" />
      </g>
    </defs>
  </svg>`;
}

const CLOUDS = {
  rain: ['#6b7088', '#5f647e'],
  overcast: ['#aeb4c8', '#9ca2b8'],
  snow: ['#c4cde0', '#b3bdd4'],
};

/** Seconds for the flag to wave once and for the clouds to drift across: faster the harder the wind blows. */
export function windTimes(kph) {
  const wind = kph == null ? 8 : kph;
  return { flag: Math.max(0.35, Math.min(2.4, 2.4 - wind * 0.075)), clouds: Math.max(8, Math.min(34, 34 - wind * 0.9)) };
}

// ---- the seasons: ground, trees and the things that fall -------------------------------------------------------------
const SEASONS = {
  spring: { back: '#4f9a4e', front: '#3d8442', green: '#66b85c', leaves: ['#f6c1d6', '#f9dbe6', '#ffffff'], trunk: '#5a4636', water: '#5aa0cc', line: '#7fb56a' },
  summer: { back: '#2a6a45', front: '#1f5a3a', green: '#2f7a50', leaves: ['#1f6b3a', '#2b7d45', '#175a30'], trunk: '#4a3a2c', water: '#4a8fc0', line: '#1b5a34' },
  autumn: { back: '#6e7a3a', front: '#59652f', green: '#7d8a42', leaves: ['#d8742e', '#e8a23a', '#b8402a'], trunk: '#4a3a2c', water: '#4a7fa8', line: '#9a6a2a' },
  winter: { back: '#66755f', front: '#566450', green: '#74846b', leaves: [], trunk: '#4a3a2c', water: '#a9cbe0', line: '#4e5a4a' },
};
const WHITE_GROUND = { back: '#e4eaf4', front: '#cdd7e8', green: '#f4f7fc', water: '#d9e8f5', line: '#c5d0e2' };

/** "spring" | "summer" | "autumn" | "winter" for a date ("YYYY-MM-DD"); `south` swaps the halves of the year. */
export function seasonOf(date, south = false) {
  const month = Number(String(date || '').slice(5, 7)) || new Date().getMonth() + 1;
  const m = south ? ((month + 5) % 12) + 1 : month;
  return m >= 3 && m <= 5 ? 'spring' : m >= 6 && m <= 8 ? 'summer' : m >= 9 && m <= 11 ? 'autumn' : 'winter';
}

const hash = (text) => { let h = 7; for (const c of String(text)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; };

// which features a course has: every card gets another mix, so no two greens look alike
const LAYOUTS = [
  { pond: true, bunker: false, trees: [285] }, { pond: false, bunker: true, trees: [205, 226] }, { pond: true, bunker: true, trees: [] },
  { pond: false, bunker: true, trees: [208, 287] }, { pond: true, bunker: false, trees: [224, 280] }, { pond: false, bunker: false, trees: [200, 222, 284] },
];

/** A tree standing on the ground at (x, base): lush, blossoming, coloured, bare or a pine, by season and snow. */
function Tree({ x, base, size, season, snow, pine, colors, trunk }) {
  const s = size;
  const cap = snow ? html`<ellipse cx="0" cy=${-s * 0.9} rx=${s * 0.3} ry=${s * 0.1} fill="#f4f7fc" />` : null;
  let body;
  if (pine) {
    body = html`<path d=${`M0 ${-s}L${s * 0.22} ${-s * 0.62}H${-s * 0.22}ZM0 ${-s * 0.78}L${s * 0.3} ${-s * 0.34}H${-s * 0.3}ZM0 ${-s * 0.55}L${s * 0.38} ${-s * 0.1}H${-s * 0.38}Z`} fill=${snow ? '#cfd9ea' : '#1c5a35'} />`;
  } else if (season === 'winter' && !snow) {
    body = html`<path class="tp-bare" d=${`M0 0V${-s * 0.55}M0 ${-s * 0.35}l${-s * 0.2} ${-s * 0.22}M0 ${-s * 0.45}l${s * 0.22} ${-s * 0.24}M0 ${-s * 0.58}l${-s * 0.1} ${-s * 0.2}M0 ${-s * 0.58}l${s * 0.1} ${-s * 0.2}`} stroke=${trunk} />`;
  } else {
    const c = snow || season === 'winter' ? ['#dfe7f2', '#cfd9ea', '#e9eff7'] : colors;
    body = html`<rect x="-1" y=${-s * 0.45} width="2" height=${s * 0.45} fill=${trunk} />
      <ellipse cx="0" cy=${-s * 0.72} rx=${s * 0.38} ry=${s * 0.32} fill=${c[0]} /><ellipse cx=${-s * 0.22} cy=${-s * 0.55} rx=${s * 0.27} ry=${s * 0.24} fill=${c[1]} /><ellipse cx=${s * 0.24} cy=${-s * 0.58} rx=${s * 0.26} ry=${s * 0.23} fill=${c[2]} />`;
  }
  return html`<g transform=${`translate(${x} ${base})`}><g class="tp-tree">${body}${cap}</g></g>`;
}

/** The far treeline: a row of rounded tops along the back of the course. */
function treeline(y) {
  let d = `M0 ${y + 8}`;
  for (let x = 0; x < 300; x += 12) d += `q6 ${-9 - ((x * 7) % 5)} 12 0`;
  return d + 'V140H0Z'; // down into the back hill, so no sky shows between them
}

function Pond({ x, color, ice, rain, duck }) {
  return html`<g><ellipse cx=${x} cy="138" rx="27" ry="4.4" fill=${color} /><ellipse class="tp-glint" cx=${x - 8} cy="137" rx="7" ry="1" fill="#ffffff" fill-opacity=".55" /><ellipse class="tp-glint tp-glint2" cx=${x + 9} cy="139.4" rx="5" ry="0.8" fill="#ffffff" fill-opacity=".45" />
    ${rain && html`<ellipse class="tp-ripple" cx=${x} cy="138" rx="10" ry="2" />`}
    ${duck && !ice && html`<g transform=${`translate(${x - 12} 136.4)`}><g class="tp-duck"><ellipse rx="3.4" ry="1.8" fill="#8a6a3a" /><circle cx="3" cy="-1.8" r="1.5" fill="#2f7a50" /><path d="M4.4 -1.8l2 .5l-2 .5z" fill="#ff9f0a" /></g></g>`}</g>`;
}

function Bunker({ x, snow }) {
  return html`<g><ellipse cx=${x} cy="153" rx="16" ry="3.8" fill=${snow ? '#b9c4d8' : '#c7b57f'} /><ellipse cx=${x} cy="153.4" rx="14" ry="3" fill=${snow ? '#f4f7fc' : '#ecdfb2'} /><ellipse cx=${x - 4} cy="153" rx="5" ry="1" fill="#ffffff" fill-opacity=".35" /></g>`;
}


// ---- guests: small animals that pop up now and then (a few seconds in every 15 to 30) ---------------------------------
const FUR = { spring: '#c9b8a4', summer: '#b98a5c', autumn: '#a9784a', winter: '#f2f4f8' };

/** Who may visit: by weather, season and what the course has. Two different guests per card, chosen by the seed. */
function guestsFor({ season, mood, pond, trees, seed }) {
  const options = [];
  if (mood === 'snow') options.push('penguin', 'rabbit', 'fox');
  else if (mood === 'rain') options.push('snail', pond ? 'frog' : 'snail', 'mole');
  else {
    options.push('rabbit');
    if (season !== 'winter') options.push('mole');
    if (pond && (season === 'spring' || season === 'summer')) options.push('frog');
    if (trees.length && season !== 'winter') options.push('squirrel');
    if (season === 'autumn') options.push('hedgehog', 'fox');
    if (season === 'winter') options.push('fox', 'penguin');
  }
  const unique = [...new Set(options)];
  const first = unique[hash(seed + 'a') % unique.length];
  const rest = unique.filter((kind) => kind !== first);
  return rest.length ? [first, rest[hash(seed + 'b') % rest.length]] : [first];
}

function Guest({ kind, season, pondX, treeX, snow }) {
  switch (kind) {
    case 'rabbit': {
      const fur = snow ? '#f2f4f8' : FUR[season];
      return html`<g transform="translate(0 162)"><g class="tp-guest tp-run"><g class="tp-hop"><ellipse cx="0" cy="-3" rx="4.6" ry="3" fill=${fur} /><circle cx="4.2" cy="-5.4" r="2.4" fill=${fur} /><ellipse cx="3.6" cy="-9" rx=".9" ry="2.8" fill=${fur} /><ellipse cx="5.7" cy="-8.8" rx=".9" ry="2.6" fill=${fur} /><circle cx="-4.8" cy="-3.6" r="1.4" fill="#ffffff" /><circle cx="5.3" cy="-5.9" r=".5" fill="#1b1b1b" /></g></g></g>`;
    }
    case 'mole':
      return html`<g transform="translate(176 153)"><g class="tp-guest"><g clip-path="url(#tp-above)"><g class="tp-mole"><ellipse cx="0" cy="-1" rx="3.4" ry="4" fill="#4f4540" /><circle cx="-1.3" cy="-2.4" r=".6" fill="#ffffff" /><circle cx="1.3" cy="-2.4" r=".6" fill="#ffffff" /><circle cx="0" cy=".2" r=".9" fill="#ff9fb3" /></g></g><ellipse cx="0" cy="1.6" rx="6.5" ry="1.8" fill=${snow ? '#b9c4d8' : '#6a4a32'} /></g></g>`;
    case 'frog':
      return html`<g transform=${`translate(${pondX + 14} 138.4)`}><g class="tp-guest"><g clip-path="url(#tp-above)"><g class="tp-frog"><ellipse rx="3.6" ry="2.6" fill="#5fb75a" /><circle cx="-2" cy="-2.4" r="1.3" fill="#7fd070" /><circle cx="2" cy="-2.4" r="1.3" fill="#7fd070" /><circle cx="-2" cy="-2.5" r=".5" fill="#111111" /><circle cx="2" cy="-2.5" r=".5" fill="#111111" /></g></g><ellipse class="tp-ripple tp-frog-ring" cx="0" cy="0" rx="6" ry="1.4" /></g></g>`;
    case 'squirrel':
      return html`<g transform=${`translate(${treeX + 5} 127)`}><g class="tp-guest"><g class="tp-squirrel"><path class="tp-tail" d="M-1.6 -6q-6 -2 -3 -9q4 3 1 6z" fill="#d98a3a" /><ellipse cx="0" cy="-5" rx="2.6" ry="3.6" fill="#b5651d" /><circle cx="1" cy="-9.4" r="2" fill="#b5651d" /><circle cx="1.8" cy="-9.8" r=".5" fill="#111111" /></g></g></g>`;
    case 'hedgehog':
      return html`<g transform="translate(0 163)"><g class="tp-guest tp-walk-left"><ellipse cx="0" cy="-3" rx="5.5" ry="3.6" fill="#6b4f3a" /><path d="M-4.6 -5.2l1-3 1 3 1-3 1 3 1-3 1 3 1-3 1 3" fill="none" stroke="#3a2a1e" stroke-width="1" /><ellipse cx="-5.8" cy="-2" rx="2.4" ry="1.8" fill="#c9a37a" /><circle cx="-7.9" cy="-2" r=".6" fill="#111111" /><circle cx="-6.2" cy="-2.9" r=".5" fill="#111111" /></g></g>`;
    case 'fox':
      return html`<g transform="translate(0 130)"><g class="tp-guest tp-trot"><g class="tp-hop tp-hop-small"><ellipse cx="0" cy="-3" rx="5" ry="2.4" fill="#e0762e" /><circle cx="5" cy="-4.4" r="2" fill="#e0762e" /><path d="M4 -6l.4 -2.4l1.4 1.8zM6 -6l1.2 -2.2l.4 2.2z" fill="#e0762e" /><path d="M-4.6 -3.4q-4 -2 -6 .6q3 2 6 .4z" fill="#e0762e" /><ellipse cx="-9.6" cy="-2.6" rx="1.3" ry=".9" fill="#ffffff" /><circle cx="5.7" cy="-4.8" r=".45" fill="#111111" /><path d="M-2 -1v3M2 -1v3" stroke="#6b3a14" stroke-width=".9" /></g></g></g>`;
    case 'penguin':
      return html`<g transform="translate(0 161)"><g class="tp-guest tp-parade"><g class="tp-waddle"><ellipse cx="0" cy="-4.4" rx="3" ry="4.8" fill="#1e2433" /><ellipse cx="0" cy="-3.6" rx="1.8" ry="3.4" fill="#f4f7fc" /><circle cx="0" cy="-9.4" r="2.4" fill="#1e2433" /><path d="M-.9 -9l.9 1.4l.9 -1.4z" fill="#ff9f0a" /><circle cx="-1" cy="-9.9" r=".4" fill="#ffffff" /><circle cx="1" cy="-9.9" r=".4" fill="#ffffff" /><ellipse cx="-1.4" cy="-.2" rx="1.4" ry=".6" fill="#ff9f0a" /><ellipse cx="1.4" cy="-.2" rx="1.4" ry=".6" fill="#ff9f0a" /></g></g></g>`;
    case 'snail':
      return html`<g transform="translate(0 164)"><g class="tp-guest tp-crawl"><ellipse cx="0" cy="-1" rx="5" ry="1.2" fill="#cdb58a" /><circle cx="-1" cy="-3.6" r="3.2" fill="#b5651d" /><path d="M-1 -3.6m-1.8 0a1.8 1.8 0 1 1 3.6 0a1 1 0 1 1 -2 0" fill="none" stroke="#7a3f10" stroke-width=".7" /><path d="M3.8 -1.6l1.4 -2.6M4.8 -1.4l2 -2" fill="none" stroke="#cdb58a" stroke-width=".7" /></g></g>`;
    default:
      return null;
  }
}

const BALL = { roll: 'tp-roll', chip: 'tp-chip', wobble: 'tp-wob' };

/** One ball, however it travels: `variant` "roll" runs straight in, "chip" flies up and bounces in, "wobble" stops at
 *  the edge, hesitates, then drops. `delay` (seconds) lets several balls follow each other. */
function Ball({ variant, color, mark, delay = 0, lane = 0 }) {
  const kind = BALL[variant] || BALL.roll;
  return html`<g transform=${`translate(26 ${144 + lane})`} style=${`--d:${delay}s`}><g class=${kind + '-x'}><g class=${kind + '-y'}><g class=${kind + '-drop'}><g class=${kind + '-spin'}>
    <circle r="3.3" fill=${color} /><path d="M-2 -1a2.4 2.4 0 0 1 3-1.3" fill="none" stroke=${mark} stroke-width="1" /><circle cx="1.1" cy="1.3" r=".6" fill=${mark} />
  </g></g></g></g></g>`;
}

const GENDER_BALL = { female: '#f08fd2', male: '#7db8ff' };

/** The scene for `mood` ("clear" | "partly" | "overcast" | "rain" | "snow"), filling its box (300 x 168 drawing).
 *  `season` colours the course and brings its own trees and falling things; `seed` (any text) picks which features
 *  this course has (pond, bunker, trees), so every card looks like another hole. `variant` picks how the ball
 *  travels ("roll", "chip", "wobble", "trio" for friends: one ball each, `friends` are their genders); `phase`
 *  (seconds) starts the loop part-way so neighbouring cards are never in step. The wind (km/h) sets the pace of flag,
 *  clouds and trees, and decides who else is out: birds when calm, a butterfly when very calm, blowing leaves and
 *  bending grass when it is windy. */
export function Scene({ mood, wind, variant = 'roll', friends = [], phase = 0, season = 'summer', seed = '' }) {
  const { flag, clouds } = windTimes(wind);
  const kph = wind == null ? 8 : wind;
  const snow = mood === 'snow';
  const wet = mood === 'rain';
  const sun = mood === 'clear' || mood === 'partly';
  const fair = sun || mood === 'overcast';
  const pair = CLOUDS[mood];
  const palette = { ...SEASONS[season] || SEASONS.summer, ...(snow ? WHITE_GROUND : {}) };
  const layout = LAYOUTS[hash(seed) % LAYOUTS.length];
  const ice = snow || (season === 'winter' && !wet);
  const white = snow ? '#ff8a3d' : '#f7f7f7';
  const mark = snow ? '#ffd0ae' : '#9aa0b5';
  const lean = Math.min(24, 4 + kph * 0.55).toFixed(1);
  const balls = variant === 'trio'
    ? [{ color: white, delay: 0 }, ...friends.slice(0, 2).map((g, i) => ({ color: GENDER_BALL[g] || '#c9cddd', delay: 1.4 * (i + 1) }))]
    : [{ color: white, delay: 0 }];
  const style = `--flag-dur:${flag.toFixed(2)}s;--cloud-dur:${clouds.toFixed(1)}s;--lean:${lean}deg;--phase:${-phase}s`;
  const treeSizes = [20, 17, 22];
  const guests = guestsFor({ season, mood, pond: layout.pond, trees: layout.trees, seed });
  return html`<svg class=${'tp-scene tp-' + mood + ' tp-' + season} style=${style} viewBox="0 0 300 168" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <rect width="300" height="168" fill=${'url(#tp-' + mood + ')'} />
    ${sun && html`<g transform="translate(250 38)"><circle class="tp-glow" r="32" fill="url(#tp-glow)" /><g class="tp-rays"><use href="#tp-rays" /></g><circle r="10" fill="#ffd60a" /></g>`}
    ${mood === 'partly' && html`<g class="tp-cloud"><ellipse cx="60" cy="26" rx="28" ry="8" fill="#e8ecf5" fill-opacity=".7" /><ellipse cx="80" cy="19" rx="18" ry="8" fill="#e8ecf5" fill-opacity=".7" /></g>`}
    ${mood === 'clear' && html`<g class="tp-cloud"><ellipse cx="70" cy="30" rx="24" ry="7" fill="#e8ecf5" fill-opacity=".45" /><ellipse cx="86" cy="24" rx="15" ry="7" fill="#e8ecf5" fill-opacity=".45" /></g>`}
    ${pair && html`<g class="tp-cloud"><ellipse cx="60" cy="22" rx="30" ry="9" fill=${pair[0]} /><ellipse cx="82" cy="15" rx="19" ry="9" fill=${pair[0]} /></g>
      <g class="tp-cloud tp-back"><ellipse cx="220" cy="24" rx="32" ry="9" fill=${pair[1]} /><ellipse cx="244" cy="17" rx="19" ry="9" fill=${pair[1]} /></g>`}
    ${sun && kph < 22 && season !== 'winter' && html`<g transform="translate(0 52)"><g class="tp-bird"><path class="tp-wing" d="M0 0q3-4 6 0q3-4 6 0" /></g></g>
      <g transform="translate(0 74)"><g class="tp-bird tp-bird2"><path class="tp-wing" d="M0 0q3-4 6 0q3-4 6 0" /></g></g>`}
    <rect width="300" height="132" fill="url(#tp-scrim)" />
    <path d=${treeline(113)} fill=${palette.line} fill-opacity=".85" />
    <path d="M0 168V132Q70 120 150 128T300 122V168Z" fill=${palette.back} />
    ${layout.pond && html`<${Pond} x=${112} color=${palette.water} ice=${ice} rain=${wet} duck=${(season === 'spring' || season === 'summer') && fair} />`}
    ${layout.trees.map((x, i) => html`<${Tree} key=${x} x=${x} base=${x > 270 ? 126 : 127} size=${treeSizes[i % 3]} season=${season} snow=${snow} pine=${season === 'winter' ? i % 2 === 0 : i === 1 && season !== 'autumn'} colors=${palette.leaves} trunk=${palette.trunk} />`)}
    <path d="M0 168V150Q90 142 180 148T300 144V168Z" fill=${palette.front} />
    ${layout.bunker && html`<${Bunker} x=${222} snow=${snow} />`}
    ${!snow && html`<g class="tp-grass"><path d="M64 150l-2-8m2 8v-9m2 9l2-8" /><path d="M118 152l-2-8m2 8v-9m2 9l2-8" /><path d="M176 151l-2-8m2 8v-9m2 9l2-8" /><path d="M222 152l-2-8m2 8v-9m2 9l2-8" /></g>`}
    ${season === 'spring' && !snow && html`<g class="tp-flowers"><circle cx="40" cy="158" r="1.5" fill="#ff8fb8" /><circle cx="48" cy="161" r="1.3" fill="#fff6a8" /><circle cx="92" cy="159" r="1.5" fill="#ffffff" /><circle cx="146" cy="158" r="1.5" fill="#ff8fb8" /><circle cx="154" cy="161" r="1.3" fill="#ffd84a" /><circle cx="196" cy="159" r="1.4" fill="#c9a6f7" /><circle cx="270" cy="156" r="1.4" fill="#ff8fb8" /></g>`}
    ${season === 'autumn' && !snow && html`<g class="tp-fallen"><ellipse cx="46" cy="158" rx="2.2" ry="1.1" fill="#d8742e" /><ellipse cx="100" cy="160" rx="2.2" ry="1.1" fill="#b8402a" /><ellipse cx="160" cy="159" rx="2.2" ry="1.1" fill="#e8a23a" /><ellipse cx="248" cy="158" rx="2.2" ry="1.1" fill="#d8742e" /></g>`}
    ${season === 'winter' && !snow && html`<g class="tp-frost"><circle cx="30" cy="156" r="1" /><circle cx="84" cy="160" r="1" /><circle cx="132" cy="157" r="1" /><circle cx="186" cy="161" r="1" /><circle cx="240" cy="158" r="1" /></g>`}
    ${snow && html`<g class="tp-snowman"><circle cx="150" cy="140" r="8" /><circle cx="150" cy="129" r="6" /><circle cx="150" cy="120" r="4.4" /><path class="tp-nose" d="M150 120l6 1.2l-6 1z" /><circle class="tp-coal" cx="148.4" cy="119" r=".7" /><circle class="tp-coal" cx="151.6" cy="119" r=".7" /></g>`}
    <ellipse cx="252" cy="147" rx="28" ry="4" fill=${palette.green} />
    <ellipse cx="252" cy="147" rx="4" ry="1.4" fill=${snow ? '#7c88a4' : '#0c2a1c'} />
    <path d="M252 147V114" stroke="#f2f4fa" stroke-width="1.6" />
    <path class="tp-flag" d="M252 114l18 5-18 6z" fill="#ff453a" />
    ${wet && html`<ellipse class="tp-ripple" cx="60" cy="158" rx="12" ry="2.4" /><ellipse class="tp-ripple tp-ripple2" cx="168" cy="160" rx="10" ry="2" />`}
    ${sun && kph < 12 && season !== 'winter' && html`<g transform="translate(0 124)"><g class="tp-flutter"><ellipse class="tp-wing2" cx="-2" cy="0" rx="2.6" ry="1.6" /><ellipse class="tp-wing2" cx="2" cy="0" rx="2.6" ry="1.6" /></g></g>`}
    ${fair && kph >= 25 && html`<g transform="translate(0 70)"><path class="tp-leaf" d="M0 0q4-5 8 0q-4 5-8 0z" /></g><g transform="translate(0 100)"><path class="tp-leaf tp-leaf2" d="M0 0q4-5 8 0q-4 5-8 0z" /></g><g transform="translate(0 124)"><path class="tp-leaf tp-leaf3" d="M0 0q3-4 6 0q-3 4-6 0z" /></g>`}
    ${guests.map((kind) => html`<${Guest} key=${kind} kind=${kind} season=${season} pondX=${112} treeX=${layout.trees[0] || 0} snow=${snow} />`)}
    ${balls.map((b, i) => html`<${Ball} key=${i} variant=${variant === 'trio' ? 'roll' : variant} color=${b.color} mark=${mark} delay=${b.delay} lane=${i === 1 ? 3 : i === 2 ? -3 : 0} />`)}
    ${mood === 'overcast' && html`<rect width="300" height="168" fill="#0c1020" opacity=".12" />`}
    ${season === 'spring' && !wet && !snow && html`<g class="tp-petals"><ellipse cx="40" cy="-6" rx="2" ry="1" fill="#f9c8dc" /><ellipse cx="120" cy="-30" rx="2" ry="1" fill="#ffffff" /><ellipse cx="190" cy="-14" rx="2" ry="1" fill="#f9c8dc" /><ellipse cx="270" cy="-40" rx="2" ry="1" fill="#ffffff" /></g>`}
    ${season === 'autumn' && !wet && !snow && html`<g class="tp-falling"><path d="M60 -4q4-5 8 0q-4 5-8 0z" fill="#d8742e" /><path d="M150 -26q4-5 8 0q-4 5-8 0z" fill="#e8a23a" /><path d="M230 -12q4-5 8 0q-4 5-8 0z" fill="#b8402a" /></g>`}
    ${wet && html`<g class="tp-fall-rain"><rect y="-40" width="300" height="208" fill="url(#tp-drops)" /></g>`}
    ${snow && html`<g class="tp-fall-far"><rect y="-50" width="300" height="218" fill="url(#tp-flakes-far)" /></g><g class="tp-fall-near"><rect y="-70" width="300" height="238" fill="url(#tp-flakes-near)" /></g>`}
  </svg>`;
}
