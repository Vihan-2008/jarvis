/* NOVA gallery: everything that has been made, in one place, and a way to start something new.
   It fills the middle of the window; the conversation is behind it and comes back as soon as a chat is opened. What it
   lists comes from the library (jcc/artifacts.py): what every chat has made, and what its owner made by hand. */
(() => {
'use strict';
const N = window.Nova; if (!N) return;
const { icon, el, notify, confirmBox, ask } = N;
const center = document.querySelector('.center'), body = document.body;
// What can be started here. (kind, name, icon, what it is for)
const TILES = [
  ['document', 'Docs', 'doc', 'A document: a report, a plan, a letter, notes'],
  ['slides', 'Slides', 'slides', 'A deck of slides to present'],
  ['sheet', 'Sheets', 'grid', 'A table of numbers, with formulas'],
  ['design', 'Design', 'palette', 'A picture, a logo, a poster, a mock-up of a screen'],
  ['data', 'Data', 'chart', 'A chart drawn from numbers'],
  ['whiteboard', 'Whiteboard', 'board', 'A board to draw on and put notes on'],
];
const ASKS = {
  document: { label: 'What should the document be about?', example: 'A one-page plan for opening a bakery in Jaipur, with what it will cost', say: 'Write a document: ', empty: 'Untitled document' },
  slides: { label: 'What should the slides be about?', example: 'Five slides on why our school should start a coding club', say: 'Make a slide deck: ', empty: 'Untitled slides' },
  sheet: { label: 'What should the sheet hold?', example: 'My monthly budget: rent, food, travel and savings, with totals', say: 'Make a spreadsheet: ', empty: 'Untitled sheet' },
  design: { label: 'What should it look like?', example: 'A logo for a bakery called Rise and Shine, in warm colours', say: 'Design this as a picture: ' },
  data: { label: 'What should the chart show?', example: 'A bar chart of the five tallest mountains and how high they are', say: 'Make a chart: ' },
};
const ICONS = { page: 'globe', picture: 'cam', diagram: 'work', app: 'code', document: 'doc', slides: 'slides', sheet: 'grid', data: 'chart', whiteboard: 'board' };
const FILTERS = [['', 'Everything'], ['document', 'Documents'], ['slides', 'Slides'], ['sheet', 'Sheets'], ['data', 'Charts'], ['whiteboard', 'Whiteboards'], ['page', 'Pages'], ['picture', 'Pictures'], ['diagram', 'Diagrams'], ['app', 'Apps']];
const ago = at => { if (!at) return ''; const s = Math.max(0, Math.round(Date.now() / 1000 - at)); return s < 90 ? 'just now' : s < 3600 ? Math.round(s / 60) + ' min ago' : s < 86400 ? Math.round(s / 3600) + ' h ago' : s < 86400 * 14 ? Math.round(s / 86400) + ' d ago' : new Date(at * 1000).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }); };
const num = v => String(Math.round(Number(v)) || 0);

const view = el('section', { id: 'nv-gallery', class: 'nv-gal hidden', 'aria-label': 'Artifacts' },
  '<div class="nv-gal-in"><h1>Artifacts</h1><div class="nv-gal-bar"><div class="nv-gal-tabs" role="tablist">' +
  [['', 'All'], ['yours', 'Yours'], ['starred', 'Starred']].map(([id, label]) => '<button type="button" role="tab" data-only="' + id + '">' + label + '</button>').join('') + '</div>' +
  '<div class="nv-gal-tools"><input type="search" id="nv-gal-q" class="hidden" maxlength="200" placeholder="Search what has been made" aria-label="Search artifacts">' +
  '<button type="button" class="nv-icon" data-do="search" aria-label="Search" data-tip="Search by name or by what is in it">' + icon('search') + '</button>' +
  '<button type="button" class="nv-icon" data-do="filter" aria-label="Show one kind" data-tip="Show one kind of thing">' + icon('filter') + '</button>' +
  '<button type="button" class="nv-icon" data-do="view" aria-label="As a list or as cards" data-tip="As a list, or as cards">' + icon('rows') + '</button>' +
  '<button type="button" class="nv-icon" data-do="new" aria-label="Make something new" data-tip="Make something new">' + icon('plus') + '</button></div></div>' +
  '<h2>Make something new</h2><div class="nv-gal-new">' + TILES.map(([kind, name, glyph, about]) => '<button type="button" class="nv-gal-tile" data-make="' + kind + '" data-tip="' + esc(about) + '"><span class="nv-gal-art" data-kind="' + kind + '">' + icon(glyph) + '</span><b>' + name + '</b></button>').join('') + '</div>' +
  '<h2 id="nv-gal-title">Everything that has been made</h2><div id="nv-gal-list"></div><p class="small nv-gal-wait hidden" id="nv-gal-more"><i class="nv-spin"></i>Reading your older chats…</p></div>');
