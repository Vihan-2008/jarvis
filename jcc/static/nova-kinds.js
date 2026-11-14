/* NOVA kinds: four more things JARVIS and its owner can make, each drawn by this app itself from plain text.
   Slides (Markdown, a line of --- between one slide and the next), a sheet (CSV, with formulas), a chart (a few lines of
   JSON) and a whiteboard (drawn by hand). What is in them is data: words go in as words, numbers as numbers, and a
   formula is worked out by the small reader below. Nothing in them is ever run as code. */
(root => {
'use strict';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (v, low, high) => Math.min(high, Math.max(low, v));
const SVG = 'http://www.w3.org/2000/svg';
const doc = () => root.document;
function svgNode(tag, attrs = {}, text) { const n = doc().createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (text != null) n.textContent = String(text); return n; }
function node(tag, cls, text) { const n = doc().createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = String(text); return n; }
const icon = name => (root.NovaIcon ? root.NovaIcon(name) : '');

/* ================= Sheet: CSV with formulas ================= */
const MOST_ROWS = 2000, MOST_COLS = 60;
function parseCsv(text, most = MOST_ROWS) {
  // (A formula written without quotes keeps the commas inside its brackets: =ROUND(C5,1) is one cell, not two.)
  const rows = []; let row = [], cell = '', quoted = false, deep = 0, i = 0; text = String(text ?? '').replace(/\r\n?/g, '\n');
  while (i < text.length) {
    const c = text[i];
    if (quoted) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i += 2; continue; } quoted = false; i++; continue; } cell += c; i++; continue; }
    if (c === '"' && cell === '') { quoted = true; i++; continue; }
    if (c === ',' && deep <= 0) { row.push(cell); cell = ''; deep = 0; i++; continue; }
    if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; deep = 0; i++; if (rows.length >= most) return rows; continue; }
    cell += c; i++;
    if (cell[0] === '=') { if (c === '(') deep++; else if (c === ')') deep--; }
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}
function toCsv(rows) {
  let last = rows.length; while (last > 0 && rows[last - 1].every(c => c === '')) last--;
  let wide = 0; for (const r of rows.slice(0, last)) for (let c = r.length; c > wide; c--) if (r[c - 1] !== '') { wide = c; break; }
  return rows.slice(0, last).map(r => r.slice(0, wide).map(c => /[",\n]/.test(c) || /^\s|\s$/.test(c) ? '"' + String(c).replace(/"/g, '""') + '"' : c).join(',')).join('\n');
}
const colName = n => { let s = ''; for (n += 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; };
const colIndex = s => { let n = 0; for (const ch of s.toUpperCase()) n = n * 26 + ch.charCodeAt(0) - 64; return n - 1; };
const asNumber = text => { const t = String(text).trim(); if (t === '') return null; const n = Number(t.replace(/^(-?)[$€£₹]/, '$1').replace(/(\d),(?=\d{3}\b)/g, '$1').replace(/%$/, '')); return Number.isFinite(n) ? (/%$/.test(t) ? n / 100 : n) : null; };
const TOKENS = /\s+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+|"[^"]*"|[A-Za-z]{1,3}\d{1,5}(?::[A-Za-z]{1,3}\d{1,5})?|[A-Za-z_]+|<>|<=|>=|[-+*/^()=<>,]/g;
const KNOWN = new Set(['SUM', 'AVERAGE', 'AVG', 'MIN', 'MAX', 'COUNT', 'ROUND', 'ABS', 'IF']);
/* A sheet saved as a file for a spreadsheet program.

   Such a program runs what a cell says when the cell starts with = + - or @: it will fetch an address, read another
   file, even start a program. What is in a sheet may have come from anywhere (a reply written from a web page or an
   email), so only what this app itself understands is left as a formula: numbers, cells, ranges, the operators and
   the functions above. Any other cell a spreadsheet program would run is saved as plain text, with an apostrophe in
   front. values: every formula is replaced by what it comes to here, so no formula is left at all.

   Returns { text, changed }: the file's text, and how many cells were made plain text. */
function understood(cell) {
  const body = cell.slice(1), tokens = body.match(TOKENS) || [];
  return tokens.join('').length === body.length && tokens.every(t => !/^[A-Za-z_]+$/.test(t) || KNOWN.has(t.toUpperCase()));
}
function exportCsv(code, values = false) {
  const grid = parseCsv(code), got = values ? compute(grid) : null; let changed = 0;
  const plain = (text, formulas) => {
    const t = text.replace(/^[\s\uFEFF]+/, '');
    if (!/^[=+\-@]/.test(t) || asNumber(t) !== null) return text;            // (-5, +5 and -5% are numbers)
    if (t[0] === '=' ? formulas && t === text && understood(text) : !/[|!]|[A-Za-z_][\w.]*\s*\(/.test(t)) return text;      // (+1 555 0100 and "- none" call nothing)
    changed++; return "'" + text;
  };
  const text = toCsv(grid.map((row, r) => row.map((raw, c) => {
    let cell = String(raw ?? '');
    if (values && cell[0] === '=') { const v = got[r][c]; cell = v && typeof v === 'object' ? v.error : typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : typeof v === 'number' ? String(Number(v.toPrecision(12))) : String(v); }
    return plain(cell, !values);
  })));
  return { text, changed };
}
/* What a sheet's cells come to. A cell that starts with = is a formula: numbers, cells (B2), ranges (B2:B9) inside a
   function, + - * / ^, brackets, comparisons, and SUM AVERAGE MIN MAX COUNT ROUND ABS IF. Anything else is an error
   shown in the cell; nothing is ever run. */
function compute(grid) {
  const memo = new Map(), busy = new Set(); let work = 0;
  const fail = code => { const e = new Error(code); e.sheet = code; return e; };
  function value(r, c) {
    const raw = grid[r]?.[c] ?? '';
    if (typeof raw !== 'string' || raw[0] !== '=') { const n = asNumber(raw); return n === null ? String(raw) : n; }
    const key = r + ':' + c;
    if (memo.has(key)) { const got = memo.get(key); if (got instanceof Error) throw got; return got; }
    if (busy.has(key)) throw fail('#CYCLE');
    if (++work > 20000) throw fail('#ERR');
    busy.add(key);
    try { const got = formula(raw.slice(1)); memo.set(key, got); return got; }
    catch (error) { const kept = error.sheet ? error : fail('#ERR'); memo.set(key, kept); throw kept; }
    finally { busy.delete(key); }
  }
  const num = v => { if (typeof v === 'number') return v; if (typeof v === 'boolean') return v ? 1 : 0; if (v === '') return 0; const n = asNumber(v); if (n === null) throw fail('#VALUE'); return n; };
  function formula(text) {
    const tokens = text.match(TOKENS) || [];
    if (tokens.join('').length !== text.length) throw fail('#ERR');
    const t = tokens.filter(x => !/^\s+$/.test(x)); let at = 0;
    const peek = () => t[at], take = x => { if (t[at] !== x) throw fail('#ERR'); at++; };
    const cell = name => { const m = /^([A-Za-z]{1,3})(\d{1,5})$/.exec(name); return [Number(m[2]) - 1, colIndex(m[1])]; };
    function range(name) {
      const [a, b] = name.split(':'), [r1, c1] = cell(a), [r2, c2] = cell(b), out = [];
      if ((Math.abs(r2 - r1) + 1) * (Math.abs(c2 - c1) + 1) > 100000) throw fail('#ERR');
      for (let r = Math.min(r1, r2); r <= Math.max(r1, r2); r++) for (let c = Math.min(c1, c2); c <= Math.max(c1, c2); c++) out.push(value(r, c));
      return out;
    }
    function args() {
      const out = []; take('(');
      if (peek() === ')') { at++; return out; }
      for (;;) { if (/^[A-Za-z]{1,3}\d{1,5}:/.test(peek() || '')) out.push(range(t[at++])); else out.push(compare()); if (peek() === ',') { at++; continue; } take(')'); return out; }
    }
    function primary() {
      const x = t[at]; if (x === undefined) throw fail('#ERR');
      if (x === '(') { at++; const v = compare(); take(')'); return v; }
      if (/^[\d.]/.test(x)) { at++; return Number(x); }
      if (x[0] === '"') { at++; return x.slice(1, -1); }
      if (/^[A-Za-z]{1,3}\d{1,5}$/.test(x)) { at++; const [r, c] = cell(x); return value(r, c); }
      if (/^[A-Za-z_]+$/.test(x)) {
        at++; const name = x.toUpperCase(), list = args(), flat = list.flat(), nums = flat.filter(v => typeof v === 'number');
        if (name === 'SUM') return nums.reduce((a, b) => a + b, 0);
        if (name === 'AVERAGE' || name === 'AVG') { if (!nums.length) throw fail('#DIV/0'); return nums.reduce((a, b) => a + b, 0) / nums.length; }
        if (name === 'MIN') return nums.length ? Math.min(...nums) : 0;
        if (name === 'MAX') return nums.length ? Math.max(...nums) : 0;
        if (name === 'COUNT') return nums.length;
        if (name === 'ABS' && list.length === 1) return Math.abs(num(list[0]));
        if (name === 'ROUND' && list.length >= 1 && list.length <= 2) { const p = 10 ** clamp(Math.round(list.length > 1 ? num(list[1]) : 0), -9, 9); return Math.round(num(list[0]) * p) / p; }
        if (name === 'IF' && list.length >= 2 && list.length <= 3) { const on = list[0]; return (typeof on === 'string' ? on !== '' : !!on) ? list[1] : (list.length > 2 ? list[2] : ''); }
        throw fail('#NAME');
      }
      throw fail('#ERR');
    }
    function unary() { if (peek() === '-') { at++; return -num(unary()); } if (peek() === '+') { at++; return num(unary()); } return primary(); }
    function power() { const base = unary(); if (peek() === '^') { at++; return num(base) ** num(unary()); } return base; }
    function product() { let v = power(); while (peek() === '*' || peek() === '/') { const op = t[at++], w = num(power()); if (op === '/' && w === 0) throw fail('#DIV/0'); v = op === '*' ? num(v) * w : num(v) / w; } return v; }
    function sum() { let v = product(); while (peek() === '+' || peek() === '-') { const op = t[at++], w = num(product()); v = op === '+' ? num(v) + w : num(v) - w; } return v; }
    function compare() {
      const a = sum(), op = peek(); if (!['=', '<>', '<', '>', '<=', '>='].includes(op)) return a;
      at++; const b = sum(), both = typeof a === 'number' && typeof b === 'number', x = both ? a : String(a).toLowerCase(), y = both ? b : String(b).toLowerCase();
      return op === '=' ? x === y : op === '<>' ? x !== y : op === '<' ? x < y : op === '>' ? x > y : op === '<=' ? x <= y : x >= y;
    }
    const out = compare(); if (at !== t.length) throw fail('#ERR');
    if (typeof out === 'number' && !Number.isFinite(out)) throw fail('#NUM');
    return out;
  }
  return grid.map((row, r) => row.map((raw, c) => { try { return value(r, c); } catch (error) { return { error: error.sheet || '#ERR' }; } }));
}
const shownValue = v => v && typeof v === 'object' ? v.error : typeof v === 'number' ? (Number.isInteger(v) ? v.toLocaleString('en') : Number(v.toPrecision(12)).toLocaleString('en', { maximumFractionDigits: Math.abs(v) >= 100 ? 2 : Math.abs(v) >= 1 ? 4 : 6 }))
  : typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : v;
function squared(code) {
  const rows = parseCsv(code), wide = clamp(Math.max(1, ...rows.map(r => r.length)), 1, MOST_COLS);
  return (rows.length ? rows : [['']]).map(r => Array.from({ length: wide }, (_, c) => r[c] ?? ''));
}
function renderSheet(host, ctx) {
  let grid = squared(ctx.code), at = [0, 0];
  const can = typeof ctx.save === 'function';
  const bar = node('div', 'nv-sheet-bar'), name = node('span', 'nv-sheet-name', 'A1'), input = node('input', 'nv-sheet-input');
  input.spellcheck = false; input.setAttribute('aria-label', 'What is in the selected cell'); input.readOnly = !can; input.placeholder = can ? 'Type a value, or a formula such as =SUM(B2:B9)' : '';
  const addRow = node('button', 'plain', '+ Row'), addCol = node('button', 'plain', '+ Column');
  bar.append(name, input); if (can) bar.append(addRow, addCol);
  const scroll = node('div', 'nv-sheet-scroll'), table = node('table', 'nv-sheet'); table.tabIndex = 0;
  scroll.append(table); host.append(bar, scroll);
  if (!can && ctx.note) host.append(node('p', 'nv-kind-note', ctx.note));
  function draw() {
    const values = compute(grid), head = node('tr'); table.replaceChildren();
    head.append(node('th')); for (let c = 0; c < grid[0].length; c++) head.append(node('th', '', colName(c)));
    table.append(head);
    grid.forEach((row, r) => {
      const tr = node('tr'); tr.append(node('th', '', r + 1));
      row.forEach((raw, c) => {
        const v = values[r][c], td = node('td', (r === 0 ? 'head ' : '') + (typeof v === 'number' ? 'num ' : '') + (v && typeof v === 'object' ? 'err ' : '') + (r === at[0] && c === at[1] ? 'on' : ''), shownValue(v));
        td.dataset.r = r; td.dataset.c = c; tr.append(td);
      });
      table.append(tr);
    });
  }
  function select(r, c, focus) {
    at = [clamp(r, 0, grid.length - 1), clamp(c, 0, grid[0].length - 1)];
    table.querySelector('td.on')?.classList.remove('on');
    const td = table.querySelector('td[data-r="' + at[0] + '"][data-c="' + at[1] + '"]'); td?.classList.add('on'); td?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    name.textContent = colName(at[1]) + (at[0] + 1); input.value = grid[at[0]][at[1]];
    if (focus) input.focus();
  }
  function commit() {
    if (!can || grid[at[0]][at[1]] === input.value) return;
    grid[at[0]][at[1]] = input.value; draw(); select(at[0], at[1]); ctx.save(toCsv(grid));
  }
  table.addEventListener('click', e => { const td = e.target.closest('td'); if (td) { commit(); select(Number(td.dataset.r), Number(td.dataset.c)); } });
  table.addEventListener('dblclick', e => { if (e.target.closest('td')) { input.focus(); input.select(); } });
  table.addEventListener('keydown', e => {
    const move = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key];
    if (move) { e.preventDefault(); select(at[0] + move[0], at[1] + move[1]); }
    else if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); input.focus(); input.select(); }
    else if (can && (e.key === 'Delete' || e.key === 'Backspace')) { e.preventDefault(); input.value = ''; commit(); }
    else if (can && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { input.value = ''; input.focus(); }
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); commit(); select(at[0] + 1, at[1]); table.focus(); }
    else if (e.key === 'Tab') { e.preventDefault(); commit(); select(at[0], at[1] + (e.shiftKey ? -1 : 1)); table.focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); input.value = grid[at[0]][at[1]]; table.focus(); }
  });
  input.addEventListener('blur', commit);
  addRow.onclick = () => { if (grid.length >= MOST_ROWS) return; grid.push(Array.from({ length: grid[0].length }, () => '')); draw(); select(grid.length - 1, at[1]); };
  addCol.onclick = () => { if (grid[0].length >= MOST_COLS) return; grid.forEach(r => r.push('')); draw(); select(at[0], grid[0].length - 1); };
  draw(); select(0, 0);
}
function sheetPage(code, title) {
  const grid = squared(code), values = compute(grid);
  return page(title, '<table>' + grid.map((row, r) => '<tr>' + row.map((_, c) => { const v = values[r][c], tag = r === 0 ? 'th' : 'td'; return '<' + tag + (typeof v === 'number' ? ' class="num"' : '') + '>' + esc(shownValue(v)) + '</' + tag + '>'; }).join('') + '</tr>').join('') + '</table>',
    'table{border-collapse:collapse;font-size:14px}th,td{border:1px solid #d9d9e0;padding:6px 10px;text-align:left}th{background:#f3f3f7}.num{text-align:right;font-variant-numeric:tabular-nums}');
}

