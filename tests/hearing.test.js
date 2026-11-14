// The window's detector for "someone is speaking" (jcc/static/nova-audio.js), fed with how loud each 20 ms piece is.
// Seen live: with a film playing on another device JARVIS waited until the film paused, because it listened for quiet to
// know that a sentence had ended. A room with other sound in it never goes quiet.
const test = require('node:test'), assert = require('node:assert'), fs = require('fs'), path = require('path'), vm = require('vm');

function load() {
  let clock = 0;
  const context = { window: {}, navigator: {}, console, setTimeout, clearTimeout, Date: { now: () => clock }, Math, Int16Array, Float32Array, Uint8Array, Set, Map, Promise };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'jcc', 'static', 'nova-audio.js'), 'utf8'), context);
  return { audio: context.window.NovaAudio, tick: ms => { clock = ms; } };
}
// A piece of sound of a given loudness (the detector is handed the loudness; the piece itself is only kept).
function piece(level) { const frame = new Int16Array(320); const peak = Math.round(level * 32768 * Math.SQRT2); for (let i = 0; i < 320; i++) frame[i] = i % 2 ? peak : -peak; return frame; }
// A film on another device: its level moves about a usual level and never drops to nothing.
function film(usual, seed) { let s = seed; return () => { s = (s * 1103515245 + 12345) % 2147483648; return usual * (0.55 + 0.9 * (s / 2147483648)); }; }
function run(parts, settings = {}) {
  const impl = load(), found = [];
  let now = 0;
  const feed = impl.audio.detector({ endMs: 840, pauseMs: 240, maxMs: 30000, ...settings,
    onEnd: (sound, voiced, when) => found.push({ start: when.start / 1000, heard: now / 1000, seconds: sound.length / 16000, noisy: when.noisy, forced: when.forced, faint: when.faint }) });
  for (const [seconds, level] of parts) {
    for (let i = 0; i < seconds * 50; i++) {
      now += 20; impl.tick(now);
      const loud = typeof level === 'function' ? level() : level;
      if (Array.isArray(loud)) feed(piece(loud[0]), loud[0], loud[1]);   // [as the browser hands it on, as it really was]
      else feed(piece(loud), loud);
    }
  }
  return { found, feed, at: now / 1000 };
}

test('in a quiet room a sentence ends after a moment of quiet, as it always did', () => {
  const { found } = run([[2, 0.002], [1.5, 0.08], [2, 0.002]]);
  assert.equal(found.length, 1);
  assert.ok(!found[0].noisy && !found[0].forced);
  assert.ok(Math.abs(found[0].heard - (3.5 + 0.84)) < 0.1, 'handed on about 0.84 s after the last word: ' + found[0].heard);
  assert.ok(found[0].seconds > 1.5 && found[0].seconds < 2.3, String(found[0].seconds));
});

test('a pause in the middle of a sentence does not end it', () => {
  const { found } = run([[2, 0.002], [1, 0.08], [0.5, 0.002], [1, 0.08], [2, 0.002]]);
  assert.equal(found.length, 1);
  assert.ok(found[0].seconds > 2.4);
});

test('a film on another device is the room, not one long sentence', () => {
  const { found, feed } = run([[1, 0.002], [40, film(0.03, 7)]]);
  assert.equal(found.length, 1, 'once, when it started');
  assert.ok(found[0].forced, 'and that was not a sentence: no end was found');
  assert.ok(found[0].seconds < 6, 'a few seconds, not half a minute: ' + found[0].seconds);
  assert.ok(feed.room().busy, 'it knows something is playing');
});

test('someone speaking over the film is heard, and the end of what they say is found without any quiet', () => {
  const noise = film(0.03, 11);
  const { found } = run([[1, 0.002], [9, noise], [1.5, () => 0.11 + noise() * 0.3], [8, noise]]);
  const mine = found.find(s => s.start < 11.5 && s.heard > 10);
  assert.ok(mine, 'the sentence was found: ' + JSON.stringify(found));
  assert.ok(mine.noisy && !mine.forced);
  assert.ok(mine.heard - 11.5 < 1.3, 'about a second after they stopped, not when the film pauses: ' + (mine.heard - 11.5).toFixed(2));
  assert.ok(mine.seconds < 2.6, 'only what they said is handed on: ' + mine.seconds);
});

