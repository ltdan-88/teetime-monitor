// The first screen, before a club is saved: what the app does and the three steps to get going.

import { html, t, Icon } from '/lib.js';
import { Scene, SceneDefs, seasonOf } from '/scene.js';

function Step({ number, title, text, state }) {
  return html`<li class=${'wl-step ' + state}>
    <span class="wl-num">${state === 'done' ? html`<${Icon} name="check" size=${16} />` : number}</span>
    <span><b>${title}</b><span class="wl-text">${text}</span></span>
  </li>`;
}

export function Welcome({ onAddClub, onLogin }) {
  return html`<section class="wl" aria-labelledby="wl-title">
    <${SceneDefs} />
    <div class="wl-scene"><${Scene} mood="clear" wind=${8} season=${seasonOf(new Date().toISOString().slice(0, 10))} seed="welcome" /></div>
    <h1 id="wl-title">${t('welcome.title')}</h1>
    <p class="wl-lead">${t('welcome.lead')}</p>
    <ol class="wl-steps">
      <${Step} number="1" state="now" title=${t('welcome.step1')} text=${t('welcome.step1.text')} />
      <${Step} number="2" state="todo" title=${t('welcome.step2')} text=${t('welcome.step2.text')} />
      <${Step} number="3" state="todo" title=${t('welcome.step3')} text=${t('welcome.step3.text')} />
    </ol>
    <div class="wl-actions">
      <button class="btn pri" onClick=${onAddClub}>${t('welcome.add')}</button>
      <button class="btn" onClick=${onLogin}>${t('welcome.login')}</button>
    </div>
  </section>`;
}
