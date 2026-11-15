/* NOVA shell: the new JARVIS interface. It sits on top of the existing tools and API,
   so every earlier feature keeps working while the layout, chat and motion are new. */
(() => {
'use strict';
const body = document.body, root = document.documentElement;
const P = {
  side: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  chat: '<path d="M20.5 11.5a8 8 0 0 1-11.7 7.1L4 20l1.3-4.4A8 8 0 1 1 20.5 11.5z"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', stop: '<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  retry: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>', edit: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m13.5 6.5 4 4"/>',
  thumb: '<path d="M7 11v9H4v-9h3z"/><path d="M7 11l4-8a2 2 0 0 1 3 2l-1 4h5a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 17 20H7"/>',
  speak: '<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/>', down: '<path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/>',
  more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>', file: '<path d="M6 3h8l4 4v14H6V3z"/><path d="M14 3v4h4"/>',
  term: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3M13 15h4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>', star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9L12 3z"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>', box: '<rect x="3" y="4" width="18" height="5" rx="1.5"/><path d="M5 9v10h14V9M10 13h4"/>',
  sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>',
  chev: '<path d="m6 9 6 6 6-6"/>', check: '<path d="m5 12 5 5 9-10"/>', spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"/>',
  clip: '<path d="M20 11.5 12 19.5a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L9.7 17.2a1.7 1.7 0 0 1-2.4-2.4L15 7"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>', code: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5"/>',
  cam: '<rect x="3" y="6" width="18" height="14" rx="3"/><circle cx="12" cy="13" r="3.5"/><path d="M8 6l1.5-2h5L16 6"/>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>', moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  keys: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  minus: '<path d="M5 12h14"/>', circle: '<circle cx="12" cy="12" r="8"/>', square: '<rect x="5" y="5" width="14" height="14" rx="2"/>', type: '<path d="M5 6h14M12 6v13M9 19h6"/>',
  note: '<path d="M5 4h14v10l-5 6H5z"/><path d="M14 20v-6h5"/>', slash: '<path d="M5 19 19 5"/>', arrow: '<path d="M5 19 19 5M10 5h9v9"/>', eraser: '<path d="m8 20-4-4L14 6l6 6-8 8H8z"/><path d="m10 10 6 6"/>', filter: '<path d="M4 5h16l-6.5 7.5V18l-3 1.5v-7L4 5z"/>', rows: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  doc: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/>', slides: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M12 16v4M8 20h8"/>',
  grid: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M9 4v16M15 4v16"/>', chart: '<path d="M4 20V4M4 20h16"/><path d="M8 20v-6M12 20V8M16 20v-9"/>',
  board: '<rect x="3" y="4" width="11" height="9" rx="1.5"/><circle cx="15.5" cy="15.5" r="4.5"/>', palette: '<path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.8 1.8-1.7 0-1.1-.9-1.4-.9-2.4 0-.9.7-1.6 1.6-1.6H17a4 4 0 0 0 4-4c0-4.6-4-8.3-9-8.3z"/><path d="M7.5 12h.01M9.5 7.8h.01M14.5 7.5h.01"/>',
  scales: '<path d="M12 4v16M8 20h8M5 7h14"/><path d="M5 7 2.5 13.5a2.6 2.6 0 0 0 5 0L5 7zM19 7l-2.5 6.5a2.6 2.6 0 0 0 5 0L19 7z"/>',
  shield: '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.3 7.5 9.5 4.3-1.2 7.5-4.9 7.5-9.5V6L12 3z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
  work: '<path d="M4 6h10M4 12h10M4 18h6"/><path d="m15 17 2 2 4-4"/>', cursor: '<path d="M5 3l14 8-6 2-2 6L5 3z"/>', up: '<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>'
};
const icon = window.NovaIcon = name => '<svg class="i" viewBox="0 0 24 24" aria-hidden="true">' + (P[name] || '') + '</svg>';
const el = (tag, props = {}, html) => { const node = document.createElement(tag); for (const [k, v] of Object.entries(props)) { if (k === 'class') node.className = v; else if (k === 'data') Object.assign(node.dataset, v); else if (k in node && k !== 'list') node[k] = v; else node.setAttribute(k, v); } if (html !== undefined) node.innerHTML = html; return node; };
// What the window remembers (theme, panel width...) is kept by the app itself, so it is the same in every JARVIS window
// and does not depend on which browser profile the window opens in. The browser's own store is only a second copy.
const KEPT = (typeof PREFS === 'object' && PREFS) || {};
const store = {
  get(k, d) { if (k in KEPT) return KEPT[k]; try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) {
    KEPT[k] = String(v); try { localStorage.setItem(k, v); } catch {}
    try { fetch('/api/window', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN }, body: JSON.stringify({ pref: k, value: String(v) }) }).catch(() => {}); } catch {}
  },
};
// A link in a reply opens in your own browser (where you are signed in to things), not inside JARVIS's window.
document.addEventListener('click', event => {
  const link = event.target.closest?.('a[href]');
  if (!link || !/^https?:/i.test(link.href) || link.origin === location.origin) return;
  event.preventDefault();
  fetch('/api/window', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN }, body: JSON.stringify({ open: link.href }) }).catch(() => window.open(link.href, '_blank', 'noopener'));
}, true);
const legacyButton = (scope, text) => [...(scope || document).querySelectorAll('button')].find(b => b.textContent.trim().replace(/^[^\w]+\s*/, '') === text || b.textContent.trim() === text);

// Styles injected by earlier layers are switched off so one design applies everywhere.
document.querySelectorAll('link[href="/operations.css"], head style').forEach(node => node.remove());

/* ---------- theme ---------- */
const dark = matchMedia('(prefers-color-scheme: dark)');
function applyTheme() {
  const choice = store.get('nv-theme', 'system'), light = choice === 'light' || (choice === 'system' && !dark.matches);
  if (light) root.dataset.theme = 'light'; else delete root.dataset.theme;
  window.NovaCore?.set({ light });
}
dark.addEventListener('change', applyTheme);

/* ---------- the 3D core ---------- */
const stage = el('div', { id: 'nv-stage', 'aria-hidden': 'true' }, '<canvas></canvas>');
body.prepend(stage);
if (!window.NovaCore?.mount(stage.firstChild)) stage.classList.add('nv-nogl');
// The orb is sized to the window. In voice chat it takes the room that is left above the captions, the buttons and the
// message box, so those are never pushed off the bottom of a small window.
function sizeStage() {
  const W = innerWidth, H = innerHeight, typing = body.classList.contains('home-expanded');
  const size = Math.round(Math.max(200, Math.min(H * 0.46, W * 0.52, 520)));
  root.style.setProperty('--stage', size + 'px'); root.style.setProperty('--k', (30 / size).toFixed(4));
  const box = document.querySelector('.composer-wrap');
  const under = (H <= 440 ? 150 : 204) + 12 + Math.max(68, box ? box.offsetHeight : 68);   // captions and buttons, then the message box
  const wide = Math.round(Math.max(84, Math.min(size * (typing ? 0.9 : 1.06), H - 44 - under, W * 0.8)));
  const centre = Math.round(Math.max(44 + wide / 2, Math.min(H * (typing ? 0.3 : 0.34), H - under - wide / 2)));
  root.style.setProperty('--vd', wide + 'px'); root.style.setProperty('--vy', centre + 'px'); root.style.setProperty('--vfit', (wide / size).toFixed(4));
  // What JARVIS is saying is shown in whole lines: as many as fit between the orb and the buttons (never half a line).
  const spare = H - (centre + wide / 2 + 14) - under + 61, line = (H <= 620 ? 17 : 20) * 1.45;
  root.style.setProperty('--me-lines', String(Math.max(1, Math.min(6, Math.floor(spare / line)))));
}
sizeStage(); addEventListener('resize', sizeStage);
if (window.ResizeObserver && document.querySelector('.composer-wrap')) new ResizeObserver(sizeStage).observe(document.querySelector('.composer-wrap'));
function coreMood() {
  const working = busy || body.classList.contains('nv-working');
  const typing = document.activeElement === $('message');
  window.NovaCore?.set({ energy: working ? 0.9 : typing ? 0.42 : 0.2 });
  stage.style.setProperty('--glow', working ? '1' : typing ? '.85' : '.6');
  window.NovaCore?.still(body.classList.contains('quiet') || body.classList.contains('orb-still'));
}
new MutationObserver(() => { coreMood(); sizeStage(); }).observe(body, { attributes: true, attributeFilter: ['class'] });

/* ---------- light mode for modest PCs ---------- */
function applyLight(serverSays) {
  const choice = store.get('nv-light', 'auto');
  const weak = window.NovaCore?.software || (navigator.deviceMemory && navigator.deviceMemory <= 4) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2);
  const on = choice === 'on' || (choice === 'auto' && (weak || serverSays === true));
  body.classList.toggle('nv-lite', !!on); window.NovaCore?.light?.(on);
}
applyLight();

/* ---------- small building blocks: tooltips, popovers, dialogs, notices ---------- */
const tip = el('div', { id: 'nv-tip', role: 'tooltip' }); body.append(tip);
const TIPS = {
  'Archive': 'Move this chat out of your recent list. It stays saved.', 'To workspace': 'Bring this chat back into your recent list.',
  'Updates': 'See what JARVIS finished while you were away.', 'System': 'See which AI accounts are ready and how much allowance is left.',
  'Control': 'Open the control centre: app health, saved chats and recovery.', 'Help': 'A short guide to using JARVIS.',
  'Settings': 'Change how JARVIS looks and works.', 'Context': 'See exactly what JARVIS will read before answering.',
  'Checklist': 'Turn your message into a checklist JARVIS must satisfy.', 'Dry run': 'Preview what JARVIS would do, without doing it.',
  'Compare rewrite': 'Compare your message with the improved version.', 'Improve message': 'Rewrite your message so the AI understands it better. Nothing is sent yet.',
  'Read replies aloud': 'Have JARVIS speak each new reply.', 'Open folder…': 'Use a folder already on this computer as a project.',
  'Run': 'Run this command.', 'New session': 'Start a fresh terminal.', 'Refresh': 'Check again for the latest information.',
  'Pause': 'Pause this work. Progress is kept.', 'Cancel': 'Stop this work. Finished parts are kept.', 'Continue': 'Carry on from where it paused.',
  'Review result': 'Look at what changed before it is applied.', 'Close': 'Close this window.'
};
let tipTimer = 0, tipFor = null;
function tipText(node) {
  if (node.title) { node.dataset.tip = node.title; node.removeAttribute('title'); }
  if (node.dataset.tip) return node.dataset.tip;
  if (node.tagName !== 'BUTTON' && node.tagName !== 'SUMMARY') return '';
  const text = node.textContent.trim().replace(/^[^\w]+\s*/, '');
  return TIPS[text] || (node.querySelector('svg') && node.getAttribute('aria-label')) || '';
}
function showTip(node) {
  const text = tipText(node); if (!text) return;
  tip.innerHTML = esc(text) + (node.dataset.key ? '<kbd>' + esc(node.dataset.key) + '</kbd>' : '');
  const r = node.getBoundingClientRect(); tip.classList.add('show');
  const w = tip.offsetWidth, h = tip.offsetHeight, above = r.top > h + 14;
  tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
  tip.style.top = (above ? r.top - h - 8 : r.bottom + 8) + 'px';
}
function hideTip() { clearTimeout(tipTimer); tipFor = null; tip.classList.remove('show'); }
document.addEventListener('pointerover', e => {
  const node = e.target.closest?.('[data-tip],[title],button,summary'); if (!node || node === tipFor) return;
  hideTip(); tipFor = node; tipTimer = setTimeout(() => showTip(node), 380);
}, { passive: true });
document.addEventListener('pointerout', e => { if (tipFor && !tipFor.contains(e.relatedTarget)) hideTip(); }, { passive: true });
document.addEventListener('pointerdown', hideTip, { passive: true, capture: true });
document.addEventListener('keydown', hideTip, { capture: true });

let pop = null, popAnchor = null;
function closePop(back) { if (!pop) return; const anchor = popAnchor; pop.remove(); anchor?.setAttribute('aria-expanded', 'false'); pop = popAnchor = null; if (back === true) anchor?.focus?.(); }
function openPop(anchor, fill, options = {}) {
  if (popAnchor === anchor) return closePop();
  closePop(); hideTip();
  pop = el('div', { class: 'nv-pop', role: 'menu' }); popAnchor = anchor; anchor.setAttribute('aria-expanded', 'true');
  fill(pop); body.append(pop);
  // The menu opens on the side asked for if it fits there, otherwise on the side with more room, and it is never taller
  // than that room: a long menu scrolls inside itself. So its last line can be reached on any screen, at any zoom, in a
  // small window, with the mouse, a finger or the keyboard.
  const r = anchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight, edge = 8;
  const above = r.top - 2 * edge, below = innerHeight - r.bottom - 2 * edge;
  let up = options.up ?? (below < h && above > below);
  if ((up ? above : below) < h && (up ? below : above) > (up ? above : below)) up = !up;
  const room = Math.max(96, Math.min(innerHeight - 2 * edge, up ? above : below)), tall = Math.min(h, room);
  pop.style.maxHeight = room + 'px';
  const left = Math.max(edge, Math.min(innerWidth - w - edge, options.right ? r.right - w : r.left));
  pop.style.left = left + 'px'; pop.style.top = Math.max(edge, Math.min(innerHeight - tall - edge, up ? r.top - tall - edge : r.bottom + edge)) + 'px';
  pop.style.setProperty('--ox', (r.left + r.width / 2 - left) + 'px'); pop.style.setProperty('--oy', up ? '100%' : '0%');
  pop.addEventListener('keydown', popKeys);
  const chosen = pop.querySelector('.nv-tick')?.closest('button');
  (chosen || pop.querySelector('button,select,input'))?.focus({ preventScroll: true });
  chosen?.scrollIntoView({ block: 'nearest' });       // the one in use is in sight when the menu opens
  return pop;
}
// Up and Down walk the lines of a menu (round and round), Home and End go to its ends, a letter goes to the next line
// that begins with it. The line that has the keyboard is brought into sight by the browser itself.
function popKeys(e) {
  if (!pop || e.ctrlKey || e.metaKey || e.altKey || e.target.matches?.('select,input,textarea')) return;
  const lines = [...pop.querySelectorAll('button:not([disabled])')].filter(b => b.offsetParent !== null);
  if (!lines.length) return;
  const at = lines.indexOf(document.activeElement);
  let next = -1;
  if (e.key === 'ArrowDown') next = (at + 1) % lines.length;
  else if (e.key === 'ArrowUp') next = (at <= 0 ? lines.length : at) - 1;
  else if (e.key === 'Home' || e.key === 'PageUp') next = 0;
  else if (e.key === 'End' || e.key === 'PageDown') next = lines.length - 1;
  else if (e.key.length === 1 && /\S/.test(e.key)) { const letter = e.key.toLowerCase(); for (let i = 1; i <= lines.length && next < 0; i++) { const one = (at + i + lines.length) % lines.length; if (lines[one].textContent.trim().toLowerCase().startsWith(letter)) next = one; } }
  if (next < 0) return;
  e.preventDefault(); lines[next].focus();
}
function item(parent, label, iconName, action, extra = {}) {
  const button = el('button', { class: 'nv-item' + (extra.danger ? ' danger' : '') + (extra.adv ? ' nv-adv' : ''), type: 'button', role: 'menuitem' },
    (iconName ? icon(iconName) : '') + '<span>' + esc(label) + (extra.note ? '<small>' + esc(extra.note) + '</small>' : '') + '</span>' + (extra.tick ? '<span class="nv-tick">' + icon('check') + '</span>' : ''));
  if (extra.tip) button.dataset.tip = extra.tip;
  button.onclick = async () => { if (!extra.keep) closePop(); try { await action(button); } catch (error) { toast(error.message); } };
  parent.append(button); return button;
}
document.addEventListener('pointerdown', e => { if (pop && !pop.contains(e.target) && !popAnchor?.contains(e.target)) closePop(); }, true);
addEventListener('resize', closePop);

function dialog(html, cls = '') {
  const d = el('dialog', { class: 'nv-dialog ' + cls }, html);
  d.addEventListener('close', () => d.remove()); body.append(d); d.showModal(); return d;
}
function confirmBox({ title, text, ok = 'OK', danger = false }) {
  return new Promise(resolve => {
    const d = dialog('<h2>' + esc(title) + '</h2><p>' + esc(text) + '</p><div class="actions"><button class="plain" value="no">Cancel</button><button class="primary" value="yes">' + esc(ok) + '</button></div>');
    if (danger) d.querySelector('.primary').style.cssText = 'background:var(--bad);color:#fff';
    d.querySelectorAll('button').forEach(b => b.onclick = () => { resolve(b.value === 'yes'); d.close(); });
    d.addEventListener('cancel', () => resolve(false));
  });
}
function ask({ title, label, value = '', ok = 'Save', placeholder = '' }) {
  return new Promise(resolve => {
    const d = dialog('<form method="dialog"><h2>' + esc(title) + '</h2><label>' + esc(label) + '<input maxlength="200" placeholder="' + esc(placeholder) + '"></label><div class="actions"><button type="button" class="plain">Cancel</button><button class="primary">' + esc(ok) + '</button></div></form>');
    const input = d.querySelector('input'); input.value = value; input.select();
    let done = false; const finish = v => { if (done) return; done = true; resolve(v); if (d.open) d.close(); };
    d.querySelector('.plain').onclick = () => finish(null);
    d.querySelector('form').onsubmit = e => { e.preventDefault(); finish(input.value.trim() || null); };
    d.addEventListener('close', () => finish(null));
  });
}
function notify(text, actionLabel, action) {
  const box = $('toast'); box.textContent = text;
  if (actionLabel) { const b = el('button', { type: 'button' }, esc(actionLabel)); b.onclick = () => { box.classList.add('hidden'); action(); }; box.append(b); }
  box.classList.remove('hidden'); box.style.animation = 'none'; void box.offsetWidth; box.style.animation = '';
  clearTimeout(toast.timer); toast.timer = setTimeout(() => box.classList.add('hidden'), actionLabel ? 9000 : 5200);
}

