// Tests for the phone relay: Word documents, sealing, push encryption, and every relay path with an in-memory store
// and fake AI and push services. No test touches the network.
// Run with: node --test cloud/phone/relay.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { deflateRawSync } from 'node:zlib';
import { makeDocx, docxText, zip, crc32, paragraphs } from './docx.js';
import { seal, unseal, sameText, sha256Hex, b64, unb64, makeRelay, requestText, searchHelp, ed25519Ok, LAPTOP_GONE } from './relay.js';
import { encryptPush, vapidHeader, allowedEndpoint, b64url, unb64url } from './webpush.js';
import { MemoryStore } from './memory-store.mjs';

const KEY = b64(new Uint8Array(32).map((_, i) => i + 1));
const DEVICE = 'laptop-secret-for-tests';
const ORIGIN = 'https://jarvis-abc12345.example.workers.dev';
const enc = new TextEncoder(), dec = new TextDecoder();

// ------------------------------------------------------------------ documents and sealing

test('crc32 matches the known value for "123456789"', () => {
  assert.equal(crc32(enc.encode('123456789')), 0xcbf43926);
});

test('a document JARVIS writes reads back as the same text', async () => {
  const text = await docxText(makeDocx('# Plan\n\nFirst line with **bold** words.\n- one\n- two\n1. step & <more>', 'Trip'));
  assert.match(text, /^Trip\nPlan\nFirst line with bold words\.\n• one\n• two\n1\. step & <more>$/);
});

test('a document with a deflated body (as Word saves it) is read', async () => {
  const xml = '<w:document><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:r><w:t>World &amp; more</w:t></w:r></w:p></w:body></w:document>';
  const raw = enc.encode(xml), packed = deflateRawSync(raw), name = enc.encode('word/document.xml');
  const local = new DataView(new ArrayBuffer(30));
  local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(8, 8, true);
  local.setUint32(14, crc32(raw), true); local.setUint32(18, packed.length, true); local.setUint32(22, raw.length, true); local.setUint16(26, name.length, true);
  const entry = new DataView(new ArrayBuffer(46));
  entry.setUint32(0, 0x02014b50, true); entry.setUint16(4, 20, true); entry.setUint16(6, 20, true); entry.setUint16(10, 8, true);
  entry.setUint32(16, crc32(raw), true); entry.setUint32(20, packed.length, true); entry.setUint32(24, raw.length, true); entry.setUint16(28, name.length, true);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, 1, true); end.setUint16(10, 1, true);
  end.setUint32(12, 46 + name.length, true); end.setUint32(16, 30 + name.length + packed.length, true);
  const parts = [new Uint8Array(local.buffer), name, packed, new Uint8Array(entry.buffer), name, new Uint8Array(end.buffer)];
  const file = new Uint8Array(parts.reduce((s, p) => s + p.length, 0));
  let at = 0; for (const p of parts) { file.set(p, at); at += p.length; }
  assert.equal(await docxText(file), 'Hello\nWorld & more');
});

test('anything that is not a .docx reads as null, never throws', async () => {
  assert.equal(await docxText(new Uint8Array(0)), null);
  assert.equal(await docxText(enc.encode('just some text, not a zip at all, long enough to scan')), null);
  assert.equal(await docxText(zip([['other.xml', '<x/>']])), null);
});

test('control characters never reach the document XML', () => {
  assert.ok(!/[\u0001\u0007]/.test(paragraphs('bell\u0007 and \u0001 start')));
});

test('sealed values open with the same key and nothing else', async () => {
  const value = { text: 'hello ✓', n: 3 };
  const sealed = await seal(KEY, value);
  assert.deepEqual(await unseal(KEY, sealed), value);
  assert.notEqual(await seal(KEY, value), sealed, 'a fresh IV each time');
  await assert.rejects(unseal(b64(new Uint8Array(32).fill(9)), sealed));
  const tampered = unb64(sealed); tampered[tampered.length - 1] ^= 1;
  await assert.rejects(unseal(KEY, b64(tampered)));
  await assert.rejects(seal('', { a: 1 }), /no data key/);
});

