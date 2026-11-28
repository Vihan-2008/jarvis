// The JARVIS phone app. Talks only to its own origin and the owner's own relay (config.json); everything else is in
// these files. The phone's key is made here, cannot be copied out (non-extractable), and signs every request.
import * as P from './proto.js';
import { toNodes } from './md.js';

const enc = new TextEncoder();
const app = document.getElementById('app');
const FILE_MOST = 20 * 1024 * 1024;
const KEEP = 500;
let config = null, me = null;
const S = { messages: [], after: 0, asks: [], answered: {}, computer: null, offlineAnswers: false, mode: 'now', online: true,
  asleep: false, checking: true, files: [], queued: new Set(), syncing: false, recording: null, timer: 0, notifyOff: false, shown: new Set() };

// ------------------------------------------------------------------ small helpers

const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
};
const ICONS = {
  attach: 'M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
  send: 'M5 12h14M13 6l6 6-6 6',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2', close: 'M6 6l12 12M18 6L6 18',
};
const icon = name => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', ICONS[name]); svg.append(path);
  return svg;
};
const size = n => n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : n >= 1024 ? Math.round(n / 1024) + ' KB' : n + ' bytes';
const page = (...kids) => { app.replaceChildren(h('div', { class: 'page' }, ...kids)); app.querySelector('h1')?.focus?.(); };
const installed = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const ios = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const iosSafari = () => ios() && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(navigator.userAgent);

// ------------------------------------------------------------------ storage on the phone (IndexedDB)

let dbOpen;
function db() {
  dbOpen ||= new Promise((resolve, reject) => {
    const r = indexedDB.open('jarvis', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('kv');
    r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error);
  });
  return dbOpen;
}
async function kv(key, value) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction('kv', value === undefined ? 'readonly' : 'readwrite').objectStore('kv');
    const r = value === undefined ? t.get(key) : value === null ? t.delete(key) : t.put(value, key);
    r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error);
  });
}
async function wipe() {
  for (const k of ['me', 'messages', 'after', 'settings']) await kv(k, null);
  me = null; S.messages = []; S.after = 0;
  try { const reg = await navigator.serviceWorker?.getRegistration(); const sub = await reg?.pushManager.getSubscription(); await sub?.unsubscribe(); } catch {}
  try { for (const name of await caches.keys()) if (name.startsWith('jarvis-files')) await caches.delete(name); } catch {}
}
const saveMessages = () => kv('messages', S.messages.slice(-KEEP)).catch(() => {});

// ------------------------------------------------------------------ the relay

