// Player directory: every name seen at any of your clubs (only a logged-in scrape shows names), with search,
// filters, sorting, each one's next tee time at any saved club, and the one thing you edit: who is a friend.

import { html, t, useState, useMemo, Sheet, Select, Status, Icon, useLoad, api, post, query, hcpText, dayLabel } from '/lib.js';

const SORTS = ['name', 'friend', 'gender', 'handicap', 'club'];
const GUESTS = '__guests'; // the Club filter's "guests (club unknown)"

/** The Club column: the club(s) the name was seen at as a member, else "Guest" (the directory is shared by every
 *  club; pc caddie never names a guest's own club). */
const memberText = (player) => !player.member_status ? '' : player.member_status === 'member' && player.home_clubs && player.home_clubs.length
  ? player.home_clubs.join(', ') : t('players.member_status.' + player.member_status);
const familyName = (name) => name.trim().split(/\s+/).pop().toLowerCase();
/** A club's name without the words every club has ("Golfclub Schloß Monrepos e.V." -> "Schloß Monrepos"). */
export const shortClub = (name) => (name || '').replace(/^\s*(golf[\s-]?club|golf[\s-]?anlage|golf[\s-]?park|g\.?c\.?)\s+/i, '')
  .replace(/\s+(e\.\s?v\.?|gmbh(\s.*)?|ag)\s*$/i, '').trim() || name;
/** The club a player is listed under when sorting by club: the first of their home clubs, or none (a guest). */
const homeClub = (player) => (player.home_clubs && player.home_clubs.length ? [...player.home_clubs].sort((a, b) => a.localeCompare(b))[0] : null);

function sorted(players, key) {
  const base = [...players].sort((a, b) => familyName(a.name).localeCompare(familyName(b.name)) || a.name.localeCompare(b.name));
  const rank = {
    friend: (p) => (p.friend ? 0 : 1),
    gender: (p) => (p.gender === 'female' ? 0 : p.gender === 'male' ? 1 : 2),
    handicap: (p) => (p.handicap == null ? 999 : p.handicap),
  }[key];
  if (key === 'club') return base.sort((a, b) => (homeClub(a) === null) - (homeClub(b) === null) || (homeClub(a) || '').localeCompare(homeClub(b) || ''));
  return rank ? base.sort((a, b) => rank(a) - rank(b)) : base;
}