/* ---------- frame: sidebar, top bar, side panel ---------- */
const layout = document.querySelector('.layout'), center = document.querySelector('.center'), sidebar = $('sidebar'), topbar = document.querySelector('.topbar');
const panel = $('tool-view'); layout.append(panel);
let sidePref = store.get('nv-side', innerWidth > 1100 ? '1' : '0') === '1', homeSide = false, home = true, lastChatId = null;
const sideToggle = el('button', { id: 'nv-side-toggle', class: 'nv-icon', type: 'button', 'aria-label': 'Show or hide your chats', data: { tip: 'Show or hide your list of chats', key: 'Ctrl+B' } }, icon('side'));
body.append(sideToggle);
let sideHeld = false, sideKept = false;
function setSide(open) {
  sideHeld = false; sideKept = open && body.classList.contains('nv-panel');
  if (home) homeSide = open; else { sidePref = open; store.set('nv-side', open ? '1' : '0'); }
  body.classList.toggle('nv-side', open);
}
sideToggle.onclick = () => setSide(!body.classList.contains('nv-side'));
// Room for the middle. With the side panel open on a window of ordinary size, the list of chats would leave the
// conversation a few hundred pixels: it folds away while that is so, and comes back by itself when there is room
// again. (Opened by hand while the panel is open, it stays: that is its owner's choice.)
const ROOM = 440;
function makeRoom() {
  const open = body.classList.contains('nv-panel') && innerWidth > 900, side = body.classList.contains('nv-side');
  if (!open) sideKept = false;
  const left = innerWidth - (open ? panel.offsetWidth : 0) - sidebar.offsetWidth;        // what the middle has with the list showing
  if (open && side && !sideKept && left < ROOM) { sideHeld = true; body.classList.remove('nv-side'); }
  else if (sideHeld && (!open || left >= ROOM)) { sideHeld = false; if (home ? homeSide : sidePref) body.classList.add('nv-side'); }
}
addEventListener('resize', () => requestAnimationFrame(makeRoom));

/* ---------- Chat and Code: two ways of working ----------
   Chat: talk, ask, and have things done on this PC. Code: build and change software in a project. Each has its own list
   of conversations, its own form of the orb (the living sphere; a block of lines, like code), and its own way of sending:
   a chat message is answered straight away by the assistant, a code message becomes work in the project.
   A conversation that belongs to a project is a code session; one that does not is a chat. */
const smallWindow = new URLSearchParams(location.search).has('mini');      // the small listening window is always the chat sphere
let workMode = !smallWindow && store.get('nv-mode', 'chat') === 'code' ? 'code' : 'chat';
const kindOf = c => c?.project ? 'code' : 'chat';
const modes = el('div', { class: 'nv-modes', role: 'tablist', 'aria-label': 'Chat or Code' });
for (const [id, label, tip] of [['chat', 'Chat', 'Talk, ask, and have things done on this PC'], ['code', 'Code', 'Build and change software in a project']]) {
  const b = el('button', { type: 'button', role: 'tab', data: { mode: id, tip } }, icon(id) + '<span>' + label + '</span>');
  b.onclick = () => setWorkMode(id, true);
  modes.append(b);
}
const usualAsk = () => workMode === 'code' ? 'Describe what to build or change' : 'Ask anything, or describe what to build';
function setWorkMode(next, byHand) {
  const changed = next !== workMode;
  workMode = next; if (changed && !smallWindow) store.set('nv-mode', next);
  body.classList.toggle('nv-coding', next === 'code');
  modes.querySelectorAll('button').forEach(b => { const on = b.dataset.mode === next; b.classList.toggle('on', on); b.setAttribute('aria-selected', String(on)); });
  window.NovaCore?.set({ code: next === 'code' });
  const mode = $('mode'), want = next === 'code' ? 'code' : 'auto';
  if (mode && (changed || (next === 'code') !== (mode.value === 'code'))) { mode.value = want; mode.dispatchEvent(new Event('change', { bubbles: true })); }
  newChat.querySelector('span').textContent = next === 'code' ? 'New session' : 'New chat';
  newChat.dataset.tip = next === 'code' ? 'Start new work in a project' : 'Start a fresh conversation';
  const box = $('message'); if (box && !window.Nova?.research) box.placeholder = usualAsk();
  if (byHand && changed) {
    // The conversation on screen belongs to the other way of working: this one starts afresh. (Chats have no project.)
    const box = $('message'), typed = box?.value || '';
    if (next === 'chat' || kindOf(chat) !== next) selectProject(next === 'chat' ? 'all' : (selectedProject || 'all'));
    if (box && typed && !box.value) { box.value = typed; box.dispatchEvent(new Event('input')); }   // what was typed comes along
    box?.focus();
  } else if (!byHand && next === 'chat' && selectedProject && !chat?.project) { selectedProject = ''; localStorage.setItem('jcc-project-filter', ''); }
  listSig = ''; renderLists?.(); projectChip?.();
}
// Sidebar: one-click new chat, search, my work, then projects and chats.
const newChat = el('button', { class: 'nv-nav', type: 'button', data: { tip: 'Start a fresh conversation', key: 'Ctrl+Shift+O' } }, icon('plus') + '<span>New chat</span>');
const workNav = el('button', { class: 'nv-nav', type: 'button', data: { tip: 'See what JARVIS is doing, what is finished and what needs you' } }, icon('work') + '<span>My work</span>');
$('search').before(newChat); $('search').after(workNav); workNav.classList.add('hidden');
$('search').placeholder = 'Search chats'; $('search').dataset.tip = 'Find a chat by its name'; $('search').dataset.key = 'Ctrl+K';
sidebar.querySelector('.brand').childNodes.forEach(n => { if (n.nodeType === 1 && n.tagName === 'DIV') n.firstChild.textContent = 'JARVIS'; });
// A small living mark next to the name. (While a chat is open the real orb sits there instead.)
sidebar.querySelector('.brand').prepend(el('span', { class: 'nv-mark', 'aria-hidden': 'true' }));
/* Full screen. JARVIS opens in full screen the first time, and after that the way it was left (jcc/placement.py). */
const fullScreen = matchMedia('(display-mode: fullscreen)');
const isFull = () => fullScreen.matches || !!document.fullscreenElement;
function setFull(on) {
  if (on === isFull()) return;
  if (document.fullscreenElement && !on) return void document.exitFullscreen();
  store.set('nv-open', on ? 'fullscreen' : 'remember');
  // The app presses F11 in this window: that is the full screen Windows itself gives a window, and it stays for next time.
  fetch('/api/window', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN }, body: JSON.stringify({ fullscreen: on }) })
    .then(response => response.json()).then(done => { if (!done.done && on) root.requestFullscreen().catch(() => toast('Press F11 for full screen.')); })
    .catch(() => { if (on) root.requestFullscreen().catch(() => toast('Press F11 for full screen.')); });
}
fullScreen.addEventListener('change', () => store.set('nv-open', fullScreen.matches ? 'fullscreen' : 'remember'));
function goHome() { selectProject(selectedProject || 'all'); if (innerWidth < 900) setSide(false); $('message').focus(); }
newChat.onclick = () => { closePanel(); goHome(); };
workNav.onclick = () => window.Nova.command?.('work');
$('new-project').dataset.tip = 'Create a project, or use a folder you already have';
$('new-project').onclick = e => { e.stopPropagation(); openPop($('new-project'), p => {
  item(p, 'Create a new project', 'plus', () => $('project-dialog').showModal(), { note: 'JARVIS sets up the folder for you' });
  item(p, 'Use a folder I already have', 'folder', () => legacyButton(sidebar, 'Open folder…')?.click(), { note: 'Pick a folder on this computer' });
}); };
const account = el('button', { id: 'nv-account', type: 'button', data: { tip: 'Settings, help, appearance and more' } }, '<span class="nv-avatar"></span><span><b>JARVIS</b><span id="nv-account-state">Connecting…</span></span>' + icon('chev'));
sidebar.querySelector('.sidebar-footer').prepend(account);
function themeItems(p) {   // one row of three, so the menu stays short enough for a small screen
  const seg = el('div', { class: 'nv-seg', role: 'radiogroup', 'aria-label': 'Appearance' });
  for (const [value, label, hint] of [['system', 'Automatic', 'Follow light or dark from Windows'], ['light', 'Light', 'Always light'], ['dark', 'Dark', 'Always dark']]) {
    const b = el('button', { type: 'button', role: 'radio', 'aria-checked': String(store.get('nv-theme', 'system') === value), class: store.get('nv-theme', 'system') === value ? 'on' : '', data: { tip: hint } }, label);
    b.onclick = () => { store.set('nv-theme', value); applyTheme(); seg.querySelectorAll('button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', String(x === b)); }); };
    seg.append(b);
  }
  p.append(seg);
}
account.onclick = () => openPop(account, p => {
  item(p, 'Connections', 'keys', () => window.Nova.voiceSettings?.('connect'), { note: 'Connect what JARVIS uses, and see what is connected' });
  item(p, 'Voice and assistant', 'mic', () => window.Nova.voiceSettings?.(), { note: 'Model, voice, hands-free and what JARVIS may do' });
  item(p, 'Usage', 'pulse', () => window.Nova.voiceSettings?.('usage'), { note: 'What your Claude and Codex plans, the voice and JARVIS itself have used' });
  item(p, 'Settings', 'sliders', () => $('info').click());
  item(p, 'Help and getting started', 'help', () => $('easy-help').click());
  item(p, 'Keyboard shortcuts', 'keys', showShortcuts);
  item(p, "What's new", 'spark', () => $('assistant-updates-button')?.click());
  p.append(el('hr')); p.append(el('h5', {}, 'Appearance')); themeItems(p);
  item(p, 'Light mode: ' + ({ auto: 'automatic', on: 'on', off: 'off' }[store.get('nv-light', 'auto')]), 'pulse', () => { const next = { auto: 'on', on: 'off', off: 'auto' }[store.get('nv-light', 'auto')]; store.set('nv-light', next); applyLight(window.Nova.lightHint); api('/api/voice', { action: 'settings', settings: { light: next } }).catch(() => {}); notify('Light mode is now ' + ({ auto: 'automatic', on: 'on', off: 'off' }[next]) + '.'); }, { note: 'Uses less memory and graphics power on modest PCs' });
  item(p, isFull() ? 'Leave full screen' : 'Full screen', 'full', () => setFull(!isFull()), { note: 'JARVIS opens the way you left it' });
  p.append(el('hr'));
  item(p, 'Deleted chats', 'trash', () => legacyButton(document.querySelector('.easy-more-list'), 'Deleted chats')?.click());
  item(p, 'AI accounts and allowance', 'pulse', () => legacyButton(topbar, 'System')?.click());
  item(p, 'Control centre', 'work', () => legacyButton(topbar, 'Control')?.click());
  item(p, body.classList.contains('everyday') ? 'Show expert tools' : 'Hide expert tools', 'code', () => $('easy-experience').click(), { note: 'Extra panels and checks for power users' });
}, { up: true });

// Top bar: title on the left, panel buttons and the chat menu on the right.
const topLeft = el('nav', { class: 'nv-top' }), topRight = el('nav', { class: 'nv-top-right' });
topLeft.append(modes, $('chat-title'), $('project-pill')); topbar.append(topLeft, topRight);
$('chat-title').dataset.tip = 'Click to rename this chat'; $('project-pill').dataset.tip = 'The project this chat belongs to. Click to change it.';
// The top bar, when there is little room (the side panel open on a small window): first the project gives way, then
// the chat's name, then the words on the Chat / Code switch. Nothing ever lies over anything else.
let modesFull = 0;
function fitTop() {
  if (!topLeft.clientWidth) return;
  if (!topbar.classList.contains('nv-top-3')) modesFull = modes.offsetWidth || modesFull;
  const cs = getComputedStyle(topLeft), free = topLeft.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - modesFull - 14;
  topbar.classList.toggle('nv-top-1', free < 150); topbar.classList.toggle('nv-top-2', free < 64); topbar.classList.toggle('nv-top-3', free < 0);
}
if (window.ResizeObserver) new ResizeObserver(fitTop).observe(topLeft);
const PANES = [], paneButtons = new Map(), TOOL_TABS = new Set(['files', 'terminal', 'browser']);
function registerPane(def) { const at = PANES.findIndex(p => p.id === def.id); if (at >= 0) PANES[at] = { ...PANES[at], ...def }; else PANES.push(def); drawTabs(); drawTopButtons(); }
function unregisterPane(id) { const at = PANES.findIndex(p => p.id === id); if (at >= 0) { PANES.splice(at, 1); drawTabs(); drawTopButtons(); } }
function drawTopButtons() {
  topRight.replaceChildren();
  for (const p of PANES.filter(p => p.top)) {
    const b = el('button', { class: 'nv-icon', type: 'button', 'aria-label': p.label, data: { tip: p.tip, pane: p.id } }, icon(p.icon));
    if (p.key) b.dataset.key = p.key;
    b.onclick = () => currentPane === p.id && body.classList.contains('nv-panel') ? closePanel() : openPane(p.id);
    paneButtons.set(p.id, b); topRight.append(b);
  }
  const settingsB = el('button', { class: 'nv-icon', id: 'nv-settings', type: 'button', 'aria-label': 'Settings', data: { tip: 'Settings: connections, voice, appearance and more' } }, icon('gear'));
  settingsB.onclick = () => window.Nova.voiceSettings ? window.Nova.voiceSettings() : $('info').click();     // (straight to Settings, as in Claude)
  topRight.append(settingsB);
  const moreB = el('button', { class: 'nv-icon nv-chat-only', type: 'button', 'aria-label': 'Chat options', data: { tip: 'Rename, star, export or delete this chat' } }, icon('more'));
  moreB.onclick = () => current && openPop(moreB, p => chatMenu(p, current), { right: true });
  topRight.append(moreB);
}
// Side panel
const panelHead = el('div', { class: 'nv-panel-head' }), tabStrip = el('div', { class: 'nv-tabs', role: 'tablist' });
const panelClose = el('button', { class: 'nv-icon', type: 'button', 'aria-label': 'Close panel', data: { tip: 'Close this side panel' } }, icon('x'));
const resizer = el('div', { id: 'nv-resize', data: { tip: 'Drag to resize the panel' } });
panelHead.append(tabStrip, panelClose); panel.prepend(resizer, panelHead);
let currentPane = '';
// There are more tabs than fit: the strip turns with the mouse wheel, fades at the side that has more, and the tab
// that is open is always brought into sight.
function tabEdges() { const more = (tabStrip.scrollLeft > 2 ? 1 : 0) + (tabStrip.scrollLeft + tabStrip.clientWidth < tabStrip.scrollWidth - 2 ? 2 : 0); tabStrip.dataset.more = ['', 'left', 'right', 'both'][more]; }
function showTab() {
  const on = tabStrip.querySelector('.on'), s = tabStrip.getBoundingClientRect();
  if (on && s.width) { const r = on.getBoundingClientRect(); if (r.left < s.left + 24) tabStrip.scrollLeft += r.left - s.left - 24; else if (r.right > s.right - 24) tabStrip.scrollLeft += r.right - s.right + 24; }
  tabEdges();
}
tabStrip.addEventListener('scroll', tabEdges, { passive: true });
tabStrip.addEventListener('wheel', e => { if (!e.deltaX && e.deltaY && tabStrip.scrollWidth > tabStrip.clientWidth) { tabStrip.scrollLeft += e.deltaY; e.preventDefault(); } }, { passive: false });
if (window.ResizeObserver) new ResizeObserver(tabEdges).observe(tabStrip);
function drawTabs() {
  const left = tabStrip.scrollLeft;
  tabStrip.replaceChildren();
  // Only the tools are tabs (as in Claude and T3 Code): files, terminal and browser, and panels of the owner's own.
  // Everything else is a /command that answers in the chat; a panel opened by one shows as a tab while it is open.
  for (const p of PANES.filter(p => TOOL_TABS.has(p.id) || p.id.startsWith('mod') || p.id === currentPane)) {
    const b = el('button', { class: 'nv-tab' + (p.adv ? ' nv-adv' : '') + (p.id === currentPane ? ' on' : ''), type: 'button', role: 'tab', data: { tip: p.tip } }, icon(p.icon) + esc(p.label));
    b.onclick = () => openPane(p.id); tabStrip.append(b);
  }
  tabStrip.scrollLeft = left; showTab(); requestAnimationFrame(showTab);
}
function hideNovaPanes() { panel.querySelectorAll('.nv-pane').forEach(n => n.classList.add('hidden')); }
async function openPane(id) {
  const def = PANES.find(p => p.id === id); if (!def) return;
  if (def.node && !panel.contains(def.node)) { box.querySelector('.nv-pane-card[data-pane="' + id + '"]')?.nvPutBack?.(); if (!panel.contains(def.node)) panel.append(def.node); }
  closePop(); currentPane = id; hideNovaPanes();
  try {
    if (def.node) { panel.querySelectorAll('.tool-content').forEach(n => n.classList.add('hidden')); panel.classList.remove('hidden'); def.node.classList.remove('hidden'); activeTool = 'nova-' + id; await def.show?.(); }
    else await def.open();
  } catch (error) { toast(error.message); }
  drawTabs(); syncPanel();
  if (innerWidth < 900) setSide(false);
}
async function closePanel() { currentPane = ''; hideNovaPanes(); if (!panel.classList.contains('hidden')) await showTool('chat'); syncPanel(); }
panelClose.onclick = closePanel;
function syncPanel() {
  const open = !panel.classList.contains('hidden'); body.classList.toggle('nv-panel', open);
  for (const [id, b] of paneButtons) b.classList.toggle('on', open && id === currentPane);
  updateMode(); makeRoom();
}
new MutationObserver(syncPanel).observe(panel, { attributes: true, attributeFilter: ['class'] });
const savedWidth = Number(store.get('nv-panel-w', 0)); if (savedWidth) root.style.setProperty('--panel-w', savedWidth + 'px');
resizer.addEventListener('pointerdown', e => {
  e.preventDefault(); resizer.setPointerCapture(e.pointerId); body.classList.add('nv-dragging');
  const move = ev => root.style.setProperty('--panel-w', Math.round(Math.max(340, Math.min(innerWidth - 380, innerWidth - ev.clientX))) + 'px');
  const up = () => { resizer.removeEventListener('pointermove', move); body.classList.remove('nv-dragging'); store.set('nv-panel-w', parseInt(getComputedStyle(root).getPropertyValue('--panel-w')) || 0); dispatchEvent(new Event('resize')); };
  resizer.addEventListener('pointermove', move); resizer.addEventListener('pointerup', up, { once: true });
});
const legacyTab = selector => () => toolBar.querySelector(selector)?.click();
registerPane({ id: 'files', label: 'Files', icon: 'folder', top: true, tip: 'Browse, create and edit the files in a project', open: () => showTool('files') });
registerPane({ id: 'terminal', label: 'Terminal', icon: 'term', top: true, key: 'Ctrl+`', tip: 'Type commands for your computer', open: () => showTool('terminal') });
registerPane({ id: 'browser', label: 'Browser', icon: 'globe', top: true, tip: 'Open web pages next to your chat', open: () => showTool('browser') });
registerPane({ id: 'activity', label: 'Activity', icon: 'pulse', tip: 'Review what JARVIS changed and approve results', open: () => showTool('activity') });
registerPane({ id: 'work', label: 'My work', icon: 'work', tip: 'Everything in progress, finished or waiting for you', open: () => $('easy-work-tab').click() });
registerPane({ id: 'insights', label: 'Efficiency', icon: 'spark', adv: true, tip: 'How much each AI was used and how well it did', open: legacyTab('[data-insights]') });
registerPane({ id: 'queue', label: 'Tasks', icon: 'check', adv: true, tip: 'The order of waiting work', open: legacyTab('[data-delivery-pane="queue"]') });
registerPane({ id: 'recall', label: 'Recall', icon: 'search', adv: true, tip: 'Search past decisions and work', open: legacyTab('[data-delivery-pane="recall"]') });

