// The mode chip in the message bar and the cards in the chat (jcc/static/nova-permissions.js). A stand-in page: no
// browser, no screen, nothing sent.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../jcc/static/nova-permissions.js'), 'utf8');
const EVIL = '<img src=x onerror=alert(1)>', SCRIPT = '"><script>alert(2)</script>';

class Node {
  constructor(html = '') {
    this.dataset = {}; this.kids = new Map(); this.handlers = {}; this.html = html; this.value = ''; this.attrs = {}; this.appended = []; this.classes = new Set(); this.textContent = '';
    this.classList = { contains: c => this.classes.has(c), add: c => this.classes.add(c), remove: c => this.classes.delete(c), toggle: (c, on) => (on ? this.classes.add(c) : this.classes.delete(c)) };
  }
  set innerHTML(v) { this.html = String(v); this.kids = new Map(); if (!this.html) this.appended = []; } get innerHTML() { return this.html; }
  querySelector(sel) { if (!this.kids.has(sel)) this.kids.set(sel, new Node()); return this.kids.get(sel); }
  querySelectorAll() { return []; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k] ?? null; }
  append(...nodes) { this.appended.push(...nodes); } after(node) { this.afterNode = node; } prepend(node) { this.prepended = node; }
  get text() { return this.html + this.appended.map(n => (n && n.text) || '').join(''); }       // everything drawn into it
}

const MODES = [{ id: 'sending', name: 'Auto', about: 'JARVIS decides.' }, { id: 'all', name: 'Manual', about: 'Always ask.' }, { id: 'edits', name: 'Accept edits', about: EVIL },
  { id: 'plan', name: 'Plan', about: 'Plan first.' }, { id: 'bypass', name: 'Bypass permissions', about: 'Never ask.' }];
const STATE = more => ({ mode: 'sending', more: 0, modes: MODES, pending: [], ...more });
const ASSISTANT = { kind: 'assistant', id: 'a1b2c3', question: 'Shall I send this email to ' + EVIL + '?', detail: 'Subject: ' + SCRIPT, chat: 'chat-1', why: 'It reaches other people.' };
const JOB = { kind: 'job', id: '20261114-010101-abcd', question: 'The coding job has a question for you', detail: 'May I change the deploy script? ' + EVIL, mark: '4cc910b57d7c4268', title: SCRIPT, project: 'Site', chat: 'chat-2' };
const REVIEW = { kind: 'review', id: '20261114-010102-abcd', question: 'Keep these changes?', detail: '', title: 'Add a page', project: 'Site', chat: 'chat-1' };
const HELD = { kind: 'blocked', id: '20261114-010103-abcd', question: 'Go ahead with this?', detail: 'It mentions deploying.', can: true, title: 'Ship it', chat: 'chat-1' };
const NEVER = { kind: 'blocked', id: '20261114-010104-abcd', question: 'A coding job may never do this', detail: 'It involves money.', can: false, title: 'Buy it', chat: 'chat-1' };

function setup(states, { yes = true, open = 'chat-1' } = {}) {
  const calls = [], said = [], opened = [], asked = [], items = [], timers = [], clicks = [];
  let pop = null, at = 0;
  const bar = new Node(); bar.children = [new Node(), new Node()];
  const document = { visibilityState: 'visible', body: new Node(), querySelector: sel => sel === '.nv-bar' ? bar : sel === '.nv-pop' ? pop : null,
    addEventListener: (name, fn) => { if (name === 'click') clicks.push(fn); }, getElementById: () => null };
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
    if (address.startsWith('/api/job/details')) return states.details || { files: ['index.html'], diff: '+<b>new</b>\n-old\n', revision: 'abc1234def' };
    if (body.action === 'state') { const answer = typeof states === 'function' ? states(at++) : states; if (answer instanceof Error) throw answer; return answer; }
    const answer = (states.answers || {})[body.action]; if (answer instanceof Error) throw answer; return answer || {};
  };
  const context = { window: { Nova }, document, api, esc, toast: text => said.push('toast: ' + text), openChat: async id => opened.push('chat:' + id), current: open,
    setTimeout: (fn, ms) => { timers.push(ms); return timers.length; }, clearTimeout: () => {}, console, JSON, Math, Number, String, encodeURIComponent };
  vm.createContext(context); vm.runInContext(code, context);
  button.node = bar.children[1].afterNode;
  // A card as the page would have it: its data, its input, its buttons; pressing one goes through the page's own click handler.
  const card = (r, words = '') => {
    const buttons = { yes: { dataset: { yes: '' }, disabled: false }, no: { dataset: { no: '' }, disabled: false } };
    const node = { dataset: { kind: r.kind, id: r.id, mark: r.mark || '', chat: r.chat || '' }, removed: false, remove() { this.removed = true; },
      querySelector: sel => sel === 'input' ? { value: words } : sel === '[data-changes]' ? { set innerHTML(v) { node.changes = v; }, set textContent(v) { node.changes = v; }, insertAdjacentHTML() {} } : sel === '[data-yes]' ? buttons.yes : null,
      querySelectorAll: () => [buttons.yes, buttons.no] };
    for (const b of Object.values(buttons)) b.closest = sel => sel === '.nv-next' ? node : null;
    node.press = async which => { for (const fn of clicks) fn({ target: { closest: sel => sel === '.nv-next button' ? buttons[which] : null } }); for (let i = 0; i < 6; i++) await new Promise(r => setImmediate(r)); };
    node.buttons = buttons;
    return node;
  };
  const settle = () => new Promise(resolve => setImmediate(resolve));
  return { calls, said, opened, asked, items, timers, bar, button: button.node, pop: () => pop, settle, Nova, card, actions: () => calls.map(c => c[1].action) };
}
const same = (a, b, why) => assert.equal(JSON.stringify(a), JSON.stringify(b), why);        // (values made in another context compare by what they hold)
const inert = html => { assert.ok(!/<img|<script/i.test(html), html.slice(0, 400)); };

