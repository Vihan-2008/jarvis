/* NOVA permissions control, beside the message box: how much JARVIS asks before it acts, and whatever is waiting for
   its owner's yes or no (jcc/permissions.py). It shows the mode in force, changes it, and answers what is waiting:
   something the assistant is holding in the middle of a reply, a coding job that stopped to ask (the same job carries
   on), or a change that waits to be looked at (that one only leads to where it can be seen).

   Everything shown from a request (its question, its details, a job's own words) is data: it reaches the page only
   through esc(). A yes to a job carries the mark of the question as it stands on the screen, so a yes is never taken
   for a question that was not shown. */
(() => {
'use strict';
const N = window.Nova; if (!N) return;
const { icon, el, notify, confirmBox, openPop, closePop } = N;
const bar = document.querySelector('.nv-bar'); if (!bar) return;
const SHORT = { sending: 'Asks before sending', risky: 'Asks before risky things', all: 'Asks before everything' };
const QUICK = 2500, SLOW = 6000;
let info = { mode: 'sending', modes: [], pending: [], more: 0 }, drawn = '', timer = 0, failed = false;

const button = el('button', { class: 'nv-chip nv-perm', type: 'button', 'aria-haspopup': 'menu', 'aria-label': 'Permissions' },
  icon('shield') + '<span class="nv-perm-name">Asks before sending</span><b class="nv-perm-n hidden"></b>');
const after = bar.children[1];
if (after) after.after(button); else bar.prepend(button);

const count = () => info.pending.length + (Math.round(Number(info.more)) || 0);
const isOpen = () => button.getAttribute('aria-expanded') === 'true';
const signature = () => JSON.stringify([info.mode, info.pending.map(r => [r.kind, r.id, r.mark || '', r.question, r.detail]), info.more, failed]);

function label() {
  const n = count(), name = SHORT[info.mode] || SHORT.sending;
  button.querySelector('.nv-perm-name').textContent = name;
  const badge = button.querySelector('.nv-perm-n');
  badge.textContent = String(n); badge.classList.toggle('hidden', !n);
  button.classList.toggle('waiting', n > 0);
  document.body?.classList.toggle('nv-perm-waiting', n > 0);      // (the start screen hides the bar; with something waiting it is shown)
  button.setAttribute('aria-label', 'Permissions: ' + name + (n ? '. ' + n + ' waiting for your answer' : ''));
  button.dataset.tip = n ? n + (n === 1 ? ' thing is' : ' things are') + ' waiting for your yes or no' : 'How much JARVIS asks before it acts. Nothing is waiting for you.';
}

// One thing that is waiting, as words on the page.
function askHtml(r) {
  const job = r.kind === 'job', review = r.kind === 'review';
  return '<div class="nv-perm-ask" data-kind="' + esc(r.kind) + '" data-id="' + esc(r.id) + '" data-mark="' + esc(r.mark || '') + '" data-chat="' + esc(r.chat || '') + '">' +
    '<b>' + esc(r.question) + '</b>' + (r.title ? '<small>' + esc(r.title) + (r.project ? ' · ' + esc(r.project) : '') + '</small>' : '') +
    (r.detail ? '<p>' + esc(r.detail) + '</p>' : '') + (r.why ? '<small>' + esc(r.why) + '</small>' : '') +
    (job ? '<input maxlength="2000" placeholder="A few words with your answer, if you like" aria-label="Your answer">' : '') +
    '<div class="nv-perm-buttons">' + (review ? '<button class="primary" type="button" data-look>Look at it</button>'
      : '<button class="plain" type="button" data-no>No</button><button class="primary" type="button" data-yes>' + (job ? 'Yes, carry on' : 'Yes') + '</button>') + '</div></div>';
}

function fill(p) {
  const typed = {};       // (what is being typed as an answer is kept while the list is drawn again)
  for (const old of p.querySelectorAll('.nv-perm-ask')) { const field = old.querySelector('input'); if (field && field.value) typed[old.dataset.id] = field.value; }
  p.innerHTML = ''; p.classList.add('nv-perm-pop');
  p.append(el('h5', {}, 'JARVIS asks you first'));
  for (const m of info.modes) N.item(p, m.name, '', () => setMode(m), { note: m.about, tick: m.id === info.mode, keep: true });
  p.append(el('hr'), el('h5', {}, info.pending.length ? 'Waiting for your answer' : 'Nothing is waiting for you'));
  p.append(el('div', { class: 'nv-perm-list' }, info.pending.map(askHtml).join('') +
    (count() > info.pending.length ? '<p class="small nv-perm-more">' + esc(String(count() - info.pending.length)) + ' more are waiting. All of them are under Agents.</p>' : '') +
    (failed ? '<p class="small nv-perm-more">This list could not be read just now. It is tried again in a moment.</p>' : '')));
  for (const box of p.querySelectorAll('.nv-perm-ask')) { const field = box.querySelector('input'); if (field && typed[box.dataset.id]) field.value = typed[box.dataset.id]; }
  if (!p.dataset.wired) {
    p.dataset.wired = '1';
    p.addEventListener('click', event => { const b = event.target.closest('button'), box = b && b.closest('.nv-perm-ask'); if (box) answer(box, b); });
  }
  drawn = signature();
}

async function answer(box, b) {
  const kind = box.dataset.kind, id = box.dataset.id, job = kind === 'job';
  if (b.dataset.look !== undefined) {
    closePop();
    if (box.dataset.chat) return void openChat(box.dataset.chat).catch(error => toast(error.message));
    return void N.openPane('agents');
  }
  const yes = b.dataset.yes !== undefined, buttons = [...box.querySelectorAll('button')];
  if (job && !yes && !(await confirmBox({ title: 'Say no to this?', text: 'The job ends and nothing is changed. If it belongs to a planner and builder, the planner is told you said no.', ok: 'Say no', danger: true }))) return;
  buttons.forEach(x => { x.disabled = true; });                // one answer, once
  try {
    // (The mark is the one of the question as it stands on the screen, not of whatever the job may be asking by now.)
    await api('/api/permissions', { action: 'decide', kind, id, yes, ...(job ? { text: box.querySelector('input').value, ...(yes ? { mark: box.dataset.mark } : {}) } : {}) });
    notify(job ? (yes ? 'Answered. The same job carries on from where it stopped.' : 'You said no. The job has ended and nothing was changed.') : (yes ? 'Allowed, this once.' : 'Not allowed.'));
  } catch (error) { toast(error.message); }                    // (it may be asking something else by now: the list is read again and shows it)
  await refresh(true);
}

async function setMode(m) {
  if (m.id === info.mode) return;
  await api('/api/permissions', { action: 'mode', mode: m.id });
  notify('From now on: ' + m.name.charAt(0).toLowerCase() + m.name.slice(1) + '.');
  await refresh(true);
}

async function refresh(redraw) {
  try { info = await api('/api/permissions', { action: 'state' }); failed = false; }
  catch { failed = true; }
  label();
  const p = isOpen() ? document.querySelector('.nv-pop') : null;
  if (p && (redraw || signature() !== drawn)) fill(p);
}

async function tick() {
  clearTimeout(timer);
  if (document.visibilityState !== 'hidden') await refresh(false);
  timer = setTimeout(tick, count() || isOpen() ? QUICK : SLOW);
}

button.onclick = () => { openPop(button, fill, { up: true }); if (isOpen()) refresh(false); };
N.permissionsChanged = () => refresh(false);
label(); tick();
})();
