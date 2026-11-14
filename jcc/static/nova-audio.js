/* NOVA audio: the microphone, a detector for when someone is speaking, a player for JARVIS's voice
   and a few soft sounds. Nothing here talks to the network. */
(() => {
'use strict';
const RATE = 16000, FRAME_MS = 20;
let micContext = null, micStream = null, micNode = null, micLevel = 0, micOpening = null;
let trueStream = null, trueLevel = 0, trueAt = 0;   // a second, untouched listener on the same microphone: how loud things really are
let echoWanted = 'all', echoAll = false, held = false;   // echoAll: the PC's own sound really is being taken out of the microphone
let wantMic = '', wantOut = '', outId = '', sinkNow = '', micName = '', changed = null;   // a chosen device is known by its name; '' is the Windows default
const heardLevels = []; let heardAt = 0;
const hearers = new Set();
let out = null, line = null, meter = null, meterData = null, queueEnd = 0, carry = null;
const playing = new Set();
let whenQuiet = null;

/* ---------- which microphone and which speakers ----------
   Windows' own default is the default. A device chosen in the settings is remembered by its name (the same name Windows
   shows), and used whenever it is connected; otherwise the Windows default carries on. */
const plain = label => String(label || '').replace(/^\s*(default|communications)\s*-\s*/i, '').replace(/\s*\([0-9a-f]{4}:[0-9a-f]{4}\)\s*$/i, '').replace(/\s+/g, ' ').trim();
async function devices() {
  const found = { mics: [], speakers: [], defaultMic: '', defaultSpeaker: '', named: false };
  if (!navigator.mediaDevices?.enumerateDevices) return found;
  for (const device of await navigator.mediaDevices.enumerateDevices()) {
    const mic = device.kind === 'audioinput', speaker = device.kind === 'audiooutput';
    if (!mic && !speaker || !device.label) continue;          // names are only given once the microphone has been allowed
    found.named = true;
    const name = plain(device.label);
    if (device.deviceId === 'default') { if (mic) found.defaultMic = name; else found.defaultSpeaker = name; continue; }
    if (device.deviceId === 'communications') continue;
    const list = mic ? found.mics : found.speakers;
    if (!list.some(d => d.name === name)) list.push({ name, id: device.deviceId });
  }
  return found;
}
async function findOut() { outId = wantOut ? ((await devices().catch(() => null))?.speakers.find(s => s.name === wantOut)?.id || '') : ''; return outId; }
async function sink() {   // send JARVIS's voice and sounds to the chosen speakers
  if (!out || typeof out.setSinkId !== 'function' || outId === sinkNow) return;
  const to = outId;
  try { await out.setSinkId(to); sinkNow = to; } catch { outId = ''; if (sinkNow) { try { await out.setSinkId(''); } catch {} sinkNow = ''; } }
}
async function use(mic, speaker) {
  mic = plain(mic); speaker = plain(speaker);
  const other = mic !== wantMic; wantMic = mic; wantOut = speaker;
  await findOut(); await sink();
  if (other && (micNode || micOpening)) await reopen();
}
navigator.mediaDevices?.addEventListener?.('devicechange', () => {   // something was plugged in or pulled out
  clearTimeout(changed);
  changed = setTimeout(async () => {
    try {
      await findOut(); await sink();
      if (micNode && wantMic && micName !== wantMic && (await devices()).mics.some(m => m.name === wantMic)) await reopen();   // the chosen microphone is back
    } catch {}
    window.dispatchEvent(new Event('nova-devices'));
  }, 500);
});

/* ---------- microphone ---------- */
function rms(frame) { let sum = 0; for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i]; return Math.sqrt(sum / frame.length) / 32768; }
async function micStart() {
  if (micNode) return;
  if (micOpening) return micOpening;
  micOpening = (async () => {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new Error('This window cannot use a microphone.');
    let stream;
    // Everything the PC itself plays (JARVIS's own voice, a film, music) is taken out of what the microphone hears, where
    // the browser can do that ("all"). Where it cannot, only this window's own sound is taken out, as before.
    const basic = () => ({ channelCount: 1, echoCancellation: echoWanted, noiseSuppression: true, autoGainControl: true });
    const ask = id => navigator.mediaDevices.getUserMedia({ audio: id ? { ...basic(), deviceId: { exact: id } } : basic() });
    const open = async id => {
      try { return await ask(id); }
      catch (error) { if (echoWanted !== 'all' || !/TypeError|OverconstrainedError|NotSupportedError/.test(error.name)) throw error; echoWanted = true; return ask(id); }
    };
    try {
      let chosen = wantMic ? ((await devices().catch(() => null))?.mics.find(m => m.name === wantMic) || null) : null;
      try { stream = await open(chosen?.id); }
      catch (error) { if (!chosen || error.name === 'NotAllowedError') throw error; chosen = null; stream = await open(); }   // unplugged or busy: the Windows default
      if (wantMic && !chosen) {   // device names are only known once the microphone has been allowed, so look once more
        const again = (await devices().catch(() => null))?.mics.find(m => m.name === wantMic);
        if (again) { try { const better = await open(again.id); stream.getTracks().forEach(t => t.stop()); stream = better; } catch {} }
      }
    }
    catch (error) {
      throw new Error(error.name === 'NotAllowedError' ? 'JARVIS needs permission to use the microphone. Allow it when Windows or the window asks, then try again.'
        : error.name === 'NotFoundError' ? 'No microphone was found. Plug one in, or check Windows sound settings.' : 'The microphone could not be opened. Another app may be using it.');
    }
    const context = new AudioContext({ sampleRate: RATE });
    try { await context.audioWorklet.addModule('/nova-mic.js'); }
    catch { stream.getTracks().forEach(t => t.stop()); context.close().catch(() => {}); throw new Error('The microphone could not be started in this window.'); }
    const node = new AudioWorkletNode(context, 'nova-mic'), silent = context.createGain(); silent.gain.value = 0;
    node.port.onmessage = e => {
      const frame = e.data, level = rms(frame); micLevel += (level - micLevel) * 0.5;
      heardLevels.push(level); if (heardLevels.length > 600) heardLevels.shift(); heardAt = Date.now();   // loudness only, for telling the PC's sound from a person
      const truly = trueStream && heardAt - trueAt < 400 ? trueLevel : undefined;                           // how loud that moment really was, if known
      for (const hear of hearers) { try { hear(frame, level, truly); } catch {} }
    };
    context.createMediaStreamSource(stream).connect(node); node.connect(silent).connect(context.destination);   // kept running, never played back
    // The microphone was unplugged: carry on with whichever one Windows offers next, for whoever was listening.
    stream.getAudioTracks()[0]?.addEventListener('ended', () => { if (micStream === stream) reopen().catch(() => {}); });
    micContext = context; micStream = stream; micNode = node; micName = plain(stream.getAudioTracks()[0]?.label);
    // Windows can have the microphone muted (its mute key, or Settings): then nothing at all arrives, and the browser says
    // so on the track. Whoever listens is told, so the owner can be told why nothing is heard.
    const track = stream.getAudioTracks()[0], tell = () => { if (micStream === stream) window.dispatchEvent(new CustomEvent('nova-mic-muted', { detail: !!track?.muted })); };
    track?.addEventListener('mute', tell); track?.addEventListener('unmute', tell);
    if (track?.muted) setTimeout(tell, 0); else setTimeout(() => { if (track?.muted) tell(); }, 1500);
    try { echoAll = stream.getAudioTracks()[0]?.getSettings?.().echoCancellation === 'all'; } catch { echoAll = false; }
    listenTruly(context, stream).catch(() => {});
    if (!outId && wantOut) findOut().then(sink).catch(() => {});   // the speakers' names are known now, too
  })();
  try { await micOpening; } finally { micOpening = null; }
}
/* The browser evens out how loud the microphone is: a film across the room is turned up until it is as loud as the
   person at the keyboard. That helps writing words down, and it hides who is near. So the same microphone is listened to
   a second time with nothing done to its sound (except taking the PC's own sound out, exactly as on the first). Only how
   loud each moment was is taken from it: not a sample of it is kept or sent anywhere. Where the browser will not give
   such a listener, everything works as it did, on the first one alone. */
async function listenTruly(context, main) {
  const first = main.getAudioTracks()[0], had = first?.getSettings?.() || {}, name = plain(first?.label);
  if (!had.echoCancellation) return;
  // The browser gives a microphone one kind of listener at a time under one name. But the microphone Windows uses by
  // default is listed twice: as "the default" and under its own name. So the second listener asks for the same
  // microphone by its other name. (A microphone that is not the Windows default has only one name: no second listener.)
  const list = await devices().catch(() => null);
  const id = !had.deviceId || had.deviceId === 'default' ? list?.mics.find(m => m.name === name)?.id : list?.defaultMic === name ? 'default' : '';
  if (!id || !name) return;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, deviceId: { exact: id },
      echoCancellation: { exact: had.echoCancellation }, noiseSuppression: { exact: false }, autoGainControl: { exact: false } } });
  } catch { return; }
  const second = stream.getAudioTracks()[0], got = second?.getSettings?.() || {};
  if (micStream !== main || plain(second?.label) !== name || got.autoGainControl !== false || got.noiseSuppression !== false || got.echoCancellation !== had.echoCancellation) { stream.getTracks().forEach(t => t.stop()); return; }
  const node = new AudioWorkletNode(context, 'nova-mic'), silent = context.createGain(); silent.gain.value = 0;
  node.port.onmessage = e => { trueLevel = rms(e.data); trueAt = Date.now(); trueFrames.push([trueAt, e.data]); if (trueFrames.length > 700) trueFrames.shift(); };
  context.createMediaStreamSource(stream).connect(node); node.connect(silent).connect(context.destination);
  stream.getAudioTracks()[0]?.addEventListener('ended', () => { if (trueStream === stream) trueStream = null; });
  trueStream = stream;
}
function close() {
  micLevel = 0;
  try { micNode?.disconnect(); micStream?.getTracks().forEach(t => t.stop()); trueStream?.getTracks().forEach(t => t.stop()); micContext?.close().catch(() => {}); } catch {}
  micContext = micStream = micNode = trueStream = null; micName = ''; trueFrames.length = 0;
}
function micStop() { hearers.clear(); close(); }
async function reopen() {   // another microphone: the listeners stay, only the sound's source changes
  if (micOpening) { try { await micOpening; } catch {} }
  close();
  if (hearers.size) { try { await micStart(); } catch { hearers.clear(); } }
}
/* How loud the microphone was between two moments (one number per 20 ms). Only the last twelve seconds are kept. */
function levels(from, to) {
  const last = heardLevels.length - 1, end = Math.min(last, last - Math.round((heardAt - to) / FRAME_MS)), start = Math.max(0, last - Math.round((heardAt - from) / FRAME_MS));
  return end >= start ? heardLevels.slice(start, end + 1).map(v => Math.round(v * 1e5) / 1e5) : [];
}
/* Receive every 20 ms piece of sound (the piece, how loud it is, and how loud it really was where that is known).
   Returns a function that stops it. */