/* ================= Chart: a few lines of JSON ================= */
const PALETTE = ['#7c6cf0', '#22b8a5', '#f0a43c', '#e5637b', '#4c9be8', '#9bc53d', '#b07cf0', '#f07c4c'];
const TYPES = ['bar', 'line', 'area', 'pie', 'scatter'];
function readChart(code) {
  let data; try { data = JSON.parse(String(code)); } catch { return { problem: 'This chart’s data is not valid JSON.' }; }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return { problem: 'A chart is written as { "type", "title", "x", "series" }.' };
  const words = (v, most = 60) => (typeof v === 'string' || typeof v === 'number' ? String(v) : '').slice(0, most);
  const x = (Array.isArray(data.x) ? data.x : []).slice(0, 400).map(v => words(v, 40));
  const series = (Array.isArray(data.series) ? data.series : []).filter(s => s && typeof s === 'object').slice(0, 12).map((s, i) => ({ name: words(s.name) || 'Series ' + (i + 1),
    values: (Array.isArray(s.values) ? s.values : []).slice(0, 400).map(v => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && asNumber(v) !== null ? asNumber(v) : null)) }));
  if (!series.length || !series.some(s => s.values.some(v => v !== null))) return { problem: 'This chart has no numbers to draw yet.' };
  const type = TYPES.includes(data.type) ? data.type : 'bar', count = Math.max(...series.map(s => s.values.length));
  while (x.length < count) x.push(String(x.length + 1));
  return { type, title: words(data.title, 120), x: x.slice(0, count), series, xLabel: words(data.xLabel), yLabel: words(data.yLabel), unit: words(data.unit, 12) };
}
function ticks(low, high, most = 6) {
  if (low === high) { high = low + 1; }
  const rough = (high - low) / most, mag = 10 ** Math.floor(Math.log10(rough)), step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= rough) || 10 * mag;
  const from = Math.floor(low / step) * step, to = Math.ceil(high / step) * step, out = [];
  for (let v = from; v <= to + step / 2; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}