center.append(view);
const list = view.querySelector('#nv-gal-list'), search = view.querySelector('#nv-gal-q'), moreNote = view.querySelector('#nv-gal-more');
let open = false, only = '', kind = '', query = '', items = [], names = {}, cards = N.store.get('nv-gal-view', 'cards') !== 'list', asked = 0;

function draw() {
  view.querySelectorAll('.nv-gal-tabs button').forEach(b => { const on = b.dataset.only === only; b.classList.toggle('on', on); b.setAttribute('aria-selected', String(on)); });
  view.querySelector('[data-do="filter"]').classList.toggle('on', !!kind);
  view.querySelector('[data-do="view"]').innerHTML = icon(cards ? 'rows' : 'grid');
  view.querySelector('#nv-gal-title').textContent = (kind ? (FILTERS.find(f => f[0] === kind) || ['', 'Everything'])[1] : only === 'starred' ? 'Starred' : only === 'yours' ? 'Made or changed by you' : 'Everything that has been made') + (query ? ' matching “' + query + '”' : '');
  if (!items.length) {
    const narrowed = !!(only || kind || query);
    list.className = '';
    list.innerHTML = '<div class="nv-blank"><div><b>' + (narrowed ? 'Nothing here matches.' : 'Nothing has been made yet.') + '</b><br>' +
      (narrowed ? 'Try another word, or look at everything.<div class="nv-wk-start"><button class="plain" data-clear>Show everything</button></div>'
        : 'Start something above, or ask in a chat: “make a page for my bakery”, “make slides about volcanoes”. What JARVIS makes is kept here.') + '</div></div>';
    return;
  }
  // (Every word shown comes from the library through esc(), and every count through num(): a saved record is data.)
  const meta = a => [names[a.kind] || 'Thing', a.versions > 1 ? num(a.versions) + ' versions' : '', ago(a.updated)].filter(Boolean).map(esc).join(' · ');
  seen?.disconnect();
  list.className = cards ? 'nv-gal-grid' : 'nv-gal-rows';
  list.innerHTML = items.map(a => '<div class="nv-gal-card" data-kind="' + esc(a.kind) + '">' +
    '<button type="button" class="nv-gal-open" data-open="' + esc(a.id) + '"><span class="nv-gal-thumb"' + (cards && MINIS.includes(a.kind) ? ' data-mini="' + esc(a.id) + '"' : '') + '>' + icon(ICONS[a.kind] || 'doc') + '<i>' + esc(a.peek || '') + '</i></span>' +
    '<span class="nv-gal-name"><b>' + (a.starred ? '<span class="nv-gal-star" aria-label="Starred">★</span>' : '') + esc(a.title) + '</b><small>' + meta(a) + '</small></span></button>' +
    '<button type="button" class="nv-icon nv-gal-more" data-more="' + esc(a.id) + '" aria-label="More for ' + esc(a.title) + '">' + icon('more') + '</button></div>').join('');
  for (const box of list.querySelectorAll('[data-mini]')) { if (seen) seen.observe(box); else mini(box); }
}
/* A miniature of a picture, a chart or a board, in place of words. It is drawn only when its card comes into sight.
   (A picture is shown as an image, which can neither run nor fetch anything; a chart and a board are drawn here from
   their numbers and marks.) */