function hear(fn) { hearers.add(fn); return () => hearers.delete(fn); }

/* ---------- when is someone speaking? ----------
   Follows the room's background sound and reports the start and the end of each thing said.
   onPause lets the caller begin transcribing during a short gap, so the answer is ready sooner.

   A quiet room: a sentence starts when the sound rises well above the room's hum and ends after a moment of quiet.
   A room with other sound in it (a film on another device, people talking, music): quiet never comes, so waiting for
   it would mean waiting until the film pauses. There the question is who is speaking. Someone talking to JARVIS is
   nearer the microphone than the film is, so their voice stands above what the room itself reaches. The sentence starts
   when the sound rises well above the room's louder moments, and it ends when the sound is back to being the room's:
   no quiet needed. If no end can be found (the room is as loud as the person), the sentence is ended after a few
   seconds anyway and the caller is told so (`forced`), instead of waiting for half a minute.

   Two loudnesses arrive with each piece: the one of the sound itself (evened out by the browser: what will be written
   down), and, where there is one, the untouched microphone's (`real`). Who is near can only be told from the second:
   the browser turns a far-off film up until it is as loud as a person. So the room and the person are compared on the
   untouched scale whenever it is there; whether there is any sound worth judging stays with the first, as before. */
function join(frames) { const all = new Int16Array(frames.length * 320); frames.forEach((f, i) => all.set(f, i * 320)); return all; }
/* ---------- the near voice only ----------
   Over a film, speech-to-text often writes down the film's line instead of the person's. Measured with the app's own
   service on thirteen recordings of a person 6 to 15 dB louder than a film: the words were right for three of them with
   the browser's evened-out sound, and for nine with this. So for what is said over other sound, the untouched
   microphone's sound is what is sent: the near voice whole from its first moment to its last (the short dips between
   words included), everything before, after and in a real pause turned down to a tenth, and the whole made as loud as it
   can be without distorting. (Kept in memory for fourteen seconds, and sent only as part of such a sentence.) */
