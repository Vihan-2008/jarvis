// The phone page's signing texts against the shared vectors (tests/phone_vectors.json), checked by all three sides.
// Run with: node --test cloud/phone/app/proto.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import * as P from './proto.js';

const v = JSON.parse(await readFile(new URL('../../../tests/phone_vectors.json', import.meta.url), 'utf8'));

test('the page builds exactly the texts the laptop checks', async () => {
  const [req, m1, m2, a1, a2] = v.cases;
  assert.equal(P.requestText('send', 'phone0001aa', 1800000000000, await P.sha256Hex(P.unb64(req.body_b64))), req.text);
  assert.equal(await P.messageText('phone0001aa', 'msg00000001', 1800000000000, 'Hello, JARVIS'), m1.text);
  assert.equal(await P.messageText('phone0001aa', 'msg00000002', 1800000000001, m2.message_text, ['a'.repeat(64), 'b'.repeat(64)]), m2.text);
  assert.equal(await P.answerText('ask0000001', 'ab'.repeat(16), 'Send the email to Sam?', 'To: sam@example.com', true), a1.text);
  assert.equal(await P.answerText('ask0000002', 'cd'.repeat(16), 'Delete it?', '', false), a2.text);
});

test('the pairing tag and the code as typed', async () => {
  const p = v.pair;
  assert.equal(P.normalCode(p.code), p.normal);
  assert.equal(await P.pairTag(p.code, p.pair_id, p.public_key, p.name), p.tag);
  assert.equal(P.showCode('k7qm2x'), 'K7QM-2X');
  assert.equal(P.normalCode('O1IL-0000'), '01110000');
  assert.equal(P.normalCode('UUUUUUUU'), '');
});

test('wire JSON parses back to the same value, with nothing a firewall would flag left in it', () => {
  const value = { text: '..%2f..%2fetc/passwd <script>alert(1)</script> Café ✓ 🎉', n: 3, files: [{ a: null }], skip: undefined };
  const wire = P.wireJson(value);
  assert.deepEqual(JSON.parse(wire), { text: value.text, n: 3, files: [{ a: null }] });
  assert.doesNotMatch(wire, /<script|%2f|\.\./);
});
