// The Agents, Pair and Courtroom panels (jcc/static/nova-work.js). A stand-in page: no browser, no screen, nothing sent.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../jcc/static/nova-work.js'), 'utf8');
const EVIL = '<img src=x onerror=alert(1)>', SCRIPT = '"><script>alert(2)</script>';

class Node {
  constructor(html = '') {
    this.dataset = {}; this.kids = new Map(); this.handlers = {}; this.html = html; this.value = ''; this.hidden = false; this.scrollTop = 99; this.isConnected = true; this.textContent = '';
    this.classList = { contains: c => c === 'hidden' && this.hidden, add: () => {}, remove: () => {} };
  }
  set innerHTML(v) { this.html = String(v); } get innerHTML() { return this.html; }
  querySelector(sel) { if (!this.kids.has(sel)) this.kids.set(sel, new Node()); return this.kids.get(sel); }
  querySelectorAll() { return []; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  append() {} focus() { this.focused = true; } dispatchEvent() {} click() {}
}

function setup(answers) {
  const panes = [], calls = [], said = [], opened = [];
  const Nova = { icon: name => '<svg data-i="' + name + '"></svg>', el: (tag, attrs, html) => new Node(html), notify: text => said.push(text), confirmBox: async () => true,
                 registerPane: def => panes.push(def), openPane: id => opened.push(id), panel: new Node() };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const api = async (address, body) => { calls.push([address, body]); const answer = answers[address + ':' + body.action]; if (answer instanceof Error) throw answer; return typeof answer === 'function' ? answer(body) : answer; };
  const context = { window: { Nova }, api, esc, toast: text => said.push('toast: ' + text), openChat: async id => opened.push('chat:' + id), setTimeout: () => 0, clearTimeout: () => {},
                    Event: class { constructor(type) { this.type = type; } }, console };
  vm.createContext(context); vm.runInContext(code, context);
  const pane = id => panes.find(p => p.id === id), body = (id, sel) => pane(id).node.querySelector(sel);
  const click = async (node, button) => { for (const fn of node.handlers.click) await fn({ target: { closest: sel => { if (sel === 'button') return button; const m = /^\[data-([a-z]+)\]$/.exec(sel); return m && m[1] in button.dataset ? button : null; } } }); };
  return { panes, calls, said, opened, pane, body, click };
}
const inert = html => { assert.ok(!/<img|<script/i.test(html), html.slice(0, 400)); assert.ok(!/onerror=alert\(1\)>/.test(html.replace(/&lt;img src=x onerror=alert\(1\)&gt;/g, '')), 'only as escaped text'); };

const PLAN = { version: 2, at: 1, summary: EVIL, note: EVIL, change: EVIL, hand_over: [3], done: false, questions: [],
               steps: [{ n: 1, title: 'Write it', detail: EVIL, check: EVIL, done: true }, { n: 2, title: EVIL, detail: '', check: '', done: false }, { n: 3, title: 'Test it', detail: '', check: '', done: false }] };
const pairRecord = more => ({ id: 'pair-20261114-010101-aaaa', goal: EVIL, status: 'building', now: EVIL, project: 'calc', chat: 'chat-1',
  planner: { model: EVIL, answered_by: EVIL, turns: '<b>2</b>', asked: 'auto' }, builder: { asked: EVIL }, plans: [{ ...PLAN, version: 1, change: '' }, PLAN],
  handoffs: [{ number: 1, plan: 1, steps: [1], job: 'job-1', finished: 5, status: 'done', report: EVIL }, { number: '<i>2</i>', plan: 2, steps: [3], job: 'job-2', finished: null, status: SCRIPT, report: '' }],
  questions: [], notes: [], usage: { input: 10, output: 5, cached: 0, turns: 2 }, ...more });
const LISTS = { pairs: [{ id: 'pair-20261114-010101-aaaa', goal: EVIL, status: 'building', now: EVIL, project: 'calc', version: SCRIPT, steps: 3, done: 1 }],
                projects: [{ key: 'calc', name: EVIL }], planners: [{ id: 'claude:opus', name: EVIL }], builders: [{ id: 'codex:gpt', name: 'GPT' }], usual: EVIL, rounds: 8 };

test('three panels are offered, and the court has scales for an icon', () => {
  const s = setup({});
  assert.deepEqual(s.panes.map(p => [p.id, p.label, p.icon]), [['agents', 'Agents', 'pulse'], ['pair', 'Pair', 'layers'], ['court', 'Courtroom', 'scales']]);
  for (const p of s.panes) assert.ok(p.tip && p.node && typeof p.show === 'function', p.id);
});

test('what every agent is doing: hostile words stay words, and a row leads to its pair, its trial or its chat', async () => {
  const row = (kind, more) => ({ kind, id: 'x', who: EVIL, title: EVIL, project: EVIL, chat: '', state: 'running', since: 5, doing: EVIL, ...more });
  const s = setup({ '/api/agents:now': { at: 9, working: [row('pair', { id: 'pair-1', steps: ['<b>1</b>', 3] }), row('job', { chat: 'chat-7' + SCRIPT })], waiting: [row('court', { id: 'court-1', state: 'halted' })],
                                          held: [row('job')], later: [row('reminder', { due: 99999999999, since: null })], recent: [] } });
  await s.pane('agents').show();
  const html = s.body('agents', '#nv-ag-body').innerHTML;
  inert(html);
  assert.match(html, /Working now <span class="nv-wk-n">2<\/span>/);
  assert.match(html, /Waiting for you/); assert.match(html, /Held up/); assert.match(html, /Set for later/);
  assert.ok(!/Just finished/.test(html), 'a part with nothing in it is not shown');
  assert.match(html, /0 of 3 steps/, 'a count that is not a number is shown as none');
  assert.match(html, /data-go="pair:pair-1"/); assert.match(html, /data-go="court:court-1"/);
  assert.match(html, /data-go=""[^>]* disabled/, 'a job with no chat leads nowhere');
  await s.click(s.body('agents', '#nv-ag-body'), { dataset: { go: 'pair:pair-1' } });
  await s.click(s.body('agents', '#nv-ag-body'), { dataset: { go: 'court:court-1' } });
  await s.click(s.body('agents', '#nv-ag-body'), { dataset: { go: 'chat:chat-7' } });
  assert.deepEqual(s.opened, ['pair', 'court', 'chat:chat-7']);
});

test('routines are listed as scheduled, and a job that failed is marked as failed and says which routine started it', async () => {
  const s = setup({ '/api/agents:now': { at: 9, working: [], waiting: [], held: [], later: [],
    scheduled: [{ kind: 'routine', id: 'rt-20261116-090000-abcd', title: EVIL, doing: SCRIPT, next: Date.now() / 1000 + 1800, state: 'scheduled', who: '', project: '', chat: '', since: null }],
    recent: [{ kind: 'job', id: 'j1', who: 'claude', title: 'Tell me my day', project: '', chat: 'chat-1', state: 'failed', since: 5, doing: 'Did not finish', routine: EVIL },
             { kind: 'job', id: 'j2', who: 'claude', title: 'Other', project: '', chat: '', state: 'done', since: 5, doing: 'Finished' }] } });
  await s.pane('agents').show();
  const html = s.body('agents', '#nv-ag-body').innerHTML;
  inert(html);
  assert.match(html, /Scheduled <span class="nv-wk-n">1<\/span>/);
  assert.match(html, /data-go="routines:rt-20261116-090000-abcd"/);
  assert.match(html, /in 30 min/, 'when it runs next');
  assert.match(html, /data-state="failed">Failed</, 'a failure is not mistaken for a finish');
  assert.equal((html.match(/data-state="failed"/g) || []).length, 1, 'only the failed one is marked');
  assert.match(html, /from the routine &lt;img/);
  await s.click(s.body('agents', '#nv-ag-body'), { dataset: { go: 'routines:rt-20261116-090000-abcd' } });
  assert.deepEqual(s.opened, ['routines'], 'it opens the Routines panel');
});

test('nothing at work: the two things that can be started are offered', async () => {
  const s = setup({ '/api/agents:now': { at: 9, working: [], waiting: [], held: [], later: [], recent: [] } });
  await s.pane('agents').show();
  const html = s.body('agents', '#nv-ag-body').innerHTML;
  assert.match(html, /Nothing is working right now/); assert.match(html, /data-open="pair"/); assert.match(html, /data-open="court"/);
  await s.click(s.body('agents', '#nv-ag-body'), { dataset: { open: 'court' } });
  assert.deepEqual(s.opened, ['court']);
});

test('a pair: the list and the view of one keep hostile words inert', async () => {
  const s = setup({ '/api/pairs:list': LISTS, '/api/pairs:get': pairRecord() });
  await s.pane('pair').show();
  const list = s.body('pair', '#nv-pr-body').innerHTML;
  inert(list);
  assert.match(list, /Start a pair/); assert.match(list, /plan version 0 · 1 of 3 steps done/, 'a version that is not a number is shown as none');
  assert.equal(s.pane('pair').node.scrollTop, 0, 'a panel opens at its top');
  s.pane('pair').node.scrollTop = 400;
  await s.click(s.body('pair', '#nv-pr-body'), { dataset: { pair: 'pair-20261114-010101-aaaa' } });
  const view = s.body('pair', '#nv-pr-body').innerHTML;
  inert(view);
  assert.equal(s.pane('pair').node.scrollTop, 0, 'a pair opened from the list starts at its top');
  assert.match(view, /data-step="done"><b>1\. Write it/); assert.match(view, /data-step="now"><b>3\. Test it/); assert.match(view, /data-step="todo"><b>2\. /);
  assert.match(view, /How the plan changed<\/b> · 2 versions/);
  assert.match(view, /Hand-over 0<\/b>/, 'a number that is not one is shown as none');
  assert.match(view, /Stop the pair/); assert.ok(!/id="nv-pr-go"/.test(view), 'a pair at work has nothing to carry on');
  assert.match(view, />Send<\/button>/);
});

test('a job that stopped to ask: the question is shown with a yes and a no, and an answer is sent once', async () => {
  const ask = { job: '20261114-010101-abcd', text: EVIL + ' May I change the deploy script?', mark: '4cc910b57d7c4268' };
  const row = { kind: 'job', id: ask.job, who: 'claude', title: 'Publish the site', project: 'Site', chat: 'chat-1', state: 'needs_approval', since: 5, doing: 'Asks you: May I change the deploy script?', ask };
  const s = setup({ '/api/agents:now': { at: 9, working: [], waiting: [row, { ...row, id: 'x2', ask: null }], held: [], later: [], recent: [] }, '/api/job/control:answer': { status: 'queued' }, '/api/job/control:decline': { status: 'cancelled' } });
  await s.pane('agents').show();
  const html = s.body('agents', '#nv-ag-body').innerHTML;
  inert(html);
  assert.equal((html.match(/class="nv-wk-ask"/g) || []).length, 1, 'only the job that asks has a way to answer');
  assert.match(html, /data-job="20261114-010101-abcd" data-mark="4cc910b57d7c4268"/, 'the question carries its mark'); assert.match(html, /data-answer>Yes, carry on</); assert.match(html, /data-decline>No</);
  const buttons = [{ disabled: false }, { disabled: false }], input = { value: 'Yes, but only the staging one.' };
  const block = { dataset: { job: ask.job, mark: ask.mark }, querySelectorAll: () => buttons, querySelector: () => input };
  const press = how => ({ dataset: { [how]: '' }, closest: () => block });
  s.calls.length = 0;
  await s.click(s.body('agents', '#nv-ag-body'), press('answer'));
  assert.equal(JSON.stringify(s.calls[0]), JSON.stringify(['/api/job/control', { id: ask.job, action: 'answer', text: 'Yes, but only the staging one.', mark: ask.mark }]),
    'a yes says which question it answers: the one that was on the screen');
  assert.ok(buttons.every(b => b.disabled), 'the buttons go dead: one answer, once');
  assert.ok(s.said.some(t => /same job carries on/.test(t)));
  s.calls.length = 0; buttons.forEach(b => { b.disabled = false; });
  await s.click(s.body('agents', '#nv-ag-body'), press('decline'));
  assert.equal(JSON.stringify(s.calls[0]), JSON.stringify(['/api/job/control', { id: ask.job, action: 'decline', text: 'Yes, but only the staging one.' }]), 'a no is asked about first (the stand-in says yes to that), then sent');
});

test('a pair whose builder asks shows the same question in the pair itself', async () => {
  const waiting = pairRecord({ status: 'waiting', now: 'The builder stopped and asks you something.', ask: { job: '20261114-010101-abcd', text: 'May I edit the .env file?', mark: 'aaaabbbbccccdddd' } });
  const s = setup({ '/api/pairs:list': LISTS, '/api/pairs:get': waiting, '/api/job/control:answer': { status: 'queued' } });
  await s.pane('pair').show();
  await s.click(s.body('pair', '#nv-pr-body'), { dataset: { pair: waiting.id } });
  const view = s.body('pair', '#nv-pr-body').innerHTML;
  assert.match(view, /class="nv-wk-ask" data-job="20261114-010101-abcd" data-mark="aaaabbbbccccdddd"/); assert.match(view, /May I edit the \.env file\?/);
  const working = pairRecord({ status: 'building', ask: { job: 'x', text: 'old' } });
  const t = setup({ '/api/pairs:list': LISTS, '/api/pairs:get': working });
  await t.pane('pair').show();
  await t.click(t.body('pair', '#nv-pr-body'), { dataset: { pair: working.id } });
  assert.ok(!/nv-wk-ask/.test(t.body('pair', '#nv-pr-body').innerHTML), 'a pair that is building again shows no question');
});

test('a pair whose planner asks: one press answers and carries on', async () => {
  const waiting = pairRecord({ status: 'halted', now: 'The planner needs an answer from you: Which page?', questions: ['Which page?'], handoffs: [] });
  const s = setup({ '/api/pairs:list': LISTS, '/api/pairs:get': waiting, '/api/pairs:tell': waiting, '/api/pairs:start': waiting });
  await s.pane('pair').show();
  const box = s.body('pair', '#nv-pr-body');
  await s.click(box, { dataset: { pair: waiting.id } });
  const view = box.innerHTML;
  assert.match(view, /The planner asks:<\/b> Which page\?/);
  assert.match(view, /id="nv-pr-tell" data-go="1">Answer and carry on</); assert.match(view, /Carry on without answering/);
  assert.match(view, /placeholder="Your answer for the planner"/);
  s.calls.length = 0;
  await s.click(box, { id: 'nv-pr-tell', dataset: { go: '1' } });
  assert.deepEqual(s.calls, [], 'nothing is sent with nothing typed');
  assert.ok(box.querySelector('#nv-pr-word').focused);
  box.querySelector('#nv-pr-word').value = 'Only in settings.';
  await s.click(box, { id: 'nv-pr-tell', dataset: { go: '1' } });
  assert.deepEqual(s.calls.slice(0, 2).map(c => [c[1].action, c[1].text || '']), [['tell', 'Only in settings.'], ['start', '']]);
  assert.ok(s.said.includes('The planner is reading your answer.'));
});

test('a pair that has finished offers nothing but its chat', async () => {
  const done = pairRecord({ status: 'done', now: 'The planner says the goal is reached.' });
  const s = setup({ '/api/pairs:list': LISTS, '/api/pairs:get': done });
  await s.pane('pair').show();
  await s.click(s.body('pair', '#nv-pr-body'), { dataset: { pair: done.id } });
  const view = s.body('pair', '#nv-pr-body').innerHTML;
  for (const gone of ['nv-pr-word', 'nv-pr-tell', 'nv-pr-go', 'nv-pr-stop']) assert.ok(!view.includes('id="' + gone + '"'), gone);
  assert.match(view, /id="nv-pr-chat"/);
});

const stage = (key, title, more) => ({ key, title, status: 'done', decision: 'advance', reason: EVIL, body: {}, model: 'sonnet', answered_by: '', attempts: 1, error: '', usage: {}, ...more });
const SOURCES = [{ title: 'A real page', url: 'https://example.org/a?b=1&c=2', date: 'March 2026', claim: EVIL, stance: 'for', analyst: 'Economics' },
                 { title: 'Not a page', url: 'javascript:alert(3)', date: EVIL, claim: 'x', stance: SCRIPT, analyst: EVIL }];
const trial = more => ({ id: 'court-20261114-010101-aaaa', created: 1, submitted: 1, status: 'closed', idea: EVIL, now: '', research: 'partial', verdict: 'PASS', verdict_reason: EVIL, pronouncement: EVIL,
  uncertainty: [EVIL], evidence: SOURCES, usage: { input: 1, output: 1, cached: 0, searches: 9 },
  stages: [stage('grand_jury', 'Grand Jury', { body: { coherence: EVIL, viability: EVIL, assumptions: [EVIL] } }),
           stage('prosecution', 'Prosecution', { attempts: 4, body: { charges: [{ charge: EVIL, severity: SCRIPT, detail: EVIL }] } }),
           stage('analysts', 'Analysts', { attempts: 3, body: { analysts: [{ key: 'economics', name: EVIL, holds: true, decisive: false, summary: EVIL, blocker: EVIL, note: EVIL, findings: [EVIL], conflicts: [], gaps: [EVIL], sources: SOURCES, searches: '<u>4</u>' }] } }),
           stage('tribunal', 'Tribunal', { body: { summary: EVIL, criteria: { coherence: { title: EVIL, finding: SCRIPT, reason: EVIL } } } }),
           stage('executioner', 'Executioner', { decision: null })], ...more });
const HALL = { sessions: [{ id: 'court-20261114-010101-aaaa', created: 1, status: 'closed', verdict: 'PASS', idea: EVIL, now: EVIL }, { id: 'court-2', created: 2, status: 'awaiting_idea', verdict: null, idea: '', now: '' }],
               rules: [EVIL, 'No appeals.'], models: { grand_jury: 'sonnet', prosecution: 'opus', analysts: 'sonnet', tribunal: 'opus', executioner: EVIL },
               stages: [{ key: 'grand_jury', title: 'Grand Jury' }], analysts: [{ key: 'a', name: 'A' }, { key: 'b', name: 'B' }, { key: 'c', name: 'C' }], longest: 6000, shortest: 20 };

test('the courtroom: the hall and a trial keep hostile words inert, and only a web address becomes a link', async () => {
  const s = setup({ '/api/court:list': HALL, '/api/court:get': trial() });
  await s.pane('court').show();
  const hall = s.body('court', '#nv-ct-body').innerHTML;
  inert(hall);
  assert.match(hall, /The Warden reads the rules/); assert.match(hall, /No appeals\./); assert.match(hall, /maxlength="6000"/);
  assert.equal((hall.match(/data-session=/g) || []).length, 1, 'a session that never got its idea is not in the record');
  await s.click(s.body('court', '#nv-ct-body'), { dataset: { session: 'court-20261114-010101-aaaa' } });
  const view = s.body('court', '#nv-ct-body').innerHTML;
  inert(view);
  assert.ok(!/href="javascript/i.test(view), 'a source that is not a web address is words, not a link');
  assert.match(view, /<a href="https:\/\/example\.org\/a\?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">A real page<\/a>/);
  assert.match(view, /data-verdict="PASS"/); assert.match(view, /It is not a promise that it will succeed/); assert.match(view, /What remains uncertain/);
  assert.match(view, /not available to every analyst/);
  assert.match(view, /Sources \(0 searches\)/, 'a count that is not a number is shown as none');
  assert.ok(!/id="nv-ct-resume"/.test(view), 'a closed trial cannot be resumed');
});

test('a stage is said to have been asked again only when it was', async () => {
  const s = setup({ '/api/court:list': HALL, '/api/court:get': trial() });
  await s.pane('court').show();
  await s.click(s.body('court', '#nv-ct-body'), { dataset: { session: 'court-20261114-010101-aaaa' } });
  const view = s.body('court', '#nv-ct-body').innerHTML, of = title => view.slice(view.indexOf('<b>' + title + '</b>')).split('</summary>')[0];
  assert.ok(!/asked again/.test(of('Grand Jury')));
  assert.match(of('Prosecution'), /asked again 3 times after technical trouble/);
  assert.ok(!/asked again/.test(of('Analysts')), 'three analysts asked once each is not three tries');
});

test('a halted trial can be resumed; one in session shows which stage is sitting', async () => {
  const halted = trial({ status: 'halted', verdict: null, now: 'The trial is halted at the Analysts.', evidence: [], uncertainty: [],
    stages: [stage('grand_jury', 'Grand Jury'), stage('prosecution', 'Prosecution'), stage('analysts', 'Analysts', { status: 'failed', decision: null, attempts: 5, error: 'The helper could not be started.' }),
             stage('tribunal', 'Tribunal', { status: 'pending', decision: null, attempts: 0 }), stage('executioner', 'Executioner', { status: 'pending', decision: null, attempts: 0 })] });
  const s = setup({ '/api/court:list': HALL, '/api/court:get': halted, '/api/court:resume': halted });
  await s.pane('court').show();
  const box = s.body('court', '#nv-ct-body');
  await s.click(box, { dataset: { session: halted.id } });
  const view = box.innerHTML;
  assert.match(view, /id="nv-ct-resume"/); assert.match(view, /data-how="halted" open/); assert.match(view, /The helper could not be started\./);
  assert.match(view, /asked again 2 times after technical trouble/); assert.equal((view.match(/data-how="pending"/g) || []).length, 2);
  s.calls.length = 0;
  await s.click(box, { id: 'nv-ct-resume', dataset: {} });
  assert.equal(JSON.stringify(s.calls[0]), JSON.stringify(['/api/court', { action: 'resume', id: halted.id }]));
});

test('an idea is submitted only after it is long enough and its owner has confirmed', async () => {
  const s = setup({ '/api/court:list': HALL, '/api/court:open': { id: 'court-new' }, '/api/court:submit': {}, '/api/court:get': trial({ id: 'court-new', status: 'in_session', verdict: null }) });
  await s.pane('court').show();
  const box = s.body('court', '#nv-ct-body');
  box.querySelector('#nv-ct-idea').value = 'Too short';
  s.calls.length = 0;
  await s.click(box, { id: 'nv-ct-submit', dataset: {} });
  assert.deepEqual(s.calls, []); assert.match(s.said.join(' '), /at least 20 characters/);
  box.querySelector('#nv-ct-idea').value = '  A bakery that delivers bread by bicycle.  ';
  await s.click(box, { id: 'nv-ct-submit', dataset: {} });
  assert.equal(JSON.stringify(s.calls.slice(0, 2)), JSON.stringify([['/api/court', { action: 'open' }], ['/api/court', { action: 'submit', id: 'court-new', idea: 'A bakery that delivers bread by bicycle.' }]]));
  assert.ok(s.said.includes('The court is in session.'));
});