const trueFrames = [];   // [when it arrived, the piece] from the untouched listener
function untouched(from, to) { const found = []; for (const entry of trueFrames) if (entry[0] >= from && entry[0] <= to) found.push(entry); return found; }
// pieces: [when, piece] of the untouched sound. marks: [when, 1 or 0] for each piece of the first listener: was the near
// voice sounding at that moment.
// how: { before, after: pieces kept whole on either side of the near voice; rest: how much of everything else is left;
//        bridge: a dip between words this many pieces long or shorter is part of the sentence (0: each piece on its own);
//        trim: leave out what comes before the first and after the last of the near voice altogether }
// (Compared on thirteen recordings of a person speaking over a film, through the app's own speech-to-text: the words
//  came out right for three with the browser's own sound, for eight with each piece judged on its own, for nine so.)
const SHAPE = { before: 5, after: 6, rest: 0.1, bridge: 15, trim: false };
function nearOnly(pieces, marks, how) {
  const n = pieces.length; if (!n || !marks.length) return null;
  const { before, after, rest, bridge, trim } = { ...SHAPE, ...how };
  const near = new Uint8Array(n), wide = new Uint8Array(n);
  // (what came before the first mark is what was kept from just before the sentence began: not the near voice)
  for (let i = 0, k = 0; i < n; i++) { while (k < marks.length - 1 && marks[k][0] < pieces[i][0]) k++; near[i] = pieces[i][0] < marks[0][0] - 25 ? 0 : marks[k][1]; }
  let first = -1, last = -1;
  for (let i = 0; i < n; i++) if (near[i]) { if (first < 0) first = i; if (last >= 0 && i - last <= bridge) for (let j = last; j < i; j++) near[j] = 1; last = i; }
  if (first < 0) return null;
  // (a soft first sound, the "s" of "set", comes before the voice stands out)
  for (let i = 0; i < n; i++) if (near[i]) for (let j = Math.max(0, i - before); j <= Math.min(n - 1, i + after); j++) wide[j] = 1;
  const from = trim ? Math.max(0, first - before - 2) : 0, to = trim ? Math.min(n, last + after + 6) : n;
  const shaped = new Float32Array((to - from) * 320); let gain = wide[from] ? 1 : rest, top = 1;
  for (let i = from; i < to; i++) {
    const want = wide[i] ? 1 : rest, piece = pieces[i][1], at = (i - from) * 320;
    for (let j = 0; j < 320; j++) {
      gain += (want - gain) * (want > gain ? 0.05 : 0.004);                  // up within a millisecond or two, down over twenty: no clicks
      const value = piece[j] * gain; shaped[at + j] = value; if (value > top) top = value; else if (-value > top) top = -value;
    }
  }
  const scale = Math.min(20, 0.9 * 32767 / top), sound = new Int16Array(shaped.length);
  for (let i = 0; i < shaped.length; i++) sound[i] = shaped[i] * scale;
  return sound;
}

