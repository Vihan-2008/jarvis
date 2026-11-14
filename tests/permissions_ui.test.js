// The permissions control beside the message box (jcc/static/nova-permissions.js). A stand-in page: no browser, no screen, nothing sent.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../jcc/static/nova-permissions.js'), 'utf8');
const EVIL = '<img src=x onerror=alert(1)>', SCRIPT = '"><script>alert(2)</script>';

class Node {
  constructor(html = '') {
    this.dataset = {}; this.kids = new Map(); this.handlers = {}; this.html = html; this.value = ''; this.attrs = {}; this.appended = []; this.classes = new Set(); this.textContent = '';
    this.classList = { contains: c => this.classes.has(c), add: c => this.classes.add(c), remove: c => this.classes.delete(c), toggle: (c, on) => (on ? this.classes.add(c) : this.classes.delete(c)) };
  }
  set innerHTML(v) { this.html = String(v); if (!this.html) this.appended = []; } get innerHTML() { return this.html; }
  querySelector(sel) { if (!this.kids.has(sel)) this.kids.set(sel, new Node()); return this.kids.get(sel); }
  querySelectorAll() { return []; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k] ?? null; }
  append(...nodes) { this.appended.push(...nodes); } after(node) { this.afterNode = node; } prepend(node) { this.prepended = node; }
  get text() { return this.html + this.appended.map(n => (n && n.text) || '').join(''); }       // everything drawn into it
}

const STATE = more => ({ mode: 'sending', more: 0,
  modes: [{ id: 'sending', name: 'Ask before sending, deleting or paying', about: 'Recommended.' }, { id: 'risky', name: 'Also ask before risky things', about: EVIL }, { id: 'all', name: 'Ask before everything', about: 'Every action.' }],
  pending: [], ...more });
const ASSISTANT = { kind: 'assistant', id: 'a1b2c3', question: 'Shall I send this email to ' + EVIL + '?', detail: 'Subject: ' + SCRIPT, chat: 'chat-1', why: 'It reaches other people.' };
const JOB = { kind: 'job', id: '20261114-010101-abcd', question: 'A coding job stopped and asks you', detail: 'May I change the deploy script? ' + EVIL, mark: '4cc910b57d7c4268', title: SCRIPT, project: 'Site', chat: 'chat-2' };
const REVIEW = { kind: 'review', id: '20261114-010102-abcd', question: 'A change is waiting for you to look at it', detail: '', title: 'Add a page', project: 'Site', chat: 'chat-3' };

function setup(states, yes = true) {
  const calls = [], said = [], opened = [], asked = [], items = [], timers = [];
  let pop = null, at = 0;
  const bar = new Node(); bar.children = [new Node(), new Node()];
  const document = { visibilityState: 'visible', querySelector: sel => sel === '.nv-bar' ? bar : sel === '.nv-pop' ? pop : null };
  const button = { node: null };
  const Nova = { icon: name => '<svg data-i="' + name + '"></svg>', el: (tag, attrs = {}, html = '') => { const n = new Node(html); n.tag = tag; n.cls = attrs.class || ''; return n; },
    notify: text => said.push(text), confirmBox: async what => { asked.push(what.title); return yes; },
    openPop: (anchor, fill) => { if (pop) { pop = null; anchor.setAttribute('aria-expanded', 'false'); return; } pop = new Node(); anchor.setAttribute('aria-expanded', 'true'); fill(pop); },
    closePop: () => { if (pop) { pop = null; button.node.setAttribute('aria-expanded', 'false'); } },
    item: (parent, labelText, iconName, action, extra = {}) => { items.push({ label: labelText, action, ...extra }); return new Node(); },
    openPane: id => opened.push('pane:' + id) };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const api = async (address, body) => {
    calls.push([address, body]);
    if (body.action === 'state') { const answer = typeof states === 'function' ? states(at++) : states; if (answer instanceof Error) throw answer; return answer; }
    const answer = (states.answers || {})[body.action]; if (answer instanceof Error) throw answer; return answer || {};
  };
  const context = { window: { Nova }, document, api, esc, toast: text => said.push('toast: ' + text), openChat: async id => opened.push('chat:' + id),
    setTimeout: (fn, ms) => { timers.push(ms); return timers.length; }, clearTimeout: () => {}, console, JSON, Math, Number, String };
  vm.createContext(context); vm.runInContext(code, context);
  button.node = bar.children[1].afterNode;
  const press = async (kind, id, how, mark = '', words = '', chat = '') => {
    const buttons = [{ disabled: false }, { disabled: false }];
    const box = { dataset: { kind, id, mark, chat }, querySelector: () => ({ value: words }), querySelectorAll: () => buttons };
    const b = { dataset: { [how]: '' }, closest: sel => sel === 'button' ? b : box };
    for (const fn of pop.handlers.click || []) await fn({ target: { closest: () => b } });
    await new Promise(resolve => setImmediate(resolve));
    return buttons;
  };
  const settle = () => new Promise(resolve => setImmediate(resolve));
  return { calls, said, opened, asked, items, timers, bar, button: button.node, pop: () => pop, press, settle, Nova, actions: () => calls.map(c => c[1].action) };
}
const same = (a, b, why) => assert.equal(JSON.stringify(a), JSON.stringify(b), why);        // (values made in another context compare by what they hold)
const inert = html => { assert.ok(!/<img|<script/i.test(html), html.slice(0, 400)); };

