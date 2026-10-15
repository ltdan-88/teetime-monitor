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

/** The scene for `mood` ("clear" | "partly" | "overcast" | "rain" | "snow"), filling its box (300 x 168 drawing). */
export function Scene({ mood, wind }) {
  const { flag, clouds } = windTimes(wind);
  const snow = mood === 'snow';
  const sun = mood === 'clear' || mood === 'partly';
  const pair = CLOUDS[mood];
  return html`<svg class=${'tp-scene tp-' + mood} style=${`--flag-dur:${flag.toFixed(2)}s;--cloud-dur:${clouds.toFixed(1)}s`} viewBox="0 0 300 168" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <rect width="300" height="168" fill=${'url(#tp-' + mood + ')'} />
    ${sun && html`<g transform="translate(250 38)"><circle class="tp-glow" r="32" fill="url(#tp-glow)" /><g class="tp-rays"><use href="#tp-rays" /></g><circle r="10" fill="#ffd60a" /></g>`}
    ${mood === 'partly' && html`<g class="tp-cloud"><ellipse cx="60" cy="26" rx="28" ry="8" fill="#e8ecf5" fill-opacity=".7" /><ellipse cx="80" cy="19" rx="18" ry="8" fill="#e8ecf5" fill-opacity=".7" /></g>`}
    ${mood === 'clear' && html`<g class="tp-cloud"><ellipse cx="70" cy="30" rx="24" ry="7" fill="#e8ecf5" fill-opacity=".45" /><ellipse cx="86" cy="24" rx="15" ry="7" fill="#e8ecf5" fill-opacity=".45" /></g>`}
    ${pair && html`<g class="tp-cloud"><ellipse cx="60" cy="22" rx="30" ry="9" fill=${pair[0]} /><ellipse cx="82" cy="15" rx="19" ry="9" fill=${pair[0]} /></g>
      <g class="tp-cloud tp-back"><ellipse cx="220" cy="24" rx="32" ry="9" fill=${pair[1]} /><ellipse cx="244" cy="17" rx="19" ry="9" fill=${pair[1]} /></g>`}
    <rect width="300" height="132" fill="url(#tp-scrim)" />
    <path d="M0 168V132Q70 120 150 128T300 122V168Z" fill=${snow ? '#e4eaf4' : '#2a6a45'} />
    <path d="M0 168V150Q90 142 180 148T300 144V168Z" fill=${snow ? '#cdd7e8' : '#1f5a3a'} />
    <ellipse cx="252" cy="147" rx="28" ry="4" fill=${snow ? '#f4f7fc' : '#2f7a50'} />
    <ellipse cx="252" cy="147" rx="4" ry="1.4" fill=${snow ? '#7c88a4' : '#0c2a1c'} />
    <path d="M252 147V114" stroke="#f2f4fa" stroke-width="1.6" />
    <path class="tp-flag" d="M252 114l18 5-18 6z" fill="#ff453a" />
    <g transform="translate(26 144)"><g class="tp-roll"><g class="tp-drop"><g class="tp-spin">
      <circle r="3.3" fill=${snow ? '#ff8a3d' : '#f7f7f7'} />
      <path d="M-2 -1a2.4 2.4 0 0 1 3-1.3" fill="none" stroke=${snow ? '#ffd0ae' : '#9aa0b5'} stroke-width="1" /><circle cx="1.1" cy="1.3" r=".6" fill=${snow ? '#ffd0ae' : '#9aa0b5'} />
    </g></g></g></g>
    ${mood === 'overcast' && html`<rect width="300" height="168" fill="#0c1020" opacity=".12" />`}
    ${mood === 'rain' && html`<g class="tp-fall-rain"><rect y="-40" width="300" height="208" fill="url(#tp-drops)" /></g>`}
    ${snow && html`<g class="tp-fall-far"><rect y="-50" width="300" height="218" fill="url(#tp-flakes-far)" /></g><g class="tp-fall-near"><rect y="-70" width="300" height="238" fill="url(#tp-flakes-near)" /></g>`}
  </svg>`;
}