test('sameText, sha256Hex and base64', async () => {
  assert.equal(sameText('abc', 'abc'), true);
  assert.equal(sameText('abc', 'abd'), false);
  assert.equal(sameText('', ''), false);
  assert.equal(await sha256Hex('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  const bytes = new Uint8Array(70000).map((_, i) => i % 251);
  assert.deepEqual(unb64(b64(bytes)), bytes);
});

// ------------------------------------------------------------------ Web Push

async function hkdf(salt, ikm, info, length) {
  const key = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, key, length * 8));
}

test('a push message decrypts on the phone side to exactly what was sent (RFC 8291)', async () => {
  const ua = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const uaPublic = new Uint8Array(await crypto.subtle.exportKey('raw', ua.publicKey));
  const auth = crypto.getRandomValues(new Uint8Array(16));
  const body = await encryptPush({ endpoint: 'https://fcm.googleapis.com/x', keys: { p256dh: b64url(uaPublic), auth: b64url(auth) } }, '{"kind":"reply","unread":1}');
  const salt = body.subarray(0, 16), rs = new DataView(body.buffer, body.byteOffset).getUint32(16), idlen = body[20];
  assert.equal(rs, 4096); assert.equal(idlen, 65);
  const asPublic = body.subarray(21, 86), sealed = body.subarray(86);
  const as = await crypto.subtle.importKey('raw', asPublic, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: as }, ua.privateKey, 256));
  const ikm = await hkdf(auth, shared, new Uint8Array([...enc.encode('WebPush: info\0'), ...uaPublic, ...asPublic]), 32);
  const cek = await hkdf(salt, ikm, enc.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, enc.encode('Content-Encoding: nonce\0'), 12);
  const key = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['decrypt']);
  const plain = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce }, key, sealed));
  assert.equal(plain[plain.length - 1], 2, 'last-record delimiter');
  assert.equal(dec.decode(plain.subarray(0, -1)), '{"kind":"reply","unread":1}');
});

test('the VAPID token is a valid ES256 signature over the push service origin', async () => {
  const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicKey = b64url(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)));
  const header = await vapidHeader('https://web.push.apple.com/abc', { privateJwk: await crypto.subtle.exportKey('jwk', pair.privateKey), publicKey, subject: ORIGIN }, 1_700_000_000_000);
  const [, token, k] = header.match(/^vapid t=([^,]+), k=(.+)$/);
  assert.equal(k, publicKey);
  const [h, c, s] = token.split('.');
  const claims = JSON.parse(dec.decode(unb64url(c)));
  assert.equal(claims.aud, 'https://web.push.apple.com'); assert.equal(claims.sub, ORIGIN);
  assert.ok(await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, pair.publicKey, unb64url(s), enc.encode(`${h}.${c}`)));
});

test('only the known push services are allowed', () => {
  for (const ok of ['https://fcm.googleapis.com/fcm/send/x', 'https://web.push.apple.com/x', 'https://updates.push.services.mozilla.com/x', 'https://wns2-par02p.notify.windows.com/x']) assert.ok(allowedEndpoint(ok), ok);
  for (const bad of ['http://fcm.googleapis.com/x', 'https://evil.example/x', 'https://fcm.googleapis.com.evil.example/x', 'https://notpush.apple.com.evil/x', 'not a url']) assert.ok(!allowedEndpoint(bad), bad);
});

// ------------------------------------------------------------------ the relay, end to end

