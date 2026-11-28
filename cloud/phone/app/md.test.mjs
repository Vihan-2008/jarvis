// The phone app's Markdown reader (md.js): what it shows, and that text can never become markup or a script.
// Run with: node --test cloud/phone/app/md.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parse, render, TAGS } from './md.js';

// A stand-in for the page's h(): records what would be made, so the test needs no browser.
const h = (tag, attrs = {}, ...kids) => ({ tag, attrs, kids: kids.flat() });
const made = text => render(parse(text), h);
const tags = (nodes, seen = new Set()) => {
  for (const n of nodes.flat(Infinity)) if (n && typeof n === 'object') { seen.add(n.tag); tags(n.kids, seen); }
  return seen;
};
const textOf = nodes => nodes.flat(Infinity).map(n => typeof n === 'string' ? n : n.tag === 'br' ? '\n' : textOf(n.kids)).join('');
const links = (nodes, out = []) => {
  for (const n of nodes.flat(Infinity)) if (n && typeof n === 'object') { if (n.tag === 'a') out.push(n.attrs); links(n.kids, out); }
  return out;
};

test('the common replies come out as paragraphs, lists, bold, italic and code', () => {
  const got = made('# Plan\n\nDo **this** and *that*, then run `npm test`.\nNext line.\n\n1. One\n2. Two\n\n- a\n- b\n\n```\nconst x = 1 < 2;\n```');
  assert.deepEqual(got.map(n => n.tag), ['p', 'p', 'ol', 'ul', 'pre']);
  assert.deepEqual(got[0].kids[0].tag, 'strong');
  assert.equal(textOf([got[0]]), 'Plan');
  assert.deepEqual([...tags([got[1]])].sort(), ['br', 'code', 'em', 'p', 'strong']);
  assert.equal(textOf([got[1]]), 'Do this and that, then run npm test.\nNext line.');
  assert.equal(got[2].kids.length, 2);
  assert.equal(textOf([got[4]]), 'const x = 1 < 2;');
});

test('an ordered list keeps its first number', () => {
  const [ol] = made('3. three\n4. four');
  assert.equal(ol.attrs.start, '3');
});

test('a nested item stays inside its parent item, so the steps keep their numbers', () => {
  const [ol, after] = made('1. First\n2. Second\n   - nested bullet\n   - another\n3. Third\n\nDone.');
  assert.equal(ol.tag, 'ol');
  assert.deepEqual(ol.kids.map(li => textOf([li])), ['First', 'Second\n\u2022 nested bullet\n\u2022 another', 'Third']);
  assert.equal(textOf([after]), 'Done.');
  const [ul] = made('- a\n  1. one\n  2. two\n- b\n    more of b');
  assert.equal(ul.tag, 'ul');
  assert.deepEqual(ul.kids.map(li => textOf([li])), ['a\n1. one\n2. two', 'b\nmore of b']);
  assert.deepEqual(made('    - only indented').map(n => n.tag), ['p'], 'an indented line alone is a paragraph');
});

test('only https links, shown with their host, opening in a new tab without the opener', () => {
  const got = made('See [the docs](https://supabase.com/docs) and [x](javascript:alert(1)) and [y](http://plain.example) and <https://a.example>');
  const [a] = links(got);
  assert.deepEqual(links(got).length, 1);
  assert.deepEqual(a, { href: 'https://supabase.com/docs', target: '_blank', rel: 'noopener noreferrer' });
  assert.equal(textOf(got), 'See the docs (supabase.com) and [x](javascript:alert(1)) and [y](http://plain.example) and <https://a.example>');
  assert.equal(links(made('[me](https://user:pw@evil.example/)')).length, 0, 'no credentials in a link');
  assert.equal(links(made('[](https://a.example)')).length, 0, 'no empty label');
});

test('markup, images, tables and unclosed markers stay as the text they were', () => {
  const nasty = [
    '<img src=x onerror=alert(1)>', '<script>alert(1)</script>', '![pic](https://a.example/p.png)',
    '| a | b |\n|---|---|\n| 1 | 2 |', '**a', '*a', '`a', '```\nnever closed', '[x](javascript:alert(1))',
    '<a href="javascript:alert(1)">x</a>', '[x](https://a.example/"onmouseover="alert(1))', '** not bold**', '* not a list*',
  ];
  for (const text of nasty) {
    const got = made(text);
    assert.equal(textOf(got).replace(/\n/g, ''), text.replace(/\n/g, '').replace(/^\* /, ''), text);
    for (const tag of tags(got)) assert.ok(['p', 'br', 'ul', 'li'].includes(tag), text + ' made ' + tag);
  }
});

test('nothing outside the allowed set can be made, whatever the text', () => {
  const pieces = ['**', '*', '`', '```', '[', '](', ')', 'https://a.example', 'javascript:', '<b>', '# ', '- ', '1. ', '\n', '\n\n', 'x', ' ', '\\*', '!', '|'];
  let seed = 7;
  const rand = n => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  for (let round = 0; round < 3000; round++) {
    const text = Array.from({ length: 1 + rand(30) }, () => pieces[rand(pieces.length)]).join('');
    const got = made(text);
    for (const tag of tags(got)) assert.ok(TAGS.has(tag), JSON.stringify(text) + ' made ' + tag);
    for (const a of links(got)) assert.match(a.href, /^https:\/\//, JSON.stringify(text));
  }
});

test('escapes, long replies and empty text', () => {
  assert.equal(textOf(made('2 \\* 3 = 6, not \\*bold\\*')), '2 * 3 = 6, not *bold*');
  const long = '**x** '.repeat(5000);
  assert.deepEqual(made(long), [{ tag: 'p', attrs: {}, kids: [long] }]);
  assert.deepEqual(made(''), []);
  assert.deepEqual(made(null), []);
});

test('app.js never turns text into HTML', async () => {
  const source = await readFile(new URL('./app.js', import.meta.url), 'utf8');
  for (const sink of ['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'DOMParser', 'createContextualFragment'])
    assert.ok(!source.includes(sink), 'app.js uses ' + sink);
  assert.match(source, /toNodes\(m\.text, h\)/, 'assistant replies go through md.js');
});