test('the control sits beside the message box and says the mode in force', async () => {
  const s = setup(STATE());
  await s.settle();
  assert.ok(s.button, 'it is put into the bar, after the options button');
  assert.equal(s.button.querySelector('.nv-perm-name').textContent, 'Asks before sending');
  assert.ok(s.button.querySelector('.nv-perm-n').classes.has('hidden'), 'no number when nothing is waiting');
  assert.ok(!s.button.classes.has('waiting'));
  assert.match(s.button.dataset.tip, /Nothing is waiting for you/);
  same(s.calls[0], ['/api/permissions', { action: 'state' }]);
  assert.equal(s.timers.at(-1), 6000, 'with nothing waiting it asks again slowly');
});

test('what is waiting is counted on the control, and it asks again sooner', async () => {
  const s = setup(STATE({ pending: [ASSISTANT, JOB], more: 3 }));
  await s.settle();
  assert.equal(s.button.querySelector('.nv-perm-n').textContent, '5');
  assert.ok(!s.button.querySelector('.nv-perm-n').classes.has('hidden')); assert.ok(s.button.classes.has('waiting'));
  assert.match(s.button.dataset.tip, /5 things are waiting for your yes or no/);
  assert.match(s.button.attrs['aria-label'], /5 waiting for your answer/);
  assert.equal(s.timers.at(-1), 2500);
  const odd = setup(STATE({ pending: [], more: '<b>9</b>' }));
  await odd.settle();
  assert.equal(odd.button.querySelector('.nv-perm-n').textContent, '0', 'a count that is not a number is shown as none');
});

test('the menu: the three ways of asking, and hostile words in a request stay words', async () => {
  const s = setup(STATE({ mode: 'risky', pending: [ASSISTANT, JOB, REVIEW], more: 2 }));
  await s.settle();
  s.button.onclick();
  const html = s.pop().text;
  inert(html);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/, 'shown as text');
  assert.deepEqual(s.items.map(i => [i.label, !!i.tick]), [['Ask before sending, deleting or paying', false], ['Also ask before risky things', true], ['Ask before everything', false]]);
  assert.match(html, /data-kind="assistant" data-id="a1b2c3"/); assert.match(html, /data-yes>Yes</); assert.match(html, /data-no>No</);
  assert.match(html, /data-kind="job" data-id="20261114-010101-abcd" data-mark="4cc910b57d7c4268"/); assert.match(html, /Yes, carry on/); assert.match(html, /<input maxlength="2000"/);
  assert.match(html, /data-kind="review"/); assert.match(html, /data-look>Look at it</);
  assert.equal((html.match(/<input /g) || []).length, 1, 'only a job is answered with words');
  assert.match(html, /2 more are waiting/);
  assert.equal(s.button.querySelector('.nv-perm-name').textContent, 'Asks before risky things');
});