function harness({ brains = [], replies = [], vapid = false } = {}) {
  let clock = 1_800_000_000_000;
  const now = () => clock;
  const store = new MemoryStore(now);
  const calls = { ai: [], push: [], whisper: 0 };
  const fake = async (url, init = {}) => {
    if (/chat\/completions$/.test(url)) {
      calls.ai.push(JSON.parse(init.body));
      const next = replies.shift();
      if (!next) return new Response('busy', { status: 503 });
      return Response.json({ choices: [{ message: next }] });
    }
    if (/audio\/transcriptions$/.test(url)) { calls.whisper++; return Response.json({ text: 'remind me to call mum' }); }
    if (/push|fcm/.test(url)) { calls.push.push({ url, init }); return new Response('', { status: 201 }); }
    throw Error('unexpected network call to ' + url);
  };
  const env = { JARVIS_DATA_KEY: KEY, JARVIS_APP_ORIGIN: ORIGIN, JARVIS_BRAINS: JSON.stringify(brains) };
  const ready = (async () => {
    env.JARVIS_DEVICE_HASH = await sha256Hex(DEVICE);
    if (vapid) {
      const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign']);
      env.JARVIS_VAPID_PRIVATE = JSON.stringify(await crypto.subtle.exportKey('jwk', pair.privateKey));
      env.JARVIS_VAPID_PUBLIC = b64url(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)));
    }
  })();
  let relay;
  const read = async res => ({ status: res.status, body: /json/.test(res.headers.get('content-type') || '') ? await res.json() : new Uint8Array(await res.arrayBuffer()), headers: res.headers });
  const h = {
    store, calls, now, tick: ms => { clock += ms; },
    async relay() { await ready; relay ||= makeRelay(env, { store, fetch: fake, now, sleep: async ms => { clock += ms; }, log: () => {} }); return relay; },
    async device(action, body = {}, extra = {}) {
      const r = await h.relay();
      const res = await r.handle(new Request('https://relay.test/', { method: 'POST', headers: { 'x-jarvis-action': action, 'x-jarvis-device': extra.secret ?? DEVICE }, body: JSON.stringify(body) }));
      await r.idle();
      return read(res);
    },
    async open(action, body = {}) {
      const r = await h.relay();
      const res = await r.handle(new Request('https://relay.test/', { method: 'POST', headers: { 'x-jarvis-action': action, origin: ORIGIN }, body: JSON.stringify(body) }));
      await r.idle();
      return read(res);
    },
    read,
  };
  return h;
}

async function makePhone() {
  const pair = await crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']);
  const publicKey = b64(new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey)));
  const sign = async text => b64(new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, pair.privateKey, enc.encode(text))));
  return { pair, publicKey, sign };
}

let pairCounter = 0;
// A paired phone, through the whole pairing flow as the app and the laptop do it.
async function paired(h, name = 'iPhone, Safari') {
  const phone = await makePhone();
  const pairId = 'pairid' + String(++pairCounter).padStart(4, '0');
  assert.equal((await h.device('pair_start', { pair_id: pairId })).status, 200);
  assert.equal((await h.open('pair_open')).body.pair_id, pairId);
  const tag = await sha256Hex('tag-made-from-the-code-' + pairId);      // the laptop checks the tag; the relay never can
  assert.equal((await h.open('pair_request', { pair_id: pairId, public_key: phone.publicKey, name, tag })).status, 200);
  const polled = await h.device('poll', { wait: 0 });
  assert.equal(polled.body.attempts.length, 1);
  assert.equal(polled.body.attempts[0].tag, tag);
  const enrolled = await h.device('enrol', { public_key: phone.publicKey });
  assert.equal(enrolled.status, 200, JSON.stringify(enrolled.body));
  const status = await h.open('pair_status', { public_key: phone.publicKey });
  assert.equal(status.body.state, 'paired');
  phone.id = status.body.phone_id;
  assert.equal(phone.id, enrolled.body.phone_id);
  phone.call = async (action, body = {}, opts = {}) => {
    const raw = opts.raw ?? enc.encode(JSON.stringify(body));
    const at = opts.at ?? h.now();
    const sig = opts.sig ?? await phone.sign(requestText(action, phone.id, at, await sha256Hex(raw)));
    const r = await h.relay();
    const res = await r.handle(new Request('https://relay.test/', { method: 'POST', body: raw, headers: { 'x-jarvis-action': action, 'x-jarvis-phone': opts.phoneId ?? phone.id,
      'x-jarvis-at': String(at), 'x-jarvis-sig': sig, origin: ORIGIN, ...(opts.headers || {}) } }));
    await r.idle();
    return h.read(res);
  };
  phone.send = async (text, extra = {}) => {
    const msgId = extra.msg_id || crypto.randomUUID().replace(/-/g, '');
    const at = h.now();
    const sig = await phone.sign(`jarvis-phone-message\n${phone.id}\n${msgId}\n${at}\n${await sha256Hex(text)}\n`);
    return { msgId, res: await phone.call('send', { msg_id: msgId, text, files: extra.files || [], at, sig, wait_for_computer: !!extra.wait }) };
  };
  return phone;
}

