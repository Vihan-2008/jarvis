// The Routines panel (jcc/static/nova-routines.js). A stand-in page: no browser, no screen, nothing sent.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../jcc/static/nova-routines.js'), 'utf8');
const EVIL = '<img src=x onerror=alert(1)>', SCRIPT = '"><script>alert(2)</script>';

class Node {
  constructor(html = '') {
    this.dataset = {}; this.kids = new Map(); this.handlers = {}; this.html = html; this.value = ''; this.checked = false; this.hidden = false; this.scrollTop = 99; this.isConnected = true;
    this.classList = { contains: c => c === 'hidden' && this.hidden, add: () => {}, remove: () => {} };
  }
  set innerHTML(v) { this.html = String(v); } get innerHTML() { return this.html; }
  querySelector(sel) { if (!this.kids.has(sel)) this.kids.set(sel, new Node()); return this.kids.get(sel); }
  querySelectorAll() { return []; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  append() {} focus() {}
}

function setup(answers, yes = true) {
  const panes = [], calls = [], said = [], opened = [], asked = [];
  const Nova = { icon: name => '<svg data-i="' + name + '"></svg>', el: (tag, attrs, html) => new Node(html), notify: text => said.push(text),
                 confirmBox: async what => { asked.push(what.title); return typeof yes === 'function' ? yes(what) : yes; }, registerPane: def => panes.push(def), panel: new Node(),
                 openPane: id => opened.push('pane:' + id) };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const api = async (address, body) => { calls.push([address, body]); const answer = answers[body.action]; if (answer instanceof Error) throw answer; return typeof answer === 'function' ? answer(body) : answer; };
  const context = { window: { Nova }, api, esc, toast: text => said.push('toast: ' + text), openChat: async id => opened.push('chat:' + id), setTimeout: () => 0, clearTimeout: () => {}, console, isFinite, Date, Set, Number };
  vm.createContext(context); vm.runInContext(code, context);
  const pane = panes.find(p => p.id === 'routines'), box = pane.node.querySelector('#nv-rt-body'), form = pane.node.querySelector('#nv-rt-form');
  const click = async button => { for (const fn of pane.node.handlers.click) await fn({ target: { closest: () => ({ dataset: {}, ...button }) } }); };
  const field = (id, value) => { form.querySelector(id).value = value; };
  return { panes, calls, said, opened, asked, pane, box, form, click, field, actions: () => calls.map(c => c[1].action), sent: action => calls.filter(c => c[1].action === action).map(c => c[1]) };
}
const inert = html => { assert.ok(!/<img|<script/i.test(html), html.slice(0, 400)); assert.ok(!html.includes('"><script'), 'not even half a tag'); };

const ID = 'rt-20261116-090000-abcd';
const run = more => ({ slot: 1, started: 1763280000, job: '20261116-000001-abcd', status: 'started', note: EVIL, state: 'done', ...more });
const routine = more => ({ id: ID, name: EVIL, what: SCRIPT, project: 'calc', mode: 'build', agent: EVIL, schedule: { kind: 'daily', at: '17:30', days: [0, 3] }, enabled: true,
  next: Date.now() / 1000 + 600, chat: '20261116-090000-cafe', in_words: EVIL, state: 'scheduled', can_cancel: false, can_retry: false, last: run(), runs: [run({ manual: true }), run({ state: SCRIPT })], ...more });
const LIST = more => ({ routines: [routine(more)], projects: [{ key: 'calc', name: EVIL }], agents: [EVIL, 'claude'], said: '' });

test('the panel is offered with a clock', () => {
  const s = setup({});
  assert.deepEqual(s.panes.map(p => [p.id, p.label, p.icon]), [['routines', 'Routines', 'clock']]);
  assert.ok(s.pane.tip && typeof s.pane.show === 'function');
});

test('no routines: one sentence says what a routine is, with two examples', async () => {
  const s = setup({ list: { routines: [], projects: [], agents: [] } });
  await s.pane.show();
  assert.match(s.box.innerHTML, /No routines yet/);
  assert.match(s.box.innerHTML, /every morning at 8, tell me what is on my calendar/);
  assert.match(s.box.innerHTML, /every 2 hours, run the tests of my project and fix what fails/);
  assert.match(s.box.innerHTML, /id="nv-rt-new"/);
});

test('hostile words in every field stay words, in the list and in the form', async () => {
  const s = setup({ list: LIST({ last: run({ state: 'failed', note: SCRIPT }) }) });
  await s.pane.show();
  const html = s.box.innerHTML;
  inert(html);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/, 'shown as text');
  assert.match(html, /Next: in 10 minutes/);
  assert.match(html, /Last run: Failed/);
  assert.match(html, /<details class="nv-wk-hand nv-rt-runs"><summary><b>Latest runs<\/b> <span class="nv-wk-n">2<\/span>/);
  assert.match(html, /started by you/);
  await s.click({ dataset: { act: 'edit', id: ID } });
  inert(s.form.innerHTML);
  assert.match(s.form.innerHTML, /Change the routine/);
  assert.match(s.form.innerHTML, /<textarea id="nv-rt-what"[^>]*>&quot;&gt;&lt;script&gt;/);
  assert.match(s.form.innerHTML, /id="nv-rt-day-0" checked/); assert.match(s.form.innerHTML, /id="nv-rt-day-3" checked/); assert.match(s.form.innerHTML, /id="nv-rt-day-1">/);
  assert.match(s.form.innerHTML, /value="17:30"/);
});

