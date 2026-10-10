// Add Club: search the platform's club directory (live list, or the bundled snapshot), a typed club id
// or tee-sheet link; add a club to your clubs, or open it just to look.

import { html, t, useState, useEffect, useRef, Sheet, Status, Icon, api, post, query, language } from '/lib.js';

function sourceText(state) {
  if (!state) return '';
  if (state.source === 'live') {
    const when = state.fetched_at ? new Date(state.fetched_at).toLocaleDateString(language(), { day: 'numeric', month: 'short', year: 'numeric' }) : '';
    return t('addclub.source_live', { n: state.count, when });
  }
  if (state.source === 'seed') return t('addclub.source_seed', { n: state.count });
  return t('addclub.source_none');
}

export function AddClubSheet({ onClose, onAdded, onOpen }) {
  const [text, setText] = useState('');
  const [state, setState] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  const latest = useRef(0);

  function run(value) {
    const mine = ++latest.current;
    api('/api/directory' + query({ q: value }))
      .then((result) => mine === latest.current && setState(result))
      .catch(() => mine === latest.current && setMessage({ kind: 'error', text: t('error.title') }));
  }
  useEffect(() => run(''), []);
  function onInput(value) {
    setText(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => run(value), 200);
  }
  async function add(entry) {
    setMessage(null);
    const result = await post('/api/club/add', { club_id: entry.id, name: entry.name });
    if (result.ok) {
      setMessage({ kind: 'ok', text: t('addclub.added', { name: entry.name || entry.id }) });
      run(text);
      onAdded(result.slug);
    }
  }
  async function refresh() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await post('/api/directory/refresh', {});
      if (result.ok) setMessage({ kind: 'ok', text: t('addclub.refreshed', { n: result.count }) });
      else setMessage({ kind: 'error', text: t('addclub.refresh_' + result.reason, { error: result.error || '' }) });
      run(text);
    } catch (error) {
      setMessage({ kind: 'error', text: t('error.title') });
    }
    setBusy(false);
  }
  const results = (state && state.results) || [];
  return html`<${Sheet} title=${t('addclub.title')} onClose=${onClose} size="medium">
    <div class="search-box">
      <${Icon} name="search" size=${18} />
      <input class="fld" type="search" autofocus value=${text} placeholder=${t('addclub.search_placeholder')}
        onInput=${(event) => onInput(event.target.value)} aria-label=${t('addclub.search_placeholder')} />
    </div>
    <p class="hint source-line">${sourceText(state)}
      <button class="link-btn" onClick=${refresh} disabled=${busy}>${t(busy ? 'refreshing' : 'addclub.refresh')}</button></p>
    <${Status} kind=${message && message.kind}>${message && message.text}<//>
    ${text.trim() && results.length === 0 && html`<div class="empty small"><h3>${t('addclub.no_matches_title')}</h3><p>${t('addclub.no_matches_desc')}</p></div>`}
    ${!text.trim() && html`<div class="empty small"><h3>${t('addclub.empty_title')}</h3><p>${t('addclub.empty_desc')}</p></div>`}
    <ul class="club-results">
      ${results.map((entry) => html`
        <li>
          <span class="club-name">${entry.name || t('addclub.unknown_name')}${entry.typed ? html` <span class="dim">· ${t('addclub.by_id')}</span>` : ''}</span>
          <span class="dim num">${entry.id}</span>
          <span class="club-actions">
            ${entry.saved
              ? html`<span class="saved-mark"><${Icon} name="check" size=${16} />${t('addclub.saved')}</span>`
              : html`<button class="btn" onClick=${() => onOpen(entry)}>${t('addclub.open')}</button>
                     <button class="btn pri" onClick=${() => add(entry)}><${Icon} name="plus" size=${16} />${t('addclub.add')}</button>`}
          </span>
        </li>`)}
    </ul>
  <//>`;
}
