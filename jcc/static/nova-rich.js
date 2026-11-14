/* Reply formatting for JARVIS: turns the AI's Markdown into safe HTML.
   Everything is escaped first; only the tags written here can ever reach the page. */
(function (root) {
'use strict';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = name => root.NovaIcon ? root.NovaIcon(name) : '';
const obsidian = note => root.NovaNoteLink ? root.NovaNoteLink(note) : '#';
function inline(s) {
  const keep = []; const hold = html => '\u0001' + (keep.push(html) - 1) + '\u0001';
  s = s.replace(/`([^`\n]+)`/g, (_, c) => hold('<code>' + c + '</code>'));
  s = s.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, name, label) => { const raw = name.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>'); return hold('<a href="' + esc(obsidian(raw)) + '">' + (label || name) + '</a>'); });
  s = s.replace(/!\[([^\]]*)\]\(jarvis-image:([0-9a-f]{16})\)/g, (_, alt, id) => hold('<img class="nv-pic" data-jarvis-image="' + id + '" alt="' + (alt || 'Picture') + '">'));
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => hold('<a href="' + url + '" target="_blank" rel="noreferrer">' + label + '</a>'));
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/(^|[\s(])\*([^*\s][^*\n]*)\*(?=[\s).,!?;:]|$)/g, '$1<em>$2</em>').replace(/(^|[\s(])_([^_\s][^_\n]*)_(?=[\s).,!?;:]|$)/g, '$1<em>$2</em>').replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  return s.replace(/\u0001(\d+)\u0001/g, (_, i) => keep[Number(i)]);
}
const PREVIEWABLE = new Set(['html', 'svg', 'xml', 'htm']);
function codeBlock(lang, code, open) {
  const name = (lang || 'text').toLowerCase().replace(/[^\w+#.-]/g, '').slice(0, 20) || 'text';
  return '<div class="nv-code" data-lang="' + name + '"><div class="nv-code-head"><span>' + name + '</span>' +
    (PREVIEWABLE.has(name) && !open ? '<button type="button" data-nv-preview data-tip="See this page working, in the side panel">' + icon('eye') + 'Preview</button>' : '') +
    (open ? '' : '<button type="button" data-nv-open data-tip="Open in the side panel to read, copy or download">' + icon('code') + 'Open</button><button type="button" data-nv-editcopy data-tip="Edit your own copy of this text">' + icon('edit') + 'Edit</button><button type="button" data-nv-copy data-tip="Copy this to the clipboard">' + icon('copy') + 'Copy</button>') +
    '</div><button type="button" data-edit-copy hidden></button><pre><code>' + code + '</code></pre></div>';
}
/* An artifact: something whole that a reply made (a page, a picture, a diagram, a small app, a document). It is shown as
   a card that opens beside the chat, with its code tucked away underneath. Short snippets and ordinary code stay as they are.
   Its name comes from the code block itself (```html title="..."```), from a line "File: name" just before it, or from what
   it contains (a page's title, a document's first heading, a component's name). Later blocks with the same name are newer
   versions of the same thing. (Everything here works on text that has already been escaped.) */
const KINDS = { html: 'page', htm: 'page', svg: 'picture', mermaid: 'diagram', jsx: 'app', tsx: 'app', react: 'app', markdown: 'document', md: 'document',
  slides: 'slides', csv: 'sheet', sheet: 'sheet', chart: 'data' };
const KIND_NAMES = { page: 'Page', picture: 'Picture', diagram: 'Diagram', app: 'App', document: 'Document', slides: 'Slides', sheet: 'Sheet', data: 'Chart', whiteboard: 'Whiteboard' };
const KIND_ICONS = { page: 'globe', picture: 'cam', diagram: 'work', app: 'code', document: 'doc', slides: 'slides', sheet: 'grid', data: 'chart', whiteboard: 'board' };
// Lines: anything shorter is a snippet, not a thing (others: 6). A chart or slides are written under their own word,
// so even one line of them is the thing itself.
const SHORTEST = { document: 10, sheet: 3, data: 1, slides: 1 };
const WORDS = '((?:[^&\\n]|&amp;|&#39;|&quot;){2,80}?)';
function artifact(lang, info, code, given) {
  const kind = KINDS[lang], count = code.split('\n').length;
  if (!kind || count < (SHORTEST[kind] || 6)) return null;
  info = info.trim();
  const said = (info.match(/(?:title|name)=(?:&quot;|&#39;)(.{1,80}?)(?:&quot;|&#39;)/i) || [])[1] || (/^[\w .()-]{2,60}\.\w{1,5}$/.test(info) ? info : '') || given;
  const found = kind === 'document' || kind === 'slides' ? (code.match(/^#{1,3}\s+(.{2,80})$/m) || [])[1]
    : kind === 'app' ? (code.match(/(?:function|const|class)\s+([A-Z]\w{1,40})/) || [])[1]
    : kind === 'diagram' || kind === 'sheet' ? ''
    : kind === 'data' ? (code.match(new RegExp('&quot;title&quot;\\s*:\\s*&quot;' + WORDS + '&quot;')) || [])[1]
    : ((code.match(new RegExp('&lt;title&gt;' + WORDS + '&lt;/title&gt;', 'i')) || code.match(new RegExp('&lt;h1[^&]*&gt;' + WORDS + '&lt;/h1&gt;', 'i')) || [])[1] || '')
      .replace(/&amp;(amp|lt|gt|quot|#39|nbsp);/g, (all, e) => (e === 'nbsp' ? ' ' : '&' + e + ';'));     // (a title is written "Rise &amp; Shine" in a page's code)
  const name = String(said || found || KIND_NAMES[kind]).replace(/[*`]/g, '').trim().slice(0, 80) || KIND_NAMES[kind];
  return '<div class="nv-artifact" data-kind="' + kind + '" data-name="' + name + '"><button type="button" class="nv-art-card" data-nv-art data-tip="Open it beside the chat">' +
    icon(KIND_ICONS[kind]) + '<span class="nv-art-text"><b>' + name + '</b><small>' + KIND_NAMES[kind] + ' \u00b7 ' + count + (count === 1 ? ' line' : ' lines') + '</small></span><span class="nv-art-go">Open</span></button>' +
    '<details class="nv-art-code"><summary>Show its code here</summary>' + codeBlock(lang, code, false) + '</details></div>';
}
function rich(text) {
  const lines = esc(String(text ?? '')).split('\n'), out = []; let i = 0, para = [];
  const flush = () => { if (para.length) { out.push('<p>' + inline(para.join('<br>')) + '</p>'); para = []; } };
  while (i < lines.length) {
    const line = lines[i]; let m;
    if ((m = line.match(/^\s*```\s*([^\s`]*)[ \t]*(.*)$/))) {
      const code = []; i++; let closed = false;
      while (i < lines.length) { if (/^\s*```\s*$/.test(lines[i])) { closed = true; i++; break; } code.push(lines[i++]); }
      const lang = (m[1] || 'text').toLowerCase().replace(/[^\w+#.-]/g, '').slice(0, 20) || 'text';
      // "File: name" on the line just before the block (or as a short paragraph of its own just before it) names what
      // the block is. The line is then not shown as text as well: the card carries the name.
      const NAMED = /^\s*(?:\*\*)?(?:File|Artifact|Title)(?:\*\*)?:\s*(?:\*\*)?\s*`?([^`*]{2,80}?)`?(?:\*\*)?\s*$/i;
      const before = !para.length && out.length ? (out[out.length - 1].match(/^<p>((?:(?!<br>).)*)<\/p>$/) || [])[1] : null;
      const label = para.length ? para[para.length - 1].match(NAMED) : before ? before.replace(/<\/?(?:strong|code|em)>/g, '').match(NAMED) : null;
      const made = closed ? artifact(lang, m[2] || '', code.join('\n'), label ? label[1] : '') : null;
      if (made && label) { if (para.length) para.pop(); else out.pop(); }
      flush(); out.push(made || codeBlock(m[1], code.join('\n'), !closed)); continue;
    }
    if (/^\s*$/.test(line)) { flush(); i++; continue; }
    if ((m = line.match(/^(#{1,4})\s+(.+)$/))) { flush(); const level = Math.min(4, m[1].length + 1); out.push('<h' + level + '>' + inline(m[2]) + '</h' + level + '>'); i++; continue; }
    if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) { flush(); out.push('<hr>'); i++; continue; }
    if (/^\s*&gt;\s?/.test(line)) { flush(); const q = []; while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) q.push(lines[i++].replace(/^\s*&gt;\s?/, '')); out.push('<blockquote>' + inline(q.join('<br>')) + '</blockquote>'); continue; }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      flush(); const cells = l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
      const head = cells(line); i += 2; const rows = [];
      while (i < lines.length && lines[i].includes('|') && !/^\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push('<div class="nv-table"><table><thead><tr>' + head.map(c => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>' + rows.map(r => '<tr>' + r.map(c => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>'); continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      flush(); const stack = []; let html = '';
      while (i < lines.length && (m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/))) {
        const indent = m[1].length, tag = /\d/.test(m[2]) ? 'ol' : 'ul';
        while (stack.length && indent < stack[stack.length - 1].indent) html += '</li></' + stack.pop().tag + '>';
        if (!stack.length || indent > stack[stack.length - 1].indent) { stack.push({ indent, tag }); html += '<' + tag + '><li>'; } else html += '</li><li>';
        html += inline(m[3]); i++;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i]) && !/^\s*```/.test(lines[i])) html += '<br>' + inline(lines[i++].trim());
      }
      while (stack.length) html += '</li></' + stack.pop().tag + '>';
      out.push(html); continue;
    }
    para.push(line); i++;
  }
  flush(); return out.join('');
}
root.NovaRich = { rich, inline, esc, KINDS, KIND_NAMES, KIND_ICONS };
})(typeof window !== 'undefined' ? window : globalThis);
