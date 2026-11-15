/* /connectors: extra tools for the assistant (jcc/connectors.py), added in the chat. Paste a connector's link, its
   command, or the setup from its instructions; or bring in the ones set up in Claude. Keys go to the key store. */
(() => {
'use strict';
const N = window.Nova; if (!N || !N.localReply || document.body.classList.contains('nv-mini')) return;
const { notify } = N;
const say = text => (typeof toast === 'function' ? toast(text) : notify(text));

async function connectorsCommand() {
  let data;
  try { data = await api('/api/connectors', { action: 'list' }); } catch (error) { return say(error.message); }
  draw(N.localReply('Connectors', ''), data);
}

function draw(node, data) {
  const box = node.querySelector('.content');
  const rows = (data.connectors || []).map(c => '<li><b>' + esc(c.name) + '</b><small>' + (c.kind === 'link' ? 'Link · ' : 'Program · ') + esc(c.where) +
    (c.secrets ? ' · ' + c.secrets + (c.secrets === 1 ? ' key' : ' keys') + ' in the key store' : '') + ' · stays until you remove it</small><span class="nv-conn-test" data-result="' + esc(c.name) + '"></span>' +
    '<button class="plain" type="button" data-test="' + esc(c.name) + '">Test</button><button class="plain" type="button" data-remove="' + esc(c.name) + '">Remove</button></li>').join('');
  box.innerHTML = '<p class="small">Connectors give the assistant more tools: a calendar, a database, GitHub, your notes app. Once one is added, just ask: “what is on my calendar tomorrow?”. JARVIS asks before using them in a chat that has read outside content.</p>' +
    '<h4>Added</h4>' + (rows ? '<ul class="nv-worklist">' + rows + '</ul>' : '<p class="small">None yet.</p>') +
    '<h4>Add a connector</h4><form class="nv-conn-add">' +
    '<label class="nv-field"><span>Link, command or setup<small>From the connector’s instructions: a link such as https://…/mcp, a command such as npx -y @org/server, or the whole setup JSON (“mcpServers”: …).</small></span>' +
    '<textarea name="text" rows="4" spellcheck="false" placeholder="https://example.com/mcp   or   npx -y @org/server   or   { &quot;mcpServers&quot;: … }"></textarea></label>' +
    '<label class="nv-field"><span>Key or token (if it needs one)<small>For a link. Kept in this computer’s key store, never in a file.</small></span><input name="token" type="password" autocomplete="off" spellcheck="false"></label>' +
    '<label class="nv-field"><span>Name (optional)</span><input name="name" autocomplete="off" spellcheck="false" placeholder="calendar"></label>' +
    '<div class="actions"><button class="primary" type="submit">Add</button></div></form>' +
    '<h4>From Claude</h4><div class="nv-conn-claude"><button class="plain" type="button" data-claude>Find the connectors I use in Claude</button></div>';
  const form = box.querySelector('form');
  form.onsubmit = async e => {
    e.preventDefault();
    const button = form.querySelector('[type=submit]'); button.disabled = true;
    try {
      const got = await api('/api/connectors', { action: 'add', ...Object.fromEntries(new FormData(form).entries()) });
      notify('Added ' + got.added.map(c => c.name).join(', ') + '. Press Test to check it.');
      draw(node, got);
    } catch (error) { say(error.message); button.disabled = false; }
  };
  box.querySelectorAll('[data-test]').forEach(b => b.onclick = async () => {
    const out = box.querySelector('[data-result="' + CSS.escape(b.dataset.test) + '"]');
    b.disabled = true; out.textContent = 'Starting it…'; out.className = 'nv-conn-test';
    try {
      const t = (await api('/api/connectors', { action: 'test', name: b.dataset.test })).test;
      out.textContent = t.ok ? 'Works: ' + (t.tools.length ? t.tools.length + (t.tools.length === 1 ? ' tool (' : ' tools (') + t.tools.slice(0, 6).join(', ') + (t.tools.length > 6 ? ', …' : '') + ')' : 'no tools offered') : t.problem;
      out.classList.add(t.ok ? 'ok' : 'bad');
    } catch (error) { out.textContent = error.message; out.classList.add('bad'); }
    b.disabled = false;
  });
  box.querySelectorAll('[data-remove]').forEach(b => b.onclick = async () => {
    if (!(await N.confirmBox({ title: 'Remove ' + b.dataset.remove + '?', text: 'The assistant stops using it, and its keys are deleted from this computer’s key store.', ok: 'Remove' }))) return;
    try { draw(node, await api('/api/connectors', { action: 'remove', name: b.dataset.remove })); } catch (error) { say(error.message); }
  });
  box.querySelector('[data-claude]').onclick = async () => {
    const place = box.querySelector('.nv-conn-claude');
    let found;
    try { found = (await api('/api/connectors', { action: 'claude' })).claude || []; } catch (error) { return say(error.message); }
    if (!found.length) { place.innerHTML = '<p class="small">No connectors were found in Claude Desktop or Claude Code on this computer.</p>'; return; }
    const sources = [...new Set(found.map(c => c.source))];
    place.innerHTML = sources.map(source => '<div class="nv-conn-source" data-source="' + esc(source) + '"><p><b>' + esc(source) + '</b></p>' +
      found.filter(c => c.source === source).map(c => '<label class="assistant-check"><input type="checkbox" value="' + esc(c.name) + '"' + (c.there ? ' disabled' : '') + '> <span>' + esc(c.name) +
        '<small>' + esc(c.where) + (c.secret ? ' · its key goes into the key store' : '') + (c.there ? ' · added already' : '') + '</small></span></label>').join('') +
      '<div class="actions"><button class="primary" type="button">Bring in the ones ticked</button></div></div>').join('');
    place.querySelectorAll('.nv-conn-source').forEach(group => group.querySelector('button').onclick = async () => {
      const names = [...group.querySelectorAll('input:checked')].map(i => i.value);
      if (!names.length) return say('Tick the ones to bring in.');
      try {
        const got = await api('/api/connectors', { action: 'import', source: group.dataset.source, names });
        notify('Brought in ' + got.added.map(c => c.name).join(', ') + '.');
        draw(node, got);
      } catch (error) { say(error.message); }
    });
  };
}

N.connectorsCommand = connectorsCommand;
})();
