// The login page of `teetime-monitor-web --serve`: one password for the whole server. Plain script, no
// framework; it only needs to post the password and go to the Overview.

const TEXT = {
  en: {
    intro: 'Enter the password for this server.', label: 'Password', submit: 'Log in',
    wrong: 'That password is not right.', wait: 'Too many attempts. Try again in {n} s.', network: 'Could not reach the server.',
  },
  de: {
    intro: 'Passwort für diesen Server eingeben.', label: 'Passwort', submit: 'Anmelden',
    wrong: 'Das Passwort stimmt nicht.', wait: 'Zu viele Versuche. Bitte in {n} s erneut versuchen.', network: 'Server nicht erreichbar.',
  },
};
const lang = (navigator.language || 'en').toLowerCase().startsWith('de') ? 'de' : 'en';
const words = TEXT[lang];
document.documentElement.lang = lang;
const $ = (id) => document.getElementById(id);
$('intro').textContent = words.intro;
$('label').textContent = words.label;
$('submit').textContent = words.submit;

function show(message) {
  $('error').hidden = !message;
  $('error').textContent = message || '';
}

$('form').addEventListener('submit', async (event) => {
  event.preventDefault();
  show('');
  $('submit').disabled = true;
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: $('password').value }),
    });
    if (response.ok) {
      location.assign('/');
      return;
    }
    const body = await response.json().catch(() => ({}));
    show(response.status === 429 ? words.wait.replace('{n}', body.retry_after || 30) : words.wrong);
    $('password').select();
  } catch (error) {
    show(words.network);
  }
  $('submit').disabled = false;
});