test('the form checks what it is given before anything is sent', async () => {
  const s = setup({ list: { routines: [], projects: [{ key: 'calc', name: 'Calc' }], agents: ['claude'] }, save: { routines: [], said: 'Saved.' } });
  await s.pane.show();
  await s.click({ id: 'nv-rt-new' });
  assert.match(s.form.innerHTML, /New routine/); assert.match(s.form.innerHTML, /Answer me in a chat/); assert.match(s.form.innerHTML, /Change code in the project/);
  assert.ok(!/id="nv-rt-new"/.test(s.box.innerHTML), 'one form at a time');
  const fill = { '#nv-rt-name': 'Tests', '#nv-rt-what': 'Run the tests and fix what fails.', '#nv-rt-project': '', '#nv-rt-mode': 'ask', '#nv-rt-agent': 'auto',
                 '#nv-rt-kind': 'every', '#nv-rt-count': '2', '#nv-rt-unit': 'hours', '#nv-rt-at': '08:00' };
  const tryWith = async (changes, words) => {
    for (const [id, value] of Object.entries({ ...fill, ...changes })) s.field(id, value);
    s.said.length = 0;
    await s.click({ id: 'nv-rt-save' });
    assert.ok(s.said.some(t => t.startsWith('toast: ') && words.test(t)), String(words) + ' ' + s.said);
    assert.deepEqual(s.sent('save'), [], 'nothing sent');
  };
  await tryWith({ '#nv-rt-name': '  ' }, /a name/);
  await tryWith({ '#nv-rt-name': 'x'.repeat(81) }, /80 characters/);
  await tryWith({ '#nv-rt-what': 'hi' }, /what JARVIS should do/);
  await tryWith({ '#nv-rt-mode': 'build' }, /Changing code needs a project/);
  await tryWith({ '#nv-rt-count': '2', '#nv-rt-unit': 'minutes' }, /every 5 minutes and once a week/);
  await tryWith({ '#nv-rt-count': '8', '#nv-rt-unit': 'days' }, /every 5 minutes and once a week/);
  await tryWith({ '#nv-rt-count': '1.5' }, /every 5 minutes and once a week/);
  await tryWith({ '#nv-rt-kind': 'daily', '#nv-rt-at': '25:00' }, /hours and minutes/);
  for (const [id, value] of Object.entries(fill)) s.field(id, value);
  await s.click({ id: 'nv-rt-save' });
  assert.equal(JSON.stringify(s.sent('save')), JSON.stringify([{ action: 'save', routine: { name: 'Tests', what: 'Run the tests and fix what fails.', project: '', mode: 'ask', agent: 'auto', schedule: { kind: 'every', minutes: 120 } } }]));
  assert.ok(s.said.includes('Saved.'));
  assert.equal(s.form.innerHTML, '', 'the form closes once saved');
  await s.click({ id: 'nv-rt-new' });
  for (const [id, value] of Object.entries({ ...fill, '#nv-rt-kind': 'daily', '#nv-rt-at': '17:30', '#nv-rt-project': 'calc', '#nv-rt-mode': 'build' })) s.field(id, value);
  s.form.querySelector('#nv-rt-day-0').checked = true; s.form.querySelector('#nv-rt-day-3').checked = true;
  await s.click({ id: 'nv-rt-save' });
  assert.equal(JSON.stringify(s.sent('save')[1].routine.schedule), JSON.stringify({ kind: 'daily', at: '17:30', days: [0, 3] }));
  assert.equal(s.sent('save')[1].routine.mode, 'build');
});