test('one loud moment in the film is not someone speaking', () => {
  const noise = film(0.03, 5);
  const { found } = run([[1, 0.002], [9, noise], [0.06, 0.12], [8, noise]]);
  assert.equal(found.filter(s => !s.forced).length, 0, JSON.stringify(found));
});

test('where the room is as loud as the person, no end is found, and that is said after a few seconds', () => {
  const noise = film(0.12, 3);
  const impl = load(); let now = 0; const found = [];
  const room = impl.audio.detector({ endMs: 840, pauseMs: 240 });
  const step = (feed, level) => { now += 20; impl.tick(now); feed(piece(level), level); };
  for (let i = 0; i < 50; i++) step(room, 0.002);
  for (let i = 0; i < 400; i++) step(room, noise());             // the film starts, and is taken for the room after a few seconds
  assert.ok(room.room().busy);
  // "Hey JARVIS ..." is heard by the helper that listens for the name: what follows is taken from the name on.
  const name = new Int16Array(320 * 60); for (let i = 0; i < name.length; i++) name[i] = i % 2 ? 4000 : -4000;      // no louder than the film
  const feed = impl.audio.detector({ endMs: 840, pauseMs: 240, maxMs: 30000, busyMaxMs: 7000, onEnd: (sound, voiced, when) => found.push({ heard: now / 1000, forced: when.forced, noisy: when.noisy }) });
  feed.prime(name);
  const from = now / 1000;
  for (let i = 0; i < 100; i++) step(feed, 0.1 + noise() * 0.5);       // the request, said over the film
  for (let i = 0; i < 500 && !found.length; i++) step(feed, noise());   // and the film goes on, as loud as they were
  assert.equal(found.length, 1);
  assert.ok(found[0].noisy && found[0].forced, JSON.stringify(found[0]));
  assert.ok(found[0].heard - from < 6.2, 'ended by the clock, seven seconds from the name at most: ' + (found[0].heard - from).toFixed(2));
});

test('a sentence that begins with the name knows the room and how loud this person is', () => {
  const noise = film(0.03, 9);
  const impl = load(); let now = 0; const found = [];
  const room = impl.audio.detector({});
  const step = (feed, level) => { now += 20; impl.tick(now); feed(piece(level), level); };
  for (let i = 0; i < 50; i++) step(room, 0.002);
  for (let i = 0; i < 400; i++) step(room, noise());
  const name = new Int16Array(320 * 50); for (let i = 0; i < name.length; i++) name[i] = i % 2 ? 5200 : -5200;      // about 0.16
  const feed = impl.audio.detector({ endMs: 840, pauseMs: 240, onEnd: (sound, voiced, when) => found.push({ heard: now / 1000, forced: when.forced, noisy: when.noisy }) });
  feed.prime(name);
  const spoke = now / 1000;
  for (let i = 0; i < 60; i++) step(feed, 0.14 + noise() * 0.2);        // the request
  const stopped = now / 1000;
  for (let i = 0; i < 300 && !found.length; i++) step(feed, noise());   // the film carries on
  assert.equal(found.length, 1);
  assert.ok(found[0].noisy && !found[0].forced, JSON.stringify(found[0]));
  assert.ok(found[0].heard - stopped < 1.3, 'found the end ' + (found[0].heard - stopped).toFixed(2) + ' s after they stopped (they spoke for ' + (stopped - spoke).toFixed(1) + ' s)');
});

test('a quiet-room sentence is never taken for a film, however long it is', () => {
  // Fifteen seconds of someone speaking: words and the short gaps between them (as the browser hands it on, and as it really was).
  const parts = [[1, [0.002, 0.0015]]];
  for (let i = 0; i < 30; i++) parts.push([0.4, [0.07, 0.05]], [0.1, [0.003, 0.002]]);
  parts.push([2, [0.002, 0.0015]]);
  const { found } = run(parts);
  assert.equal(found.length, 1, JSON.stringify(found));
  assert.ok(!found[0].forced && found[0].seconds > 14, JSON.stringify(found[0]));
});

