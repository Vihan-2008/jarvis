/* NOVA Security panel: check a project for the usual holes, then have the chosen ones fixed by a coding job in its own
   copy of the project (jcc/security_check.py). Everything a scan says (titles, file names, the lines found, a diff) is
   data from the project: it reaches the page only through esc(), and every count only through num(). */
(() => {
'use strict';
const N = window.Nova; if (!N) return;
const { icon, el, notify, confirmBox, registerPane } = N;
const num = v => String(Math.round(Number(v)) || 0);
const secs = v => { const n = Number(v); return isFinite(n) && n > 0 ? (n < 10 ? n.toFixed(1) : String(Math.round(n))) : '0'; };
const clock = at => at ? new Date(at * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '';
const LEVELS = [['high', 'High'], ['medium', 'Medium'], ['low', 'Low']];
const shown = node => !node.classList.contains('hidden') && node.isConnected;
// Asks again every little while, but only while the panel is showing (as in nova-work.js).
function poller(node, draw, quick = 2500, slow = 8000) {
  let timer = 0;
  const tick = async () => { clearTimeout(timer); if (!shown(node)) return; let busy = false; try { busy = await draw(); } catch (error) { toast(error.message); } timer = setTimeout(tick, busy ? quick : slow); };
  return tick;
}

const node = el('section', { id: 'tool-nvsecurity', class: 'tool-content nv-pane nv-wk hidden' },
  '<div class="tool-heading"><div><h2>Security check</h2><p>JARVIS reads a project’s files, looks for the usual holes, and can fix the ones you choose in its own copy of the project.</p></div></div><div id="nv-sec-body" class="nv-wk-body nv-sec"></div>');
N.panel.append(node);
const box = node.querySelector('#nv-sec-body');

let info = null;          // {projects, scans}
let project = '';         // the project chosen
let open = '';            // the id of the check being shown
let scan = null;          // that check, with its fix's state
let ticks = new Set();    // the findings ticked
let working = false;      // a check is running now
let diff = null;          // the changes of the fix, once asked for
let revision = '';        // which state of the fixed copy those changes are (what Apply applies is what was shown)
let compared = null;      // what a second check said

function choose() {
  if (!info.projects.length) return '<div class="settings-box nv-wk-new"><p>A security check works on a project. Connect a project folder first (Files, then “Connect a folder”).</p></div>';
  if (!info.projects.some(p => p.key === project)) project = info.projects[0].key;
  return '<div class="settings-box nv-wk-new"><label>Project<select id="nv-sec-project">' +
    info.projects.map(p => '<option value="' + esc(p.key) + '"' + (p.key === project ? ' selected' : '') + '>' + esc(p.name) + '</option>').join('') + '</select></label>' +
    '<p class="small">It only reads the files. Nothing from the project is run or installed, and nothing is sent anywhere.</p>' +
    '<div class="settings-buttons"><button class="primary" id="nv-sec-run"' + (working ? ' disabled' : '') + '>' + icon('shield') + 'Check this project</button></div></div>' +
    (working ? '<p class="nv-wk-now"><i class="nv-spin"></i>Reading the project’s files. This takes a few seconds.</p>' : '');
}

function summary(s) {
  const counts = LEVELS.map(([key, label]) => num(s.findings.filter(f => f.severity === key).length) + ' ' + label.toLowerCase()).join(', ');
  const kind = (s.stack || []).length ? (s.stack || []).map(esc).join(', ') : 'No known kind of code';
  return '<div class="nv-sec-head"><b>' + esc(s.name) + (s.where === 'copy' ? ' (the fixed copy)' : '') + '</b><small>' + esc(clock(s.at)) + ' · ' + kind + '</small></div>' +
    '<p class="nv-sec-sum">' + (s.findings.length ? counts : 'Nothing found by these rules') + ' · ' + num(s.files) + ' files read · ' + secs(s.took) + ' s</p>' +
    (s.truncated ? '<p class="nv-sec-warn">' + esc(s.stopped || 'It stopped early.') + ' Files after that point were not checked, so no findings there does not mean none.</p>' : '') +
    (s.skipped && (s.skipped.large || s.skipped.binary || s.skipped.links) ? '<p class="small">Not read: ' + num(s.skipped.large) + ' files over 1 MB, ' + num(s.skipped.binary) + ' binary files, ' +
      num(s.skipped.links) + ' links that point elsewhere.</p>' : '');
}

function checked(s) {
  return '<details class="nv-wk-hand nv-sec-scanners"><summary><b>What was checked</b></summary><ul>' + (s.scanners || []).map(c =>
    '<li data-ran="' + (c.ran ? 'yes' : 'no') + '"><span class="nv-sec-mark">' + icon(c.ran ? 'check' : 'minus') + '</span><span><b>' + esc(c.name) + '</b>' +
    (c.ran ? ' <span class="nv-wk-n">' + num(c.findings) + '</span>' : '') + '<small>' + esc(c.covers) + '</small>' + (c.ran ? '' : '<small class="nv-sec-why">' + esc(c.why_not) + '</small>') + '</span></li>').join('') + '</ul>' +
    '<p class="small">This is a first pass with fixed rules. It finds well-known patterns, not every problem, and it leaves out what it is unsure of rather than raise false alarms.</p></details>';
}

function findings(s) {
  const fixing = new Set((s.fix && s.fix.findings) || []), locked = !!s.fix || s.where === 'copy';
  return LEVELS.map(([key, label]) => {
    const rows = s.findings.filter(f => f.severity === key);
    if (!rows.length) return '';
    return '<h3>' + label + ' <span class="nv-wk-n">' + num(rows.length) + '</span></h3>' + rows.map(f =>
      '<div class="nv-sec-find" data-severity="' + key + '"><label><input type="checkbox" data-finding="' + esc(f.id) + '"' + ((locked ? fixing.has(f.id) : ticks.has(f.id)) ? ' checked' : '') + (locked ? ' disabled' : '') + '>' +
      '<b>' + esc(f.title) + '</b></label><small>' + esc(f.file) + ':' + num(f.line) + '</small>' + (f.evidence ? '<code>' + esc(f.evidence) + '</code>' : '') +
      '<details><summary>Why it matters and how to fix it</summary><p>' + esc(f.why) + '</p><p>' + esc(f.fix) + '</p></details></div>').join('');
  }).join('');
}

function comparison(s) {
  if (!compared) return '';
  const mine = new Set((s.fix && s.fix.findings) || s.findings.map(f => f.id));
  const gone = compared.fixed.filter(id => mine.has(id)).length, all = [...mine].length;
  const still = s.findings.filter(f => compared.still.includes(f.id) && mine.has(f.id));
  const line = f => '<li>' + esc(f.title) + ' <small>' + esc(f.file) + ':' + num(f.line) + '</small></li>';
  return '<div class="settings-box nv-sec-compare"><b>' + num(gone) + ' of ' + num(all) + ' are gone</b>' +
    (compared.scan.where === 'copy' ? ' <small>in the fixed copy</small>' : ' <small>in the project</small>') +
    (still.length ? '<p class="small">Still there:</p><ul>' + still.map(line).join('') + '</ul>' : '') +
    (compared.new.length ? '<p class="small">New since the first check:</p><ul>' + compared.new.map(line).join('') + '</ul>' : '') + '</div>';
}

function fixing(s) {
  const state = s.state || { status: 'none' }, chat = state.chat ? '<button class="plain" id="nv-sec-chat">' + icon('chat') + 'Open its chat</button>' : '';
  if (s.where === 'copy') return '';
  if (state.status === 'none') return '<div class="settings-buttons nv-sec-go"><span class="small">' + num(ticks.size) + ' selected</span><button class="primary" id="nv-sec-fix"' + (ticks.size ? '' : ' disabled') + '>' + icon('spark') + 'Fix the selected with JARVIS</button></div>';
  const changes = diff === null ? '' : '<pre class="nv-sec-diff">' + esc(diff || 'No changes to show.') + '</pre>';
  const say = {
    working: '<p class="nv-wk-now"><i class="nv-spin"></i>JARVIS is fixing ' + num(((s.fix && s.fix.findings) || []).length) + ' findings in its own copy of the project.</p><div class="settings-buttons">' + chat + '</div>',
    ready: '<p class="nv-sec-ok">The fix is ready to look at. It has passed the project’s checks in its copy; nothing is in your project yet.</p><div class="settings-buttons nv-sec-actions">' +
      '<button class="plain" id="nv-sec-diff">' + icon('code') + 'Show the changes</button><button class="plain" id="nv-sec-copy">' + icon('search') + 'Scan the fixed copy</button>' +
      '<button class="primary" id="nv-sec-apply"' + (revision ? '' : ' disabled title="Show the changes first: what is applied is what you were shown"') + '>' + icon('check') + 'Apply to the project</button>' + chat + '</div>' +
      (revision ? '' : '<p class="small">Show the changes first. What is applied is exactly what you were shown.</p>'),
    applied: '<p class="nv-sec-ok">The fix is applied to the project.</p><div class="settings-buttons nv-sec-actions"><button class="plain" id="nv-sec-diff">' + icon('code') + 'Show the changes</button>' +
      '<button class="plain" id="nv-sec-again">' + icon('search') + 'Scan the project again</button><button class="plain" id="nv-sec-undo">' + icon('retry') + 'Undo the fix</button>' + chat + '</div>',
    asked: '<p class="nv-sec-warn">JARVIS stopped and asks you something. Its question, with a way to answer, is under Agents.</p><div class="settings-buttons">' +
      '<button class="plain" id="nv-sec-agents">' + icon('pulse') + 'Open Agents</button>' + chat + '</div>',
    failed: '<p class="nv-sec-warn">The fix did not finish. Nothing was changed in your project.</p><div class="settings-buttons">' + chat + '</div>',
    undone: '<p class="small">The fix was undone. Your project is as it was before it.</p><div class="settings-buttons">' + chat + '</div>',
  }[state.status] || '';
  return '<div class="settings-box nv-sec-fixbox"><h3>The fix</h3>' + say + changes + '</div>';
}

function past() {
  const rows = info.scans.filter(s => s.project === project).slice(0, 20).map(s => '<button class="nv-wk-row" type="button" data-scan="' + esc(s.id) + '"><span class="nv-wk-ico">' + icon('shield') + '</span>' +
    '<span class="nv-wk-main"><b>' + esc(clock(s.at)) + (s.where === 'copy' ? ' · the fixed copy' : '') + '</b><small>' + num(s.counts.high) + ' high, ' + num(s.counts.medium) + ' medium, ' + num(s.counts.low) + ' low · ' + num(s.files) + ' files</small></span>' +
    '<span class="nv-wk-when">' + (s.fix ? '<span class="nv-wk-pill" data-state="running">Fix started</span>' : '') + '</span></button>').join('');
  return rows ? '<h3>Earlier checks of this project</h3>' + rows : '';
}

function render() {
  // Once a fix has been started it is what matters: it and what a second check said are shown first, above the findings
  // (they used to sit below the whole list, out of sight).
  const started = !!(scan && scan.state && scan.state.status && scan.state.status !== 'none');
  const html = choose() + (scan ? '<div class="nv-sec-scan">' + summary(scan) + (started ? fixing(scan) + comparison(scan) : '') + checked(scan) + findings(scan) +
    (started ? '' : fixing(scan) + comparison(scan)) + '</div>' : '') + past();
  if (box.dataset.sig !== html) { box.dataset.sig = html; box.innerHTML = html; }
}

async function show(id) {
  const fresh = id !== open;
  open = id; scan = await api('/api/security', { action: 'get', id });
  if (fresh) { ticks = new Set(scan.findings.filter(f => f.severity !== 'low').map(f => f.id)); diff = null; revision = ''; compared = null; project = scan.project; }
}

const draw = async () => {
  if (!info) info = await api('/api/security', { action: 'list' });
  if (open) await show(open);
  render();
  return working || !!(scan && scan.state && scan.state.status === 'working');
};
const poll = poller(node, draw);

box.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'nv-sec-project') { project = t.value; open = ''; scan = null; render(); return; }
  if (t.dataset && t.dataset.finding !== undefined) { if (t.checked) ticks.add(t.dataset.finding); else ticks.delete(t.dataset.finding); render(); }
});