/* ---------- chat list ---------- */
let starred = new Set(), listSig = '', projectSig = '', runningChats = new Set(), unread = new Set(), sending = new Set();
async function loadStars() { try { const d = await api('/api/library', { action: 'query', filters: { pinned: true } }); starred = new Set(d.chats.map(c => c.id)); listSig = ''; if (state) renderLists(); } catch {} }
function dayGroup(ts) {
  const now = new Date(), start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  return !ts ? 'Earlier' : ts >= start ? 'Today' : ts >= start - 86400 ? 'Yesterday' : ts >= start - 7 * 86400 ? 'Previous 7 days' : 'Earlier';
}
const foldedGroups = new Set((() => { try { return JSON.parse(store.get('nv-folded', '[]')) || []; } catch { return []; } })());
document.addEventListener('click', e => {
  const fold = e.target.closest?.('[data-fold]'), add = e.target.closest?.('[data-new-in]');
  if (fold) { const k = fold.dataset.fold; foldedGroups.has(k) ? foldedGroups.delete(k) : foldedGroups.add(k); store.set('nv-folded', JSON.stringify([...foldedGroups])); listSig = ''; renderLists(); }
  else if (add) { e.stopPropagation(); setWorkMode('code', true); selectProject(add.dataset.newIn); projectChip?.(); message.focus(); }
});
const row = c => '<div class="nv-row' + (c.nvChild ? ' nv-child' : '') + '">' + (starred.has(c.id) ? '<i class="nv-star"></i>' : '') + '<button class="nav-item ' + (c.id === current ? 'active' : '') + '" data-chat="' + esc(c.id) + '">' + (runningChats.has(c.id) ? '<i class="nv-live" data-tip="JARVIS is working in this chat"></i>' : unread.has(c.id) ? '<i class="nv-unread" data-tip="New reply you have not read"></i>' : '') + esc(c.title || 'Untitled chat') + '</button><button class="nv-row-more" type="button" data-row-menu="' + esc(c.id) + '" aria-label="Options for this chat" data-tip="Rename, star or delete">' + icon('more') + '</button></div>';
renderLists = function () {
  if (!state) return;
  const openGroups = new Set([...$('chats').querySelectorAll('details[open]')].map(e => e.dataset.group));
  const q = $('search').value.trim().toLowerCase(), active = state.chats.filter(isWorkspace), archive = state.chats.filter(c => !isWorkspace(c));
  $('workspace-tab').classList.toggle('active', libraryMode === 'workspace'); $('history-tab').classList.toggle('active', libraryMode === 'history'); $('history-count').textContent = archive.length || '';
  const items = q ? state.chats.filter(c => (c.title + ' ' + projectName(c.project) + ' ' + (c.source || '')).toLowerCase().includes(q)) : libraryMode === 'history' ? archive : active.filter(c => kindOf(c) === workMode && (!selectedProject || c.project === selectedProject));
  $('library-heading').textContent = q ? 'Results · ' + items.length : libraryMode === 'history' ? 'Older and imported chats' : selectedProject ? projectName(selectedProject) : workMode === 'code' ? 'Code sessions' : 'Chats';
  let html;
  if (libraryMode === 'history' && !q) {
    const labels = { 'Claude': 'From Claude', 'ChatGPT': 'From ChatGPT', 'Codex local': 'Codex on this computer', 'Claude Code local': 'Claude Code on this computer', 'null': 'Archived JARVIS chats' };
    const order = ['Claude', 'ChatGPT', 'Codex local', 'Claude Code local'], sources = [...new Set(items.map(c => c.source))].sort((a, b) => order.indexOf(a) - order.indexOf(b));
    html = sources.map(source => { const group = items.filter(c => c.source === source); return '<details class="history-group" data-group="' + esc(source) + '" ' + (openGroups.has(String(source)) ? 'open' : '') + '><summary>' + esc(labels[source] || source) + '<span>' + group.length + '</span></summary><div class="nav-list">' + group.slice(0, 50).map(row).join('') + (group.length > 50 ? '<div class="nav-empty">Search to find more.</div>' : '') + '</div></details>'; }).join('') || '<div class="nav-empty">Chats you archive or import appear here.</div>';
  } else if (q) html = items.slice(0, 60).map(row).join('') || '<div class="nav-empty">No chats match that search.</div>';
  else {
    const stars = items.filter(c => starred.has(c.id)), rest = items.filter(c => !starred.has(c.id)).slice(0, 120); html = '';
    if (stars.length) html += '<div class="section-label">Starred</div>' + stars.map(row).join('');
    // As in Claude Code: the chats under their project, newest project first, each folding away; "+" starts a chat in it.
    const byProject = new Map();
    for (const c of rest) { const k = c.project || ''; if (!byProject.has(k)) byProject.set(k, []); byProject.get(k).push(c); }
    const grouped = !selectedProject && !(byProject.size === 1 && byProject.has(''));
    body.classList.toggle('nv-grouped', grouped);
    if (grouped) {
      for (const [k, unordered] of byProject) {
        const ids = new Set(unordered.map(c => c.id)), list = [];
        for (const c of unordered) if (!c.parent || !ids.has(c.parent)) { list.push(c); for (const kid of unordered.filter(x => x.parent === c.id)) list.push({ ...kid, nvChild: true }); }
        const name = k ? projectName(k) : workMode === 'code' ? 'No project' : 'Chats', closed = foldedGroups.has(k || '-');
        html += '<div class="nv-pgroup' + (closed ? ' closed' : '') + '"><div class="nv-pgroup-head"><button type="button" class="nv-pgroup-name" data-fold="' + esc(k || '-') + '" aria-expanded="' + !closed + '">' +
          '<span>' + esc(name) + '</span>' + icon('chev') + '</button>' + (k ? '<button type="button" class="nv-icon nv-pgroup-add" data-new-in="' + esc(k) + '" aria-label="New chat in ' + esc(name) + '" data-tip="New chat in ' + esc(name) + '">' + icon('plus') + '</button>' : '') +
          '</div>' + (closed ? '' : list.map(row).join('')) + '</div>';
      }
    } else {
      let group = '';
      for (const c of rest) { const g = dayGroup(c.updated); if (g !== group) { group = g; html += '<div class="section-label">' + g + '</div>'; } html += row(c); }
    }
    html = html || '<div class="nav-empty">' + (workMode === 'code' ? 'No code sessions yet. Choose a project and describe what to build.' : 'No chats yet. Type a message to start one.') + '</div>';
  }
  if (html !== listSig) { listSig = html; $('chats').innerHTML = html; }
  const projects = '<button class="nav-item project-item ' + (!selectedProject ? 'active' : '') + '" data-project="all">' + (workMode === 'code' ? 'All projects' : 'All chats') + '</button>' + state.projects.map(p => '<button class="nav-item project-item ' + (selectedProject === p.key ? 'active' : '') + '" data-project="' + esc(p.key) + '">' + icon('folder') + '<span>' + esc(p.name) + '</span><span class="project-count">' + (active.filter(c => c.project === p.key).length || '') + '</span></button>').join('');
  if (projects !== projectSig) { projectSig = projects; $('projects').innerHTML = projects; }
  const busyJobs = (state.jobs || []).filter(j => ['running', 'queued'].includes(j.status)).length + (state.approvals || []).length;
  workNav.querySelector('.nv-badge')?.remove(); if (busyJobs) workNav.append(el('span', { class: 'nv-badge' }, String(busyJobs)));
  $('nv-account-state').textContent = busyJobs ? busyJobs + ' in progress' : 'Ready';
};
async function setStar(id, on) {
  const d = await api('/api/library', { action: 'query', filters: {} }), meta = d.chats.find(c => c.id === id) || {};
  await api('/api/library', { action: 'organize', id, preferences: { folder: meta.folder || '', tags: meta.tags || [], pinned: on } });
  on ? starred.add(id) : starred.delete(id); listSig = ''; renderLists();
}
// "Delete project": it leaves JARVIS. Its folder stays where it is unless the box is ticked, and then it goes to the
// Recycle Bin (never deleted for good). Its chats are deleted with it (to Deleted chats, where they can be brought back).
const BIN = /Mac/.test(navigator.platform) ? 'Trash' : 'Recycle Bin';
async function deleteProject(key) {
  const p = (state?.projects || []).find(x => x.key === key); if (!p) return;
  const n = (state?.chats || []).filter(c => c.project === key).length;
  const d = dialog('<h2>Delete the project ' + esc(p.name) + '?</h2><p>It is taken out of JARVIS' + (n ? ', with its ' + n + (n === 1 ? ' chat' : ' chats') + ' (you can bring them back from Deleted chats)' : '') + '. Its notes are kept.</p>' +
    '<label class="nv-check"><input type="checkbox" data-trash> Also move its folder to the ' + BIN + '</label>' +
    '<p class="small">' + esc(p.path || '') + '</p><div class="actions"><button class="plain" data-no>Cancel</button><button class="primary danger" data-yes>Delete project</button></div>');
  d.querySelector('[data-no]').onclick = () => d.close();
  d.querySelector('[data-yes]').onclick = async () => {
    const trash = d.querySelector('[data-trash]').checked; d.close();
    try {
      const done = await api('/api/project/remove', { project: key, trash });
      if (selectedProject === key || state?.chats?.some(c => c.id === current && c.project === key)) selectProject('');
      notify('Deleted' + (done.chats ? ', with ' + done.chats + (done.chats === 1 ? ' chat' : ' chats') : '') + '. ' + (done.trashed ? 'Its folder is in the ' + BIN + '.' : 'Its folder is still at ' + (done.kept || 'the same place') + '.'));
      await refresh();
    } catch (error) { toast(error.message); }
  };
}
// A chat in the list: right-click for its menu (rename, star, delete...), as in Claude.
document.addEventListener('contextmenu', e => {
  const chatRow = e.target.closest?.('#chats [data-chat]'); if (!chatRow) return;
  e.preventDefault();
  openPop(chatRow, p => chatMenu(p, chatRow.dataset.chat));
});
// A project in the list: right-click for its folder, or to delete it.
document.addEventListener('contextmenu', e => {
  const row = e.target.closest?.('.project-item[data-project]'); if (!row || row.dataset.project === 'all') return;
  e.preventDefault();
  openPop(row, p => {
    item(p, 'Open file location', 'folder', () => revealProject(row.dataset.project));
    item(p, 'Delete project', 'trash', () => deleteProject(row.dataset.project), { danger: true });
  });
});
async function revealProject(key, file) {
  try { await api('/api/reveal', { project: key, ...(file ? { file } : {}) }); } catch (error) { toast(error.message); }
}
async function renameChat(id) {
  const info = state.chats.find(c => c.id === id), title = await ask({ title: 'Rename chat', label: 'Chat name', value: info?.title || '' });
  if (!title) return; await api('/api/chat/update', { id, title }); await refresh();
}
async function deleteChat(id) {
  const info = state.chats.find(c => c.id === id);
  if (!await confirmBox({ title: 'Delete this chat?', text: '"' + (info?.title || 'This chat') + '" will be removed from JARVIS. You can bring it back from Deleted chats.', ok: 'Delete', danger: true })) return;
  await api('/api/library', { action: 'delete', id });
  if (current === id) goHome();
  await refresh();
  notify('Chat deleted.', 'Undo', async () => { try { await api('/api/library', { action: 'restore', id }); await refresh(); } catch (error) { toast(error.message); } });
}
function exportChat(c) {
  const text = '# ' + c.title + '\n\n' + c.messages.map(m => '## ' + (m.role === 'user' ? 'You' : 'JARVIS') + '\n\n' + m.content).join('\n\n') + '\n';
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' })), a = el('a', { href: url, download: (c.title || 'chat').replace(/[^\w -]+/g, '').slice(0, 60) + '.md' });
  a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000);
}
function sharePage(c) {
  const parts = c.messages.map(m => '<section class="' + (m.role === 'user' ? 'you' : 'ai') + '"><h2>' + (m.role === 'user' ? 'You' : 'JARVIS') + '</h2>' + (m.role === 'user' ? '<p>' + esc(m.content).replace(/\n/g, '<br>') + '</p>' : rich(m.content).replace(/<button[\s\S]*?<\/button>/g, '').replace(/<img[^>]*data-jarvis-image[^>]*>/g, '<p><em>(picture)</em></p>')) + '</section>').join('');
  const page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(c.title) + '</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#1b1b22;background:#faf9f6}h1{font-size:26px}h2{font-size:13px;color:#777;margin:28px 0 6px;text-transform:uppercase;letter-spacing:.06em}.you p{background:#eeedf7;padding:12px 16px;border-radius:14px;display:inline-block}pre{background:#f0efea;padding:14px;border-radius:10px;overflow:auto}code{background:#f0efea;padding:1px 5px;border-radius:5px}pre code{background:none;padding:0}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px 10px;text-align:left}.nv-code-head{display:none}footer{margin:40px 0;color:#999;font-size:13px}</style><h1>' + esc(c.title) + '</h1>' + parts + '<footer>Saved from JARVIS</footer></html>';
  const url = URL.createObjectURL(new Blob([page], { type: 'text/html' })), a = el('a', { href: url, download: (c.title || 'chat').replace(/[^\w -]+/g, '').slice(0, 60) + '.html' });
  a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000); notify('Saved. Send that file to anyone; it opens in any browser.');
}
function chatMenu(p, id) {
  const info = state.chats.find(c => c.id === id) || {}, isStar = starred.has(id);
  item(p, isStar ? 'Remove star' : 'Star', 'star', () => setStar(id, !isStar), { note: 'Starred chats stay at the top' });
  item(p, 'Rename', 'edit', () => renameChat(id));
  if (info?.project) item(p, 'Open file location', 'folder', () => revealProject(info.project), { note: 'Show the project’s folder in ' + (/Mac/.test(navigator.platform) ? 'Finder' : 'File Explorer') });
  item(p, isWorkspace(info) ? 'Archive' : 'Move back to chats', 'box', async () => { await api('/api/chat/update', { id, archived: isWorkspace(info) }); await refresh(); }, { note: 'Hide it from the main list, but keep it' });
  if (id === current && chat) item(p, 'Save as a file', 'down', () => exportChat(chat), { note: 'Download this chat as a text document' });
  if (id === current && chat) item(p, 'Save as a web page to share', 'globe', () => sharePage(chat), { note: 'One file anyone can open in a browser' });
  p.append(el('hr'));
  item(p, 'Delete', 'trash', () => deleteChat(id), { danger: true });
}
document.addEventListener('click', e => { const b = e.target.closest('[data-row-menu]'); if (b) { e.stopPropagation(); openPop(b, p => chatMenu(p, b.dataset.rowMenu)); } });
$('workspace-tab').textContent = 'Recent'; $('history-tab').firstChild.textContent = 'Older ';

