/* /trading: the owner's paper-trading app (jcc/trading.py), in the chat. Read only: how each market is doing, its
   services, the kill switch and pause, the latest decisions, and the owner's monthly goal. Nothing here can buy, sell
   or change anything on the trading server; "Open dashboard" opens the app's own dashboard, where the owner signs in. */
(() => {
'use strict';
const N = window.Nova; if (!N || !N.localReply || document.body.classList.contains('nv-mini')) return;
const { notify } = N;
const say = text => (typeof toast === 'function' ? toast(text) : notify(text));
const SIGN = { USD: '$', INR: '₹', EUR: '€', GBP: '£' };

function money(value, currency, signed) {
  if (typeof value !== 'number' || !isFinite(value)) return '–';
  const sign = value < 0 ? '−' : signed && value > 0 ? '+' : '';
  return sign + (SIGN[currency] || (currency || '') + ' ') + Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
const tone = value => (typeof value !== 'number' ? '' : value > 0 ? ' ok' : value < 0 ? ' bad' : '');
const when = seconds => (typeof seconds === 'number' ? new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '');
const monthName = ym => (/^\d{4}-\d{2}$/.test(ym || '') ? new Date(ym + '-01T00:00:00').toLocaleDateString(undefined, { month: 'long', year: 'numeric' }) : ym || '');
const day = iso => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { dateStyle: 'medium' }) : '');
const MARKET = { crypto: 'Crypto', us: 'US stocks', in: 'India' };
const SERVICE = { marketdata: 'market data', orchestrator: 'decision maker', risk: 'risk checks', api: 'dashboard', supervisor: 'supervisor' };
const STATE = { stale: 'not updated lately', down: 'stopped', error: 'in trouble' };
const cap = text => (text ? text[0].toUpperCase() + text.slice(1) : '');
const marketOf = book => MARKET[String(book || '').split(':')[1]] || book;

async function tradingCommand(words) {
  if (/^\s*(panel|dashboard|pane)\b/i.test(String(words || ''))) return void openTradingPane();
  let data;
  try { data = await api('/api/trading', { action: 'show' }); } catch (error) { return say(error.message); }
  draw(N.localReply('Trading', ''), data);
}

function statusHtml(data) {
  const s = data.state, cur = s.currency;
  const flags = [s.kill_switch.active ? '<span class="nv-site-state bad">Kill switch on</span>' : '',
    s.paused.active ? '<span class="nv-site-state wait">Trading paused</span>' : ''].join('');
  const markets = s.markets.map(m => '<li><b>' + esc(m.label) + '</b><small>Value ' + esc(money(m.equity, cur)) + '</small>' +
    '<span class="nv-site-state' + tone(m.pnl) + '">' + esc(money(m.pnl, cur, true)) + '</span></li>').join('');
  const down = s.services.filter(v => !['ok', 'running', 'healthy', 'idle', 'up'].includes(v.status));
  const services = s.services.length ? (down.length ? '<p class="nv-site-state bad">Needs a look: ' + down.map(v => esc(SERVICE[v.name] || v.name) + ' (' + esc(STATE[v.status] || v.status || 'no word') + ')').join(', ') + '</p>'
    : '<p class="small">All ' + s.services.length + ' services are running.</p>') : '';
  const decisions = s.decisions.slice(0, 5).map(d => '<li><b>' + esc(cap(d.action || d.status || 'decision')) + ' ' + esc(d.symbol) + '</b><small>' +
    [marketOf(d.book), d.status, when(d.when)].filter(Boolean).map(esc).join(' · ') + '</small></li>').join('');
  return '<p><b>' + (s.mode === 'paper' ? 'Paper trading' : 'Trading') + '</b> · read only · ' + esc(money(s.total.equity, cur)) +
    ' · <span class="nv-site-state' + tone(s.total.pnl) + '">' + esc(money(s.total.pnl, cur, true)) + ' overall</span>' +
    (s.total.partial ? '<small> (some books are left out until an exchange rate is known)</small>' : '') + '</p>' + flags +
    (markets ? '<ul class="nv-worklist">' + markets + '</ul>' : '') + services +
    (decisions ? '<h4>Latest decisions</h4><ul class="nv-worklist">' + decisions + '</ul>' : '');
}

function goalHtml(data) {
  const g = data.goal, p = data.progress;
  if (!g || !g.monthly) return '<h4>Monthly goal</h4><p class="small">None set. Add what the trading should pay for each month.</p>';
  const made = p && typeof p.made === 'number' ? p.made : null;
  const share = p && typeof p.share === 'number' ? Math.max(0, Math.min(1, p.share)) : 0;
  const floor = money(g.monthly, g.currency), aim = money(p && typeof p.target === 'number' ? p.target : g.monthly, g.currency);
  const step = Math.round(((g.raise || {}).step || 0.1) * 100) + '%', last = p && p.last;
  const climb = !(g.raise && g.raise.on) ? 'Stays at ' + floor + ' (raising is off).'
    : p && p.raised ? 'Raised from ' + floor + ' after months that met it. It goes up ' + step + ' after each month that meets it, and never down.'
    : 'At least ' + floor + '. It goes up ' + step + ' after each month that meets it, and never down.';
  return '<h4>Monthly goal</h4><p>' + esc(aim) + ' this month</p>' +
    (g.items.length ? '<p class="small">' + g.items.map(i => esc(i.name) + ' ' + esc(money(i.amount, g.currency))).join(' · ') + '</p>' : '') +
    '<p class="small">' + esc(climb) + '</p>' +
    (last && typeof last.made === 'number' ? '<p class="small">' + esc(monthName(last.month)) + ': ' + esc(money(last.made, g.currency, true)) + ' of ' + esc(money(last.goal, g.currency)) +
      (last.met ? ', met.' : ', not met.') + '</p>' : '') +
    (made !== null ? '<p>This month: <span class="nv-site-state' + tone(made) + '">' + esc(money(made, g.currency, true)) + '</span> of ' + esc(aim) + ' (' + Math.round(share * 100) + '%)</p>' +
      '<div class="nv-use-bar" role="progressbar" aria-label="This month against this month’s goal" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(share * 100) +
      '" aria-valuetext="' + esc(money(made, g.currency) + ' of ' + aim) + '"><i data-level="low" style="width:' + (share * 100).toFixed(1) + '%"></i></div>' +
      (p.since ? '<p class="small">Counted from ' + esc(day(p.since)) + ', when JARVIS first looked this month.</p>' : '') : '') +
    (p && p.note ? '<p class="small">' + esc(p.note) + '</p>' : '') +
    (p && p.paper ? '<p class="small">Paper money: progress here is a test of the strategy, it does not pay for anything. The goal never changes how the app trades.</p>' : '');
}

function draw(node, data) {
  const box = node.querySelector('.content');
  const address = (data.connected || {}).address || '';
  box.innerHTML = (address
    ? (data.state ? statusHtml(data) : '') + (data.error ? '<p class="nv-site-state bad">' + esc(data.error) + '</p>' : '') + goalHtml(data) +
      '<div class="actions" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px"><button class="primary" type="button" data-panel>Open Trading panel</button><button class="plain" type="button" data-open>Open dashboard</button><button class="plain" type="button" data-refresh>Refresh</button>' +
      '<button class="plain" type="button" data-speak' + (data.said ? '' : ' disabled') + '>Read aloud</button><button class="plain" type="button" data-goal>' + (data.goal && data.goal.monthly ? 'Edit goal' : 'Set goal') + '</button>' +
      '<button class="plain" type="button" data-forget style="margin-left:auto">Disconnect</button></div>' +
      '<p class="small">Read only. To change anything, open the dashboard and sign in there. Connected to ' + esc(address) + '.</p>'
    : '<p class="small">See how your paper-trading app is doing, here and by voice (“how is my trading doing?”). JARVIS only looks: it cannot buy, sell or change anything there.</p>' +
      goalHtml(data) + '<div class="actions"><button class="plain" type="button" data-goal>Set goal</button></div>' +
      '<h4>Connect</h4><ol class="nv-tr-connect small">' +
      '<li>On the trading server, run this. It prints a token.<code class="nv-tr-cmd">cd /opt/trading-ai &amp;&amp; sudo docker compose exec app trading-ai jarvis-token new</code></li>' +
      '<li>Paste the token and your dashboard address below.</li></ol><form class="nv-trading-add">' +
      '<label class="nv-field"><span>Dashboard address<small>The address you open the dashboard at, starting with https://.</small></span><input name="address" placeholder="https://trading.example.com" autocomplete="off" spellcheck="false"></label>' +
      '<label class="nv-field"><span>Token<small>The one the command printed. It can only read, and it is not your password.</small></span><input name="token" type="password" autocomplete="off" spellcheck="false"></label>' +
      '<div class="actions"><button class="primary" type="submit">Connect</button></div></form>');
  const form = box.querySelector('form');
  if (form) form.onsubmit = async e => {
    e.preventDefault();
    const button = form.querySelector('[type=submit]'); button.disabled = true; button.textContent = 'Checking…';
    try { const got = await api('/api/trading', { action: 'connect', ...Object.fromEntries(new FormData(form).entries()) }); notify('Connected to the trading app.'); draw(node, got); }
    catch (error) { say(error.message); button.disabled = false; button.textContent = 'Connect'; }
  };
  box.querySelector('[data-refresh]')?.addEventListener('click', async e => {
    const button = e.currentTarget; button.disabled = true; button.textContent = 'Refreshing…';
    try { draw(node, await api('/api/trading', { action: 'show' })); } catch (error) { say(error.message); button.disabled = false; button.textContent = 'Refresh'; }
  });
  box.querySelector('[data-speak]')?.addEventListener('click', () => N.speakText ? N.speakText(data.said) : say(data.said));
  box.querySelector('[data-open]')?.addEventListener('click', () => {
    if (N.openWeb) N.openWeb(address);
    else api('/api/browser/open', { query: address }).then(() => notify('Opened in your own browser.')).catch(error => say(error.message));
  });
  box.querySelector('[data-forget]')?.addEventListener('click', async () => {
    if (!(await N.confirmBox({ title: 'Disconnect the trading app?', text: 'JARVIS forgets its address and deletes its token from this computer. Nothing changes on the trading server, and your goal is kept.', ok: 'Disconnect' }))) return;
    try { draw(node, await api('/api/trading', { action: 'disconnect' })); } catch (error) { say(error.message); }
  });
  box.querySelector('[data-goal]')?.addEventListener('click', () => editGoal(node, data));
  box.querySelector('[data-panel]')?.addEventListener('click', () => openTradingPane());
}

function editGoal(node, data, after = got => draw(node, got)) {
  const g = data.goal || {}, rows = (g.items && g.items.length ? g.items : [{ name: '', amount: '' }]);
  const line = item => '<div class="nv-goal-row" style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><input aria-label="What it pays for" placeholder="Claude Ultra" value="' + esc(item.name || '') + '" style="flex:2">' +
    '<input aria-label="Price per month" type="number" min="0" step="0.01" placeholder="200" value="' + esc(item.amount ?? '') + '" style="flex:1">' +
    '<button class="plain" type="button" data-drop aria-label="Remove this line">×</button></div>';
  const ask = N.dialog('<h2>Monthly goal</h2><p>What the trading should pay for each month. The goal is shown beside how the month is going; it never changes how the app trades.</p>' +
    '<div class="small" style="display:flex;gap:8px;margin-bottom:4px" aria-hidden="true"><span style="flex:2">What it pays for</span><span style="flex:1">Per month</span><span style="width:32px"></span></div>' +
    '<div class="nv-goal-rows">' + rows.map(line).join('') + '</div><p><button class="plain" type="button" data-more>Add a line</button></p>' +
    '<label class="nv-field"><span>Currency</span><select data-currency>' + ['USD', 'INR', 'EUR', 'GBP'].map(c => '<option' + (c === (g.currency || 'USD') ? ' selected' : '') + '>' + c + '</option>').join('') + '</select></label>' +
    '<p data-total aria-live="polite"></p>' +
    '<label style="display:flex;gap:8px;align-items:flex-start;margin-bottom:10px"><input type="checkbox" data-raise' + (!g.raise || g.raise.on ? ' checked' : '') + '>' +
    '<span>Raise the goal 10% after each month that meets it<small style="display:block">The total above stays the least it can be. A month that falls short keeps the goal where it is.</small></span></label>' +
    '<div class="actions">' + (g.monthly ? '<button class="plain" data-clear style="margin-right:auto;color:var(--bad)">Remove goal</button>' : '') + '<button class="plain" data-no>Cancel</button><button class="primary" data-yes>Save</button></div>');
  const list = ask.querySelector('.nv-goal-rows'), currency = ask.querySelector('[data-currency]');
  const read = () => [...list.querySelectorAll('.nv-goal-row')].map(r => { const [name, amount] = r.querySelectorAll('input'); return { name: name.value.trim(), amount: parseFloat(amount.value), row: r }; });
  const total = () => { const sum = read().filter(i => i.name && isFinite(i.amount)).reduce((a, i) => a + i.amount, 0); ask.querySelector('[data-total]').textContent = 'Total: ' + money(sum, currency.value) + ' a month, the least the goal can be'; };
  list.addEventListener('input', total); currency.onchange = total;
  list.addEventListener('click', e => { if (e.target.closest('[data-drop]')) { e.target.closest('.nv-goal-row').remove(); if (!list.children.length) list.insertAdjacentHTML('beforeend', line({})); total(); } });
  ask.querySelector('[data-more]').onclick = () => { list.insertAdjacentHTML('beforeend', line({})); list.lastElementChild.querySelector('input').focus(); };
  ask.querySelector('[data-no]').onclick = () => ask.close();
  ask.querySelector('[data-clear]')?.addEventListener('click', async () => {
    if (!(await N.confirmBox({ title: 'Remove the monthly goal?', text: 'The card stops showing the goal. Nothing changes in the trading app.', ok: 'Remove' }))) return;
    try { const got = await api('/api/trading', { action: 'clear_goal' }); ask.close(); after(got); } catch (error) { say(error.message); }
  });
  ask.querySelector('[data-yes]').onclick = async () => {
    const lines = read(), missing = lines.find(i => i.name && !isFinite(i.amount));
    if (missing) { say('Add a price for ' + missing.name + '.'); missing.row.querySelectorAll('input')[1].focus(); return; }
    const items = lines.filter(i => i.name && isFinite(i.amount)).map(({ name, amount }) => ({ name, amount }));
    try { const got = await api('/api/trading', { action: 'goal', items, currency: currency.value, raise: ask.querySelector('[data-raise]').checked }); ask.close(); notify('Goal saved: at least ' + money(got.goal.monthly, got.goal.currency) + ' a month.'); after(got); }
    catch (error) { say(error.message); }
  };
  total();
}

/* ================= The Trading panel: the same read-only feed, at length, beside the chat =================
   Opened from the card ("Open Trading panel") or /trading panel. It shows and never changes: no buy, sell, approve, arm,
   halt or resume control exists here; "Open the trading dashboard" opens the app's own dashboard, where the owner signs in.
   Every word the server sends is a fixed code worded below; anything unknown gets the fallback line, never the raw code. */
const X = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const REASON = {
  not_enough_data: 'Not enough price history yet.', price_moved: 'The price moved too far before the order.',
  rule_no_entry: 'The rules found no entry.', rule_skip_confirmed: 'The rules said skip, so no AI review was spent.',
  scout_pass: 'The first look found nothing worth a full review.', strategist_pass: 'The strategist proposed no trade.',
  desk_declined: 'The desk reviewed it and chose not to trade.', lead_unavailable: 'The final reviewer could not be reached.',
  forecast_unavailable: 'The price forecast was unavailable.', news_unavailable: 'The news check was unavailable.',
  budget_exhausted: 'The AI budget was used up.', expired_unreviewed: 'It expired before the desk could review it.',
  other: 'No trade, for a reason JARVIS cannot name.' };
const reasonText = code => (Object.prototype.hasOwnProperty.call(REASON, code) ? REASON[code] : REASON.other);
const ATTENTION = {
  kill_switch: 'Kill switch is on: all trading is stopped.', trading_paused: 'Trading is paused.', book_halted: 'A portfolio is halted.',
  incident: 'An error was logged in the last day.', service_silent: 'A service has gone quiet.', stale_prices: 'Some prices are old.',
  price_gap: 'A price gap needs checking.', ai_budget_exhausted: 'The AI budget is used up.',
  legacy_unassigned: 'An old account needs assigning.', decision_deferred: 'A decision is waiting.', unknown: 'Something needs a look.' };
const ORDER_STATE = { shadow_logged: 'Recorded, not placed', rejected_by_gate: 'Stopped by a limit', skipped_too_small: 'Too small', stale: 'Too old', not_mirrored: 'Not copied' };
const STAGE = { off: 'Off', shadow: 'Shadow test', approve: 'Asks you first', autonomous: 'Live', unknown: 'Unknown' };
const OKS = ['ok', 'running', 'healthy', 'idle', 'up'];
const SERVICE_STATE = { stale: 'not updated lately', down: 'stopped', error: 'in trouble' };
const LEVEL_ORDER = ['critical', 'error', 'action', 'warning', 'info'];
const NOT_TRADED = ['skipped', 'deferred', 'expired', 'failed'];
const clock = s => (typeof s === 'number' ? new Date(s * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '');
const ago = s => (typeof s !== 'number' ? '' : s < 90 ? Math.round(s) + 's ago' : s < 5400 ? Math.round(s / 60) + ' min ago' : Math.round(s / 3600) + ' h ago');
const signedPct = (v, base) => (typeof v === 'number' && typeof base === 'number' && base > 0 ? (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v / base * 100).toFixed(1) + '%' : '');
const plainNum = v => (Number.isInteger(v) ? String(v) : v.toFixed(1));
function bookLabel(id) {
  const parts = String(id || '').split(':'), [mode, market] = parts[0] === 'live' ? parts.slice(1) : parts;
  return [MARKET[market] || market || '', mode || ''].filter(Boolean).join(' ');
}
function verb(d) {
  const sell = d.action === 'sell';
  return ({ executed: sell ? 'Sold' : 'Bought', filled: sell ? 'Sold' : 'Bought', decided: sell ? 'Decided to sell' : 'Decided to buy', running: 'Reviewing',
    skipped: 'Skipped', deferred: 'Put off', expired: 'Expired', failed: 'Failed' })[d.status] || 'Decision on';
}
const pill = (kind, text) => '<span class="nv-tr-pill ' + kind + '">' + X(text) + '</span>';
const fold = (key, open, summary, inner, extra) => '<details class="nv-tr-fold' + (extra ? ' ' + extra : '') + '" data-tr-key="' + X(key) + '"' + (open ? ' open' : '') + '><summary>' + summary + '</summary><div class="nv-tr-fold-body">' + inner + '</div></details>';

function chartSvg(series, cur) {
  if (!Array.isArray(series) || series.length < 2) return '<p class="small">The chart starts after two days of history.</p>';
  const values = series.flatMap(p => [p[1], p[2]]);
  let lo = Math.min(...values), hi = Math.max(...values);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08; lo -= pad; hi += pad;
  const t0 = series[0][0], span = series[series.length - 1][0] - t0 || 1;
  const x = t => ((t - t0) / span * 300).toFixed(1), y = v => (72 - (v - lo) / (hi - lo) * 72).toFixed(1);
  const line = series.map((p, i) => (i ? 'L' : 'M') + x(p[0]) + ' ' + y(p[1])).join('');
  const step = series.map((p, i) => (i ? 'H' + x(p[0]) + 'V' : 'M' + x(p[0]) + ' ') + y(p[2])).join('');
  const days = Math.max(1, Math.round(span / 86400)), eq = series.map(p => p[1]), last = series[series.length - 1];
  const label = 'Value over the last ' + days + ' days: from ' + money(series[0][1], cur) + ' to ' + money(last[1], cur) + '. Money put in: ' + money(last[2], cur) + '.';
  return '<svg class="nv-tr-chart" viewBox="0 0 300 72" preserveAspectRatio="none" role="img" aria-label="' + X(label) + '"><path class="nv-tr-put" d="' + step + '"/><path class="nv-tr-val" d="' + line + '"/></svg>' +
    '<p class="nv-tr-legend small" aria-hidden="true"><span><i class="nv-tr-key val"></i>Value</span><span><i class="nv-tr-key put"></i>Money put in</span><span>Last ' + days + ' days, low ' + X(money(Math.min(...eq), cur)) + ', high ' + X(money(Math.max(...eq), cur)) + '</span></p>';
}

function alertsHtml(s, view) {
  const out = [], seen = new Set(['kill_switch', 'trading_paused']);
  const add = (level, text) => out.push('<p class="nv-site-state ' + level + '">' + X(text) + '</p>');
  if (s.kill_switch.active) add('bad', ATTENTION.kill_switch);
  if (s.paused.active) add('bad', ATTENTION.trading_paused);
  if (s.live && s.live.past_shadow) add('bad', 'A real-money portfolio is past the shadow test. JARVIS does not show its orders. Open the trading dashboard.');
  if (view.failed) add('wait', 'Could not refresh. Showing figures from ' + clock(s.now) + '.');
  const age = typeof s.now === 'number' ? view.nowS - s.now : 0;
  if (age > 300) add('wait', 'These figures are ' + Math.round(age / 60) + ' minutes old.');
  for (const level of LEVEL_ORDER) for (const a of s.attention.filter(a => a.level === level)) {
    if (seen.has(a.kind)) continue; seen.add(a.kind);
    add(level === 'critical' || level === 'error' ? 'bad' : 'wait', ATTENTION[a.kind] || ATTENTION.unknown);
  }
  const down = s.services.filter(v => !OKS.includes(v.status));
  if (down.length && !seen.has('service_silent')) add('wait', 'Needs a look: ' + down.map(v => SERVICE[v.name] || v.name).join(', ') + '.');
  const crit = s.kill_switch.active || s.paused.active || (s.live && s.live.past_shadow) || s.attention.some(a => a.level === 'critical');
  return '<div class="nv-tr-alerts' + (crit && out.length ? ' crit' : '') + '" role="status">' + (out.length ? out.join('') + '<button class="link-button" type="button" data-tr-open>Open the trading dashboard</button>' : '') + '</div>';
}

function totalsHtml(s) {
  const t = s.total, cur = s.currency;
  const tile = (label, value, cls) => '<div class="nv-tr-stat"><small>' + label + '</small><b class="' + (cls || '') + '">' + value + '</b></div>';
  const pct = signedPct(t.pnl, t.put_in);
  return '<h3 class="nv-tr-money">Simulated money</h3><div class="nv-tr-stats">' + tile('Total value', X(money(t.equity, cur))) +
    tile('Profit or loss', X(money(t.pnl, cur, true)) + (pct ? ' <span>' + X(pct) + '</span>' : ''), tone(t.pnl).trim()) +
    (typeof t.today === 'number' ? tile('Today', X(money(t.today, cur, true)), tone(t.today).trim()) : '') +
    (typeof t.cash === 'number' ? tile('Cash', X(money(t.cash, cur))) : '') + '</div>' +
    (t.partial ? '<p class="small">India is left out of the totals until an exchange rate is known.</p>' : '');
}

// Real money is shown apart from the simulated figures, never added to them, and as a state rather than a value while the
// real-money part is a shadow test (the trading app's own Home does the same).
const NOT_SHARED = 'Real-money status is not shared with JARVIS. To share it, switch it on in the trading app. Its Real money page shows how.';
function realSlotHtml(s) {
  const l = s.live;
  let state, note;
  if (!l) { state = 'Not reported to JARVIS'; note = NOT_SHARED; }
  else if (l.past_shadow) { state = 'Balance not reported yet'; note = 'A real-money portfolio is past the shadow test. JARVIS does not show its figures: open the trading dashboard.'; }
  else {
    const shadow = l.books.filter(b => b.stage === 'shadow'), halted = shadow.filter(b => b.halted).length;
    if (!shadow.length) { state = 'Not in use'; note = 'No real-money portfolio is switched on.'; }
    else {
      state = 'No real money in use';
      note = 'Shadow test on ' + shadow.length + (shadow.length === 1 ? ' portfolio' : ' portfolios') + (halted ? ', ' + halted + ' halted' : '') + ': it records the orders it would place and places none.';
    }
  }
  return '<div class="nv-tr-real"><h3 class="nv-tr-money">Real money ' + pill('real', 'Real') + '</h3><p><b>' + X(state) + '</b></p><p class="small">' + X(note) + '</p></div>';
}

function goalSection(data) {
  const g = data.goal, p = data.progress;
  if (!g || !g.monthly) return '<section class="nv-tr-sec"><h3>Monthly goal</h3><p class="small">No monthly goal yet.</p><div class="actions"><button class="plain" type="button" data-tr-goal>Set goal</button></div></section>';
  const made = p && typeof p.made === 'number' ? p.made : null, share = p && typeof p.share === 'number' ? Math.max(0, Math.min(1, p.share)) : 0;
  const floor = money(g.monthly, g.currency), aim = money(p && typeof p.target === 'number' ? p.target : g.monthly, g.currency);
  const step = Math.round(((g.raise || {}).step || 0.1) * 100) + '%';
  const climb = !(g.raise && g.raise.on) ? 'Stays at ' + floor + ' (raising is off).'
    : p && p.raised ? 'Raised from ' + floor + ' after months that met it. It goes up ' + step + ' after each month that meets it, and never down.'
    : 'At least ' + floor + '. It goes up ' + step + ' after each month that meets it, and never down.';
  const pct = Math.round(share * 100);
  return '<section class="nv-tr-sec"><h3>Monthly goal</h3>' +
    (made !== null ? '<p class="nv-tr-goal"><b class="' + tone(made).trim() + '">' + X(money(made, g.currency, true)) + '</b> of ' + X(aim) + ' this month (' + pct + '%)</p>' +
      '<div class="nv-use-bar" role="progressbar" aria-label="This month against this month’s goal" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct +
      '" aria-valuetext="' + X(money(made, g.currency) + ' of ' + aim) + '"><i style="width:' + (share * 100).toFixed(1) + '%"></i></div>'
      : '<p class="nv-tr-goal">' + X(aim) + ' this month</p><p class="small">' + X((p && p.note) || 'This month’s result is not known yet.') + '</p>') +
    '<p class="small">' + X(climb) + '</p>' +
    (p && p.partial ? '<p class="small">Some books are not counted yet.</p>' : '') +
    (p && p.since ? '<p class="small">Counted from ' + X(day(p.since)) + ', when JARVIS first looked this month.</p>' : '') +
    '<p class="small">Paper money: this tests the strategy, it does not pay for anything.</p>' +
    '<div class="actions"><button class="plain" type="button" data-tr-goal>Edit goal</button></div></section>';
}

function bookHtml(b, view) {
  const cur = b.currency || 'USD';
  const state = b.halted ? pill('halted', 'Halted') : b.status && b.status !== 'active' ? pill('paused', 'Paused')
    : b.stale_marks > 0 ? pill('paused', b.stale_marks + (b.stale_marks === 1 ? ' old price' : ' old prices')) : '';
  const pct = signedPct(b.pnl, b.net_contributed);
  const summary = '<span class="nv-tr-bk"><b>' + (b.mode === 'investing' ? 'Investing' : 'Trading') + '</b>' + state + '</span>' +
    '<span class="nv-tr-num">' + X(money(b.equity, cur)) + '</span><span class="nv-tr-num ' + tone(b.pnl).trim() + '">' + X(money(b.pnl, cur, true)) + (pct ? ' ' + X(pct) : '') + '</span>';
  const fig = (label, value, cls) => '<div><dt>' + label + '</dt><dd class="' + (cls || '') + '">' + X(value) + '</dd></div>';
  const figures = '<dl class="nv-tr-figs">' + fig('Cash', money(b.cash, cur)) + fig('Today', money(b.daily_pnl, cur, true), tone(b.daily_pnl).trim()) +
    fig('Realized', money(b.realized, cur, true), tone(b.realized).trim()) + fig('Fees', money(b.fees_paid, cur)) + '</dl>';
  const rows = b.positions.map(p => '<tr><td>' + (p.side === 'short' ? '<span class="nv-tr-narrow">Short </span>' : '') + X(p.symbol) + '</td><td class="nv-tr-wide">' + (p.side === 'short' ? 'Short' : 'Long') + '</td>' +
    '<td>' + X(money(p.value, cur)) + '</td><td class="' + tone(p.unrealized).trim() + '">' + X(money(p.unrealized, cur, true)) + '</td>' +
    '<td class="nv-tr-wide">' + (typeof p.weight === 'number' ? (p.weight * 100).toFixed(1) + '%' : '–') + '</td></tr>').join('');
  const positions = b.positions.length ? '<table class="nv-use-table nv-tr-pos"><caption class="nv-tr-cap">Positions</caption><thead><tr><th scope="col">Symbol</th><th scope="col" class="nv-tr-wide">Side</th><th scope="col">Value</th>' +
      '<th scope="col">Unrealized</th><th scope="col" class="nv-tr-wide">Weight</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      (b.positions_total > b.positions.length ? '<p class="small">Showing the ' + b.positions.length + ' largest of ' + b.positions_total + '.</p>' : '')
    : '<p class="small">No positions. This portfolio is all cash.</p>';
  const d = b.last_decision;
  const last = d ? '<p class="small">Last decision: ' + X((verb(d) + ' ' + (d.symbol || '')).trim()) + (d.when ? ', ' + X(when(d.when)) : '') +
    (NOT_TRADED.includes(d.status) ? '. ' + X(reasonText(d.reason)) : '.') + '</p>' : '';
  return fold('book:' + b.id, view.open.has('book:' + b.id), summary, figures + chartSvg(b.series, cur) + positions + last, 'nv-tr-book');
}

function booksHtml(s, view) {
  if (!s.books.length) return '<section class="nv-tr-sec"><h3>Portfolios</h3><p class="small">No portfolios yet.</p></section>';
  const groups = Object.entries(MARKET).map(([key, label]) => [label, s.books.filter(b => b.market === key)]);
  const other = s.books.filter(b => !MARKET[b.market]);
  if (other.length) groups.push(['Other', other]);
  return groups.filter(([, list]) => list.length).map(([label, list]) => '<section class="nv-tr-sec"><h3>' + X(label) + '</h3>' + list.map(b => bookHtml(b, view)).join('') + '</section>').join('');
}

function decisionsHtml(s, view) {
  const skips = Object.entries(s.skips_7d || {}).sort((a, b) => b[1] - a[1]);
  const skipped = skips.length ? '<h4>Skipped, last 7 days</h4><ul class="nv-tr-skips">' + skips.map(([code, n]) => '<li><span>' + X(reasonText(code)) + '</span><b>' + n + (n === 1 ? ' time' : ' times') + '</b></li>').join('') + '</ul>'
    : '<p class="small">Nothing was skipped in the last 7 days.</p>';
  const list = view.showAll ? s.decisions : s.decisions.slice(0, 8);
  const rows = list.map(d => '<li><div class="nv-tr-row"><b>' + X(verb(d) + ' ' + (d.symbol || '')) + '</b><small>' + X([bookLabel(d.book), when(d.when)].filter(Boolean).join(' · ')) + '</small></div>' +
    (NOT_TRADED.includes(d.status) ? '<p class="small">' + X(reasonText(d.reason)) + '</p>' : '') + '</li>').join('');
  const more = s.decisions.length > 8 ? '<button class="link-button" type="button" data-tr-more aria-expanded="' + !!view.showAll + '">' + (view.showAll ? 'Show fewer' : 'Show all ' + s.decisions.length) + '</button>' : '';
  return '<section class="nv-tr-sec"><h3>Recent decisions</h3>' + skipped + (rows ? '<h4>Latest</h4><ul class="nv-tr-list">' + rows + '</ul>' + more : '<p class="small">No decisions yet.</p>') + '</section>';
}

const CHECK = {
  paper_days: 'Days of paper history', shadow_days: 'Days of shadow history', round_trips: 'Completed paper trades', shadow_orders: 'Shadow orders' };
function checkLine(c, cur) {
  const unknown = 'not known yet';
  if (CHECK[c.name]) {
    const days = c.name.endsWith('_days') ? ' days' : '';
    return CHECK[c.name] + ': ' + (c.have === null ? unknown : plainNum(c.have) + days) + (c.need === null ? '' : ' (needs ' + plainNum(c.need) + days + ')');
  }
  if (c.name === 'paper_net') return 'Paper result after costs: ' + (c.have === null ? unknown : money(c.have, cur, true)) + ' (must be above zero)';
  if (c.name === 'profit_factor') return 'Profit factor: ' + (c.have === null ? unknown : c.have.toFixed(2)) + (c.need === null ? '' : ' (needs ' + plainNum(c.need) + ' or more)');
  if (c.name === 'max_drawdown') return 'Largest fall from a peak: ' + (c.have === null ? unknown : plainNum(c.have) + '%') + (c.need === null ? '' : ' (limit ' + plainNum(c.need) + '%)');
  return '';
}
// Real-money setup, mirrored from the trading dashboard's Real money page. Each step is read from the status feed.
// The commands to type on the trading server are shown there, not here: JARVIS never holds or runs them.
function setupSteps(l) {
  const ex = l.executor, on = l.books.filter(b => b.enabled && b.stage !== 'off');
  const steps = [!ex ? { title: 'Install and start the shadow executor', state: 'todo', status: 'Not started', note: 'Two commands on the server: install, then start.' }
    : !ex.running ? { title: 'Start the shadow executor', state: 'bad', status: 'Stopped' }
    : { title: 'Install and start the shadow executor', state: 'done' }];
  steps.push(!ex ? { title: 'Choose what to copy', state: 'wait' }
    : on.length ? { title: 'Choose what to copy', state: 'done' }
    : { title: 'Choose what to copy', state: 'todo', status: 'To do', note: 'Every market is off. Switch one on at the shadow stage in the limits file, then restart.' });
  if (!on.length) steps.push({ title: 'Set a sell code for each portfolio', state: 'wait' });
  // One lock covers every portfolio (one unlock), so it is one step.
  if (on.some(b => b.sell_locked)) steps.push({ title: 'Unlock selling', state: 'bad', status: 'Locked', note: 'Selling is locked after five wrong codes. One unlock covers every portfolio; they stay halted until you resume them.' });
  for (const b of on) {
    const title = 'Sell code for ' + bookLabel(b.id);
    steps.push(b.sell_code_set ? { title, state: 'done' }
      : { title, state: 'todo', status: 'To do', note: 'Your phone scans a code shown only in the server terminal.' });
  }
  return { steps, done: steps.every(s => s.state === 'done') };
}
function setupHtml(l) {
  if (l.past_shadow) return '';
  const { steps, done } = setupSteps(l);
  if (done) return '<p class="small">Set up: shadow running, sell codes set. No real orders are placed.</p>';
  const word = { done: 'Done', wait: 'Waiting for the step above' };
  return '<h4>Set up</h4><p class="small">Each step’s command is on the trading dashboard’s Real money page. Type it on the server. This list ticks itself off.</p><ol class="nv-tr-setup">' +
    steps.map(s => '<li class="nv-tr-step-' + s.state + '"><div class="nv-tr-row"><b>' + X(s.title) + '</b><small>' + X(word[s.state] || s.status) + '</small></div>' +
      (s.note ? '<p class="small">' + X(s.note) + '</p>' : '') + + '</li>').join('') + '</ol>';
}
function liveHtml(s, view) {
  const l = s.live;
  const summary = pill('real', 'Real money') + '<b>' + (l ? (l.past_shadow ? 'A portfolio is past the shadow test' : 'Shadow test, no orders placed') : 'Not reported to JARVIS') + '</b>';
  if (!l) return fold('live', view.open.has('live'), summary, '<p class="small">' + X(NOT_SHARED) + '</p>', 'nv-tr-live');
  const ex = l.executor;
  let inner = '<p class="small">The real-money part runs as a shadow test: it records the orders it would place and places none. Changes are made on the trading server, not here. Its figures are never added to the paper totals.</p>' +
    '<p>Real-money service: ' + (!ex ? 'not set up.' : ex.running ? 'running' + (typeof ex.seen_age_s === 'number' ? ', seen ' + X(ago(ex.seen_age_s)) : '') : '<span class="bad">not running</span>') + '</p>';
  inner += setupHtml(l);
  inner += l.books.length ? '<ul class="nv-tr-list">' + l.books.map(b => {
    const checks = b.checks || [], passed = checks.filter(c => c.pass).length;
    const lines = checks.map(c => '<li><span>' + X(checkLine(c, b.currency || 'USD')) + '</span><b class="' + (c.pass ? 'ok' : '') + '">' + (c.pass ? 'Passed' : 'Not yet') + '</b></li>').join('');
    return '<li><div class="nv-tr-row"><b>' + X(bookLabel(b.id)) + '</b>' + pill(b.stage === 'shadow' || b.stage === 'off' ? '' : 'real', STAGE[b.stage] || STAGE.unknown) + (b.halted ? pill('halted', 'Halted') : '') +
      (checks.length ? '<small>Checks passed: ' + passed + ' of ' + checks.length + '</small>' : '') + '</div>' +
      (checks.length ? fold('checks:' + b.id, view.open.has('checks:' + b.id), 'Readiness checks', '<ul class="nv-tr-skips">' + lines + '</ul>' + (b.checks_pass ? '<p class="small">All checks passed. This is evidence, not advice to switch.</p>' : ''), 'nv-tr-sub') : '') + '</li>';
  }).join('') + '</ul>' : '<p class="small">No real-money portfolios.</p>';
  if (!l.past_shadow) {
    inner += '<h4>Shadow orders, last 7 days: ' + (typeof l.shadow_orders_7d === 'number' ? l.shadow_orders_7d : 'not known') + '</h4>';
    inner += l.shadow_orders.length ? '<ul class="nv-tr-list">' + l.shadow_orders.map(o => '<li><div class="nv-tr-row"><b>' + X((o.side === 'sell' ? 'Would sell ' : 'Would buy ') + o.symbol + ', ' + money(o.notional, 'USD')) + '</b><small>' +
      X([bookLabel(o.book), clock(o.when)].filter(Boolean).join(' · ')) + '</small></div><p class="small">' + X(ORDER_STATE[o.state] || 'Recorded') + '</p></li>').join('') + '</ul>' : '<p class="small">No shadow orders yet.</p>';
  }
  return fold('live', view.open.has('live'), summary, inner, 'nv-tr-live');
}

function servicesHtml(s, view) {
  if (!s.services.length) return '';
  const down = s.services.filter(v => !OKS.includes(v.status));
  const summary = '<b>' + (down.length ? 'Services: ' + down.length + (down.length === 1 ? ' needs a look' : ' need a look') : 'Services: all ' + s.services.length + ' running') + '</b>';
  const rows = s.services.map(v => '<li><span>' + X(cap(SERVICE[v.name] || v.name)) + '</span><b class="' + (OKS.includes(v.status) ? 'ok' : 'bad') + '">' + X(OKS.includes(v.status) ? 'running' : SERVICE_STATE[v.status] || 'no word') + '</b>' +
    (typeof v.age_s === 'number' ? '<small>seen ' + X(ago(v.age_s)) + '</small>' : '') + '</li>').join('');
  const open = view.open.has('services') || (down.length > 0 && !view.closed.has('services'));
  return fold('services', open, summary, '<ul class="nv-tr-svc">' + rows + '</ul>');
}

function paneHtml(data, view) {
  const s = data && data.state, address = data && (data.connected || {}).address;
  const head = '<div class="tool-heading nv-tr-head"><div><h2>Trading ' + pill('paper', 'Paper money') + '</h2><p>' + (s && s.now ? 'Updated ' + X(clock(s.now)) + '. ' : '') +
    'Read only: JARVIS cannot buy, sell or change anything.</p></div>' + (address ? '<button class="plain" type="button" data-tr-refresh' + (view.cooling ? ' aria-disabled="true"' : '') + '>Refresh</button>' : '') + '</div>' +
    '<p class="nv-tr-notice">This app does not guarantee any profit. Test with paper money before you switch to real money.</p>';
  if (!data) return head + (view.loading ? '<p class="small" aria-busy="true">Loading your trading figures…</p>'
    : '<p class="nv-site-state bad">' + X(view.error || 'JARVIS could not ask for the trading figures.') + '</p><div class="actions"><button class="plain" type="button" data-tr-retry>Try again</button></div>');
  if (!address) return head + '<p>Connect the trading app first.</p><div class="actions"><button class="plain" type="button" data-tr-connect>Open /trading to connect</button></div>' + goalSection(data);
  if (!s) return head + '<p class="nv-site-state bad">' + X(data.error || 'The trading server did not answer.') + '</p><div class="actions"><button class="plain" type="button" data-tr-retry>Try again</button></div>' + goalSection(data);
  return head + alertsHtml(s, view) + totalsHtml(s) + realSlotHtml(s) + goalSection(data) + booksHtml(s, view) + decisionsHtml(s, view) + liveHtml(s, view) + servicesHtml(s, view) +
    '<div class="nv-tr-foot"><button class="link-button" type="button" data-tr-open>Open the trading dashboard</button><p class="small">Changes are made there, after you sign in. Connected to ' + X(address) + '.</p></div>';
}

const PANE = { node: null, good: null, data: null, error: '', failed: false, loading: false, errors: 0, timer: 0, last: 0, cooling: false, showAll: false, open: new Set(), closed: new Set(), html: '' };
function focusKey(node) {           // where focus is, as a selector that finds the same control after a redraw
  const at = document.activeElement;
  if (!at || !node.contains(at)) return '';
  const fold = at.tagName === 'SUMMARY' && at.parentElement.dataset.trKey;
  if (fold) return '[data-tr-key="' + CSS.escape(fold) + '"]>summary';
  const name = [...at.attributes].map(a => a.name).find(n => n.startsWith('data-tr-'));
  return name ? '[' + name + ']' : '';
}
const paneVisible = () => !!PANE.node && !PANE.node.classList.contains('hidden') && !document.hidden && document.body.classList.contains('nv-panel');
function paneDraw() {
  const view = { loading: PANE.loading, error: PANE.error, failed: PANE.failed, nowS: Date.now() / 1000, cooling: PANE.cooling, showAll: PANE.showAll, open: PANE.open, closed: PANE.closed };
  const html = paneHtml(PANE.good || PANE.data, view);
  if (html === PANE.html) return;
  const node = PANE.node, top = node.scrollTop, key = focusKey(node);
  PANE.html = html; node.innerHTML = html; node.scrollTop = top;
  if (key) { try { node.querySelector(key)?.focus({ preventScroll: true }); } catch { /* (a key that is no longer there) */ } }
}
function paneSchedule() {
  clearTimeout(PANE.timer);
  if (!paneVisible()) return;
  const wait = PANE.errors ? [60, 120, 300][Math.min(PANE.errors, 3) - 1] * 1000 : 60000;
  PANE.timer = setTimeout(() => { if (paneVisible()) paneLoad(); }, PANE.rate ? Math.max(wait, 120000) : wait);
}
async function paneLoad(fresh) {
  clearTimeout(PANE.timer); PANE.loading = true; PANE.last = Date.now();
  if (!PANE.good && !PANE.data) paneDraw();
  let got = null;
  try { got = await api('/api/trading', { action: 'show', fresh: !!fresh }); PANE.error = ''; } catch (error) { PANE.error = error.message; }
  PANE.loading = false; PANE.rate = !!got && got.error_kind === 'rate';
  if (got && got.state) { PANE.good = got; PANE.data = got; PANE.failed = false; PANE.errors = 0; }
  else if (got && !(got.connected || {}).address) { PANE.good = null; PANE.data = got; PANE.failed = false; PANE.errors = 0; }
  else { PANE.errors += 1; PANE.failed = !!PANE.good; if (got) PANE.data = got; if (PANE.good && got) PANE.good = { ...PANE.good, goal: got.goal, progress: got.goal ? PANE.good.progress : null }; }
  paneDraw(); paneSchedule();
}
function paneGoalSaved(got) {
  if (got.state) { PANE.good = got; PANE.data = got; }
  else { PANE.data = { ...(PANE.data || {}), ...got }; if (PANE.good) PANE.good = { ...PANE.good, goal: got.goal, progress: got.goal ? got.progress || PANE.good.progress : null }; }
  paneDraw();
}
function paneNode() {
  if (PANE.node) return PANE.node;
  const node = PANE.node = N.el('section', { id: 'tool-nvtrading', class: 'tool-content nv-pane nv-tr hidden', 'aria-label': 'Trading' }, '');
  node.dataset.w = 'wide'; N.panel.append(node);
  if (window.ResizeObserver) new ResizeObserver(entries => { const w = node.clientWidth; if (w) node.dataset.w = w < 520 ? 'narrow' : 'wide'; }).observe(node);
  node.addEventListener('toggle', e => {
    const key = e.target.dataset && e.target.dataset.trKey; if (!key) return;
    if (e.target.open) { PANE.open.add(key); PANE.closed.delete(key); } else { PANE.open.delete(key); PANE.closed.add(key); }
    PANE.html = '';          // (the next draw is compared afresh: the page itself now differs from the last one drawn)
  }, true);
  node.addEventListener('click', e => {
    const t = e.target.closest('button'); if (!t) return;
    const data = PANE.good || PANE.data || {}, address = (data.connected || {}).address;
    if (t.getAttribute('aria-disabled') === 'true') return;
    if (t.hasAttribute('data-tr-refresh')) { PANE.cooling = true; setTimeout(() => { PANE.cooling = false; paneDraw(); }, 10000); paneLoad(true); }
    else if (t.hasAttribute('data-tr-retry')) paneLoad(true);
    else if (t.hasAttribute('data-tr-open') && address) { if (N.openWeb) N.openWeb(address); else api('/api/browser/open', { query: address }).then(() => notify('Opened in your own browser.')).catch(error => say(error.message)); }
    else if (t.hasAttribute('data-tr-connect')) tradingCommand();
    else if (t.hasAttribute('data-tr-goal')) editGoal(null, data, paneGoalSaved);
    else if (t.hasAttribute('data-tr-more')) { PANE.showAll = !PANE.showAll; paneDraw(); }
  });
  document.addEventListener('visibilitychange', () => { if (paneVisible()) { if (Date.now() - PANE.last > 60000) paneLoad(); else paneSchedule(); } });
  return node;
}
function openTradingPane() {
  N.registerPane({ id: 'trading', label: 'Trading', icon: 'pulse', node: paneNode(), tip: 'Your paper-trading app at length: read only', show: () => paneLoad() });
  return N.openPane('trading');
}

N.tradingCommand = tradingCommand;
N.openTradingPane = openTradingPane;
N.tradingView = { paneHtml, chartSvg, reasonText, REASON, ATTENTION };     // (pure: the page tests draw with it)
})();