const MINIS = ['picture', 'data', 'whiteboard'], minis = new Map(), seen = window.IntersectionObserver ? new IntersectionObserver(found => { for (const e of found) if (e.isIntersecting) { seen.unobserve(e.target); mini(e.target); } }, { root: view, rootMargin: '200px' }) : null;
let fetching = 0;
function place(box, made) {
  if (!made || !box.isConnected) return;
  const copy = made.cloneNode(true); copy.classList.add('nv-gal-mini'); box.querySelector('i')?.remove(); box.querySelector('svg.i')?.remove(); box.append(copy); box.classList.add('has-mini');
}
async function mini(box) {
  const a = items.find(i => i.id === box.dataset.mini); if (!a) return;
  const key = a.id + ':' + a.updated;
  if (minis.has(key)) return void place(box, minis.get(key));
  if (fetching >= 4) return void setTimeout(() => mini(box), 250);
  fetching++;
  let made = null;
  try {
    const got = await api('/api/artifacts', { action: 'get', id: a.id }), K = window.NovaKinds;
    if (a.kind === 'data') { const chart = K.readChart(got.code); if (!chart.problem) made = K.chartSvg(chart); }
    else if (a.kind === 'whiteboard') made = K.boardSvg(K.readBoard(got.code));
    else if (/^\s*(<\?xml[^>]*>\s*)?<svg[\s>]/i.test(got.code) && got.code.length < 600000) { made = new Image(); made.alt = ''; made.src = URL.createObjectURL(new Blob([got.code], { type: 'image/svg+xml' })); }
    if (made && made.removeAttribute) { made.removeAttribute('width'); made.removeAttribute('height'); }
  } catch { made = null; }
  fetching--;
  if (minis.size > 300) minis.clear();
  minis.set(key, made); place(box, made);
}
async function load() {
  const mine = ++asked;
  let got; try { got = await api('/api/artifacts', { action: 'list', query, kind, only }); } catch (error) { if (mine === asked) toast(error.message); return; }
  if (mine !== asked) return;                                  // (a newer question has been asked since)
  items = got.items; names = got.kinds || {}; moreNote.classList.toggle('hidden', !got.more); draw();
  if (got.more && open) setTimeout(() => { if (open && mine === asked) load(); }, 300);      // older chats are read a few at a time
}
function openGallery() {
  open = true; view.classList.remove('hidden'); body.classList.add('nv-gallery-on'); nav.classList.add('on'); view.scrollTop = 0; load();
  if (innerWidth < 900 && N.closePanel) N.closePanel();
}
function closeGallery() { if (!open) return; open = false; view.classList.add('hidden'); body.classList.remove('nv-gallery-on'); nav.classList.remove('on'); }
N.openGallery = openGallery; N.closeGallery = closeGallery; N.galleryChanged = () => { if (open) load(); };