test("with only the browser's evened-out loudness, twelve seconds without one pause are handed on, and are the room from then on", () => {
  // (There a film cannot be told from a person by its quiet moments: the browser hollows them out. Measured in the app's window.)
  const hollow = (usual, seed) => { const loud = film(usual, seed); let i = 0; return () => (i++ % 5 === 0 ? 0.004 : loud()); };
  const { found, feed } = run([[40, hollow(0.05, 91)]]);
  assert.ok(found.length >= 1 && !found[0].forced, JSON.stringify(found));
  assert.ok(found[0].seconds > 11.5 && found[0].seconds < 12.6, 'twelve seconds, not thirty: ' + found[0].seconds);
  assert.ok(feed.room().busy, 'and that is what the room sounds like now');
});

test("over other sound, with only the browser's loudness, nothing begins by itself unless the caller says to guess", () => {
  const noise = film(0.03, 95);
  const parts = [[1, 0.002], [9, noise], [1.5, () => 0.11 + noise() * 0.3], [8, noise]];
  const cautious = run(parts, { guess: false }).found.filter(s => !s.forced);
  assert.equal(cautious.length, 0, "JARVIS's name, heard by the helper, begins it there: " + JSON.stringify(cautious));
  const guessing = run(parts, { guess: () => true }).found.filter(s => !s.forced);
  assert.equal(guessing.length, 1, JSON.stringify(guessing));
});

// The browser evens out the microphone's loudness: a film across the room is turned up until it is as loud as the person
// at the keyboard (measured in the app's own window: the film's louder lines arrived two to three times as loud as they
// were, the person no louder than the film). A second, untouched listener on the same microphone says how loud each
// moment really was.
test('a far-off film that the browser has turned up: who is near is told from the untouched microphone', () => {
  const shown = film(0.09, 21), really = film(0.025, 22);
  const room = () => [shown(), really()];
  const { found } = run([[1, [0.002, 0.001]], [9, room], [1.5, () => [0.1 + shown() * 0.2, 0.075 + really() * 0.3]], [8, room]]);
  const mine = found.find(s => s.start < 11.5 && s.heard > 10);
  assert.ok(mine, 'the sentence was found: ' + JSON.stringify(found));
  assert.ok(mine.noisy && !mine.forced, JSON.stringify(mine));
  assert.ok(mine.heard - 11.5 < 1.3, 'about a second after they stopped: ' + (mine.heard - 11.5).toFixed(2));
  assert.ok(mine.seconds < 2.9, 'only what they said is handed on: ' + mine.seconds);
  assert.equal(found.filter(s => !s.forced).length, 1, 'and nothing else was taken for someone speaking: ' + JSON.stringify(found));
});

test('a line of the film that the browser turned up is not someone near', () => {
  const shown = film(0.05, 31), really = film(0.025, 32);
  const room = () => [shown(), really()];
  const { found } = run([[1, [0.002, 0.001]], [9, room], [1.5, () => [0.22 + shown(), really() * 1.1]], [8, room]]);
  assert.equal(found.filter(s => !s.forced).length, 0, JSON.stringify(found));
});

test('the untouched listener arriving or leaving between sentences never makes a sentence of its own', () => {
  const shown = film(0.05, 41), really = film(0.02, 42);
  const { found, feed } = run([[1, 0.002], [6, shown], [6, () => [shown(), really()]], [6, shown]]);
  assert.equal(found.filter(s => !s.forced).length, 0, JSON.stringify(found));
  assert.ok(feed.room().busy && !feed.room().truly);
});

test('if the untouched listener goes away in the middle of a sentence said over other sound, the sentence is ended', () => {
  const shown = film(0.09, 51), really = film(0.025, 52);
  const room = () => [shown(), really()];
  const { found } = run([[1, [0.002, 0.001]], [9, room], [0.6, () => [0.1 + shown() * 0.2, 0.075 + really() * 0.3]], [3, shown]]);
  const mine = found.find(s => s.heard > 10);
  assert.ok(mine && mine.forced, JSON.stringify(found));
  assert.ok(mine.heard < 11.4, 'within a second of losing it: ' + mine.heard);
});