const short = v => Math.abs(v) >= 1e9 ? Number((v / 1e9).toPrecision(3)) + 'B' : Math.abs(v) >= 1e6 ? Number((v / 1e6).toPrecision(3)) + 'M' : Math.abs(v) >= 1e4 ? Number((v / 1e3).toPrecision(3)) + 'k' : String(Number(v.toPrecision(6)));
/* The chart as a picture (an SVG element), from what readChart gave. ink: the colour of its words and lines. */
function chartSvg(chart, ink = 'currentColor') {
  const W = 720, H = 420, svg = svgNode('svg', { xmlns: SVG, viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'font-family': 'system-ui, Segoe UI, sans-serif' });
  svg.append(svgNode('title', {}, chart.title || 'Chart'));
  if (chart.title) svg.append(svgNode('text', { x: W / 2, y: 26, 'text-anchor': 'middle', 'font-size': 16, 'font-weight': 600, fill: ink }, chart.title));
  const legend = chart.type === 'pie' ? chart.x : chart.series.map(s => s.name), top = chart.title ? 46 : 18, bottom = H - (legend.length > 1 || chart.type === 'pie' ? 58 : 40);
  const key = (label, i, n) => {
    const each = Math.min(170, (W - 40) / Math.max(1, Math.min(n, 8))), row = Math.floor(i / 8), x0 = (W - each * Math.min(n - row * 8, 8)) / 2 + (i % 8) * each, y0 = H - 22 + row * 16 - (n > 8 ? 12 : 0);
    svg.append(svgNode('rect', { x: x0, y: y0 - 9, width: 10, height: 10, rx: 2, fill: PALETTE[i % PALETTE.length] }), svgNode('text', { x: x0 + 15, y: y0, 'font-size': 11.5, fill: ink }, label.slice(0, 22)));
  };
  if (chart.type === 'pie') {
    const values = chart.series[0].values.map(v => (v !== null && v > 0 ? v : 0)), total = values.reduce((a, b) => a + b, 0) || 1, cx = W / 2, cy = (top + bottom) / 2, r = Math.min(bottom - top, W) / 2 - 6;
    let angle = -Math.PI / 2;
    values.forEach((v, i) => {
      if (!v) return; const next = angle + v / total * Math.PI * 2, big = next - angle > Math.PI ? 1 : 0, mid = (angle + next) / 2;
      const slice = v === total ? svgNode('circle', { cx, cy, r, fill: PALETTE[i % PALETTE.length] })
        : svgNode('path', { d: `M${cx} ${cy}L${(cx + r * Math.cos(angle)).toFixed(2)} ${(cy + r * Math.sin(angle)).toFixed(2)}A${r} ${r} 0 ${big} 1 ${(cx + r * Math.cos(next)).toFixed(2)} ${(cy + r * Math.sin(next)).toFixed(2)}Z`, fill: PALETTE[i % PALETTE.length], stroke: '#fff', 'stroke-width': 1 });
      slice.append(svgNode('title', {}, chart.x[i] + ': ' + short(v) + chart.unit + ' (' + Math.round(v / total * 100) + '%)')); svg.append(slice);
      if (v / total > 0.05) svg.append(svgNode('text', { x: cx + r * 0.62 * Math.cos(mid), y: cy + r * 0.62 * Math.sin(mid) + 4, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 600, fill: '#fff' }, Math.round(v / total * 100) + '%'));
      angle = next;
    });
    chart.x.slice(0, 16).forEach((label, i) => key(label, i, Math.min(chart.x.length, 16)));
    return svg;
  }
  const left = 58, right = W - 18, all = chart.series.flatMap(s => s.values.filter(v => v !== null)), scatter = chart.type === 'scatter';
  const ys = ticks(Math.min(0, ...all), Math.max(0, ...all)), y0 = ys[0], y1 = ys[ys.length - 1], py = v => bottom - (v - y0) / (y1 - y0) * (bottom - top);
  const xn = scatter ? chart.x.map(v => asNumber(v)) : null, numeric = scatter && xn.every(v => v !== null);
  const xs = numeric ? ticks(Math.min(...xn), Math.max(...xn)) : null, n = chart.x.length, band = (right - left) / Math.max(1, n);
  const px = i => numeric ? left + (xn[i] - xs[0]) / (xs[xs.length - 1] - xs[0]) * (right - left) : left + band * (i + 0.5);
  for (const t of ys) svg.append(svgNode('line', { x1: left, x2: right, y1: py(t), y2: py(t), stroke: ink, 'stroke-opacity': t === 0 ? 0.55 : 0.13 }), svgNode('text', { x: left - 8, y: py(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: ink, 'fill-opacity': 0.75 }, short(t) + chart.unit));
  if (numeric) for (const t of xs) svg.append(svgNode('text', { x: left + (t - xs[0]) / (xs[xs.length - 1] - xs[0]) * (right - left), y: bottom + 16, 'text-anchor': 'middle', 'font-size': 11, fill: ink, 'fill-opacity': 0.75 }, short(t)));
  else { const every = Math.ceil(n / 12); chart.x.forEach((label, i) => { if (i % every === 0) svg.append(svgNode('text', { x: px(i), y: bottom + 16, 'text-anchor': 'middle', 'font-size': 11, fill: ink, 'fill-opacity': 0.75 }, label.slice(0, Math.max(4, Math.floor(band * every / 6.5))))); }); }
  if (chart.yLabel) svg.append(svgNode('text', { x: 14, y: (top + bottom) / 2, 'text-anchor': 'middle', 'font-size': 11.5, fill: ink, 'fill-opacity': 0.75, transform: `rotate(-90 14 ${(top + bottom) / 2})` }, chart.yLabel));
  if (chart.xLabel) svg.append(svgNode('text', { x: (left + right) / 2, y: bottom + 32, 'text-anchor': 'middle', 'font-size': 11.5, fill: ink, 'fill-opacity': 0.75 }, chart.xLabel));
  chart.series.forEach((s, k) => {
    const colour = PALETTE[k % PALETTE.length], tip = (i, v) => s.name + ', ' + chart.x[i] + ': ' + short(v) + chart.unit;
    if (chart.type === 'bar') {
      const wide = Math.max(1, band * 0.76 / chart.series.length);
      s.values.forEach((v, i) => { if (v === null) return; const bar = svgNode('rect', { x: (left + band * i + band * 0.12 + wide * k).toFixed(2), y: Math.min(py(v), py(0)).toFixed(2), width: Math.max(1, wide - 1).toFixed(2), height: Math.max(0.5, Math.abs(py(v) - py(0))).toFixed(2), rx: Math.min(3, wide / 4), fill: colour }); bar.append(svgNode('title', {}, tip(i, v))); svg.append(bar); });
      return;
    }
    const points = s.values.map((v, i) => (v === null ? null : [px(i), py(v), i, v])).filter(Boolean);
    if (!scatter && points.length) {
      const line = points.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(2) + ' ' + p[1].toFixed(2)).join('');
      if (chart.type === 'area') svg.append(svgNode('path', { d: line + `L${points[points.length - 1][0].toFixed(2)} ${py(0).toFixed(2)}L${points[0][0].toFixed(2)} ${py(0).toFixed(2)}Z`, fill: colour, 'fill-opacity': 0.18 }));
      svg.append(svgNode('path', { d: line, fill: 'none', stroke: colour, 'stroke-width': 2.2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    }
    for (const p of points) { const dot = svgNode('circle', { cx: p[0].toFixed(2), cy: p[1].toFixed(2), r: scatter ? 4 : points.length > 40 ? 1.6 : 3, fill: colour }); dot.append(svgNode('title', {}, tip(p[2], p[3]))); svg.append(dot); }
  });
  if (legend.length > 1) legend.forEach((label, i) => key(label, i, legend.length));
  return svg;
}
function renderChart(host, ctx) {
  const chart = readChart(ctx.code), box = node('div', 'nv-chart');
  if (chart.problem) box.append(node('p', 'nv-kind-note', chart.problem + ' Its text is under Show code.')); else box.append(chartSvg(chart));
  host.append(box);
}
const svgText = svg => new (root.XMLSerializer)().serializeToString(svg);
function chartPicture(code, ink = '#22222a') { const chart = readChart(code); return chart.problem ? '' : svgText(chartSvg(chart, ink)); }

/* ================= Slides: Markdown, a line of --- between slides ================= */
function splitSlides(code) {
  const out = []; let now = [], fenced = false;
  for (const line of String(code ?? '').replace(/\r\n?/g, '\n').split('\n')) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    if (!fenced && /^\s*-{3,}\s*$/.test(line)) { out.push(now.join('\n')); now = []; } else now.push(line);
  }
  out.push(now.join('\n'));
  return out.map(s => s.trim()).filter(Boolean).slice(0, 300);
}
const richText = md => (root.NovaRich ? root.NovaRich.rich(md) : '<p>' + esc(md) + '</p>');
function renderSlides(host, ctx) {
  const slides = splitSlides(ctx.code); let at = 0;
  const stage = node('div', 'nv-slides'), frame = node('div', 'nv-slide-frame'), slide = node('div', 'nv-slide nv-doc-text'), bar = node('div', 'nv-slides-bar');
  const prev = node('button', 'plain', '‹'), next = node('button', 'plain', '›'), count = node('span', 'nv-art-version'), present = node('button', 'plain');
  prev.setAttribute('aria-label', 'The slide before'); next.setAttribute('aria-label', 'The next slide'); present.innerHTML = icon('full') + 'Present';
  frame.append(slide); stage.append(frame); bar.append(prev, count, next, present); host.append(stage, bar); stage.tabIndex = 0;
  if (!slides.length) { slide.textContent = 'There are no slides in this yet.'; }
  function fit() { const w = frame.clientWidth; if (w) slide.style.transform = 'scale(' + (w / 960) + ')'; }
  function draw() {
    if (!slides.length) return;
    at = clamp(at, 0, slides.length - 1);
    slide.className = 'nv-slide nv-doc-text' + (at === 0 && /^#\s/.test(slides[0]) ? ' title' : ''); slide.style.fontSize = '';
    slide.innerHTML = richText(slides[at]);                     // (the same safe reading a reply gets: words stay words)
    for (const size of [26, 23, 20, 17, 15]) { slide.style.fontSize = size + 'px'; if (slide.scrollHeight <= 540) break; }
    count.textContent = (at + 1) + ' of ' + slides.length; prev.disabled = at === 0; next.disabled = at === slides.length - 1; fit();
  }
  const go = by => { at += by; draw(); };
  prev.onclick = () => go(-1); next.onclick = () => go(1);
  stage.addEventListener('keydown', e => {
    if (['ArrowRight', 'PageDown', ' ', 'Enter'].includes(e.key)) { e.preventDefault(); go(1); }
    else if (['ArrowLeft', 'PageUp', 'Backspace'].includes(e.key)) { e.preventDefault(); go(-1); }
    else if (e.key === 'Home') { at = 0; draw(); } else if (e.key === 'End') { at = slides.length - 1; draw(); }
  });
  stage.addEventListener('click', e => { if (doc().fullscreenElement === stage && !e.target.closest('a, button')) go(1); });
  present.onclick = () => { stage.requestFullscreen?.().then(() => { stage.focus(); fit(); }).catch(() => {}); };
  doc().addEventListener('fullscreenchange', () => { if (stage.isConnected) setTimeout(fit, 60); });
  if (root.ResizeObserver) new root.ResizeObserver(fit).observe(frame);
  draw();
}
function slidesPage(code, title) {
  const slides = splitSlides(code);
  return page(title, slides.map((s, i) => '<section' + (i === 0 && /^#\s/.test(s) ? ' class="title"' : '') + '>' + richText(s) + '<small>' + (i + 1) + ' / ' + slides.length + '</small></section>').join(''),
    'body{background:#15151a;margin:0}section{box-sizing:border-box;width:min(100vw,177.78vh);height:min(56.25vw,100vh);margin:0 auto;padding:6% 8%;background:#fff;color:#1c1c22;font-size:min(2.6vw,4.6vh);line-height:1.45;display:none;position:relative;overflow:hidden}' +
    'section.on{display:block}section.title{display:none;text-align:center;padding-top:16%}section.title.on{display:block}h2{font-size:1.9em;margin:0 0 .5em}h3{font-size:1.4em;margin:0 0 .5em}h4,h5{font-size:1.1em}p,ul,ol{margin:0 0 .7em}li{margin:.2em 0}' +
    'pre{background:#f3f3f7;padding:.6em .8em;border-radius:8px;font-size:.7em;overflow:hidden}.nv-code-head,button{display:none}table{border-collapse:collapse;font-size:.8em}td,th{border:1px solid #d9d9e0;padding:.3em .6em}' +
    'section small{position:absolute;right:3%;bottom:3%;font-size:.5em;color:#8a8a96}@media print{@page{size:landscape;margin:0}body{background:#fff}section,section.title{display:block!important;page-break-after:always;width:100vw;height:100vh}}',
    '<script>(() => { const all = [...document.querySelectorAll("section")]; let at = 0; const show = () => all.forEach((s, i) => s.classList.toggle("on", i === at)); ' +
    'const go = by => { at = Math.min(all.length - 1, Math.max(0, at + by)); show(); }; addEventListener("keydown", e => { if (["ArrowRight", "PageDown", " ", "Enter"].includes(e.key)) go(1); else if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) go(-1); }); ' +
    'addEventListener("click", e => go(e.clientX < innerWidth / 3 ? -1 : 1)); show(); })();</' + 'script>');
}

/* ================= Whiteboard: drawn by hand ================= */
const BOARD_W = 1600, BOARD_H = 1000, INKS = ['#1f1f24', '#e5484d', '#f0a43c', '#2fa46a', '#3b82f6', '#8b5cf6'], NOTES = ['#fde68a', '#bbf7d0', '#bfdbfe', '#fbcfe8'];
const blankBoard = () => JSON.stringify({ v: 1, w: BOARD_W, h: BOARD_H, items: [] });
function readBoard(code) {
  let data; try { data = JSON.parse(String(code)); } catch { data = null; }
  const items = [], colour = (v, d) => (typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v) ? v : d), n = (v, low, high, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? clamp(v, low, high) : d);
  const words = v => (typeof v === 'string' ? v : '').slice(0, 400);
  for (const it of (data && Array.isArray(data.items) ? data.items : []).slice(0, 4000)) {
    if (!it || typeof it !== 'object') continue;
    if (it.t === 'pen' && Array.isArray(it.p) && it.p.length >= 2) items.push({ t: 'pen', c: colour(it.c, INKS[0]), s: n(it.s, 1, 40, 4), p: it.p.slice(0, 8000).map((v, i) => n(v, -200, (i % 2 ? BOARD_H : BOARD_W) + 200)) });
    else if (['line', 'arrow', 'rect', 'ellipse'].includes(it.t)) items.push({ t: it.t, c: colour(it.c, INKS[0]), s: n(it.s, 1, 40, 4), x1: n(it.x1, -200, BOARD_W + 200), y1: n(it.y1, -200, BOARD_H + 200), x2: n(it.x2, -200, BOARD_W + 200), y2: n(it.y2, -200, BOARD_H + 200) });
    else if (it.t === 'text' && words(it.text)) items.push({ t: 'text', c: colour(it.c, INKS[0]), z: n(it.z, 10, 120, 28), x: n(it.x, -200, BOARD_W + 200), y: n(it.y, -200, BOARD_H + 200), text: words(it.text) });
    else if (it.t === 'note') items.push({ t: 'note', c: colour(it.c, NOTES[0]), x: n(it.x, -200, BOARD_W + 200), y: n(it.y, -200, BOARD_H + 200), w: n(it.w, 80, 600, 220), h: n(it.h, 60, 600, 160), text: words(it.text) });
  }
  return { v: 1, w: BOARD_W, h: BOARD_H, items };
}
function wrap(text, most) { const lines = []; for (const para of String(text).split('\n')) { let line = ''; for (const word of para.split(/\s+/)) { if ((line + ' ' + word).trim().length > most && line) { lines.push(line); line = word; } else line = (line + ' ' + word).trim(); } lines.push(line); } return lines.slice(0, 12); }
function boardItem(it, i) {
  const g = svgNode('g', { 'data-i': i });
  if (it.t === 'pen') { let d = ''; for (let k = 0; k + 1 < it.p.length; k += 2) d += (k ? 'L' : 'M') + it.p[k].toFixed(1) + ' ' + it.p[k + 1].toFixed(1); if (it.p.length === 2) d += 'l0.1 0'; g.append(svgNode('path', { d, fill: 'none', stroke: it.c, 'stroke-width': it.s, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })); }
  else if (it.t === 'line' || it.t === 'arrow') {
    g.append(svgNode('line', { x1: it.x1, y1: it.y1, x2: it.x2, y2: it.y2, stroke: it.c, 'stroke-width': it.s, 'stroke-linecap': 'round' }));
    if (it.t === 'arrow') { const a = Math.atan2(it.y2 - it.y1, it.x2 - it.x1), h = 10 + it.s * 2.5, pt = k => (it.x2 - h * Math.cos(a + k)).toFixed(1) + ' ' + (it.y2 - h * Math.sin(a + k)).toFixed(1); g.append(svgNode('path', { d: `M${pt(0.42)}L${it.x2} ${it.y2}L${pt(-0.42)}`, fill: 'none', stroke: it.c, 'stroke-width': it.s, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })); }
  }
  else if (it.t === 'rect') g.append(svgNode('rect', { x: Math.min(it.x1, it.x2), y: Math.min(it.y1, it.y2), width: Math.abs(it.x2 - it.x1), height: Math.abs(it.y2 - it.y1), rx: 6, fill: 'none', stroke: it.c, 'stroke-width': it.s }));
  else if (it.t === 'ellipse') g.append(svgNode('ellipse', { cx: (it.x1 + it.x2) / 2, cy: (it.y1 + it.y2) / 2, rx: Math.abs(it.x2 - it.x1) / 2, ry: Math.abs(it.y2 - it.y1) / 2, fill: 'none', stroke: it.c, 'stroke-width': it.s }));
  else if (it.t === 'text') { const t = svgNode('text', { x: it.x, y: it.y, 'font-size': it.z, fill: it.c, 'font-family': 'system-ui, Segoe UI, sans-serif' }); wrap(it.text, 60).forEach((line, k) => t.append(svgNode('tspan', { x: it.x, dy: k ? it.z * 1.25 : 0 }, line))); g.append(t); }
  else if (it.t === 'note') {
    g.append(svgNode('rect', { x: it.x, y: it.y, width: it.w, height: it.h, rx: 8, fill: it.c, stroke: '#00000022' }));
    const t = svgNode('text', { x: it.x + 14, y: it.y + 30, 'font-size': 20, fill: '#1f1f24', 'font-family': 'system-ui, Segoe UI, sans-serif' });
    wrap(it.text, Math.max(6, Math.floor((it.w - 28) / 10.5))).slice(0, Math.max(1, Math.floor((it.h - 20) / 26))).forEach((line, k) => t.append(svgNode('tspan', { x: it.x + 14, dy: k ? 26 : 0 }, line))); g.append(t);
  }
  return g;
}
function boardSvg(board) {
  const svg = svgNode('svg', { xmlns: SVG, viewBox: '0 0 ' + board.w + ' ' + board.h, width: board.w, height: board.h });
  svg.append(svgNode('rect', { x: 0, y: 0, width: board.w, height: board.h, fill: '#fbfaf7' }));
  board.items.forEach((it, i) => svg.append(boardItem(it, i)));
  return svg;
}
const boardPicture = code => svgText(boardSvg(readBoard(code)));
const TOOLS = [['select', 'cursor', 'Move things'], ['pen', 'edit', 'Draw'], ['line', 'slash', 'A straight line'], ['arrow', 'arrow', 'An arrow'], ['rect', 'square', 'A box'], ['ellipse', 'circle', 'A circle'], ['text', 'type', 'Words'], ['note', 'note', 'A sticky note'], ['erase', 'eraser', 'Rub something out']];
function renderBoard(host, ctx) {
  let board = readBoard(ctx.code), tool = 'pen', ink = INKS[0], thick = 4, drawing = null, picked = -1, moved = null;
  const can = typeof ctx.save === 'function', undo = [], redo = [];
  const bar = node('div', 'nv-board-bar'), wrapBox = node('div', 'nv-board-wrap');
  const toolButtons = TOOLS.map(([id, glyph, tip]) => { const b = node('button', 'nv-icon'); b.type = 'button'; b.innerHTML = icon(glyph); b.dataset.tool = id; b.dataset.tip = tip; b.setAttribute('aria-label', tip); return b; });
  const inks = INKS.map(c => { const b = node('button', 'nv-ink'); b.type = 'button'; b.style.background = c; b.dataset.ink = c; b.setAttribute('aria-label', 'Colour ' + c); return b; });
  const sizes = [[2, 'Thin'], [4, 'Medium'], [9, 'Thick']].map(([s, label]) => { const b = node('button', 'nv-thick'); b.type = 'button'; b.dataset.thick = s; b.dataset.tip = label; b.setAttribute('aria-label', label + ' line'); const dot = node('i'); dot.style.cssText = 'width:' + (s + 3) + 'px;height:' + (s + 3) + 'px'; b.append(dot); return b; });
  const undoB = node('button', 'plain', 'Undo'), redoB = node('button', 'plain', 'Redo'), clearB = node('button', 'plain', 'Clear');
  if (can) bar.append(...toolButtons, node('span', 'nv-board-gap'), ...inks, node('span', 'nv-board-gap'), ...sizes, node('span', 'nv-board-gap'), undoB, redoB, clearB);
  host.append(bar, wrapBox);
  if (!can) { bar.remove(); if (ctx.note) host.append(node('p', 'nv-kind-note', ctx.note)); }
  let svg = null;
  function draw() {
    svg = boardSvg(board); svg.removeAttribute('width'); svg.removeAttribute('height'); svg.setAttribute('class', 'nv-board' + (can ? ' tool-' + tool : ''));
    if (picked >= 0 && svg.querySelector('[data-i="' + picked + '"]')) svg.querySelector('[data-i="' + picked + '"]').setAttribute('class', 'picked');
    wrapBox.replaceChildren(svg);
    toolButtons.forEach(b => b.classList.toggle('on', b.dataset.tool === tool)); inks.forEach(b => b.classList.toggle('on', b.dataset.ink === ink)); sizes.forEach(b => b.classList.toggle('on', Number(b.dataset.thick) === thick));
    undoB.disabled = !undo.length; redoB.disabled = !redo.length;
  }
  const keep = () => { undo.push(JSON.stringify(board.items)); if (undo.length > 80) undo.shift(); redo.length = 0; };
  const changed = () => { draw(); ctx.save(JSON.stringify(board)); };
  const point = e => { const m = svg.getScreenCTM(); if (!m) return [0, 0]; const p = new root.DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse()); return [Math.round(p.x * 10) / 10, Math.round(p.y * 10) / 10]; };
  const hit = e => { const g = e.target.closest?.('[data-i]'); return g ? Number(g.getAttribute('data-i')) : -1; };
  function shift(it, dx, dy) { if (it.t === 'pen') it.p = it.p.map((v, i) => v + (i % 2 ? dy : dx)); else if ('x1' in it) { it.x1 += dx; it.x2 += dx; it.y1 += dy; it.y2 += dy; } else { it.x += dx; it.y += dy; } }
  async function words(title, before = '') { return root.Nova?.ask ? root.Nova.ask({ title, label: 'What should it say?', value: before, ok: 'Put it there' }) : null; }
  if (can) {
    bar.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.tool) { tool = b.dataset.tool; picked = -1; draw(); }
      else if (b.dataset.ink) { ink = b.dataset.ink; if (picked >= 0 && board.items[picked].t !== 'note') { keep(); board.items[picked].c = ink; changed(); } else draw(); }
      else if (b.dataset.thick) { thick = Number(b.dataset.thick); draw(); }
      else if (b === undoB && undo.length) { redo.push(JSON.stringify(board.items)); board.items = JSON.parse(undo.pop()); picked = -1; changed(); }
      else if (b === redoB && redo.length) { undo.push(JSON.stringify(board.items)); board.items = JSON.parse(redo.pop()); picked = -1; changed(); }
      else if (b === clearB && board.items.length) { keep(); board.items = []; picked = -1; changed(); }
    });
    wrapBox.addEventListener('pointerdown', async e => {
      if (e.button !== 0 || !svg) return; const [x, y] = point(e), on = hit(e);
      if (tool === 'erase') { if (on >= 0) { keep(); board.items.splice(on, 1); picked = -1; changed(); } return; }
      if (tool === 'select') { picked = on; moved = on >= 0 ? { x, y, kept: false } : null; draw(); if (moved) wrapBox.setPointerCapture?.(e.pointerId); return; }
      if (tool === 'text' || tool === 'note') {
        const said = await words(tool === 'text' ? 'Words on the board' : 'A sticky note'); if (!said) return;
        keep(); board.items.push(tool === 'text' ? { t: 'text', c: ink, z: 28, x, y, text: said } : { t: 'note', c: NOTES[board.items.filter(i => i.t === 'note').length % NOTES.length], x: x - 110, y: y - 80, w: 220, h: 160, text: said }); changed(); return;
      }
      keep(); drawing = tool === 'pen' ? { t: 'pen', c: ink, s: thick, p: [x, y] } : { t: tool, c: ink, s: thick, x1: x, y1: y, x2: x, y2: y };
      board.items.push(drawing); wrapBox.setPointerCapture?.(e.pointerId); draw();
    });
    wrapBox.addEventListener('pointermove', e => {
      if (!svg) return;
      if (drawing) { const [x, y] = point(e); if (drawing.t === 'pen') { const p = drawing.p; if (Math.hypot(x - p[p.length - 2], y - p[p.length - 1]) > 2 && p.length < 8000) p.push(x, y); } else { drawing.x2 = x; drawing.y2 = y; } svg.replaceChild(boardItem(drawing, board.items.length - 1), svg.lastChild); }
      else if (moved && picked >= 0) { const [x, y] = point(e); if (!moved.kept) { keep(); moved.kept = true; } shift(board.items[picked], x - moved.x, y - moved.y); moved.x = x; moved.y = y; const old = svg.querySelector('[data-i="' + picked + '"]'), fresh = boardItem(board.items[picked], picked); fresh.setAttribute('class', 'picked'); old.replaceWith(fresh); }
    });
    const end = () => {
      if (drawing) { const d = drawing; drawing = null; if (d.t !== 'pen' && Math.hypot(d.x2 - d.x1, d.y2 - d.y1) < 4) { board.items.pop(); undo.pop(); draw(); } else changed(); }
      else if (moved) { const was = moved.kept; moved = null; if (was) changed(); }
    };
    wrapBox.addEventListener('pointerup', end); wrapBox.addEventListener('pointercancel', end);
    wrapBox.addEventListener('dblclick', async e => {
      const on = hit(e); if (on < 0 || !['text', 'note'].includes(board.items[on].t)) return;
      const said = await words('Change the words', board.items[on].text); if (said) { keep(); board.items[on].text = said; changed(); }
    });
    wrapBox.tabIndex = 0;
    wrapBox.addEventListener('keydown', e => { if ((e.key === 'Delete' || e.key === 'Backspace') && picked >= 0) { e.preventDefault(); keep(); board.items.splice(picked, 1); picked = -1; changed(); } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); (e.shiftKey ? redoB : undoB).click(); } });
  }
  draw();
}

