/* NOVA work panels: what every agent is doing (Agents), a planner and a builder on one goal (Pair), and the Court of
   JARVIS (Courtroom). Each lives in the side panel next to the chat and only talks to this app. */
(() => {
'use strict';
const N = window.Nova; if (!N) return;
const { icon, el, notify, confirmBox, registerPane, openPane } = N;
const pane = (id, html) => { const node = el('section', { id: 'tool-nv' + id, class: 'tool-content nv-pane nv-wk hidden' }, html); N.panel.append(node); return node; };
const shown = node => !node.classList.contains('hidden') && node.isConnected;
const ago = at => { if (!at) return ''; const s = Math.max(0, Math.round(Date.now() / 1000 - at)); return s < 60 ? s + ' s' : s < 3600 ? Math.round(s / 60) + ' min' : s < 86400 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' d'; };
const until = at => { const s = Math.max(0, Math.round(at - Date.now() / 1000)); return s < 90 ? 'in ' + s + ' s' : s < 5400 ? 'in ' + Math.round(s / 60) + ' min' : s < 129600 ? 'in ' + Math.round(s / 3600) + ' h' : 'in ' + Math.round(s / 86400) + ' days'; };
const clock = at => at ? new Date(at * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '';
const number = n => Number(n || 0).toLocaleString();
// Everything shown comes through esc() or, for a count, through num(): a saved record is data, never markup.
const num = v => String(Math.round(Number(v)) || 0);
// A source is a link only when it is a web address; anything else is shown as plain words.
const source = src => /^https?:\/\//i.test(String(src.url || '')) ? '<a href="' + esc(src.url) + '" target="_blank" rel="noopener noreferrer">' + esc(src.title) + '</a>' : esc(src.title);
// Asks again every little while, but only while its panel is showing: a hidden panel costs nothing.
function poller(node, draw, quick = 2000, slow = 6000) {
  let timer = 0;
  const tick = async () => { clearTimeout(timer); if (!shown(node)) return; let busy = false; try { busy = await draw(); } catch (error) { toast(error.message); } timer = setTimeout(tick, busy ? quick : slow); };
  return tick;
}

/* A job that stopped to ask its owner for something: what it asked, and a way to answer. Yes carries the same job on
   (with a few words, if its owner wants to add any); no ends it. One answer, once. */
const askBlock = a => '<div class="nv-wk-ask" data-job="' + esc(a.job) + '" data-mark="' + esc(a.mark || '') + '"><b>It stopped and asks you</b><p>' + esc(a.text) + '</p>' +
  '<div class="nv-wk-tell"><input maxlength="2000" placeholder="A few words with your answer, if you like" aria-label="Your answer">' +
  '<button class="primary" type="button" data-answer>Yes, carry on</button><button class="plain" type="button" data-decline>No</button></div></div>';
async function answerJob(block, yes) {
  const buttons = [...block.querySelectorAll('button')];
  if (!yes && !(await confirmBox({ title: 'Say no to this?', text: 'The job ends and nothing is changed. If it belongs to a planner and builder, the planner is told you said no.', ok: 'Say no', danger: true }))) return false;
  buttons.forEach(b => { b.disabled = true; });                  // one answer, once
  try {
    // (A yes says which question it answers: if the job has moved on to another one, it is refused and the list is read again.)
    await api('/api/job/control', { id: block.dataset.job, action: yes ? 'answer' : 'decline', text: block.querySelector('input').value, ...(yes ? { mark: block.dataset.mark } : {}) });
    notify(yes ? 'Answered. The same job carries on from where it stopped.' : 'You said no. The job has ended and nothing was changed.');
    return true;
  } catch (error) { buttons.forEach(b => { b.disabled = false; }); toast(error.message); return false; }
}
// What is being typed as an answer is kept while the list is drawn again.
const typedAnswers = box => Object.fromEntries([...box.querySelectorAll('.nv-wk-ask')].map(n => [n.dataset.job, n.querySelector('input').value]));
const putAnswers = (box, kept) => box.querySelectorAll('.nv-wk-ask').forEach(n => { if (kept[n.dataset.job]) n.querySelector('input').value = kept[n.dataset.job]; });

/* ================= Agents: what every agent is doing, in one list ================= */
const agents = pane('agents', '<div class="tool-heading"><div><h2>Agents</h2><p>Everything that is working for you, in one place: who, on what, and what it is doing this moment.</p></div></div><div id="nv-ag-body" class="nv-wk-body"></div>');
const agBody = agents.querySelector('#nv-ag-body');
const KIND = { assistant: ['chat', 'Assistant'], job: ['work', 'Coding job'], pair: ['layers', 'Planner and builder'], court: ['scales', 'Court of JARVIS'], scan: ['search', 'Skills scan'], timer: ['pulse', 'Timer'], reminder: ['pulse', 'Reminder'], routine: ['clock', 'Routine'] };
// A job that ended badly is marked as such, so a failure is not mistaken for a finish.
const ENDED = { failed: 'Failed', cancelled: 'Cancelled' };
function agentRow(r, live) {
  const [glyph, kind] = KIND[r.kind] || ['work', 'Agent'];
  const steps = r.steps && r.steps[1] ? '<span class="nv-wk-count">' + num(r.steps[0]) + ' of ' + num(r.steps[1]) + ' steps</span>' : '';
  const where = r.kind === 'pair' ? 'pair:' + r.id : r.kind === 'court' ? 'court:' + r.id : r.kind === 'routine' ? 'routines:' + r.id : r.chat ? 'chat:' + r.chat : '';
  const ended = ENDED[r.state] ? '<span class="nv-wk-pill" data-state="' + esc(r.state) + '">' + ENDED[r.state] + '</span>' : '';
  const when = r.kind === 'routine' ? (r.next ? until(r.next) : '') : r.due ? until(r.due) : r.since ? ago(r.since) + (live ? '' : ' ago') : '';
  return '<button class="nv-wk-row' + (live ? ' live' : '') + '" type="button" data-go="' + esc(where) + '"' + (where ? '' : ' disabled') + '>' +
    '<span class="nv-wk-ico">' + icon(glyph) + '</span><span class="nv-wk-main"><b>' + esc(r.title || kind) + '</b>' +
    '<span class="nv-wk-doing">' + (live ? '<i class="nv-spin"></i>' : '') + esc(r.doing || '') + '</span>' +
    '<small>' + [kind, r.routine ? 'from the routine ' + r.routine : '', r.kind === 'routine' && r.next ? 'next ' + clock(r.next) : '', r.who, r.project].filter(Boolean).map(esc).join(' · ') + '</small></span>' +
    '<span class="nv-wk-when">' + ended + steps + esc(when) + '</span></button>' +
    (r.ask && r.ask.job ? askBlock(r.ask) : '');
}
const drawAgents = async () => {
  const d = await api('/api/agents', { action: 'now' });
  const part = (title, rows, live, note) => rows.length ? '<h3>' + title + ' <span class="nv-wk-n">' + rows.length + '</span></h3>' + (note ? '<p class="small">' + note + '</p>' : '') + rows.map(r => agentRow(r, live)).join('') : '';
  const html = part('Working now', d.working, true) + part('Waiting for you', d.waiting, false, 'These go on once you have looked: a change to review, or a question to answer.') +
    part('Held up', d.held, false) + part('Set for later', d.later, false) + part('Scheduled', d.scheduled || [], false, 'Your routines: each runs by itself at its time, as if you had typed it.') +
    part('Just finished', d.recent, false);
  const next = html || '<div class="nv-blank"><div><b>Nothing is working right now.</b><br>Ask for something in the chat, or start one of these.<div class="nv-wk-start">' +
    '<button class="plain" data-open="pair">' + icon('layers') + 'A planner and a builder</button><button class="plain" data-open="court">' + icon('scales') + 'Take an idea to court</button></div></div></div>';
  if (agBody.dataset.sig !== next) { const kept = typedAnswers(agBody); agBody.dataset.sig = next; agBody.innerHTML = next; putAnswers(agBody, kept); }
  return d.working.length > 0 || d.waiting.some(r => r.ask);
};
const pollAgents = poller(agents, drawAgents);
agBody.addEventListener('click', async e => {
  const said = e.target.closest('[data-answer]') || e.target.closest('[data-decline]');
  if (said) { if (await answerJob(said.closest('.nv-wk-ask'), said.dataset.answer !== undefined)) { agBody.dataset.sig = ''; await pollAgents(); } return; }
  const open = e.target.closest('[data-open]'); if (open) return void openPane(open.dataset.open);
  const row = e.target.closest('[data-go]'); if (!row || !row.dataset.go) return;
  const [kind, id] = [row.dataset.go.slice(0, row.dataset.go.indexOf(':')), row.dataset.go.slice(row.dataset.go.indexOf(':') + 1)];
  if (kind === 'chat') openChat(id).catch(error => toast(error.message));
  else if (kind === 'pair') { pairShown = id; openPane('pair'); }
  else if (kind === 'court') { courtShown = id; openPane('court'); }
  else if (kind === 'routines') openPane('routines');
});
registerPane({ id: 'agents', label: 'Agents', icon: 'pulse', node: agents, tip: 'What every agent is doing right now, in one list', show: async () => { agBody.dataset.sig = ''; await pollAgents(); } });

/* ================= Pair: one model plans, another builds ================= */
const pair = pane('pair', '<div class="tool-heading"><div><h2>Planner and builder</h2><p>One model plans and never touches a file. Another builds, a few steps at a time. The builder’s report goes back to the planner, which revises the plan.</p></div></div><div id="nv-pr-body" class="nv-wk-body"></div>');
const prBody = pair.querySelector('#nv-pr-body');
let pairShown = '', pairLists = null;
const PAIR_STATE = { new: 'Not started', planning: 'Planning', building: 'Building', waiting: 'Waiting for your review', halted: 'Needs you', done: 'Finished', stopped: 'Stopped' };
const JOB_STATE = { done: 'Done and merged', failed: 'Did not pass', stalled: 'Could not finish', blocked: 'Not allowed', asked: 'Asked for something', needs_approval: 'Waiting for your review', running: 'Building', queued: 'Waiting', paused: 'Paused', cancelled: 'Cancelled' };
function pairList(d) {
  const rows = d.pairs.map(p => '<button class="nv-wk-row' + (['planning', 'building'].includes(p.status) ? ' live' : '') + '" type="button" data-pair="' + esc(p.id) + '"><span class="nv-wk-ico">' + icon('layers') + '</span>' +
    '<span class="nv-wk-main"><b>' + esc(p.goal) + '</b><span class="nv-wk-doing">' + esc(p.now || PAIR_STATE[p.status] || p.status) + '</span><small>' +
    esc((d.projects.find(x => x.key === p.project) || {}).name || p.project) + ' · plan version ' + num(p.version) + ' · ' + num(p.done) + ' of ' + num(p.steps) + ' steps done</small></span>' +
    '<span class="nv-wk-when"><span class="nv-wk-pill" data-state="' + esc(p.status) + '">' + esc(PAIR_STATE[p.status] || p.status) + '</span></span></button>').join('');
  const choose = (id, list, first) => '<select id="' + id + '">' + first + list.map(m => '<option value="' + esc(m.id) + '">' + esc(m.name) + '</option>').join('') + '</select>';
  return '<div class="settings-box nv-wk-new"><h3>Start a pair</h3>' +
    (d.projects.length ? '<label>Project<select id="nv-pr-project">' + d.projects.map(p => '<option value="' + esc(p.key) + '">' + esc(p.name) + '</option>').join('') + '</select></label>' +
      '<label>The goal<textarea id="nv-pr-goal" rows="3" maxlength="4000" placeholder="What should exist when this is finished? For example: add a dark mode switch to the settings page, remembered between visits, with a test."></textarea></label>' +
      '<div class="nv-wk-two"><label>Planner' + choose('nv-pr-planner', d.planners, '<option value="auto">Strongest available (' + esc(d.usual) + ')</option>') + '</label>' +
      '<label>Builder' + choose('nv-pr-builder', d.builders, '<option value="auto">JARVIS chooses for each step</option>') + '</label></div>' +
      '<p class="small">The planner reads the project but cannot change it. The builder works in its own copy; a change is merged only when the project’s checks pass, and waits for your review where the project asks for one. After ' + num(d.rounds) + ' hand-overs the pair stops and waits for you.</p>' +
      '<div class="settings-buttons"><button class="primary" id="nv-pr-start">' + icon('layers') + 'Start</button></div>'
      : '<p>A pair works inside a project. Connect a project folder first (Files, then “Connect a folder”).</p>') + '</div>' +
    (rows ? '<h3>Your pairs</h3>' + rows : '');
}
function pairView(p, d) {
  const plan = p.plans[p.plans.length - 1], out = p.handoffs.length && !p.handoffs[p.handoffs.length - 1].finished ? p.handoffs[p.handoffs.length - 1].steps.map(Number) : [];
  const live = ['planning', 'building'].includes(p.status);
  const steps = plan ? plan.steps.map(s => '<li data-step="' + (s.done ? 'done' : out.includes(Number(s.n)) ? 'now' : 'todo') + '"><b>' + num(s.n) + '. ' + esc(s.title) + '</b>' +
    (s.detail ? '<small>' + esc(s.detail) + '</small>' : '') + (s.check ? '<small class="nv-wk-check">Done when: ' + esc(s.check) + '</small>' : '') + '</li>').join('') : '';
  const hand = p.handoffs.slice().reverse().map(h => '<details class="nv-wk-hand"' + (h.finished ? '' : ' open') + '><summary><b>Hand-over ' + num(h.number) + '</b> · step' + (h.steps.length > 1 ? 's ' : ' ') + h.steps.map(num).join(', ') +
    ' · plan version ' + num(h.plan) + '<span class="nv-wk-pill" data-state="' + esc(h.status || 'running') + '">' + esc(JOB_STATE[h.status || 'running'] || h.status) + '</span></summary>' +
    (h.report ? '<pre class="nv-wk-report">' + esc(h.report.slice(-2500)) + '</pre>' : '<p class="small">' + (h.finished ? 'No report came back.' : 'The builder has not reported yet.') + '</p>') + '</details>').join('');
  const versions = p.plans.length > 1 ? '<details class="nv-wk-hand"><summary><b>How the plan changed</b> · ' + p.plans.length + ' versions</summary><ol class="nv-wk-changes">' +
    p.plans.map(v => '<li><b>Version ' + num(v.version) + '</b> · ' + esc(clock(v.at)) + '<br>' + esc(v.change || (v.version === 1 ? v.summary : 'No change to the plan itself.')) + '</li>').join('') + '</ol></details>' : '';
  const canGo = ['halted', 'new'].includes(p.status), ended = ['done', 'stopped'].includes(p.status), asks = canGo && p.questions && p.questions.length > 0;
  return '<button class="plain nv-wk-back" data-back>' + icon('chev') + 'All pairs</button>' +
    '<div class="nv-wk-head"><b>' + esc(p.goal) + '</b><span class="nv-wk-pill" data-state="' + esc(p.status) + '">' + esc(PAIR_STATE[p.status] || p.status) + '</span></div>' +
    '<p class="nv-wk-now">' + (live ? '<i class="nv-spin"></i>' : '') + esc(p.now || '') + '</p>' +
    (p.ask && p.ask.job && p.status === 'waiting' ? askBlock(p.ask) : '') +
    '<div class="nv-wk-seats"><div><small>Planner</small><b>' + esc(p.planner.answered_by || p.planner.model) + '</b><small>' + (p.planner.answered_by ? 'asked for: ' + esc(p.planner.model) + ' · ' : '') +
    num(p.planner.turns) + ' turn' + (p.planner.turns === 1 ? '' : 's') + ' · reads only</small></div><div><small>Builder</small><b>' + esc(p.builder.asked === 'auto' ? 'JARVIS chooses' : ((d.builders.find(m => m.id === p.builder.asked) || {}).name || p.builder.asked)) +
    '</b><small>an ordinary coding job for each hand-over</small></div></div>' +
    (plan ? '<h3>The plan <span class="nv-wk-n">version ' + num(plan.version) + '</span></h3><p class="small">' + esc(plan.summary) + '</p><ol class="nv-wk-steps">' + steps + '</ol>' +
      (plan.note ? '<p class="small"><b>The planner’s note to the builder:</b> ' + esc(plan.note) + '</p>' : '') : '<p class="small">No plan yet.</p>') +
    (p.questions && p.questions.length && !ended ? '<div class="nv-careful-note"><span><b>The planner asks:</b> ' + p.questions.map(esc).join(' ') + '</span></div>' : '') +
    versions + (hand ? '<h3>Hand-overs to the builder</h3>' + hand : '') +
    (ended ? '' : '<div class="nv-wk-tell"><input id="nv-pr-word" maxlength="2000" aria-label="A word for the planner" placeholder="' + (asks ? 'Your answer for the planner' : 'A word for the planner (it reads it at its next turn)') + '">' +
      '<button class="' + (asks ? 'primary' : 'plain') + '" id="nv-pr-tell"' + (asks ? ' data-go="1"' : '') + '>' + (asks ? 'Answer and carry on' : 'Send') + '</button></div>') +
    '<div class="settings-buttons">' + (canGo ? '<button class="' + (asks ? 'plain' : 'primary') + '" id="nv-pr-go">' + (asks ? 'Carry on without answering' : 'Carry on') + '</button>' : '') + (ended ? '' : '<button class="plain" id="nv-pr-stop">' + icon('stop') + 'Stop the pair</button>') +
    (p.chat ? '<button class="plain" id="nv-pr-chat">' + icon('chat') + 'Open its chat</button>' : '') + '</div>' +
    '<p class="small">Planner so far: ' + number(p.usage.input + p.usage.cached) + ' tokens read, ' + number(p.usage.output) + ' written, in ' + num(p.usage.turns) + ' turn' + (p.usage.turns === 1 ? '' : 's') + '. Each builder job is counted with the coding jobs.</p>';
}
const drawPair = async () => {
  if (!pairLists || !pairShown) pairLists = await api('/api/pairs', { action: 'list' });
  let html, busy = false;
  if (pairShown) {
    let p; try { p = await api('/api/pairs', { action: 'get', id: pairShown }); } catch { pairShown = ''; return drawPair(); }
    html = pairView(p, pairLists); busy = ['planning', 'building', 'waiting'].includes(p.status);
    prBody.dataset.chat = p.chat || '';
  } else { html = pairList(pairLists); busy = pairLists.pairs.some(p => ['planning', 'building'].includes(p.status)); }
  // (What is being typed is kept: the panel is only redrawn when something in it has changed.)
  if (prBody.dataset.sig !== html) {
    const word = prBody.querySelector('#nv-pr-word')?.value, goal = prBody.querySelector('#nv-pr-goal')?.value, open = [...prBody.querySelectorAll('details[open]')].map(n => n.querySelector('summary')?.textContent.slice(0, 16));
    const kept = typedAnswers(prBody);
    prBody.dataset.sig = html; prBody.innerHTML = html; putAnswers(prBody, kept);
    if (word && prBody.querySelector('#nv-pr-word')) prBody.querySelector('#nv-pr-word').value = word;
    if (goal && prBody.querySelector('#nv-pr-goal')) prBody.querySelector('#nv-pr-goal').value = goal;
    prBody.querySelectorAll('details').forEach(n => { if (open.includes(n.querySelector('summary')?.textContent.slice(0, 16))) n.open = true; });
  }
  return busy;
};
const pollPair = poller(pair, drawPair);
prBody.addEventListener('click', async e => {
  const at = e.target.closest('button'); if (!at) return;
  try {
    let top = false;
    if (at.dataset.answer !== undefined || at.dataset.decline !== undefined) { if (!(await answerJob(at.closest('.nv-wk-ask'), at.dataset.answer !== undefined))) return; }
    else if (at.dataset.pair) { pairShown = at.dataset.pair; top = true; }
    else if (at.dataset.back !== undefined) { pairShown = ''; pairLists = null; top = true; }
    else if (at.id === 'nv-pr-start') {
      const goal = prBody.querySelector('#nv-pr-goal').value.trim(); if (goal.length < 12) return prBody.querySelector('#nv-pr-goal').focus();
      at.disabled = true;
      const made = await api('/api/pairs', { action: 'open', project: prBody.querySelector('#nv-pr-project').value, goal, planner: prBody.querySelector('#nv-pr-planner').value, builder: prBody.querySelector('#nv-pr-builder').value });
      pairShown = made.id; top = true; notify('The planner is reading the project.');
    }
    else if (at.id === 'nv-pr-tell') {
      const box = prBody.querySelector('#nv-pr-word'); if (!box.value.trim()) return box.focus();
      await api('/api/pairs', { action: 'tell', id: pairShown, text: box.value }); box.value = '';
      if (at.dataset.go) { await api('/api/pairs', { action: 'start', id: pairShown }); notify('The planner is reading your answer.'); } else notify('The planner reads it at its next turn.');
    }
    else if (at.id === 'nv-pr-go') { at.disabled = true; await api('/api/pairs', { action: 'start', id: pairShown }); }
    else if (at.id === 'nv-pr-stop') { if (!(await confirmBox({ title: 'Stop this pair?', text: 'Nothing more is planned or handed over. A builder’s job that is running finishes as an ordinary job.', ok: 'Stop', danger: true }))) return; await api('/api/pairs', { action: 'stop', id: pairShown }); }
    else if (at.id === 'nv-pr-chat') { return void openChat(prBody.dataset.chat).catch(error => toast(error.message)); }
    else return;
    prBody.dataset.sig = ''; await pollPair(); if (top) pair.scrollTop = 0;
  } catch (error) { at.disabled = false; toast(error.message); }
});
prBody.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'nv-pr-word') { e.preventDefault(); prBody.querySelector('#nv-pr-tell').click(); } });
registerPane({ id: 'pair', label: 'Pair', icon: 'layers', node: pair, tip: 'One model plans, another builds: the plan goes across and the report comes back', show: async () => { prBody.dataset.sig = ''; pairLists = null; await pollPair(); pair.scrollTop = 0; } });