test('after its name, the request is followed on the untouched scale too', () => {
  const shown = film(0.09, 61), really = film(0.025, 62);
  const impl = load(); let now = 0; const found = [];
  const room = impl.audio.detector({});
  const step = (feed, level, real) => { now += 20; impl.tick(now); feed(piece(level), level, real); };
  for (let i = 0; i < 50; i++) step(room, 0.002, 0.001);
  for (let i = 0; i < 400; i++) step(room, shown(), really());
  const known = room.room();
  assert.ok(known.busy && known.truly && known.n >= 50, JSON.stringify(known));
  const name = new Int16Array(320 * 50); for (let i = 0; i < name.length; i++) name[i] = i % 2 ? 3600 : -3600;      // as loud as the film, as the browser hands it on
  const feed = impl.audio.detector({ endMs: 840, pauseMs: 240, busyMaxMs: 7000, onEnd: (sound, voiced, when) => found.push({ heard: now / 1000, forced: when.forced, noisy: when.noisy }) });
  feed.prime(name, new Array(50).fill(0.08));                    // but really three times as loud: someone near
  for (let i = 0; i < 60; i++) step(feed, 0.1 + shown() * 0.2, 0.07 + really() * 0.3);   // the request
  const stopped = now / 1000;
  for (let i = 0; i < 300 && !found.length; i++) step(feed, shown(), really());            // the film carries on
  assert.equal(found.length, 1);
  assert.ok(found[0].noisy && !found[0].forced, JSON.stringify(found[0]));
  assert.ok(found[0].heard - stopped < 1.3, 'found the end ' + (found[0].heard - stopped).toFixed(2) + ' s after they stopped');
});

// A new listener is made for every sentence. It used to start knowing nothing about the room: with a film playing, the
// first seconds after each of JARVIS's answers went on finding out, and a request made in them was lost in the film.
test('the listener for your next sentence knows the room from its first moment', () => {
  const noise = film(0.03, 71);
  const impl = load(); let now = 0; const found = [];
  const step = (feed, level) => { now += 20; impl.tick(now); feed(piece(level), level); };
  const before = impl.audio.detector({});
  for (let i = 0; i < 50; i++) step(before, 0.002);
  for (let i = 0; i < 450; i++) step(before, noise());                  // the film, while JARVIS was listening and answering
  const next = impl.audio.detector({ endMs: 840, pauseMs: 240, onEnd: (sound, voiced, when) => found.push({ heard: now / 1000, seconds: sound.length / 16000, noisy: when.noisy, forced: when.forced }) });
  for (let i = 0; i < 25; i++) step(next, noise());                     // half a second later you speak
  assert.ok(next.room().busy, 'it knows something is playing');
  for (let i = 0; i < 75; i++) step(next, 0.11 + noise() * 0.3);
  const stopped = now / 1000;
  for (let i = 0; i < 200 && !found.length; i++) step(next, noise());
  assert.equal(found.length, 1, JSON.stringify(found));
  assert.ok(found[0].noisy && !found[0].forced, JSON.stringify(found[0]));
  assert.ok(found[0].heard - stopped < 1.3 && found[0].seconds < 2.7, JSON.stringify(found[0]));
});

test('what the room sounded like is forgotten once nobody has listened for a while', () => {
  const noise = film(0.03, 81);
  const impl = load(); let now = 0;
  const step = (feed, level) => { now += 20; impl.tick(now); feed(piece(level), level); };
  const before = impl.audio.detector({});
  for (let i = 0; i < 50; i++) step(before, 0.002);
  for (let i = 0; i < 300; i++) step(before, noise());
  assert.ok(before.room().busy);
  now += 5000; impl.tick(now);                                          // the microphone was off; the film has been stopped since
  const next = impl.audio.detector({});
  step(next, 0.002);
  assert.ok(!next.room().busy && next.room().n <= 1, JSON.stringify(next.room()));
});

test('half a sentence left in a listener that was set aside is not carried into its next turn', () => {
  const impl = load(); let now = 0; const found = [];
  const step = (feed, level) => { now += 20; impl.tick(now); feed(piece(level), level); };
  const one = impl.audio.detector({ onEnd: () => found.push('one') }), other = impl.audio.detector({});
  for (let i = 0; i < 50; i++) step(one, 0.002);
  for (let i = 0; i < 20; i++) step(one, 0.08);                         // someone begins to speak...
  assert.ok(one.talking());
  for (let i = 0; i < 200; i++) step(other, 0.002);                     // ...and another listener takes over for four seconds
  step(one, 0.002);
  assert.ok(!one.talking(), 'the old beginning is gone');
  for (let i = 0; i < 100; i++) step(one, 0.002);
  assert.deepEqual(found, []);
});

