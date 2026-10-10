// Teetime Monitor web UI: the shell. Preact + htm, no build step; data from /api/* (src/webui/server.py).

import {
  html, render, useState, useEffect, useRef, useCallback, api, post, query, loadStrings, t, updatedText, dayLabel, applyScale,
  Icon, Sheet, Select, Status,
} from '/lib.js';
import { DayCard, Banners, focusTime } from '/overview.js';
import { PreferencesSheet, SettingsSheet } from '/forms.js';
import { AddClubSheet } from '/addclub.js';
import { SearchSheet } from '/search.js';
import { HeatmapSheet } from '/heatmap.js';
import { PlayersSheet } from '/players.js';

const ADD_CLUB = '__add_club__';
applyScale();

const refOf = (view) => (view.kind === 'saved' ? { slug: view.slug } : { club_id: view.id, name: view.name });
const refreshKeyOf = (view) => (view.kind === 'saved' ? view.slug : 'club:' + view.id);

/** The text for a refresh that ended in an error: a known rejection (a club with no tee sheet ...)
 *  in plain words, anything else as "Refresh failed: ...". */
function refreshErrorText(error) {
  const known = t('preview.' + error);
  return known !== 'preview.' + error ? known : t('error.refresh', { error });
}

function Empty({ title, text, children }) {
  return html`<div class="empty"><h2>${title}</h2>${text && html`<p>${text}</p>`}${children}</div>`;
}

function Legend({ onClose }) {
  const swatch = (color) => html`<span class="swatch" style=${{ background: color }}></span>`;
  return html`<${Sheet} title=${t('legend.title')} onClose=${onClose} size="small">
    <dl class="legend">
      <dt>${swatch('var(--green)')}</dt><dd>${t('legend.occ.open')}</dd>
      <dt>${swatch('var(--orange)')}</dt><dd>${t('legend.occ.mid')}</dd>
      <dt>${swatch('var(--red)')}</dt><dd>${t('legend.occ.full')}</dd>
      <dt>${swatch('var(--faint)')}</dt><dd>${t('legend.occ.none')}</dd>
    </dl>
    <dl class="legend">
      <dt><span class="pill pick"><${Icon} name="star" size=${14} style="fill:currentColor" />09:10</span></dt><dd>${t('legend.pick')}</dd>
      <dt><span class="pill booked"><${Icon} name="flag" size=${14} style="fill:currentColor" />11:00</span></dt><dd>${t('legend.booked')}</dd>
      <dt><span class="pill quiet"><${Icon} name="lock" size=${14} />Wed 21:00</span></dt><dd>${t('legend.locked')}</dd>
      <dt><${Icon} name="star" size=${16} style="color:var(--blue);fill:var(--blue)" /></dt><dd>${t('legend.recommended')}</dd>
      <dt><${Icon} name="moon" size=${16} class="dim" /></dt><dd>${t('legend.too_late')}</dd>
    </dl>
    <dl class="legend">
      <dt><span class="name">Max</span></dt><dd>${t('legend.male')}</dd>
      <dt><span class="name alt">Erika</span></dt><dd>${t('legend.female')}</dd>
      <dt><span class="name f">★ Ben</span></dt><dd>${t('legend.friend')}</dd>
      <dt><span class="name anon">${t('anonymous')}</span></dt><dd>${t('legend.anon')}</dd>
    </dl>
    <dl class="legend">
      <dt><span class="kbd">r</span></dt><dd>${t('action.refresh')}</dd>
      <dt><span class="kbd">s</span></dt><dd>${t('action.search')}</dd>
      <dt><span class="kbd">h</span></dt><dd>${t('action.heatmap')}</dd>
      <dt><span class="kbd">p</span></dt><dd>${t('action.players')}</dd>
      <dt><span class="kbd">e</span></dt><dd>${t('action.preferences')}</dd>
      <dt><span class="kbd">,</span></dt><dd>${t('action.settings')}</dd>
      <dt><span class="kbd">a</span></dt><dd>${t('addclub.title')}</dd>
    </dl>
  <//>`;
}

