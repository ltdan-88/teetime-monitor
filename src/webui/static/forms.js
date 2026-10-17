// Preferences and Settings: forms generated from the server's field list (settings_api.py), plus the
// Settings sheet's own sections (clubs, login, AI key).

import { html, t, useState, Sheet, Select, Switch, TimeSelect, Status, useLoad, api, post, query, Icon } from '/lib.js';
import { DisplaySection, AboutSection } from '/viewmenu.js';

// ---------------------------------------------------------------- generated form

function FieldControl({ field, value, onChange }) {
  const id = 'f-' + field.id;
  if (field.kind === 'display') return html`<span class="static-value">${field.value}</span>`;
  if (field.kind === 'bool') return html`<${Switch} id=${id} checked=${value} onChange=${onChange} />`;
  if (field.kind === 'optional_time') return html`<${TimeSelect} id=${id} value=${value} label=${field.label} onChange=${onChange} />`;
  if (field.choices) return html`<${Select} id=${id} value=${value} options=${field.choices} onChange=${onChange} />`;
  return html`<input id=${id} class="fld" value=${value} inputmode=${field.kind === 'int' ? 'numeric' : 'decimal'}
    placeholder=${field.kind === 'optional_float' ? t('off') : ''} onInput=${(event) => onChange(event.target.value)} />`;
}

/** Cards in two balanced columns, in their order: each goes to the shorter column (by `weight`, roughly its rows), so
 *  they read top to bottom, left before right, and a short card never leaves a hole beside a tall one. On a narrow
 *  screen the columns stack, still in that order. */
function Columns({ items }) {
  const side = new Map();
  let a = 0;
  let b = 0;
  for (const item of items) {
    if (a <= b) {
      side.set(item, 0);
      a += item.weight;
    } else {
      side.set(item, 1);
      b += item.weight;
    }
  }
  const column = (n) => items.filter((item) => side.get(item) === n).map((item) => html`<div class="col-item" style=${{ order: items.indexOf(item) }}>${item.node}</div>`);
  return html`<div class="columns"><div class="col">${column(0)}</div><div class="col">${column(1)}</div></div>`;
}

/** A group's rows: the times first (each from–to pair on one row, "Weekdays 14:00 – 17:00"), then the rest; a limit
 *  that belongs to a switch (rain from 50 %) only while that switch is on. */
function fieldRows(group, values, setValue) {
  const times = group.fields.filter((field) => field.kind === 'optional_time');
  const rows = [];
  for (const field of times) {
    if (!field.id.endsWith('-after')) continue;
    const until = times.find((other) => other.id === field.id.replace(/-after$/, '-before'));
    rows.push(html`
      <div class="field-row">
        <label for=${'f-' + field.id}>${field.label.split(' — ')[0]}</label>
        <span class="time-range"><${FieldControl} field=${field} value=${values[field.id]} onChange=${(value) => setValue(field.id, value)} />
          ${until && html`<span class="dim">–</span><${FieldControl} field=${until} value=${values[until.id]} onChange=${(value) => setValue(until.id, value)} />`}</span>
      </div>`);
  }
  for (const field of group.fields) {
    if (field.kind === 'optional_time' || (field.depends && !values[field.depends])) continue;
    rows.push(html`
      <div class=${'field-row' + (field.depends ? ' sub' : '')}>
        <label for=${'f-' + field.id}>${field.label}</label>
        <${FieldControl} field=${field} value=${values[field.id]} onChange=${(value) => setValue(field.id, value)} />
      </div>`);
  }
  return rows;
}

/** The groups of fields as cards with a weight; `values`/`setValue` are the form state ({field id: value}). */
function groupItems(groups, values, setValue) {
  return groups.map((group) => ({ weight: group.fields.length + 1, node: html`
    <section class="group">
      <h3>${group.label}</h3>
      ${fieldRows(group, values, setValue)}
    </section>` }));
}

function initialValues(groups) {
  const values = {};
  for (const group of groups) for (const field of group.fields) if (field.kind !== 'display') values[field.id] = field.value;
  return values;
}

function useForm(groups) {
  const [values, setValues] = useState(() => initialValues(groups));
  const setValue = (id, value) => setValues((current) => ({ ...current, [id]: value }));
  return [values, setValue];
}

// ---------------------------------------------------------------- Preferences

/** The club's courses, each one you cannot play (a 9 hole membership), can play, or want Search to start with (the 9 hole
 *  course when the 6 hole one is only for a quick round). A choice saves at once. One course: nothing to choose, no card. */
