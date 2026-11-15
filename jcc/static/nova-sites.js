/* The owner's websites, in the chat (jcc/sites.py). A change the assistant makes to a site is shown here first: its
   preview, served by JARVIS on this computer, with Publish and Discard. Nothing reaches the site before Publish.
   /sites lists the connected sites and the changes waiting, and connects a new site (its key goes to the key store). */
(() => {
'use strict';
const N = window.Nova; if (!N || !N.localReply || document.body.classList.contains('nv-mini')) return;
const { notify } = N;
const say = text => (typeof toast === 'function' ? toast(text) : notify(text));
const cards = new Map();                 // change id -> its card in the chat

const previewPath = change => '/site-preview/' + encodeURIComponent(change.id) + '?k=' + encodeURIComponent(change.view || '');
const what = change => (change.action === 'update' ? 'Change to the ' : 'New ') + change.kind + (change.title ? ': ' + change.title : '');

function drawCard(card, change) {
  const box = card.querySelector('.content');
  const live = (change.result || {}).url;
  const state = change.state === 'published' ? '<p class="nv-site-state ok">Published on ' + esc(change.site_name) + (live ? ': <a href="' + esc(live) + '" target="_blank" rel="noopener">' + esc(live) + '</a>' : '.') + '</p>'
    : change.state === 'discarded' ? '<p class="nv-site-state">Thrown away. Nothing was sent to the site.</p>'
    : '<p class="nv-site-state wait">Not published yet. This preview is on your computer only.</p>';
  box.innerHTML = '<p><b>' + esc(what(change)) + '</b> · ' + esc(change.site_name) + '</p><p class="small">' + esc(change.summary || '') + '</p>' + state +
    (change.error ? '<p class="nv-site-state bad">' + esc(change.error) + '</p>' : '') +
    (change.view ? '<iframe class="nv-site-frame" title="Preview of the change" src="' + esc(previewPath(change)) + '"></iframe>' : '') +
    '<div class="actions">' + (change.view ? '<button class="plain" type="button" data-open>Open in browser</button>' : '') +
    (change.state === 'preview' ? '<button class="plain" type="button" data-discard>Discard</button><button class="primary" type="button" data-publish>Publish</button>' : '') + '</div>';
  box.querySelector('[data-open]')?.addEventListener('click', () => window.open(location.origin + previewPath(change), '_blank', 'noopener'));
  box.querySelector('[data-discard]')?.addEventListener('click', () => decide(card, change, 'discard'));
  box.querySelector('[data-publish]')?.addEventListener('click', () => decide(card, change, 'publish'));
}

async function decide(card, change, action) {
  card.querySelectorAll('.actions button').forEach(b => { b.disabled = true; });
  if (action === 'publish') card.querySelector('[data-publish]').textContent = 'Publishing…';
  try {
    const got = await api('/api/sites', { action, id: change.id });
    const next = { ...change, ...got.change };
    drawCard(card, next);
    notify(action === 'publish' ? 'Published on ' + change.site_name + '.' : 'Discarded. Nothing was sent.');
  } catch (error) {
    drawCard(card, { ...change, error: error.message });
    say(error.message);
  }
}

// A change from the assistant (or a later word on it): one card per change, kept up to date.
N.siteCard = change => {
  if (!change || !change.id) return;
  let card = cards.get(change.id);
  if (!card || !card.isConnected) {
    card = N.localReply('Website change', '');
    card.classList.add('nv-site-card');
    cards.set(change.id, card);
  } else if (!change.view) {
    change = { ...card.nvChange, ...change };
  }
  card.nvChange = change;
  drawCard(card, change);
};

async function sitesCommand() {
  let data;
  try { data = await api('/api/sites', { action: 'list' }); } catch (error) { return say(error.message); }
  const node = N.localReply('Websites', '');
  draw(node, data);
}

function draw(node, data) {
  const box = node.querySelector('.content');
  const platforms = data.platforms || {};
  const rows = (data.sites || []).map(s => '<li><b>' + esc(s.name) + '</b> <small>' + esc(s.label) + ' · ' + esc(s.address) + ' · ' +
    s.kinds.map(k => k + 's').join(', ') + (s.edits ? '' : ' (new ones only)') + ' · stays connected until you remove it</small>' +
    '<button class="plain" type="button" data-rekey="' + esc(s.id) + '">Replace key</button><button class="plain" type="button" data-remove="' + esc(s.id) + '">Remove</button></li>').join('');
  const waiting = (data.pending || []).map(c => '<li><b>' + esc(what(c)) + '</b> <small>' + esc(c.site_name) + ' · ' + esc(c.summary || '') +
    '</small><button class="plain" type="button" data-show="' + esc(c.id) + '">Preview</button></li>').join('');
  box.innerHTML = '<p class="small">Tell JARVIS what to change, for example “add a blog post about our summer sale to my WordPress site”. Every change is shown here first, on this computer; it goes online only when you press Publish.</p>' +
    '<h4>Connected</h4>' + (rows ? '<ul class="nv-worklist">' + rows + '</ul>' : '<p class="small">No website yet.</p>') +
    (waiting ? '<h4>Waiting for you</h4><ul class="nv-worklist">' + waiting + '</ul>' : '') +
    '<h4>Connect a website</h4><form class="nv-site-add">' +
    '<label class="nv-field"><span>Platform</span><select name="platform">' + Object.entries(platforms).map(([k, p]) => '<option value="' + k + '">' + esc(p.label) + '</option>').join('') + '</select></label>' +
    '<p class="small nv-site-how"></p>' +
    '<label class="nv-field"><span>Site address</span><input name="address" placeholder="https://example.com" autocomplete="off" spellcheck="false"></label>' +
    '<label class="nv-field" data-need="user"><span>WordPress user name</span><input name="user" autocomplete="off" spellcheck="false"></label>' +
    '<label class="nv-field" data-need="site_id"><span>Wix site ID</span><input name="site_id" autocomplete="off" spellcheck="false"></label>' +
    '<label class="nv-field"><span data-key-label>Key</span><input name="key" type="password" autocomplete="off" spellcheck="false"></label>' +
    '<label class="nv-field"><span>Name (optional)</span><input name="name" placeholder="My shop" autocomplete="off"></label>' +
    '<p class="small">The key is kept in this computer’s key store (Windows Credential Manager or the Keychain), never in a file. JARVIS can reach only the sites listed here.</p>' +
    '<div class="actions"><button class="primary" type="submit">Connect</button></div></form>';
  const form = box.querySelector('form'), pick = form.querySelector('select');
  const sync = () => {
    const p = platforms[pick.value] || {};
    form.querySelector('.nv-site-how').textContent = p.how || '';
    form.querySelector('[data-key-label]').textContent = p.key || 'Key';
    form.querySelectorAll('[data-need]').forEach(f => f.classList.toggle('hidden', !(p.needs || []).includes(f.dataset.need)));
  };
  pick.onchange = sync; sync();
  form.onsubmit = async e => {
    e.preventDefault();
    const button = form.querySelector('[type=submit]'); button.disabled = true; button.textContent = 'Checking the key…';
    const values = Object.fromEntries(new FormData(form).entries());
    try {
      const got = await api('/api/sites', { action: 'add', ...values });
      notify('Connected ' + got.site.name + '.');
      draw(node, got);
    } catch (error) { say(error.message); button.disabled = false; button.textContent = 'Connect'; }
  };
  box.querySelectorAll('[data-remove]').forEach(b => b.onclick = async () => {
    const site = (data.sites || []).find(s => s.id === b.dataset.remove);
    if (!(await N.confirmBox({ title: 'Remove ' + (site ? site.name : 'this site') + '?', text: 'JARVIS forgets the site and deletes its key from this computer. Nothing on the site changes.', ok: 'Remove' }))) return;
    try { draw(node, await api('/api/sites', { action: 'remove', id: b.dataset.remove })); } catch (error) { say(error.message); }
  });
  box.querySelectorAll('[data-rekey]').forEach(b => b.onclick = async () => {
    const site = (data.sites || []).find(s => s.id === b.dataset.rekey) || {};
    const label = ((data.platforms || {})[site.platform] || {}).key || 'key';
    const ask = N.dialog('<h2>A new key for ' + esc(site.name || 'this site') + '</h2><p>The site stays connected; only its key changes. The new key is tried first.</p>' +
      '<label class="nv-field"><span>' + esc(label) + '</span><input type="password" autocomplete="off" spellcheck="false"></label>' +
      '<div class="actions"><button class="plain" data-no>Cancel</button><button class="primary" data-yes>Replace key</button></div>');
    ask.querySelector('[data-no]').onclick = () => ask.close();
    ask.querySelector('[data-yes]').onclick = async () => {
      try { const got = await api('/api/sites', { action: 'rekey', id: site.id, key: ask.querySelector('input').value }); ask.close(); notify('New key kept for ' + got.site.name + '.'); draw(node, got); }
      catch (error) { say(error.message); }
    };
  });
  box.querySelectorAll('[data-show]').forEach(b => b.onclick = async () => {
    try { const got = await api('/api/sites', { action: 'change', id: b.dataset.show }); N.siteCard({ ...got.change, view: (data.pending || []).find(c => c.id === b.dataset.show)?.view }); }
    catch (error) { say(error.message); }
  });
}

N.sitesCommand = sitesCommand;
})();
