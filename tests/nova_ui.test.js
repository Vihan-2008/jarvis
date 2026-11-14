// Reply formatting contracts. Pure functions only: no browser, screen or provider access.
const { test } = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../jcc/static/nova-rich.js'), 'utf8');
function load() {
  const context = { NovaIcon: () => '', NovaNoteLink: note => 'obsidian://open?file=' + encodeURIComponent(note) };
  context.globalThis = context; vm.createContext(context); vm.runInContext(code, context);
  return context.NovaRich;
}
const { rich } = load();

test('model text can never inject markup or scripts', () => {
  const html = rich('<img src=x onerror=alert(1)> <script>alert(2)</script>\n\n[x](javascript:alert(3)) [y](https://ok.example/a"onmouseover="alert(4))');
  assert.ok(!/<img|<script/i.test(html), html);
  assert.ok(!html.includes('href="javascript'), html);
  assert.ok(!/"onmouseover=/.test(html), html);
  assert.match(html, /&lt;script&gt;/);
});

test('code blocks keep their text exactly and never run', () => {
  const html = rich('```html\n<button onclick="x()">Hi</button>\n```');
  assert.match(html, /data-lang="html"/);
  assert.match(html, /&lt;button onclick=&quot;x\(\)&quot;&gt;Hi&lt;\/button&gt;/);
  assert.match(html, /data-nv-preview/);
  assert.ok(!/<button onclick/.test(html));
  const python = rich('```python\nprint(1)\n```');
  assert.ok(!/data-nv-preview/.test(python), 'only pages get a Preview button');
  assert.match(python, /data-nv-copy/);
});

test('an unfinished code block renders while the reply is still streaming', () => {
  const html = rich('Here:\n```js\nconst a = 1;');
  assert.match(html, /<pre><code>const a = 1;<\/code><\/pre>/);
  assert.ok(!/data-nv-copy/.test(html), 'no actions until the block is complete');
});

test('headings, lists, tables, quotes and inline styles', () => {
  const html = rich('# Title\n\nSome **bold**, *soft* and `code`.\n\n- one\n- two\n  - nested\n\n1. first\n2. second\n\n> quoted\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n---\n');
  assert.match(html, /<h2>Title<\/h2>/);
  assert.match(html, /<strong>bold<\/strong>/);
  assert.match(html, /<em>soft<\/em>/);
  assert.match(html, /<code>code<\/code>/);
  assert.match(html, /<ul><li>one<\/li><li>two<ul><li>nested<\/li><\/ul><\/li><\/ul>/);
  assert.match(html, /<ol><li>first<\/li><li>second<\/li><\/ol>/);
  assert.match(html, /<blockquote>quoted<\/blockquote>/);
  assert.match(html, /<table><thead><tr><th>A<\/th><th>B<\/th><\/tr><\/thead><tbody><tr><td>1<\/td><td>2<\/td><\/tr><\/tbody><\/table>/);
  assert.match(html, /<hr>/);
});

test('links open safely and note links point at Obsidian', () => {
  const html = rich('See [the docs](https://example.com/a?b=1&c=2) and [[Projects/demo/Memory|project memory]].');
  assert.match(html, /<a href="https:\/\/example.com\/a\?b=1&amp;c=2" target="_blank" rel="noreferrer">the docs<\/a>/);
  assert.match(html, /<a href="obsidian:\/\/open\?file=Projects%2Fdemo%2FMemory">project memory<\/a>/);
});

test('snake_case words and maths are not turned into italics', () => {
  const html = rich('Use my_file_name and 2 * 3 * 4 here.');
  assert.ok(!/<em>/.test(html), html);
});

test('empty and odd input never throws', () => {
  for (const value of ['', null, undefined, 42, '```', '|', '- ', '#', '\n\n\n']) assert.equal(typeof rich(value), 'string');
});

// ---- artifacts: something whole that a reply made is shown as a card that opens beside the chat
const PAGE = ['<!doctype html>', '<html><head><title>Rise & Shine Bakery</title></head>', '<body>', '<h1>Fresh bread</h1>', '<p>Every morning from 7.</p>', '<script>alert(1)</script>', '</body></html>'].join('\n');
const kindOf = html => (html.match(/class="nv-artifact" data-kind="(\w+)" data-name="([^"]*)"/) || []).slice(1);

test('a whole page becomes a card, with its code kept underneath and never run', () => {
  const html = rich('Here it is:\n\n```html\n' + PAGE + '\n```\n\nTell me what to change.');
  assert.deepEqual(kindOf(html), ['page', 'Rise &amp; Shine Bakery'], 'named after the page\'s own title');
  assert.match(html, /<button type="button" class="nv-art-card" data-nv-art[^>]*>.*<b>Rise &amp; Shine Bakery<\/b><small>Page · 7 lines<\/small>/);
  assert.match(html, /<details class="nv-art-code"><summary>Show its code here<\/summary><div class="nv-code" data-lang="html">/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/, 'the code is text');
  assert.ok(!/<script/i.test(html) && !/<h1>/.test(html), html);
  assert.match(html, /<p>Tell me what to change\.<\/p>/);
});

test('a snippet, ordinary code and an unfinished block stay as they are', () => {
  assert.ok(!/nv-artifact/.test(rich('```html\n<b>Hi</b>\n```')), 'too short to be a thing of its own');
  assert.ok(!/nv-artifact/.test(rich('```python\n' + Array(40).fill('print(1)').join('\n') + '\n```')), 'ordinary code is read where it is');
  assert.ok(!/nv-artifact/.test(rich('```html\n' + PAGE)), 'still being written');
  assert.ok(!/nv-artifact/.test(rich('```markdown\n# Short\n\ntext\n```')));
});

test('what an artifact is called: said beside it, or found in it', () => {
  assert.deepEqual(kindOf(rich('```html title="Opening hours"\n' + PAGE + '\n```')), ['page', 'Opening hours']);
  assert.deepEqual(kindOf(rich('```html index.html\n' + PAGE + '\n```')), ['page', 'index.html']);
  const labelled = rich('Done.\nFile: bakery.html\n```html\n' + PAGE + '\n```');
  assert.deepEqual(kindOf(labelled), ['page', 'bakery.html']);
  assert.ok(!/File:/.test(labelled) && /<p>Done\.<\/p>/.test(labelled), 'the line that named it is not shown as text as well');
  const apart = rich('Here you go.\n\n**File:** `bakery.html`\n\n```html\n' + PAGE + '\n```');
  assert.deepEqual(kindOf(apart), ['page', 'bakery.html'], 'also when it stands as a line of its own above the block');
  assert.ok(!/File:/.test(apart) && /<p>Here you go\.<\/p>/.test(apart), apart.slice(0, 200));
  assert.ok(/<p>File: a\.html<br>and more<\/p>/.test(rich('File: a.html\nand more\n\n```html\n' + PAGE + '\n```')), 'a longer paragraph is left as it is');
  assert.deepEqual(kindOf(rich('**File:** `chart.svg`\n```svg\n<svg viewBox="0 0 10 10">\n<circle r="1"/>\n<circle r="2"/>\n<circle r="3"/>\n<circle r="4"/>\n</svg>\n```')), ['picture', 'chart.svg']);
  assert.deepEqual(kindOf(rich('```svg\n<svg viewBox="0 0 10 10">\n<circle r="1"/>\n<circle r="2"/>\n<circle r="3"/>\n<circle r="4"/>\n</svg>\n```')), ['picture', 'Picture'], 'nothing to go by: what it is');
  assert.deepEqual(kindOf(rich('```jsx\nimport { useState } from "react";\nexport default function Counter() {\n  const [n, setN] = useState(0);\n  const more = () => setN(n + 1);\n  return <button onClick={more}>{n}</button>;\n}\n```')), ['app', 'Counter']);
  assert.deepEqual(kindOf(rich('```mermaid\ngraph TD\nA-->B\nB-->C\nC-->D\nD-->E\nE-->A\n```')), ['diagram', 'Diagram']);
  assert.deepEqual(kindOf(rich('```markdown\n# Trip plan\n\n' + Array(9).fill('A line of the plan.').join('\n') + '\n```')), ['document', 'Trip plan']);
  assert.ok(/<p>File: notes\.txt<\/p>/.test(rich('File: notes.txt\n```python\nprint(1)\n```')), 'a name above ordinary code is left alone');
});

test('a name can never carry markup into the page', () => {
  const html = rich('```html title="<img src=x onerror=alert(1)>"\n' + PAGE + '\n```');
  assert.ok(!/<img/i.test(html), html);
  const second = rich('File: "><script>alert(1)</script>\n```html\n' + PAGE + '\n```');
  assert.ok(!/<script/i.test(second) && !/data-name="[^"]*"[^>]*>[^<]*<script/i.test(second), second);
  assert.match(second, /data-name="&quot;&gt;&lt;script&gt;alert\(1\)&lt;\/script&gt;"/);
});