/* ================= A page of its own (to open in a window, pin, print or save) ================= */
function page(title, inner, css = '', script = '') {
  return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(title || 'Made with JARVIS') + '</title>' +
    '<style>body{margin:24px;font-family:system-ui,Segoe UI,sans-serif;color:#1c1c22;background:#fff;line-height:1.6}' + css + '</style></head><body>' + inner + script + '</body></html>';
}
const DOC_CSS = 'body{max-width:46em;margin:40px auto;padding:0 24px;font-size:16px}h2{font-size:1.6em}h3{font-size:1.25em}pre{background:#f3f3f7;padding:12px 14px;border-radius:8px;overflow:auto}code{font-family:ui-monospace,Consolas,monospace;font-size:.92em}' +
  '.nv-code-head,button{display:none}table{border-collapse:collapse}td,th{border:1px solid #d9d9e0;padding:6px 10px}blockquote{margin:0;padding-left:14px;border-left:3px solid #d9d9e0;color:#555}a{color:#4b46d6}';
const KINDS = {
  slides: { name: 'Slides', show: 'Show slides', render: renderSlides, page: slidesPage, blank: title => '# ' + (title || 'A new deck') + '\n\nWhat this is about, in a line.\n\n---\n\n## The first point\n\n- one thing\n- another thing\n\n---\n\n## What happens next\n\nSay what you want people to do.' },
  sheet: { name: 'Sheet', show: 'Show sheet', render: renderSheet, page: sheetPage, blank: () => 'Item,Amount\nFirst,10\nSecond,20\nTotal,=SUM(B2:B3)' },
  data: { name: 'Chart', show: 'Show chart', render: renderChart, picture: chartPicture, page: (code, title) => page(title, chartPicture(code) || '<p>' + esc(readChart(code).problem) + '</p>', 'svg{max-width:100%;height:auto}'),
          blank: title => JSON.stringify({ type: 'bar', title: title || 'A new chart', x: ['One', 'Two', 'Three'], series: [{ name: 'Amount', values: [3, 5, 4] }] }, null, 2) },
  whiteboard: { name: 'Whiteboard', show: 'Show board', render: renderBoard, picture: boardPicture, page: (code, title) => page(title, boardPicture(code), 'body{margin:0;background:#fbfaf7}svg{display:block;width:100vw;height:auto;max-height:100vh}'), blank: blankBoard },
};
const documentPage = (code, title) => page(title, richText(code), DOC_CSS);
root.NovaKinds = { KINDS, parseCsv, toCsv, exportCsv, compute, shownValue, colName, readChart, chartSvg, ticks, splitSlides, readBoard, boardSvg, page, documentPage, esc };
})(typeof window !== 'undefined' ? window : globalThis);
