// The Security panel (jcc/static/nova-security.js). A stand-in page: no browser, no screen, nothing sent.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../jcc/static/nova-security.js'), 'utf8');
const EVIL = '<img src=x onerror=alert(1)>', SCRIPT = '"><script>alert(2)</script>';

class Node {
  constructor(html = '') {
    this.dataset = {}; this.kids = new Map(); this.handlers = {}; this.html = html; this.value = ''; this.hidden = false; this.scrollTop = 99; this.isConnected = true;
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
  const context = { window: { Nova }, api, esc, toast: text => said.push('toast: ' + text), openChat: async id => opened.push('chat:' + id), setTimeout: () => 0, clearTimeout: () => {}, console, isFinite, Date, Set };
  vm.createContext(context); vm.runInContext(code, context);
  const pane = panes.find(p => p.id === 'security'), box = pane.node.querySelector('#nv-sec-body');
  const click = async button => { for (const fn of box.handlers.click) await fn({ target: { closest: () => ({ dataset: {}, ...button }) } }); };
  const change = async target => { for (const fn of box.handlers.change) fn({ target: { dataset: {}, ...target } }); };
  return { panes, calls, said, opened, asked, pane, box, click, change, actions: () => calls.map(c => c[1].action) };
}
const inert = html => { assert.ok(!/<img|<script/i.test(html), html.slice(0, 400)); };

const finding = (id, severity, more) => ({ id, scanner: 'patterns', rule: 'py-eval', title: EVIL, severity, file: SCRIPT, line: '<b>9</b>', evidence: EVIL + ' `rm -rf` ' + SCRIPT, why: EVIL, fix: SCRIPT, ...more });
const SCAN = more => ({ id: 'sec-20261114-010101-aaaa', project: 'calc', name: EVIL, where: 'project', at: 1, took: '<i>1</i>', stack: [EVIL, 'Python'], files: SCRIPT, truncated: true, stopped: EVIL,
  skipped: { large: 1, binary: '<u>2</u>', links: 3, ignored: 4 },
  scanners: [{ id: 'patterns', name: EVIL, ran: true, covers: SCRIPT, why_not: '', findings: '<b>1</b>' }, { id: 'bandit', name: SCRIPT, ran: false, covers: EVIL, why_not: EVIL, findings: 0 }],
  findings: [finding('f1', 'high'), finding('f2', 'medium', { title: 'Second' }), finding('f3', 'low', { title: 'Third' }), finding(SCRIPT, 'high', { title: 'Odd id' })],
  fix: null, state: { status: 'none', job: '', chat: '', can_preview: false }, ...more });
const LIST = { projects: [{ key: 'calc', name: EVIL }], scans: [{ id: 'sec-20261114-010101-aaaa', project: 'calc', at: 1, where: 'copy', files: SCRIPT, counts: { high: EVIL, medium: 1, low: 0 }, fix: { job: 'x' } }] };

test('the panel is offered with a shield', () => {
  const s = setup({});
  assert.deepEqual(s.panes.map(p => [p.id, p.label, p.icon]), [['security', 'Security', 'shield']]);
  assert.ok(s.pane.tip && typeof s.pane.show === 'function');
});

test('no projects: it says a folder has to be connected first', async () => {
  const s = setup({ list: { projects: [], scans: [] } });
  await s.pane.show();
  assert.match(s.box.innerHTML, /Connect a project folder first/);
  assert.ok(!/nv-sec-run/.test(s.box.innerHTML));
});

test('hostile words in every field of a check stay words', async () => {
  const s = setup({ list: LIST, get: SCAN() });
  await s.pane.show();
  inert(s.box.innerHTML);
  await s.click({ dataset: { scan: 'sec-20261114-010101-aaaa' } });
  const html = s.box.innerHTML;
  inert(html);
  assert.ok(!html.includes('"><script'), 'not even half a tag');
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/, 'shown as text');
  assert.match(html, /2 high, 1 medium, 1 low · 0 files read · 0 s/, 'counts that are not numbers are shown as none');
  assert.match(html, /What was checked/); assert.match(html, /first pass with fixed rules/);
  assert.match(html, /data-ran="no"/); assert.match(html, /files after that point were not checked/i);
  assert.match(html, /<code>&lt;img/); assert.match(html, /:0<\/small>/, 'a line number that is not a number');
  assert.match(html, /data-finding="f1" checked/); assert.match(html, /data-finding="f2" checked/); assert.match(html, /data-finding="f3">/, 'low is not ticked to begin with');
  assert.match(html, /<details><summary>Why it matters and how to fix it/);
  assert.match(html, /Earlier checks of this project/); assert.match(html, /the fixed copy/);
});

