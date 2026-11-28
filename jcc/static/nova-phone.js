/* /phone: the phone app, set up in the owner's own Supabase and Cloudflare accounts (jcc/phone_setup.py), in the chat.
   Setting up, adding a phone (a code typed or scanned there, then a yes here), laptop-off answers per AI key, removing
   a phone or everything. Tokens are pasted here, sent to this computer only, and never shown again. */
(() => {
'use strict';
const N = window.Nova; if (!N || !N.localReply || document.body.classList.contains('nv-mini')) return;
const { notify } = N;
const say = text => (typeof toast === 'function' ? toast(text) : notify(text));
const SUPABASE_TOKENS = 'https://supabase.com/dashboard/account/tokens';
const CLOUDFLARE_TOKENS = 'https://dash.cloudflare.com/profile/api-tokens';
const REGIONS = [['ap-south-1', 'Mumbai'], ['ap-southeast-1', 'Singapore'], ['eu-central-1', 'Frankfurt'], ['eu-west-2', 'London'], ['us-east-1', 'North Virginia'], ['us-west-1', 'North California']];
const STATUS = { on: 'relay awake', starting: 'connecting to your relay', off: 'not running' };
let card = null;                       // the /phone reply shown last, redrawn when something changes

const openLink = url => (N.openWeb ? N.openWeb(url) : api('/api/browser/open', { query: url }).then(() => notify('Opened in your own browser.')).catch(error => say(error.message)));
const added = seconds => {
  if (typeof seconds !== 'number') return '';
  const when = new Date(seconds * 1000);
  const year = when.getFullYear() === new Date().getFullYear() ? undefined : 'numeric';
  return 'Added ' + when.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year });
};
// "Added Nov 28 · Last used Nov 29 · Notifications off": last use and notifications come from the relay, when it answered.
const rowLine = p => {
  const parts = [added(p.added)];
  if (p.last_seen) {
    const when = new Date(p.last_seen);
    if (!isNaN(when)) parts.push('Last used ' + when.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: when.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' }));
  }
  if (p.push === false) parts.push('Notifications off');
  return parts.filter(Boolean).join(' \u00b7 ');
};
// A dialog named by its own heading, opening on the control that should have focus first.
const labelled = (d, first) => {
  const title = d.querySelector('h2');
  if (title) { title.id ||= 'nv-ph-' + Math.random().toString(36).slice(2, 8); d.setAttribute('aria-labelledby', title.id); }
  if (first) first.focus();
  return d;
};
const spelled = code => 'Code: ' + String(code).split('-').map(g => g.split('').join(' ')).join(', ');
const SUPABASE_PROJECT = ref => 'https://supabase.com/dashboard/project/' + encodeURIComponent(ref || '');

async function phoneCommand() {
  let data;
  try { data = await api('/api/phone', { action: 'show' }); } catch (error) { return say(error.message); }
  card = N.localReply('Phone app', '');
  draw(data);
}

function summary(data) {
  const on = data.brains.on.map(id => (data.brains.can.find(b => b.id === id) || { name: id }).name);
  return data.phones.length + (data.phones.length === 1 ? ' phone' : ' phones') + ' · ' + (STATUS[data.status] || data.status) +
    ' · laptop-off answers: ' + (on.length ? on.join(', ') : 'off');
}

function draw(data) {
  if (!card) return;
  const box = card.querySelector('.content');
  box.classList.add('nv-phone');
  const top = '<p class="small">' + esc(data.privacy) + '</p>';
  if (!data.setup) {
    box.innerHTML = top + '<p>Use JARVIS from your phone. About five minutes, free, in your own accounts.</p>' +
      '<div class="actions"><button class="primary" type="button" data-start>Set up</button></div>';
    box.querySelector('[data-start]').onclick = () => drawSetup(data);
    return;
  }
  const changed = data.tampered.length ? '<div role="alert"><p class="nv-site-state bad">The phone page was changed outside JARVIS.</p>' +
    '<div class="actions" style="display:flex;gap:6px;margin-bottom:8px"><button class="plain" type="button" data-again>Redeploy</button><button class="plain" type="button" data-unpair-all>Unpair all phones</button></div></div>' : '';
  const asleep = /refused|answered|reach/.test(data.status) ? '<div role="alert"><p class="nv-site-state bad">Your relay went to sleep after a week without use. The phone app is silent until it wakes.</p>' +
    '<p class="small">' + esc(data.status) + '</p><div class="actions" style="display:flex;gap:6px;margin-bottom:8px"><button class="plain" type="button" data-wake>Wake it</button></div></div>' : '';
  const phones = data.phones.map(p => '<li><b>' + esc(p.name || 'A phone') + '</b><small>' + esc(rowLine(p)) + '</small>' +
    '<button class="plain" type="button" data-remove="' + esc(p.id) + '" data-name="' + esc(p.name || 'this phone') + '">Remove</button></li>').join('');
  const keys = data.brains.can.length ? data.brains.can.map(b => '<label style="display:flex;gap:8px;align-items:center;min-height:32px"><input type="checkbox" value="' + esc(b.id) + '"' +
    (data.brains.on.includes(b.id) ? ' checked' : '') + '><span>' + esc(b.name) + '</span></label>').join('') +
    '<div class="actions"><button class="plain" type="button" data-brains disabled>Save</button></div>'
    : '<p class="small">No AI keys are connected. Connect one in Settings, Connections to answer while your laptop is off.</p>';
  box.innerHTML = top + changed + asleep + '<p><b>' + esc(summary(data)) + '</b></p>' +
    (phones ? '<ul class="nv-worklist">' + phones + '</ul>' : '<p class="small">No phone is paired yet.</p>') +
    '<div class="actions" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px"><button class="primary" type="button" data-add>Add a phone</button>' +
    '<button class="plain" type="button" data-check>Check the phone page</button><button class="nv-text-btn" type="button" data-everything style="margin-left:auto">Remove the phone app</button></div>' +
    '<h4>Laptop-off answers</h4><p class="small">Tick the AI keys JARVIS may use while this computer is off. Only ticked keys are copied to your relay, each with a daily limit. Claude and ChatGPT subscriptions answer only while this computer is on.</p>' + keys +
    '<p class="small" style="margin-top:12px">Lost a phone? Remove it here. Away from your computer? Pause the project at supabase.com from any browser.</p>';
  box.querySelector('[data-add]').onclick = () => addPhone(data);
  box.querySelector('[data-check]').onclick = e => run(e.currentTarget, 'Checking…', { action: 'check' }, d => notify(d.tampered.length ? 'The phone page was changed outside JARVIS.' : 'The phone page is as JARVIS deployed it.'));
  const ticked = () => [...box.querySelectorAll('input[type=checkbox]:checked')].map(i => i.value).sort().join(',');
  const before = ticked();
  box.querySelectorAll('input[type=checkbox]').forEach(i => i.onchange = () => { box.querySelector('[data-brains]').disabled = ticked() === before; });
  box.querySelector('[data-wake]')?.addEventListener('click', () => openLink(SUPABASE_PROJECT(data.project)));
  box.querySelector('[data-brains]')?.addEventListener('click', e => {
    const names = [...box.querySelectorAll('input[type=checkbox]:checked')].map(i => i.value);
    run(e.currentTarget, 'Saving…', { action: 'brains', names }, () => notify(names.length ? 'Laptop-off answers: on.' : 'Laptop-off answers: off. The keys were deleted from your relay.'));
  });
  box.querySelectorAll('[data-remove]').forEach(b => b.onclick = async () => {
    if (!(await N.confirmBox({ title: 'Remove ‘' + b.dataset.name + '’?', text: 'It stops working at once and its saved messages are erased the next time it connects.', ok: 'Remove', cancel: 'Keep', danger: true }))) return;
    run(b, 'Removing…', { action: 'remove', phone: b.dataset.remove }, () => notify('Removed.'));
  });
  box.querySelector('[data-everything]').onclick = async e => {
    if (!(await N.confirmBox({ title: 'Remove the phone app?', text: 'This deletes the relay’s messages, the phone page and every pairing. Your chat stays on this computer. Your Supabase project stays: delete it at supabase.com if you no longer want it.', ok: 'Remove everything', cancel: 'Keep', danger: true }))) return;
    run(e.currentTarget, 'Removing…', { action: 'remove_everything' }, () => notify('The phone app was removed.'));
  };
  box.querySelector('[data-again]')?.addEventListener('click', () => drawSetup(data));
  box.querySelector('[data-unpair-all]')?.addEventListener('click', async e => {
    if (!(await N.confirmBox({ title: 'Unpair all phones?', text: 'Every phone stops working at once. Add them again after the page is redeployed.', ok: 'Unpair all', cancel: 'Keep', danger: true }))) return;
    const button = e.currentTarget; button.disabled = true;
    try { let last = data; for (const p of data.phones) last = await api('/api/phone', { action: 'remove', phone: p.id }); draw(last); } catch (error) { say(error.message); button.disabled = false; }
  });
}

async function run(button, working, body, then) {
  const label = button.textContent; button.disabled = true; button.textContent = working;
  try { const got = await api('/api/phone', body); draw(got); then?.(got); return got; }
  catch (error) { say(error.message); button.disabled = false; button.textContent = label; }
}

function drawSetup(data) {
  const box = card.querySelector('.content');
  box.classList.add('nv-phone');
  box.innerHTML = '<p class="small">' + esc(data.privacy) + '</p><form class="nv-phone-setup">' +
    '<h4>1. Your relay</h4><p class="small">Make an empty project at supabase.com (free), then make an access token and paste it here. JARVIS creates what the relay needs. The token is used once and not kept.</p>' +
    '<p><button class="plain" type="button" data-link="' + SUPABASE_TOKENS + '">Open Supabase access tokens</button></p>' +
    '<label class="nv-field"><span>Supabase access token<small>It starts with sbp_.</small></span><input name="supabase_token" type="password" autocomplete="off" spellcheck="false" required></label>' +
    '<label class="nv-field"><span>Where your relay runs<small>Pick the place nearest to you.</small></span><select name="region">' + REGIONS.map(([v, l]) => '<option value="' + v + '">' + l + '</option>').join('') + '</select></label>' +
    '<h4>2. The phone page</h4><p class="small">Make a free Cloudflare account, then an API token with only “Workers Scripts: Edit” (the “Edit Cloudflare Workers” template), and paste it here. JARVIS keeps it on this computer to update the page.</p>' +
    '<p><button class="plain" type="button" data-link="' + CLOUDFLARE_TOKENS + '">Open Cloudflare API tokens</button></p>' +
    '<label class="nv-field"><span>Cloudflare API token</span><input name="cloudflare_token" type="password" autocomplete="off" spellcheck="false" required></label>' +
    '<p class="error" role="alert" data-problem hidden></p>' +
    '<div class="actions"><button class="plain" type="button" data-back>Not now</button><button class="primary" type="submit">Set up</button></div>' +
    '<p class="small">You can close this and carry on later. Laptop-off answers and phones come next.</p></form>';
  const form = box.querySelector('form'), problem = form.querySelector('[data-problem]');
  form.querySelectorAll('[data-link]').forEach(b => b.onclick = () => openLink(b.dataset.link));
  form.querySelector('[data-back]').onclick = () => draw(data);
  const show = (text, html) => { problem.hidden = false; if (html) problem.innerHTML = html; else problem.textContent = text; problem.tabIndex = -1; problem.focus(); };
  const submit = async once => {
    const button = form.querySelector('[type=submit]'); button.disabled = true; button.textContent = 'Creating your relay and uploading the phone page…';
    problem.hidden = true;
    try {
      const got = await api('/api/phone', { action: 'setup', use_broad_once: !!once, ...Object.fromEntries(new FormData(form).entries()) });
      if (got.broad) {
        button.disabled = false; button.textContent = 'Set up';
        show('', esc('That Cloudflare token can reach more than one thing. Make a narrower one (recommended), or let JARVIS use it once and forget it.') +
          '<span style="display:flex;gap:6px;margin-top:6px"><button class="plain" type="button" data-narrow>Make a narrower one</button><button class="plain" type="button" data-once>Use it once</button></span>');
        problem.querySelector('[data-narrow]').onclick = () => { openLink(CLOUDFLARE_TOKENS); form.elements.cloudflare_token.value = ''; form.elements.cloudflare_token.focus(); };
        problem.querySelector('[data-once]').onclick = () => submit(true);
        return;
      }
      notify('The phone app is set up. Now add a phone.');
      draw(got); addPhone(got);
    } catch (error) { button.disabled = false; button.textContent = 'Set up'; show(error.message); }
  };
  form.onsubmit = e => { e.preventDefault(); submit(false); };
  form.elements.supabase_token.focus();
}

/* Adding a phone: part 1 opens the page on the phone, part 2 shows the code. The phone can be anywhere. */
let adding = null;
function addPhone(data) {
  const d = labelled(N.dialog('<h2>Add a phone</h2><div data-part></div>', 'nv-phone-add nv-phone'));
  adding = d; let timer = 0;
  const part = d.querySelector('[data-part]');
  const done = () => { clearInterval(timer); if (adding === d) adding = null; };
  d.addEventListener('close', () => { if (adding === d) api('/api/phone', { action: 'pair_stop' }).catch(() => {}); done(); });
  const first = () => {
    part.innerHTML = '<p>On your phone, scan this to open the app.</p>' + (data.page_qr ? '<div class="nv-phone-qr" style="width:200px;max-width:100%;margin:8px 0">' + data.page_qr + '</div>' : '') +
      '<p style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><code style="user-select:all">' + esc(data.origin) + '</code><button class="plain" type="button" data-copy>Copy</button></p>' +
      '<p>Then add it to your Home Screen and open it from there.</p><div class="actions"><button class="plain" type="button" data-close>Cancel</button><button class="primary" type="button" data-next>Next</button></div>';
    part.querySelector('[data-copy]').onclick = () => navigator.clipboard.writeText(data.origin).then(() => notify('Copied.'), () => say('Copy did not work: select the address instead.'));
    part.querySelector('[data-close]').onclick = () => d.close();
    part.querySelector('[data-next]').onclick = second;
    part.querySelector('[data-next]').focus();
  };
  const second = async () => {
    part.innerHTML = '<p>Getting a code…</p>';
    let got;
    try { got = await api('/api/phone', { action: 'pair' }); } catch (error) { part.innerHTML = '<p class="error" role="alert">' + esc(error.message) + '</p><div class="actions"><button class="plain" type="button" data-close>Close</button></div>'; part.querySelector('[data-close]').onclick = () => d.close(); return; }
    part.innerHTML = '<p>Type this code in the app, or scan it there.</p>' +
      '<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:8px 0"><p class="nv-phone-code" tabindex="-1" style="margin:0;font:600 32px/1 var(--mono, ui-monospace, monospace);letter-spacing:.12em"><span aria-hidden="true">' + esc(got.code) + '</span><span class="nv-sr">' + esc(spelled(got.code)) + '</span></p>' +
      (got.code_qr ? '<div style="width:140px">' + got.code_qr + '</div>' : '') + '</div>' +
      '<p class="small" data-left aria-live="off"></p><p class="small">When your phone asks, this computer shows “Pair this phone?”. Your phone can be anywhere: you can read the code out over a call.</p>' +
      '<div class="actions"><button class="plain" type="button" data-close>Cancel</button></div>';
    part.querySelector('[data-close]').onclick = () => d.close();
    const left = part.querySelector('[data-left]');
    const tick = () => {
      const s = Math.max(0, got.until - Math.floor(Date.now() / 1000));
      if (!s) { clearInterval(timer); part.innerHTML = '<p>That code ran out.</p><div class="actions"><button class="plain" type="button" data-close>Close</button><button class="primary" type="button" data-new>New code</button></div>'; part.querySelector('[data-close]').onclick = () => d.close(); part.querySelector('[data-new]').onclick = second; part.querySelector('[data-new]').focus(); return; }
      left.textContent = 'Expires in ' + Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    };
    clearInterval(timer); tick(); timer = setInterval(tick, 1000);
    part.querySelector('.nv-phone-code')?.focus();
  };
  first();
}

/* A phone typed the right code: only this window can say yes. */
let asking = null;
async function phonePair(event) {
  const name = String(event.name || 'A phone');
  if (asking?.open) return;                      // one question at a time; the phone waits for it
  const box = asking = labelled(N.dialog('<h2>Pair this phone?</h2><p>‘' + esc(name) + '’ asked just now.</p><div class="actions"><button class="plain" data-no>Not mine</button><button class="primary" data-yes>Yes, pair it</button></div>', 'nv-ask'));
  box.querySelector('[data-no]').focus();
  const answer = async yes => {
    box.close();
    try {
      const got = await api('/api/phone', { action: 'approve', yes });
      if (adding) adding.close();
      notify(yes ? 'Paired: ' + (got.paired || name) + '.' : 'Not paired. That code no longer works.');
      draw(got);
    } catch (error) { say(error.message); }
  };
  box.querySelector('[data-yes]').onclick = () => answer(true);
  box.querySelector('[data-no]').onclick = () => answer(false);
  box.addEventListener('cancel', e => { e.preventDefault(); });
}

N.phoneCommand = phoneCommand;
N.phonePair = phonePair;
})();
