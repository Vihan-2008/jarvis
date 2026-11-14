/* NOVA Routines panel: what the owner wants done again and again, at the times they chose (jcc/routines.py). Each run
   is sent in the routine's own chat as if the owner had typed it, so every approval and review applies to it. A
   routine's name, its request, a run's note and every other saved word are data: they reach the page only through
   esc(), and every number only through num(). */
(() => {
'use strict';
const N = window.Nova; if (!N) return;
const { icon, el, notify, confirmBox, registerPane } = N;
const num = v => String(Math.round(Number(v)) || 0);
const clock = at => at ? new Date(at * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '';
const shown = node => !node.classList.contains('hidden') && node.isConnected;
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const STATE = { scheduled: 'Scheduled', running: 'Running', waiting: 'Waiting for you', failed: 'Failed', paused: 'Paused', done: 'Done' };
const RUN = { starting: 'Starting', running: 'Running', waiting: 'Waiting for you', failed: 'Failed', cancelled: 'Cancelled', done: 'Done', skipped: 'Skipped' };
const UNITS = [['minutes', 1], ['hours', 60], ['days', 1440]];
// Asks again every little while, but only while the panel is showing (as in nova-security.js).
function poller(node, draw, quick = 3000, slow = 15000) {
  let timer = 0;
  const tick = async () => { clearTimeout(timer); if (!shown(node)) return; let busy = false; try { busy = await draw(); } catch (error) { toast(error.message); } timer = setTimeout(tick, busy ? quick : slow); };
  return tick;
}

const node = el('section', { id: 'tool-nvroutines', class: 'tool-content nv-pane nv-wk hidden' },
  '<div class="tool-heading"><div><h2>Routines</h2><p>Things JARVIS does for you again and again, at the times you choose. Each run is sent in the routine’s own chat, as if you had typed it.</p></div></div>' +
  '<div id="nv-rt-form" class="nv-rt-form"></div><div id="nv-rt-body" class="nv-wk-body nv-rt"></div>');
N.panel.append(node);
const form = node.querySelector('#nv-rt-form'), box = node.querySelector('#nv-rt-body');

let info = null;          // {routines, projects, agents}
let editing = null;       // the routine being made ({}) or changed, while the form is open

// When it runs next, in words: "in 12 minutes", "today 17:30", "tomorrow 08:00", or a date.
function when(next) {
  if (!next) return '';
  const at = new Date(next * 1000), left = next - Date.now() / 1000;
  if (left < 60) return 'in under a minute';
  if (left < 3600) { const m = Math.round(left / 60); return 'in ' + num(m) + (m === 1 ? ' minute' : ' minutes'); }
  const hm = at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), today = new Date(), tomorrow = new Date(today.getTime() + 86400000);
  if (at.toDateString() === today.toDateString()) return 'today ' + hm;
  if (at.toDateString() === tomorrow.toDateString()) return 'tomorrow ' + hm;
  return clock(next);
}

function lastRun(r) {
  const run = r.last;
  if (!run) return '<small>It has not run yet.</small>';
  return '<small class="nv-rt-last" data-state="' + esc(run.state) + '">Last run: ' + esc(RUN[run.state] || run.state) + ' · ' + esc(clock(run.started)) + (run.note ? ' · ' + esc(run.note) : '') + '</small>';
}

function runs(r) {
  const list = (r.runs || []).slice().reverse();
  if (!list.length) return '';
  return '<details class="nv-wk-hand nv-rt-runs"><summary><b>Latest runs</b> <span class="nv-wk-n">' + num(list.length) + '</span></summary><ul>' + list.map(run =>
    '<li data-state="' + esc(run.state) + '"><span>' + esc(clock(run.started)) + (run.manual ? ' · started by you' : '') + '</span><span class="nv-wk-pill" data-state="' + esc(run.state) + '">' + esc(RUN[run.state] || run.state) + '</span>' +
    (run.note ? '<small>' + esc(run.note) + '</small>' : '') + '</li>').join('') + '</ul></details>';
}

function buttons(r) {
  const b = (act, glyph, words, cls = 'plain') => '<button class="' + cls + '" type="button" data-act="' + act + '" data-id="' + esc(r.id) + '">' + icon(glyph) + words + '</button>';
  return '<div class="settings-buttons nv-rt-actions">' + (r.enabled ? b('pause', 'stop', 'Pause') : b('resume', 'retry', 'Resume')) +
    (r.can_cancel ? b('cancel', 'stop', 'Cancel run') : b('run', 'spark', 'Run now')) + (r.can_retry ? b('retry', 'retry', 'Retry') : '') +
    (r.chat ? b('chat', 'chat', 'Open its chat') : '') + b('edit', 'edit', 'Change') + b('remove', 'trash', 'Remove') + '</div>';
}

function row(r) {
  const project = (info.projects.find(p => p.key === r.project) || {}).name || r.project;
  return '<div class="nv-rt-item" data-state="' + esc(r.state) + '"><div class="nv-rt-top"><span class="nv-wk-ico">' + icon('clock') + '</span><span class="nv-wk-main"><b>' + esc(r.name) + '</b>' +
    '<small>' + esc(r.in_words) + (r.enabled && r.next ? ' · Next: ' + esc(when(r.next)) : '') + (project ? ' · ' + esc(project) : '') + (r.mode === 'build' ? ' · changes code' : ' · answers in a chat') + '</small>' +
    lastRun(r) + '</span><span class="nv-wk-pill" data-state="' + esc(r.state) + '">' + esc(STATE[r.state] || r.state) + '</span></div>' + buttons(r) + runs(r) + '</div>';
}

function render() {
  if (!info) return;
  const head = editing ? '' : '<div class="settings-buttons nv-rt-head"><button class="primary" type="button" id="nv-rt-new">' + icon('plus') + 'New routine</button></div>';
  const list = info.routines.length ? info.routines.map(row).join('') :
    '<div class="nv-blank"><div><b>No routines yet.</b><br>A routine is something JARVIS does for you again and again, at the times you choose: for example “every morning at 8, tell me what is on my calendar”, or “every 2 hours, run the tests of my project and fix what fails”.</div></div>';
  const html = head + list;
  if (box.dataset.sig !== html) { box.dataset.sig = html; box.innerHTML = html; }
}

/* ---------- the form: make a routine, or change one ---------- */
function split(minutes) {
  for (const [unit, size] of UNITS.slice().reverse()) if (minutes % size === 0) return [minutes / size, unit];
  return [minutes, 'minutes'];
}
function drawForm() {
  if (!editing) { form.innerHTML = ''; return; }
  const r = editing, s = r.schedule || { kind: 'daily', at: '08:00', days: [] }, every = s.kind === 'every';
  const [count, unit] = every ? split(Number(s.minutes) || 60) : [1, 'hours'];
  const days = new Set(every ? [] : s.days || []);
  const option = (value, words, chosen) => '<option value="' + esc(value) + '"' + (value === chosen ? ' selected' : '') + '>' + esc(words) + '</option>';
  form.innerHTML = '<div class="settings-box nv-wk-new nv-rt-edit"><h3>' + (r.id ? 'Change the routine' : 'New routine') + '</h3>' +
    '<label>Name<input id="nv-rt-name" maxlength="80" value="' + esc(r.name || '') + '" placeholder="Morning calendar"></label>' +
    '<label>What to do<textarea id="nv-rt-what" rows="4" maxlength="4000" placeholder="Tell me what is on my calendar today, and anything I should prepare for.">' + esc(r.what || '') + '</textarea></label>' +
    '<div class="nv-wk-two"><label>Project<select id="nv-rt-project">' + option('', 'None', r.project || '') + info.projects.map(p => option(p.key, p.name, r.project || '')).join('') + '</select></label>' +
    '<label>What kind<select id="nv-rt-mode">' + option('ask', 'Answer me in a chat', r.mode || 'ask') + option('build', 'Change code in the project', r.mode || 'ask') + '</select></label></div>' +
    '<label>Which agent<select id="nv-rt-agent">' + option('auto', 'Auto', r.agent || 'auto') + info.agents.map(a => option(a, a, r.agent || 'auto')).join('') + '</select></label>' +
    '<label>When<select id="nv-rt-kind">' + option('every', 'Every so often', every ? 'every' : 'daily') + option('daily', 'Every day at a time', every ? 'every' : 'daily') + '</select></label>' +
    '<div class="nv-rt-when"><span>Every</span><input id="nv-rt-count" type="number" min="1" max="10080" value="' + num(count) + '" aria-label="How many">' +
    '<select id="nv-rt-unit" aria-label="Minutes, hours or days">' + UNITS.map(([u]) => option(u, u, unit)).join('') + '</select>' +
    '<span>or every day at</span><input id="nv-rt-at" type="time" value="' + esc(every ? '08:00' : s.at || '08:00') + '" aria-label="Time of day"></div>' +
    '<div class="nv-rt-days"><span class="small">On these days (none ticked: every day)</span>' + DAYS.map((d, i) => '<label><input type="checkbox" id="nv-rt-day-' + i + '"' + (days.has(i) ? ' checked' : '') + '>' + d + '</label>').join('') + '</div>' +
    '<p class="small">A routine never has more rights than a message you type: anything that needs your yes waits for it.</p>' +
    '<div class="settings-buttons"><button class="plain" type="button" id="nv-rt-close">Cancel</button><button class="primary" type="button" id="nv-rt-save">' + icon('check') + 'Save</button></div></div>';
}

// What the form says, checked as the app will check it, with a plain sentence for what is missing.
const refuse = text => { toast(text); return null; };
function collect() {
  const value = id => String(form.querySelector(id).value || '');
  const name = value('#nv-rt-name').trim(), what = value('#nv-rt-what').trim(), project = value('#nv-rt-project'), mode = value('#nv-rt-mode') || 'ask';
  if (!name || name.length > 80) return refuse('Give the routine a name of up to 80 characters.');
  if (what.length < 3) return refuse('Say what JARVIS should do, in a few words at least.');
  if (what.length > 4000) return refuse('Say what to do in up to 4,000 characters.');
  if (mode === 'build' && !project) return refuse('Changing code needs a project. Choose one, or have it answer you in a chat.');
  let schedule;
  if (value('#nv-rt-kind') === 'every') {
    const count = Number(value('#nv-rt-count')), size = (UNITS.find(u => u[0] === value('#nv-rt-unit')) || UNITS[1])[1], minutes = count * size;
    if (!Number.isInteger(count) || count < 1 || minutes < 5 || minutes > 10080) return refuse('Choose between every 5 minutes and once a week.');
    schedule = { kind: 'every', minutes };
  } else {
    const at = value('#nv-rt-at');
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(at)) return refuse('Give the time as hours and minutes, like 08:00.');
    schedule = { kind: 'daily', at, days: DAYS.map((_, i) => i).filter(i => form.querySelector('#nv-rt-day-' + i).checked) };
  }
  return { ...(editing.id ? { id: editing.id } : {}), name, what, project, mode, agent: value('#nv-rt-agent') || 'auto', schedule };
}

const draw = async () => {
  info = await api('/api/routines', { action: 'list' });
  render();
  return info.routines.some(r => r.state === 'running' || r.state === 'waiting');
};
const poll = poller(node, draw);
const send = async (body) => { const got = await api('/api/routines', body); if (got && got.said) notify(got.said); return got; };

node.addEventListener('click', async e => {
  const at = e.target.closest('button'); if (!at) return;
  const routine = at.dataset.id ? (info.routines.find(r => r.id === at.dataset.id) || null) : null;
  try {
    if (at.id === 'nv-rt-new') { editing = {}; drawForm(); render(); return; }
    if (at.id === 'nv-rt-close') { editing = null; drawForm(); render(); return; }
    if (at.id === 'nv-rt-save') {
      const routine = collect(); if (!routine) return;
      at.disabled = true;
      await send({ action: 'save', routine });
      editing = null; drawForm();
    }
    else if (!routine) return;
    else if (at.dataset.act === 'chat') { return void openChat(routine.chat).catch(error => toast(error.message)); }
    else if (at.dataset.act === 'edit') { editing = routine; drawForm(); render(); node.scrollTop = 0; return; }
    else if (at.dataset.act === 'remove') {
      if (!(await confirmBox({ title: 'Remove this routine?', ok: 'Remove', danger: true, text: 'It will not run again. Its chat and what it has done stay where they are.' }))) return;
      at.disabled = true; await send({ action: 'remove', id: routine.id });
    }
    else if (['pause', 'resume', 'run', 'cancel', 'retry'].includes(at.dataset.act)) { at.disabled = true; await send({ action: at.dataset.act, id: routine.id }); }
    else return;
    box.dataset.sig = ''; await poll();
  } catch (error) { at.disabled = false; toast(error.message); }
});

registerPane({ id: 'routines', label: 'Routines', icon: 'clock', node, tip: 'Things JARVIS does for you again and again, at the times you choose',
  show: async () => { box.dataset.sig = ''; await poll(); node.scrollTop = 0; } });
})();