// Over a film, speech-to-text often writes down the film's line instead of the person's (measured with the app's own
// service). What is sent for a sentence said over other sound is the untouched microphone's sound, with everything but
// the near voice turned down.
const loudness = (sound, from, to) => { let sum = 0; for (let i = from; i < to; i++) sum += sound[i] * sound[i]; return Math.sqrt(sum / (to - from)); };
test('everything but the near voice is turned down, and the whole is made loud', () => {
  const { audio } = load();
  const pieces = [], marks = [];
  for (let i = 0; i < 100; i++) { pieces.push([i * 20, piece(0.03)]); marks.push([i * 20, i >= 40 && i < 70 ? 1 : 0]); }
  const sound = audio.nearOnly(pieces, marks);
  assert.equal(sound.length, 100 * 320);
  const film = loudness(sound, 0, 20 * 320), near = loudness(sound, 45 * 320, 65 * 320), after = loudness(sound, 85 * 320, 100 * 320);
  assert.ok(near > 0.8 * 32767 * 0.9, 'the near voice fills the range: ' + near);
  assert.ok(film < near * 0.16 && after < near * 0.16, 'the rest is an eighth of it: ' + (film / near).toFixed(3) + ', ' + (after / near).toFixed(3));
  assert.ok(loudness(sound, 36 * 320, 39 * 320) > near * 0.9, 'a little before the voice stood out is kept whole (a soft first sound)');
  assert.equal(audio.nearOnly([], marks), null);
  assert.equal(audio.nearOnly(pieces, []), null);
});

test('what is handed on for a sentence said over other sound is the untouched sound, the near voice only', () => {
  const shown = film(0.09, 101), really = film(0.025, 102);
  const impl = load(); let now = 0; const found = [], untouched = [];
  const feed = impl.audio.detector({ endMs: 840, pauseMs: 240, truth: (from, to) => untouched.filter(([at]) => at >= from && at <= to),
    onEnd: (sound, voiced, when) => found.push({ sound, when, start: when.start }) });
  const step = (level, real) => { now += 20; impl.tick(now); untouched.push([now - 5, piece(real)]); feed(piece(level), level, real); };
  for (let i = 0; i < 50; i++) step(0.002, 0.001);
  for (let i = 0; i < 450; i++) step(shown(), really());
  const spoke = now;
  for (let i = 0; i < 75; i++) step(0.1 + shown() * 0.2, 0.075 + really() * 0.3);
  for (let i = 0; i < 150 && found.filter(f => !f.when.forced).length === 0; i++) step(shown(), really());
  const mine = found.find(f => !f.when.forced);
  assert.ok(mine && mine.when.noisy && mine.when.near, JSON.stringify(mine && mine.when));
  const lead = Math.round((spoke - mine.start) / 20), sound = mine.sound;
  assert.ok(lead >= 15 && lead <= 30, 'half a second of what came before is kept: ' + lead);
  const before = loudness(sound, 0, 8 * 320), voice = loudness(sound, (lead + 20) * 320, (lead + 60) * 320), end = loudness(sound, sound.length - 8 * 320, sound.length);
  assert.ok(voice > 15000, 'the person, loud: ' + voice);
  assert.ok(before < voice * 0.1 && end < voice * 0.1, 'the film before and after, turned down: ' + (before / voice).toFixed(3) + ', ' + (end / voice).toFixed(3));
});

test('in a quiet room the sound is handed on exactly as before', () => {
  const impl = load(); let now = 0; const found = [];
  const feed = impl.audio.detector({ truth: () => { throw new Error('not asked for in a quiet room'); }, onEnd: sound => found.push(sound) });
  const step = (level, real) => { now += 20; impl.tick(now); feed(piece(level), level, real); };
  for (let i = 0; i < 100; i++) step(0.002, 0.001);
  for (let i = 0; i < 60; i++) step(0.08, 0.05);
  for (let i = 0; i < 60; i++) step(0.002, 0.001);
  assert.equal(found.length, 1);
  assert.ok(Math.abs(loudness(found[0], 20 * 320, 60 * 320) / 32768 - 0.08 * Math.SQRT2) < 0.01, 'the first listener’s own sound, untouched by this');
});