test('the chip sits in the message bar and says the mode in force, as Claude Code does', async () => {
  const s = setup(STATE());
  await s.settle();
  assert.ok(s.button, 'it is put into the bar, after the options button');
  assert.equal(s.button.querySelector('.nv-perm-name').textContent, 'Auto');
  assert.ok(s.button.querySelector('.nv-perm-n').classes.has('hidden'), 'no number when nothing is waiting');
  assert.ok(!s.button.classes.has('waiting'));
  assert.match(s.button.dataset.tip, /Mode: Auto/);
  same(s.calls[0], ['/api/permissions', { action: 'state' }]);
  assert.equal(s.timers.at(-1), 6000, 'with nothing waiting it asks again slowly');
});

test('what is waiting is counted on the chip, and it asks again sooner', async () => {
  const s = setup(STATE({ pending: [ASSISTANT, JOB], more: 3 }));
  await s.settle();
  assert.equal(s.button.querySelector('.nv-perm-n').textContent, '5');
  assert.ok(s.button.classes.has('waiting'));
  assert.match(s.button.dataset.tip, /5 things are waiting for your answer/);
  assert.match(s.button.attrs['aria-label'], /5 waiting for your answer/);
  assert.equal(s.timers.at(-1), 2500);
  const odd = setup(STATE({ pending: [], more: '<b>9</b>' }));
  await odd.settle();
  assert.equal(odd.button.querySelector('.nv-perm-n').textContent, '0', 'a count that is not a number is shown as none');
});

test('the menu: the five modes, numbered, and what waits in other chats', async () => {
  const s = setup(STATE({ mode: 'plan', pending: [ASSISTANT, JOB], more: 2 }));
  await s.settle();
  s.button.onclick();
  assert.deepEqual(s.items.slice(0, 5).map(i => [i.label, !!i.tick]), [['1.  Auto', false], ['2.  Manual', false], ['3.  Accept edits', false], ['4.  Plan', true], ['5.  Bypass permissions', false]]);
  assert.equal(s.items[2].note, EVIL, 'handed to the menu as words (the menu writes them as text)');
  const other = s.items.slice(5);
  assert.deepEqual(other.map(i => i.label), [JOB.question], 'only what waits in another chat; this chat has its card');
  await other[0].action();
  assert.deepEqual(s.opened, ['chat:chat-2'], 'it opens that chat, where the card is');
  assert.match(s.pop() ? s.pop().text : '', /|/);
  assert.equal(s.button.querySelector('.nv-perm-name').textContent, 'Plan');
});

test('choosing a mode saves it and says so; the one in force is not sent again', async () => {
  let mode = 'sending';
  const states = () => STATE({ mode });
  states.answers = { mode: {} };
  const s = setup(states);
  await s.settle();
  s.button.onclick(); s.calls.length = 0;
  await s.items.find(i => i.label === '1.  Auto').action();
  assert.ok(!s.actions().includes('mode'), 'the one already in force is not sent again');
  mode = 'bypass';
  await s.items.find(i => i.label === '5.  Bypass permissions').action();
  same(s.calls.find(c => c[1].action === 'mode'), ['/api/permissions', { action: 'mode', mode: 'bypass' }]);
  assert.ok(s.said.some(t => /^Mode: Bypass permissions\./.test(t)));
  assert.equal(s.button.dataset.mode, 'bypass');
});