test('a change is saved under the routine it changes', async () => {
  const s = setup({ list: LIST(), save: { routines: [], said: 'Saved.' } });
  await s.pane.show();
  await s.click({ dataset: { act: 'edit', id: ID } });
  for (const [id, value] of Object.entries({ '#nv-rt-name': 'Tests', '#nv-rt-what': 'Run them.', '#nv-rt-project': 'calc', '#nv-rt-mode': 'build', '#nv-rt-agent': 'claude', '#nv-rt-kind': 'daily', '#nv-rt-at': '09:00' })) s.field(id, value);
  await s.click({ id: 'nv-rt-save' });
  assert.equal(s.sent('save')[0].routine.id, ID);
});

test('each button sends exactly its own action for its own routine', async () => {
  for (const [act, more] of [['pause', {}], ['resume', { enabled: false }], ['run', {}], ['cancel', { state: 'running', can_cancel: true }], ['retry', { state: 'failed', can_retry: true }]]) {
    const s = setup({ list: LIST(more), [act]: { routines: [], said: 'Done.' } });
    await s.pane.show();
    await s.click({ dataset: { act, id: ID } });
    assert.equal(JSON.stringify(s.sent(act)), JSON.stringify([{ action: act, id: ID }]), act);
    assert.deepEqual(s.actions().filter(a => a !== 'list'), [act], act);
  }
  const s = setup({ list: LIST() });
  await s.pane.show();
  await s.click({ dataset: { act: 'chat', id: ID } });
  assert.deepEqual(s.opened, ['chat:20261116-090000-cafe']);
  await s.click({ dataset: { act: 'run', id: 'rt-20261116-090000-ffff' } });
  assert.deepEqual(s.actions(), ['list'], 'a routine that is not in the list is not acted on');
});

test('Cancel is offered only while a run is going, and Retry only after one failed', async () => {
  const offered = async more => { const s = setup({ list: LIST(more) }); await s.pane.show(); return s.box.innerHTML; };
  let html = await offered({});
  assert.ok(!/data-act="cancel"/.test(html)); assert.ok(!/data-act="retry"/.test(html)); assert.match(html, /data-act="run"/); assert.match(html, /data-act="pause"/);
  assert.match(html, /data-state="scheduled">Scheduled</);
  html = await offered({ state: 'running', can_cancel: true });
  assert.match(html, /data-act="cancel"/); assert.ok(!/data-act="run"/.test(html), 'no second run on top of one that is going'); assert.match(html, />Running</);
  html = await offered({ state: 'waiting', can_cancel: true });
  assert.match(html, /Waiting for you/); assert.match(html, /data-act="cancel"/);
  html = await offered({ state: 'failed', can_retry: true });
  assert.match(html, /data-act="retry"/); assert.ok(!/data-act="cancel"/.test(html)); assert.match(html, />Failed</);
  html = await offered({ state: 'paused', enabled: false });
  assert.match(html, /data-act="resume"/); assert.ok(!/data-act="pause"/.test(html)); assert.ok(!/Next:/.test(html), 'a paused routine has no next run');
  html = await offered({ chat: '' });
  assert.ok(!/data-act="chat"/.test(html), 'no chat before its first run');
});

test('Remove asks first', async () => {
  let yes = false;
  const s = setup({ list: LIST(), remove: { routines: [], said: 'Removed.' } }, () => yes);
  await s.pane.show();
  await s.click({ dataset: { act: 'remove', id: ID } });
  assert.equal(s.asked.length, 1); assert.deepEqual(s.sent('remove'), [], 'nothing removed without a yes');
  yes = true;
  await s.click({ dataset: { act: 'remove', id: ID } });
  assert.equal(JSON.stringify(s.sent('remove')), JSON.stringify([{ action: 'remove', id: ID }]));
});

test('an error from the app is told, not thrown', async () => {
  const s = setup({ list: LIST(), run: new Error('The last run is still going.') });
  await s.pane.show();
  await s.click({ dataset: { act: 'run', id: ID } });
  assert.ok(s.said.includes('toast: The last run is still going.'));
});