test('pairing goes through the relay only, and the relay keeps no pairing secret', async () => {
  const h = harness();
  const phone = await paired(h);
  assert.equal((await h.store.phones()).length, 1);
  const pairing = await h.store.get('pairing');
  assert.deepEqual(Object.keys(pairing).sort(), ['attempts', 'closed', 'expires', 'pair_id']);
  const other = await makePhone();
  assert.equal((await h.open('pair_request', { pair_id: pairing.pair_id, public_key: other.publicKey, name: 'x', tag: await sha256Hex('t') })).status, 409);
  assert.ok(phone.id);
});

test('pairing expires after 10 minutes, and wrong pair ids are refused', async () => {
  const h = harness();
  await h.device('pair_start', { pair_id: 'pairid9002' });
  const phone = await makePhone();
  assert.equal((await h.open('pair_request', { pair_id: 'wrongid000', public_key: phone.publicKey, name: 'x', tag: await sha256Hex('t') })).status, 409);
  h.tick(10 * 60 * 1000 + 1);
  assert.equal((await h.open('pair_open')).body.pair_id, null);
  assert.equal((await h.open('pair_request', { pair_id: 'pairid9002', public_key: phone.publicKey, name: 'x', tag: await sha256Hex('t') })).status, 409);
});

test('pairing tries are limited to 10 an hour', async () => {
  const h = harness();
  await h.device('pair_start', { pair_id: 'pairid9003' });
  for (let i = 0; i < 10; i++) {
    const p = await makePhone();
    assert.equal((await h.open('pair_request', { pair_id: 'pairid9003', public_key: p.publicKey, name: 'x', tag: await sha256Hex('t' + i) })).status, 200);
  }
  const p = await makePhone();
  assert.equal((await h.open('pair_request', { pair_id: 'pairid9003', public_key: p.publicKey, name: 'x', tag: await sha256Hex('t') })).status, 429);
});

test('a sixth phone is refused', async () => {
  const h = harness();
  for (let i = 0; i < 5; i++) await paired(h, 'phone ' + i);
  await h.device('pair_start', { pair_id: 'pairid9009' });
  const p = await makePhone();
  await h.open('pair_request', { pair_id: 'pairid9009', public_key: p.publicKey, name: 'six', tag: await sha256Hex('t') });
  assert.equal((await h.device('enrol', { public_key: p.publicKey })).status, 409);
});

test('the laptop needs its own secret', async () => {
  const h = harness();
  assert.equal((await h.device('status', {}, { secret: 'wrong' })).status, 401);
  assert.equal((await h.device('status')).status, 200);
});

test('unsigned, wrongly signed, stale and unknown-phone requests are refused and write nothing', async () => {
  const h = harness();
  const phone = await paired(h);
  const body = { msg_id: 'aaaaaaaaaaaa', text: 'hi', at: h.now(), sig: 'x' };
  const other = await makePhone();
  const raw = enc.encode(JSON.stringify(body));
  const wrongSig = await other.sign(requestText('send', phone.id, h.now(), await sha256Hex(raw)));
  assert.equal((await phone.call('send', body, { sig: wrongSig })).status, 401);
  assert.equal((await phone.call('send', body, { sig: '' })).status, 401);
  assert.equal((await phone.call('send', body, { at: h.now() - 6 * 60 * 1000 })).status, 401);
  assert.equal((await phone.call('send', body, { phoneId: 'nosuchphone1' })).status, 401);
  const sig = await phone.sign(requestText('send', phone.id, h.now(), await sha256Hex(raw)));
  assert.equal((await phone.call('send', body, { raw: enc.encode(JSON.stringify({ ...body, text: 'changed' })), sig })).status, 401);
  assert.equal(h.store.inbox.size, 0);
  assert.equal(h.store.transcript.length, 0);
});

