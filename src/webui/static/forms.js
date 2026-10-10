// Preferences and Settings: forms generated from the server's field list (settings_api.py), plus the
// Settings sheet's own sections (clubs, login, AI key).

import {
  html, t, useState, Sheet, Select, Switch, TimeSelect, Status, useLoad, api, post, query, Icon, SCALES, DEFAULT_SCALE, getScale, setScale,
  themeNames, themeLabel, applyTheme, systemTheme,
} from '/lib.js';

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

/** The groups of fields; `values`/`setValue` are the form state ({field id: value}). `extras` maps
 *  a group key to rows of this page's own (not saved with the rest) to append to that group. */
export function FieldGroups({ groups, values, setValue, extras = {} }) {
  return groups.map((group) => html`
    <section class="group">
      <h3>${group.label}</h3>
      ${group.fields.map((field) => html`
        <div class="field-row">
          <label for=${'f-' + field.id}>${field.label}</label>
          <${FieldControl} field=${field} value=${values[field.id]} onChange=${(value) => setValue(field.id, value)} />
        </div>`)}
      ${extras[group.key]}
    </section>`);
}

/** The colour theme: the same eleven as the terminal and Mac apps, saved in the same setting. */
function ThemeRow({ initial }) {
  const [name, setName] = useState(initial || systemTheme());
  return html`
    <div class="field-row"><label for="f-theme">${t('settings.field.theme')}</label>
      <${Select} id="f-theme" value=${name} options=${themeNames().map((value) => ({ value, label: themeLabel(value) }))}
        onChange=${(value) => { setName(value); applyTheme(value); post('/api/theme', { name: value }).catch(() => {}); }} /></div>`;
}

/** How large the page is: this browser only, applied at once, not saved with the settings. */
function ScaleRow() {
  const [percent, setPercent] = useState(getScale());
  return html`
    <div class="field-row"><label for="f-scale">${t('settings.scale')}</label>
      <${Select} id="f-scale" value=${String(percent)}
        options=${SCALES.map((value) => ({ value: String(value), label: value + ' %' + (value === DEFAULT_SCALE ? ' · ' + t('settings.scale.default') : '') }))}
        onChange=${(value) => { setPercent(Number(value)); setScale(Number(value)); }} /></div>`;
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

export function PreferencesSheet({ clubId, onClose, onSaved }) {
  const { data, error } = useLoad(() => api('/api/preferences' + query({ club_id: clubId })), [clubId]);
  return html`<${Sheet} title=${t('preferences.title')} onClose=${onClose} size="wide">
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<p class="dim">${t('loading')}</p>`}
    ${data && html`<${PreferencesForm} groups=${data.groups} onClose=${onClose} onSaved=${onSaved} />`}
  <//>`;
}

function PreferencesForm({ groups, onClose, onSaved }) {
  const [values, setValue] = useForm(groups);
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
    <p class="intro">${t('preferences.intro')}</p>
    <div class="columns"><${FieldGroups} groups=${groups} values=${values} setValue=${setValue} /></div>
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
              : html`<button class="btn" onClick=${() => setConfirmRemove(club.id)}><${Icon} name="trash" size=${16} />${t('club.remove')}</button>`}
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

export function SettingsSheet({ clubId, onClose, onSaved, onAddClub, onClubsChanged }) {
  const { data, error, reload } = useLoad(() => api('/api/settings' + query({ club_id: clubId })), [clubId]);
  return html`<${Sheet} title=${t('settings.title')} onClose=${onClose} size="wide">
    ${error && html`<${Status} kind="error">${t('error.title')}<//>`}
    ${!data && !error && html`<p class="dim">${t('loading')}</p>`}
    ${data && html`<${SettingsBody} data=${data} clubId=${clubId} reload=${reload} onClose=${onClose} onSaved=${onSaved} onAddClub=${onAddClub} onClubsChanged=${onClubsChanged} />`}
  <//>`;
}

function SettingsBody({ data, clubId, reload, onClose, onSaved, onAddClub, onClubsChanged }) {
  const [values, setValue] = useForm(data.groups);
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const verifyClub = clubId || (data.clubs[0] && data.clubs[0].id) || null;
  const aiGroup = data.groups.find((group) => group.key === 'settings.group.ai');
  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await post('/api/settings', { values });
      setMessage({ kind: 'ok', text: t('settings.saved') });
      onSaved(values['field-__language__']);
    } catch (error) {
      setMessage({ kind: 'error', text: (error.payload && error.payload.error) || t('error.title') });
    }
    setSaving(false);
  }
  const otherGroups = data.groups.filter((group) => group !== aiGroup);
  return html`
    <div class="columns">
      <${ClubsSection} clubs=${data.clubs} onChanged=${(listChanged) => { reload(); if (listChanged) onClubsChanged(); }} onAddClub=${onAddClub} />
      <${AccountSection} account=${data.account} verifyClubId=${verifyClub} onChanged=${reload} />
      <${FieldGroups} groups=${otherGroups} values=${values} setValue=${setValue} extras=${{ 'settings.group.display': html`<${ThemeRow} initial=${data.theme} /><${ScaleRow} />` }} />
      ${aiGroup && html`
        <section class="group">
          <h3>${aiGroup.label}</h3>
          ${aiGroup.fields.map((field) => html`
            <div class="field-row"><label for=${'f-' + field.id}>${field.label}</label>
              <${FieldControl} field=${field} value=${values[field.id]} onChange=${(value) => setValue(field.id, value)} /></div>`)}
          <${AiSection} ai=${data.ai} onChanged=${reload} />
        </section>`}
    </div>
    <div class="actions">
      <${Status} kind=${message && message.kind}>${message && message.text}<//>
      <span class="grow"></span>
      <button class="btn" onClick=${onClose}>${t('close')}</button>
      <button class="btn pri" onClick=${save} disabled=${saving}>${t('save')}</button>
    </div>`;
}