/* ---- starting something new ---- */
async function make(what) {
  if (what === 'whiteboard') { try { await N.newArtifact('whiteboard', 'Whiteboard, ' + new Date().toLocaleDateString([], { day: 'numeric', month: 'short' })); } catch (error) { toast(error.message); } return; }
  const tile = TILES.find(t => t[0] === what), how = ASKS[what]; if (!tile || !how) return;
  const d = N.dialog('<form method="dialog" class="nv-gal-make"><h2>' + icon(tile[2]) + esc(tile[1]) + '</h2><label>' + esc(how.label) + '<textarea rows="4" maxlength="4000" placeholder="' + esc(how.example) + '"></textarea></label>' +
    '<p class="small">JARVIS makes it in a new chat and it opens beside it. You can then ask for changes, or change it yourself; every version is kept.</p>' +
    '<div class="actions">' + (how.empty ? '<button type="button" class="plain" data-empty>Start with an empty one</button>' : '') + '<button type="button" class="plain" data-cancel>Cancel</button><button class="primary">Ask JARVIS to make it</button></div></form>');
  const box = d.querySelector('textarea'); box.focus();
  d.querySelector('[data-cancel]').onclick = () => d.close();
  const empty = d.querySelector('[data-empty]');
  if (empty) empty.onclick = async () => { const title = box.value.trim().split('\n')[0].slice(0, 80) || how.empty; d.close(); try { await N.newArtifact(what, title); } catch (error) { toast(error.message); } };
  box.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); d.querySelector('.primary').click(); } };
  d.querySelector('form').onsubmit = e => {
    e.preventDefault(); const text = box.value.trim(); if (text.length < 3) return void box.focus();
    d.close(); closeGallery();
    // A new conversation, in Chat (not a coding session), with the request already asked.
    if (body.classList.contains('nv-coding')) document.querySelector('.nv-modes button[data-mode="chat"]')?.click();
    N.newChat();
    setTimeout(() => { N.setDraft(how.say + text); document.getElementById('composer').requestSubmit(); }, 120);
  };
}
function cardMenu(button, a) {
  const change = async (body, said) => { try { await api('/api/artifacts', { ...body, id: a.id }); if (said) notify(said); await load(); } catch (error) { toast(error.message); } };
  N.openPop(button, p => {
    N.item(p, 'Open', 'eye', () => N.openArtifact(a.id));
    N.item(p, a.starred ? 'Take the star off' : 'Star it', 'star', () => change({ action: 'star', on: !a.starred }));
    N.item(p, 'Rename', 'edit', async () => { const name = await ask({ title: 'Rename', label: 'Its name', value: a.title, ok: 'Rename' }); if (name) await change({ action: 'rename', title: name }); });
    if (a.chat) N.item(p, 'Open the chat that made it', 'chat', () => openChat(a.chat).catch(() => toast('That chat is no longer there.')));
    p.append(el('hr'));
    N.item(p, 'Take it out of the library', 'trash', async () => {
      if (!(await confirmBox({ title: 'Take “' + a.title + '” out of the library?', text: 'It and its ' + num(a.versions) + (a.versions === 1 ? ' version go' : ' versions go') + ' from Artifacts.' + (a.chat ? ' What the chat itself says is not touched.' : ' This cannot be undone.'), ok: 'Take it out', danger: true }))) return;
      await change({ action: 'remove' }, 'Taken out of the library.');
    }, { danger: true });
  }, { right: true });
}
view.addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.only !== undefined) { only = b.dataset.only; load(); draw(); }
  else if (b.dataset.make) make(b.dataset.make);
  else if (b.dataset.open) N.openArtifact(b.dataset.open).catch(error => { toast(error.message); load(); });
  else if (b.dataset.more) { const a = items.find(i => i.id === b.dataset.more); if (a) cardMenu(b, a); }
  else if (b.dataset.clear !== undefined) { only = ''; kind = ''; query = ''; search.value = ''; search.classList.add('hidden'); load(); }
  else if (b.dataset.do === 'search') { search.classList.toggle('hidden'); if (search.classList.contains('hidden')) { if (query) { query = ''; search.value = ''; load(); } } else search.focus(); }
  else if (b.dataset.do === 'view') { cards = !cards; N.store.set('nv-gal-view', cards ? 'cards' : 'list'); draw(); }
  else if (b.dataset.do === 'filter') N.openPop(b, p => { p.append(el('h5', {}, 'Show')); for (const [id, label] of FILTERS) N.item(p, label, id ? ICONS[id] : 'layers', () => { kind = id; load(); }, { tick: kind === id }); }, { right: true });
  else if (b.dataset.do === 'new') N.openPop(b, p => { p.append(el('h5', {}, 'Make something new')); for (const [id, label, glyph, about] of TILES) N.item(p, label, glyph, () => make(id), { note: about }); }, { right: true });
});
let typing = 0;
search.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { query = search.value.trim(); load(); }, 220); });
search.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); search.value = ''; query = ''; search.classList.add('hidden'); load(); } });

/* ---- where it is opened from, and what puts the conversation back ---- */
const nav = el('button', { class: 'nv-nav', id: 'nv-gal-nav', type: 'button', data: { tip: 'Everything JARVIS and you have made, and a place to start something new' } }, icon('grid') + '<span>Artifacts</span>');
const anchor = document.getElementById('search')?.nextElementSibling;                // (the "My work" line)
if (anchor && anchor.classList.contains('nv-nav')) anchor.after(nav); else document.getElementById('search')?.after(nav);
nav.onclick = () => (open ? closeGallery() : openGallery());
const earlier = window.openChat;
if (typeof earlier === 'function') window.openChat = (...args) => { closeGallery(); return earlier(...args); };
// (Anything else pressed in the list of chats, a chat, a project or New chat, shows the conversation again. "My work" opens beside it.)
document.getElementById('sidebar')?.addEventListener('click', e => { if (open && !e.target.closest('#nv-gal-nav, #search') && !(anchor && anchor.contains(e.target)) && e.target.closest('button, a, [role="button"], li')) closeGallery(); }, true);
document.querySelector('.nv-modes')?.addEventListener('click', closeGallery, true);
addEventListener('keydown', e => { if (e.key === 'Escape' && open && !document.querySelector('dialog[open], .nv-pop')) closeGallery(); });
})();