class Gone extends Error {}
async function sign(text) {
  return P.b64(new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, me.privateKey, enc.encode(text))));
}
async function call(action, body = {}, { raw, type, name, signed = true, timeout = 40000 } = {}) {
  const bytes = raw ?? enc.encode(P.wireJson(body));
  const headers = { 'x-jarvis-action': action, 'content-type': raw ? (type || 'application/octet-stream') : 'application/json' };
  if (name) headers['x-jarvis-name'] = encodeURIComponent(name).slice(0, 300);
  if (signed) {
    const at = Date.now();
    Object.assign(headers, { 'x-jarvis-phone': me.phoneId, 'x-jarvis-at': String(at), 'x-jarvis-sig': await sign(P.requestText(action, me.phoneId, at, await P.sha256Hex(bytes))) });
  }
  const stop = new AbortController(), timer = setTimeout(() => stop.abort(), timeout);
  let res;
  try { res = await fetch(config.relay, { method: 'POST', body: bytes, headers, signal: stop.signal, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer' }); }
  finally { clearTimeout(timer); }
  const json = /json/.test(res.headers.get('content-type') || '');
  const value = json ? await res.json().catch(() => ({})) : await res.blob();
  if (res.status === 401 && signed && value?.error === 'revoked') { await wipe(); showRevoked(); throw new Gone('revoked'); }
  if (!res.ok) { const e = new Error(value?.error || `The relay answered ${res.status}.`); e.status = res.status; e.body = value; throw e; }
  return value;
}

// ------------------------------------------------------------------ start

async function start() {
  try { config = await (await fetch('config.json', { cache: 'no-store' })).json(); }
  catch { page(h('h1', {}, 'JARVIS'), h('p', { class: 'error' }, "This page couldn't load its settings. Redeploy it from JARVIS on your computer.")); return; }
  registerWorker();
  let pairing = null;
  const hash = location.hash.match(/^#p=([A-Za-z0-9_-]{8,64})\.([0-9A-Za-z]{8})$/);
  if (location.hash) history.replaceState(null, '', location.pathname);       // the code never stays in the address
  if (hash) pairing = { pairId: hash[1], code: hash[2] };
  if (!(await ed25519Works())) { showOld(); return; }
  if (!installed() && !config.allow_tab) { showInstall(); return; }      // (allow_tab: the local dev server only)
  me = await kv('me').catch(() => null);
  const settings = (await kv('settings').catch(() => null)) || {};
  if (settings.size) document.documentElement.dataset.size = settings.size;
  if (!me?.phoneId) { showPair(pairing); return; }
  S.messages = (await kv('messages').catch(() => null)) || [];
  S.after = (await kv('after').catch(() => null)) || 0;
  showChat();
}

async function ed25519Works() {
  try { await crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']); return true; } catch { return false; }
}

function registerWorker() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('sw.js').then(reg => {
    reg.addEventListener('updatefound', () => {
      const next = reg.installing;
      next?.addEventListener('statechange', () => { if (next.state === 'installed' && navigator.serviceWorker.controller) document.getElementById('update').hidden = false; });
    });
  }).catch(() => {});
  document.getElementById('reload').onclick = async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    reg?.waiting?.postMessage('take-over');
    setTimeout(() => location.reload(), 300);
  };
}

// ------------------------------------------------------------------ install

function showOld() {
  page(h('h1', { tabindex: -1 }, 'JARVIS'), h('p', {}, "This phone's software is too old for JARVIS. It needs iOS 17 or Chrome 137."));
}

let installPrompt = null;
addEventListener('beforeinstallprompt', e => { e.preventDefault(); installPrompt = e; if (!installed() && me === null && app.querySelector('[data-install]')) showInstall(); });

function showInstall() {
  if (ios() && !iosSafari()) {
    const copy = h('button', { class: 'primary', onclick: async () => { try { await navigator.clipboard.writeText(location.origin + location.pathname); copy.textContent = 'Copied'; } catch {} } }, 'Copy link');
    page(h('h1', { tabindex: -1 }, 'Open this page in Safari to install JARVIS.'), h('div', { class: 'actions' }, copy));
    return;
  }
  if (ios()) {
    page(h('h1', { tabindex: -1 }, 'Add JARVIS to your Home Screen'),
      h('ol', {}, h('li', {}, 'Tap Share at the bottom.'), h('li', {}, 'Tap Add to Home Screen.'), h('li', {}, 'Tap Add, then open JARVIS from your Home Screen.')),
      h('p', { class: 'muted' }, 'This is needed for notifications and to keep you signed in.'));
    return;
  }
  const kids = [h('h1', { tabindex: -1, 'data-install': true }, 'Install JARVIS')];
  if (installPrompt) {
    kids.push(h('div', { class: 'actions' }, h('button', { class: 'primary', onclick: async () => { installPrompt.prompt(); await installPrompt.userChoice; installPrompt = null; } }, 'Install')));
  } else kids.push(h('p', {}, 'Tap ⋮, then Add to Home screen.'));
  kids.push(h('p', { class: 'muted' }, 'This is needed for notifications and to keep you signed in.'));
  page(...kids);
}

// ------------------------------------------------------------------ pairing (inside the installed app only)

function phoneName() {
  const ua = navigator.userAgent;
  const device = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) || ios() ? 'iPad' : /Android/.test(ua) ? ((ua.match(/Android [\d.]+; ([^;)]+)/) || [])[1] || 'Android phone').trim() : 'Phone';
  const browser = /CriOS|Chrome/.test(ua) ? 'Chrome' : /Firefox|FxiOS/.test(ua) ? 'Firefox' : /Safari/.test(ua) ? 'Safari' : 'browser';
  return `${device}, ${browser}`.slice(0, 60);
}

function showPair(given = null, problem = '') {
  const input = h('input', { class: 'code', id: 'code', inputmode: 'text', autocomplete: 'one-time-code', autocapitalize: 'characters', spellcheck: 'false',
    maxlength: 9, 'aria-describedby': 'pair-error', value: given ? P.showCode(given.code) : '' });
  input.addEventListener('input', () => { const at = input.value; input.value = P.showCode(at); });
  const error = h('p', { class: 'error', id: 'pair-error', role: 'alert' }, problem);
  const go = h('button', { class: 'primary', type: 'submit' }, 'Pair');
  const form = h('form', { class: 'field', onsubmit: e => { e.preventDefault(); pair(P.normalCode(input.value), given?.pairId, error, go); } },
    h('label', { for: 'code' }, 'Code from your computer'), input, h('div', { class: 'actions' }, go,
      'BarcodeDetector' in window ? h('button', { type: 'button', onclick: () => scan(error) }, 'Scan the code instead') : null));
  page(h('h1', { tabindex: -1 }, 'Pair with your computer'), h('p', {}, 'In JARVIS on your computer, type /phone and choose Add a phone.'), form, error);
  if (given) pair(P.normalCode(given.code), given.pairId, error, go);
}

async function scan(error) {
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }); }
  catch { error.textContent = "JARVIS can't use the camera. Type the code instead."; return; }
  const video = h('video', { class: 'scan', playsinline: true, muted: true, 'aria-label': 'Camera' });
  video.srcObject = stream;
  const cancel = h('button', { onclick: () => { stream.getTracks().forEach(t => t.stop()); showPair(); } }, 'Type the code instead');
  page(h('h1', { tabindex: -1 }, 'Point at the code on your computer'), video, h('div', { class: 'actions' }, cancel));
  await video.play().catch(() => {});
  const detector = new BarcodeDetector({ formats: ['qr_code'] });
  const look = async () => {
    if (!stream.active) return;
    try {
      for (const code of await detector.detect(video)) {
        const m = String(code.rawValue).match(/#p=([A-Za-z0-9_-]{8,64})\.([0-9A-Za-z]{8})$/);
        if (m) { stream.getTracks().forEach(t => t.stop()); showPair({ pairId: m[1], code: m[2] }); return; }
      }
    } catch {}
    setTimeout(look, 300);
  };
  look();
}

