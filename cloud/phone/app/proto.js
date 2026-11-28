// What the phone signs and sends, in one place: the same strings as jcc/phone.py and cloud/phone/relay.js.
// tests/phone_vectors.json is checked against this file, the relay and the laptop.
const enc = new TextEncoder();

export const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
export const PAIR_ROUNDS = 600000;

export function b64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
export const unb64 = text => Uint8Array.from(atob(String(text || '')), c => c.charCodeAt(0));
export const unb64url = text => {
  const s = String(text || '').replace(/-/g, '+').replace(/_/g, '/');
  return unb64(s + '='.repeat((4 - s.length % 4) % 4));
};
const hex = bytes => Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');

export async function sha256Hex(data) {
  return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', typeof data === 'string' ? enc.encode(data) : data)));
}

export const requestText = (action, phoneId, at, bodyHash) => `jarvis-phone-request\n${action}\n${phoneId}\n${at}\n${bodyHash}`;
export const messageText = async (phoneId, msgId, at, text, fileHashes = []) =>
  `jarvis-phone-message\n${phoneId}\n${msgId}\n${at}\n${await sha256Hex(text)}\n${fileHashes.join(',')}`;
export const answerText = async (askId, nonce, question, detail, yes) =>
  `jarvis-phone-answer\n${askId}\n${nonce}\n${await sha256Hex(question + '\n' + detail)}\n${yes ? 'yes' : 'no'}`;
export const pairText = (publicKey, name, pairId) => `jarvis-phone-pair\n${publicKey}\n${name}\n${pairId}`;

// The 8 characters as typed: case, spaces and dashes ignored; O read as 0 and I or L as 1.
export function normalCode(code) {
  const text = String(code || '').replace(/[\s-]/g, '').toUpperCase().replace(/O/g, '0').replace(/[IL]/g, '1');
  return text.length === 8 && [...text].every(c => CROCKFORD.includes(c)) ? text : '';
}
// As it is shown while typing: K7QM-2XHD.
export function showCode(code) {
  const text = String(code || '').replace(/[\s-]/g, '').toUpperCase().slice(0, 8);
  return text.length > 4 ? text.slice(0, 4) + '-' + text.slice(4) : text;
}

export async function pairTag(code, pairId, publicKey, name, rounds = PAIR_ROUNDS) {
  const base = await crypto.subtle.importKey('raw', enc.encode(normalCode(code)), 'PBKDF2', false, ['deriveBits']);
  const key = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: enc.encode(pairId), iterations: rounds }, base, 256);
  const mac = await crypto.subtle.importKey('raw', key, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return hex(new Uint8Array(await crypto.subtle.sign('HMAC', mac, enc.encode(pairText(publicKey, name, pairId)))));
}

// JSON with every character but ASCII letters and digits written as \u escapes, as the laptop sends it: Supabase sits
// behind Cloudflare, whose firewall refuses request bodies that look like attacks (a pasted path, a bit of HTML).
// JSON parsing gives back the identical text, and the signature covers the bytes as sent.
export function wireJson(value) {
  if (typeof value === 'string') {
    let out = '"';
    for (const ch of value) {
      if (/^[A-Za-z0-9]$/.test(ch)) { out += ch; continue; }
      const code = ch.codePointAt(0);
      if (code > 0xffff) {
        const c = code - 0x10000;
        out += '\\u' + (0xd800 + (c >> 10)).toString(16).padStart(4, '0') + '\\u' + (0xdc00 + (c & 0x3ff)).toString(16).padStart(4, '0');
      } else out += '\\u' + code.toString(16).padStart(4, '0');
    }
    return out + '"';
  }
  if (Array.isArray(value)) return '[' + value.map(wireJson).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.entries(value).filter(([, v]) => v !== undefined).map(([k, v]) => wireJson(k) + ':' + wireJson(v)).join(',') + '}';
  return JSON.stringify(value ?? null);
}

export const newId = () => hex(crypto.getRandomValues(new Uint8Array(12)));