test('the flow: check, fix only after a yes, scan the copy, apply, undo only after a yes', async () => {
  let current = SCAN({ truncated: false, findings: [finding('f1', 'high', { title: 'Eval' }), finding('f2', 'low', { title: 'Temp' })] });
  const answers = {
    list: { projects: [{ key: 'calc', name: 'Calc' }], scans: [] },
    scan: () => current, get: () => current,
    fix: () => { current = { ...current, fix: { job: '20261114-010101-abcd', chat: 'chat-1', findings: ['f1'] }, state: { status: 'working', job: '20261114-010101-abcd', chat: 'chat-1' } }; return current; },
    rescan: body => ({ scan: { ...current, id: 'sec-2', where: body.where }, fixed: ['f1'], still: ['f2'], new: [{ ...finding('f9', 'high'), title: EVIL }] }),
    preview: { patch: '+<script>alert(5)</script>\n-' + EVIL, files: [SCRIPT], revision: 'abc1234def' },
    apply: { status: 'done' }, undo: { status: 'done' },
  };
  let yes = false;
  const s = setup(answers, () => yes);
  await s.pane.show();
  await s.click({ id: 'nv-sec-run' });
  assert.deepEqual(s.actions(), ['list', 'scan', 'get', 'list', 'get']);
  assert.equal(JSON.stringify(s.calls[1][1]), JSON.stringify({ action: 'scan', project: 'calc' }));
  assert.match(s.box.innerHTML, /1 selected/);
  await s.change({ dataset: { finding: 'f1' }, checked: false });
  assert.match(s.box.innerHTML, /id="nv-sec-fix" disabled/, 'nothing ticked: nothing to fix');
  await s.change({ dataset: { finding: 'f1' }, checked: true });
  s.calls.length = 0;
  await s.click({ id: 'nv-sec-fix' });
  assert.equal(s.asked.length, 1); assert.ok(!s.actions().includes('fix'), 'no fix without a yes');
  yes = true;
  await s.click({ id: 'nv-sec-fix' });
  assert.equal(JSON.stringify(s.calls.find(c => c[1].action === 'fix')[1]), JSON.stringify({ action: 'fix', id: 'sec-20261114-010101-aaaa', findings: ['f1'] }));
  assert.match(s.box.innerHTML, /JARVIS is fixing 1 findings/); assert.match(s.box.innerHTML, /Open its chat/);
  current = { ...current, state: { status: 'ready', job: '20261114-010101-abcd', chat: 'chat-1', can_preview: true } };
  await s.pane.show();
  assert.match(s.box.innerHTML, /The fix is ready to look at/);
  await s.click({ id: 'nv-sec-diff' });
  inert(s.box.innerHTML); assert.match(s.box.innerHTML, /<pre class="nv-sec-diff">\+&lt;script&gt;/);
  await s.click({ id: 'nv-sec-copy' });
  assert.match(s.box.innerHTML, /1 of 1 are gone/); assert.match(s.box.innerHTML, /New since the first check/); inert(s.box.innerHTML);
  await s.click({ id: 'nv-sec-apply' });
  assert.equal(JSON.stringify(s.calls.find(c => c[1].action === 'apply')[1]), JSON.stringify({ action: 'apply', id: 'sec-20261114-010101-aaaa', revision: 'abc1234def' }),
    'what is applied is the state of the copy that was shown');
  current = { ...current, state: { status: 'applied', job: '20261114-010101-abcd', chat: 'chat-1', can_preview: true } };
  await s.pane.show();
  assert.match(s.box.innerHTML, /Undo the fix/);
  yes = false; s.calls.length = 0;
  await s.click({ id: 'nv-sec-undo' });
  assert.ok(!s.actions().includes('undo'), 'no undo without a yes');
  yes = true;
  await s.click({ id: 'nv-sec-undo' });
  const order = s.actions().filter(a => ['undo'].includes(a));
  assert.deepEqual(order, ['undo']);
  await s.click({ id: 'nv-sec-chat' });
  assert.deepEqual(s.opened, ['chat:chat-1']);
});

test('the order of the whole flow over the wire', async () => {
  let current = SCAN({ findings: [finding('f1', 'high')] });
  const s = setup({ list: { projects: [{ key: 'calc', name: 'Calc' }], scans: [] }, scan: () => current, get: () => current,
    fix: () => { current = { ...current, fix: { job: '20261114-010101-abcd', chat: 'c', findings: ['f1'] }, state: { status: 'ready', chat: 'c' } }; return current; },
    rescan: () => ({ scan: current, fixed: [], still: ['f1'], new: [] }), preview: { patch: '+fixed', files: ['a.py'], revision: 'abc1234def' }, apply: {}, undo: {} });
  await s.pane.show();
  await s.click({ id: 'nv-sec-run' }); await s.click({ id: 'nv-sec-fix' }); await s.click({ id: 'nv-sec-copy' });
  assert.match(s.box.innerHTML, /id="nv-sec-apply" disabled/, 'nothing can be applied before it has been shown');
  assert.match(s.box.innerHTML, /Show the changes first/);
  await s.click({ id: 'nv-sec-apply' });
  assert.ok(!s.actions().includes('apply'), 'and pressing it anyway sends nothing');
  await s.click({ id: 'nv-sec-diff' });
  assert.ok(!/id="nv-sec-apply" disabled/.test(s.box.innerHTML)); assert.ok(!/Show the changes first/.test(s.box.innerHTML));
  await s.click({ id: 'nv-sec-apply' });
  current = { ...current, state: { status: 'applied', chat: 'c' } };
  await s.pane.show(); await s.click({ id: 'nv-sec-undo' });
  const main = s.actions().filter(a => ['scan', 'fix', 'rescan', 'apply', 'undo'].includes(a));
  assert.deepEqual(main, ['scan', 'fix', 'rescan', 'apply', 'undo']);
  assert.match(s.box.innerHTML, /0 of 1 are gone|Undo the fix/);
});

test('a fix that stopped to ask, or failed, says so', async () => {
  for (const [status, words] of [['asked', /stopped and asks you something\. Its question, with a way to answer, is under Agents/], ['failed', /Nothing was changed in your project/]]) {
    const s = setup({ list: LIST, get: SCAN({ fix: { job: 'j', chat: 'c', findings: ['f1'] }, state: { status, chat: 'c' } }) });
    await s.pane.show(); await s.click({ dataset: { scan: 'sec-20261114-010101-aaaa' } });
    assert.match(s.box.innerHTML, words);
    assert.ok(!/id="nv-sec-fix"/.test(s.box.innerHTML), 'a check with a fix cannot start another');
    if (status === 'asked') { await s.click({ id: 'nv-sec-agents' }); assert.deepEqual(s.opened, ['pane:agents'], 'where its question can be answered'); }
  }
});