/* ---------- rich text (see nova-rich.js) ---------- */
window.NovaNoteLink = note => obsidian(note);
const rich = window.NovaRich.rich;
window.renderRichText = rich;
const codeOf = b => b.closest('.nv-code').querySelector('pre code').textContent;
document.addEventListener('click', async e => {
  const card = e.target.closest('[data-nv-art]'); if (card) { window.Nova.artifact?.(card.closest('.nv-artifact')); return; }
  const b = e.target.closest('[data-nv-copy],[data-nv-editcopy],[data-nv-preview],[data-nv-open]'); if (!b) return;
  try {
    if (b.dataset.nvCopy !== undefined) { await navigator.clipboard.writeText(codeOf(b)); const old = b.innerHTML; b.innerHTML = icon('check') + 'Copied'; setTimeout(() => b.innerHTML = old, 1400); }
    else if (b.dataset.nvEditcopy !== undefined) b.closest('.nv-code').querySelector('[data-edit-copy]').click();
    else window.Nova.preview?.({ code: codeOf(b), lang: b.closest('.nv-code').dataset.lang, run: b.dataset.nvPreview !== undefined });
  } catch (error) { toast(error.message); }
});

/* ---------- conversation ---------- */
const box = $('messages');
let madeIn = { chat: '', count: 0 };              // how many artifacts the open conversation had when it was last looked at
const STAGES = { planned: 'Chose the best AI for this', effort: 'Decided how deeply to think', working: 'Working on it', checking: 'Double-checking the result', waiting: 'Waiting for an AI to be free', switching: 'Switching to another AI', repair: 'Fixing a problem it found', baseline: 'Looking at the project first', context: 'Gathering more background', context_reused: 'Reusing what it already knows', acceptance: 'Noting the evidence', stalled: 'Stuck and needs you', done: 'Finished', failed: 'Could not finish', paused: 'Paused', queued: 'Waiting to start', cancelled: 'Stopped', needs_approval: 'Waiting for your answer', tool: 'Used a tool', note: 'Note' };
const LIVE = new Set(['running', 'queued']);
const WORDS = { running: 'Working', queued: 'Waiting to start', paused: 'Paused', failed: 'Could not finish', needs_approval: 'Waiting for your answer', cancelled: 'Stopped', done: 'Finished' };
let rendered = [], pinned = true, wasLive = new Map(), revealing = new Map(), eventsCache = new Map(), liveText = new Map(), openWork = new Map(), ratings = new Map();
const jump = el('button', { class: 'nv-jump', type: 'button', 'aria-label': 'Jump to the latest message', data: { tip: 'Jump to the latest message' } }, icon('up'));
document.querySelector('.composer-wrap').append(jump);
jump.onclick = () => { pinned = true; box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' }); };
box.addEventListener('scroll', () => { pinned = box.scrollHeight - box.scrollTop - box.clientHeight < 90; jump.classList.toggle('show', !pinned && !home); }, { passive: true });
const stick = () => { if (pinned) box.scrollTop = box.scrollHeight; };
const fmtTime = s => s < 60 ? Math.max(1, Math.round(s)) + 's' : Math.floor(s / 60) + 'm ' + String(Math.round(s % 60)).padStart(2, '0') + 's';
function plainWait(text) {
  if (/too many/i.test(text)) return 'JARVIS is busy with your other requests, or with an earlier message in this chat or project. This one starts by itself as soon as there is room. You can keep chatting meanwhile.';
  if (/no agent available/i.test(text)) return 'No AI is free right now. This will start by itself when one is ready.';
  return text.slice(0, 200);
}
// A step as one short line: the job's own copy of the project is left out of paths ("cd C:/.../jobs/<id>/repo && npm test"
// is "npm test"), and a step the agent took is told apart from what JARVIS itself did around it.
function plainStep(text) {
  return String(text || '').replace(/(?:cd\s+)?["']?[A-Za-z]:[\\/][^\s"']*?[\\/]jobs[\\/][^\\/\s"']+[\\/]repo[\\/]?["']?\s*(?:&&|;)?\s*/gi, '').replace(/\s+/g, ' ').trim() || 'Working';
}
const KINDS = [['command', /^(running|ran|run)\b|command/i, 'ran %n command', 'ran %n commands'], ['read', /^(reading|read|looking at|opening|opened)\b/i, 'read %n file', 'read %n files'],
  ['edit', /^(editing|edited|changing|changed|updating|updated|writing|wrote|saving|saved)\b/i, 'edited %n file', 'edited %n files'], ['create', /^(creating|created|making|made|adding|added)\b/i, 'created %n file', 'created %n files'],
  ['search', /^(searching|searched|finding|found|looking up|looked up|looking for)\b/i, 'searched %n time', 'searched %n times']];
function tally(events) {
  const counts = {};
  for (const ev of events) if (ev.stage === 'tool') { const kind = KINDS.find(([, test]) => test.test(plainStep(ev.message))); if (kind) counts[kind[0]] = (counts[kind[0]] || 0) + 1; }
  const parts = KINDS.filter(([kind]) => counts[kind]).map(([kind, , one, many]) => (counts[kind] === 1 ? one : many).replace('%n', counts[kind]));
  return parts.length ? parts.join(', ').replace(/^./, c => c.toUpperCase()) : '';
}
function stepsHtml(rid, message) {
  const events = eventsCache.get(rid) || [];
  if (!events.length) return '<li>' + (message.status === 'queued' ? 'Waiting its turn' : LIVE.has(message.status) ? 'Getting started' : 'No step-by-step record for this reply') + (LIVE.has(message.status) && message.content ? '<small>' + esc(plainWait(message.content)) + '</small>' : '') + '</li>';
  return events.map(ev => ev.stage === 'tool' ? '<li class="tool">' + esc(plainStep(ev.message)) + '</li>' : '<li class="stage">' + esc(STAGES[ev.stage] || ev.stage) + (ev.agent ? ' · ' + esc(ev.agent === 'codex' ? 'GPT' : ev.agent[0].toUpperCase() + ev.agent.slice(1)) + (ev.model ? ' ' + esc(ev.model) : '') : '') + '</li>').join('');
}
function workBlock(message) {
  const rid = message.receipt, live = LIVE.has(message.status), events = eventsCache.get(rid) || [];
  const open = openWork.has(rid) ? openWork.get(rid) : store.get('nv-transcript', 'normal') === 'verbose';   // (one line until it is opened, as in Claude Code; Verbose: open)
  const span = events.length > 1 ? events[events.length - 1].at - events[0].at : 0;
  const latest = events[events.length - 1];
  const did = tally(events);
  const label = live ? (latest ? (latest.stage === 'tool' ? plainStep(latest.message) : STAGES[latest.stage] || 'Working') : (message.fast ? 'Thinking' : WORDS[message.status])) : message.status === 'done' ? (did || (span ? 'Worked for ' + fmtTime(span) : message.fast ? 'Did ' + events.length + (events.length === 1 ? ' thing' : ' things') : 'Finished')) : WORDS[message.status] || 'Details';
  const mark = live ? '<i class="nv-spin"></i>' : '<i class="nv-done-dot ' + (message.status === 'done' ? '' : ['failed', 'cancelled'].includes(message.status) ? 'bad' : 'wait') + '"></i>';
  return '<details class="nv-work ' + (live ? 'live' : '') + '" data-rid="' + esc(rid) + '" ' + (open ? 'open' : '') + '><summary>' + mark + '<b>' + esc(label) + '</b>' + (live ? '<span data-since="' + (message.at || Date.now() / 1000) + '"></span>' : '') + '</summary><ol class="nv-steps">' + stepsHtml(rid, message) + '</ol>' +
    (live ? '<div class="nv-work-foot"><button class="plain" type="button" data-nv-stop="' + esc(rid) + '" data-tip="Stop this reply. Anything already finished is kept.">' + icon('stop') + 'Stop</button></div>' : message.fast ? '' : ['paused', 'failed'].includes(message.status) ? '<div class="nv-work-foot"><button class="plain" data-job-action="resume" data-job-id="' + esc(rid) + '" data-tip="Carry on from where it stopped">Continue</button></div>' : '') + '</details>';
}
const act = (name, label, iconName, extra = '') => '<button class="nv-icon ' + (name === 'down' ? 'nv-flip' : '') + '" type="button" aria-label="' + label + '" data-tip="' + label + '" ' + extra + '>' + icon(iconName) + '</button>';
function messageHtml(m, i, c) {
  if (m.role === 'user') {
    const [text, note] = m.content.split('\n\nAttached: ');
    return '<div class="nv-bubble">' + esc(text) + '</div>' + (note ? '<div class="nv-attach-note">' + icon('clip') + ' ' + esc(note) + '</div>' : '') +
      '<div class="nv-actions">' + act('copy', 'Copy your message', 'copy', 'data-nv-act="copy" data-i="' + i + '"') + act('edit', 'Edit and send again', 'edit', 'data-nv-act="edit" data-i="' + i + '"') + '</div>';
  }
  if (m.fast && m.steps?.length && !eventsCache.has(m.receipt)) eventsCache.set(m.receipt, m.steps.map((t, n) => ({ stage: 'tool', message: t, at: n })));
  const live = LIVE.has(m.status), job = m.fast ? (LIVE.has(m.status) || !!m.steps?.length) : (!!m.agent || (m.status && m.status !== 'done')), streamed = liveText.get(m.receipt);
  let html = (m.receipt && (job || live)) ? workBlock(m) : '';
  if (m.content?.startsWith('**From the planner**')) return '<details class="nv-planner"><summary>' + icon('note') + '<b>The planner wrote the next steps</b></summary><div class="content">' + rich(m.content.replace(/^\*\*From the planner\*\*\s*/, '')) + '</div></details>';
  if (m.child) html += '<button class="nv-open-child" type="button" data-open-chat="' + esc(m.child) + '">' + icon('arrow') + 'Open its chat</button>';
  if (m.receipt && !m.fast && (m.job || m.agent) && !live && /^(done|needs_approval)$/.test(m.status || '')) html += '<details class="nv-changed" data-job="' + esc(m.receipt) + '"><summary>' + icon('edit') + '<b>See what changed</b></summary><div class="nv-changed-body">Reading the changes…</div></details>';
  if (m.fast && m.status === 'paused' && m.resumes) html += '<div class="nv-waits">' + icon('clock') + '<span>Waiting for an AI to be available again. JARVIS carries on with this by itself at about ' +
    esc(new Date(m.resumes * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })) + '.</span><button class="plain" type="button" data-nv-wait="now" data-rid="' + esc(m.receipt) + '">Try now</button>' +
    '<button class="plain" type="button" data-nv-wait="cancel" data-rid="' + esc(m.receipt) + '">Do not</button></div>';
  if (live) html += streamed ? '<div class="content nv-caret">' + rich(streamed) + '</div>' : '';
  else {
    html += '<div class="content">' + rich(m.content) + '</div>';
    const rated = ratings.get(m.receipt);
    html += '<div class="nv-actions">' + act('copy', 'Copy this reply', 'copy', 'data-answer-action="copy" data-message-index="' + i + '"') + act('retry', 'Try again for a new reply', 'retry', 'data-nv-act="retry" data-i="' + i + '"') +
      act('speak', 'Read this reply aloud', 'speak', 'data-answer-action="speak" data-message-index="' + i + '"') + act('save', 'Save this reply as a file', 'down', 'data-answer-action="save" data-message-index="' + i + '"') +
      (m.agent && m.receipt && !m.fast ? '<button class="nv-icon ' + (rated === 'helpful' ? 'on' : '') + '" type="button" aria-label="Good reply" data-tip="Good reply. Helps JARVIS choose better next time." data-nv-rate="helpful" data-rid="' + esc(m.receipt) + '">' + icon('thumb') + '</button><button class="nv-icon nv-flip ' + (rated === 'needs_work' ? 'on' : '') + '" type="button" aria-label="Not helpful" data-tip="Not helpful. Helps JARVIS choose better next time." data-nv-rate="needs_work" data-rid="' + esc(m.receipt) + '">' + icon('thumb') + '</button>' : '') +
      '<span class="nv-meta">' + (m.image_ids?.length ? '<span>' + m.image_ids.length + ' image' + (m.image_ids.length === 1 ? '' : 's') + '</span>' : '') + (m.status && m.status !== 'done' ? '<span class="status ' + esc(m.status) + '">' + esc(WORDS[m.status] || m.status) + '</span>' : '') +
      (m.model && m.model !== 'none' && m.model !== 'compact' ? '<span data-tip="' + (m.switched?.length ? esc('Carried on here after ' + m.switched.join(' and ') + ' reached its limit') : 'The AI that wrote this reply') + '">' +
        esc((m.agent === 'codex' ? 'GPT ' : m.agent === 'claude' ? 'Claude ' : m.agent && m.agent !== 'jarvis' ? m.agent[0].toUpperCase() + m.agent.slice(1) + ' ' : '') + String(m.model).split('/').pop()) + (m.switched?.length ? ' ↺' : '') + '</span>' : '') +
      (m.receipt && !m.fast ? '<a href="' + esc(obsidian('Requests/' + m.receipt.slice(0, 4) + '/' + m.receipt.slice(4, 6) + '/' + m.receipt)) + '" data-tip="Open the saved record of this request in Obsidian">Record</a>' : '') + '</span></div>';
  }
  return html;
}
function reveal(node, text, rid) {
  const total = text.length, started = performance.now(), duration = Math.max(450, Math.min(2600, total * 5)); let last = 0;
  cancelAnimationFrame(revealing.get(rid)); node.classList.add('nv-caret');
  const step = now => {
    const progress = Math.min(1, (now - started) / duration);
    if (progress >= 1) { node.classList.remove('nv-caret'); node.innerHTML = rich(text); revealing.delete(rid); stick(); return; }
    if (now - last > 34) { last = now; let cut = Math.floor(total * progress); const space = text.indexOf(' ', cut); if (space > 0 && space - cut < 14) cut = space; node.innerHTML = rich(text.slice(0, cut)); stick(); }
    revealing.set(rid, requestAnimationFrame(step));
  };
  revealing.set(rid, requestAnimationFrame(step));
}
function draw(c) {
  const fresh = (c?.id || '') !== lastChatId; lastChatId = c?.id || '';
  if (fresh) { box.querySelectorAll('.nv-pane-card').forEach(card => card.nvPutBack?.()); rendered = []; box.replaceChildren(); wasLive.clear(); pinned = true; }
  const messages = c?.messages || [];
  if (!messages.length) { rendered = []; box.innerHTML = '<div class="welcome"></div><div class="nv-empty">' + (body.classList.contains('nv-panel') ? 'Type a message below to start this chat.' : '') + '</div>'; return; }
  let thread = box.querySelector('.nv-thread'); if (!thread) { box.replaceChildren(); thread = el('div', { class: 'nv-thread' }); box.append(thread); rendered = []; }
  const list = busy && messages[messages.length - 1].role === 'user' ? [...messages, { role: 'assistant', status: 'running', content: '', pending: true, receipt: '', at: Date.now() / 1000 }] : messages;
  list.forEach((m, i) => {
    const sig = m.role + '|' + (m.status || '') + '|' + (m.model || '') + '|' + (m.receipt || '') + '|' + m.content.length + '|' + m.content.slice(0, 60) + m.content.slice(-40) + '|' + (m.pending ? 'p' : '');
    const live = LIVE.has(m.status), key = m.receipt || 'i' + i;
    if (rendered[i]?.sig === sig) return;
    const node = rendered[i]?.node || el('article'); node.className = 'nv-msg ' + (m.role === 'user' ? 'user' : 'assistant') + (fresh ? ' nv-old' : '');
    node.dataset.i = i;
    const finishedNow = m.role === 'assistant' && !live && wasLive.get(key) && !fresh;
    if (m.pending) node.innerHTML = '<details class="nv-work live" open><summary><i class="nv-spin"></i><b>Thinking</b></summary></details>';
    else node.innerHTML = messageHtml(m, i, c);
    if (!rendered[i]) thread.append(node);
    rendered[i] = { sig, node };
    if (m.role === 'assistant' && !m.pending) {
      if (finishedNow && !liveText.get(m.receipt)) reveal(node.querySelector('.content'), m.content, key);
      wasLive.set(key, live || (m.pending ? true : false)); if (!live) liveText.delete(m.receipt);
    }
  });
  if (busy && messages[messages.length - 1].role === 'user') wasLive.set('i' + messages.length, true);
  while (rendered.length > list.length) rendered.pop().node.remove();
  drawChecklist(c);
  requestAnimationFrame(stick);
  // A chat opens at its latest message, as in Claude, even when pictures and cards finish drawing a moment later.
  if (fresh) for (const ms of [60, 250, 700]) setTimeout(() => { if (pinned && lastChatId === (c?.id || '')) box.scrollTop = box.scrollHeight; }, ms);
}
/* ---------- the master chat's checklist: everything this chat set going, one line each, opening to its progress ---------- */
const checklistOpen = new Set();
const JOB_MARK = { running: '<i class="nv-spin"></i>', queued: '<i class="nv-ck wait"></i>', paused: '<i class="nv-ck wait"></i>', done: '<i class="nv-ck done"></i>',
  failed: '<i class="nv-ck bad"></i>', cancelled: '<i class="nv-ck off"></i>', needs_approval: '<i class="nv-ck ask"></i>' };
function jobsOf(c) {
  const messages = c?.messages || [];
  return messages.map((m, i) => ({ m, i })).filter(({ m }) => m.role === 'assistant' && m.receipt && !m.fast && (m.job || m.agent) && /^\d{8}-\d{6}-[a-z0-9]{4}$/.test(m.receipt))
    .map(({ m, i }) => {
      const asked = [...messages.slice(0, i)].reverse().find(x => x.role === 'user');
      const title = String(m.task || (asked ? asked.content.split('\n\nAttached: ')[0] : '') || 'Coding job').split('\n')[0].slice(0, 160);
      return { rid: m.receipt, status: m.status || 'running', title, message: m, child: m.child || '' };
    });
}
function drawChecklist(c) {
  let spot = box.querySelector(':scope > .nv-checklist');
  const jobs = jobsOf(c);
  if (jobs.length < 2 && !(jobs.length === 1 && LIVE.has(jobs[0].status))) { spot?.remove(); return; }      // (one finished job needs no list)
  if (!spot) { spot = el('section', { class: 'nv-checklist', 'aria-label': 'Everything in this chat' }); }
  const asks = box.querySelector(':scope > .nv-asks');
  if (asks) asks.before(spot); else if (spot !== box.lastElementChild) box.append(spot);
  const done = jobs.filter(j => j.status === 'done').length;
  const sig = JSON.stringify(jobs.map(j => [j.rid, j.status, j.title])) + [...checklistOpen].join();
  if (spot.dataset.sig === sig) { for (const rid of checklistOpen) fillChecklistRow(spot, rid); return; }
  spot.dataset.sig = sig;
  spot.innerHTML = '<div class="nv-checklist-head"><b>Everything in this chat</b><span>' + done + ' of ' + jobs.length + ' done</span></div>' +
    jobs.map(j => '<details class="nv-ck-row ' + esc(j.status) + '" data-ck="' + esc(j.rid) + '"' + (checklistOpen.has(j.rid) ? ' open' : '') + '><summary>' + (JOB_MARK[j.status] || JOB_MARK.queued) +
      '<span>' + esc(j.title) + '</span><small>' + esc(WORDS[j.status] || j.status) + '</small></summary><div class="nv-ck-body">Reading its progress…</div></details>').join('');
  for (const rid of checklistOpen) fillChecklistRow(spot, rid);
  stick();
}
async function fillChecklistRow(spot, rid) {
  const row = spot.querySelector('[data-ck="' + rid + '"]'); if (!row) return;
  const job = jobsOf(chat).find(j => j.rid === rid); if (!job) return;
  try {
    const [timeline, live] = await Promise.all([api('/api/timeline?id=' + encodeURIComponent(rid)).catch(() => null), LIVE.has(job.status) ? api('/api/live?id=' + encodeURIComponent(rid)).catch(() => null) : null]);
    const events = [...(timeline?.events || [])];
    for (const step of live?.steps || []) events.push({ stage: 'tool', message: step.text, at: step.at });
    events.sort((a, b) => (a.at || 0) - (b.at || 0)); eventsCache.set(rid, events);
    const body = row.querySelector('.nv-ck-body'); if (!body) return;
    const did = tally(events);
    body.innerHTML = (did ? '<p class="nv-ck-did">' + esc(did) + '</p>' : '') + '<ol class="nv-steps">' + stepsHtml(rid, job.message) + '</ol>' +
      '<div class="nv-ck-foot">' + (LIVE.has(job.status) ? '<button class="plain" type="button" data-nv-stop="' + esc(rid) + '">' + icon('stop') + 'Stop</button>' : '') +
      (job.child ? '<button class="plain" type="button" data-open-chat="' + esc(job.child) + '">Open its chat</button>' : '<button class="plain" type="button" data-ck-show="' + esc(rid) + '">Show in the chat</button>') + '</div>';
    stick();
  } catch {}
}
box.addEventListener('toggle', e => {
  const row = e.target.closest?.('.nv-ck-row[data-ck]'); if (!row) return;
  if (row.open) { checklistOpen.add(row.dataset.ck); fillChecklistRow(row.closest('.nv-checklist'), row.dataset.ck); } else checklistOpen.delete(row.dataset.ck);
}, true);
box.addEventListener('click', e => {
  const b = e.target.closest?.('[data-ck-show]'); if (!b) return;
  const block = box.querySelector('.nv-work[data-rid="' + b.dataset.ckShow + '"]')?.closest('.nv-msg');
  if (block) { pinned = false; block.scrollIntoView({ behavior: 'smooth', block: 'center' }); block.classList.add('nv-flash'); setTimeout(() => block.classList.remove('nv-flash'), 1400); }
});
// While something in the checklist is running, its open rows are read again every few seconds.
setInterval(() => { const spot = box.querySelector(':scope > .nv-checklist'); if (!spot || document.hidden) return; for (const rid of checklistOpen) { const j = jobsOf(chat).find(x => x.rid === rid); if (j && LIVE.has(j.status)) fillChecklistRow(spot, rid); } }, 3000);
renderChat = function (c) {
  chat = c; busy = sending.has(c?.id || 'new') || (sending.has('new') && !c?.messages?.length);
  if (c) unread.delete(c.id);
  $('send').disabled = busy || !!window.jarvisUploading;
  if ($('chat-title').contentEditable !== 'true') $('chat-title').textContent = c?.title || (selectedProject ? projectName(selectedProject) : 'New chat');
  $('project-pill').textContent = projectName(c?.project || selectedProject);
  $('chat-note').classList.toggle('hidden', !c); if (c) $('chat-note').href = obsidian('Conversations/' + c.id);
  const project = state?.projects.find(p => p.key === (c?.project || selectedProject));
  $('project-memory').classList.toggle('hidden', !project); if (project) $('project-memory').href = project.memory;
  const key = JSON.stringify(c?.messages || []) + (busy ? '|busy' : '') + '|' + (c?.id || '');
  if (key !== lastMessages) { lastMessages = key; draw(c); }
  const working = !!c?.messages.some(m => LIVE.has(m.status));
  body.classList.toggle('nv-working', working || (busy && !!c));
  if (c?.messages?.length && kindOf(c) !== workMode) setWorkMode(kindOf(c), false);   // opened from a search, or from the other list
  const made = box.querySelectorAll('.nv-artifact').length;
  if (!c) madeIn = { chat: '', count: 0 };
  else if (madeIn.chat !== c.id) madeIn = { chat: c.id, count: made };
  else if (!working) { if (made > madeIn.count && innerWidth >= 1000 && !smallWindow) window.Nova.artifactLatest?.(); madeIn.count = made; }
  projectChip();
  updateMode(); coreMood(); if (working) fastPoll();
};
async function refreshSteps(rid) {
  if (window.Nova.assistantLive?.(rid)) return;
  const [timeline, live] = await Promise.all([api('/api/timeline?id=' + encodeURIComponent(rid)).catch(() => null), api('/api/live?id=' + encodeURIComponent(rid)).catch(() => null)]);
  const events = [...(timeline?.events || [])];
  for (const step of live?.steps || []) events.push({ stage: 'tool', message: step.text, at: step.at });
  events.sort((a, b) => (a.at || 0) - (b.at || 0));
  const before = (eventsCache.get(rid) || []).length; eventsCache.set(rid, events);
  const block = box.querySelector('.nv-work[data-rid="' + rid + '"]'), message = chat?.messages.find(m => m.receipt === rid && m.role === 'assistant');
  if (block && message && events.length !== before) {
    block.querySelector('.nv-steps').innerHTML = stepsHtml(rid, message);
    if (LIVE.has(message.status)) { const latest = events[events.length - 1]; block.querySelector('summary b').textContent = latest.stage === 'tool' ? plainStep(latest.message) : STAGES[latest.stage] || 'Working'; }
    stick();
  }
  if (live?.text && message && LIVE.has(message.status) && live.text !== liveText.get(rid)) {
    liveText.set(rid, live.text);
    const article = block?.closest('.nv-msg'); if (!article) return;
    let content = article.querySelector('.content'); if (!content) { content = el('div', { class: 'content nv-caret' }); article.append(content); }
    content.innerHTML = rich(live.text); stick();
  }
}
// Words and steps pushed straight from the fast assistant, without waiting for the next check.
function liveUpdate(rid, text, stepList) {
  if (stepList) eventsCache.set(rid, stepList.map((t, i) => ({ stage: 'tool', message: t, at: i })));
  if (text !== undefined) liveText.set(rid, text);
  const block = box.querySelector('.nv-work[data-rid="' + rid + '"]'), message = chat?.messages.find(m => m.receipt === rid && m.role === 'assistant');
  if (!block || !message) return;
  if (stepList) { block.querySelector('.nv-steps').innerHTML = stepsHtml(rid, message); block.querySelector('summary b').textContent = plainStep(stepList[stepList.length - 1]); }
  if (text !== undefined) {
    const article = block.closest('.nv-msg'); let content = article.querySelector('.content');
    if (!content) { content = el('div', { class: 'content nv-caret' }); article.append(content); }
    content.innerHTML = rich(text);
  }
  stick();
}
let fastTimer = 0;
function fastPoll() {
  if (fastTimer) return;
  fastTimer = setTimeout(async function tick() {
    fastTimer = 0;
    const running = (chat?.messages || []).filter(m => m.role === 'assistant' && LIVE.has(m.status) && m.receipt);
    if (!running.length || document.hidden) return;
    try { await Promise.all(running.map(m => refreshSteps(m.receipt))); if (current && !busy) { const fresh = await api('/api/chat?id=' + encodeURIComponent(current)); if (fresh.id === current) renderChat(fresh); } } catch {}
    if (!fastTimer) fastTimer = setTimeout(tick, 900);
  }, 700);
}
setInterval(() => { for (const node of box.querySelectorAll('[data-since]')) node.textContent = '· ' + fmtTime(Date.now() / 1000 - Number(node.dataset.since)); }, 1000);
box.addEventListener('toggle', async e => {
  const changed = e.target.closest?.('.nv-changed[data-job]');
  if (changed && changed.open && !changed.dataset.read) {
    changed.dataset.read = '1'; const spot = changed.querySelector('.nv-changed-body');
    try {
      const d = await api('/api/job/details?id=' + encodeURIComponent(changed.dataset.job)), seen = window.Nova.changeSummary ? window.Nova.changeSummary(d) : { html: esc((d.files || []).join(', ')) };
      const key = chat?.project || '';
      spot.innerHTML = seen.html + '<div class="nv-changed-foot">' + (key ? '<button class="plain" type="button" data-nv-cmd="folder">' + icon('folder') + 'Open file location</button>' : '') +
        (d.can_undo ? '<button class="plain" type="button" data-nv-undo="' + esc(changed.dataset.job) + '">' + icon('retry') + 'Undo these changes</button>' : '') + '</div>';
      if (!(d.files || []).length) spot.textContent = 'No files were changed.';
    } catch (error) { spot.textContent = 'The changes could not be read: ' + error.message; changed.dataset.read = ''; }
    return;
  }
  const block = e.target.closest?.('.nv-work[data-rid]'); if (!block || !block.dataset.rid) return;
  openWork.set(block.dataset.rid, block.open);
  if (block.open && !eventsCache.has(block.dataset.rid)) refreshSteps(block.dataset.rid).then(() => { const m = chat?.messages.find(x => x.receipt === block.dataset.rid && x.role === 'assistant'); if (m) block.querySelector('.nv-steps').innerHTML = stepsHtml(block.dataset.rid, m); });
}, true);
async function stopReply(rid) {
  const target = rid || [...(chat?.messages || [])].reverse().find(m => LIVE.has(m.status) && m.receipt)?.receipt;
  if (!target) return;
  if (await window.Nova.assistantStop?.()) { notify('Stopped.'); return; }
  const d = await api('/api/job/control', { id: target, action: 'cancel' }); notify(d.requested ? 'Stopping. Anything already done is kept.' : 'Stopped.'); await refresh();
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-nv-act],[data-nv-stop],[data-nv-rate],[data-nv-undo],[data-nv-cmd]'); if (!b) return;
  try {
    if (b.dataset.nvCmd) return void runCommand(b.dataset.nvCmd, b.dataset.arg || '');
    if (b.dataset.nvUndo) {
      if (!(await confirmBox({ title: 'Undo these changes?', text: 'JARVIS puts the project back as it was before them, after checking that its checks still pass. Later changes are kept.', ok: 'Undo' }))) return;
      b.disabled = true; await api('/api/job/review', { id: b.dataset.nvUndo, action: 'undo' }); notify('Undone. The project is as it was before those changes.'); return void refresh();
    }
    if (b.dataset.nvStop !== undefined) return await stopReply(b.dataset.nvStop);
    if (b.dataset.nvRate) {
      await api('/api/feedback', { id: b.dataset.rid, rating: b.dataset.nvRate }); ratings.set(b.dataset.rid, b.dataset.nvRate);
      b.parentElement.querySelectorAll('[data-nv-rate]').forEach(x => x.classList.toggle('on', x === b)); return notify('Thanks. JARVIS will use that when choosing an AI.');
    }
    const i = Number(b.dataset.i), m = chat?.messages[i]; if (!m) return;
    if (b.dataset.nvAct === 'copy') { await navigator.clipboard.writeText(m.content.split('\n\nAttached: ')[0]); notify('Copied.'); }
    else if (b.dataset.nvAct === 'edit') { setDraft(m.content.split('\n\nAttached: ')[0]); notify('Change your message, then press Send.'); }
    else if (b.dataset.nvAct === 'retry') {
      const prior = [...chat.messages.slice(0, i)].reverse().find(x => x.role === 'user'); if (!prior || busy) return;
      setDraft(prior.content.split('\n\nAttached: ')[0]); $('composer').requestSubmit();
    }
  } catch (error) { toast(/no measured result/i.test(error.message) ? 'Ratings are available for replies written by an AI job.' : error.message); }
});