test('what turned out not to be meant for JARVIS is part of what the room sounds like from then on', () => {
  const impl = load(); let now = 0; const found = [];
  const step = (feed, level) => { now += 20; impl.tick(now); feed(piece(level), level); };
  const line = feed => { for (let i = 0; i < 90; i++) step(feed, 0.06); for (let i = 0; i < 60; i++) step(feed, 0.002); };
  const one = impl.audio.detector({ onEnd: () => found.push('line') });
  for (let i = 0; i < 100; i++) step(one, 0.002);
  line(one);                                                             // a line of the film on another device, then a pause
  assert.deepEqual(found, ['line'], 'the first one cannot be told from someone speaking');
  impl.audio.overheard();                                                // ...the AI judged it was not meant for JARVIS
  const next = impl.audio.detector({ guess: true, onEnd: () => found.push('line') });
  step(next, 0.002);
  assert.ok(next.room().busy, 'the room is known to have sound in it');
  line(next); line(next);                                                // the film goes on at the same loudness
  assert.deepEqual(found, ['line'], 'and its next lines are the room, not someone speaking');
  for (let i = 0; i < 75; i++) step(next, 0.16);                         // someone nearer and louder
  for (let i = 0; i < 60; i++) step(next, 0.002);
  assert.deepEqual(found, ['line', 'line'], 'someone who stands out from it is still heard');
});

test('a sentence that hardly stands out from what surrounds it is most likely the room: a line of a film', () => {
  // As listening starts a film is already playing on another device: its line, then its music and murmur.
  const bed = film(0.012, 111), speech = film(0.04, 112);
  const parts = [[0.8, () => [bed() * 2, bed()]], [2, () => [speech() * 2, speech()]], [1.5, () => [0.004, bed()]]];   // (the browser hollows out the pause)
  const told = run(parts, { faintBelow: 4 });
  assert.equal(told.found.length, 1);
  assert.ok(told.found[0].faint, JSON.stringify(told.found[0]));
  assert.ok(told.feed.room().busy, 'and it is what the room sounds like from now on');
  // Someone speaking in a quiet room stands far above it.
  const person = run([[0.8, [0.002, 0.0015]], [2, [0.08, 0.06]], [1.5, [0.002, 0.0015]]], { faintBelow: 4 });
  assert.equal(person.found.length, 1);
  assert.ok(!person.found[0].faint && !person.feed.room().busy, JSON.stringify(person.found[0]));
  // ...and so does someone in a room with a fan going.
  const fan = run([[0.8, [0.004, 0.009]], [2, [0.08, 0.06]], [1.5, [0.004, 0.009]]], { faintBelow: 4 });
  assert.ok(fan.found.length === 1 && !fan.found[0].faint, JSON.stringify(fan.found));
});

test('a hiccup of the untouched listener does not wipe what is known about the room', () => {
  const shown = film(0.09, 121), really = film(0.025, 122);
  const impl = load(); let now = 0, i = 0; const found = [];
  const feed = impl.audio.detector({ endMs: 840, pauseMs: 240, onEnd: (sound, voiced, when) => found.push(when) });
  const step = (level, real) => { now += 20; impl.tick(now); feed(piece(level), level, ++i % 30 === 0 ? undefined : real); };   // now and then its loudness is missing for a moment
  for (let k = 0; k < 50; k++) step(0.002, 0.001);
  for (let k = 0; k < 500; k++) step(shown(), really());
  const room = feed.room();
  assert.ok(room.truly && room.busy && room.n >= 150, JSON.stringify(room));
  for (let k = 0; k < 75; k++) step(0.1 + shown() * 0.2, 0.075 + really() * 0.3);
  for (let k = 0; k < 150 && !found.some(w => !w.forced); k++) step(shown(), really());
  const mine = found.find(w => !w.forced);
  assert.ok(mine && mine.noisy && mine.near, 'and someone speaking over the film is still told from it: ' + JSON.stringify(found));
});
