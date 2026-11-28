// Word documents without any library: a small writer (text with headings and bullets, in a zip of stored entries) and
// a reader that pulls the text back out of a .docx (its parts are usually deflated; the platform inflates them).
// The same file runs on the relay (Deno) and in the tests (Node).

const enc = new TextEncoder();

const TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// A zip of stored (uncompressed) entries: what Word needs, nothing more.
export function zip(files) {
  const parts = [], central = [];
  let offset = 0;
  for (const [name, data] of files) {
    const n = enc.encode(name), body = typeof data === 'string' ? enc.encode(data) : data, crc = crc32(body);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
    local.setUint32(14, crc, true); local.setUint32(18, body.length, true); local.setUint32(22, body.length, true);
    local.setUint16(26, n.length, true);
    const entry = new DataView(new ArrayBuffer(46));
    entry.setUint32(0, 0x02014b50, true); entry.setUint16(4, 20, true); entry.setUint16(6, 20, true); entry.setUint16(8, 0x0800, true);
    entry.setUint32(16, crc, true); entry.setUint32(20, body.length, true); entry.setUint32(24, body.length, true);
    entry.setUint16(28, n.length, true); entry.setUint32(42, offset, true);
    parts.push(new Uint8Array(local.buffer), n, body);
    central.push(new Uint8Array(entry.buffer), n);
    offset += 30 + n.length + body.length;
  }
  const size = central.reduce((s, p) => s + p.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, size, true); end.setUint32(16, offset, true);
  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((s, p) => s + p.length, 0));
  let at = 0;
  for (const p of all) { out.set(p, at); at += p.length; }
  return out;
}

const xml = s => String(s).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function runs(text, extra = '') {
  // **bold** spans inside a line; everything else plain.
  return String(text).split(/(\*\*[^*]+\*\*)/).filter(Boolean).map(piece => {
    const bold = /^\*\*[^*]+\*\*$/.test(piece);
    const words = bold ? piece.slice(2, -2) : piece;
    return `<w:r><w:rPr>${bold ? '<w:b/>' : ''}${extra}</w:rPr><w:t xml:space="preserve">${xml(words)}</w:t></w:r>`;
  }).join('');
}

// Markdown-ish text to the body of a Word document: # headings, - or * bullets, 1. numbered lines, blank-line paragraphs.
export function paragraphs(markdown) {
  const out = [];
  for (const raw of String(markdown || '').replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim()) continue;
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      const size = { 1: 36, 2: 30, 3: 26 }[h[1].length];
      out.push(`<w:p><w:pPr><w:spacing w:before="240" w:after="120"/></w:pPr>${runs(h[2], `<w:b/><w:sz w:val="${size}"/>`)}</w:p>`);
      continue;
    }
    const b = line.match(/^\s*[-*•]\s+(.*)$/);
    if (b) { out.push(`<w:p><w:pPr><w:ind w:left="360" w:hanging="240"/></w:pPr>${runs('• ' + b[1])}</w:p>`); continue; }
    const n = line.match(/^\s*(\d+)[.)]\s+(.*)$/);
    if (n) { out.push(`<w:p><w:pPr><w:ind w:left="360" w:hanging="300"/></w:pPr>${runs(n[1] + '. ' + n[2])}</w:p>`); continue; }
    out.push(`<w:p>${runs(line)}</w:p>`);
  }
  return out.join('') || '<w:p/>';
}

export function makeDocx(markdown, title = '') {
  const body = (title ? `<w:p>${runs(title, '<w:b/><w:sz w:val="40"/>')}</w:p>` : '') + paragraphs(markdown);
  return zip([
    ['[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'],
    ['_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'],
    ['word/document.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
      `<w:body>${body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>`],
  ]);
}

async function inflateRaw(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

const MOST = 20 * 1024 * 1024;   // a document part larger than this, unpacked, is not read

// The plain text of a .docx (one line per paragraph), or null when it is not one this can read.
export async function docxText(bytes) {
  try {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let end = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 66000); i--) if (view.getUint32(i, true) === 0x06054b50) { end = i; break; }
    if (end < 0) return null;
    const count = view.getUint16(end + 10, true);
    let at = view.getUint32(end + 16, true);
    for (let k = 0; k < count && at + 46 <= bytes.length; k++) {
      if (view.getUint32(at, true) !== 0x02014b50) return null;
      const method = view.getUint16(at + 10, true), packed = view.getUint32(at + 20, true), size = view.getUint32(at + 24, true);
      const nameLength = view.getUint16(at + 28, true), extra = view.getUint16(at + 30, true), note = view.getUint16(at + 32, true);
      const local = view.getUint32(at + 42, true), name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nameLength));
      at += 46 + nameLength + extra + note;
      if (name !== 'word/document.xml') continue;
      if (size > MOST || view.getUint32(local, true) !== 0x04034b50) return null;
      const start = local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true);
      const data = bytes.subarray(start, start + packed);
      const raw = method === 0 ? data : method === 8 ? await inflateRaw(data) : null;
      if (!raw || raw.length > MOST) return null;
      const doc = new TextDecoder().decode(raw);
      return doc.replace(/<w:tab\/>/g, '\t').replace(/<\/w:p>/g, '\n').replace(/<w:br\/>/g, '\n').replace(/<[^>]+>/g, '')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&')
        .replace(/\n{3,}/g, '\n\n').trim();
    }
    return null;
  } catch {
    return null;
  }
}