test("a message reaches the laptop with the phone's own signature, once", async () => {
  const h = harness();
  const phone = await paired(h);
  await h.device('poll', { wait: 0 });                        // the laptop is here
  const { msgId, res } = await phone.send('What is on my list today?');
  assert.equal(res.status, 200);
  assert.equal(res.body.computer, 'on');
  assert.equal((await phone.send('again', { msg_id: msgId })).res.body.duplicate, true);
  const polled = await h.device('poll', { wait: 0 });
  assert.equal(polled.body.items.length, 1);
  const item = polled.body.items[0];
  assert.equal(item.text, 'What is on my list today?');
  assert.equal(item.phone_id, phone.id);
  assert.ok(await ed25519Ok(phone.publicKey, item.sig, `jarvis-phone-message\n${phone.id}\n${msgId}\n${item.at}\n${await sha256Hex(item.text)}\n`));
  assert.equal(h.calls.ai.length, 0);
  await h.device('send', { text: 'Two things: dentist at 4, and the report.', reply_to: msgId });
  const synced = await phone.call('sync', { after: 0, wait: 0 });
  assert.deepEqual(synced.body.messages.map(m => [m.role, m.status ?? null, m.text]),
    [['user', 'with_computer', 'What is on my list today?'], ['assistant', null, 'Two things: dentist at 4, and the report.']]);
  assert.equal(synced.body.computer.on, true);
  await h.device('ack', { ids: [msgId] });
  assert.equal(h.store.inbox.size, 0);
});

test('with the laptop off and no laptop-off answers, a message waits and the phone is told', async () => {
  const h = harness();
  const phone = await paired(h);
  h.tick(LAPTOP_GONE + 1);
  const { msgId } = await phone.send('Send Priya the deck');
  assert.equal(h.store.inbox.get(msgId).status, 'deferred');
  const synced = await phone.call('sync', { after: 0, wait: 0 });
  assert.equal(synced.body.messages[0].status, 'queued');
  assert.equal(synced.body.messages[1].role, 'notice');
  assert.equal(synced.body.offline_answers, false);
  const polled = await h.device('poll', { wait: 0 });
  assert.equal(polled.body.items[0].msg_id, msgId);
});

const GROQ = [{ name: 'groq', base: 'https://api.groq.com/openai/v1', key: 'k', model: 'llama', daily: 100 }];

test('with the laptop off, the smaller assistant answers, and the phone sees it tagged', async () => {
  const h = harness({ brains: GROQ, replies: [{ content: 'Paris.' }] });
  const phone = await paired(h);
  await h.device('context', { pack: { name: 'JARVIS', facts: 'Lives in Mumbai.', help: [] } });
  h.tick(LAPTOP_GONE + 1);
  const { msgId } = await phone.send('Capital of France?');
  assert.equal(h.calls.ai.length, 1);
  assert.match(h.calls.ai[0].messages[0].content, /Lives in Mumbai/);
  assert.equal(h.store.inbox.size, 0);
  const synced = await phone.call('sync', { after: 0, wait: 0 });
  assert.equal(synced.body.messages[0].status, 'answered_here');
  assert.deepEqual(synced.body.messages[1].tags, ['offline']);
  assert.equal(synced.body.messages[1].text, 'Paris.');
  const log = await h.device('offlog');
  assert.equal(log.body.turns.length, 2);
  assert.equal(log.body.turns[0].msg_id, msgId);
  // The phone's signed original travels with the turn, so the laptop writes only what the phone really sent.
  const signed = log.body.turns[0].signed;
  assert.equal(signed.text, 'Capital of France?');
  assert.equal(signed.phone_id, phone.id);
  assert.equal(signed.msg_id, msgId);
  assert.equal(typeof signed.sig, 'string');
  assert.equal(log.body.turns[1].signed, undefined);
});

test('switching every laptop-off key off also drops the context the relay held for them', async () => {
  const h = harness({ brains: GROQ });
  await h.device('context', { pack: { name: 'JARVIS', facts: 'Lives in Mumbai.', help: [] } });
  assert.ok(await h.store.get('context'));
  await h.device('brains', { brains: [] });
  assert.equal(await h.store.get('context'), null);
  assert.equal(await h.store.get('brains'), null);
});

test('"wait for my computer" never calls the model', async () => {
  const h = harness({ brains: GROQ, replies: [{ content: 'no' }] });
  const phone = await paired(h);
  h.tick(LAPTOP_GONE + 1);
  await phone.send('Do it on the computer', { wait: true });
  assert.equal(h.calls.ai.length, 0);
  assert.equal(h.store.transcript[0].status, 'queued');
});