/** Runs of players under one heading: the club (or "Guests") when sorted by club. */
function byClub(players) {
  const groups = [];
  for (const player of players) {
    const label = homeClub(player) || t('players.filter.guests');
    const last = groups[groups.length - 1];
    if (last && last.letter === label) last.players.push(player);
    else groups.push({ letter: label, players: [player] });
  }
  return groups;
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

export function PlayersSheet({ club, showHandicaps, onJump, onClose, onChanged }) {
  const ref = club.slug ? { slug: club.slug } : { club_id: club.id };
  const { data, error, reload } = useLoad(() => api('/api/players' + query(ref)), [club.id]);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('name');
  const [friendsOnly, setFriendsOnly] = useState(false);
  const [clubFilter, setClubFilter] = useState('all'); // 'all', a club's name, or GUESTS
  const [genderFilter, setGenderFilter] = useState('all'); // 'all', 'female', 'male'
  const clubs = useMemo(() => (data ? [...new Set(data.players.flatMap((p) => p.home_clubs || []))].sort((a, b) => a.localeCompare(b)) : []), [data]);
  const [local, setLocal] = useState({});
  const [choice, setChoice] = useState(null); // { name, hits }: a player with several tee times, asking which one
  const [none, setNone] = useState(false);
  const courses = data ? new Set(data.players.flatMap((p) => (p.upcoming || []).map((hit) => hit.course))).size : 1;
  const focus = (player) => {
    const hits = player.upcoming || [];
    setNone(hits.length === 0);
    setChoice(hits.length > 1 ? { name: player.name, hits } : null);
    if (hits.length === 1) onJump(hits[0]);
  };
  const rows = useMemo(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    return sorted(data.players, sort)
      .map((p) => ({ ...p, friend: p.name in local ? local[p.name] : p.friend }))
      .filter((p) => (!needle || p.name.toLowerCase().includes(needle)) && (!friendsOnly || p.friend)
        && (clubFilter === 'all' || (clubFilter === GUESTS ? !homeClub(p) : (p.home_clubs || []).includes(clubFilter)))
        && (genderFilter === 'all' || p.gender === genderFilter));
  }, [data, search, sort, friendsOnly, local, clubFilter, genderFilter]);
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
  const grouped = sort === 'name' ? byLetter(rows) : sort === 'club' ? byClub(rows) : null;
  const letters = sort === 'name' && grouped ? grouped.map((group) => group.letter).filter((letter, i, all) => all.indexOf(letter) === i) : [];
  const jump = (letter) => {
    // scrollTo on the list itself: scrollIntoView would also move every scrollable parent
    const list = document.querySelector('.player-list');
    const target = document.getElementById('letter-' + letter);
    if (list && target) list.scrollTo({ top: target.offsetTop, behavior: 'smooth' });
  };
  const row = (player) => html`
        <li onDblClick=${() => focus(player)}>
          <button class=${'star-btn' + (player.friend ? ' on' : '')} onClick=${() => toggle(player)} aria-pressed=${player.friend}
            title=${t(player.friend ? 'players.unmark_friend' : 'players.mark_friend')} aria-label=${t(player.friend ? 'players.unmark_friend' : 'players.mark_friend') + ': ' + player.name}>
            <${Icon} name="star" size=${18} style=${player.friend ? 'fill:currentColor' : ''} /></button>
          <span class=${'player-name' + (player.gender === 'female' ? ' alt' : '') + (player.friend ? ' f' : '')} title=${player.name}>${player.name}</span>
          <span class="dim player-meta">${player.gender ? t('players.gender.' + player.gender) : ''}</span>
          <span class="dim player-meta" title=${memberText(player)}>${memberText(player)}</span>
          <span class="num dim player-hcp">${showHandicaps && player.handicap != null ? hcpText(player.handicap) : ''}</span>
          ${player.upcoming && player.upcoming.length > 0
            ? html`<button class="tee-btn" onClick=${() => focus(player)} title=${t('players.focus_title') + ': ' + player.name}>
                <span>${dayLabel(player.upcoming[0].date).split(' ')[0]}</span><span class="tee-date">${dayLabel(player.upcoming[0].date).split(' ')[1]}</span><span>${player.upcoming[0].time}</span>${!player.upcoming[0].here && html`<span class="tee-club" title=${player.upcoming[0].club}> · ${shortClub(player.upcoming[0].club)}</span>`}${player.upcoming.length > 1 && html`<span class="more" title=${t('players.tee_time_more', { n: player.upcoming.length - 1 })}>+${player.upcoming.length - 1}</span>`}</button>`
            : html`<span></span>`}
        </li>`;
  return html`<${Sheet} title=${t('players.title')} onClose=${onClose} size="directory" fixed>
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    <div class="players-tools">
      <span class="search-box"><${Icon} name="search" size=${18} />
        <input class="fld" type="search" value=${search} placeholder=${t('players.search_placeholder')} aria-label=${t('players.search_placeholder')} onInput=${(event) => setSearch(event.target.value)} /></span>
      <div class="players-filters">
      <${Select} id="p-sort" value=${sort} options=${SORTS.map((key) => ({ value: key, label: t('players.sort.' + key) }))} onChange=${setSort} aria-label=${t('players.sort')} />
      ${clubs.length > 0 && html`<${Select} id="p-club" value=${clubFilter} onChange=${setClubFilter} aria-label=${t('players.filter.club')}
        options=${[{ value: 'all', label: t('players.filter.club_all') }, ...clubs.map((name) => ({ value: name, label: name })), { value: GUESTS, label: t('players.filter.guests') }]} />`}
      <${Select} id="p-gender" value=${genderFilter} onChange=${setGenderFilter} aria-label=${t('players.filter.gender')}
        options=${[{ value: 'all', label: t('players.filter.gender_all') }, { value: 'female', label: t('players.filter.female') }, { value: 'male', label: t('players.filter.male') }]} />
      <button id="p-friends" class="chip tn-pick" aria-pressed=${friendsOnly} onClick=${() => setFriendsOnly(!friendsOnly)}>★ ${t('players.friends_only')}</button>
      </div>
    </div>
    ${data && data.players.length > 0 && html`<p class="hint count">${t('players.count', { n: rows.length, total: data.players.length })}</p>`}
    ${data && data.players.length === 0 && html`<div class="empty small"><h3>${t('players.empty_title')}</h3><p>${t('players.empty')}</p></div>`}
    ${data && data.players.length > 0 && rows.length === 0 && html`<p class="dim">${t('players.no_matches')}</p>`}
    ${none && html`<div class="banner" role="status"><${Icon} name="info" size=${18} /><span>${t('players.focus_none')}</span></div>`}
    ${choice && html`<div class="banner jump-choice" role="group" aria-label=${t('players.focus_title')}><span>${t('players.focus_title')}: ${choice.name}</span>
      ${choice.hits.map((hit) => html`<button class="btn" onClick=${() => onJump(hit)}>${dayLabel(hit.date)} ${hit.time}${courses > 1 || !hit.here ? ' · ' + hit.course : ''}${!hit.here ? ' · ' + shortClub(hit.club) : ''}</button>`)}
      <button class="btn" onClick=${() => setChoice(null)}>${t('cancel')}</button></div>`}
    <div class="player-scroll">
      <ul class="player-list scroll">
        ${data && data.players.length > 0 && html`
          <li class="player-head" aria-hidden="true">
            <span></span><span>${t('players.column.name')}</span><span>${t('players.column.gender')}</span>
            <span>${t('players.column.member_status')}</span><span class="r">${showHandicaps ? t('players.column.handicap') : ''}</span><span>${t('players.column.tee_time')}</span>
          </li>`}
        ${grouped
          ? grouped.map((group, index) => html`
              <li class="letter" id=${sort === 'name' && index === grouped.findIndex((g) => g.letter === group.letter) ? 'letter-' + group.letter : null}>${group.letter}</li>
              ${group.players.map(row)}`)
          : rows.map(row)}
      </ul>
      ${grouped && letters.length > 1 && html`<nav class="alpha" aria-label=${t('players.index')}>${letters.map((letter) => html`<button onClick=${() => jump(letter)}>${letter}</button>`)}</nav>`}
    </div>
    ${data && data.my_handicap != null && showHandicaps && html`<p class="hint">${t('settings.field.my_handicap')}: ${hcpText(data.my_handicap)}</p>`}
  <//>`;
}