/* ---------- several chats at once ---------- */
const priorRenderState = renderState;
renderState = function (d) {
  const now = new Set((d.jobs || []).filter(j => LIVE.has(j.status) && j.chat).map(j => j.chat));
  for (const id of runningChats) if (!now.has(id) && id !== current) {
    const info = d.chats.find(c => c.id === id); if (!info) continue;
    unread.add(id);
    notify('JARVIS has a new reply in "' + (info.title || 'another chat').slice(0, 48) + '".', 'Open', () => openChat(id).catch(error => toast(error.message)));
  }
  const changed = now.size !== runningChats.size || [...now].some(id => !runningChats.has(id));
  if ([...runningChats].some(id => !now.has(id))) runHooks('job');
  runningChats = now; if (changed) listSig = '';
  priorRenderState(d);
};

/* ---------- where the window is ---------- */
// The app window tells the app its size and place, so that it opens there next time (jcc/placement.py). Only the app's
// own window does this (a tab in a browser says nothing), and only while it can be seen: a covered or minimized window
// is not kept up to date about itself by the browser.
(() => {
  const own = matchMedia('(display-mode: standalone)');
  let told = '';
  const tell = () => {
    if (!own.matches && !fullScreen.matches || document.hidden || isFull()) return;   // (in full screen the size to go back to is kept as it was)
    const now = { x: Math.round(screenX), y: Math.round(screenY), width: Math.round(outerWidth), height: Math.round(outerHeight),
      max: outerWidth >= screen.availWidth - 2 && outerHeight >= screen.availHeight - 2 };
    const text = JSON.stringify(now);
    if (text === told || now.width < 200 || now.height < 200) return;
    told = text;
    try { fetch('/api/window', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN }, body: text }).catch(() => {}); } catch {}
  };
  setInterval(tell, 2000);   // nothing is sent unless it has moved or changed size
})();

/* ---------- home / chat mode ---------- */
const wrap = document.querySelector('.composer-wrap');
function updateMode() {
  const has = !!chat?.messages?.length || !!box.querySelector('.nv-local'), voice = body.classList.contains('nv-voice') && !body.classList.contains('nv-panel');
  const nextHome = voice || (!has && !body.classList.contains('nv-panel') && !(busy && current));
  if (nextHome === home && body.classList.contains(home ? 'nv-home' : 'nv-chat')) return;
  const first = wrap.getBoundingClientRect(); home = nextHome;
  body.classList.toggle('nv-home', home); body.classList.toggle('nv-chat', !home);
  body.classList.toggle('nv-side', home ? homeSide : sidePref);
  if (home) { window.NovaCore?.set({ docked: false }); body.classList.toggle('home-expanded', document.activeElement === $('message') || !!$('message').value); }
  else { setTimeout(() => { if (!home) window.NovaCore?.set({ docked: true }); }, 650); window.NovaCore?.pulse(); }
  const last = wrap.getBoundingClientRect(), dx = first.left - last.left, dy = first.top - last.top;
  if (first.width && (Math.abs(dx) > 2 || Math.abs(dy) > 2) && !matchMedia('(prefers-reduced-motion: reduce)').matches)
    wrap.animate([{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }], { duration: 620, easing: 'cubic-bezier(.22,1,.36,1)' });
  grow();
}