function useCoursesCard({ clubId, onSaved }) {
  const { data } = useLoad(() => (clubId ? api('/api/club/courses' + query({ club_id: clubId })) : Promise.resolve(null)), [clubId]);
  const [local, setLocal] = useState({});
  if (!data || data.error || data.courses.length < 2) return null;
  const choose = async (course, state) => {
    setLocal((current) => ({ ...current, [course.name]: state }));
    try {
      await post('/api/club/course-state', { slug: data.slug, course: course.name, state });
      onSaved();
    } catch (failure) {
      setLocal((current) => ({ ...current, [course.name]: course.state }));
    }
  };
  const options = ['default', 'on', 'off'].map((state) => ({ value: state, label: t('preferences.course.' + state) }));
  return {
    weight: data.courses.length + 1,
    node: html`<section class="group">
      <h3>${t('preferences.courses')}</h3>
      ${data.courses.map((course, index) => html`
        <div class="field-row">
          <label for=${'c-play-' + index}>${course.name}</label>
          <${Select} id=${'c-play-' + index} value=${course.name in local ? local[course.name] : course.state} options=${options} onChange=${(state) => choose(course, state)} />
        </div>`)}
    </section>`,
  };
}

export function PreferencesSheet({ clubId, onClose, onSaved }) {
  const { data, error } = useLoad(() => api('/api/preferences' + query({ club_id: clubId })), [clubId]);
  return html`<${Sheet} title=${t('preferences.title')} onClose=${onClose} size="wide">
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<p class="dim">${t('loading')}</p>`}
    ${data && html`<${PreferencesForm} groups=${data.groups} clubId=${clubId} onClose=${onClose} onSaved=${onSaved} />`}
  <//>`;
}

function PreferencesForm({ groups, clubId, onClose, onSaved }) {
  const [values, setValue] = useForm(groups);
  const courses = useCoursesCard({ clubId, onSaved });
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await post('/api/preferences', { values });
      setMessage({ kind: 'ok', text: t('settings.saved') });
      onSaved();
    } catch (error) {
      setMessage({ kind: 'error', text: (error.payload && error.payload.error) || t('error.title') });
    }
    setSaving(false);
  }
  return html`
    <${Columns} items=${[...(courses ? [courses] : []), ...groupItems(groups, values, setValue)]} />
    <div class="actions">
      <${Status} kind=${message && message.kind}>${message && message.text}<//>
      <span class="grow"></span>
      <button class="btn" onClick=${onClose}>${t('close')}</button>
      <button class="btn pri" onClick=${save} disabled=${saving}>${t('save')}</button>
    </div>`;
}

// ---------------------------------------------------------------- Settings

function ClubsSection({ clubs, onChanged, onAddClub }) {
  const [confirmRemove, setConfirmRemove] = useState(null);
  async function setDefault(club, course) {
    await post('/api/club/default-course', { slug: club.slug, course });
    onChanged();
  }
  async function setHoles(club, course, value) {
    await post('/api/club/holes', { slug: club.slug, course, holes: value === '' ? null : Number(value) });
    onChanged();
  }
  async function remove(club) {
    await post('/api/club/remove', { club_id: club.id });
    setConfirmRemove(null);
    onChanged(true);
  }
  return html`
    <section class="group wide-group">
      <h3>${t('settings.clubs')}</h3>
      ${clubs.length === 0 && html`<p class="dim">${t('empty.no_clubs.title')}</p>`}
      ${clubs.map((club) => html`
        <div class="club-row">
          <div class="club-head">
            <strong>${club.name}</strong><span class="dim num">${club.id}</span>
            <span class="grow"></span>
            ${club.courses.length > 0 && html`
              <${Select} id=${'dc-' + club.id} aria-label=${t('club.default_course')} title=${t('club.default_course')}
                value=${club.default_course || club.courses[0]}
                options=${club.courses.map((course) => ({ value: course, label: course }))} onChange=${(course) => setDefault(club, course)} />`}
            ${confirmRemove === club.id
              ? html`<span class="inline-confirm">${t('club.remove_confirm', { name: club.name })}
                  <button class="btn danger" onClick=${() => remove(club)}>${t('club.remove')}</button>
                  <button class="btn" onClick=${() => setConfirmRemove(null)}>${t('cancel')}</button></span>`
              : html`<button class="icon-btn danger" onClick=${() => setConfirmRemove(club.id)} aria-label=${t('club.remove')} title=${t('club.remove')}><${Icon} name="trash" size=${18} /></button>`}
          </div>
          ${club.course_holes.length > 0 && html`<p class="hint">${t('settings.course_holes.hint')}</p>`}
          ${club.course_holes.map((row) => html`
            <div class="field-row">
              <label for=${'ch-' + club.id + row.course}>${row.course}</label>
              <${Select} id=${'ch-' + club.id + row.course} value=${row.holes == null ? '' : String(row.holes)}
                options=${[{ value: '', label: t('settings.course_holes.auto') }, { value: '9', label: t('settings.course_holes.option', { n: 9 }) }, { value: '18', label: t('settings.course_holes.option', { n: 18 }) }]}
                onChange=${(value) => setHoles(club, row.course, value)} />
            </div>`)}
        </div>`)}
      <div class="actions"><button class="btn" onClick=${onAddClub}><${Icon} name="plus" size=${16} />${t('addclub.title')}</button></div>
    </section>`;
}

