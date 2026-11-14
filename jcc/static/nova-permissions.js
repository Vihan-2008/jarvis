/* NOVA permissions: the mode chip in the message bar (Claude Code's modes: Auto, Manual, Accept edits, Plan, Bypass
   permissions) and, at the end of a chat, a card for whatever in that chat waits for its owner (jcc/permissions.py):
   something the assistant is holding in the middle of a reply, a coding job with a question (the same job carries on),
   a finished change to keep or throw away, or a job held for what it mentions. Each card has its answers on it; the
   work carries on as soon as it is answered, and nothing stops while it waits.

   Everything shown from a request (its question, its details, a job's own words, a diff) is data: it reaches the page
   only through esc(). A yes to a job carries the mark of the question as it stands on the screen, and Keep carries the
   state of the change that the card showed, so neither is ever taken for something that was not shown. */
(() => {
'use strict';
const N = window.Nova; if (!N) return;
const { icon, el, notify, confirmBox, openPop, closePop } = N;
const bar = document.querySelector('.nv-bar'); if (!bar) return;
const ORDER = ['sending', 'all', 'edits', 'plan', 'bypass'];
const NAMES = { sending: 'Auto', all: 'Manual', edits: 'Accept edits', plan: 'Plan', bypass: 'Bypass permissions', risky: 'Ask before risky things' };
const GLYPH = { sending: 'spark', all: 'shield', edits: 'edit', plan: 'note', bypass: 'arrow', risky: 'shield' };
const KIND_GLYPH = { assistant: 'shield', job: 'help', review: 'check', blocked: 'shield', plan: 'note' };
const QUICK = 2500, SLOW = 6000;
let info = { mode: 'sending', modes: [], pending: [], more: 0 }, drawn = '', drawnCards = '', timer = 0, failed = false;
const changes = new Map();                 // a job's change as its card showed it: { revision, files, plus, minus, html }
const planDone = new Set();                // replies whose "Go ahead with this plan?" was answered or put aside

const button = el('button', { class: 'nv-chip nv-perm', type: 'button', 'aria-haspopup': 'menu', 'aria-label': 'Mode' },
  icon('spark') + '<span class="nv-perm-name">Auto</span><b class="nv-perm-n hidden"></b>');
const after = bar.children[1];
if (after) after.after(button); else bar.prepend(button);

const openChatId = () => { try { return String(current || ''); } catch { return ''; } };          // (the chat on screen)
const openChatNow = () => { try { return chat || null; } catch { return null; } };
const count = () => info.pending.length + (Math.round(Number(info.more)) || 0);
const isOpen = () => button.getAttribute('aria-expanded') === 'true';
const signature = () => JSON.stringify([info.mode, info.pending.map(r => [r.kind, r.id, r.mark || '', r.question, r.detail, r.chat]), info.more, failed]);
const modeName = id => (info.modes.find(m => m.id === id) || {}).name || NAMES[id] || NAMES.sending;

function label() {
  const n = count(), name = modeName(info.mode);
  button.innerHTML = icon(GLYPH[info.mode] || 'spark') + '<span class="nv-perm-name"></span><b class="nv-perm-n hidden"></b>';
  button.querySelector('.nv-perm-name').textContent = name;
  const badge = button.querySelector('.nv-perm-n');
  badge.textContent = String(n); badge.classList.toggle('hidden', !n);
  button.dataset.mode = info.mode;
  button.classList.toggle('waiting', n > 0);
  document.body?.classList.toggle('nv-perm-waiting', n > 0);      // (the start screen hides the bar; with something waiting it is shown)
  button.setAttribute('aria-label', 'Mode: ' + name + (n ? '. ' + n + ' waiting for your answer' : ''));
  button.dataset.tip = (n ? n + (n === 1 ? ' thing is' : ' things are') + ' waiting for your answer. ' : '') + 'Mode: ' + name + '. Click to change it (Shift+Tab in the message box).';
}

// The menu: the modes, numbered as in Claude Code, and what waits in other chats.
function fill(p) {
  p.innerHTML = ''; p.classList.add('nv-perm-pop');
  p.append(el('h5', {}, 'Mode'));
  ORDER.forEach((id, i) => {
    const m = info.modes.find(x => x.id === id) || { id, name: NAMES[id], about: '' };
    N.item(p, (i + 1) + '.  ' + m.name, GLYPH[id], () => setMode(id), { note: m.about, tick: info.mode === id, keep: true });
  });
  if (info.mode === 'risky') p.append(el('p', { class: 'small nv-perm-more' }, 'In force now: the older setting "Ask before risky things". Choose one of these to change it.'));
  const here = openChatId(), kids = new Set((() => { try { return (state?.chats || []).filter(c => c.parent === here).map(c => c.id); } catch { return []; } })());
  const elsewhere = info.pending.filter(r => r.chat !== here && !kids.has(r.chat));
  if (elsewhere.length) {
    p.append(el('hr'), el('h5', {}, 'Waiting in other chats'));
    for (const r of elsewhere) N.item(p, r.question, KIND_GLYPH[r.kind] || 'help', () => goTo(r), { note: (r.title || r.detail || '').slice(0, 90) + (r.project ? ' · ' + r.project : '') });
  }
  if (count() > info.pending.length) p.append(el('p', { class: 'small nv-perm-more' }, String(count() - info.pending.length) + ' more are waiting. /work lists them all.'));
  if (failed) p.append(el('p', { class: 'small nv-perm-more' }, 'This list could not be read just now. It is tried again in a moment.'));
  drawn = signature();
}

function goTo(r) {
  closePop();
  if (r.chat) return void openChat(r.chat).then(() => reread(true)).catch(error => toast(error.message));
  showHere([r]);
}

async function setMode(id) {
  if (!ORDER.includes(id)) return;
  if (id !== info.mode) {
    await api('/api/permissions', { action: 'mode', mode: id });
    notify('Mode: ' + NAMES[id] + '. ' + ((info.modes.find(m => m.id === id) || {}).about || ''));
  }
  closePop();
  await reread(true);
}
function cycle() { setMode(ORDER[(ORDER.indexOf(info.mode) + 1) % ORDER.length]).catch(error => toast(error.message)); }

// ---------------------------------------------------------------- the cards
function cardHtml(r) {
  const B = (attr, text, primary) => '<button type="button" class="' + (primary ? 'primary' : 'plain') + '" ' + attr + '>' + esc(text) + '</button>';
  const where = r.title && r.kind !== 'assistant' ? '<small>' + esc(r.title) + (r.project ? ' · ' + esc(r.project) : '') + '</small>' : '';
  let html = '<div class="nv-next-head">' + icon(KIND_GLYPH[r.kind] || 'help') + '<span>' + (r.kind === 'plan' ? 'Your plan is ready' : 'Waiting for your answer') + '</span>' + where + '</div>' +
    '<b class="nv-next-q">' + esc(r.question) + '</b>';
  if (r.detail) html += r.detail.length > 220 ? '<details class="nv-next-more"><summary>' + esc(r.detail.slice(0, 160)) + '…</summary><pre>' + esc(r.detail) + '</pre></details>' : '<p class="nv-next-detail">' + esc(r.detail) + '</p>';
  if (r.why) html += '<small class="nv-next-why">' + esc(r.why) + '</small>';
  if (r.kind === 'review') html += '<div class="nv-next-changes" data-changes>Reading the changes…</div>';
  if (r.kind === 'job') html += '<input class="nv-next-words" placeholder="Add a few words, if you like" aria-label="Your answer">';
  const buttons = r.kind === 'review' ? B('data-no', 'Throw away') + B('data-yes disabled', 'Keep them', true)
    : r.kind === 'blocked' ? (r.can ? B('data-no', 'Cancel') + B('data-yes', 'Go ahead', true) : B('data-no', 'Cancel', true))
    : r.kind === 'job' ? B('data-no', 'No') + B('data-yes', 'Yes, carry on', true)
    : r.kind === 'plan' ? B('data-no', 'Keep planning') + B('data-yes', 'Yes, go ahead', true)
    : B('data-no', 'No') + B('data-yes', 'Yes, do it', true);
  return '<div class="nv-next" data-kind="' + esc(r.kind) + '" data-id="' + esc(r.id) + '" data-mark="' + esc(r.mark || '') + '" data-chat="' + esc(r.chat || '') + '">' + html +
    '<div class="nv-next-buttons">' + buttons + '</div></div>';
}

// What a finished change is, from its diff: how many files, lines added and removed, and the diff itself to look at.
function changeSummary(d) {
  const text = String(d.diff || ''); let plus = 0, minus = 0, inNew = false;
  const lines = text.split('\n').map(line => {
    if (line.startsWith('New file: ')) { inNew = true; return '<span class="hunk">' + esc(line) + '</span>'; }
    if (line.startsWith('diff --git') || line.startsWith('index ') || line.startsWith('+++') || line.startsWith('---')) { inNew = false; return '<span class="meta">' + esc(line) + '</span>'; }
    if (line.startsWith('@@')) return '<span class="hunk">' + esc(line) + '</span>';
    if (line.startsWith('+') || inNew) { plus++; return '<span class="add">' + esc(line) + '</span>'; }
    if (line.startsWith('-')) { minus++; return '<span class="del">' + esc(line) + '</span>'; }
    return esc(line);
  });
  const files = (d.files || []).length;
  return { revision: String(d.revision || ''), files, plus, minus,
    html: '<p class="nv-change-line">' + icon('edit') + '<b>' + (files ? files + (files === 1 ? ' file changed' : ' files changed') : 'Changes') + '</b>' +
      (plus ? '<span class="add">+' + plus + '</span>' : '') + (minus ? '<span class="del">−' + minus + '</span>' : '') + '</p>' +
      (files ? '<details class="nv-diff-box"><summary>' + esc((d.files || []).slice(0, 6).join(', ') + (files > 6 ? ' and ' + (files - 6) + ' more' : '')) + '</summary><pre class="nv-diff">' + lines.join('\n') + '</pre></details>' : '') };
}
async function fillChanges(card) {
  const id = card.dataset.id, spot = card.querySelector('[data-changes]'); if (!spot) return;
  let seen = changes.get(id);
  if (!seen) {
    try { seen = changeSummary(await api('/api/job/details?id=' + encodeURIComponent(id))); changes.set(id, seen); }
    catch (error) { spot.textContent = 'The changes could not be read: ' + error.message; return; }
  }
  spot.innerHTML = seen.html;
  const keep = card.querySelector('[data-yes]'); if (keep) keep.disabled = !seen.revision;
  if (!seen.revision) spot.insertAdjacentHTML('beforeend', '<p class="small">There is no copy left to keep. Throw it away to clear it.</p>');
}

// The card asking to go ahead with a plan: in Plan mode, under the last reply of the chat on screen.
function planCard() {
  const c = openChatNow(); if (info.mode !== 'plan' || !c?.messages?.length) return null;
  const last = c.messages[c.messages.length - 1];
  if (last.role !== 'assistant' || last.status !== 'done' || !last.receipt || planDone.has(last.receipt)) return null;
  return { kind: 'plan', id: last.receipt, chat: c.id, question: 'Go ahead with this plan?', detail: '', why: 'Yes switches to Auto and JARVIS starts. Or keep planning: say what to change.' };
}

function host() {
  const box = document.getElementById ? document.getElementById('messages') : null;
  if (!box || !box.querySelector('.nv-thread')) return null;
  let spot = box.querySelector(':scope > .nv-asks');
  if (!spot) spot = el('div', { class: 'nv-asks', role: 'region', 'aria-label': 'Waiting for your answer' });
  if (spot !== box.lastElementChild) box.append(spot);
  return spot;
}
function drawCards(force) {
  // This chat's own, and those of the work it set going (each piece of work has a chat of its own, under this Master).
  const here = openChatId(), kids = new Set((() => { try { return (state?.chats || []).filter(c => c.parent === here).map(c => c.id); } catch { return []; } })());
  const mine = info.pending.filter(r => r.chat && (r.chat === here || kids.has(r.chat))), plan = planCard();
  if (plan) mine.push(plan);
  const spot = host(); if (!spot) { drawnCards = ''; return; }
  const sig = here + JSON.stringify(mine.map(r => [r.kind, r.id, r.mark || '', r.question, r.detail]));
  if (!force && sig === drawnCards && spot.childElementCount === mine.length) return;
  const typed = {};
  for (const old of spot.querySelectorAll('.nv-next')) { const field = old.querySelector('input'); if (field && field.value) typed[old.dataset.id] = field.value; }
  spot.innerHTML = mine.map(cardHtml).join('');
  for (const card of spot.querySelectorAll('.nv-next')) {
    const field = card.querySelector('input'); if (field && typed[card.dataset.id]) field.value = typed[card.dataset.id];
    if (card.dataset.kind === 'review') fillChanges(card);
  }
  const fresh = sig !== drawnCards && mine.length; drawnCards = sig;
  if (fresh) { const box = document.getElementById('messages'); box.scrollTo?.({ top: box.scrollHeight, behavior: 'smooth' }); }
}
// Cards shown somewhere other than the end of their chat (/work lists everything that waits, in the chat on screen).
function showHere(rows) { return rows.map(cardHtml).join(''); }

async function answer(card, yes) {
  const kind = card.dataset.kind, id = card.dataset.id, buttons = [...card.querySelectorAll('button')];
  if (kind === 'plan') {
    planDone.add(id); card.remove();
    if (!yes) { document.getElementById('message')?.focus(); return notify('Say what to change in the plan.'); }
    await api('/api/permissions', { action: 'mode', mode: 'sending' });
    await reread(true);
    N.setDraft?.('Go ahead with the plan.'); document.getElementById('composer')?.requestSubmit();
    return;
  }
  if (kind === 'review' && !yes && !(await confirmBox({ title: 'Throw these changes away?', text: 'Your project stays exactly as it is. The changes stay in git on a branch of their own, in case you want them later.', ok: 'Throw away', danger: true }))) return;
  if (kind === 'job' && !yes && !(await confirmBox({ title: 'Say no to this?', text: 'The job ends and nothing is changed. If it belongs to a planner and builder, the planner is told you said no.', ok: 'Say no', danger: true }))) return;
  buttons.forEach(x => { x.disabled = true; });                // one answer, once
  try {
    const body = { action: 'decide', kind, id, yes };
    if (kind === 'job') { body.text = card.querySelector('input')?.value || ''; if (yes) body.mark = card.dataset.mark; }
    if (kind === 'review' && yes) body.revision = changes.get(id)?.revision || '';
    await api('/api/permissions', body);
    if (kind === 'assistant') N.confirmAnswered?.(id, yes);
    notify({ assistant: yes ? 'Doing it.' : 'Okay, not that.', job: yes ? 'Answered. The job carries on from where it stopped.' : 'You said no. The job has ended and nothing was changed.',
      review: yes ? 'Kept: the changes are in your project now.' : 'Thrown away. Your project is as it was.', blocked: yes ? 'Started again. It reports in this chat.' : 'Cancelled.' }[kind] || 'Answered.');
    card.remove(); changes.delete(id);
  } catch (error) { toast(error.message); buttons.forEach(x => { x.disabled = false; }); if (kind === 'review') fillChanges(card); }
  await reread(true);
  try { if (typeof refresh === 'function') await refresh(); } catch {}
}
document.addEventListener('click', event => {
  const b = event.target?.closest?.('.nv-next button'); if (!b || b.disabled) return;
  const card = b.closest('.nv-next'); if (!card) return;
  if (b.dataset.yes !== undefined || b.dataset.no !== undefined) answer(card, b.dataset.yes !== undefined).catch(error => toast(error.message));
});

async function reread(redraw) {
  try { info = await api('/api/permissions', { action: 'state' }); failed = false; }
  catch { failed = true; }
  label();
  const p = isOpen() ? document.querySelector('.nv-pop') : null;
  if (p && (redraw || signature() !== drawn)) fill(p);
  try { drawCards(redraw); } catch {}
}

async function tick() {
  clearTimeout(timer);
  if (document.visibilityState !== 'hidden') await reread(false);
  timer = setTimeout(tick, count() || isOpen() || info.mode === 'plan' ? QUICK : SLOW);
}

button.onclick = () => { openPop(button, fill, { up: true }); if (isOpen()) reread(false); };
// 1 to 5 choose a mode while the menu is open; Shift+Tab in the message box goes to the next one (as in Claude Code).
document.addEventListener('keydown', event => {
  if (isOpen() && /^[1-5]$/.test(event.key || '')) { event.preventDefault(); setMode(ORDER[Number(event.key) - 1]).catch(error => toast(error.message)); return; }
  if (event.key === 'Tab' && event.shiftKey && event.target?.id === 'message' && !document.querySelector('.nv-slash:not(.hidden)')) { event.preventDefault(); cycle(); }
});
// When another chat is opened, its cards are drawn at once.
if (typeof renderChat === 'function') {
  const shown = renderChat;
  renderChat = function () { const result = shown.apply(this, arguments); try { drawCards(false); } catch {} return result; };   // eslint-disable-line no-global-assign
}
N.permissionsChanged = () => reread(false);
N.permissionMode = () => info.mode;
N.setPermissionMode = setMode;
N.waiting = () => info.pending.slice();
N.waitingCards = showHere;
N.fillChanges = fillChanges;
N.changeSummary = changeSummary;
label(); tick();
})();
