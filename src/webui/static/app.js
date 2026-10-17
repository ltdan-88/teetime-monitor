// Teetime Monitor web UI: the shell. Preact + htm, no build step; data from /api/* (src/webui/server.py).

import {
  html, render, useState, useEffect, useRef, useCallback, api, post, query, loadStrings, t, language, updatedText, dayLabel, applyScale, loadThemes, applyTheme, systemTheme,
  Icon, Sheet, Select, Status,
  tempTone, rainTone, windTone,
} from '/lib.js';
import { DayCard, Banners, focusTime } from '/overview.js';
import { PreferencesSheet, SettingsSheet } from '/forms.js';
import { AddClubSheet } from '/addclub.js';
import { SearchSheet, forgetSearch } from '/search.js';
import { HeatmapSheet } from '/heatmap.js';
import { ReservationsSheet } from '/reservations.js';
import { TournamentsSheet } from '/tournaments.js';
import { PlayersSheet } from '/players.js';
import { ViewMenu } from '/viewmenu.js';
import { BottomPanel } from '/panel.js';
import { Welcome } from '/welcome.js';
import { UpdateNotice, UpdateSheet } from '/update.js';
import { installTouchTips } from '/tips.js';

const ADD_CLUB = '__add_club__';

/** A request that failed to even reach the server (a dropped connection on Wi-Fi, a server that is just restarting) is tried
 *  again a few times before the page gives up. */
async function withRetry(work, tries = 4) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await work();
    } catch (error) {
      if (attempt >= tries || !(error instanceof TypeError)) throw error;
      await new Promise((done) => setTimeout(done, 600 * attempt));
    }
  }
}

/** The texts of the "cannot reach it" screen also work when the page's own strings never arrived. */
function say(key, fallback) {
  const text = t(key);
  return text === key ? fallback : text;
}
applyScale();
installTouchTips();

const refOf = (view) => (view.kind === 'saved' ? { slug: view.slug } : { club_id: view.id, name: view.name });
const refreshKeyOf = (view) => (view.kind === 'saved' ? view.slug : 'club:' + view.id);

/** The text for a refresh that ended in an error: a known rejection (a club with no tee sheet ...)
 *  in plain words, anything else as "Refresh failed: ...". */
function refreshErrorText(error) {
  const known = t('preview.' + error);
  return known !== 'preview.' + error ? known : t('error.refresh', { error });
}

/** One standing explanation for days that all say "too dark": your window opens after the latest start
 *  that still finishes before sunset (the terminal app's and the Mac app's hint, with a way to the setting). */
function WindowHint({ hint, onPreferences, onDismiss }) {
  const hours = String(Math.round((hint.round_minutes / 60) * 100) / 100).replace('.', language() === 'de' ? ',' : '.');
  let text = t('hint.window_too_late', { after: hint.window_after, hours, sunset: hint.sunset, latest: hint.latest_start });
  if (hint.alternative_courses && hint.alternative_courses.length) {
    text += ' ' + t('overview.hint_alternative', { courses: hint.alternative_courses.join(', ') });
  }
  return html`<div class="banner hint-bar" role="status"><${Icon} name="info" size=${18} /><span>${text}</span>
    <div class="banner-actions">
      <button class="icon-btn" onClick=${onPreferences} aria-label=${t('action.preferences')} title=${t('action.preferences')}><${Icon} name="clock" size=${18} /></button>
      <button class="icon-btn" onClick=${onDismiss} aria-label=${t('dismiss')} title=${t('dismiss')}><${Icon} name="close" size=${16} /></button>
    </div></div>`;
}

/** The app's name, always in view (the browser tab has it too): beside the toolbar on wide windows, a slim line above it on narrow ones. */
function Brand({ className }) {
  return html`<div class=${className}><img class="brand-icon" src="/icons/icon-64.png" alt="" width="22" height="22" /><span>${t('app.title')}</span></div>`;
}

function Empty({ title, text, children }) {
  return html`<div class="empty"><h2>${title}</h2>${text && html`<p>${text}</p>`}${children}</div>`;
}

