// A small, safe Markdown reader for JARVIS's replies on the phone. It never makes HTML from text: parse() returns a
// plain tree, and render() builds elements one by one with the page's own h(). Only p, br, strong, em, code, pre, ol,
// ul, li and a can come out, and a link only when it is https. Anything else (images, tables, HTML, unclosed markers)
// stays as the literal text it was. The text that was signed and stored is never changed: this runs at display time.

export const TAGS = new Set(['p', 'br', 'strong', 'em', 'code', 'pre', 'ol', 'ul', 'li', 'a']);
const MOST = 20000;                    // longer replies are shown as plain text
const ESCAPABLE = '\\`*_[]()#+-.!>|~';

// ------------------------------------------------------------------ inline: **bold**, *italic*, `code`, [text](https://…)

function safeLink(target) {
  try {
    const url = new URL(target);
    return url.protocol === 'https:' && !url.username && !url.password ? url : null;
  } catch { return null; }
}

// Where a closing marker for an opener at `from` is: not right after a space, and with something inside.
function closing(text, marker, from) {
  for (let at = text.indexOf(marker, from); at !== -1; at = text.indexOf(marker, at + 1)) {
    if (at <= from || /\s/.test(text[at - 1])) continue;
    if (marker === '*' && (text[at + 1] === '*' || text[at - 1] === '*')) continue;      // part of a **
    return at;
  }
  return -1;
}

export function inline(text) {
  const out = [];
  let plain = '';
  const flush = () => { if (plain) { out.push(plain); plain = ''; } };
  for (let i = 0; i < text.length;) {
    const c = text[i];
    if (c === '\\' && ESCAPABLE.includes(text[i + 1] || '\0')) { plain += text[i + 1]; i += 2; continue; }
    if (c === '`') {
      let run = 1;
      while (text[i + run] === '`') run++;
      const end = text.indexOf('`'.repeat(run), i + run);
      if (end > i + run) { flush(); out.push({ t: 'code', kids: [text.slice(i + run, end)] }); i = end + run; continue; }
      plain += '`'.repeat(run); i += run; continue;
    }
    if (c === '*' && text[i + 1] === '*' && text[i + 2] && !/\s/.test(text[i + 2])) {
      const end = closing(text, '**', i + 2);
      if (end !== -1) { flush(); out.push({ t: 'strong', kids: inline(text.slice(i + 2, end)) }); i = end + 2; continue; }
    }
    if (c === '*' && text[i + 1] !== '*' && text[i + 1] && !/\s/.test(text[i + 1])) {
      const end = closing(text, '*', i + 1);
      if (end !== -1) { flush(); out.push({ t: 'em', kids: inline(text.slice(i + 1, end)) }); i = end + 1; continue; }
    }
    if (c === '[' && text[i - 1] !== '!') {
      const close = text.indexOf('](', i + 1);
      const end = close === -1 ? -1 : text.indexOf(')', close + 2);
      const label = close === -1 ? '' : text.slice(i + 1, close);
      const url = end === -1 || /[\s<>"]/.test(text.slice(close + 2, end)) ? null : safeLink(text.slice(close + 2, end));
      if (url && label.trim() && !label.includes('[')) {
        flush();
        const kids = label === url.href || label === text.slice(close + 2, end) ? [url.host] : [...inline(label), ' (' + url.host + ')'];
        out.push({ t: 'a', href: url.href, kids });
        i = end + 1; continue;
      }
    }
    plain += c; i++;
  }
  flush();
  return out;
}

// ------------------------------------------------------------------ blocks: paragraphs, lists, fenced code, # headings

const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
const NUMBER = /^\s{0,3}(\d{1,9})[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/;
const FENCE = /^\s{0,3}(```+|~~~+)/;

const indent = row => /^\s*/.exec(row)[0].length;
const lines = (texts) => texts.flatMap((t, n) => n ? [{ t: 'br' }, ...inline(t)] : inline(t));

export function parse(text) {
  text = String(text ?? '').replace(/\r\n?/g, '\n');
  if (text.length > MOST) return [{ t: 'p', kids: [text] }];
  const rows = text.split('\n'), out = [];
  let para = [];
  const endPara = () => { if (para.length) { out.push({ t: 'p', kids: lines(para) }); para = []; } };
  for (let i = 0; i < rows.length;) {
    const row = rows[i];
    const fence = FENCE.exec(row);
    if (fence) {
      const mark = fence[1];
      const end = rows.findIndex((r, n) => n > i && r.trim().startsWith(mark[0].repeat(mark.length)) && r.trim().replace(/[`~]/g, '') === '');
      if (end !== -1) {
        endPara();
        out.push({ t: 'pre', kids: [{ t: 'code', kids: [rows.slice(i + 1, end).join('\n')] }] });
        i = end + 1; continue;
      }
    }
    if (!row.trim()) { endPara(); i++; continue; }
    const heading = HEADING.exec(row);
    if (heading && heading[1]) { endPara(); out.push({ t: 'p', kids: [{ t: 'strong', kids: inline(heading[1]) }] }); i++; continue; }
    const kind = indent(row) > 3 ? null : BULLET.test(row) ? 'ul' : NUMBER.test(row) ? 'ol' : null;
    if (kind) {
      endPara();
      const pattern = kind === 'ul' ? BULLET : NUMBER, items = [];
      const first = kind === 'ol' ? Number(NUMBER.exec(row)[1]) : 1;
      const base = indent(row);
      while (i < rows.length && pattern.test(rows[i]) && indent(rows[i]) <= base + 1) {
        const got = pattern.exec(rows[i]);
        const kids = inline(kind === 'ul' ? got[1] : got[2]);
        i++;
        // One level only: an indented line, nested item or not, stays inside this item on a line of its own, so
        // the outer list keeps its count and its numbers.
        while (i < rows.length && rows[i].trim() && indent(rows[i]) > base + 1) {
          const line = rows[i++].trim(), bullet = BULLET.exec(line), number = NUMBER.exec(line);
          kids.push({ t: 'br' }, ...(bullet ? ['\u2022 ', ...inline(bullet[1])] : number ? [number[1] + '. ', ...inline(number[2])] : inline(line)));
        }
        items.push({ t: 'li', kids });
      }
      out.push(kind === 'ol' && first !== 1 ? { t: 'ol', start: first, kids: items } : { t: kind, kids: items });
      continue;
    }
    para.push(row);
    i++;
  }
  endPara();
  return out;
}

// ------------------------------------------------------------------ to elements, with the page's h(tag, attrs, ...kids)

export function render(nodes, h) {
  return nodes.map(node => {
    if (typeof node === 'string') return node;
    if (!TAGS.has(node.t)) return '';
    const attrs = {};
    if (node.t === 'a') {
      const url = safeLink(node.href);
      if (!url) return render(node.kids, h);
      Object.assign(attrs, { href: url.href, target: '_blank', rel: 'noopener noreferrer' });
    }
    if (node.t === 'ol' && Number.isInteger(node.start)) attrs.start = String(node.start);
    return h(node.t, attrs, ...render(node.kids || [], h));
  });
}

export const toNodes = (text, h) => render(parse(text), h);