test("queue_for_laptop keeps the phone's signed original for the laptop", async () => {
  const h = harness({ brains: GROQ, replies: [{ content: '', tool_calls: [{ id: 'c1', type: 'function', function: { name: 'queue_for_laptop', arguments: JSON.stringify({ request: 'email the report', reply: 'Queued for your computer.' }) } }] }] });
  const phone = await paired(h);
  h.tick(LAPTOP_GONE + 1);
  const { msgId } = await phone.send('Email the report to Sam');
  const polled = await h.device('poll', { wait: 0 });
  assert.equal(polled.body.items[0].text, 'Email the report to Sam');
  assert.ok(polled.body.items[0].sig);
  assert.equal(polled.body.items[0].queued, 'email the report');
  const synced = await phone.call('sync', { after: 0, wait: 0 });
  assert.equal(synced.body.messages.find(m => m.msg_id === msgId).status, 'queued');
  assert.equal(synced.body.messages[1].text, 'Queued for your computer.');
});

test('how_to answers from the guides the laptop uploaded, data questions included', async () => {
  const h = harness({ brains: GROQ, replies: [
    { content: '', tool_calls: [{ id: 'h1', type: 'function', function: { name: 'how_to', arguments: JSON.stringify({ question: 'where does my voice data go' }) } }] },
    { content: 'Voice notes go to Groq for transcription.' }] });
  const phone = await paired(h);
  await h.device('context', { pack: { help: [{ title: 'Voice notes: where your data goes', text: 'Audio is sent to Groq Whisper, then deleted.' }, { title: 'Gmail', text: 'Connect in Connections.' }] } });
  h.tick(LAPTOP_GONE + 1);
  await phone.send('Where does my voice data go?');
  assert.equal(h.calls.ai.length, 2);
  const toolTurn = h.calls.ai[1].messages.find(m => m.role === 'tool');
  assert.match(toolTurn.content, /Groq Whisper/);
  assert.doesNotMatch(toolTurn.content, /Gmail/);
});

test('searchHelp ranks titles first and ignores short words', () => {
  const sections = [{ title: 'Phone app', text: 'Set up the phone app from /phone.' }, { title: 'Gmail', text: 'phone numbers are not used' }];
  assert.equal(searchHelp(sections, 'how do I set up the phone')[0].title, 'Phone app');
  assert.deepEqual(searchHelp(sections, 'a an'), []);
});

test('make_document stores a sealed Word file the phone can download', async () => {
  const h = harness({ brains: GROQ, replies: [{ content: '', tool_calls: [{ id: 'd1', type: 'function', function: { name: 'make_document', arguments: JSON.stringify({ filename: 'Trip plan', title: 'Goa', content: '# Day 1\n- beach', caption: 'Your plan.' }) } }] }] });
  const phone = await paired(h);
  h.tick(LAPTOP_GONE + 1);
  await phone.send('Make me a trip plan document');
  const synced = await phone.call('sync', { after: 0, wait: 0 });
  const file = synced.body.messages[1].files[0];
  assert.equal(file.name, 'Trip plan.docx');
  assert.notEqual(dec.decode(h.store.blobs.get(file.id).subarray(0, 2)), 'PK', 'stored sealed, not as a plain zip');
  const got = await phone.call('file', { id: file.id });
  assert.match(await docxText(got.body), /^Goa\nDay 1\n• beach$/);
});

test('a voice note is transcribed while the laptop is off', async () => {
  const h = harness({ brains: GROQ, replies: [{ content: 'Reminder noted for when your computer is back.' }] });
  const phone = await paired(h);
  h.tick(LAPTOP_GONE + 1);
  const audio = new Uint8Array(1000).fill(7);
  const up = await phone.call('upload', null, { raw: audio, headers: { 'content-type': 'audio/mp4', 'x-jarvis-name': 'voice.m4a' } });
  assert.equal(up.status, 200);
  assert.equal(up.body.sha256, await sha256Hex(audio));
  await phone.send('', { files: [{ id: up.body.id, sha256: up.body.sha256, name: 'voice.m4a', mime: 'audio/mp4', size: 1000 }] });
  assert.equal(h.calls.whisper, 1);
  assert.match(h.calls.ai[0].messages.at(-1).content, /\(Voice note\) remind me to call mum/);
});

test('files over 20 MB are refused', async () => {
  const h = harness();
  const phone = await paired(h);
  const res = await phone.call('upload', null, { raw: new Uint8Array(20 * 1024 * 1024 + 2048), headers: { 'content-type': 'application/pdf' } });
  assert.equal(res.status, 413);
});

