// What the window does when JARVIS finishes something (finishPlan in jcc/static/nova-audio.js): the finished sound, and a
// toast for another chat. The Windows notification is the app's own (jcc/notices.py, tests/test_notices.py).
const test = require('node:test'), assert = require('node:assert'), fs = require('fs'), path = require('path'), vm = require('vm');

function plan() {
  const context = { window: {}, navigator: {}, console, setTimeout, clearTimeout, Date, Math, Int16Array, Float32Array, Uint8Array, Set, Map, Promise };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'jcc', 'static', 'nova-audio.js'), 'utf8'), context);
  return context.window.NovaAudio.finishPlan;
}
const finishPlan = plan(), now = 100000;

test('in front, in this chat: quick answers are silent, long work gets the sound, never a toast', () => {
  assert.deepEqual({ ...finishPlan({ status: 'done', seconds: 4, now }) }, { chime: '', toast: false });
  assert.deepEqual({ ...finishPlan({ status: 'done', seconds: 19, now }) }, { chime: '', toast: false });
  assert.deepEqual({ ...finishPlan({ status: 'done', seconds: 25, now }) }, { chime: 'done', toast: false });
});

test('in front, another chat: a toast, and the sound only after a long piece of work', () => {
  assert.deepEqual({ ...finishPlan({ status: 'done', seconds: 3, sameChat: false, now }) }, { chime: '', toast: true });
  assert.deepEqual({ ...finishPlan({ status: 'done', seconds: 40, sameChat: false, now }) }, { chime: 'done', toast: true });
});

test('behind other windows: the sound after five seconds; a failure always; a background task always', () => {
  assert.equal(finishPlan({ status: 'done', seconds: 3, focused: false, now }).chime, '');
  assert.equal(finishPlan({ status: 'done', seconds: 6, focused: false, now }).chime, 'done');
  assert.equal(finishPlan({ status: 'failed', seconds: 1, focused: false, now }).chime, 'error');
  assert.equal(finishPlan({ status: 'needs_approval', seconds: 0, background: true, now }).chime, 'done');
});

test('never while JARVIS speaks, when switched off, for a stopped task, or twice within three seconds', () => {
  assert.equal(finishPlan({ status: 'done', seconds: 60, speaking: true, now }).chime, '');
  assert.equal(finishPlan({ status: 'done', seconds: 60, sound: false, now }).chime, '');
  assert.deepEqual({ ...finishPlan({ status: 'cancelled', seconds: 60, sameChat: false, now }) }, { chime: '', toast: false });
  assert.equal(finishPlan({ status: 'done', seconds: 60, lastChime: now - 1000, now }).chime, '');
  assert.equal(finishPlan({ status: 'done', seconds: 60, lastChime: now - 3000, now }).chime, 'done');
});

test('the finished sound is two soft notes, a fifth apart', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'jcc', 'static', 'nova-audio.js'), 'utf8');
  assert.match(source, /done: \[\[523, 0, 0\.12\], \[784, 0\.11, 0\.26\]\]/);
});
