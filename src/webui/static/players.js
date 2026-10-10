// Player directory: every name your scrapes have seen (only a logged-in scrape shows names), with
// search, sorting, and the one thing you edit: who is a friend (friends get a ★ and a ranking boost).

import { html, t, useState, useMemo, Sheet, Select, Switch, Status, Icon, useLoad, api, post, query, hcpText } from '/lib.js';

const SORTS = ['name', 'friend', 'gender', 'handicap', 'member'];
const familyName = (name) => name.trim().split(/\s+/).pop().toLowerCase();

function sorted(players, key) {
  const base = [...players].sort((a, b) => familyName(a.name).localeCompare(familyName(b.name)) || a.name.localeCompare(b.name));
  const rank = {
    friend: (p) => (p.friend ? 0 : 1),
    gender: (p) => (p.gender === 'female' ? 0 : p.gender === 'male' ? 1 : 2),
    member: (p) => (p.member_status === 'member' ? 0 : p.member_status === 'guest' ? 1 : 2),
    handicap: (p) => (p.handicap == null ? 999 : p.handicap),
  }[key];
  return rank ? base.sort((a, b) => rank(a) - rank(b)) : base;
}

/** Groups of players by the first letter of their family name, '#' for anything else (only
 *  meaningful when the list is sorted by name). */
function byLetter(players) {
  const groups = [];
  for (const player of players) {
    const initial = familyName(player.name).charAt(0).toUpperCase();
    const letter = /\p{L}/u.test(initial) ? initial : '#';
    const last = groups[groups.length - 1];
    if (last && last.letter === letter) last.players.push(player);
    else groups.push({ letter, players: [player] });
  }
  return groups;
}

export function PlayersSheet({ club, showHandicaps, onClose, onChanged }) {
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const { data, error, reload } = useLoad(() => api('/api/players' + query(ref)), [club.id]);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('name');
  const [friendsOnly, setFriendsOnly] = useState(false);
  const [local, setLocal] = useState({});
  const rows = useMemo(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    return sorted(data.players, sort)
      .map((p) => ({ ...p, friend: p.name in local ? local[p.name] : p.friend }))
      .filter((p) => (!needle || p.name.toLowerCase().includes(needle)) && (!friendsOnly || p.friend));
  }, [data, search, sort, friendsOnly, local]);
  async function toggle(player) {
    const next = !player.friend;
    setLocal((current) => ({ ...current, [player.name]: next }));
    try {
      await post('/api/players/friend', { ...ref, name: player.name, friend: next });
      onChanged();
    } catch (failure) {
      setLocal((current) => ({ ...current, [player.name]: player.friend }));
    }
  }
  const grouped = sort === 'name' ? byLetter(rows) : null;
  const letters = grouped ? grouped.map((group) => group.letter).filter((letter, i, all) => all.indexOf(letter) === i) : [];
  const jump = (letter) => {
    // scrollTo on the list itself: scrollIntoView would also move every scrollable parent
    const list = document.querySelector('.player-list');
    const target = document.getElementById('letter-' + letter);
    if (list && target) list.scrollTo({ top: target.offsetTop, behavior: 'smooth' });
  };
  const row = (player) => html`
        <li>
          <button class=${'star-btn' + (player.friend ? ' on' : '')} onClick=${() => toggle(player)} aria-pressed=${player.friend}
            title=${t(player.friend ? 'players.unmark_friend' : 'players.mark_friend')} aria-label=${t(player.friend ? 'players.unmark_friend' : 'players.mark_friend') + ': ' + player.name}>
            <${Icon} name="star" size=${18} style=${player.friend ? 'fill:currentColor' : ''} /></button>
          <span class=${'player-name' + (player.gender === 'female' ? ' alt' : '') + (player.friend ? ' f' : '')} title=${player.name}>${player.name}</span>
          <span class="dim player-meta">${player.gender ? t('players.gender.' + player.gender) : ''}</span>
          <span class="dim player-meta">${player.member_status ? t('players.member_status.' + player.member_status) : ''}</span>
          <span class="num dim player-hcp">${showHandicaps && player.handicap != null ? hcpText(player.handicap) : ''}</span>
        </li>`;
  return html`<${Sheet} title=${t('players.title')} onClose=${onClose} size="directory" fixed>
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    <p class="hint">${t('players.intro')}</p>
    <div class="players-tools">
      <span class="search-box"><${Icon} name="search" size=${18} />
        <input class="fld" type="search" value=${search} placeholder=${t('players.search_placeholder')} aria-label=${t('players.search_placeholder')} onInput=${(event) => setSearch(event.target.value)} /></span>
      <${Select} id="p-sort" value=${sort} options=${SORTS.map((key) => ({ value: key, label: t('players.sort.' + key) }))} onChange=${setSort} aria-label=${t('players.sort')} />
      <label class="check"><${Switch} id="p-friends" checked=${friendsOnly} onChange=${setFriendsOnly} /> ${t('players.friends_only')}</label>
    </div>
    ${data && data.players.length > 0 && html`<p class="hint count">${t('players.count', { n: rows.length, total: data.players.length })}</p>`}
    ${data && data.players.length === 0 && html`<div class="empty small"><h3>${t('players.empty_title')}</h3><p>${t('players.empty')}</p></div>`}
    ${data && data.players.length > 0 && rows.length === 0 && html`<p class="dim">${t('players.no_matches')}</p>`}
    ${data && data.players.length > 0 && html`
      <div class="player-head" aria-hidden="true">
        <span></span><span>${t('players.column.name')}</span><span>${t('players.column.gender')}</span>
        <span>${t('players.column.member_status')}</span><span class="r">${showHandicaps ? t('players.column.handicap') : ''}</span>
      </div>`}
    <div class="player-scroll">
      <ul class="player-list scroll">
        ${grouped
          ? grouped.map((group, index) => html`
              <li class="letter" id=${index === grouped.findIndex((g) => g.letter === group.letter) ? 'letter-' + group.letter : null}>${group.letter}</li>
              ${group.players.map(row)}`)
          : rows.map(row)}
      </ul>
      ${grouped && letters.length > 1 && html`<nav class="alpha" aria-label=${t('players.index')}>${letters.map((letter) => html`<button onClick=${() => jump(letter)}>${letter}</button>`)}</nav>`}
    </div>
    ${data && data.my_handicap != null && showHandicaps && html`<p class="hint">${t('settings.field.my_handicap')}: ${hcpText(data.my_handicap)}</p>`}
  <//>`;
}