/** Settings > Server password (only on a `--serve` server): the current one, the new one twice. This browser
 *  stays logged in; every other one has to log in again. */
function ServerPasswordSection() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  async function save(event) {
    event.preventDefault();
    if (next.length < 8) return setMessage({ kind: 'error', text: t('password.short', { n: 8 }) });
    if (next !== again) return setMessage({ kind: 'error', text: t('password.mismatch') });
    setBusy(true);
    setMessage(null);
    try {
      await post('/api/auth/password', { current, new: next });
      setCurrent('');
      setNext('');
      setAgain('');
      setMessage({ kind: 'ok', text: t('password.changed') });
    } catch (error) {
      const code = error.payload && error.payload.error;
      const wait = error.payload && error.payload.retry_after;
      setMessage({ kind: 'error', text: code === 'bad_password' ? t('password.wrong') : code === 'too_many' ? t('login.wait', { n: wait || 30 }) : t('error.title') });
    }
    setBusy(false);
  }
  return html`
    <section class="group">
      <h3>${t('password.title')}</h3>
      <form onSubmit=${save} autocomplete="off">
        <div class="field-row"><label for="pw-current">${t('password.current')}</label>
          <input id="pw-current" class="fld" type="password" value=${current} onInput=${(event) => setCurrent(event.target.value)} autocomplete="current-password" /></div>
        <div class="field-row"><label for="pw-new">${t('password.new')}</label>
          <input id="pw-new" class="fld" type="password" value=${next} onInput=${(event) => setNext(event.target.value)} autocomplete="new-password" /></div>
        <div class="field-row"><label for="pw-again">${t('password.again')}</label>
          <input id="pw-again" class="fld" type="password" value=${again} onInput=${(event) => setAgain(event.target.value)} autocomplete="new-password" /></div>
        <p class="hint">${t('password.note')}</p>
        <div class="actions"><${Status} kind=${message && message.kind}>${message && message.text}<//><span class="grow"></span>
          <button class="btn" type="submit" disabled=${busy || !current || !next}>${t('password.change')}</button></div>
      </form>
    </section>`;
}

function AccountSection({ account, verifyClubId, onChanged }) {
  const [username, setUsername] = useState(account.username);
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const result = await post('/api/login', { username, password, club_id: verifyClubId });
      setPassword('');
      if (!result.saved) setMessage({ kind: 'error', text: t('login.' + result.reason) });
      else if (result.verified === true) setMessage({ kind: 'ok', text: t('login.verified') });
      else if (result.verified === false) setMessage({ kind: 'error', text: t('login.rejected') });
      else if (result.reason === 'network_error') setMessage({ kind: 'warn', text: t('login.network_error') });
      else setMessage({ kind: 'ok', text: t('login.saved_unchecked') });
      onChanged();
    } catch (error) {
      setMessage({ kind: 'error', text: t('error.title') });
    }
    setBusy(false);
  }
  return html`
    <section class="group">
      <h3>${t('settings.group.account')}</h3>
      <form onSubmit=${save} autocomplete="off">
        <div class="field-row"><label for="login-user">${t('login.username')}</label>
          <input id="login-user" class="fld" value=${username} onInput=${(event) => setUsername(event.target.value)} autocomplete="username" /></div>
        <div class="field-row"><label for="login-pass">${t('login.password')}</label>
          <input id="login-pass" class="fld" type="password" value=${password} placeholder=${account.has_password ? t('login.keep') : ''}
            onInput=${(event) => setPassword(event.target.value)} autocomplete="current-password" /></div>
        <p class="hint">${t('login.hint')}</p>
        <div class="actions"><${Status} kind=${message && message.kind}>${message && message.text}<//><span class="grow"></span>
          <button class="btn pri" type="submit" disabled=${busy || !username}>${t(busy ? 'login.checking' : 'login.save')}</button></div>
      </form>
    </section>`;
}