function Legend({ onClose }) {
  const swatch = (color, state) => html`<span class=${'swatch o-' + state} style=${{ backgroundColor: color }}></span>`;
  const toolIcon = (name) => html`<span class="tool-ico"><${Icon} name=${name} size=${18} /></span>`;
  return html`<${Sheet} title=${t('legend.title')} onClose=${onClose} size="small">
    <p class="hint">${t('legend.touch')}</p>
    <details class="legend-group" name="legend"><summary>${t('legend.group.tools')}</summary>
    <dl class="legend">
      <dt>${toolIcon('search')}</dt><dd>${t('legend.tool.search')}</dd>
      <dt>${toolIcon('grid')}</dt><dd>${t('legend.tool.heatmap')}</dd>
      <dt>${toolIcon('calendarcheck')}</dt><dd>${t('legend.tool.reservations')}</dd>
      <dt>${toolIcon('trophy')}</dt><dd>${t('legend.tool.tournaments')}</dd>
      <dt>${toolIcon('users')}</dt><dd>${t('legend.tool.players')}</dd>
      <dt>${toolIcon('clock')}</dt><dd>${t('legend.tool.preferences')}</dd>
      <dt>${toolIcon('sliders')}</dt><dd>${t('legend.tool.settings')}</dd>
      <dt>${toolIcon('refresh')}</dt><dd>${t('legend.tool.refresh')}</dd>
      <dt>${toolIcon('palette')}</dt><dd>${t('legend.tool.view')}</dd>
    </dl>
    </details>
    <details class="legend-group" name="legend" open><summary>${t('legend.group.times')}</summary>
    <dl class="legend">
      <dt>${swatch('var(--green)', 'open')}</dt><dd>${t('legend.occ.open')}</dd>
      <dt>${swatch('var(--orange)', 'mid')}</dt><dd>${t('legend.occ.mid')}</dd>
      <dt>${swatch('var(--red)', 'full')}</dt><dd>${t('legend.occ.full')}</dd>
      <dt>${swatch('var(--faint)', 'none')}</dt><dd>${t('legend.occ.none')}</dd>
    </dl>
    <dl class="legend">
      <dt><span class="hits-link"><${Icon} name="search" size=${13} />12</span></dt><dd>${t('legend.count')}</dd>
      <dt><span class="seats legend-seats"><span class="seat taken"></span><span class="seat friend"></span><span class="seat"></span><span class="seat"></span></span></dt><dd>${t('legend.seats')}</dd>
      <dt><span class="pill booked"><${Icon} name="flag" size=${14} style="fill:currentColor" />11:00</span></dt><dd>${t('legend.booked')}</dd>
      <dt><span class="pill quiet"><${Icon} name="lock" size=${14} />Wed 21:00</span></dt><dd>${t('legend.locked')}</dd>
      <dt><span class="pill quiet word">${t('badge.rain')}</span></dt><dd>${t('legend.no_play')}</dd>
      <dt><${Icon} name="star" size=${16} style="color:var(--accent);fill:var(--accent)" /></dt><dd>${t('legend.recommended')}</dd>
      <dt><${Icon} name="moon" size=${16} class="dim" /></dt><dd>${t('legend.too_late')}</dd>
      <dt><span class="chipdemo"><${Icon} name="users" size=${14} />3</span></dt><dd>${t('legend.chip')}</dd>
      <dt><span class="cell warn">13°</span></dt><dd>${t('legend.warn')}</dd>
    </dl>
    <p class="hint">${t('legend.slot_tap')}</p>
    </details>
    <details class="legend-group" name="legend"><summary>${t('legend.group.weather')}</summary>
    <dl class="legend">
      <dt><span class="tones"><span style=${tempTone(3)}>3°</span> <span style=${tempTone(13)}>13°</span> <span style=${tempTone(21)}>21°</span> <span style=${tempTone(30)}>30°</span></span></dt><dd>${t('legend.temp_colors')}</dd>
      <dt><span class="tones"><span style=${rainTone(20)}>20%</span> <span style=${rainTone(80)}>80%</span></span></dt><dd>${t('legend.rain_colors')}</dd>
      <dt><span class="tones"><span style=${windTone(20)}>20</span> <span style=${windTone(40)}>40</span></span></dt><dd>${t('legend.wind_colors')}</dd>
    </dl>
    </details>
    <details class="legend-group" name="legend"><summary>${t('legend.group.players')}</summary>
    <dl class="legend">
      <dt><span class="name">Max</span></dt><dd>${t('legend.male')}</dd>
      <dt><span class="name alt">Erika</span></dt><dd>${t('legend.female')}</dd>
      <dt><span class="name f">★ Ben</span></dt><dd>${t('legend.friend')}</dd>
      <dt><span class="name anon">${t('anonymous')}</span></dt><dd>${t('legend.anon')}</dd>
    </dl>
    </details>
    <details class="legend-group" name="legend"><summary>${t('legend.group.keys')}</summary>
    <dl class="legend">
      <dt><span class="kbd">r</span></dt><dd>${t('action.refresh')}</dd>
      <dt><span class="kbd">s</span></dt><dd>${t('action.search')}</dd>
      <dt><span class="kbd">h</span></dt><dd>${t('action.heatmap')}</dd>
      <dt><span class="kbd">b</span></dt><dd>${t('action.reservations')}</dd>
      <dt><span class="kbd">t</span></dt><dd>${t('action.tournaments')}</dd>
      <dt><span class="kbd">p</span></dt><dd>${t('action.players')}</dd>
      <dt><span class="kbd">e</span></dt><dd>${t('action.preferences')}</dd>
      <dt><span class="kbd">,</span></dt><dd>${t('action.settings')}</dd>
      <dt><span class="kbd">a</span></dt><dd>${t('addclub.title')}</dd>
      <dt><span class="kbd">v</span></dt><dd>${t('action.view')}</dd>
    </dl>
    </details>
  <//>`;
}