test('the 61st message in an hour is refused without a model call', async () => {
  const h = harness();
  const phone = await paired(h);
  for (let i = 0; i < 60; i++) { await h.device('poll', { wait: 0 }); assert.equal((await phone.send('m' + i)).res.status, 200); }
  const last = await phone.send('one too many');
  assert.equal(last.res.status, 429);
  assert.equal(last.res.body.limit, true);
});

test('approvals are only stored and passed on; the laptop decides; expired asks take no answer', async () => {
  const h = harness();
  const phone = await paired(h);
  const nonce = 'ab'.repeat(16);
  await h.device('ask', { ask_id: 'ask000001', question: 'Send the email to Sam?', detail: 'To: sam@example.com', nonce, seconds: 150 });
  const synced = await phone.call('sync', { after: 0, wait: 0 });
  assert.equal(synced.body.asks[0].question, 'Send the email to Sam?');
  const sig = await phone.sign(`jarvis-phone-answer\nask000001\n${nonce}\n${await sha256Hex('Send the email to Sam?\nTo: sam@example.com')}\nyes`);
  assert.equal((await phone.call('answer', { ask_id: 'ask000001', yes: true, sig })).status, 200);
  const polled = await h.device('poll', { wait: 0 });
  assert.equal(polled.body.answers[0].yes, true);
  assert.equal(polled.body.answers[0].sig, sig);
  await h.device('ask_close', { ask_id: 'ask000001', result: 'yes' });
  assert.equal((await phone.call('answer', { ask_id: 'ask000001', yes: true, sig })).status, 409);
  await h.device('ask', { ask_id: 'ask000002', question: 'q', detail: '', nonce, seconds: 30 });
  h.tick(31_000);
  assert.equal((await phone.call('answer', { ask_id: 'ask000002', yes: true, sig })).status, 409);
});

test('a removed phone gets "revoked" and nothing else', async () => {
  const h = harness();
  const phone = await paired(h);
  await h.device('revoke', { phone_id: phone.id });
  const res = await phone.call('sync', { after: 0, wait: 0 });
  assert.equal(res.status, 401);
  assert.equal(res.body.error, 'revoked');
});

test('push: only allowed services are stored, sealed; pushes carry no message text', async () => {
  const h = harness({ vapid: true });
  const phone = await paired(h);
  const ua = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const keys = { p256dh: b64url(new Uint8Array(await crypto.subtle.exportKey('raw', ua.publicKey))), auth: b64url(crypto.getRandomValues(new Uint8Array(16))) };
  assert.equal((await phone.call('push', { subscription: { endpoint: 'https://evil.example/x', keys } })).status, 400);
  assert.equal((await phone.call('push', { subscription: { endpoint: 'https://fcm.googleapis.com/fcm/send/abc', keys } })).status, 200);
  assert.doesNotMatch((await h.store.phone(phone.id)).push, /fcm/);
  await h.device('send', { text: 'A secret answer about the dentist' });
  assert.equal(h.calls.push.length, 1);
  assert.doesNotMatch(dec.decode(h.calls.push[0].init.body), /dentist/);
  assert.match(h.calls.push[0].init.headers.Authorization, /^vapid t=/);
});

test("CORS: only the owner's own page origin is allowed", async () => {
  const h = harness();
  const r = await h.relay();
  const ok = await r.handle(new Request('https://relay.test/', { method: 'OPTIONS', headers: { origin: ORIGIN } }));
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get('access-control-allow-origin'), ORIGIN);
  const bad = await r.handle(new Request('https://relay.test/', { method: 'OPTIONS', headers: { origin: 'https://evil.example' } }));
  assert.equal(bad.status, 403);
});

test('remove everything clears messages, files and phones', async () => {
  const h = harness();
  const phone = await paired(h);
  await phone.call('upload', null, { raw: new Uint8Array(10), headers: { 'content-type': 'text/plain' } });
  await phone.send('hello');
  await h.store.put('brains', { sealed: 'x' });
  await h.store.put('ask:abcd1234', { question: 'Send it?' });
  await h.device('remove_everything');
  assert.equal(h.store.state.size, 0, 'every stored row goes: keys, push key, questions, context, pairing');
  assert.equal(h.store.inbox.size, 0);
  assert.equal(h.store.transcript.length, 0);
  assert.equal(h.store.blobs.size, 0);
  assert.equal((await h.store.phone(phone.id)).revoked, true);
});