test('choosing another way of asking saves it and says so', async () => {
  let mode = 'sending';
  const states = () => STATE({ mode });
  states.answers = { mode: {} };
  const s = setup(states);
  await s.settle();
  s.button.onclick();
  s.calls.length = 0;
  await s.items.find(i => i.label === 'Ask before sending, deleting or paying').action();
  assert.deepEqual(s.actions(), [], 'the one already in force is not sent again');
  mode = 'all';
  await s.items.find(i => i.label === 'Ask before everything').action();
  same(s.calls[0], ['/api/permissions', { action: 'mode', mode: 'all' }]);
  assert.ok(s.said.some(t => /From now on: ask before everything\./.test(t)));
  assert.equal(s.button.querySelector('.nv-perm-name').textContent, 'Asks before everything');
});

test('a yes or a no to the assistant is sent once, for that question', async () => {
  const s = setup(STATE({ pending: [ASSISTANT] }));
  await s.settle();
  s.button.onclick(); s.calls.length = 0;
  const buttons = await s.press('assistant', 'a1b2c3', 'yes');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'assistant', id: 'a1b2c3', yes: true }]);
  assert.ok(buttons.every(b => b.disabled), 'the buttons go dead: one answer, once');
  assert.ok(s.said.includes('Allowed, this once.'));
  s.calls.length = 0;
  await s.press('assistant', 'a1b2c3', 'no');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'assistant', id: 'a1b2c3', yes: false }]);
  assert.equal(s.asked.length, 0, 'a no to the assistant is not asked about again');
});

test('a yes to a job carries the mark of the question on the screen, and its words', async () => {
  const s = setup(STATE({ pending: [JOB] }));
  await s.settle();
  s.button.onclick(); s.calls.length = 0;
  await s.press('job', JOB.id, 'yes', 'mark-on-the-screen', 'Yes, but only the staging one.');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'job', id: JOB.id, yes: true, text: 'Yes, but only the staging one.', mark: 'mark-on-the-screen' }]);
  assert.ok(s.said.some(t => /same job carries on/.test(t)));
  s.calls.length = 0;
  await s.press('job', JOB.id, 'no', 'mark-on-the-screen', 'Not now.');
  assert.deepEqual(s.asked, ['Say no to this?'], 'a no ends the job, so it is asked about first');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'job', id: JOB.id, yes: false, text: 'Not now.' }], 'a no needs no mark');
  const unsure = setup(STATE({ pending: [JOB] }), false);
  await unsure.settle();
  unsure.button.onclick(); unsure.calls.length = 0;
  await unsure.press('job', JOB.id, 'no');
  assert.deepEqual(unsure.actions().filter(a => a === 'decide'), [], 'no was not confirmed: nothing is sent');
});

test('an answer that is refused is said, and the list is read again', async () => {
  const states = () => STATE({ pending: [JOB] });
  states.answers = { decide: new Error('This job is asking something else now. Read its question again before you answer.') };
  const s = setup(states);
  await s.settle();
  s.button.onclick(); s.calls.length = 0;
  await s.press('job', JOB.id, 'yes', 'old-mark');
  assert.ok(s.said.includes('toast: This job is asking something else now. Read its question again before you answer.'));
  assert.deepEqual(s.actions(), ['decide', 'state'], 'the list is read again, so the question it asks now is shown');
  assert.ok(!s.said.some(t => /carries on/.test(t)));
});

test('a change that waits to be looked at only leads to where it can be seen', async () => {
  const s = setup(STATE({ pending: [REVIEW] }));
  await s.settle();
  s.button.onclick(); s.calls.length = 0;
  await s.press('review', REVIEW.id, 'look', '', '', 'chat-3');
  assert.deepEqual(s.opened, ['chat:chat-3']);
  assert.deepEqual(s.actions().filter(a => a === 'decide'), [], 'nothing is decided from here');
  const lost = setup(STATE({ pending: [REVIEW] }));
  await lost.settle();
  lost.button.onclick();
  await lost.press('review', REVIEW.id, 'look');
  assert.deepEqual(lost.opened, ['pane:agents'], 'with no chat to open, the list of all work');
});

test('when the list cannot be read it says so and keeps what it had', async () => {
  let n = 0;
  const s = setup(() => (n++ === 0 ? STATE({ pending: [ASSISTANT] }) : new Error('offline')));
  await s.settle();
  s.button.onclick();
  await s.settle();
  assert.match(s.pop().text, /could not be read just now/);
  assert.match(s.pop().text, /data-id="a1b2c3"/, 'what was waiting is still shown');
  assert.equal(s.button.querySelector('.nv-perm-n').textContent, '1');
});