/* ---------- composer ---------- */
const form = $('composer'), message = $('message');
message.before($('attachment-chips')); message.placeholder = 'Ask anything, or describe what to build'; message.rows = 1;
const bar = el('div', { class: 'nv-bar' }); message.after(bar);
const plusB = el('button', { class: 'nv-icon', type: 'button', 'aria-label': 'Add files and more', data: { tip: 'Add a file, photo, screenshot or web page' } }, icon('plus'));
const toolsB = el('button', { class: 'nv-icon', type: 'button', 'aria-label': 'Options for this message', data: { tip: 'Choose what JARVIS should do and how carefully' } }, icon('sliders'));
const modelB = el('button', { class: 'nv-chip', type: 'button', data: { tip: 'Choose which AI answers. Auto picks the best one for you.' } }, '<span id="nv-model-name">Auto</span>' + icon('chev'));
// Research: the next message is looked into on the web and answered as a report with its sources. The small arrow beside
// it chooses who does the research.
const researchB = el('button', { class: 'nv-chip nv-research-on', type: 'button', 'aria-pressed': 'false', data: { tip: 'Research your next message on the web and answer with a report and its sources' } }, icon('search') + '<span>Research</span>');
const researchMoreB = el('button', { class: 'nv-icon nv-research-more', type: 'button', 'aria-label': 'Who does the research', data: { tip: 'Choose who does the research' } }, icon('chev'));
const researchG = el('span', { class: 'nv-research' }); researchG.append(researchB, researchMoreB);
// Code: which project the work is for. (A session that is under way keeps its project.)
const projectB = el('button', { class: 'nv-chip nv-project-chip', type: 'button', data: { tip: 'The project this work is for' } }, icon('folder') + '<span>Choose a project</span>' + icon('chev'));
function projectChip() {
  const key = chat?.project || selectedProject || '';
  projectB.querySelector('span').textContent = key ? projectName(key) : 'Choose a project';
  projectB.classList.toggle('nv-need', !key);
}
function chooseProject(then) {
  openPop(projectB, p => {
    p.append(el('h5', {}, 'Which project is this for?'));
    for (const one of state?.projects || []) item(p, one.name, 'folder', () => {
      const typed = message.value;                 // (each project keeps its own unsent draft: what was just typed goes along)
      selectProject(one.key); if (typed && !message.value) { message.value = typed; grow(); }
      projectChip(); then?.();
    }, { tick: (chat?.project || selectedProject) === one.key });
    if (!(state?.projects || []).length) p.append(el('p', { class: 'nv-pop-note' }, 'No projects yet. Create one, or use a folder you already have.'));
    p.append(el('hr'));
    if (chat?.project || selectedProject) {
      item(p, 'Open file location', 'folder', () => revealProject(chat?.project || selectedProject), { note: 'Show this project’s folder' });
      item(p, 'Delete this project', 'trash', () => deleteProject(chat?.project || selectedProject), { danger: true });
    }
    item(p, 'Create a new project', 'plus', () => $('project-dialog').showModal(), { note: 'JARVIS sets up the folder for you' });
    item(p, 'Use a folder I already have', 'folder', () => legacyButton(sidebar, 'Open folder…')?.click(), { note: 'Pick a folder on this computer' });
  });
}
projectB.onclick = () => { if (chat?.project && chat.messages?.length) $('project-pill').click(); else chooseProject(); };
// Ultracode (Code only): work that has to be right gets the strongest AI, thinking as hard as it can, treated as a large
// job and looked at again by a second AI (the service does all that for the effort "ultra"). It stays on until it is
// switched off, and it uses much more of the allowance, so it says so. A model chosen by hand is still respected.
const ultraB = el('button', { class: 'nv-chip nv-ultra', type: 'button', 'aria-pressed': 'false',
  data: { tip: 'Ultracode: the strongest AI, thinking as hard as it can, for work that has to be right. Uses much more of your allowance.' } }, icon('spark') + '<span>Ultracode</span>');
let ultra = store.get('nv-ultra', '0') === '1';
function setUltra(on, quiet) {
  ultra = !!on; store.set('nv-ultra', ultra ? '1' : '0');
  ultraB.classList.toggle('on', ultra); ultraB.setAttribute('aria-pressed', String(ultra));
  if (!quiet) notify(ultra ? 'Ultracode is on: the strongest AI, thinking as hard as it can, and a second AI checks the result. It uses much more of your allowance.' : 'Ultracode is off.');
}
ultraB.onclick = () => setUltra(!ultra);
setUltra(ultra, true);
// Dry run (Code only, and always in the options menu): the plan for what is typed, shown without anything being started.
const dryB = el('button', { class: 'nv-chip nv-dry', type: 'button', data: { tip: 'Dry run: see what JARVIS would do with what you typed (which AI, which steps, what counts as done) without doing any of it.' } },
  icon('pulse') + '<span>Dry run</span>');
dryB.onclick = () => beforeSending('Dry run');
// Security check (Code only): opens the panel that checks a project for the usual holes (nova-security.js).
const secureB = el('button', { class: 'nv-chip nv-secure', type: 'button', data: { tip: 'Security check: look for the usual holes in a project, and have them fixed in a copy.' } },
  icon('shield') + '<span>Security check</span>');
secureB.onclick = () => window.Nova.openPane('security');
const micB = el('button', { class: 'nv-icon', type: 'button', 'aria-label': 'Speak your message', data: { tip: 'Speak instead of typing' } }, icon('mic'));
const stopB = el('button', { id: 'nv-stop', type: 'button', 'aria-label': 'Stop', data: { tip: 'Stop the reply in progress' } }, icon('stop'));
// One row, as in Claude: add, options, the mode (nova-permissions.js puts it after the options), the project in Code, and
// on the right the AI, the microphone and Send. Research and Ultracode show here only while they are on; they, Dry run
// and the security check are in the options menu and are /research, /ultracode, /dryrun and /security.
bar.append(plusB, toolsB, projectB, researchG, ultraB, el('span', { class: 'nv-spacer' }), modelB, micB, stopB, $('send'));
function setResearch(on) {
  window.Nova.research = !!on; researchB.classList.toggle('on', !!on); researchB.setAttribute('aria-pressed', on ? 'true' : 'false'); researchG.classList.toggle('active', !!on);
  message.placeholder = on ? 'What should I research?' : usualAsk();
}
researchB.onclick = () => { setResearch(!window.Nova.research); message.focus(); };
researchMoreB.onclick = async () => {
  if (popAnchor === researchMoreB) return closePop();
  await window.Nova.loadServices?.().catch(() => {});
  openPop(researchMoreB, p => {
    const found = window.Nova.researchChoices?.() || { chosen: 'auto', list: [{ value: 'auto', label: 'Automatic' }] };
    p.append(el('h5', {}, 'Who does the research'));
    let group = '';
    for (const choice of found.list) {
      if ((choice.group || '') !== group) { group = choice.group || ''; if (group) p.append(el('h5', {}, group)); }
      item(p, choice.label, choice.value === 'auto' ? 'spark' : '', async () => {
        await window.Nova.setResearch(choice.value); setResearch(true); message.focus();
        notify(choice.value === 'auto' ? 'JARVIS chooses who does the research.' : choice.label + ' does the research from now on.');
      }, { note: choice.note, tick: found.chosen === choice.value });
    }
    if (!found.perplexity) { p.append(el('hr')); item(p, 'Connect Perplexity', 'keys', () => window.Nova.voiceSettings?.('models'), { note: 'Made for research: it searches widely and lists its sources' }); }
    p.append(el('hr')); item(p, 'What research has used', 'pulse', () => window.Nova.voiceSettings?.('usage'));
  });      // (it opens upwards or downwards, whichever has the room)
};
$('send').dataset.tip = 'Send your message'; $('send').dataset.key = 'Enter'; $('send').setAttribute('aria-label', 'Send');
const suggest = el('div', { class: 'nv-suggest' }, '<p>Just say what you want: JARVIS does the rest. Or start with one of these, or type <b>/</b> to see everything it can do.</p><button type="button" data-easy-start="ask">' + icon('help') + 'Ask a question</button><button type="button" data-easy-start="create">' + icon('spark') + 'Create something</button><button type="button" data-easy-start="continue">' + icon('folder') + 'Continue a project</button>');
wrap.append(suggest);
suggest.querySelectorAll('button')[0].dataset.tip = 'Get an explanation, a plan or ideas';
suggest.querySelectorAll('button')[1].dataset.tip = 'Start a website, tool or automation. No coding needed.';
suggest.querySelectorAll('button')[2].dataset.tip = 'Pick up something you already started';
function grow() { message.style.height = 'auto'; message.style.height = Math.min(message.scrollHeight, innerHeight * 0.38) + 'px'; form.classList.toggle('nv-nodraft', !message.value.trim()); }
function setDraft(text) { message.value = text; grow(); message.focus(); }
let lastLen = -1; setInterval(() => { if (message.value.length !== lastLen) { lastLen = message.value.length; grow(); } }, 300);
message.addEventListener('input', grow);
message.addEventListener('focus', () => { body.classList.add('home-expanded'); coreMood(); });
message.addEventListener('blur', () => { coreMood(); setTimeout(() => { if (home && !message.value && !pop && !form.contains(document.activeElement) && !suggest.contains(document.activeElement) && !document.querySelector('dialog[open]')) body.classList.remove('home-expanded'); }, 180); });
form.addEventListener('pointerdown', e => { if (e.target === form || e.target === bar) { e.preventDefault(); message.focus(); } });
/* ---------- mods: the owner's own commands, hooks, panels and status line (jcc/mods.py) ---------- */
let modsData = { commands: [], builtin: [], packs: [], hooks: [], panels: [], status: { on: false, items: [] } };
// Typing "/" lists the commands, in two: JARVIS's own features, and the skills, plugins and mods (the owner's own
// commands and those of switched-on skill packs). A switch at the top chooses which; ← and → switch too, and typing
// finds a command in either (the side that has it is shown).
const slash = el('div', { class: 'nv-slash hidden', role: 'listbox', 'aria-label': 'Commands' }); form.append(slash);
let slashAt = 0, slashTab = 'features';
const slashLists = () => ({ features: modsData.builtin.map(c => ({ ...c, from: '', own: true })),
  more: [...modsData.commands.map(c => ({ ...c, from: 'Yours' })), ...modsData.packs.map(c => ({ ...c, from: 'Skill pack' }))] });
const slashQuery = () => { const typed = message.value.match(/^\/([\w-]*)$/); return typed ? typed[1].toLowerCase() : null; };
const slashMatch = (list, q) => { const starts = list.filter(c => c.name.startsWith(q)); return q ? [...starts, ...list.filter(c => !starts.includes(c) && (c.name.includes(q) || (c.about || '').toLowerCase().includes(q)))] : list; };
const slashFound = () => { const q = slashQuery(); return q === null ? [] : slashMatch(slashLists()[slashTab], q).slice(0, 80); };
function drawSlash() {
  const q = slashQuery();
  if (q === null) { slash.classList.add('hidden'); return; }
  const lists = slashLists(), here = slashMatch(lists[slashTab], q), there = slashMatch(lists[slashTab === 'features' ? 'more' : 'features'], q);
  if (!here.length && there.length && q) { slashTab = slashTab === 'features' ? 'more' : 'features'; slashAt = 0; return drawSlash(); }
  const found = slashFound();
  slash.classList.remove('hidden');
  slashAt = Math.max(0, Math.min(slashAt, found.length - 1));
  const seg = el('div', { class: 'nv-slash-seg', role: 'tablist' });
  for (const [id, label] of [['features', 'Features'], ['more', 'Skills, plugins & mods']]) {
    const count = slashMatch(lists[id], q).length;
    const b = el('button', { type: 'button', role: 'tab', class: id === slashTab ? 'on' : '', 'aria-selected': String(id === slashTab) }, esc(label) + '<em>' + count + '</em>');
    b.onpointerdown = event => { event.preventDefault(); slashTab = id; slashAt = 0; drawSlash(); };
    seg.append(b);
  }
  const rows = found.map((c, i) => {
    const b = el('button', { type: 'button', role: 'option', class: 'nv-slash-row' + (i === slashAt ? ' on' : ''), 'aria-selected': String(i === slashAt) },
      '<b>/' + esc(c.name) + '</b><span>' + esc(c.about || '') + '</span>' + (c.from ? '<small>' + c.from + '</small>' : ''));
    b.onpointerdown = event => { event.preventDefault(); takeSlash(c); };
    return b;
  });
  const empty = !found.length ? el('div', { class: 'nv-slash-empty' }, slashTab === 'more'
    ? 'No skills, plugins or mods yet. Make your own commands, or switch on a skill pack, in Settings.' : 'No feature is called that.') : null;
  if (empty && slashTab === 'more') { const add = el('button', { type: 'button', class: 'plain' }, 'Open Settings, Customize'); add.onpointerdown = event => { event.preventDefault(); slash.classList.add('hidden'); window.Nova.voiceSettings?.('mods'); }; empty.append(add); }
  const list = el('div', { class: 'nv-slash-list' }); list.append(...rows, ...(empty ? [empty] : []));
  slash.replaceChildren(seg, list);
  list.querySelector('.on')?.scrollIntoView?.({ block: 'nearest' });
}
const AT_ONCE = new Set(['activity', 'efficiency', 'tasks', 'recall', 'shared', 'control', 'folder', 'chat', 'code', 'ultracode', 'new', 'usage', 'mods', 'help', 'compact', 'work', 'mode', 'status', 'projects', 'undo', 'stop', 'settings', 'files', 'terminal', 'browser',
  'artifacts', 'agents', 'pair', 'court', 'security', 'routines', 'voice', 'connections', 'models', 'updates', 'setup', 'advisor']);      // nothing follows these: chosen, they are done
function takeSlash(c) {
  slash.classList.add('hidden');
  if (c.own && AT_ONCE.has(c.name)) { message.value = '/' + c.name; grow(); form.requestSubmit(); return; }
  message.value = '/' + c.name + ' '; grow(); message.focus();
}
message.addEventListener('input', () => { slashAt = 0; drawSlash(); });
message.addEventListener('blur', () => setTimeout(() => slash.classList.add('hidden'), 150));
message.addEventListener('keydown', e => {
  if (slash.classList.contains('hidden')) return;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); slashTab = slashTab === 'features' ? 'more' : 'features'; slashAt = 0; drawSlash(); return; }
  if (e.key === 'Escape') { e.stopPropagation(); slash.classList.add('hidden'); return; }
  const found = slashFound(); if (!found.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); slashAt = (slashAt + (e.key === 'ArrowDown' ? 1 : found.length - 1)) % found.length; drawSlash(); }
  else if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) { e.preventDefault(); e.stopImmediatePropagation(); takeSlash(found[slashAt]); }
  else if (e.key === 'Escape') { e.stopPropagation(); slash.classList.add('hidden'); }
}, true);
// What a command answers is shown in the chat on screen, as a reply of the window's own (it is not saved in the chat).
function localReply(title, html) {
  let thread = box.querySelector('.nv-thread');
  if (!thread) { box.replaceChildren(); thread = el('div', { class: 'nv-thread' }); box.append(thread); body.classList.remove('nv-home'); }
  const node = el('article', { class: 'nv-msg assistant nv-local' }, '<div class="nv-local-head">' + icon('slash') + '<b>' + esc(title) + '</b><button class="nv-icon" type="button" aria-label="Close" data-tip="Close">' + icon('x') + '</button></div><div class="content">' + html + '</div>');
  node.querySelector('.nv-local-head button').onclick = () => { node.remove(); updateMode(); };
  thread.append(node); pinned = true; updateMode(); requestAnimationFrame(stick);
  return node;
}
const PANE_COMMANDS = { files: 'files', terminal: 'terminal', browser: 'browser', artifacts: 'preview', agents: 'agents', pair: 'pair', court: 'court', security: 'security',
  routines: 'routines', activity: 'activity', efficiency: 'insights', tasks: 'queue', recall: 'recall', shared: 'shared', control: 'computer' };