/* What the room sounds like while nobody is speaking to JARVIS: how loud each piece of the last few seconds was. One
   memory for all the detectors (only one of them is listening at any moment), so that one which starts in the middle of
   things, the listener for your next sentence after JARVIS has answered, say, knows the room from its first moment.
   levels: on the scale the room is measured by (truly: the untouched microphone's); heard: as the browser hands it on. */
const theRoom = { levels: [], heard: [], truly: false, at: 0, noise: 0, still: 0, last: null };   // last: the sentence heard most recently
// What was just heard turned out not to be meant for JARVIS (people talking to each other, a line of a film): it is part
// of what the room sounds like, so the next thing has to stand out from it.
function overheard() {
  const last = theRoom.last; theRoom.last = null;
  if (!last || Date.now() - last.at > 20000 || (theRoom.levels.length && theRoom.truly !== last.truly)) return;
  theRoom.truly = last.truly;
  for (let i = 0; i < last.levels.length; i++) { theRoom.levels.push(last.levels[i]); theRoom.heard.push(last.heard[i]); }
  while (theRoom.levels.length > 200) { theRoom.levels.shift(); theRoom.heard.shift(); }
}
function detector(o) {
  const set = { start: 3, endMs: 650, pauseMs: 300, preMs: 300, minMs: 240, maxMs: 30000, floor: 0.011, factor: 3.2,
    roomMs: 4000, lift: 2.3, busyMaxMs: 9000, steadyMs: 4000, longMs: 12000, faintBelow: 0, memory: theRoom, ...o };
  const R = set.memory;
  let noise = 0.004, peak = 0, warm = 0, talking = false, run = 0, quiet = 0, voiced = 0, pre = [], frames = [], began = 0, fedAt = 0;
  const recent = [], lows = [];
  // From the room's memory: the level the room usually has (mid) and the level its louder moments reach (high).
  // busy: something is sounding in it.
  const said = [], saidHeard = [], last = [];   // said: how loud each piece of the sentence was; last: was each of its newest ten pieces the person's
  const marks = [];                              // for a sentence said over other sound: [when, was that piece the near voice]
  const preReal = []; let before = [];           // how loud it really was just before the sentence began
  // The sentence so far (its first `keep` pieces). Said over other sound: the near voice only, from the untouched sound.
  const soundOf = keep => {
    if (noisy && truly && marks.length) {
      const pieces = (set.truth || untouched)(began - 30, began + keep * FRAME_MS + 30), shaped = pieces.length >= keep * 0.6 ? nearOnly(pieces, marks, set.shape) : null;
      if (shaped) return shaped;
    }
    return join(frames.slice(0, keep));
  };
  let mid = 0, high = 0, busy = false, counted = 0, noisy = false, forced = false, voice = 0, hum = 0, steady = 0;
  let truly = false, still = 0.004, kept = 0, lost = 0, settled = false, other = 0;   // truly: this sentence is being measured on the untouched microphone's scale; still: the room's quietest, there
  const forget = () => { R.levels.length = 0; R.heard.length = 0; R.noise = R.still = 0; };
  const measure = () => {
    const sorted = R.levels.slice().sort((a, b) => a - b), n = sorted.length;
    mid = sorted[Math.floor(n * 0.5)] || 0; high = sorted[Math.floor(n * 0.9)] || 0;
    let over = 0; for (let i = 0; i < n; i++) if (R.heard[i] > set.floor) over++;
    busy = n >= 50 && over / n >= 0.3;    // a third of the last seconds was louder than a voice would need to be in a silent room
  };
  const quietly = () => { talking = false; run = 0; quiet = 0; voiced = 0; frames = []; said.length = 0; saidHeard.length = 0; last.length = 0; noisy = false; forced = false; };
  // Is this "sentence" really one person speaking in a quiet room? Speech keeps dropping back to the room's hum, between
  // words and phrases: a tenth of it is as quiet as the room. Sound whose quietest tenth is still a good part of its
  // usual level has no such drops: something is playing (a film, music, a room full of people).
  // (Measured in the app's own window, on the untouched microphone: a film's quietest tenth is 0.4 to 0.6 of its usual
  // level, a person's in a quiet room 0.05 or less. hum is 0 when the sentence began before the room was known, a film
  // already playing as listening starts, say: then there is no hum to allow for, and the bar is a little higher.)
  const playing = () => {
    const sorted = said.slice(-200).sort((a, b) => a - b), n = sorted.length;
    return n >= 200 && sorted[Math.floor(n * 0.1)] > Math.max(hum * 1.5, sorted[Math.floor(n * 0.5)] * (hum ? 0.22 : 0.3));
  };
  // This detector has not been listening for a while (another one was, or nobody): half a sentence it may still hold is
  // dropped, and what the room sounds like is taken from the memory (itself out of date if nobody has listened since).
  const catchUp = (now, have) => {
    if (fedAt && talking) quietly();
    if (now - R.at > 1500) forget();
    run = 0; pre = []; recent.length = 0; lows.length = 0; counted = 0;
    if (R.levels.length) { truly = R.truly; if (R.noise) noise = R.noise; if (R.still) still = R.still; } else truly = have;
    other = 0; measure();
  };
  const feed = (frame, level, real) => {
    const now = Date.now(), have = real !== undefined && real !== null && real >= 0;
    if (now - fedAt > 1500) catchUp(now, have);
    fedAt = R.at = now;
    // Which loudness the room is measured by. It changes only after half a second of the other kind (a hiccup of the
    // untouched listener is not its end), and never in the middle of a sentence: the two are on different scales.
    other = have === truly ? 0 : other + 1;
    if (!talking) {
      // (The untouched listener arriving is taken up at once: a sentence must not begin on the browser's scale while it
      //  is there. Its going away is only believed after half a second.)
      if (other >= (have ? 1 : 25)) { truly = have; other = 0; lows.length = 0; still = have ? real : noise; run = 0; }
      if (R.levels.length && R.truly !== truly) { forget(); measure(); }
      R.truly = truly;
    }
    const actual = truly ? (have ? (kept = real) : kept) : level;
    // (The untouched listener went away in the middle of a sentence said over other sound: its end cannot be found now.)
    if (truly && talking && noisy && !have) { if (++lost > 25) { forced = true; finish(); return; } } else lost = 0;
    // The quietest moment of the last second and a half is the room itself (a fan, a hum, an open window).
    recent.push(level); if (recent.length > 75) recent.shift();
    let low = level; for (let i = 0; i < recent.length; i++) if (recent[i] < low) low = recent[i];
    noise += (low - noise) * (low < noise ? 0.3 : talking ? 0.01 : 0.05);
    const base = Math.max(set.floor, noise * set.factor);
    let around = base;                                                       // the same, on the scale the room is measured by
    if (truly) {
      lows.push(actual); if (lows.length > 75) lows.shift();
      let least = actual; for (let i = 0; i < lows.length; i++) if (lows[i] < least) least = lows[i];
      still += (least - still) * (least < still ? 0.3 : talking ? 0.01 : 0.05);
      around = still * set.factor;
    }
    if (!talking) {
      R.levels.push(actual); R.heard.push(level); R.noise = noise; R.still = truly ? still : 0;
      if (R.levels.length > set.roomMs / FRAME_MS) { R.levels.shift(); R.heard.shift(); }
      if (++counted % 10 === 0) measure();
      pre.push(frame); if (pre.length > Math.max(set.preMs, 500) / FRAME_MS) pre.shift();
      preReal.push(actual); if (preReal.length > 25) preReal.shift();
      if (warm < 15) { warm++; return; }                                     // settle on the room's sound before judging anything
      const limit = busy ? Math.max(around, high * 1.25, mid * set.lift) : base;
      // Where only the browser's evened-out loudness is known, nobody can be told from the room by how loud they are
      // (measured: a film's lines arrive as loud as the person). Over other sound nothing begins by itself there
      // unless the caller says to guess: it has no other way to hear JARVIS's name, or you have just pressed Talk.
      const may = !busy || truly || (typeof set.guess === 'function' ? set.guess() : set.guess !== false);
      run = may && (busy ? actual : level) > limit ? run + 1 : 0;
      if (run >= (busy ? Math.max(set.start, 5) : set.start)) {
        // (Over other sound a little more of what came just before is kept: the two listeners are not exactly in step.)
        frames = pre.slice(-Math.round((busy && truly ? 500 : set.preMs) / FRAME_MS)); pre = [];
        talking = true; noisy = busy; forced = false; quiet = 0; peak = level; voiced = run * FRAME_MS; began = now - frames.length * FRAME_MS;
        voice = actual; hum = R.levels.length < 50 ? 0 : truly ? still : noise; steady = 0; said.length = 0; saidHeard.length = 0; last.length = 0; for (let i = 0; i < run; i++) last.push(1);
        marks.length = 0; for (let i = run - 1; i >= 0; i--) marks.push([now - i * FRAME_MS, 1]);
        before = preReal.slice(0, Math.max(0, preReal.length - run)); preReal.length = 0;
        R.levels.length = Math.max(0, R.levels.length - run); R.heard.length = R.levels.length;   // (those first pieces were the person, not the room)
        set.onStart?.();
      }
      return;
    }
    frames.push(frame); peak = Math.max(peak * 0.999, level);
    said.push(actual); saidHeard.push(level); if (said.length > 500) { said.shift(); saidHeard.shift(); }
    let loud;
    if (noisy) {
      // The person's: well above what the room reaches, and not far below their own voice. (What the room reaches was
      // measured before they spoke, and the microphone turns itself down while someone speaks: so the room never
      // counts for more than a good part of the voice itself.)
      const mine = actual > Math.max(truly ? 0 : set.floor, Math.min(around, voice * 0.75), truly ? Math.min(Math.max(high * 1.15, Math.sqrt(high * voice)), voice * 0.7) : Math.min(high * 1.15, voice * 0.6), voice * 0.4);
      if (mine) voice += (actual - voice) * 0.08;
      marks.push([now, mine ? 1 : 0]);
      last.push(mine ? 1 : 0); if (last.length > 10) last.shift();
      let sum = 0; for (let i = 0; i < last.length; i++) sum += last[i];
      loud = sum >= 5;                                                       // one loud moment of the film does not make it the person again
      if (loud && mine) voiced += FRAME_MS;
    } else {
      const limit = Math.min(base, Math.max(set.floor, peak * 0.3));         // a long sentence must not talk itself into silence
      loud = level > limit;
      if (loud) voiced += FRAME_MS;
      // After a few seconds, and every half second from then on: is this still a person speaking, or has something
      // started playing? If it has, the "sentence" is ended here and is what the room sounds like from now on.
      if (++steady % 25 === 0 && frames.length * FRAME_MS >= set.steadyMs && playing()) { noisy = forced = true; finish(); return; }
    }
    if (loud) { if (quiet >= 200) set.onResume?.(); quiet = 0; } else quiet += FRAME_MS;
    if (quiet >= set.endMs) finish();
    else if (frames.length * FRAME_MS >= (noisy ? Math.min(set.maxMs, set.busyMaxMs) : set.maxMs)) { forced = noisy; finish(); }
    // Where only the browser's evened-out loudness is known, a film cannot be told from a person by its quiet moments
    // (the browser hollows them out). There, a "sentence" that has gone on this long without one pause is handed on as
    // it is, and what it sounded like is the room from now on: the next thing has to stand out from it.
    else if (!noisy && !truly && frames.length * FRAME_MS >= set.longMs) { settled = true; finish(); }
    else if (quiet === set.pauseMs && voiced >= set.minMs) set.onPause?.(() => soundOf(frames.length), { start: began, end: Date.now() - quiet, noisy });
  };
  function finish() {
    if (!talking) return;
    const keep = frames.length - Math.max(0, quiet / FRAME_MS - (noisy && truly ? 25 : 10)), spoken = voiced;   // (over other sound a soft last word may not have stood out: more of the end is kept)
    // near: said over other sound by someone plainly nearer the microphone than it (nearly twice what the room reaches).
    // Someone speaking near the microphone in a room without other sound stands far above what surrounds the sentence
    // (the moments just before it and the pause that ended it). A line of a film on another device ends in the film's
    // own music and murmur: it stands only a little above them. Such a sentence is most likely the room (measured on
    // the untouched microphone: a film's line about three times its surroundings, a person forty times).
    let faint = false;
    if (set.faintBelow && truly && !noisy && !forced && !settled) {
      const gone = Math.min(said.length, Math.round(quiet / FRAME_MS)), around = before.concat(said.slice(said.length - gone)).sort((a, b) => a - b);
      const body = said.slice(0, said.length - gone).sort((a, b) => a - b);
      faint = around.length >= 15 && body.length >= 10 && body[Math.floor(body.length * 0.5)] < around[Math.floor(around.length * 0.5)] * set.faintBelow;
    }
    const sound = soundOf(keep), when = { faint, start: began, end: Date.now() - Math.max(0, quiet - 200), noisy, forced, near: noisy && truly && high > 0 && voice >= high * 1.8 };
    // A sentence for which no end was found was most likely the room itself getting louder. That is what the room
    // sounds like from now on, so it does not start another "sentence" straight away.
    if (forced || settled || faint) {
      settled = false; R.levels.length = 0; R.heard.length = 0; R.truly = truly; counted = 9;
      for (let i = Math.max(0, said.length - 150); i < said.length; i++) { R.levels.push(said[i]); R.heard.push(saidHeard[i]); }
    }
    R.last = { at: Date.now(), truly, levels: said.slice(-150), heard: saidHeard.slice(-150) };
    quietly();
    if (spoken >= set.minMs) set.onEnd?.(sound, spoken, when); else set.onDrop?.();
  }
  feed.finish = () => { if (talking && quiet >= set.pauseMs) finish(); };   // the caller already knows the sentence is complete
  feed.talking = () => talking;
  // Take over a sentence another detector was already hearing (you began speaking just before pressing the button), or
  // one that began with JARVIS's name (the name is then how loud this person's voice is).
  // reals: how loud each of those pieces really was (the untouched microphone), where that is known for all of them.
  feed.prime = (sound, reals) => {
    const now = Date.now();
    frames = []; const levels = [];
    for (let i = 0; i + 320 <= sound.length; i += 320) { const piece = sound.subarray(i, i + 320); frames.push(piece); levels.push(rms(piece)); }
    const real = reals && frames.length && reals.length >= frames.length ? reals.slice(reals.length - frames.length) : null;
    const felt = real && real.every(v => v >= 0) ? real : levels, sorted = felt.slice().sort((a, b) => a - b);
    if (now - R.at > 1500) forget();
    if (R.noise) noise = R.noise;
    truly = felt === real; measure();                                       // what the room sounds like, from the memory
    if (R.levels.length && R.truly !== truly) mid = high = 0;               // (measured on the other scale: no use comparing with it)
    still = truly ? (R.truly && R.still) || sorted[Math.floor(sorted.length * 0.05)] || 0.004 : noise;
    kept = felt[felt.length - 1] || 0; lost = 0; lows.length = 0; fedAt = R.at = now;
    talking = true; warm = 15; quiet = 0; voiced = Math.max(set.minMs, frames.length * FRAME_MS / 2); peak = 0.1; began = now - frames.length * FRAME_MS;
    noisy = busy; forced = false; hum = R.levels.length < 50 ? 0 : truly ? still : noise; steady = 0; said.length = 0; saidHeard.length = 0;
    for (let i = 0; i < levels.length; i++) { said.push(felt[i]); saidHeard.push(levels[i]); }
    last.length = 0; for (let i = 0; i < 10; i++) last.push(1);
    voice = sorted[Math.floor(sorted.length * 0.7)] || 0.05;
    // Which of these pieces were the near voice: the name is the loudest of them, and what the room reaches is known.
    // (Part of them is the room from just before the name: a film's louder moment must not count as the voice.)
    const top = sorted[Math.floor(sorted.length * 0.9)] || voice, limit = Math.max(high * 1.3, top * 0.35);
    marks.length = 0; for (let i = 0; i < felt.length; i++) marks.push([began + (i + 1) * FRAME_MS, felt[i] > limit ? 1 : 0]);
  };
  feed.reset = () => { quietly(); warm = 0; pre = []; };
  feed.sofar = () => soundOf(frames.length);
  // Is what is being said now plainly by someone nearer the microphone than the room's other sound?
  feed.near = () => talking && noisy && truly && high > 0 && voice >= high * 1.8;
  // What the room sounds like right now (n: how many pieces that is known from; truly: on the untouched microphone's scale).
  feed.room = () => ({ busy, mid, high, noise, hush: still, truly, n: R.levels.length, noisy: talking && noisy });
  return feed;
}