test('cards: every kind with its own answers, and hostile words stay words', async () => {
  const s = setup(STATE());
  await s.settle();
  const html = s.Nova.waitingCards([ASSISTANT, JOB, REVIEW, HELD, NEVER]);
  inert(html);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/, 'shown as text');
  assert.match(html, /data-kind="assistant" data-id="a1b2c3"/); assert.match(html, /data-yes>Yes, do it</);
  assert.match(html, /data-kind="job" data-id="20261114-010101-abcd" data-mark="4cc910b57d7c4268"/); assert.match(html, /Yes, carry on/);
  assert.match(html, /data-kind="review"[\s\S]*Reading the changes[\s\S]*data-no>Throw away<[\s\S]*data-yes disabled>Keep them</, 'Keep waits until the changes are shown');
  assert.match(html, /Go ahead</);
  assert.equal((html.match(/data-kind="blocked"/g) || []).length, 2);
  assert.ok(!/A coding job may never do this[\s\S]*Go ahead/.test(html), 'what may never be done can only be cancelled');
  assert.equal((html.match(/<input /g) || []).length, 1, 'only a job is answered with words');
});

test('a yes to the assistant is sent once, for that question, and the buttons go dead', async () => {
  const s = setup(STATE({ pending: [ASSISTANT] }));
  await s.settle(); s.calls.length = 0;
  const c = s.card(ASSISTANT);
  await c.press('yes');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'assistant', id: 'a1b2c3', yes: true }]);
  assert.ok(c.buttons.yes.disabled && c.buttons.no.disabled, 'one answer, once');
  assert.ok(c.removed); assert.ok(s.said.includes('Doing it.'));
  assert.equal(s.asked.length, 0, 'a no or a yes to the assistant is not asked about again');
});

test('a yes to a job carries the mark of the question on the screen, and its words', async () => {
  const s = setup(STATE({ pending: [JOB] }));
  await s.settle(); s.calls.length = 0;
  await s.card(JOB, 'Yes, but only the staging one.').press('yes');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'job', id: JOB.id, yes: true, text: 'Yes, but only the staging one.', mark: JOB.mark }]);
  const no = setup(STATE({ pending: [JOB] }), { yes: false });
  await no.settle(); no.calls.length = 0;
  await no.card(JOB).press('no');
  assert.deepEqual(no.asked, ['Say no to this?']);
  assert.ok(!no.actions().includes('decide'), 'a no that is taken back sends nothing');
});

test('Keep sends the state of the change the card showed; Throw away asks first', async () => {
  const s = setup(STATE({ pending: [REVIEW] }));
  await s.settle();
  const c = s.card(REVIEW);
  await s.Nova.fillChanges(c);
  assert.match(c.changes, /1 file changed/); assert.match(c.changes, /\+1/); assert.match(c.changes, /−1/);
  inert(c.changes); assert.match(c.changes, /&lt;b&gt;new&lt;\/b&gt;/, 'the diff is shown as text');
  assert.equal(c.buttons.yes.disabled, false, 'Keep can be pressed once the changes are shown');
  s.calls.length = 0;
  await c.press('yes');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'review', id: REVIEW.id, yes: true, revision: 'abc1234def' }]);
  assert.ok(s.said.includes('Kept: the changes are in your project now.'));
  const t = setup(STATE({ pending: [REVIEW] }));
  await t.settle(); t.calls.length = 0;
  await t.card(REVIEW).press('no');
  assert.deepEqual(t.asked, ['Throw these changes away?']);
  same(t.calls[0], ['/api/permissions', { action: 'decide', kind: 'review', id: REVIEW.id, yes: false }]);
});

test('Go ahead and Cancel for a held job', async () => {
  const s = setup(STATE({ pending: [HELD] }));
  await s.settle(); s.calls.length = 0;
  await s.card(HELD).press('yes');
  same(s.calls[0], ['/api/permissions', { action: 'decide', kind: 'blocked', id: HELD.id, yes: true }]);
  assert.ok(s.said.includes('Started again. It reports in this chat.'));
});

test('an answer that is refused says why, and the card can be answered again', async () => {
  const states = STATE({ pending: [ASSISTANT] }); states.answers = { decide: new Error('That question is no longer waiting.') };
  const s = setup(states);
  await s.settle();
  const c = s.card(ASSISTANT);
  await c.press('yes');
  assert.ok(s.said.includes('toast: That question is no longer waiting.'));
  assert.ok(!c.removed); assert.equal(c.buttons.yes.disabled, false);
});