const MODE_IDS = { auto: 'sending', manual: 'all', edits: 'edits', 'accept-edits': 'edits', plan: 'plan', bypass: 'bypass' };
// A feature's panel, shown inside a chat card instead of beside the chat: the same controls, in the conversation.
// (Files, Terminal and Browser stay beside the chat, as tools; so do Artifacts, which open next to what made them.)
const BESIDE = new Set(['files', 'terminal', 'browser', 'preview']);
async function paneInChat(id) {
  const def = PANES.find(p => p.id === id); if (!def) return;
  if (BESIDE.has(id)) return openPane(id);
  const there = box.querySelector('.nv-pane-card[data-pane="' + id + '"]');
  if (there) { there.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
  let node = def.node;
  if (!node) {           // an older panel: it is drawn once, then its part is taken into the chat
    await openPane(id);
    node = [...panel.querySelectorAll('.tool-content')].find(n => !n.classList.contains('hidden'));
    if (!node) return;
  }
  const home = node.parentElement;
  const card = localReply(def.label, ''); card.dataset.pane = id; card.classList.add('nv-pane-card');
  node.classList.remove('hidden', 'tool-content'); node.classList.add('nv-in-chat');
  card.querySelector('.content').append(node);
  if (body.classList.contains('nv-panel')) await closePanel();
  const putBack = () => { if (!node.classList.contains('nv-in-chat')) return; node.classList.remove('nv-in-chat'); node.classList.add('tool-content', 'hidden'); (home || panel).append(node); };
  card.nvPutBack = putBack;
  card.querySelector('.nv-local-head button').onclick = () => { putBack(); card.remove(); updateMode(); };
  if (def.node) { try { await def.show?.(); } catch (error) { toast(error.message); } }
  requestAnimationFrame(() => card.scrollIntoView({ behavior: 'smooth', block: 'start' }));
}
async function runCommand(name, words) {
  try {
    if (name === 'work') {
      const [now, waiting] = await Promise.all([api('/api/agents', { action: 'now' }).catch(() => null), Promise.resolve(window.Nova.waiting?.() || [])]);
      const row = r => '<li><span class="nv-dot ' + esc(r.state || '') + '"></span><b>' + esc(r.title || 'Working') + '</b>' + (r.project ? ' <small>' + esc(r.project) + '</small>' : '') + '<small>' + esc(r.doing || '') + '</small>' +
        (r.chat ? '<button class="plain" type="button" data-open-chat="' + esc(r.chat) + '">Open</button>' : '') + '</li>';
      const working = now?.working || [], recent = (now?.recent || []).slice(0, 6), held = now?.held || [];
      const heldBack = waiting.filter(r => r.kind === 'blocked');
      const node = localReply('Work', (waiting.length ? '<h4>Waiting for you</h4>' + (heldBack.length > 1 ? '<p class="small">' + heldBack.length + ' jobs were held for what they mention. ' +
        '<button class="plain" type="button" data-cancel-held>Cancel all ' + heldBack.length + '</button></p>' : '') + window.Nova.waitingCards(waiting) : '') +
        '<h4>Working now</h4>' + (working.length ? '<ul class="nv-worklist">' + working.map(row).join('') + '</ul>' : '<p class="small">Nothing is running.</p>') +
        (held.length ? '<h4>Waiting to start</h4><ul class="nv-worklist">' + held.map(row).join('') + '</ul>' : '') +
        (recent.length ? '<h4>Finished lately</h4><ul class="nv-worklist">' + recent.map(row).join('') + '</ul>' : ''));
      node.querySelectorAll('.nv-next[data-kind="review"]').forEach(card => window.Nova.fillChanges?.(card));
      // Held jobs often pile up as the same request sent again: they can be cancelled together (nothing was started).
      const all = node.querySelector('[data-cancel-held]');
      if (all) all.onclick = async () => {
        if (!(await confirmBox({ title: 'Cancel all ' + heldBack.length + ' held jobs?', text: 'None of them was started, so nothing in your projects changes. You can ask again any time.', ok: 'Cancel them' }))) return;
        all.disabled = true; let done = 0;
        for (const r of heldBack) { try { await api('/api/permissions', { action: 'decide', kind: 'blocked', id: r.id, yes: false }); done++; } catch {} }
        notify(done + (done === 1 ? ' held job cancelled.' : ' held jobs cancelled.')); node.remove(); window.Nova.permissionsChanged?.(); runCommand('work');
      };
      return;
    }
    if (name === 'mode' || name === 'permissions') {
      const want = MODE_IDS[String(words || '').toLowerCase().replace(/\s+/g, '-')];
      if (want) return void window.Nova.setPermissionMode?.(want);
      const current = window.Nova.permissionMode?.() || 'sending';
      return void localReply('Mode', '<ul class="nv-modelist">' + [['sending', 'Auto', 'JARVIS decides. It asks only before sending, deleting or paying.'], ['all', 'Manual', 'Always ask before making changes.'],
        ['edits', 'Accept edits', 'File edits happen by themselves; commands and other changes ask first.'], ['plan', 'Plan', 'Make a plan first, and change nothing until you say go ahead.'], ['bypass', 'Bypass permissions', 'Never ask. (What JARVIS never does stays off.)']]
        .map(([id, label, about], i) => '<li><button class="' + (id === current ? 'primary' : 'plain') + '" type="button" data-set-mode="' + id + '">' + (i + 1) + '. ' + label + '</button><small>' + about + '</small></li>').join('') + '</ul><p class="small">Shift+Tab in the message box goes to the next mode.</p>');
    }
    if (name === 'status' || name === 'usage') {
      let now = {}; try { now = await api('/api/mods', { action: 'status_now' }); } catch {}
      const left = w => (w.minutes === 300 || /five hour|primary/i.test(w.name) ? '5 hours' : w.minutes === 10080 || /seven day$|secondary/i.test(w.name) ? 'week' : w.name) + ': ' + w.left + '% left';
      const lines = [['Mode', ({ sending: 'Auto', all: 'Manual', edits: 'Accept edits', plan: 'Plan', bypass: 'Bypass permissions' })[window.Nova.permissionMode?.()] || 'Auto'], ['Answers with', now.brain || 'Auto'],
        ['Claude', now.claude ? now.claude.slice(0, 2).map(left).join(' · ') : 'not measured yet'], ['Codex', now.codex ? now.codex.slice(0, 2).map(left).join(' · ') : 'not measured yet'],
        ['Voice', now.voice ? Math.max(0, 100 - Math.round(now.voice.percent)) + '% left' : 'not measured yet'], ['Waiting for you', String((window.Nova.waiting?.() || []).length)]];
      return void localReply(name === 'usage' ? 'Usage' : 'Status', '<dl class="nv-facts">' + lines.map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join('') + '</dl>' +
        '<button class="plain" type="button" data-nv-cmd="settings" data-arg="usage">All the numbers</button>');
    }
    if (name === 'projects') {
      return void localReply('Projects', (state?.projects || []).length ? '<ul class="nv-worklist">' + state.projects.map(p => '<li>' + icon('folder') + '<b>' + esc(p.name) + '</b><button class="plain" type="button" data-use-project="' + esc(p.key) + '">Work on this</button><button class="plain" type="button" data-reveal-project="' + esc(p.key) + '">Open file location</button><button class="plain" type="button" data-delete-project="' + esc(p.key) + '">Delete</button></li>').join('') + '</ul>'
        : '<p>No projects yet. Say what you want built and JARVIS makes one.</p>');
    }
    if (name === 'undo') {
      const job = [...(chat?.messages || [])].reverse().find(m => m.role === 'assistant' && m.receipt && !m.fast && m.status === 'done' && (m.job || m.agent));
      if (!job) return void localReply('Undo', '<p>There is no finished change in this chat to undo.</p>');
      if (!(await confirmBox({ title: 'Undo the last change in this chat?', text: 'JARVIS puts the project back as it was before it, after checking that its checks still pass.', ok: 'Undo' }))) return;
      await api('/api/job/review', { id: job.receipt, action: 'undo' }); notify('Undone.'); return void refresh();
    }
    if (name === 'stop') return void stopReply();
    if (name === 'setup') return void window.Nova.gettingStarted?.();
    if (name === 'advisor') return void advisorCommand(String(words || '').trim().toLowerCase());
    if (name === 'folder') { const key = chat?.project || selectedProject; return void (key ? revealProject(key) : localReply('Open file location', '<p>Choose a project first: /projects.</p>')); }
    if (name === 'settings') return void window.Nova.voiceSettings?.(words || undefined);
    if (['voice', 'connections', 'models', 'updates'].includes(name)) return void window.Nova.voiceSettings?.(name === 'connections' ? 'connections' : name);
    if (PANE_COMMANDS[name]) return void paneInChat(PANE_COMMANDS[name]);
  } catch (error) { toast(error.message); }
}
// /advisor, as in Claude Code: the stronger model Claude Code jobs consult before choosing an approach, when an error
// keeps coming back, and before saying a task is done. "/advisor opus" sets it, "/advisor off" turns it off, and
// "/advisor" alone shows the choices. It is saved, and used by every Claude Code job from then on.
const ADVISORS = [['', 'No advisor', 'Jobs work on their own.'], ['opus', 'Opus', 'The usual choice: strong planning and checking, at Opus rates.'],
  ['fable', 'Fable', 'The strongest, where your account has Fable (on some plans it bills to usage credits).'], ['sonnet', 'Sonnet', 'A cheaper second opinion.']];
const advisorName = id => (ADVISORS.find(([value]) => value === id) || [id, id])[1] || 'No advisor';
async function advisorCommand(words) {
  if (words) {
    const value = words === 'off' || words === 'none' ? 'off' : words;
    const saved = await api('/api/voice', { action: 'settings', settings: { advisor: value } });
    return void localReply('Advisor', '<p>Advisor set to <b>' + esc(advisorName(saved.advisor || '')) + '</b>.' + (saved.advisor ? ' Claude Code jobs consult it at hard moments from now on; it uses more of your allowance.' : '') + '</p>');
  }
  let current = ''; try { current = (await api('/api/voice', { action: 'settings', settings: {} })).advisor || ''; } catch {}
  const node = localReply('Advisor', '<p>A stronger model that Claude Code jobs consult at hard moments: before choosing an approach, when an error keeps coming back, and before saying a task is done. Claude decides when. Each consultation uses more of your allowance. Codex jobs have no advisor.</p>' +
    '<ul class="nv-modelist">' + ADVISORS.map(([id, label, about], i) => '<li><button class="' + (id === current ? 'primary' : 'plain') + '" type="button" data-set-advisor="' + (id || 'off') + '">' + (i + 1) + '. ' + label + '</button><small>' + about + '</small></li>').join('') + '</ul>' +
    '<p class="small">Or type <b>/advisor</b> with a model, for example <b>/advisor opus</b>, a full model id such as <b>/advisor claude-opus-5-5</b>, or <b>/advisor off</b>. An advisor weaker than a job\'s own model is not used.</p>');
  node.querySelectorAll('[data-set-advisor]').forEach(b => b.onclick = async () => { node.remove(); try { await advisorCommand(b.dataset.setAdvisor); } catch (error) { toast(error.message); } });
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-set-mode],[data-open-chat],[data-use-project],[data-reveal-project],[data-delete-project]'); if (!b) return;
  if (b.dataset.revealProject) return void revealProject(b.dataset.revealProject);
  if (b.dataset.deleteProject) return void deleteProject(b.dataset.deleteProject).then(() => b.closest('.nv-local')?.remove());
  if (b.dataset.setMode) { window.Nova.setPermissionMode?.(b.dataset.setMode); b.closest('.nv-local')?.remove(); }
  else if (b.dataset.openChat) openChat(b.dataset.openChat).catch(error => toast(error.message));
  else if (b.dataset.useProject) { setWorkMode('code', true); selectProject(b.dataset.useProject); projectChip(); b.closest('.nv-local')?.remove(); message.focus(); }
});
// JARVIS's own commands are done by the window. True: it was one of them, and it is done.
const IN_CHAT = new Set(['setup', 'advisor', 'activity', 'efficiency', 'tasks', 'recall', 'shared', 'control', 'folder', 'work', 'mode', 'permissions', 'status', 'projects', 'undo', 'stop', 'settings', 'voice', 'connections', 'models', 'updates', 'artifacts', 'files', 'terminal', 'browser', 'agents', 'pair', 'court', 'security', 'routines']);
function runBuiltin(name, words = '') {
  if (IN_CHAT.has(name)) { runCommand(name, words); return true; }
  if (name === 'chat' || name === 'code') setWorkMode(name, true);
  else if (name === 'ultracode') { if (workMode !== 'code') { setWorkMode('code', true); setUltra(true); } else setUltra(!ultra); }
  else if (name === 'new') newChat.click();
  else if (name === 'usage') runCommand('usage');
  else if (name === 'mods') window.Nova.voiceSettings?.('mods');
  else if (name === 'research') { setResearch(true); message.focus(); }
  else if (name === 'help') { const line = (c, from) => '<li><b>/' + esc(c.name) + '</b><span>' + esc(c.about || '') + '</span>' + (from ? '<small>' + from + '</small>' : '') + '</li>';
    localReply('Commands', '<p class="small">Type / in the message box to pick one.</p><ul class="nv-cmdlist">' + modsData.commands.map(c => line(c, 'Yours')).join('') + modsData.builtin.map(c => line(c, '')).join('') + modsData.packs.map(c => line(c, 'Skill pack')).join('') + '</ul>' +
      '<button class="plain" type="button" data-nv-cmd="settings" data-arg="mods">Add or change your own</button>'); }
  else return false;
  return true;
}
function showCommands() {
  const line = (c, from) => '<div class="nv-cmd"><b>/' + esc(c.name) + '</b><span>' + esc(c.about || '') + '</span>' + (from ? '<small>' + from + '</small>' : '') + '</div>';
  const d = dialog('<div class="nv-set-head"><h2>Commands</h2><button class="nv-icon" data-close aria-label="Close">' + icon('x') + '</button></div><div class="nv-cmds">' +
    '<p class="small">Type / in the message box to pick one as you write.</p>' + modsData.commands.map(c => line(c, 'Yours')).join('') + modsData.builtin.map(c => line(c, '')).join('') +
    modsData.packs.map(c => line(c, 'Skill pack')).join('') + '</div><div class="nv-cmd-foot"><button class="plain" data-mods>Add or change your own</button></div>', 'nv-commands');
  d.querySelector('[data-close]').onclick = () => d.close();
  d.querySelector('[data-mods]').onclick = () => { d.close(); window.Nova.voiceSettings?.('mods'); };
}
// The status line: what the owner wants in view, under the message box.
const statusLine = el('div', { class: 'nv-statusline hidden', role: 'status' }); form.after(statusLine);
let statusTimer = 0;
async function drawStatus() {
  clearTimeout(statusTimer);
  const set = modsData.status, on = !!set?.on && !smallWindow;
  statusLine.classList.toggle('hidden', !on); if (!on) return;
  let now = {}; try { now = await api('/api/mods', { action: 'status_now' }); } catch {}
  const left = w => (w.minutes === 300 || /five hour|primary/i.test(w.name) ? '5 h' : w.minutes === 10080 || /seven day$|secondary/i.test(w.name) ? 'week' : w.name) + ' ' + w.left + '%';
  const parts = {
    brain: () => now.brain ? icon('spark') + esc(now.brain) : '',
    claude: () => now.claude ? 'Claude left: ' + esc(now.claude.slice(0, 2).map(left).join(' \u00b7 ')) : '',
    codex: () => now.codex ? 'Codex left: ' + esc(now.codex.slice(0, 2).map(left).join(' \u00b7 ')) : '',
    voice: () => now.voice ? 'Voice left: ' + Math.max(0, 100 - Math.round(now.voice.percent)) + '%' : '',
    clock: () => new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }),
  };
  statusLine.innerHTML = set.items.map(item => parts[item]?.()).filter(Boolean).map(text => '<span>' + text + '</span>').join('');
  statusTimer = setTimeout(drawStatus, 60000);
}
// Hooks: when something happens, a note is shown, something is said, or one of the owner's commands is run (in a
// conversation of its own, so that it never cuts into the one on screen).
function runHooks(when) {
  if (smallWindow) return;
  for (const hook of modsData.hooks) {
    if (!hook.on || hook.when !== when) continue;
    if (hook.do === 'toast') notify(hook.text);
    else if (hook.do === 'say') window.Nova.speakText?.(hook.text);
    else if (hook.do === 'command' && when !== 'answer') api('/api/voice', { action: 'say', text: hook.text, chat: null }).then(() => refresh()).catch(error => toast(error.message));
  }
}
async function loadMods() {
  try { modsData = await api('/api/mods', { action: 'list' }); } catch { return modsData; }
  drawStatus(); window.Nova.pinPanels?.(modsData.panels);
  return modsData;
}
// Each chat sends on its own, so you can start a second request while the first is still running.
form.onsubmit = async e => {
  e.preventDefault();
  let text = message.value.trim(), slot = current || 'new', cid = '';
  if (armed && !text.startsWith('/')) {        // a check chosen in the menu is done now, and answers in the chat; nothing is sent yet
    const what = armed; arm(what);
    if (what === 'Security check') return void paneInChat('security');
    if (!text) { arm(what); return toast('Type your message first, then press Send.'); }
    if (what === 'Improve message') return void improveInChat(text);
    return void beforeSending(what);
  }
  if (!text || sending.has(slot)) return;
  if (window.jarvisUploading) return toast('Wait a moment for the file to finish loading.');
  const command = text.match(/^\/([a-z0-9-]+)(?:\s+([\s\S]*))?$/i);
  if (command) {   // one of JARVIS's own commands is done here; one of the owner's goes on to JARVIS, which knows what it stands for
    const name = command[1].toLowerCase(), words = (command[2] || '').trim();
    if (name === 'research' && words) { setResearch(true); text = words; }
    else if (BEFORE_COMMANDS[name]) { message.value = words; grow(); if (words) beforeSending(BEFORE_COMMANDS[name]); else arm(BEFORE_COMMANDS[name]); return; }   // what follows stays in the box, unsent
    else if ((name === 'mode' || name === 'permissions') && words && runBuiltin(name, words)) { message.value = ''; grow(); return; }
    else if (!words && runBuiltin(name)) { message.value = ''; grow(); return; }
  }
  if (workMode === 'code' && !current && !selectedProject) {   // which project is this for? Then it is sent.
    body.classList.add('home-expanded'); message.focus();
    return setTimeout(() => chooseProject(() => form.requestSubmit()), 0);
  }
  sending.add(slot); busy = true; $('send').disabled = true; window.NovaCore?.pulse();
  const held = { files: [...(window.jarvisFiles || [])], uploads: [...(window.pendingUploads || [])], page: $('attach-page')?.checked || false };
  try {
    if (window.preparePromptForSend) { const prepared = await window.preparePromptForSend(text); text = prepared.text; if (prepared.review) { setDraft(text); toast('JARVIS improved your message. Check it, then press Send again.'); return; } }
    if (!held.page && await window.Nova.pageForSend?.()) held.page = true;
    const planning = window.Nova.permissionMode?.() === 'plan' && !(held.uploads || []).some(u => u.image_id);      // (the assistant plans; nothing is changed)
    if (window.Nova.assistantSend && (window.Nova.assistantUsable(held) || planning)) {
      // Fast path: one warm AI answers straight away. The chat is created by the same request.
      message.value = ''; grow(); window.clearJarvisAttachments?.();
      if (current) { lastMessages = ''; renderChat({ ...chat, messages: [...(chat?.messages || []), { role: 'user', content: text }] }); }
      const started = await window.Nova.assistantSend(text, { files: held.files, uploads: held.uploads, use_browser: held.page, project: current ? undefined : (selectedProject || undefined), research: !!window.Nova.research });
      setResearch(false); cid = started.chat; return;
    }
    if (!current) await makeChat();
    cid = current; sending.add(cid); sending.delete('new'); busy = true;
    message.value = ''; grow();
    const payload = { id: cid, text, agent: $('agent').value, mode: $('mode').value, model: $('model')?.value || 'auto', effort: ultra && workMode === 'code' ? 'ultra' : $('effort')?.value || 'auto', files: held.files, uploads: held.uploads, use_browser: held.page };
    window.clearJarvisAttachments?.();
    lastMessages = ''; renderChat({ ...chat, messages: [...(chat?.messages || []), { role: 'user', content: text }] });
    const reply = await api('/api/chat/send', payload);
    sending.delete(cid);
    if (current === cid) { lastMessages = ''; renderChat(reply); window.readNewReply?.(reply); }
    await refresh();
  } catch (error) {
    if (current === cid || (!cid && !current)) { if (!message.value) setDraft(text); if (!window.jarvisFiles.length && !window.pendingUploads.length) { window.jarvisFiles = held.files; window.pendingUploads = held.uploads; renderAttachments(); } }
    toast(error.message);
  } finally {
    sending.delete(slot); sending.delete(cid); busy = sending.has(current || 'new'); $('send').disabled = busy;
    if (current === cid) { lastMessages = ''; renderChat(chat); message.focus(); }
    coreMood();
  }
};
stopB.onclick = () => stopReply().catch(error => toast(error.message));
box.addEventListener('click', e => { const b = e.target.closest('[data-nv-wait]'); if (b) window.Nova.waitingAction?.(b.dataset.nvWait, b.dataset.rid); });
micB.onclick = () => mic.click(); // replaced by the voice button when voice is available
plusB.onclick = () => openPop(plusB, p => {
  item(p, 'Add a file or photo', 'clip', () => attachButton.click(), { note: 'Documents, pictures, code and more' });
  item(p, 'Take a screenshot', 'cam', () => window.Nova.screenshot?.(), { note: 'You choose which window or screen to share' });
  item(p, 'Add a file from a project', 'folder', () => openPane('files'), { note: 'Pick it in the Files panel' });
  item(p, 'Add the web page I shared', 'globe', () => $('browser-attach').click(), { note: 'Uses the page open in the Browser panel' });
  item(p, 'Use a folder on this computer', 'folder', () => legacyButton(sidebar, 'Open folder…')?.click(), { note: 'Connect it as a project' });
}, { up: !home });
function modeSeg(p) {
  const seg = el('div', { class: 'nv-seg', role: 'radiogroup' });
  for (const [value, label, hint] of [['auto', 'Auto', 'JARVIS decides whether to answer or build'], ['chat', 'Just answer', 'Only talk it through. No files are changed.'], ['code', 'Build', 'Create or change files in a project']]) {
    const b = el('button', { type: 'button', class: $('mode').value === value ? 'on' : '', data: { tip: hint } }, label);
    b.onclick = () => { $('mode').value = value; $('mode').dispatchEvent(new Event('change', { bubbles: true })); seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); };
    seg.append(b);
  }
  p.append(el('h5', {}, 'What should JARVIS do?'), seg);
}
toolsB.onclick = () => openPop(toolsB, p => {
  modeSeg(p);
  item(p, 'Research on the web', 'search', () => { setResearch(!window.Nova.research); message.focus(); }, { note: 'Answer with a report and its sources (/research)', tick: !!window.Nova.research });
  if (workMode === 'code') {
    item(p, 'Ultracode', 'spark', () => setUltra(!ultra), { note: 'The strongest AI, thinking hardest. Uses more allowance (/ultracode)', tick: ultra });
    item(p, 'Security check', 'shield', () => arm('Security check'), { note: 'Look for the usual holes in a project (/security)', tick: armed === 'Security check' });
  }
  p.append(el('hr'));
  const effort = el('label', {}, 'How carefully to think'); const select = el('select', { 'aria-label': 'How carefully to think' }); select.innerHTML = $('effort').innerHTML; select.value = $('effort').value;
  select.onchange = () => { $('effort').value = select.value; $('effort').dispatchEvent(new Event('change', { bubbles: true })); }; effort.append(select); p.append(effort, el('hr'));
  const options = $('easy-option-body');
  item(p, 'Improve message', 'spark', () => arm('Improve message'), { tip: TIPS['Improve message'], note: 'Your message, rewritten so the AI understands it better', tick: armed === 'Improve message' });
  if (!$('undo-prompt').classList.contains('hidden')) item(p, 'Undo the improvement', 'retry', () => $('undo-prompt').click());
  const speak = legacyButton(options, 'Read replies aloud') || legacyButton(options, 'Turn off spoken replies');
  if (speak) item(p, speak.textContent.trim(), 'speak', () => speak.click(), { tip: 'Have JARVIS speak each new reply' });
  // What can be looked at before anything is sent. (These were only shown with "expert tools" switched on; they are for everyone.)
  p.append(el('hr'), el('h5', {}, 'Before you send'));
  for (const [name, glyph, note] of BEFORE) { const legacy = legacyButton(options, name); if (legacy) item(p, name, glyph, () => arm(name), { note, tip: TIPS[name], tick: armed === name }); }
}, { up: !home });
// Chosen in the menu, a check is done when the message is sent, and answers in the chat. Until then it shows in the bar
// as a chip (press it to take it off). One at a time.
let armed = '';
const armedB = el('button', { class: 'nv-chip nv-armed hidden', type: 'button', data: { tip: 'Done when you press Send. Press here to take it off.' } });
researchG.before(armedB);
function arm(name) {
  armed = armed === name ? '' : name;
  armedB.innerHTML = armed ? icon(({ 'Dry run': 'pulse', Checklist: 'check', Context: 'eye', 'Compare rewrite': 'copy', 'Improve message': 'spark', 'Security check': 'shield' })[armed] || 'spark') + '<span>' + esc(armed) + '</span>' + icon('x') : '';
  armedB.classList.toggle('hidden', !armed);
  if (armed) notify(armed + ': type your message and press Send. ' + (armed === 'Security check' ? 'It checks the project you choose.' : 'Nothing is started; the answer comes in the chat.'));
  closePop(); message.focus();
}
armedB.onclick = () => { if (armed) arm(armed); };
// "Improve message", answered in the chat: the rewrite, with the choice to use it.
async function improveInChat(original) {
  let d;
  try { d = await rewriteDraft(original); } catch (error) { return toast(error.message); }
  window.lastPromptRewrite = d;
  const card = localReply('Improve message', '<p class="small">Your message, rewritten so the AI understands it better:</p><pre>' + esc(d.prompt || '') + '</pre>' +
    '<div class="nv-local-foot"><button class="plain" type="button" data-keep-mine>Keep mine</button><button class="plain" type="button" data-use-edit>Use it, I will edit</button><button class="primary" type="button" data-use-send>Use it and send</button></div>');
  card.querySelector('[data-keep-mine]').onclick = () => { card.remove(); message.focus(); };
  card.querySelector('[data-use-edit]').onclick = () => { card.remove(); setDraft(d.prompt || original); };
  card.querySelector('[data-use-send]').onclick = () => { card.remove(); setDraft(d.prompt || original); form.requestSubmit(); };
}
const BEFORE = [['Dry run', 'pulse', 'What JARVIS would do, without doing it'], ['Checklist', 'check', 'What will count as done'],
  ['Context', 'eye', 'What JARVIS will read before answering'], ['Compare rewrite', 'copy', 'Your message beside the improved one']];