async function pair(code, pairId, error, button) {
  if (!code) { error.textContent = "That code didn't match. Check it and try again."; return; }
  button.disabled = true; error.textContent = '';
  try {
    if (!pairId) {
      const open = await call('pair_open', {}, { signed: false });
      if (!open.pair_id) { error.textContent = 'That code ran out. Ask your computer for a new one.'; return; }
      pairId = open.pair_id;
    }
    const keys = await crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']);   // the private half can never be read out
    const publicKey = P.b64(new Uint8Array(await crypto.subtle.exportKey('raw', keys.publicKey)));
    const name = phoneName();
    const tag = await P.pairTag(code, pairId, publicKey, name);
    await call('pair_request', { pair_id: pairId, public_key: publicKey, name, tag }, { signed: false });
    page(h('h1', { tabindex: -1 }, "Now click 'Yes, pair it' on your computer."), h('p', { class: 'muted', role: 'status' }, 'Waiting for your computer…'));
    for (;;) {
      await new Promise(r => setTimeout(r, 2500));
      const st = await call('pair_status', { public_key: publicKey }, { signed: false }).catch(() => ({ state: 'waiting' }));
      if (st.state === 'paired' && st.phone_id) {
        me = { phoneId: st.phone_id, privateKey: keys.privateKey, publicKey, name };
        await kv('me', me);
        showNotifyAsk();
        return;
      }
      if (st.state === 'refused') { showPair(null, "That code didn't match. Check it and try again."); return; }
      if (st.state === 'expired' || st.state === 'unknown') { showPair(null, 'That code ran out. Ask your computer for a new one.'); return; }
    }
  } catch (e) {
    if (e.status === 409) error.textContent = 'That code ran out. Ask your computer for a new one.';
    else if (e.status === 429) error.textContent = e.message;
    else error.textContent = 'No connection. Check your internet and try again.';
  } finally { button.disabled = false; }
}

function showNotifyAsk() {
  page(h('h1', { tabindex: -1 }, "You're in."), h('p', {}, 'Turn on notifications so you know when JARVIS answers.'),
    h('div', { class: 'actions' },
      h('button', { class: 'primary', onclick: async () => { const ok = await turnOnPush(); if (!ok) S.notifyOff = true; showChat(); } }, 'Turn on'),
      h('button', { onclick: () => { S.notifyOff = true; showChat(); } }, 'Not now')));
}

async function turnOnPush() {
  try {
    if (!config.vapid || !('PushManager' in window)) return false;
    if ((await Notification.requestPermission()) !== 'granted') return false;
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: P.unb64url(config.vapid) });
    const json = sub.toJSON();
    await call('push', { subscription: { endpoint: json.endpoint, keys: json.keys } });
    return true;
  } catch { return false; }
}