/** Book a time on pc caddie for yourself, or cancel your booking there. Nothing happens until the button is pressed. */
function BookingDialog({ booking, onClose, onDone }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const cancelling = booking.mode === 'cancel';
  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const body = { ...booking.ref, course: booking.course, date: booking.date, time: booking.time };
      await post(cancelling ? '/api/booking/cancel' : '/api/booking', body);
      onDone();
    } catch (failure) {
      const payload = (failure && failure.payload) || {};
      const key = 'booking.error.' + (payload.error || 'other');
      const named = t(key, { message: payload.message || '' });
      setError(named === key ? t('booking.error.other', { message: payload.message || '' }) : named);
      setBusy(false);
    }
  }
  return html`<${Sheet} title=${t(cancelling ? 'booking.cancel_title' : 'booking.book_title', { time: booking.time })} onClose=${busy ? () => {} : onClose} size="small">
    <p><b>${booking.course}</b> · ${booking.dateText}, ${booking.time}</p>
    <p class="hint">${t(cancelling ? 'booking.cancel_explain' : 'booking.book_explain')}</p>
    ${busy && html`<${Status} kind="busy">${t(cancelling ? 'booking.cancelling' : 'booking.booking')}<//>`}
    <${Status} kind="error">${error}<//>
    <div class="actions">
      <span class="grow"></span>
      <button class="btn" onClick=${onClose} disabled=${busy}>${t('booking.not_now')}</button>
      <button class=${'btn ' + (cancelling ? 'danger' : 'pri')} onClick=${confirm} disabled=${busy}>${t(cancelling ? 'booking.cancel' : 'booking.book')}</button>
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
  const [tournamentDate, setTournamentDate] = useState(null); // the day the Tournaments window opens on (a tournament slot in the tee sheet), else this month
  const [prefsBack, setPrefsBack] = useState(null);
  const [searchDay, setSearchDay] = useState(null); // the day whose count was tapped: Search opens on it
  const [tabCourse, setTabCourse] = useState(null); // the course tab of Search and the Heatmap (one course at a time) // the sheet Preferences was opened from (Search): it comes back when they close
  const [sheet, setSheet] = useState(() => (location.hash.startsWith('#sheet=') ? location.hash.slice(7) : null)); // 'legend' | 'search' | 'heatmap' | 'players' | 'preferences' | 'settings' | 'addclub'
  const [booking, setBooking] = useState(null);
  const [viewOpen, setViewOpen] = useState(false);
  const [display, setDisplay] = useState(null); // { units, showHandicaps }: applied at once, saved in the background
  const [picksPending, setPicksPending] = useState(false);
  const [jumpTick, setJumpTick] = useState(0);
  const [update, setUpdate] = useState(null); // { latest, newer, url, command, can_update ... }: a newer release exists
  const [dismissedUpdate, setDismissedUpdate] = useState(() => { try { return localStorage.getItem('tm_update_dismissed'); } catch (failure) { return null; } });
  const dismissUpdate = () => { try { localStorage.setItem('tm_update_dismissed', update.latest); } catch (failure) { /* just not remembered */ } setDismissedUpdate(update.latest); };
  // "Check for updates" always shows what it found, even a version dismissed before
  // The "your window starts too late" note can be put away. It stays away until the window or the round length changes (the sunset moves every day, so it is not part of the key).
  const hintKey = overview && overview.hint ? [overview.club.id, overview.hint.window_after, overview.hint.round_minutes].join('|') : null;
  const [dismissedHint, setDismissedHint] = useState(() => { try { return localStorage.getItem('tm_hint_dismissed'); } catch (failure) { return null; } });
  const dismissHint = () => { try { localStorage.setItem('tm_hint_dismissed', hintKey); } catch (failure) { /* just not remembered */ } setDismissedHint(hintKey); };
  const checked = (result) => { if (result && result.newer) { try { localStorage.removeItem('tm_update_dismissed'); } catch (failure) { /* fine */ } setDismissedUpdate(null); } setUpdate(result); };
  const loadSeq = useRef(0);
  const [searchTick, setSearchTick] = useState(0);
  const [failure, setFailure] = useState(null);
  const [, tick] = useState(0);
  const [tips, setTips] = useState(() => { try { return localStorage.getItem('tm_tips') !== '0'; } catch (failure) { return true; } }); // the tip cards at the bottom
  const chooseTips = (on) => { try { localStorage.setItem('tm_tips', on ? '1' : '0'); } catch (failure) { /* just not remembered */ } setTips(on); };
  const [showPast, setShowPast] = useState(false); // the past days instead of the coming ones
  const current = useRef({ view: null, course: null, showPast: false });
  current.current = { view, course, showPast };
  const lastSaved = useRef(null);
  const focusOnOpen = useRef(null); // a day the user just opened: scroll to its pick once its slots are drawn
  const jumpTarget = useRef(null); // { date, time, course }: a slot to open, scroll to and flash once its course is on screen

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
    const wrap = document.querySelector('.card.open .dh-wrap');
    if (!wrap) return undefined;
    const apply = () => document.documentElement.style.setProperty('--dh-h', wrap.offsetHeight + 'px');
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [openDate, overview]);
  useEffect(() => {
    if (!openDate || focusOnOpen.current !== openDate || !overview) return;
    focusOnOpen.current = null;
    const day = overview.days.find((entry) => entry.date === openDate);
    const time = day && focusTime(day);
    const row = time && document.querySelector(`[data-slot="${openDate} ${time}"]`);
    if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [openDate, overview]);

  useEffect(() => {
    const target = jumpTarget.current;
    if (!target || !overview || overview.course !== target.course || (target.slug && overview.club && overview.club.slug !== target.slug)) return;
    const row = document.querySelector(`[data-slot="${target.date} ${target.time}"]`);
    if (!row) return; // the days are still loading, or the slot is not on this course
    jumpTarget.current = null;
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    row.classList.remove('flash');
    void row.offsetWidth; // restart the animation if it is already running
    row.classList.add('flash');
    setTimeout(() => row.classList.remove('flash'), 2400);
  }, [openDate, overview, jumpTick]);

  // Leaving Search and the Heatmap forgets their filters, course and day. A count tapped right after a sheet closed must not
  // be undone by that sheet's reset, which can still be on its way: `toSearch` holds it off until Search is up.
  const toSearch = useRef(false);
  useEffect(() => {
    if (sheet === 'search' || sheet === 'heatmap') toSearch.current = false;
    else if (!toSearch.current) { forgetSearch(); setTabCourse(null); setSearchDay(null); }
  }, [sheet]);
  const searchOn = (date) => { toSearch.current = true; forgetSearch(); setTabCourse(null); setSearchDay(date); setSheet('search'); };
  useEffect(() => {
    history.replaceState(null, '', openDate ? '#' + openDate : location.pathname);
  }, [openDate]);
  useEffect(() => {
    document.title = t('app.title');
  });

  // With no theme saved the page follows the system's dark or light.
  useEffect(() => {
    if (!boot || boot.theme || !window.matchMedia) return undefined;
    const query = window.matchMedia('(prefers-color-scheme: light)');
    const follow = () => applyTheme(systemTheme());
    query.addEventListener('change', follow);
    return () => query.removeEventListener('change', follow);
  }, [boot && boot.theme]);

  useEffect(() => {
    if (!boot) return undefined;
    const look = () => api('/api/update').then(setUpdate).catch(() => {});
    look();
    const timer = setInterval(look, 30 * 60 * 1000);
    window.addEventListener('focus', look); // a tab that has sat open for days looks again when you come back to it
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', look);
    };
  }, [!!boot]);

  const handleError = useCallback((error) => {
    setFailure(error && (error.status === 403 || error.name === 'TypeError') ? 'gone' : 'error');
  }, []);

  const loadOverview = useCallback(async (forView, forCourse) => {
    const mine = ++loadSeq.current;
    const stale = () => mine !== loadSeq.current || !current.current.view || refreshKeyOf(current.current.view) !== refreshKeyOf(forView);
    const apply = (result) => {
      setOverview(result);
      setCourse((previous) => (forCourse || previous === result.course ? previous : result.course));
      setOpenDate((previous) => (previous && result.days.some((day) => day.date === previous) ? previous : null));
      setFailure(null);
    };
    try {
      // The days come straight from the database; the picks (which can take seconds, with AI ranking on)
      // follow in a second request, so switching a course or a club never waits for them.
      const quick = await api('/api/overview' + query({ ...refOf(forView), course: forCourse, picks: 0, history: current.current.showPast ? 1 : null }));
      if (stale()) return;
      apply(quick);
      if (!quick.picks_pending) {
        setPicksPending(false);
        return;
      }
      setPicksPending(true);
      const full = await api('/api/overview' + query({ ...refOf(forView), course: quick.course }));
      if (stale()) return;
      apply(full);
      setPicksPending(false);
    } catch (error) {
      if (!stale()) setPicksPending(false);
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
        const result = await withRetry(() => api('/api/bootstrap'));
        await withRetry(() => loadStrings(result.language));
        await withRetry(() => loadThemes());
        applyTheme(result.theme || systemTheme());
        setBoot(result);
        setDisplay({ units: result.units, showHandicaps: result.show_handicaps });
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
      .then((status) => {
        setRefresh({ running: !!status.running, error: status.running ? null : status.error });
        // a Refresh that was already over when the answer came (nothing to fetch, or a very fast club) still reads the data again
        if (force && !status.running) loadOverview(target, current.current.course);
      })
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
    if (!view) return;
    setOpenDate(null);
    loadOverview(view, course);
  }, [showPast]);
  useEffect(() => {
    if (!view || !course) return;
    loadOverview(view, course);
    if (view.kind === 'saved') post('/api/last', { slug: view.slug, course }).catch(() => {});
  }, [course]);

  // Keep-alive for the server, a gentle re-read of the data, and a relative-time tick.
  useEffect(() => {
    // The ping also says which server process answered: once it is another one (an update restarted the server)
    // this page's scripts are the old ones, so it loads again by itself. Only a new process counts, not a new version
    // number: a server that has been updated in place but not restarted still serves the old code.
    // And when the server was out of reach (the "cannot reach" screen) and answers again, the page loads again too,
    // so nobody has to press "Try again" while the server restarts.
    let boot = null;
    let wasDown = false;
    const ping = async () => {
      try {
        const answer = await post('/api/ping', {});
        if (boot === null) boot = answer.boot;
        else if (wasDown || (answer.boot && answer.boot !== boot)) location.reload();
      } catch (error) {
        if (boot !== null) { wasDown = true; handleError(error); }
      }
    };
    const pinger = setInterval(ping, 5000);
    const wake = () => { if (document.visibilityState === 'visible') ping(); };  // a tab that slept through the update
    document.addEventListener('visibilitychange', wake);
    window.addEventListener('online', wake);
    ping();
    const reload = setInterval(() => {
      const { view: v, course: c } = current.current;
      if (v) loadOverview(v, c);
    }, 30000);
    const clock = setInterval(() => tick((n) => n + 1), 30000);
    return () => { [pinger, reload, clock].forEach(clearInterval); document.removeEventListener('visibilitychange', wake); window.removeEventListener('online', wake); };
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
      else if (event.key === 'b') open('reservations');
      else if (event.key === 't' && v) (event.preventDefault(), openTournaments(null));
      else if (event.key === 'e') open('preferences');
      else if (event.key === ',') open('settings');
      else if (event.key === 'a') open('addclub');
      else if (event.key === 'v') { event.preventDefault(); setViewOpen((o) => !o); }
      else if (event.key === '?') open('legend');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ---- actions

  const selectClub = (value) => {
    if (value === ADD_CLUB) return setSheet('addclub');
    setOpenDate(null); // a new club or course starts collapsed, like the Mac app
    setCourse(null);
    setView({ kind: 'saved', slug: value });
  };
  const askBooking = (date, time, courseName, ref, cancel) =>
    setBooking({ mode: cancel ? 'cancel' : 'book', date, time, course: courseName, ref, dateText: dayLabel(date) });
  const pickSlot = (day, slot) => askBooking(day.date, slot.time, overview.course, refOf(view), slot.booked_by_you);
  /** Open a day and bring one of its slots into view, switching to its course first when needed. */
  const openTournaments = (date) => { setTournamentDate(date); setSheet('tournaments'); };
  /** `slug`: another saved club to switch to first (a player's tee time there, from the shared directory). */
  const jumpTo = (date, time, courseName, slug = null) => {
    const target = courseName || (slug ? null : overview && overview.course);  // another club: its own course, once it is open
    focusOnOpen.current = null;
    jumpTarget.current = { date, time, course: target, slug };
    if (slug && !(view && view.kind === 'saved' && view.slug === slug)) {
      setCourse(target);
      setView({ kind: 'saved', slug });
    } else if (overview && target !== overview.course) setCourse(target);
    setOpenDate(date);
    setJumpTick((n) => n + 1);
  };
  const markFromSearch = (match) => askBooking(match.date, match.time, match.course, match.ref || refOf(view), false);
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

  if (failure === 'gone') {
    return html`<${Empty} title=${say('error.gone.title', 'Cannot reach Teetime Monitor')}
      text=${say('error.gone.text', 'The program was stopped, or the connection dropped. Start it again if needed, or try once more.')}>
      <div class="actions center"><button class="btn pri" onClick=${() => location.reload()}>${say('error.retry', 'Try again')}</button></div><//>`;
  }
  if (failure === 'error' && !overview && !boot) return html`<${Empty} title=${t('error.title')} text=${t('error.text')} />`;
  if (!boot) return null;

  const club = overview && overview.club;
  const units = display ? display.units : boot.units;
  const showHandicaps = display ? display.showHandicaps : boot.show_handicaps;
  const clubOptions = [...boot.clubs.map((entry) => ({ value: entry.slug, label: entry.name })), { value: ADD_CLUB, label: '＋ ' + t('addclub.title') + '…' }];
  const courseOptions = ((overview && overview.courses) || []).map((name) => ({ value: name, label: name }));
  const freshness = overview && overview.freshness;
  const noClub = !view;
  const empty = overview && overview.days.length === 0 && !showPast;
  const clubForSheets = club || (view && view.kind === 'preview' ? { slug: null, id: view.id, name: view.name } : null);
  const tool = (name, icon, label, key, onClick, disabled, extra = '') => html`
    <button class=${'tool' + extra} onClick=${onClick} disabled=${disabled} title=${label + ' (' + key + ')'} aria-keyshortcuts=${key}>
      <${Icon} name=${icon} class=${name === 'refresh' && refresh.running ? 'spin' : ''} /><span class="tool-label">${label}</span></button>`;
  const noCourse = noClub || !overview || !overview.course;
  // Search and the Heatmap are one window with two tabs: both answer "when should I play?"
  const searchTabs = (active) => [
    { key: 'search', label: t('search.tab.free'), on: active === 'search', onSelect: () => setSheet('search') },
    { key: 'heatmap', label: t('action.heatmap'), on: active === 'heatmap', onSelect: () => setSheet('heatmap') },
  ];

  return html`
    <div class="app">
      <${Brand} className="brand top" />
      <header class="toolbar">
        <${Brand} className="brand in-bar" />
        <div class="toolbar-picks">
        ${boot.clubs.length > 0 && view && view.kind === 'saved' && html`<${Select} id="club" aria-label=${t('club')} value=${view.slug} options=${clubOptions} onChange=${selectClub} />`}
        ${view && view.kind === 'preview' && html`<span class="picker-static" title=${view.name}>${view.name}</span>`}
        ${courseOptions.length > 0 && html`<${Select} id="course" aria-label=${t('course')} value=${(overview && overview.course) || course} options=${courseOptions} onChange=${(value) => { setOpenDate(null); setCourse(value); }} />`}
        </div>
        <div class="toolbar-tools">
        ${tool('search', 'search', t('action.search'), 's', () => setSheet('search'), noClub || !overview || !overview.course)}
        ${tool('reservations', 'calendarcheck', t('action.reservations'), 'b', () => setSheet('reservations'), boot.clubs.length === 0)}
        ${tool('tournaments', 'trophy', t('action.tournaments'), 't', () => openTournaments(null), noClub || !(club && club.slug))}
        ${tool('players', 'users', t('action.players'), 'p', () => setSheet('players'), noClub)}
        ${tool('preferences', 'clock', t('action.preferences'), 'e', () => setSheet('preferences'), false, ' setup')}
        ${tool('settings', 'sliders', t('action.settings'), ',', () => setSheet('settings'), false)}
        </div>
      </header>
      <main class="main">
        <h1 class="sr-only">${t('app.title')}</h1>
        ${view && view.kind === 'preview' && html`
          <div class="preview-bar" role="status"><${Icon} name="info" size=${18} />
            <span>${t('preview.not_saved', { name: view.name })}</span><span class="grow"></span>
            <button class="btn pri" onClick=${savePreview}><${Icon} name="plus" size=${16} />${t('preview.add')}</button>
            <button class="btn" onClick=${closePreview}>${t('preview.close')}</button></div>`}
        ${noClub && html`<${Welcome} onAddClub=${() => setSheet('addclub')} onLogin=${() => setSheet('settings')} />`}
        ${update && update.newer && dismissedUpdate !== update.latest && html`<${UpdateNotice} update=${update} onUpdate=${() => setSheet('update')} onDismiss=${dismissUpdate} />`}
        ${overview && html`<${Banners} banners=${overview.banners} onAcknowledge=${ackBanner} />`}
        ${showPast && html`
          <div class="preview-bar" role="status"><${Icon} name="info" size=${18} /><span>${t('history.note')}</span><span class="grow"></span>
            <button class="btn pri" onClick=${() => setShowPast(false)}>${t('history.back')}</button></div>`}
        ${showPast && overview && overview.days.length === 0 && html`<${Empty} title=${t('history.empty.title')} text=${t('history.empty.text')} />`}
        ${overview && overview.hint && hintKey !== dismissedHint && html`<${WindowHint} hint=${overview.hint} onPreferences=${() => setSheet('preferences')} onDismiss=${dismissHint} />`}
        ${view && !overview && !failure && html`<${Empty} title=${t('empty.updating')} />`}
        ${empty && html`<${Empty}
          title=${refresh.running ? t('empty.updating') : refresh.error ? refreshErrorText(refresh.error) : t('empty.no_data.title')}
          text=${refresh.running || refresh.error ? '' : t('empty.no_data.text')} />`}
        ${overview && overview.days.map((day) => html`
          <${DayCard} key=${day.date} day=${day} open=${openDate === day.date} units=${units} showHandicaps=${showHandicaps} onPick=${pickSlot} onTournament=${(date) => openTournaments(date)} onAlternative=${(day, alt) => jumpTo(day.date, alt.time, alt.course)}
            best=${Math.max(1, ...overview.days.map((d) => d.matches || 0))} onSearch=${searchOn}
            onToggle=${() => { focusOnOpen.current = openDate === day.date ? null : day.date; setOpenDate(openDate === day.date ? null : day.date); }} />`)}
        ${tips && !showPast && overview && club && html`<${BottomPanel} refQuery=${refOf(view)} course=${overview.course} ready=${!picksPending} units=${units}
          dataKey=${[overview.freshness && overview.freshness.last_success_at, overview.days.map((day) => day.date + (day.booked_time || '')).join()].join('|')}
          onOpen=${(card) => jumpTo(card.date, card.time, card.course)} />`}
      </main>
      <footer class="footer">
        <div class="status">
          <button class="tool small refresh-btn" onClick=${() => startRefresh(true)} disabled=${refresh.running || noClub} title=${t('action.refresh') + ' (r)'}
            aria-label=${t('action.refresh')} aria-keyshortcuts="r"><${Icon} name="refresh" size=${18} class=${refresh.running ? 'spin' : ''} /></button>
          <span class=${'dot' + (freshness && freshness.warning ? ' warn' : refresh.running ? ' busy' : '')}></span>
          <span>${refresh.running ? t('refreshing') : updatedText(freshness && freshness.last_success_at)}</span>
          ${picksPending && html`<span class="dim">· ${t('picks.loading')}</span>`}
          ${refresh.error && overview && overview.days.length > 0 && html`<span class="warning">${refreshErrorText(refresh.error)}</span>`}
          ${freshness && freshness.warning && html`<span class="warning">${freshness.warning}</span>`}
        </div>
        <${ViewMenu} showHandicaps=${showHandicaps} history=${showPast} onHistory=${setShowPast} tips=${tips} onTips=${chooseTips} open=${viewOpen} onToggle=${() => setViewOpen((o) => !o)} onClose=${() => setViewOpen(false)}
          onDisplay=${(change) => setDisplay((current) => ({ ...current, ...change }))} />
        <button class="tool small" onClick=${() => setSheet('legend')} title=${t('legend') + ' (?)'}><${Icon} name="info" size=${16} /><span class="legend-text">${t('legend')}</span></button>
      </footer>
      ${sheet === 'legend' && html`<${Legend} onClose=${() => setSheet(null)} />`}
      ${sheet === 'update' && update && html`<${UpdateSheet} update=${update} onClose=${() => setSheet(null)} />`}
      ${sheet === 'preferences' && html`<${PreferencesSheet} clubId=${club && club.id} onClose=${() => { setSheet(prefsBack); setPrefsBack(null); }} onSaved=${() => view && loadOverview(view, course)} />`}
      ${sheet === 'settings' && html`<${SettingsSheet} clubId=${club && club.id} serve=${!!boot.serve} onClose=${() => setSheet(null)}
        display=${{ boot, units, onDisplay: (change) => setDisplay((current) => ({ ...current, ...change })), onLanguage: () => location.reload(), onUpdate: checked }}
        onSaved=${() => { loadBoot(); if (view) loadOverview(view, course); }}
        onAddClub=${() => setSheet('addclub')} onClubsChanged=${clubsChanged} />`}
      ${sheet === 'addclub' && html`<${AddClubSheet} onClose=${() => setSheet(null)} onAdded=${clubsChanged} onOpen=${openPreview} />`}
      ${sheet === 'search' && clubForSheets && overview && html`<${SearchSheet} club=${clubForSheets} startDay=${searchDay} course=${tabCourse} pageCourse=${overview.course} onCourse=${setTabCourse} units=${units} showHandicaps=${showHandicaps}
        onPreferences=${() => { setPrefsBack('search'); setSheet('preferences'); }}
        refreshKey=${searchTick} onClose=${() => setSheet(null)} onMark=${markFromSearch} tabs=${searchTabs('search')} />`}
      ${sheet === 'heatmap' && clubForSheets && overview && html`<${HeatmapSheet} club=${clubForSheets} course=${tabCourse} pageCourse=${overview.course} onCourse=${setTabCourse} units=${units} onClose=${() => setSheet(null)} tabs=${searchTabs('heatmap')} />`}
      ${sheet === 'players' && clubForSheets && html`<${PlayersSheet} club=${clubForSheets} showHandicaps=${showHandicaps} onJump=${(hit) => { setSheet(null); jumpTo(hit.date, hit.time, hit.course, hit.here === false ? hit.slug : null); }} onClose=${() => setSheet(null)} onChanged=${() => view && loadOverview(view, course)} />`}
      ${sheet === 'tournaments' && club && club.slug && html`<${TournamentsSheet} club=${club} units=${units} focusDate=${tournamentDate} knownDays=${overview ? overview.days.map((day) => day.date) : []} onShowDay=${(date) => { setSheet(null); jumpTo(date); }} onClose=${() => setSheet(null)} />`}
      ${sheet === 'reservations' && html`<${ReservationsSheet} refreshKey=${searchTick} onClose=${() => setSheet(null)}
        onCancel=${(item) => setBooking({ mode: 'cancel', date: item.date, time: item.time, course: item.course, ref: { slug: item.slug, club_id: item.slug ? null : item.club_id }, dateText: dayLabel(item.date) })} />`}
      ${booking && html`<${BookingDialog} booking=${booking} onClose=${() => setBooking(null)} onDone=${bookingDone} />`}
    </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