/* ---------- playing JARVIS's voice ---------- */
function output() {
  if (!out) {
    try { out = new AudioContext(outId ? { latencyHint: 'interactive', sinkId: outId } : { latencyHint: 'interactive' }); sinkNow = outId; }
    catch { out = new AudioContext({ latencyHint: 'interactive' }); sinkNow = ''; }
    if (outId !== sinkNow) sink();
    meter = out.createAnalyser(); meter.fftSize = 512; meterData = new Float32Array(meter.fftSize);
    meter.connect(out.destination);
  }
  if (out.state === 'suspended' && !held) out.resume().catch(() => {});
  return out;
}
function schedule(buffer) {
  const context = output(), source = context.createBufferSource();
  // Each stretch of speech has its own volume control, so cutting one off can never silence the next.
  if (!line) { line = context.createGain(); line.connect(meter); }
  source.buffer = buffer; source.connect(line);
  const at = Math.max(context.currentTime + 0.04, queueEnd);
  source.start(at); queueEnd = at + buffer.duration;
  playing.add(source);
  // Told by the sound itself when the last piece has played, so this works even while the window is covered or minimised.
  source.onended = () => { playing.delete(source); if (!playing.size && whenQuiet) whenQuiet(); };
}
/* Raw 16-bit sound as it arrives. Pieces may end in the middle of a sample; the odd byte is kept for the next piece. */
function pcm(bytes, rate) {
  if (carry) { const merged = new Uint8Array(carry.length + bytes.length); merged.set(carry); merged.set(bytes, carry.length); bytes = merged; carry = null; }
  if (bytes.length % 2) { carry = bytes.slice(bytes.length - 1); bytes = bytes.subarray(0, bytes.length - 1); }
  if (!bytes.length) return;
  const samples = new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length)), buffer = output().createBuffer(1, samples.length, rate), channel = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 32768;
  schedule(buffer);
}
async function encoded(bytes) { carry = null; schedule(await output().decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length))); }
/* Fall silent at once, mid-word, without losing the place (someone has started to talk over it); or carry on from there. */
function hold(on) {
  held = !!on; if (!out) return;
  if (!held && line) { const now = out.currentTime; line.gain.cancelScheduledValues(now); line.gain.setTargetAtTime(1, now, 0.03); }
  if (held && out.state === 'running') out.suspend().catch(() => {});
  else if (!held && out.state === 'suspended') out.resume().catch(() => {});
}
function hush() {
  hold(false);
  carry = null; queueEnd = 0;
  const old = line, stopping = [...playing]; line = null; playing.clear();
  if (!out || !old) return;
  const now = out.currentTime;
  old.gain.setValueAtTime(old.gain.value, now); old.gain.linearRampToValueAtTime(0, now + 0.03);   // a quick fade, so stopping does not click
  setTimeout(() => { stopping.forEach(s => { try { s.stop(); } catch {} }); try { old.disconnect(); } catch {} }, 80);
}
/* Lower (or restore) the voice without stopping it, for the moment someone starts talking over it. */
function duck(to) { if (to >= 1) hold(false); if (!out || !line) return; const now = out.currentTime; line.gain.cancelScheduledValues(now); line.gain.setTargetAtTime(to, now, 0.03); }
function speaking() { return !!out && (playing.size > 0 || queueEnd > out.currentTime + 0.02); }
function remaining() { return out ? Math.max(0, queueEnd - out.currentTime) : 0; }
function loudness() {
  if (!meter || !speaking()) return 0;
  meter.getFloatTimeDomainData(meterData); let sum = 0; for (let i = 0; i < meterData.length; i++) sum += meterData[i] * meterData[i];
  return Math.sqrt(sum / meterData.length);
}