function showRevoked() {
  page(h('h1', { tabindex: -1 }, 'This phone was removed from JARVIS.'), h('p', {}, 'Its messages here are erased.'),
    h('div', { class: 'actions' }, h('button', { class: 'primary', onclick: () => showPair() }, 'Pair again')));
}

// ------------------------------------------------------------------ the chat

const UI = {};
function showChat() {
  UI.status = h('span', { class: 'status' });
  UI.said = h('span', { class: 'sr', role: 'status' });
  UI.checking = h('div', { class: 'checking', role: 'status' }, 'Checking for new messages…');
  UI.list = h('div', { class: 'list', 'aria-live': 'polite', 'aria-label': 'Messages' });
  UI.ask = h('div');
  UI.composer = h('div', { class: 'composer' });
  const header = h('header', {},
    h('button', { class: 'who quiet', onclick: whatWorks, 'aria-haspopup': 'dialog' }, h('b', {}, 'JARVIS'), UI.status),
    h('button', { class: 'icon', onclick: showSettings, 'aria-label': 'Settings' }, icon('gear')));
  app.replaceChildren(h('div', { class: 'chat' }, header, UI.said, UI.checking, UI.list, UI.ask, UI.composer));
  renderStatus(); renderMessages(); renderComposer();
  if (!S.syncing) syncLoop();
  addEventListener('online', () => { S.online = true; flush(); renderStatus(); });
  addEventListener('offline', () => { S.online = false; renderStatus(); });
}

function computerLine() {
  if (!S.online) return ['', 'No connection'];
  if (S.asleep) return ['', 'Relay asleep · wake it from your computer'];
  if (!S.computer) return ['', 'Connecting…'];
  if (S.computer.on) return ['ok', 'Your computer is on'];
  return ['warn', S.offlineAnswers ? 'Computer off · a smaller assistant answers' : 'Computer off · messages wait for it'];
}
function renderStatus() {
  if (!UI.status) return;
  const [kind, text] = computerLine();
  UI.status.replaceChildren(h('span', { class: 'dot ' + kind }), text);
  if (UI.said && UI.lastSaid !== text) { if (UI.lastSaid !== undefined) UI.said.textContent = text; UI.lastSaid = text; }
}

function whatWorks() {
  const on = S.computer?.on;
  sheet(h('h2', {}, 'What works right now'),
    h('p', {}, on ? 'Everything, as in the app, in careful mode. Private notes stay on your computer.'
      : 'Works now: questions, drafting, Word documents, voice notes. Waits for your computer: your files, apps, email, projects, pictures and PDFs.'));
}

let sheets = 0;
function sheet(...kids) {
  const opener = document.activeElement, id = 'sheet-' + (++sheets);
  const shut = () => {
    el.remove(); removeEventListener('keydown', onKey);
    if (opener?.isConnected) opener.focus();
  };
  const onKey = e => { if (e.key === 'Escape' && el.isConnected && !document.querySelector('.full')) { e.preventDefault(); shut(); } };
  const close = h('button', { onclick: shut }, 'Close');
  const el = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true', onclick: e => { if (e.target === el) shut(); } }, h('div', {}, ...kids, close));
  el.shut = shut;
  const title = el.querySelector('h2');
  if (title) { title.id = id; title.setAttribute('tabindex', '-1'); el.setAttribute('aria-labelledby', id); }
  document.body.append(el);
  addEventListener('keydown', onKey);
  title?.focus();
  return el;
}

function stateLine(m) {
  if (m.local === 'sending') return h('div', { class: 'state' }, S.online ? 'Sending…' : "Will send when you're back online.");
  if (m.local === 'failed') return h('div', { class: 'state' }, h('button', { onclick: () => resend(m) }, 'Not sent. Tap to try again.'));
  if (m.local === 'limit') return h('div', { class: 'state' }, "That's a lot of messages. Try again in a few minutes.");
  if (m.local === 'next') return h('div', { class: 'state' }, 'Next in line');
  const replied = S.messages.some(x => x.role === 'assistant' && x.reply_to === m.msg_id && (x.tags || []).includes('done'));
  if (replied) return null;
  if (m.status === 'queued') return h('div', { class: 'state' }, icon('clock'), m.limit ? 'Laptop-off answers reached today’s limit. This is waiting for your computer.' : 'Waiting for your computer');
  if (m.status === 'with_computer' || m.status === 'received') return h('div', { class: 'state' }, 'Working on your computer…');
  if (m.status === 'failed') return h('div', { class: 'state' }, "Your computer couldn't run this.");
  return null;
}