/** Mark a time as your booking, or cancel it. */
function BookingDialog({ booking, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const cancelling = booking.mode === 'cancel';
  async function confirm() {
    setBusy(true);
    try {
      const body = { ...booking.ref, course: booking.course, date: booking.date, time: booking.time };
      await post(cancelling ? '/api/booking/cancel' : '/api/booking', body);
      onDone();
    } catch (failure) {
      setError(t('error.title'));
      setBusy(false);
    }
  }
  return html`<${Sheet} title=${t(cancelling ? 'booking.cancel_title' : 'booking.mark_title', { time: booking.time })} onClose=${onClose} size="small">
    <p>${booking.course} · ${booking.dateText}</p>
    <${Status} kind="error">${error}<//>
    <div class="actions">
      <span class="grow"></span>
      <button class="btn" onClick=${onClose}>${t('booking.not_now')}</button>
      <button class=${'btn ' + (cancelling ? 'danger' : 'pri')} onClick=${confirm} disabled=${busy}>${t(cancelling ? 'booking.cancel' : 'booking.confirm')}</button>
    </div>
  <//>`;
}

function App() {
  const [boot, setBoot] = useState(null);
  const [view, setView] = useState(null); // { kind: 'saved', slug } | { kind: 'preview', id, name }
  const [course, setCourse] = useState(null);
  const [overview, setOverview] = useState(null);
  const [openDate, setOpenDate] = useState(() => (/^\d{4}-\d{2}-\d{2}$/.test(location.hash.slice(1)) ? location.hash.slice(1) : null));
  const [refresh, setRefresh] = useState({ running: false, error: null });
  const [sheet, setSheet] = useState(() => (location.hash.startsWith('#sheet=') ? location.hash.slice(7) : null)); // 'legend' | 'search' | 'heatmap' | 'players' | 'preferences' | 'settings' | 'addclub'
  const [booking, setBooking] = useState(null);
  const [searchTick, setSearchTick] = useState(0);
  const [failure, setFailure] = useState(null);
  const [, tick] = useState(0);
  const current = useRef({ view: null, course: null });
  current.current = { view, course };
  const lastSaved = useRef(null);
  const focusOnOpen = useRef(null); // a day the user just opened: scroll to its pick once its slots are drawn

  // The day header stays pinned under the toolbar while its slots scroll: tell the CSS how tall that is.
  const ready = !!boot;
  useEffect(() => {
    const bar = document.querySelector('.toolbar');
    if (!bar) return undefined;
    const apply = () => document.documentElement.style.setProperty('--toolbar-h', bar.offsetHeight + 'px');
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(bar);
    return () => observer.disconnect();
  }, [ready]);
  useEffect(() => {
    if (!openDate || focusOnOpen.current !== openDate || !overview) return;
    focusOnOpen.current = null;
    const day = overview.days.find((entry) => entry.date === openDate);
    const time = day && focusTime(day);
    const row = time && document.querySelector(`[data-slot="${openDate} ${time}"]`);
    if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [openDate, overview]);

  useEffect(() => {
    history.replaceState(null, '', openDate ? '#' + openDate : location.pathname);
  }, [openDate]);
  useEffect(() => {
    document.title = t('app.title');
  });

  const handleError = useCallback((error) => {
    setFailure(error && (error.status === 403 || error.name === 'TypeError') ? 'gone' : 'error');
  }, []);

  const loadOverview = useCallback(async (forView, forCourse) => {
    try {
      const result = await api('/api/overview' + query({ ...refOf(forView), course: forCourse }));
      const now = current.current.view;
      if (!now || refreshKeyOf(now) !== refreshKeyOf(forView)) return;
      setOverview(result);
      setCourse((previous) => (forCourse || previous === result.course ? previous : result.course));
      setOpenDate((previous) => (previous && result.days.some((day) => day.date === previous) ? previous : result.days.length ? result.days[0].date : null));
      setFailure(null);
    } catch (error) {
      handleError(error);
    }
  }, []);

  const loadBoot = useCallback(async () => {
    const result = await api('/api/bootstrap');
    setBoot(result);
    return result;
  }, []);

  // First load.
  useEffect(() => {
    (async () => {
      try {
        const result = await api('/api/bootstrap');
        await loadStrings(result.language);
        setBoot(result);
        const last = result.last && result.clubs.find((club) => club.slug === result.last.slug);
        const first = last || result.clubs[0];
        if (first) {
          setView({ kind: 'saved', slug: first.slug });
          setCourse(last ? result.last.course : first.default_course || null);
        }
      } catch (error) {
        handleError(error);
      }
    })();
  }, []);

  function startRefresh(force, forView) {
    const target = forView || current.current.view;
    if (!target) return;
    post('/api/refresh', { ...refOf(target), force: force || target.kind === 'preview' })
      .then((status) => setRefresh({ running: !!status.running, error: status.running ? null : status.error }))
      .catch(handleError);
  }

  // The selection changed: load it, and let the scraper fetch what is due.
  const viewKey = view ? refreshKeyOf(view) : null;
  useEffect(() => {
    if (!view) return;
    if (view.kind === 'saved') lastSaved.current = view;
    setOverview(null);
    setRefresh({ running: false, error: null });
    loadOverview(view, course);
    startRefresh(false, view);
  }, [viewKey]);
  useEffect(() => {
    if (!view || !course) return;
    loadOverview(view, course);
    if (view.kind === 'saved') post('/api/last', { slug: view.slug, course }).catch(() => {});
  }, [course]);

  // Keep-alive for the server, a gentle re-read of the data, and a relative-time tick.
  useEffect(() => {
    const ping = setInterval(() => post('/api/ping', {}).catch(handleError), 5000);
    post('/api/ping', {}).catch(() => {});
    const reload = setInterval(() => {
      const { view: v, course: c } = current.current;
      if (v) loadOverview(v, c);
    }, 30000);
    const clock = setInterval(() => tick((n) => n + 1), 30000);
    return () => [ping, reload, clock].forEach(clearInterval);
  }, []);

  // While a refresh runs, poll it; when it ends, read the overview again.
  useEffect(() => {
    if (!refresh.running || !view) return;
    const key = refreshKeyOf(view);
    const poll = setInterval(async () => {
      try {
        const status = await api('/api/refresh/status' + query({ key }));
        if (!status.running) {
          setRefresh({ running: false, error: status.error });
          loadOverview(current.current.view, current.current.course);
        }
      } catch (error) {
        handleError(error);
      }
    }, 1200);
    return () => clearInterval(poll);
  }, [refresh.running, viewKey]);

  // Keyboard: single letters, like the terminal app, when nothing is being typed or open.
  useEffect(() => {
    const onKey = (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (target && (/^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName) || target.isContentEditable)) return;
      if (document.querySelector('.scrim')) return;
      const { view: v } = current.current;
      const open = (name) => (event.preventDefault(), setSheet(name));
      if (event.key === 'r' && v) { event.preventDefault(); startRefresh(true); }
      else if (event.key === 's' && v) open('search');
      else if (event.key === 'h' && v) open('heatmap');
      else if (event.key === 'p' && v) open('players');
      else if (event.key === 'e') open('preferences');
      else if (event.key === ',') open('settings');
      else if (event.key === 'a') open('addclub');
      else if (event.key === '?') open('legend');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ---- actions

  const selectClub = (value) => {
    if (value === ADD_CLUB) return setSheet('addclub');
    setCourse(null);
    setView({ kind: 'saved', slug: value });
  };
  const askBooking = (date, time, courseName, ref, cancel) =>
    setBooking({ mode: cancel ? 'cancel' : 'mark', date, time, course: courseName, ref, dateText: dayLabel(date) });
  const pickSlot = (day, slot) => askBooking(day.date, slot.time, overview.course, refOf(view), slot.booked_by_you);
  const markFromSearch = (match) => askBooking(match.date, match.time, match.course, refOf(view), false);
  const bookingDone = () => {
    setBooking(null);
    setSearchTick((n) => n + 1);
    loadOverview(view, course);
  };
  const ackBanner = async (banner) => {
    await post('/api/banners/ack', { ...refOf(view), ids: [banner.id] }).catch(() => {});
    loadOverview(view, course);
  };
  const clubsChanged = async () => {
    const result = await loadBoot();
    const v = current.current.view;
    if (v && v.kind === 'saved' && !result.clubs.some((club) => club.slug === v.slug)) {
      const next = result.clubs[0];
      setCourse(null);
      setView(next ? { kind: 'saved', slug: next.slug } : null);
      if (!next) setOverview(null);
    } else if (!v && result.clubs[0]) {
      setView({ kind: 'saved', slug: result.clubs[0].slug });
    }
  };
  const openPreview = (entry) => {
    setSheet(null);
    setCourse(null);
    setView({ kind: 'preview', id: entry.id, name: entry.name || entry.id });
  };
  const savePreview = async () => {
    const result = await post('/api/club/add', { club_id: view.id, name: view.name });
    if (result.ok) {
      await loadBoot();
      setCourse(null);
      setView({ kind: 'saved', slug: result.slug });
    }
  };
  const closePreview = () => {
    setCourse(null);
    setView(lastSaved.current || (boot && boot.clubs[0] ? { kind: 'saved', slug: boot.clubs[0].slug } : null));
  };

  // ---- render

  if (failure === 'gone') return html`<${Empty} title=${t('error.gone.title')} text=${t('error.gone.text')} />`;
  if (failure === 'error' && !overview && !boot) return html`<${Empty} title=${t('error.title')} text=${t('error.text')} />`;
  if (!boot) return null;

  const club = overview && overview.club;
  const units = (overview && overview.units) || boot.units;
  const showHandicaps = overview ? overview.show_handicaps : boot.show_handicaps;
  const clubOptions = [...boot.clubs.map((entry) => ({ value: entry.slug, label: entry.name })), { value: ADD_CLUB, label: '＋ ' + t('addclub.title') + '…' }];
  const courseOptions = ((overview && overview.courses) || []).map((name) => ({ value: name, label: name }));
  const freshness = overview && overview.freshness;
  const noClub = !view;
  const empty = overview && overview.days.length === 0;
  const clubForSheets = club || (view && view.kind === 'preview' ? { slug: null, id: view.id, name: view.name } : null);
  const tool = (name, icon, label, key, onClick, disabled) => html`
    <button class="tool" onClick=${onClick} disabled=${disabled} title=${label + ' (' + key + ')'} aria-keyshortcuts=${key}>
      <${Icon} name=${icon} class=${name === 'refresh' && refresh.running ? 'spin' : ''} /><span class="tool-label">${label}</span></button>`;

  return html`
    <div class="app">
      <header class="toolbar">
        ${boot.clubs.length > 0 && view && view.kind === 'saved' && html`<${Select} id="club" aria-label=${t('club')} value=${view.slug} options=${clubOptions} onChange=${selectClub} />`}
        ${view && view.kind === 'preview' && html`<span class="picker-static" title=${view.name}>${view.name}</span>`}
        ${courseOptions.length > 0 && html`<${Select} id="course" aria-label=${t('course')} value=${(overview && overview.course) || course} options=${courseOptions} onChange=${setCourse} />`}
        <span class="grow"></span>
        ${tool('refresh', 'refresh', t(refresh.running ? 'refreshing' : 'action.refresh'), 'r', () => startRefresh(true), refresh.running || noClub)}
        ${tool('search', 'search', t('action.search'), 's', () => setSheet('search'), noClub || !overview || !overview.course)}
        ${tool('heatmap', 'grid', t('action.heatmap'), 'h', () => setSheet('heatmap'), noClub || !overview || !overview.course)}
        ${tool('players', 'users', t('action.players'), 'p', () => setSheet('players'), noClub)}
        ${tool('preferences', 'sliders', t('action.preferences'), 'e', () => setSheet('preferences'), false)}
        ${tool('settings', 'gear', t('action.settings'), ',', () => setSheet('settings'), false)}
      </header>
      <main class="main">
        ${view && view.kind === 'preview' && html`
          <div class="preview-bar" role="status"><${Icon} name="info" size=${18} />
            <span>${t('preview.not_saved', { name: view.name })}</span><span class="grow"></span>
            <button class="btn pri" onClick=${savePreview}><${Icon} name="plus" size=${16} />${t('preview.add')}</button>
            <button class="btn" onClick=${closePreview}>${t('preview.close')}</button></div>`}
        ${noClub && html`<${Empty} title=${t('empty.no_clubs.title')} text=${t('empty.no_clubs.text')}>
          <div class="actions center"><button class="btn pri" onClick=${() => setSheet('addclub')}><${Icon} name="plus" size=${16} />${t('addclub.title')}</button>
            <button class="btn" onClick=${() => setSheet('settings')}>${t('settings.title')}</button></div><//>`}
        ${overview && html`<${Banners} banners=${overview.banners} onAcknowledge=${ackBanner} />`}
        ${view && !overview && !failure && html`<${Empty} title=${t('empty.updating')} />`}
        ${empty && html`<${Empty}
          title=${refresh.running ? t('empty.updating') : refresh.error ? refreshErrorText(refresh.error) : t('empty.no_data.title')}
          text=${refresh.running || refresh.error ? '' : t('empty.no_data.text')} />`}
        ${overview && overview.days.map((day) => html`
          <${DayCard} key=${day.date} day=${day} open=${openDate === day.date} units=${units} showHandicaps=${showHandicaps} onPick=${pickSlot}
            onToggle=${() => { focusOnOpen.current = openDate === day.date ? null : day.date; setOpenDate(openDate === day.date ? null : day.date); }} />`)}
      </main>
      <footer class="footer">
        <div class="status">
          <span class=${'dot' + (freshness && freshness.warning ? ' warn' : refresh.running ? ' busy' : '')}></span>
          <span>${refresh.running ? t('refreshing') : updatedText(freshness && freshness.last_success_at)}</span>
          ${refresh.error && overview && overview.days.length > 0 && html`<span class="warning">${refreshErrorText(refresh.error)}</span>`}
          ${freshness && freshness.warning && html`<span class="warning">${freshness.warning}</span>`}
        </div>
        <button class="tool small" onClick=${() => setSheet('legend')} title=${t('legend') + ' (?)'}><${Icon} name="info" size=${16} />${t('legend')}</button>
      </footer>
      ${sheet === 'legend' && html`<${Legend} onClose=${() => setSheet(null)} />`}
      ${sheet === 'preferences' && html`<${PreferencesSheet} clubId=${club && club.id} onClose=${() => setSheet(null)} onSaved=${() => view && loadOverview(view, course)} />`}
      ${sheet === 'settings' && html`<${SettingsSheet} clubId=${club && club.id} onClose=${() => setSheet(null)}
        onSaved=${(language) => { if (language && language !== boot.language) location.reload(); else { loadBoot(); if (view) loadOverview(view, course); } }}
        onAddClub=${() => setSheet('addclub')} onClubsChanged=${clubsChanged} />`}
      ${sheet === 'addclub' && html`<${AddClubSheet} onClose=${() => setSheet(null)} onAdded=${clubsChanged} onOpen=${openPreview} />`}
      ${sheet === 'search' && clubForSheets && overview && html`<${SearchSheet} club=${clubForSheets} course=${overview.course} units=${units} showHandicaps=${showHandicaps}
        refreshKey=${searchTick} onClose=${() => setSheet(null)} onMark=${markFromSearch} />`}
      ${sheet === 'heatmap' && clubForSheets && overview && html`<${HeatmapSheet} club=${clubForSheets} course=${overview.course} onClose=${() => setSheet(null)} />`}
      ${sheet === 'players' && clubForSheets && html`<${PlayersSheet} club=${clubForSheets} showHandicaps=${showHandicaps} onClose=${() => setSheet(null)} onChanged=${() => view && loadOverview(view, course)} />`}
      ${booking && html`<${BookingDialog} booking=${booking} onClose=${() => setBooking(null)} onDone=${bookingDone} />`}
    </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
