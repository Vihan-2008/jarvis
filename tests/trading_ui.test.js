// The Trading panel (jcc/static/nova-trading.js): drawn from the cleaned feed, read only, paper money labelled as such,
// every server code worded (an unknown one never shown raw). Pure drawing only: no browser, server or network.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../jcc/static/nova-trading.js'), 'utf8');

function load() {
  const N = { localReply() {}, notify() {}, el() { return {}; }, panel: { append() {} }, registerPane() {}, openPane() {} };
  const context = { window: { Nova: N }, document: { body: { classList: { contains: () => false } }, addEventListener() {} },
    esc: s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
    api: async () => ({}), toast() {}, Date, Math, Object, String, Number, Array, Set, Intl };
  context.globalThis = context; vm.createContext(context); vm.runInContext(code, context);
  return N.tradingView;
}
const view = load();
const NOW = 1_800_000_000;
const looking = (extra = {}) => ({ nowS: NOW + 30, open: new Set(), closed: new Set(), ...extra });

function state(changes = {}) {
  return {
    mode: 'paper', now: NOW, currency: 'USD',
    total: { equity: 10_640.5, pnl: 640.5, partial: false, cash: 4_000, today: -12.5, put_in: 10_000 },
    month_pnl: 120, month_partial: false, live: null, markets: [],
    books: [{ id: 'trading:crypto', mode: 'trading', market: 'crypto', currency: 'USD', halted: false, status: 'active', equity: 5_400, pnl: 400, cash: 1_000,
      net_contributed: 5_000, realized: 20, unrealized: 50, fees_paid: 3, daily_pnl: 3, positions_value: 4_400, stale_marks: 0, positions_total: 1,
      positions: [{ symbol: 'BTC/USD', side: 'long', qty: 0.05, value: 4_400, unrealized: 50, weight: 0.81 }],
      series: [[NOW - 86400 * 2, 5_300, 5_000], [NOW - 86400, 5_350, 5_000], [NOW, 5_400, 5_000]],
      last_decision: { id: 9, action: 'skip', status: 'skipped', reason: 'scout_pass', when: NOW - 60, symbol: '' } }],
    kill_switch: { active: false }, paused: { active: false },
    services: [{ name: 'risk', status: 'ok', age_s: 4 }, { name: 'orchestrator', status: 'ok', age_s: 40 }],
    attention: [],
    decisions: [{ id: 9, book: 'trading:crypto', symbol: 'ETH/USD', kind: 'trade_entry', action: 'skip', status: 'skipped', reason: 'scout_pass', when: NOW - 60 },
      { id: 8, book: 'trading:crypto', symbol: 'BTC/USD', kind: 'trade_entry', action: 'buy', status: 'executed', reason: '', when: NOW - 3600 }],
    skips_7d: { scout_pass: 14, budget_exhausted: 1 },
    ...changes,
  };
}
const data = (s = state(), extra = {}) => ({ connected: { address: 'https://trading.example.test' }, goal: null, progress: null, state: s, error: '', ...extra });

test('paper money and the no-guarantee line show in every state', () => {
  const NOTICE = 'This app does not guarantee any profit. Test with paper money before you switch to real money.';
  for (const html of [view.paneHtml(null, looking({ loading: true })), view.paneHtml(null, looking({ error: 'offline' })),
    view.paneHtml({ connected: {}, goal: null, progress: null, state: null }, looking()),
    view.paneHtml(data(null, { error: 'The trading server could not be reached.' }), looking()), view.paneHtml(data(), looking())]) {
    assert.match(html, /Paper money/);
    assert.ok(html.includes(NOTICE), 'the notice is in every state');
    assert.match(html, /Read only: JARVIS cannot buy, sell or change anything/);
  }
});