// ------------------------------------------------------------------ the same texts and signatures as the laptop (tests/phone_vectors.json)

test('the laptop and the relay sign and check the very same texts', async () => {
  const { readFile } = await import('node:fs/promises');
  const v = JSON.parse(await readFile(new URL('../../tests/phone_vectors.json', import.meta.url), 'utf8'));
  for (const c of v.cases) assert.ok(await ed25519Ok(v.public_key, c.sig, c.text), c.kind);
  const body = unb64(v.cases[0].body_b64);
  assert.equal(requestText('send', 'phone0001aa', 1800000000000, await sha256Hex(body)), v.cases[0].text);
  const m = v.cases[2];
  assert.equal(`jarvis-phone-message\nphone0001aa\nmsg00000002\n1800000000001\n${await sha256Hex(m.message_text)}\n${'a'.repeat(64)},${'b'.repeat(64)}`, m.text);
  const p = v.pair;
  const base = await crypto.subtle.importKey('raw', enc.encode(p.normal), 'PBKDF2', false, ['deriveBits']);
  const key = new Uint8Array(await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: enc.encode(p.pair_id), iterations: 600000 }, base, 256));
  assert.equal(Buffer.from(key).toString('hex'), p.key_hex);
  const mac = await crypto.subtle.importKey('raw', key, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const tag = new Uint8Array(await crypto.subtle.sign('HMAC', mac, enc.encode(`jarvis-phone-pair\n${p.public_key}\n${p.name}\n${p.pair_id}`)));
  assert.equal(Buffer.from(tag).toString('hex'), p.tag);
});

test('an approval the phone already shows does not end its wait, so an open ask is not polled in a loop', async () => {
  const h = harness();
  const phone = await paired(h);
  await h.device('ask', { ask_id: 'ask000009', question: 'q', detail: '', nonce: 'ab'.repeat(16), seconds: 150 });
  const first = await phone.call('sync', { after: 0, wait: 0 });
  assert.equal(first.body.asks.length, 1);
  const started = h.now();
  const second = await phone.call('sync', { after: first.body.latest, wait: 20, known_asks: ['ask000009'] });
  assert.ok(h.now() - started >= 20000, 'it waited');
  assert.equal(second.body.asks.length, 1);
});

test('an attempt the laptop already holds does not end its long poll', async () => {
  const h = harness();
  const phone = await makePhone();
  await h.device('pair_start', { pair_id: 'pairid7001' });
  await h.open('pair_request', { pair_id: 'pairid7001', public_key: phone.publicKey, name: 'x', tag: await sha256Hex('t') });
  assert.equal((await h.device('poll', { wait: 0 })).body.attempts.length, 1);
  const started = h.now();
  const held = await h.device('poll', { wait: 20, known_attempts: [phone.publicKey] });
  assert.ok(h.now() - started >= 20000, 'it waited');
  assert.equal(held.body.attempts.length, 0);
});

test('keys switched on in JARVIS are kept sealed and answer while the laptop is off; switching them off deletes them', async () => {
  const h = harness({ replies: [{ content: 'Paris.' }] });
  const phone = await paired(h);
  const set = await h.device('brains', { brains: GROQ });
  assert.deepEqual(set.body.brains, ['groq']);
  assert.doesNotMatch(JSON.stringify([...h.store.state]), /"key":"k"/, 'the key is stored sealed');
  h.tick(LAPTOP_GONE + 1);
  await phone.send('Capital of France?');
  assert.equal(h.calls.ai.length, 1);
  await h.device('brains', { brains: [] });
  assert.equal(await h.store.get('brains'), null);
  assert.deepEqual((await h.device('status')).body.brains, []);
});

test('with no push key in the secrets, the relay makes one, keeps it sealed, and hands out only the public half', async () => {
  const h = harness();
  const status = await h.device('status');
  assert.match(status.body.vapid, /^[A-Za-z0-9_-]{80,90}$/);
  assert.equal((await h.device('status')).body.vapid, status.body.vapid, 'made once');
  assert.doesNotMatch(JSON.stringify([...h.store.state]), /"d":/, 'the private half is sealed');
});