/* ---------- soft sounds ---------- */
const TONES = { listen: [[660, 0, 0.09], [880, 0.08, 0.12]], heard: [[880, 0, 0.07], [660, 0.07, 0.1]], notice: [[784, 0, 0.14], [1047, 0.14, 0.14], [1319, 0.28, 0.22]], error: [[330, 0, 0.16], [262, 0.14, 0.22]] };
function chime(name) {
  const notes = TONES[name]; if (!notes) return;
  const context = output(), start = context.currentTime + 0.02, volume = context.createGain(); volume.gain.value = 0.07; volume.connect(context.destination);
  for (const [pitch, at, length] of notes) {
    const tone = context.createOscillator(), shape = context.createGain(); tone.type = 'sine'; tone.frequency.value = pitch;
    shape.gain.setValueAtTime(0, start + at); shape.gain.linearRampToValueAtTime(1, start + at + 0.015); shape.gain.exponentialRampToValueAtTime(0.001, start + at + length);
    tone.connect(shape).connect(volume); tone.start(start + at); tone.stop(start + at + length + 0.02);
  }
}

window.NovaAudio = { RATE, micStart, micStop, hear, detector, join, pcm, encoded, hush, duck, hold, speaking, remaining, loudness, chime, unlock: output,
  get echoAll() { return echoAll; }, get held() { return held; },
  onQuiet: fn => { whenQuiet = fn; }, devices, use, plain, levels, overheard, nearOnly, get truly() { return !!trueStream; },
  get micLevel() { return micLevel; }, get micOn() { return !!micNode; }, get micName() { return micName; },
  get micMuted() { return !!micStream?.getAudioTracks()[0]?.muted; },
  get speakerChosen() { return !!outId; } };   // true while JARVIS's sound is being sent to speakers other than the Windows default
})();