function AiSection({ ai, onChanged }) {
  const [provider, setProvider] = useState(ai.provider);
  const [key, setKey] = useState('');
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const current = ai.providers.find((entry) => entry.id === provider);
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const result = await post('/api/ai-key', { provider, api_key: key });
      setKey('');
      if (!result.saved) setMessage({ kind: 'error', text: t('ai.' + result.reason) });
      else if (result.verified) setMessage({ kind: 'ok', text: t('ai.verified') });
      else setMessage({ kind: 'error', text: t(result.reason === 'invalid_key' ? 'ai.invalid_key' : 'ai.network_error') });
      onChanged();
    } catch (error) {
      setMessage({ kind: 'error', text: t('error.title') });
    }
    setBusy(false);
  }
  return html`
    <form onSubmit=${save} autocomplete="off">
      <div class="field-row"><label for="ai-provider">${t('settings.field.ai_credentials')}</label>
        <${Select} id="ai-provider" value=${provider}
          options=${ai.providers.map((entry) => ({ value: entry.id, label: entry.label + (entry.has_key ? ' ✓' : '') }))} onChange=${setProvider} /></div>
      <div class="field-row"><label for="ai-key">${t('ai.key')}</label>
        <input id="ai-key" class="fld" type="password" value=${key} placeholder=${current && current.has_key ? t('login.keep') : ''}
          onInput=${(event) => setKey(event.target.value)} autocomplete="off" /></div>
      <div class="actions"><${Status} kind=${message && message.kind}>${message && message.text}<//><span class="grow"></span>
        <button class="btn" type="submit" disabled=${busy || (!key && !(current && current.has_key))}>${t(busy ? 'login.checking' : 'ai.save')}</button></div>
    </form>`;
}

export function SettingsSheet({ clubId, serve, display, onClose, onSaved, onAddClub, onClubsChanged }) {
  const { data, error, reload } = useLoad(() => api('/api/settings' + query({ club_id: clubId })), [clubId]);
  return html`<${Sheet} title=${t('settings.title')} onClose=${onClose} size="wide">
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<p class="dim">${t('loading')}</p>`}
    ${data && html`<${SettingsBody} data=${data} clubId=${clubId} serve=${serve} display=${display} reload=${reload} onClose=${onClose} onSaved=${onSaved} onAddClub=${onAddClub} onClubsChanged=${onClubsChanged} />`}
  <//>`;
}

// The server's Display group (language, units, handicaps) is drawn by DisplaySection instead: those apply at once.
const VIEW_GROUP = 'settings.group.display';

function SettingsBody({ data, clubId, serve, display, reload, onClose, onSaved, onAddClub, onClubsChanged }) {
  const visible = data.groups.filter((group) => group.key !== VIEW_GROUP);
  const [values, setValue] = useForm(visible);
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const verifyClub = clubId || (data.clubs[0] && data.clubs[0].id) || null;
  const aiGroup = visible.find((group) => group.key === 'settings.group.ai');
  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await post('/api/settings', { values });
      setMessage({ kind: 'ok', text: t('settings.saved') });
      onSaved();
    } catch (error) {
      setMessage({ kind: 'error', text: (error.payload && error.payload.error) || t('error.title') });
    }
    setSaving(false);
  }
  const otherGroups = visible.filter((group) => group !== aiGroup);
  return html`
    <div class="stack">
      <${ClubsSection} clubs=${data.clubs} onChanged=${(listChanged) => { reload(); if (listChanged) onClubsChanged(); }} onAddClub=${onAddClub} />
      <${Columns} items=${[
        { weight: 7, node: html`<${AccountSection} account=${data.account} verifyClubId=${verifyClub} onChanged=${reload} />` },
        ...(serve ? [{ weight: 8, node: html`<${ServerPasswordSection} />` }] : []),
        ...(display ? [{ weight: 6, node: html`<${DisplaySection} ...${display} />` }] : []),
        ...groupItems(otherGroups, values, setValue),
        ...(aiGroup ? [{ weight: aiGroup.fields.length + 6, node: html`
          <section class="group">
            <h3>${aiGroup.label}</h3>
            ${fieldRows(aiGroup, values, setValue)}
            <${AiSection} ai=${data.ai} onChanged=${reload} />
          </section>` }] : []),
        ...(display ? [{ weight: 3, node: html`<${AboutSection} boot=${display.boot} onUpdate=${display.onUpdate} />` }] : []),
      ]} />
    </div>
    <div class="actions">
      <${Status} kind=${message && message.kind}>${message && message.text}<//>
      <span class="grow"></span>
      <button class="btn" onClick=${onClose}>${t('close')}</button>
      <button class="btn pri" onClick=${save} disabled=${saving}>${t('save')}</button>
    </div>`;
}
