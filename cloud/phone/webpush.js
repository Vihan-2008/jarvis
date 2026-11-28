// Web Push without any library: the message encryption (RFC 8291, aes128gcm) and the VAPID signature (RFC 8292), on
// WebCrypto only. The same file runs on the relay (Deno) and in the tests (Node).
//
// What a push carries is decided by the relay, not here: only {kind, unread}, never message text.

const enc = new TextEncoder();

export const b64url = bytes => {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};
export const unb64url = text => {
  const s = String(text || '').replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(s + '='.repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0));
};
const concat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};

// Push services the phone app may subscribe with: Google (Android Chrome), Apple (iPhone), Mozilla, Microsoft.
export function allowedEndpoint(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:') return false;
    const host = u.hostname.toLowerCase();
    return host === 'fcm.googleapis.com' || host === 'updates.push.services.mozilla.com'
      || host === 'push.apple.com' || host.endsWith('.push.apple.com') || host.endsWith('.notify.windows.com');
  } catch { return false; }
}

async function hkdf(salt, ikm, info, length) {
  const key = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, key, length * 8));
}

// Encrypts one push message for one subscription ({endpoint, keys: {p256dh, auth}}): one record, as RFC 8291 asks.
export async function encryptPush(subscription, payload, deps = {}) {
  const uaPublic = unb64url(subscription?.keys?.p256dh), auth = unb64url(subscription?.keys?.auth);
  if (uaPublic.length !== 65 || auth.length < 16) throw Error('The phone gave an unusable push subscription.');
  const pair = deps.pair || await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const asPublic = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey));
  const ua = await crypto.subtle.importKey('raw', uaPublic, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: ua }, pair.privateKey, 256));
  const ikm = await hkdf(auth, shared, concat(enc.encode('WebPush: info\0'), uaPublic, asPublic), 32);
  const salt = deps.salt || crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, enc.encode('Content-Encoding: nonce\0'), 12);
  const body = typeof payload === 'string' ? enc.encode(payload) : payload;
  const key = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']);
  const sealed = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, key, concat(body, new Uint8Array([2]))));
  const header = new Uint8Array(21);
  header.set(salt, 0);
  new DataView(header.buffer).setUint32(16, 4096, false);
  header[20] = 65;
  return concat(header, asPublic, sealed);
}

// The VAPID header for one push service: a short-lived ES256 token naming that service and the owner's page.
export async function vapidHeader(endpoint, vapid, now = Date.now()) {
  const audience = new URL(endpoint).origin;
  const head = b64url(enc.encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const claims = b64url(enc.encode(JSON.stringify({ aud: audience, exp: Math.floor(now / 1000) + 12 * 3600, sub: vapid.subject })));
  const key = await crypto.subtle.importKey('jwk', vapid.privateJwk, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  const signature = new Uint8Array(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key, enc.encode(`${head}.${claims}`)));
  return `vapid t=${head}.${claims}.${b64url(signature)}, k=${vapid.publicKey}`;
}

// Sends one push. Returns 'sent', 'gone' (the phone's subscription has ended: forget it) or 'failed'.
export async function sendPush(fetcher, subscription, payload, vapid, now = Date.now()) {
  if (!allowedEndpoint(subscription?.endpoint)) return 'failed';
  const body = await encryptPush(subscription, payload);
  const response = await fetcher(subscription.endpoint, { method: 'POST', body, headers: {
    Authorization: await vapidHeader(subscription.endpoint, vapid, now), 'Content-Encoding': 'aes128gcm',
    'Content-Type': 'application/octet-stream', TTL: '86400', Urgency: 'high' } });
  if (response.status === 404 || response.status === 410) return 'gone';
  return response.ok ? 'sent' : 'failed';
}