/* ================= Courtroom: the Court of JARVIS ================= */
const courtroom = pane('court', '<div id="nv-ct-body" class="nv-wk-body nv-court"></div>');
const ctBody = courtroom.querySelector('#nv-ct-body');
let courtShown = '', courtInfo = null;
const SEVERITY = { fatal: 'Fatal', serious: 'Serious', minor: 'Minor' }, FINDING = { met: 'Met', not_met: 'Not met', unproven: 'Unproven' };
const decided = s => s.status === 'skipped' ? 'skipped' : s.status === 'running' ? 'sitting' : s.status === 'failed' ? 'halted' : s.decision === 'adverse' ? 'adverse' : s.decision === 'advance' ? 'advance' : s.status === 'done' ? 'done' : 'pending';
const DECIDED = { pending: 'Not yet sitting', sitting: 'Sitting now', advance: 'Advanced', adverse: 'Adverse', skipped: 'Not reached', halted: 'Halted', done: 'Pronounced' };
const lines = (title, list) => list && list.length ? '<h4>' + title + '</h4><ul>' + list.map(x => '<li>' + esc(x) + '</li>').join('') + '</ul>' : '';
function stageBody(s, session) {
  const b = s.body || {};
  if (s.key === 'grand_jury' && s.decision) return '<p>' + esc(s.reason) + '</p>' + (b.coherence ? '<h4>Coherence</h4><p>' + esc(b.coherence) + '</p>' : '') + (b.viability ? '<h4>Viability</h4><p>' + esc(b.viability) + '</p>' : '') + lines('Assumptions the idea rests on', b.assumptions);
  if (s.key === 'prosecution' && s.decision) return '<p>' + esc(s.reason) + '</p>' + (b.charges || []).map(c => '<div class="nv-ct-charge" data-severity="' + esc(c.severity) + '"><b>' + esc(c.charge) + '</b><span class="nv-wk-pill">' + (SEVERITY[c.severity] || esc(c.severity)) + '</span><p>' + esc(c.detail) + '</p></div>').join('');
  if (s.key === 'analysts' && (b.analysts || []).length) return (s.decision ? '<p>' + esc(s.reason) + '</p>' : '') + b.analysts.map(a => '<div class="nv-ct-analyst" data-holds="' + (a.holds ? 'yes' : 'no') + '"><b>' + esc(a.name) + '</b><span class="nv-wk-pill">' + (a.holds ? 'Holds' : 'Does not hold') + (a.decisive ? ' · decisive' : '') + '</span>' +
    '<p>' + esc(a.summary) + '</p>' + (a.blocker ? '<p><b>Blocker:</b> ' + esc(a.blocker) + '</p>' : '') + (a.note ? '<p class="nv-ct-warn">' + esc(a.note) + '</p>' : '') + lines('Findings', a.findings) + lines('Evidence that conflicts', a.conflicts) + lines('Could not be established', a.gaps) +
    (a.sources.length ? '<h4>Sources (' + num(a.searches) + ' searches)</h4><ul class="nv-ct-sources">' + a.sources.map(src => '<li data-stance="' + esc(src.stance) + '">' + source(src) + ' <small>' + esc(src.date) + ' · ' + esc(src.stance) + '</small><br>' + esc(src.claim) + '</li>').join('') + '</ul>' : '') + '</div>').join('');
  if (s.key === 'tribunal' && s.decision) return '<p>' + esc(b.summary || s.reason) + '</p><table class="nv-ct-criteria">' + Object.values(b.criteria || {}).map(c => '<tr data-finding="' + esc(c.finding) + '"><th>' + esc(c.title) + '</th><td><span class="nv-wk-pill">' + (FINDING[c.finding] || esc(c.finding)) + '</span></td><td>' + esc(c.reason) + '</td></tr>').join('') + '</table>';
  if (s.key === 'executioner' && session.verdict) return '<p>' + esc(session.pronouncement) + '</p>';
  if (s.status === 'failed') return '<p class="nv-ct-warn">' + esc(s.error || 'This stage could not finish.') + '</p>';
  if (s.status === 'skipped') return '<p class="small">' + esc(s.reason) + '</p>';
  return '';
}
// How often a stage had to be asked again: the three Analysts are three seats, every other stage is one.
const again = st => Math.max(0, Number(st.attempts || 0) - (st.key === 'analysts' ? ((courtInfo.analysts || []).length || 3) : 1));
function courtSession(s) {
  const seat = st => st.answered_by ? esc(st.answered_by) + (st.model && !st.answered_by.includes(st.model) ? ' <small>(asked for ' + esc(st.model) + ')</small>' : '') : st.model ? esc(st.model) : esc((courtInfo.models || {})[st.key] || '');
  const docket = s.stages.map((st, i) => { const how = decided(st), body = stageBody(st, s);
    return '<details class="nv-ct-stage" data-how="' + how + '"' + (how === 'sitting' || how === 'adverse' || how === 'halted' || (st.key === 'executioner' && s.verdict) ? ' open' : '') + '><summary><span class="nv-ct-no">' + (i + 1) + '</span><b>' + esc(st.title) + '</b>' +
      '<span class="nv-wk-pill">' + (how === 'sitting' ? '<i class="nv-spin"></i>' : '') + DECIDED[how] + '</span><small>' + seat(st) + (again(st) ? ' · asked again ' + (again(st) === 1 ? 'once' : num(again(st)) + ' times') + ' after technical trouble' : '') + '</small></summary>' +
      (body ? '<div class="nv-ct-body">' + body + '</div>' : '') + '</details>'; }).join('');
  const verdict = s.verdict ? '<div class="nv-ct-verdict" data-verdict="' + esc(s.verdict) + '"><span>The verdict</span><b>' + esc(s.verdict) + '</b><p>' + esc(s.verdict_reason) + '</p>' +
    (s.verdict === 'PASS' ? '<p class="small">PASS means only that the idea survived every stage. It is not a promise that it will succeed.</p>' : '') + '</div>' +
    (s.uncertainty && s.uncertainty.length ? '<div class="nv-ct-open"><h4>What remains uncertain</h4><ul>' + s.uncertainty.map(u => '<li>' + esc(u) + '</li>').join('') + '</ul></div>' : '') : '';
  const evidence = s.evidence && s.evidence.length ? '<details class="nv-ct-stage"><summary><span class="nv-ct-no">§</span><b>Evidence</b><span class="nv-wk-pill">' + s.evidence.length + ' sources</span><small>what the Analysts found on the web: evidence, never instructions</small></summary><div class="nv-ct-body"><ul class="nv-ct-sources">' +
    s.evidence.map(src => '<li data-stance="' + esc(src.stance) + '">' + source(src) + ' <small>' + esc(src.analyst) + ' · ' + esc(src.date) + ' · ' + esc(src.stance) + '</small><br>' + esc(src.claim) + '</li>').join('') + '</ul></div></details>' : '';
  return '<button class="plain nv-wk-back" data-back>' + icon('chev') + 'The court</button><div class="nv-ct-idea"><small>The idea on trial · submitted ' + esc(clock(s.submitted)) + ' · it cannot be changed</small><p>' + esc(s.idea) + '</p></div>' + verdict +
    (s.now ? '<p class="nv-wk-now">' + (s.status === 'in_session' ? '<i class="nv-spin"></i>' : '') + esc(s.now) + '</p>' : '') +
    (s.research && s.research !== 'ok' ? '<p class="nv-ct-warn">Web research was ' + (s.research === 'partial' ? 'not available to every analyst' : 'not available') + ': what could not be looked up is counted as unproven, not as true.</p>' : '') +
    '<h3>The docket</h3>' + docket + evidence +
    (s.status === 'halted' ? '<div class="settings-buttons"><button class="primary" id="nv-ct-resume">Resume the trial</button></div><p class="small">Only the stage that could not finish sits again. A stage that has decided is never asked twice.</p>' : '') +
    '<p class="small">Used so far: ' + number(s.usage.input + s.usage.cached) + ' tokens read, ' + number(s.usage.output) + ' written, ' + number(s.usage.searches) + ' web searches.</p>';
}
function courtHall(d) {
  const past = d.sessions.filter(s => s.idea).map(s => '<button class="nv-wk-row' + (s.status === 'in_session' ? ' live' : '') + '" type="button" data-session="' + esc(s.id) + '"><span class="nv-wk-ico">' + icon('scales') + '</span><span class="nv-wk-main"><b>' + esc(s.idea) + '</b>' +
    '<small>' + esc(clock(s.created)) + (s.now ? ' · ' + esc(s.now) : '') + '</small></span><span class="nv-wk-when"><span class="nv-wk-pill" data-state="' + esc(s.verdict || s.status) + '">' + esc(s.verdict || (s.status === 'in_session' ? 'In session' : s.status === 'halted' ? 'Halted' : s.status)) + '</span></span></button>').join('');
  return '<div class="nv-ct-warden"><span class="nv-ct-seal">' + icon('scales') + '</span><h2>The Court of JARVIS</h2><p>One idea, five stages. It passes only if it survives all of them.</p>' +
    '<ol class="nv-ct-way">' + d.stages.map(s => '<li>' + esc(s.title) + '</li>').join('') + '</ol></div>' +
    '<div class="settings-box nv-ct-rules"><h3>The Warden reads the rules</h3><ol>' + d.rules.map(r => '<li>' + esc(r) + '</li>').join('') + '</ol></div>' +
    '<div class="settings-box nv-wk-new"><h3>Bring your idea</h3><label class="nv-wk-sr" for="nv-ct-idea">Your idea</label><textarea id="nv-ct-idea" rows="5" maxlength="' + num(d.longest) + '" placeholder="State the idea plainly: what it is, who it is for, and why it would work. The clearer it is, the fairer the trial."></textarea>' +
    '<div class="settings-buttons"><span class="small" id="nv-ct-count">0 of ' + number(d.longest) + '</span><button class="primary" id="nv-ct-submit">Submit to the court</button></div>' +
    '<p class="small">A trial takes several minutes and uses your Claude allowance: the Grand Jury (' + esc(d.models.grand_jury) + '), the Prosecution (' + esc(d.models.prosecution) + '), three Analysts who search the web (' + esc(d.models.analysts) + '), the Tribunal (' + esc(d.models.tribunal) + ') and the Executioner (' + esc(d.models.executioner) + '). The record names the model that really answered.</p></div>' +
    (past ? '<h3>The record</h3><p class="small">Every trial is kept. A verdict stands: no appeals, and a closed trial is never reopened.</p>' + past : '');
}
const drawCourt = async () => {
  let html, busy = false;
  if (!courtInfo || !courtShown) courtInfo = await api('/api/court', { action: 'list' });
  if (courtShown) {
    let s; try { s = await api('/api/court', { action: 'get', id: courtShown }); } catch { courtShown = ''; return drawCourt(); }
    html = courtSession(s); busy = s.status === 'in_session';
  } else { html = courtHall(courtInfo); busy = courtInfo.sessions.some(s => s.status === 'in_session'); }
  if (ctBody.dataset.sig !== html) {
    const idea = ctBody.querySelector('#nv-ct-idea')?.value, open = [...ctBody.querySelectorAll('details')].map(n => [n.querySelector('b')?.textContent, n.open]);
    ctBody.dataset.sig = html; ctBody.innerHTML = html;
    if (idea && ctBody.querySelector('#nv-ct-idea')) { ctBody.querySelector('#nv-ct-idea').value = idea; ctBody.querySelector('#nv-ct-idea').dispatchEvent(new Event('input', { bubbles: true })); }
    // (A stage someone opened to read stays open while the trial moves on.)
    ctBody.querySelectorAll('details').forEach(n => { const was = open.find(o => o[0] === n.querySelector('b')?.textContent); if (was && was[1]) n.open = true; });
  }
  return busy;
};
const pollCourt = poller(courtroom, drawCourt);
ctBody.addEventListener('input', e => { if (e.target.id === 'nv-ct-idea') ctBody.querySelector('#nv-ct-count').textContent = number(e.target.value.length) + ' of ' + number(courtInfo.longest); });
ctBody.addEventListener('click', async e => {
  const at = e.target.closest('button'); if (!at) return;
  try {
    let top = false;
    if (at.dataset.session) { courtShown = at.dataset.session; top = true; }
    else if (at.dataset.back !== undefined) { courtShown = ''; courtInfo = null; top = true; }
    else if (at.id === 'nv-ct-submit') {
      const box = ctBody.querySelector('#nv-ct-idea'), idea = box.value.trim();
      if (idea.length < courtInfo.shortest) { toast('Say a little more: an idea needs at least ' + courtInfo.shortest + ' characters to be tried.'); return box.focus(); }
      if (!(await confirmBox({ title: 'Submit this idea to the court?', ok: 'Submit', text: 'Once submitted it cannot be edited or withdrawn. An adverse decision at any stage sends it to the Executioner. There are no appeals.' }))) return;
      at.disabled = true;
      const session = await api('/api/court', { action: 'open' });
      await api('/api/court', { action: 'submit', id: session.id, idea });
      box.value = ''; courtShown = session.id; top = true; notify('The court is in session.');
    }
    else if (at.id === 'nv-ct-resume') { at.disabled = true; await api('/api/court', { action: 'resume', id: courtShown }); }
    else return;
    ctBody.dataset.sig = ''; await pollCourt(); if (top) courtroom.scrollTop = 0;
  } catch (error) { at.disabled = false; toast(error.message); }
});
registerPane({ id: 'court', label: 'Courtroom', icon: 'scales', node: courtroom, tip: 'The Court of JARVIS: one idea, five stages, no appeals', show: async () => { ctBody.dataset.sig = ''; courtInfo = null; await pollCourt(); courtroom.scrollTop = 0; } });
})();