test('it has no control that could change the trading app', () => {
  const html = view.paneHtml(data(state({ live: { max_stage: 'shadow', executor: { running: true, seen_age_s: 40 }, past_shadow: false, shadow_orders_7d: 1,
    books: [{ id: 'live:trading:crypto', market: 'crypto', stage: 'shadow', enabled: true, halted: false, currency: 'USD', checks_pass: false, checks: [] }],
    shadow_orders: [{ book: 'live:trading:crypto', symbol: 'BTC/USD', side: 'buy', notional: 120, state: 'shadow_logged', when: NOW }] } })), looking());
  const buttons = [...html.matchAll(/<button[^>]*>([^<]*)</g)].map(m => m[1]);
  for (const b of buttons) assert.doesNotMatch(b, /\b(buy|sell|approve|arm|halt|resume|enable|switch|live)\b/i, b);
  const attrs = [...html.matchAll(/<button[^>]*(data-tr-[a-z]+)/g)].map(m => m[1]);
  assert.deepEqual([...new Set(attrs)].sort(), ['data-tr-goal', 'data-tr-open', 'data-tr-refresh']);
  assert.doesNotMatch(html, /<form|<input|<select/);
});

test('every reason is said in words, and an unknown one never shows its code', () => {
  for (const [codeName, sentence] of Object.entries(view.REASON)) assert.equal(view.reasonText(codeName), sentence);
  assert.equal(view.reasonText('made_up_code'), view.REASON.other);
  assert.equal(view.reasonText('__proto__'), view.REASON.other);
  const s = state({ skips_7d: { scout_pass: 14, budget_exhausted: 1 },
    decisions: [{ id: 1, book: 'trading:crypto', symbol: 'ETH/USD', action: 'skip', status: 'skipped', reason: '', when: NOW }] });
  const html = view.paneHtml(data(s), looking());
  assert.match(html, /The first look found nothing worth a full review\.<\/span><b>14 times/);
  assert.match(html, /The AI budget was used up\.<\/span><b>1 time</);
  assert.match(html, /No trade, for a reason JARVIS cannot name\./);
  assert.doesNotMatch(html, /scout_pass|budget_exhausted/);
});