// One of those four, from the menu, the Dry run button in Code, or /dryrun and /checklist. Nothing is sent and nothing is started.
// The four "Before you send" choices are commands too: /dryrun, /checklist, /context and /compare, each with what follows.
const BEFORE_COMMANDS = { dryrun: 'Dry run', checklist: 'Checklist', context: 'Context', compare: 'Compare rewrite' };
async function beforeSending(name) {
  if (!message.value.trim()) { toast('Type what you want first, then ' + ({ 'Dry run': 'Dry run shows what JARVIS would do with it, without doing it.', Checklist: 'Checklist shows what will count as done.', Context: 'Context shows what JARVIS will read before answering.', 'Compare rewrite': 'Compare rewrite shows your message beside the improved one.' }[name] || name)); message.focus(); return; }
  // The reply is in the chat at once, saying it is being worked out; the answer fills it when it is ready.
  const card = localReply(name, '<p class="small nv-set-wait"><i class="nv-spin"></i>Working it out…</p>'), spot = card.querySelector('.content');
  const before = new Set(document.querySelectorAll('dialog[open]'));
  legacyButton($('easy-option-body'), name)?.click();
  let last = '', steady = 0;
  for (let i = 0; i < 400; i++) {                     // (its answer is drawn in a box of its own: it is shown in the chat instead; up to a minute)
    await new Promise(resolve => setTimeout(resolve, 150));
    if (!card.isConnected) return;                    // (closed meanwhile)
    const d = [...document.querySelectorAll('dialog[open]')].find(x => !before.has(x)); if (!d) continue;
    d.classList.add('nv-offscreen');                  // (it is not shown while it is being worked out: its answer goes in the chat)
    const now = d.innerHTML; steady = now === last && d.textContent.trim().length > 20 && !/^\s*(Loading|One moment|Checking)/i.test(d.textContent) && !/Preparing|Working/i.test(d.textContent.slice(0, 200)) ? steady + 1 : 0; last = now;
    if (steady < 2) continue;
    const copy = el('div'); copy.innerHTML = now;                 // (the window's own drawing of it, already made safe)
    copy.querySelectorAll('button, dialog, form [type=submit], h2').forEach(n => n.remove());
    copy.querySelectorAll('[id]').forEach(n => n.removeAttribute('id'));
    d.close(); d.classList.remove('nv-offscreen');
    spot.innerHTML = copy.innerHTML + '<div class="nv-local-foot"><button class="plain" type="button" data-before-edit>Change my message</button><button class="primary" type="button" data-before-send>Send it</button></div>';
    spot.querySelector('[data-before-send]').onclick = () => { card.remove(); updateMode(); form.requestSubmit(); };
    spot.querySelector('[data-before-edit]').onclick = () => { card.remove(); updateMode(); message.focus(); };
    stick();
    return;
  }
  spot.innerHTML = '<p>That took too long. Try again in a moment.</p>';
}
function modelLabel() { const option = $('model')?.selectedOptions[0]; $('nv-model-name').textContent = !option || option.value === 'auto' ? 'Auto' : option.textContent; }
modelB.onclick = () => openPop(modelB, p => {
  const select = $('model');
  item(p, 'Auto', 'spark', () => pick('auto'), { note: 'JARVIS picks the best AI and saves your allowance', tick: select.value === 'auto' });
  for (const group of select.querySelectorAll('optgroup')) { if (!group.children.length) continue; p.append(el('h5', {}, group.label)); for (const option of group.children) item(p, option.textContent, '', () => pick(option.value), { tick: select.value === option.value }); }
  function pick(value) { select.value = value; select.dispatchEvent(new Event('change', { bubbles: true })); modelLabel(); }
}, { up: !home, right: true });
const priorPicker = window.updateModelPicker; window.updateModelPicker = d => { priorPicker?.(d); modelLabel(); };
$('model')?.addEventListener('change', modelLabel);       // (however the choice was changed, the button says what it is)
// Drag a file anywhere onto the window to attach it.
let dragDepth = 0;
addEventListener('dragenter', e => { if ([...(e.dataTransfer?.types || [])].includes('Files')) { dragDepth++; body.classList.add('nv-drop'); } });
addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; body.classList.remove('nv-drop'); } });
addEventListener('dragover', e => { if ([...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault(); });
addEventListener('drop', e => { dragDepth = 0; body.classList.remove('nv-drop'); if (!form.contains(e.target) && e.dataTransfer?.files.length) { e.preventDefault(); form.dispatchEvent(new DragEvent('drop', { dataTransfer: e.dataTransfer, bubbles: false, cancelable: true })); } });

/* ---------- title rename ---------- */
const title = $('chat-title');
title.onclick = () => { if (!current || title.contentEditable === 'true') return; title.contentEditable = 'true'; title.focus(); document.getSelection().selectAllChildren(title); };
title.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); title.blur(); } if (e.key === 'Escape') { title.textContent = chat?.title || ''; title.blur(); } };
title.onblur = async () => { if (title.contentEditable !== 'true') return; title.contentEditable = 'false'; const value = title.textContent.trim(); if (value && chat && value !== chat.title) { try { await api('/api/chat/update', { id: current, title: value }); await refresh(); } catch (error) { toast(error.message); } } else title.textContent = chat?.title || 'New chat'; };

/* ---------- shortcuts and first-run guide ---------- */
function showShortcuts() {
  const d = dialog('<h2>Keyboard shortcuts</h2><p>Quicker ways to get around.</p><div class="nv-keys">' + [['New chat', 'Ctrl + Shift + O'], ['Search your chats', 'Ctrl + K'], ['Show or hide the chat list', 'Ctrl + B'], ['Open the terminal', 'Ctrl + `'], ['Send your message', 'Enter'], ['Start a new line', 'Shift + Enter'], ['Stop a reply', 'Esc'], ['Full screen', 'F11'], ['Show this list', 'Ctrl + /']].map(([a, b]) => '<span>' + a + '</span><kbd>' + b + '</kbd>').join('') + '</div><div class="actions"><button class="primary">Done</button></div>');
  d.querySelector('.primary').onclick = () => d.close();
}
document.addEventListener('keydown', e => {
  const mod = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
  if (e.key === 'Escape') { if (pop) { closePop(true); e.stopPropagation(); return; } if (body.classList.contains('nv-working') && !document.querySelector('dialog[open]') && document.activeElement === message && !message.value) stopReply().catch(() => {}); return; }
  if (!mod) return;
  if (key === 'k') { e.preventDefault(); e.stopImmediatePropagation(); setSide(true); $('search').focus(); $('search').select(); }
  else if (key === 'b') { e.preventDefault(); sideToggle.click(); }
  else if (key === 'o' && e.shiftKey) { e.preventDefault(); newChat.click(); }
  else if (e.key === '`') { e.preventDefault(); openPane('terminal'); }
  else if (e.key === '/') { e.preventDefault(); showShortcuts(); }
  else if (key === 'p' && e.shiftKey) { e.preventDefault(); legacyButton(topbar, 'Control')?.click(); }
}, true);
// (The first-run guide is in the chat: nova-start.js, also /setup.)

/* ---------- start ---------- */
welcome = () => '<div class="welcome"></div>';
setWorkMode(workMode, false);
window.Nova = { command: (name, words) => runCommand(name, words || ''), localReply, loadMods, mods: () => modsData, hook: runHooks, unregisterPane, setFull, isFull, icon, el, openPop, closePop, item, dialog, confirmBox, ask, notify, registerPane, openPane, closePanel, rich, setDraft, store, panel, liveUpdate, applyLight, micButton: micB, refreshMode: () => updateMode(), newChat: () => newChat.click(),
  setTheme: name => { store.set('nv-theme', name); applyTheme(); }, get pane() { return currentPane; } };
applyTheme(); drawTabs(); drawTopButtons();
body.classList.add('nova', 'nv-home'); body.classList.remove('workspace-open');
lastMessages = ''; renderChat(chat || null); if (state) { renderLists(); modelLabel(); }
loadStars(); coreMood(); grow();
setTimeout(() => loadMods().then(() => { let first = true; try { first = !sessionStorage.getItem('nv-opened'); sessionStorage.setItem('nv-opened', '1'); } catch {} if (first) runHooks('open'); }), 600);
})();