box.addEventListener('click', async e => {
  const at = e.target.closest('button'); if (!at) return;
  try {
    if (at.dataset.scan) { await show(at.dataset.scan); }
    else if (at.id === 'nv-sec-run') {
      const picked = box.querySelector('#nv-sec-project').value || project;
      working = true; render();
      try { const made = await api('/api/security', { action: 'scan', project: picked }); project = picked; info = null; open = ''; await show(made.id); }
      finally { working = false; }
      if (!info) info = await api('/api/security', { action: 'list' });
    }
    else if (at.id === 'nv-sec-fix') {
      if (!ticks.size) return;
      if (!(await confirmBox({ title: 'Fix ' + num(ticks.size) + ' findings with JARVIS?', ok: 'Start the fix',
        text: 'A coding agent will change a copy of the project, not the project itself. Nothing is applied until the change has passed the project’s checks and you have looked at it.' }))) return;
      at.disabled = true;
      await api('/api/security', { action: 'fix', id: open, findings: [...ticks] });
      notify('JARVIS is fixing them in its own copy of the project.'); info = null; await show(open);
    }
    else if (at.id === 'nv-sec-chat') { return void openChat(scan.state.chat).catch(error => toast(error.message)); }
    else if (at.id === 'nv-sec-diff') { const seen = await api('/api/security', { action: 'preview', id: open }); diff = seen.patch; revision = String(seen.revision || ''); }
    else if (at.id === 'nv-sec-agents') { return void N.openPane('agents'); }
    else if (at.id === 'nv-sec-copy' || at.id === 'nv-sec-again') {
      at.disabled = true;
      compared = await api('/api/security', { action: 'rescan', id: open, where: at.id === 'nv-sec-copy' ? 'copy' : 'project' }); info = null;
    }
    else if (at.id === 'nv-sec-apply') {
      if (!revision) return;
      at.disabled = true; await api('/api/security', { action: 'apply', id: open, revision }); notify('The fix is applied to the project.'); diff = null; revision = ''; compared = null; await show(open);
    }
    else if (at.id === 'nv-sec-undo') {
      if (!(await confirmBox({ title: 'Undo the fix?', ok: 'Undo', danger: true, text: 'JARVIS adds a change that takes the fix back out, after the project’s checks pass. Nothing is thrown away: both changes stay in the history.' }))) return;
      at.disabled = true; await api('/api/security', { action: 'undo', id: open }); notify('The fix was undone.'); compared = null; await show(open);
    }
    else return;
    box.dataset.sig = ''; await poll();
  } catch (error) { at.disabled = false; toast(error.message); render(); }
});

registerPane({ id: 'security', label: 'Security', icon: 'shield', node, tip: 'Check a project for the usual holes, and have them fixed in a copy', show: async () => { box.dataset.sig = ''; info = null; await poll(); node.scrollTop = 0; } });
})();
