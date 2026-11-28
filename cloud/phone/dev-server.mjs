// A local stand-in for the whole phone set-up, for trying the phone page in a browser: it serves cloud/phone/app,
// runs the real relay code (relay.js) on an in-memory store, and plays the laptop (pairs the first phone that gets
// the code right, answers each message, and asks one approval when a message says "ask me").
// Run with: node cloud/phone/dev-server.mjs [port] [--real=SECRET]     Never deployed; no network beyond localhost.
// With --real, it does not play the laptop: a real JARVIS on this PC (its phone.json endpoint set to
// http://127.0.0.1:<port>/relay, its device secret SECRET) pairs, answers and asks, as it would with the cloud relay.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { makeRelay, sha256Hex } from './relay.js';
import { MemoryStore } from './memory-store.mjs';
import { pairTag, newId } from './app/proto.js';

const port = Number(process.argv[2] || 8787);
const REAL = (process.argv.find(a => a.startsWith('--real=')) || '').slice(7);
const DEVICE = REAL || 'dev-laptop-secret-' + newId();
const store = new MemoryStore();
const env = { JARVIS_DATA_KEY: Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64'), JARVIS_APP_ORIGIN: `http://localhost:${port}`,
  JARVIS_DEVICE_HASH: await sha256Hex(DEVICE), JARVIS_BRAINS: '[]' };
const relay = makeRelay(env, { store, log: () => {} });
const TYPES = { html: 'text/html', js: 'text/javascript', css: 'text/css', webmanifest: 'application/manifest+json', png: 'image/png', json: 'application/json' };
const code = Array.from(crypto.getRandomValues(new Uint8Array(8)), b => '0123456789ABCDEFGHJKMNPQRSTVWXYZ'[b % 32]).join('');
const pairId = 'devpair' + newId().slice(0, 9);
let laptopOn = true;

async function device(action, body = {}) {
  const res = await relay.handle(new Request('http://relay/', { method: 'POST', headers: { 'x-jarvis-action': action, 'x-jarvis-device': DEVICE }, body: JSON.stringify(body) }));
  return res.json();
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${port}`);
  const headers = { 'Content-Security-Policy': `default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`,
    'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff' };
  if (url.pathname === '/relay' && req.method === 'POST') {
    const chunks = []; for await (const c of req) chunks.push(c);
    const reply = await relay.handle(new Request('http://relay/', { method: 'POST', headers: req.headers, body: Buffer.concat(chunks) }));
    res.writeHead(reply.status, Object.fromEntries(reply.headers)); res.end(Buffer.from(await reply.arrayBuffer())); return;
  }
  if (url.pathname === '/laptop') { laptopOn = url.searchParams.get('on') !== '0'; res.end('laptop ' + (laptopOn ? 'on' : 'off')); return; }
  if (url.pathname === '/config.json') { res.writeHead(200, { ...headers, 'content-type': 'application/json' }); res.end(JSON.stringify({ relay: '/relay', vapid: null, version: 'dev', allow_tab: true })); return; }
  const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  if (!/^[\w.-]+$/.test(name)) { res.writeHead(404); res.end(); return; }
  try {
    const body = name.startsWith('icon-') ? Buffer.alloc(0) : await readFile(new URL('./app/' + name, import.meta.url));
    res.writeHead(200, { ...headers, 'content-type': TYPES[name.split('.').pop()] || 'application/octet-stream' }); res.end(body);
  } catch { res.writeHead(404); res.end(); }
}).listen(port, () => console.log(REAL ? `Phone page: http://localhost:${port}/   relay for the real JARVIS: http://127.0.0.1:${port}/relay`
  : `Phone page: http://localhost:${port}/   pairing code: ${code.slice(0, 4)}-${code.slice(4)}   (laptop off: /laptop?on=0)`));
if (REAL) await new Promise(() => {});         // (the real JARVIS is the laptop)

// The pretend laptop.
await device('pair_start', { pair_id: pairId });
for (;;) {
  if (!laptopOn) { await new Promise(r => setTimeout(r, 1000)); continue; }
  const got = await device('poll', { wait: 1 });
  for (const a of got.attempts || []) {
    if (a.tag === await pairTag(code, pairId, a.public_key, a.name)) await device('enrol', { public_key: a.public_key });
    else await device('refuse', { public_key: a.public_key });
  }
  for (const item of got.items || []) {
    await device('mark', { msg_id: item.msg_id, status: 'with_computer' });
    await new Promise(r => setTimeout(r, 1200));
    if (/ask me/i.test(item.text)) await device('ask', { ask_id: 'ask' + newId().slice(0, 9), question: 'Shall I send the email to Sam?', detail: 'To: sam@example.com\nSubject: Friday', nonce: newId() + newId().slice(0, 8), seconds: 150 });
    await device('send', { text: `(dev laptop) You said: ${item.text || '(files)'}${item.files?.length ? `\nFiles: ${item.files.map(f => f.name).join(', ')}` : ''}`, tags: ['done'], reply_to: item.msg_id });
    await device('ack', { ids: [item.msg_id] });
  }
  for (const a of got.answers || []) await device('ask_close', { ask_id: a.ask_id, result: a.yes ? 'yes' : 'no' });
}
