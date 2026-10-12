// Tooltips on touch screens. A title="..." only shows when a mouse hovers, and there is no hover on a phone or tablet:
// touch and hold anything with a title (an icon, a number, a column heading) and its text appears as a small bubble.
// (What matters most is also written out on the page itself, and the Legend explains the rest.)

const HOLD_MS = 450;
const SHOW_MS = 3800;

export function installTouchTips() {
  let timer = null;
  let bubble = null;
  let hideTimer = null;
  let suppressUntil = 0;
  let start = null;

  const hide = () => {
    clearTimeout(hideTimer);
    if (bubble) bubble.remove();
    bubble = null;
  };
  const show = (element, text) => {
    hide();
    bubble = document.createElement('div');
    bubble.className = 'touch-tip';
    bubble.setAttribute('role', 'tooltip');
    bubble.textContent = text;
    document.body.appendChild(bubble);
    const box = element.getBoundingClientRect();
    const tip = bubble.getBoundingClientRect();
    const above = box.top - tip.height - 8;
    const left = Math.min(Math.max(8, box.left + box.width / 2 - tip.width / 2), window.innerWidth - tip.width - 8);
    bubble.style.left = left + 'px';
    bubble.style.top = (above >= 8 ? above : box.bottom + 8) + 'px';
    hideTimer = setTimeout(hide, SHOW_MS);
  };
  const cancel = () => {
    clearTimeout(timer);
    timer = null;
  };

  document.addEventListener('pointerdown', (event) => {
    if (event.pointerType !== 'touch') return;
    hide();
    const element = event.target.closest && event.target.closest('[title]');
    const text = element && element.getAttribute('title');
    if (!text) return;
    start = { x: event.clientX, y: event.clientY };
    timer = setTimeout(() => {
      show(element, text);
      suppressUntil = Date.now() + 800; // the release that follows must not also be a tap on what was held
    }, HOLD_MS);
  }, true);
  document.addEventListener('pointermove', (event) => {
    if (timer && start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 10) cancel();
  }, true);
  for (const name of ['pointerup', 'pointercancel']) document.addEventListener(name, cancel, true);
  document.addEventListener('scroll', () => { cancel(); hide(); }, true);
  const swallow = (event) => {
    if (Date.now() < suppressUntil) {
      event.stopPropagation();
      event.preventDefault();
    }
  };
  document.addEventListener('click', swallow, true);
  document.addEventListener('contextmenu', swallow, true);
}