test('the kill switch comes first, and a failed refresh keeps the figures', () => {
  const s = state({ kill_switch: { active: true }, attention: [{ level: 'warning', kind: 'stale_prices' }, { level: 'critical', kind: 'kill_switch' }, { level: 'info', kind: 'odd_kind' }] });
  const html = view.paneHtml(data(s), looking({ failed: true }));
  const alerts = html.slice(html.indexOf('nv-tr-alerts'), html.indexOf('nv-tr-stats'));
  const lines = [...alerts.matchAll(/nv-site-state [a-z]+">([^<]*)</g)].map(m => m[1]);
  assert.equal(lines[0], 'Kill switch is on: all trading is stopped.');
  assert.ok(lines.includes('Could not refresh. Showing figures from ' + new Date(NOW * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) + '.'));
  assert.ok(lines.includes('Some prices are old.') && lines.includes('Something needs a look.'));
  assert.equal(lines.filter(l => l.startsWith('Kill switch')).length, 1, 'said once');
  assert.match(html, /\$10,640\.50/, 'the last figures stay');
});

test('old figures and missing exchange rates are said', () => {
  const html = view.paneHtml(data(state({ total: { ...state().total, partial: true } })), looking({ nowS: NOW + 12 * 60 }));
  assert.match(html, /These figures are 12 minutes old\./);
  assert.match(html, /India is left out of the totals until an exchange rate is known\./);
});

test('books start closed, and a book the owner opened stays open', () => {
  const closed = view.paneHtml(data(), looking());
  assert.match(closed, /<details class="nv-tr-fold nv-tr-book" data-tr-key="book:trading:crypto">/);
  assert.match(closed, /data-tr-key="live">/, 'real money starts closed');
  assert.match(closed, /data-tr-key="services">/, 'services start closed when all run');
  const opened = view.paneHtml(data(), looking({ open: new Set(['book:trading:crypto']) }));
  assert.match(opened, /data-tr-key="book:trading:crypto" open>/);
  const down = view.paneHtml(data(state({ services: [{ name: 'risk', status: 'down', age_s: 900 }] })), looking());
  assert.match(down, /data-tr-key="services" open>.*Services: 1 needs a look/s);
});

test('the chart draws value and money put in, and waits for two days', () => {
  const svg = view.chartSvg(state().books[0].series, 'USD');
  assert.match(svg, /<svg class="nv-tr-chart" viewBox="0 0 300 72"/);
  assert.match(svg, /aria-label="Value over the last 2 days: from \$5,300\.00 to \$5,400\.00\. Money put in: \$5,000\.00\."/);
  assert.equal((svg.match(/<path /g) || []).length, 2);
  assert.match(view.chartSvg([[NOW, 1, 1]], 'USD'), /The chart starts after two days of history\./);
});

test('real money: not shared, a shadow test, or past it', () => {
  assert.match(view.paneHtml(data(), looking()), /Real-money status is not shared with JARVIS\. To share it, switch it on in the trading app\. Its Real money page shows how\./);
  const shadow = { max_stage: 'shadow', executor: { running: true, seen_age_s: 40 }, past_shadow: false, shadow_orders_7d: 3,
    books: [{ id: 'live:trading:crypto', market: 'crypto', stage: 'shadow', enabled: true, halted: false, currency: 'USD', checks_pass: false,
      checks: [{ name: 'paper_days', pass: true, need: 60, have: 61 }, { name: 'profit_factor', pass: false, need: 1.2, have: null }] }],
    shadow_orders: [{ book: 'live:trading:crypto', symbol: 'BTC/USD', side: 'buy', notional: 120, state: 'shadow_logged', when: NOW }] };
  const html = view.paneHtml(data(state({ live: shadow })), looking());
  assert.match(html, /Real money<\/span><b>Shadow test, no orders placed/);
  assert.match(html, /records the orders it would place and places none/);
  assert.match(html, /Would buy BTC\/USD, \$120\.00/);
  assert.match(html, /Recorded, not placed/);
  assert.match(html, /Checks passed: 1 of 2/);
  assert.match(html, /Days of paper history: 61 days \(needs 60 days\)/);
  assert.match(html, /Profit factor: not known yet \(needs 1\.2 or more\)/);
  assert.ok(!html.includes('Bought BTC/USD, $120'), 'a shadow order is never said as bought');
  const past = view.paneHtml(data(state({ live: { ...shadow, past_shadow: true, shadow_orders: [],
    books: [{ id: 'live:investing:us', market: 'us', stage: 'autonomous', enabled: true, halted: false }] } })), looking());
  assert.match(past, /A real-money portfolio is past the shadow test\. JARVIS does not show its orders\./);
  assert.doesNotMatch(past, /Would buy|Shadow orders, last 7 days/);
});

test('simulated and real money are shown apart, and real money as a state, never a figure', () => {
  const slot = live => { const html = view.paneHtml(data(state({ live })), looking()); return html.slice(html.indexOf('nv-tr-real'), html.indexOf('</div>', html.indexOf('nv-tr-real'))); };
  const top = view.paneHtml(data(), looking());
  assert.ok(top.indexOf('Simulated money') < top.indexOf('nv-tr-stats') && top.indexOf('nv-tr-stats') < top.indexOf('nv-tr-real'), 'simulated totals, then real money beside them');
  assert.match(slot(null), /Not reported to JARVIS/);
  const book = (stage, halted = false) => ({ id: 'live:trading:crypto', market: 'crypto', stage, enabled: true, halted, currency: 'USD', checks: [], checks_pass: false });
  const base = { max_stage: 'shadow', executor: null, past_shadow: false, shadow_orders_7d: 0, shadow_orders: [] };
  assert.match(slot({ ...base, books: [] }), /Not in use/);
  assert.match(slot({ ...base, books: [book('off')] }), /Not in use/);
  assert.match(slot({ ...base, books: [book('shadow', true)] }), /No real money in use.*Shadow test on 1 portfolio, 1 halted/s);
  assert.match(slot({ ...base, past_shadow: true, books: [{ id: 'live:investing:us', market: 'us', stage: 'autonomous', enabled: true, halted: false }] }), /Balance not reported yet/);
  for (const live of [null, { ...base, books: [book('shadow')] }]) assert.doesNotMatch(slot(live), /\$|₹/, 'no amount in the real-money slot');
});

test('whatever the server sent is escaped before it is drawn', () => {
  const s = state({ books: [{ ...state().books[0], positions: [{ symbol: '<img src=x onerror=alert(1)>', side: 'short', value: 1, unrealized: -1, weight: 0.1 }] }] });
  const html = view.paneHtml(data(s, { connected: { address: 'https://a.test/"><script>' } }), looking());
  assert.doesNotMatch(html, /<img src=x|<script>/);
  assert.match(html, /&lt;img src=x/);
});

test('the monthly goal is shown with its paper-money line', () => {
  const goal = { monthly: 798.99, currency: 'USD', items: [], raise: { on: true, step: 0.1 } };
  const progress = { target: 878.89, raised: true, made: 120, share: 120 / 878.89, partial: true, paper: true, note: '' };
  const html = view.paneHtml(data(state(), { goal, progress }), looking());
  assert.match(html, /\+\$120\.00<\/b> of \$878\.89 this month \(14%\)/);
  assert.match(html, /Raised from \$798\.99 after months that met it/);
  assert.match(html, /Some books are not counted yet\./);
  assert.match(html, /Paper money: this tests the strategy, it does not pay for anything\./);
  assert.match(view.paneHtml(data(), looking()), /No monthly goal yet\./);
});

test('real-money setup mirrors the dashboard checklist; the commands stay on the dashboard', () => {
  const book = (id, extra = {}) => ({ id, market: 'crypto', stage: 'shadow', enabled: true, halted: false, currency: 'USD', checks: [], checks_pass: false,
    sell_code_set: false, sell_locked: false, ...extra });
  const base = { max_stage: 'shadow', past_shadow: false, shadow_orders_7d: 0, shadow_orders: [] };
  const pane = live => view.paneHtml(data(state({ live })), looking({ open: new Set(['live']) }));
  const fresh = pane({ ...base, executor: null, books: [] });
  assert.match(fresh, /Install and start the shadow executor<\/b><small>Not started/);
  assert.match(fresh, /Each step’s command is on the trading dashboard’s Real money page/);
  const stopped = pane({ ...base, executor: { running: false, seen_age_s: 900 }, books: [] });
  assert.match(stopped, /Start the shadow executor<\/b><small>Stopped/);
  const offAll = pane({ ...base, executor: { running: true, seen_age_s: 5 }, books: [book('live:trading:crypto', { stage: 'off', enabled: false })] });
  assert.match(offAll, /Every market is off/);
  const locked = pane({ ...base, executor: { running: true, seen_age_s: 5 },
    books: [book('live:trading:crypto', { sell_code_set: true, sell_locked: true }), book('live:investing:crypto', { sell_locked: true })] });
  assert.equal((locked.match(/Unlock selling/g) || []).length, 1, 'one unlock for every portfolio');
  assert.match(locked, /Sell code for [^<]*<\/b><small>To do/);
  const done = pane({ ...base, executor: { running: true, seen_age_s: 5 }, books: [book('live:trading:crypto', { sell_code_set: true })] });
  assert.match(done, /Set up: shadow running, sell codes set\. No real orders are placed\./);
  for (const html of [fresh, stopped, offAll, locked, done]) assert.doesNotMatch(html, /live\.sh|install\.sh|sell-code|unlock-sell|sudo /, 'no server command in JARVIS');
  assert.doesNotMatch(code, /runTerminal|computerUse|N\.terminal|N\.run\(|\/api\/terminal|\/api\/computer/, 'the panel never hands anything to a tool');
});
