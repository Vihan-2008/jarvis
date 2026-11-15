/* Getting started: the first minute in JARVIS, in the chat. Shown once, the first time JARVIS opens, and again with
   /setup or Settings › Advanced › Getting started. It says what JARVIS is doing right now (ready, listening, working,
   asleep, waiting for a permission), gives one harmless first command with the exact words, tests the microphone,
   explains "Hey JARVIS" and "Sleep JARVIS", and on a Mac shows what macOS has to allow, each with "Check again".
   Nothing in it is required: JARVIS works without finishing it, and every step can be skipped. */
(() => {
'use strict';
const N = window.Nova, A = window.NovaAudio; if (!N || !N.localReply || document.body.classList.contains('nv-mini')) return;
const { icon, notify, store } = N, body = document.body;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const MAC = /Mac/i.test(navigator.platform || '') || /Mac OS X/.test(navigator.userAgent || '');
const FIRST = 'open calculator';
let card = null, content = null, timer = 0, conn = null, meterTimer = 0;

const STEPS = () => [
  ['first', 'Try your first command', 'Type <kbd>' + FIRST + '</kbd> in the box below and press Enter, or press the button. JARVIS opens the Calculator by itself: no account is needed for this.',
    '<button class="primary" type="button" data-first>Open Calculator</button>'],
  ['mic', 'Test the microphone', 'Press the button and speak for a few seconds: the bar moves when JARVIS hears you.',
    '<button class="plain" type="button" data-mic>' + icon('mic') + '<span>Test the microphone</span></button><div class="nv-meter hidden" aria-hidden="true"><i></i></div>'],
  ['talk', 'Talk to JARVIS', 'Say <b>“Hey JARVIS”</b>, then what you need, for example “Hey JARVIS, open Calculator”. Say <b>“Sleep JARVIS”</b> when you are done: it stops listening until it hears its name again. You can also press the microphone beside the box below.',
    '<span class="small" data-wake></span><button class="plain" type="button" data-voice>Voice settings</button>'],
  ...(MAC ? [['allow', 'Allow what macOS asks for', 'Only for working in other apps (clicking, typing) and seeing the screen. JARVIS asks when it first needs one; you can also switch them on now.',
    '<ul class="nv-start-perms" data-perms><li class="small">Checking…</li></ul>']] : []),
  ['ai', 'Connect an AI (optional)', 'For questions, writing and building things. Sign in with your Claude or ChatGPT account, or add a key. Quick things like opening apps, timers and sums work without one.',
    '<button class="plain" type="button" data-ai>Connect an AI</button>']];

function html() {
  return '<div class="nv-start"><p class="nv-start-now"><span class="nv-dot" data-dot></span><b data-now>Checking…</b> <span data-now-more></span></p><ol class="nv-start-steps">' +
    STEPS().map(([id, title, about, controls]) => '<li data-step="' + id + '"' + (store.get('nv-start-' + id, '') ? ' class="done"' : '') + '><span class="nv-start-tick">' + icon('check') + '</span><div><b>' + title + '</b><p>' + about + '</p><div class="nv-start-do">' + controls + '</div></div></li>').join('') +
    '</ol><p class="small">Open this again any time: type <b>/setup</b>, or Settings › Advanced › Getting started.</p><div class="actions"><button class="primary" type="button" data-done>Done</button></div></div>';
}

const mark = id => { store.set('nv-start-' + id, '1'); content?.querySelector('[data-step="' + id + '"]')?.classList.add('done'); };

// What JARVIS is doing right now, in plain words.
function now() {
  const items = conn?.items || [], waiting = items.filter(i => String(i.id).startsWith('mac-') && i.state === 'needed'), helper = items.find(i => i.id === 'helper');
  if (body.classList.contains('nv-listening')) return ['ok', 'Listening.', 'Say what you need.'];
  if (body.classList.contains('nv-speaking')) return ['ok', 'Speaking.', ''];
  if (body.classList.contains('nv-thinking') || body.classList.contains('nv-working')) return ['busy', 'Working on it.', 'Its progress shows in the chat.'];
  if (waiting.length) return ['wait', 'Waiting for permission.', 'macOS has to allow ' + (waiting.length === 1 ? 'one thing' : waiting.length + ' things') + ' before JARVIS can work in other apps: see below.'];
  if (!conn) return ['', 'Checking…', ''];
  if (helper && helper.state === 'ok' && /listening for/i.test(helper.status || '')) return ['ok', 'Ready.', 'Asleep until you say “Hey JARVIS”, or type below.'];
  return ['ok', 'Ready.', 'Type below, or press the microphone to talk.'];
}

function draw() {
  if (!content) return;
  const [dot, text, more] = now();
  content.querySelector('[data-dot]').className = 'nv-dot ' + dot;
  content.querySelector('[data-now]').textContent = text;
  content.querySelector('[data-now-more]').textContent = more;
  const helper = (conn?.items || []).find(i => i.id === 'helper'), wake = content.querySelector('[data-wake]');
  if (wake) wake.textContent = helper ? '“Hey JARVIS”: ' + (helper.status || '') + (helper.state === 'problem' && helper.how ? '. ' + helper.how : '') : '';
  const perms = content.querySelector('[data-perms]');
  if (perms && conn) {
    const mine = conn.items.filter(i => String(i.id).startsWith('mac-'));
    perms.innerHTML = mine.length ? mine.map(i => '<li><span class="nv-dot ' + (i.state === 'ok' ? 'ok' : 'wait') + '"></span><b>' + esc(i.name.replace(' (macOS)', '')) + '</b><small>' + esc(i.status) + ' · ' + esc(i.about) + '</small>' +
      (i.state === 'ok' ? '' : '<button class="plain" type="button" data-open-mac="' + (i.id === 'mac-screen' ? 'screen' : 'accessibility') + '">Open System Settings</button><button class="plain" type="button" data-check>Check again</button>') + '</li>').join('')
      : '<li class="small">Nothing to allow here.</li>';
    if (mine.length && mine.every(i => i.state === 'ok')) mark('allow');
  }
}

async function check() {
  try { conn = await api('/api/connections'); } catch { conn = conn || { items: [] }; }
  draw();
}

function attach() {          // shown again at the bottom if the chat was redrawn under it, until Done
  if (card?.isConnected) return;
  card = N.localReply('Getting started', '');
  card.classList.add('nv-start-card');
  card.querySelector('.content').append(content);
  card.querySelector('.nv-local-head button').onclick = finish;
}

function finish() {
  store.set('nv-started', '1'); clearInterval(timer); timer = 0; clearInterval(meterTimer); meterTimer = 0;
  card?.remove(); card = null; content = null; N.refreshMode?.();
}

async function testMic(button) {
  if (meterTimer || !A) return;
  const meter = content.querySelector('.nv-meter'), label = button.querySelector('span');
  try { await A.micStart(); } catch (error) { return notify(error.message || 'The microphone could not be opened.'); }
  const stop = A.hear(() => {}), until = Date.now() + 8000; let heard = 0;
  meter.classList.remove('hidden'); label.textContent = 'Speak now…';
  meterTimer = setInterval(() => {
    const level = A.micLevel || 0; if (level > 0.01) heard++;
    meter.firstElementChild.style.width = Math.min(100, Math.round(Math.sqrt(level) * 260)) + '%';
    if (Date.now() < until && meter.isConnected) return;
    clearInterval(meterTimer); meterTimer = 0; try { stop?.(); } catch {}
    meter.classList.add('hidden'); label.textContent = 'Test again';
    if (heard > 5) { mark('mic'); notify('JARVIS hears you.'); }
    else notify('Nothing was heard. Check that the right microphone is chosen in Settings › Voice, and that it is not muted.');
  }, 60);
}

function guide() {
  if (content && card?.isConnected) { card.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
  content = document.createElement('div'); content.innerHTML = html(); content = content.firstElementChild;
  content.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.matches('[data-done]')) return finish();
    if (b.matches('[data-first]')) { N.setDraft(FIRST); document.getElementById('send')?.click(); mark('first'); return; }
    if (b.matches('[data-mic]')) return void testMic(b);
    if (b.matches('[data-voice]')) { mark('talk'); return void N.voiceSettings?.('voice'); }
    if (b.matches('[data-ai]')) { mark('ai'); return void N.voiceSettings?.('models'); }
    if (b.matches('[data-open-mac]')) return void api('/api/connections', { action: 'mac_settings', which: b.dataset.openMac }).catch(error => notify(error.message));
    if (b.matches('[data-check]')) { b.disabled = true; b.textContent = 'Checking…'; return void check(); }
  });
  attach(); check();
  clearInterval(timer); let ticks = 0;
  timer = setInterval(() => { if (!content) return; attach(); draw(); if (++ticks % 10 === 0 && document.visibilityState === 'visible') check(); }, 1500);
}

// A typed first command counts too.
document.addEventListener('submit', () => { const box = document.getElementById('message'); if (content && box && /^\s*(?:hey jarvis,?\s*)?open (?:the )?calculator\b/i.test(box.value)) mark('first'); }, true);

N.gettingStarted = guide;
// The first time JARVIS opens (someone who saw the older welcome note has seen enough of it).
if (!store.get('nv-started', '') && !store.get('nv-welcomed', '')) setTimeout(guide, 900);
})();