function fileCard(f) {
  const status = h('span');
  const open = h('button', { onclick: async () => {
    open.disabled = true; status.textContent = ' · Downloading…';
    try {
      const blob = await call('file', { id: f.id }, { timeout: 120000 });
      const file = new File([blob], f.name, { type: f.mime || blob.type });
      if (navigator.canShare?.({ files: [file] })) await navigator.share({ files: [file] }).catch(() => {});
      else { const url = URL.createObjectURL(file); h('a', { href: url, download: f.name }).click(); setTimeout(() => URL.revokeObjectURL(url), 60000); }
      status.textContent = '';
    } catch (e) {
      status.textContent = e.status === 404 ? ' · This file is no longer on the relay. Ask JARVIS to send it again.' : " · Couldn't download. Try again.";
    } finally { open.disabled = false; }
  } }, 'Open');
  return h('div', { class: 'file' }, h('div', { class: 'meta' }, h('b', {}, f.name), h('span', {}, (f.mime || 'file').split('/').pop() + ' · ' + size(f.size || 0)), status), open);
}

function messageEl(m) {
  if (m.role === 'notice') return h('div', { class: 'msg notice' }, m.text);
  if (m.role === 'user') {
    return h('div', { class: 'msg user' },
      m.text ? h('div', { class: 'bubble' }, m.text) : null,
      m.voiceUrl ? h('audio', { controls: true, src: m.voiceUrl, 'aria-label': 'Your voice note' }) : null,
      (m.files || []).filter(f => !m.voiceUrl || !/^audio\//.test(f.mime)).map(f => h('div', { class: 'state' }, '\u{1F4CE} ' + f.name + ' · ' + size(f.size || 0))),
      stateLine(m));
  }
  const tags = m.tags || [];
  return h('div', { class: 'msg assistant' }, h('div', { class: 'text md' }, toNodes(m.text, h)),
    (m.files || []).map(fileCard),
    tags.includes('offline') ? h('span', { class: 'tag' }, 'Answered while your computer was off') : null,
    tags.includes('done') && S.queued.has(m.reply_to) ? h('span', { class: 'tag done' }, 'Done on your computer') : null);
}

function renderMessages() {
  if (!UI.list) return;
  UI.checking.hidden = !S.checking;
  const atBottom = UI.list.scrollHeight - UI.list.scrollTop - UI.list.clientHeight < 80;
  if (!S.messages.length) {
    const chip = text => h('button', { type: 'button', onclick: () => { UI.field.value = text; UI.field.focus(); renderComposerButtons(); } }, text);
    UI.list.replaceChildren(h('div', { class: 'empty' },
      h('p', {}, 'Ask anything. With your computer on, this is the same JARVIS. With it off, a smaller assistant answers and anything bigger waits.'),
      h('div', { class: 'chips' }, chip("What's on my list today?"), chip('Draft a reply to…'), chip('Remind me to…'))));
  } else {
    // Only a message shown for the first time rises in; the list is redrawn on every update without moving the rest.
    UI.list.replaceChildren(...S.messages.map(m => {
      const el = messageEl(m), key = m.msg_id || m.id;
      if (S.shown.has(key)) el.classList.add('seen'); else S.shown.add(key);
      return el;
    }));
  }
  if (atBottom || S.justSent) { UI.list.scrollTop = UI.list.scrollHeight; S.justSent = false; }
}

// ------------------------------------------------------------------ approvals

function renderAsk() {
  if (!UI.ask) return;
  clearInterval(S.timer);
  const ask = S.asks.find(a => !S.answered[a.ask_id]);
  const done = Object.entries(S.answered).find(([, v]) => v.show && Date.now() - v.at < 6000);
  if (!ask) {
    UI.ask.replaceChildren(done ? h('div', { class: 'ask', role: 'status' }, h('p', {}, done[1].text)) : '');
    return;
  }
  if (!ask.approvable) {
    UI.ask.replaceChildren(h('div', { class: 'ask', role: 'alert' }, h('h2', {}, 'Needs your computer'),
      h('div', { class: 'what' }, ask.question + (ask.detail ? '\n\n' + ask.detail : '')),
      h('p', {}, 'This kind of action (paying, deleting, installing, system commands) can only be approved there.')));
    return;
  }
  const left = h('span', { class: 'left' });
  const tick = () => {
    const s = Math.max(0, Math.round((ask.expires - Date.now()) / 1000));
    left.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} left`;
    if (s <= 0) { S.answered[ask.ask_id] = { at: Date.now(), show: true, text: 'This ran out, so the answer was no. Ask again if you still want it.' }; renderAsk(); }
  };
  const answer = async yes => {
    no.disabled = go.disabled = true;
    try {
      const sig = await sign(await P.answerText(ask.ask_id, ask.nonce, ask.question, ask.detail, yes));
      await call('answer', { ask_id: ask.ask_id, yes, sig });
      S.answered[ask.ask_id] = { at: Date.now(), show: true, text: yes ? 'You said yes.' : 'You said no.' };
    } catch (e) {
      S.answered[ask.ask_id] = { at: Date.now(), show: true, text: e.body?.error === 'expired' ? 'This ran out, so the answer was no. Ask again if you still want it.'
        : e.status === 409 ? 'Answered on your computer.' : 'No connection. Try again.' };
      if (!e.status) delete S.answered[ask.ask_id];
    }
    renderAsk();
  };
  const no = h('button', { onclick: () => answer(false) }, 'No');
  const go = h('button', { class: 'primary', onclick: () => answer(true) }, 'Yes, do it');
  UI.ask.replaceChildren(h('div', { class: 'ask', role: 'alert' }, h('h2', {}, 'JARVIS needs your answer'),
    h('div', { class: 'what', tabindex: 0 }, ask.question + (ask.detail ? '\n\n' + ask.detail : '')),
    h('p', {}, 'JARVIS will only do this if you say yes.'), left, h('div', { class: 'actions' }, no, go)));
  tick(); S.timer = setInterval(tick, 1000);
}

// ------------------------------------------------------------------ the composer

function renderComposer() {
  UI.field = h('textarea', { rows: 1, placeholder: 'Message JARVIS', 'aria-label': 'Message JARVIS', enterkeyhint: 'send' });
  UI.field.addEventListener('input', () => { UI.field.style.height = 'auto'; UI.field.style.height = Math.min(UI.field.scrollHeight, innerHeight * 0.4) + 'px'; renderComposerButtons(); });
  UI.picker = h('input', { type: 'file', multiple: true, hidden: true, onchange: () => { addFiles([...UI.picker.files]); UI.picker.value = ''; } });
  UI.modes = h('div', { class: 'modes', role: 'group', 'aria-label': 'When the computer is off' });
  UI.attached = h('div', { class: 'attached' });
  UI.note = h('div', { class: 'note', role: 'status' });
  UI.action = h('span');
  UI.row = h('div', { class: 'row' }, h('button', { class: 'icon', onclick: () => UI.picker.click(), 'aria-label': 'Attach a photo or file' }, icon('attach')), UI.field, UI.action, UI.picker);
  UI.composer.replaceChildren(UI.modes, UI.attached, UI.note, UI.row);
  renderComposerButtons(); renderModes();
}

function renderModes() {
  if (!UI.modes) return;
  const show = S.computer && !S.computer.on && S.offlineAnswers;
  UI.modes.hidden = !show;
  if (!show) return;
  const b = (mode, label) => h('button', { 'aria-pressed': String(S.mode === mode), onclick: () => { S.mode = mode; renderModes(); } }, label);
  UI.modes.replaceChildren(b('now', 'Answer now'), b('wait', 'Wait for my computer'));
}

function renderComposerButtons() {
  const has = UI.field.value.trim() || S.files.length;
  UI.action.replaceChildren(has ? h('button', { class: 'icon', onclick: () => send(), 'aria-label': 'Send' }, icon('send'))
    : h('button', { class: 'icon', onclick: record, 'aria-label': 'Record a voice note' }, icon('mic')));
  UI.attached.replaceChildren(...S.files.map((f, i) => h('span', { class: 'chip' }, h('span', {}, f.name + ' · ' + size(f.size)),
    h('button', { class: 'icon', 'aria-label': 'Remove ' + f.name, onclick: () => { S.files.splice(i, 1); renderComposerButtons(); } }, icon('close')))));
  const needsComputer = S.files.some(f => /^image\/|pdf$/.test(f.type)) && S.computer && !S.computer.on;
  UI.note.textContent = needsComputer ? 'Pictures and PDFs are read on your computer. This will wait for it.' : UI.note.dataset.keep || '';
}

function addFiles(files) {
  for (const f of files) {
    if (f.size > FILE_MOST) { UI.note.textContent = 'That file is over 20 MB. Send a smaller one.'; continue; }
    S.files.push(f);
  }
  renderComposerButtons();
}

UI.field = null;
addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && e.target === UI.field && matchMedia('(pointer: fine)').matches) { e.preventDefault(); send(); } });

async function send(voice = null) {
  const text = UI.field.value.trim();
  const files = voice ? [voice.file] : S.files.splice(0);
  if (!text && !files.length) return;
  const m = { role: 'user', msg_id: P.newId(), text: voice ? '' : text, files: files.map(f => ({ name: f.name, mime: f.type, size: f.size })), at: Date.now(),
    local: 'sending', wait: S.mode === 'wait' || files.some(f => /^image\/|pdf$/.test(f.type)), pending: files, voiceUrl: voice?.url };
  if (!voice) { UI.field.value = ''; UI.field.style.height = ''; }
  S.messages.push(m); S.justSent = true;
  renderComposerButtons(); renderMessages();
  await deliver(m);
}

async function deliver(m) {
  if (!S.online) return;            // sent by flush() when the connection is back
  try {
    const uploaded = [];
    for (const f of m.pending || []) {
      const bytes = new Uint8Array(await f.arrayBuffer());
      const made = await call('upload', {}, { raw: bytes, type: f.type || 'application/octet-stream', name: f.name, timeout: 180000 });
      uploaded.push({ id: made.id, sha256: made.sha256, name: f.name.slice(0, 120), mime: f.type || 'application/octet-stream', size: f.size });
    }
    const at = Date.now();
    const sig = await sign(await P.messageText(me.phoneId, m.msg_id, at, m.text, uploaded.map(f => f.sha256)));
    const res = await call('send', { msg_id: m.msg_id, text: m.text, files: uploaded, at, sig, wait_for_computer: m.wait });
    m.local = null; m.pending = null; m.status = res.computer === 'on' ? 'with_computer' : 'received';
  } catch (e) {
    if (e instanceof Gone) return;
    m.local = e.status === 429 ? 'limit' : 'failed';
  }
  saveMessages(); renderMessages();
}
const resend = m => { m.local = 'sending'; renderMessages(); deliver(m); };
const flush = () => { for (const m of S.messages) if (m.local === 'sending' && m.pending !== null) deliver(m); };

// ------------------------------------------------------------------ voice notes

async function record() {
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { UI.note.textContent = "JARVIS can't hear you. Allow the microphone in your phone's settings."; return; }
  const type = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'].find(t => MediaRecorder.isTypeSupported?.(t)) || '';
  const rec = new MediaRecorder(stream, type ? { mimeType: type } : {});
  const chunks = []; rec.ondataavailable = e => e.data.size && chunks.push(e.data);
  const audio = new AudioContext(), source = audio.createMediaStreamSource(stream), meter = audio.createAnalyser();
  source.connect(meter); const buf = new Uint8Array(meter.fftSize);
  const time = h('span', { class: 'time', 'aria-live': 'off' }, '0:00'), level = h('i');
  const started = Date.now();
  let cancelled = false;
  const finish = sendIt => { cancelled = !sendIt; rec.stop(); };
  rec.onstop = () => {
    stream.getTracks().forEach(t => t.stop()); audio.close(); clearInterval(tick);
    renderComposer();
    if (cancelled || !chunks.length) return;
    const mime = (rec.mimeType || type || 'audio/mp4').split(';')[0];
    const blob = new Blob(chunks, { type: mime });
    const file = new File([blob], 'voice.' + (mime.includes('webm') ? 'webm' : 'm4a'), { type: mime });
    send({ file, url: URL.createObjectURL(blob) });
  };
  const tick = setInterval(() => {
    const s = Math.floor((Date.now() - started) / 1000);
    time.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    meter.getByteTimeDomainData(buf);
    let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
    level.style.width = Math.min(100, peak / 1.28) + '%';
    if (s >= 600) finish(true);
  }, 100);
  UI.composer.replaceChildren(h('div', { class: 'recording', role: 'group', 'aria-label': 'Recording a voice note' },
    time, h('div', { class: 'meter', 'aria-hidden': 'true' }, level),
    h('button', { onclick: () => finish(false) }, 'Cancel'), h('button', { class: 'primary', onclick: () => finish(true) }, 'Send')));
  rec.start(1000);
}

// ------------------------------------------------------------------ keeping up with the relay

async function syncLoop() {
  S.syncing = true;
  let wait = 0, failures = 0;
  while (me && S.syncing) {
    try {
      const got = await call('sync', { after: S.after, wait, seen: document.visibilityState === 'visible', known_asks: S.asks.map(a => a.ask_id) }, { timeout: 45000 });
      S.checking = false; merge(got); failures = 0; wait = document.visibilityState === 'visible' ? 25 : 0; S.asleep = false; S.online = true;
      if (document.visibilityState !== 'visible') await new Promise(r => document.addEventListener('visibilitychange', r, { once: true }));
    } catch (e) {
      if (e instanceof Gone) { S.syncing = false; return; }
      failures++;
      if (e.status >= 500) S.asleep = failures > 2; else if (!e.status) S.online = navigator.onLine && failures < 3 ? S.online : false;
      renderStatus();
      await new Promise(r => setTimeout(r, Math.min(30000, 1500 * 2 ** Math.min(failures, 5))));
      wait = 0;
    }
    S.checking = false;
  }
}

function merge(got) {
  for (const m of got.messages || []) {
    S.after = Math.max(S.after, m.id);
    const mine = m.msg_id && m.role === 'user' ? S.messages.find(x => x.msg_id === m.msg_id) : null;
    if (m.status === 'queued' && m.msg_id) S.queued.add(m.msg_id);
    if (mine) { Object.assign(mine, { id: m.id, status: m.status, files: m.files?.length ? m.files : mine.files }); mine.local = null; continue; }
    const known = S.messages.find(x => x.id === m.id);
    if (known) Object.assign(known, m); else S.messages.push(m);
  }
  // A status change to an earlier message comes back with the next message, so recent ones are kept in step.
  for (const m of got.messages || []) if (m.role === 'assistant' && m.reply_to) {
    const asked = S.messages.find(x => x.msg_id === m.reply_to && x.role === 'user');
    if (asked && (m.tags || []).includes('done')) asked.status = 'done';
    else if (asked && asked.status === 'received' && (m.tags || []).includes('offline')) asked.status = 'answered_here';
  }
  S.messages.sort((a, b) => (a.id ?? Infinity) - (b.id ?? Infinity));
  if (S.messages.length > KEEP) S.messages.splice(0, S.messages.length - KEEP);
  const before = new Set(S.asks.map(a => a.ask_id));
  S.asks = got.asks || [];
  for (const id of before) if (!S.asks.some(a => a.ask_id === id) && !S.answered[id]) S.answered[id] = { at: Date.now(), show: true, text: 'Answered on your computer.' };
  if (got.computer) S.computer = got.computer;
  S.offlineAnswers = !!got.offline_answers;
  kv('after', S.after).catch(() => {}); saveMessages();
  const asksNow = S.asks.map(a => a.ask_id).join(',');
  renderStatus(); renderMessages(); if (asksNow !== S.shownAsks) { S.shownAsks = asksNow; renderAsk(); } renderModes();
  if (!S.files.length && !UI.field?.value) renderComposerButtons();
}

// ------------------------------------------------------------------ settings

async function showSettings() {
  const settings = (await kv('settings').catch(() => null)) || {};
  const push = 'Notification' in window && Notification.permission === 'granted';
  const sizeSel = h('select', { id: 'size', onchange: async () => { settings.size = sizeSel.value; document.documentElement.dataset.size = sizeSel.value; await kv('settings', settings); } },
    ...['small', 'normal', 'large'].map(v => h('option', { value: v, selected: (settings.size || 'normal') === v }, v[0].toUpperCase() + v.slice(1))));
  const pushRow = push ? h('span', { class: 'muted' }, 'On')
    : h('button', { onclick: async () => { pushRow.replaceWith(h('span', { class: 'muted' }, (await turnOnPush()) ? 'On' : 'Notifications are off. You can turn them on in Settings.')); } }, 'Turn on');
  sheet(h('h2', {}, 'Settings'),
    h('div', { class: 'setting' }, h('span', {}, 'This phone'), h('span', { class: 'muted' }, me?.name || '')),
    h('div', { class: 'setting' }, h('span', {}, 'Notifications'), pushRow),
    h('div', { class: 'setting' }, h('label', { for: 'size' }, 'Text size'), sizeSel),
    h('p', { class: 'muted' }, 'Messages from this chat are kept on the relay in your own Supabase project for 7 days at most. Private notes never leave your computer.'),
    h('button', { class: 'danger', onclick: async () => {
      if (!confirm('Unpair this phone? This erases JARVIS’s messages from this phone.')) return;
      try { await call('leave'); } catch {}
      S.syncing = false; await wipe(); document.querySelector('.sheet')?.shut?.(); showPair();
    } }, 'Unpair this phone'),
    h('p', { class: 'muted' }, 'Erases JARVIS’s messages from this phone.'));
}

start();
