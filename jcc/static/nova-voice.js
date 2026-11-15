/* NOVA voice: talk to JARVIS and hear it answer. The same fast assistant also answers typed messages.
   Listening uses Whisper, ElevenLabs live transcription or the browser, whichever is available;
   speaking uses ElevenLabs or the browser's voices. The 3D core moves with the real sound. */
(() => {
'use strict';
const N = window.Nova, A = window.NovaAudio; if (!N || !A) return;
const { icon, el, notify, dialog, store } = N, body = document.body;
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const DIRECT = document.querySelector('meta[name="jcc-direct"]')?.content !== '0';   // opened by you, not by a link on some website
// The small "listening" window: shown in a corner while another program is in use (jcc/mini.py). Same page, small layout.
const MINI = DIRECT && new URLSearchParams(location.search).has('mini'), KIND = MINI ? 'mini' : 'main';
// (A second JARVIS on this PC, on another port, names its small window after the port: see jcc/mini.py.)
if (MINI) { document.title = 'JARVIS \u00b7 Listening' + (location.port && location.port !== '8765' ? ' \u00b7 ' + location.port : ''); body.classList.add('nv-mini'); }
const SHIELD = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 4.6-3.2 8-8 9-4.8-1-8-4.4-8-9V6z"/><path d="M9 12l2.2 2.2L15 10"/></svg>';
let options = { model: 'haiku', speak: true, hands_free: true, ask: 'sending', pc_control: true, persona: '', light: 'auto', assistant: { id: 'jarvis', name: 'JARVIS', voice_id: '' } };
let speech = { listen: Recognition ? 'browser' : '', speak: 'browser', configured: false, whisper: '', keys: {}, pcm_rate: 24000, socket: '', languages: {}, models: {},
  settings: { wake: false, barge_in: true, sounds: true, language: 'en', listen: 'auto', speak: 'auto', words: '', speed: 1, voice_id: '', tts_model: '', stt_model: '' } };
let since = -1, voiceMode = false, phase = 'idle', muted = false, expecting = false, confirmOpen = null, wantListen = false, dictating = false;
let capture = null, engineDown = {}, restTimer = 0, restBy = 0, level = 0, kick = 0, raf = 0, wasSpeaking = false, lastSpoken = '';
const turns = new Map(); let focus = null;   // focus: the turn whose reply is captioned and spoken

const chime = name => { if (speech.settings.sounds) try { A.chime(name); } catch {} };
const words = text => (text.toLowerCase().match(/[a-z0-9']+/g) || []);
async function post(path, bytes) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-JCC-Token': TOKEN }, body: bytes });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const problem = new Error(data.error || 'That did not work. Try again.'); problem.busy = !!data.busy; throw problem; }
  return data;
}
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
// Windows has the microphone muted: said once a minute at most, with what to do about it.
let mutedSaidAt = 0;
window.addEventListener('nova-mic-muted', e => {
  speech.mic_muted = !!e.detail;
  if (e.detail && Date.now() - mutedSaidAt > 60000) {
    mutedSaidAt = Date.now();
    notify('Windows has the microphone muted, so JARVIS hears nothing. Unmute it with your microphone key, or press Unmute in Settings, Voice.');
  }
});
async function loadSpeech() {
  try { speech = { ...speech, ...(await api('/api/speech')) }; } catch {}
  await A.use(speech.settings.mic || '', speech.settings.speaker || '').catch(() => {});   // the microphone and speakers chosen in the settings
  return speech;
}
function engine() {   // how JARVIS listens right now, after stepping down from anything that failed
  const order = { whisper: ['whisper', 'browser'], eleven: ['eleven', 'whisper', 'browser'], browser: ['browser'] }[speech.listen || 'browser'] || ['browser'];
  return order.find(name => !(engineDown[name] > Date.now()) && (name === 'browser' ? !!Recognition : name === 'whisper' ? !!speech.whisper : speech.configured)) || '';
}

/* ---------- the voice screen ---------- */
const captions = el('div', { id: 'nv-captions', 'aria-live': 'polite' },
  '<p class="state"><i></i><span></span></p><p class="you"></p><p class="me"></p><p class="nv-hint"></p><div class="nv-voice-keys"></div>');
document.querySelector('.composer-wrap').before(captions);
const capState = captions.querySelector('.state span'), capYou = captions.querySelector('.you'), capMe = captions.querySelector('.me'), capHint = captions.querySelector('.nv-hint');
const keys = captions.querySelector('.nv-voice-keys');
const key = (name, label, tip, shortcut) => el('button', { class: 'plain', type: 'button', data: shortcut ? { tip, key: shortcut } : { tip } }, icon(name) + '<span>' + label + '</span>');
const talkB = key('mic', 'Talk', 'Start speaking to JARVIS', 'Space'), muteB = key('mic', 'Mute', 'Stop JARVIS hearing you for a moment'), holdB = key('stop', 'Stop', 'Stop JARVIS talking or working', 'Esc');
const typeB = key('keys', 'Type', 'Type a message instead of speaking'), leaveB = key('x', 'End', 'Leave voice chat and go back to typing');
keys.append(talkB, muteB, holdB, typeB, leaveB);
const hint = text => { capHint.textContent = text || ''; };
const TRY = ['Try: “Open Notepad”', 'Try: “Set a timer for ten minutes”', 'Try: “What is on my screen?”', 'Try: “Search YouTube for lo-fi music”', 'Try: “Remind me to stretch in an hour”', 'Try: “Make a website for my bakery”'];
function setPhase(next, label) {
  phase = next;
  body.classList.toggle('nv-listening', next === 'listening'); body.classList.toggle('nv-thinking', next === 'thinking');
  captions.dataset.phase = next;
  capState.textContent = label || { idle: muted ? 'Microphone muted' : 'Tap the microphone, or press Space, and speak', listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking…' }[next];
  window.NovaCore?.set({ energy: next === 'listening' ? 0.55 : next === 'thinking' ? 0.9 : next === 'speaking' ? 0.7 : 0.25 });
  tellPresence();
  animate();
}

/* The service is told whether a spoken conversation is going on, so the wake word never cuts into one or answers JARVIS's own voice. */
let toldPhase = '', toldAt = 0;
const WINDOW = Math.random().toString(36).slice(2, 12);   // this window's name for the app, so it knows at once when the window has gone
function tellPresence() {
  const now = voiceMode ? phase : 'idle';
  if (now === toldPhase && Date.now() - toldAt < 4000) return;
  toldPhase = now; toldAt = Date.now(); api('/api/voice', { action: 'presence', phase: now, w: WINDOW, kind: KIND }).catch(() => {});
}
addEventListener('pagehide', () => {   // closing: say so, or "Hey JARVIS" would be taken for part of a conversation that is over
  try { fetch('/api/voice', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN }, body: JSON.stringify({ action: 'presence', phase: 'idle', w: WINDOW, kind: KIND, gone: true }) }); } catch {}
});
setInterval(() => { if (voiceMode && phase !== 'idle') tellPresence(); }, 5000);
// Waiting to hear its name in this window (when the background helper is not running). The app is told, so it keeps track
// of what the PC itself is playing: a film that says "JARVIS" is then not taken for you.
function tellWaiting() {
  if (!voiceMode && wakeWanted() && engine() === 'whisper' && A.micOn) api('/api/voice', { action: 'presence', phase: 'idle', w: WINDOW, kind: KIND, wake: true }).catch(() => {});
}
setInterval(tellWaiting, 20000);

/* ---------- speaking ---------- */
function speakable(text) {
  // (A list of sources under an answer is for reading, not for saying. Nor is the name written above something it made.)
  return text.replace(/^[ \t]*(?:\*\*)?File(?:\*\*)?:[^\n]*$/gim, '').replace(/\n\s*(?:\*\*|#{1,4}\s*)?Sources:?(?:\*\*)?\s*\n[\s\S]*$/i, '').replace(/```[\s\S]*?(```|$)/g, ' I have put the code in the chat. ').replace(/!\[[^\]]*\]\([^)]*\)/g, ' ').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\[\[([^\]|]+)(\|([^\]]+))?\]\]/g, (_, a, b, c) => c || a).replace(/https?:\/\/\S+/g, ' a link ').replace(/[*_#>`|]+/g, ' ').replace(/\s+/g, ' ').trim();
}
function pickVoice() {
  const voices = speechSynthesis.getVoices(), wanted = store.get('nv-voice-name', '');
  const lang = (navigator.language || 'en-US').toLowerCase(), base = lang.split('-')[0];
  return voices.find(v => v.name === wanted) || voices.find(v => /natural/i.test(v.name) && v.lang.toLowerCase() === lang) ||
    voices.find(v => /natural/i.test(v.name) && v.lang.toLowerCase().startsWith(base)) || voices.find(v => v.lang.toLowerCase() === lang) ||
    voices.find(v => v.lang.toLowerCase().startsWith(base)) || voices[0] || null;
}
const speaker = (() => {
  let jobs = [], browserCount = 0, previous = '', warned = false, localDown = false;
  function browserSay(text) {
    if (!window.speechSynthesis) return;
    const utterance = new SpeechSynthesisUtterance(text), voice = pickVoice();
    if (voice) { utterance.voice = voice; utterance.lang = voice.lang; }
    utterance.rate = Number(store.get('nv-voice-rate', '1.05')) || 1.05;
    // If Windows never reports that it finished (no voice installed, sound device gone), carry on anyway after a sensible wait.
    let over = false;
    const done = () => { if (over) return; over = true; clearTimeout(guard); browserCount = Math.max(0, browserCount - 1); setTimeout(settle, 0); };
    const guard = setTimeout(done, Math.max(5000, text.length * 110 + 4000));
    utterance.onstart = () => { kick = 1; animate(); }; utterance.onboundary = () => { kick = 1; };
    utterance.onend = utterance.onerror = done;
    browserCount++; speechSynthesis.speak(utterance);
  }
  async function fetchSound(job) {
    try {
      const response = await fetch('/api/speech/tts', { method: 'POST', signal: job.cancel.signal, headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN },
        body: JSON.stringify(job.local ? { text: job.text, local: true } : { text: job.text, previous: job.previous, voice: options.assistant?.voice_id || '' }) });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || 'The voice service did not answer.');
      job.kind = (response.headers.get('Content-Type') || '').includes('mpeg') ? 'mp3' : 'pcm';
      const reader = response.body.getReader();
      for (;;) { const { done, value } = await reader.read(); if (done) break; job.pieces.push(value); play(); }
    } catch (error) { if (error.name !== 'AbortError') job.failed = error.message || 'failed'; }
    job.done = true; play(); startMore();
  }
  function startMore() { for (const job of jobs) { if (jobs.filter(j => j.started && !j.done).length >= 2) break; if (!job.started) { job.started = true; fetchSound(job); } } }
  function play() {   // strictly in sentence order, even though two sentences are fetched at once
    while (jobs.length) {
      const job = jobs[0];
      if (job.failed && !job.heard) {
        jobs.shift();
        if (job.local) { if (!localDown) { localDown = true; notify('The built-in voice could not be sent to the chosen speakers. It is playing on the Windows default for now.'); } }
        else if (!warned) { warned = true; notify(job.failed + ' Using the built-in voice for now.'); }
        // Chosen speakers stay chosen: the built-in voice is then made on this PC and played there too.
        if (!job.local && A.speakerChosen && !localDown) { jobs.unshift({ text: job.text, local: true, pieces: [], cancel: new AbortController() }); startMore(); continue; }
        browserSay(job.text); continue;
      }
      if (job.kind === 'pcm') while (job.pieces.length) { A.pcm(job.pieces.shift(), speech.pcm_rate); job.heard = true; }
      else if (job.kind === 'mp3' && job.done && !job.decoding) {
        const size = job.pieces.reduce((n, p) => n + p.length, 0), all = new Uint8Array(size); let at = 0;
        for (const piece of job.pieces) { all.set(piece, at); at += piece.length; }
        job.pieces = []; job.heard = true; job.decoding = A.encoded(all).catch(() => {}).then(() => { job.decoded = true; play(); });
      }
      if (!job.done || (job.decoding && !job.decoded)) return;
      jobs.shift();
    }
  }
  return {
    say(text) {
      const clean = speakable(text); if (!clean) return;
      lastSpoken = (lastSpoken + ' ' + clean).slice(-600); wasSpeaking = true;
      if (speech.speak === 'eleven' && !warned) { jobs.push({ text: clean, previous, pieces: [], cancel: new AbortController() }); previous = clean; startMore(); }
      // The voice built into the window can only play on the Windows default. For chosen speakers the sentence is made on this PC instead.
      else if (A.speakerChosen && !localDown) { jobs.push({ text: clean, local: true, pieces: [], cancel: new AbortController() }); startMore(); }
      else browserSay(clean);
      if (phase !== 'speaking' && voiceMode) setPhase('speaking');
      animate();
    },
    hush() { jobs.forEach(job => job.cancel.abort()); jobs = []; previous = ''; browserCount = 0; A.hush(); try { speechSynthesis.cancel(); } catch {} },
    // Silent at once, mid-word, keeping the place; or carrying on from there (a cough is not an interruption).
    hold(on) { A.hold(on); if (browserCount) { try { if (on) speechSynthesis.pause(); else speechSynthesis.resume(); } catch {} } },
    active: () => jobs.length > 0 || A.speaking() || browserCount > 0,
    natural: () => A.speaking() || jobs.length > 0,
    retry() { warned = false; localDown = false; },
  };
})();
// (The small window may be showing a conversation that the app window is holding: then that window speaks, not this one.)
const shouldSpeak = turn => options.speak && (voiceMode || turn?.spoken) && !(MINI && !voiceMode);
// JARVIS says a few words the moment it starts on something ("Opening Gmail."). What the AI says afterwards is spoken only
// when it adds to that: not "Opened Gmail." again, and not a bare "Done."
const BARE = /^(?:done|okay|ok|all set|all done|there you go|here you go|got it|sure|on it|it'?s (?:playing|open|opened|done|up|on|running)(?: now)?|(?:now )?playing(?: now)?|opened|open now)[.!]?$/i;
function addsNothing(turn, sentence) {
  if (!turn.lead) return false;
  const said = words(sentence); if (!said.length || BARE.test(sentence.trim())) return true;
  const lead = new Set(words(turn.lead));
  return said.filter(word => lead.has(word)).length / said.length >= 0.5;
}
function speakProgress(turn, final) {
  if (!shouldSpeak(turn)) return;
  const rest = turn.text.slice(turn.said);
  if (final) { if (rest.trim() && !addsNothing(turn, rest)) speaker.say(rest); turn.said = turn.text.length; return; }
  if ((rest.match(/```/g) || []).length % 2) return;
  // Speak whole sentences as soon as they are complete, so the voice starts before the reply ends.
  const match = rest.match(/^[\s\S]*?[.!?…](?=\s)|^[\s\S]*\n/) || (rest.length > 140 ? rest.match(/^[\s\S]{60,}?[,;:](?=\s)/) : null);
  if (match && match[0].trim().length > 2) { if (!addsNothing(turn, match[0])) speaker.say(match[0]); turn.said += match[0].length; }
}
function settle() { if (wasSpeaking && !speaker.active()) { wasSpeaking = false; afterSpeech(); } }
A.onQuiet(() => { settle(); setTimeout(settle, 80); });
let quietSince = 0;
function afterSpeech() {
  quietSince = Date.now();
  if (interrupting) return;
  if (capture?.mode === 'barge') { speaker.hold(false); return; }   // you are mid-sentence: let it finish and be handled
  if (leaving) return void leave();
  if (!voiceMode || confirmOpen && !wantListen) { if (!turns.size && phase === 'speaking') setPhase('idle'); return; }
  if (confirmOpen) { wantListen = false; listen('confirm'); return; }   // the task is waiting for this answer, so this comes before "still working"
  if (focus && turns.has(focus)) { setPhase('thinking'); return; }
  if (options.hands_free || wantListen) { wantListen = false; listen('command'); } else setPhase('idle');
}

/* ---------- the core moves with the real sound ---------- */
function animate() {
  if (raf) return;
  const step = now => {
    raf = 0;
    const talking = speaker.active();
    let target = 0;
    if (talking) {
      if (speaker.natural()) target = Math.min(1, 0.16 + A.loudness() * 3.4);
      else { kick *= 0.9; target = 0.3 + 0.32 * Math.abs(Math.sin(now / 83)) * (0.6 + 0.4 * Math.sin(now / 37)) + kick * 0.4; }
    } else if (phase === 'listening' || dictating) target = Math.min(1, A.micLevel * 8) * 0.8;
    level += (target - level) * (target > level ? 0.5 : 0.16);
    window.NovaCore?.voice?.(level);
    body.classList.toggle('nv-speaking', talking);
    settle();
    if (talking || phase === 'listening' || dictating || level > 0.01) raf = requestAnimationFrame(step); else window.NovaCore?.voice?.(0);
  };
  raf = requestAnimationFrame(step);
}

/* ---------- listening ---------- */
const YES = /\b(yes|yeah|yep|yup|ya|sure|ok|okay|alright|all right|fine|do it|go ahead|go on|go for it|please do|proceed|continue|carry on|approve|approved|allow|allowed|send it|confirm|confirmed|affirmative|correct|absolutely|definitely|of course|haan|han|ji|theek hai|kar do)\b/i;
const NO = /\b(no|nope|nah|not|stop|cancel|wait|never mind|deny|denied|reject|refuse|negative|nahi|nahin|mat)\b|n'?t\b/i;   // any doubt counts as no
const wakeWord = () => new RegExp('^\\W*(?:(?:hey|hi|ok|okay|hello|yo)[\\s,]+)?(?:jarvis|jarvice|jervis|javis|jarvas|' +
  String(options.assistant?.name || 'jarvis').toLowerCase().replace(/[^a-z0-9 ]/g, '') + ')\\b[\\s,.!?]*(.*)$', 'i');
function echoOfMe(text) {   // did the microphone just pick up JARVIS's own voice?
  const said = words(text), mine = new Set(words(lastSpoken));
  return said.length >= 3 && said.filter(word => mine.has(word)).length / said.length > 0.72;
}
const heardName = () => { const name = options.assistant?.name || ''; return /^jarvis$/i.test(name) ? '' : name; };
// Its name alone is not a request (it is also what Whisper tends to write for a noise in the room). In "Hey JARVIS, what
// time is it?" only the question matters; "Jarvis is a film character, right?" is left as it is.
function withoutName(text) {
  let rest = text, called, stripped = false;
  for (let i = 0; i < 3 && (called = rest.match(wakeWord())); i++) {
    const prefix = rest.slice(0, rest.length - called[1].length), after = called[1].trim();
    if (after.length < 2) return '';
    if (!/^\W*(?:hey|hi|ok|okay|hello|yo)\b/i.test(prefix) && !/[,.!?]\s*$/.test(prefix) && !wakeWord().test(after)) break;
    rest = after; stripped = true;
  }
  return stripped ? rest : text;
}
// Dictation, and waiting to hear its name: your words only, no name suggested. (A name Whisper has been told is also
// what it writes down for a noise, and a noise must never wake JARVIS or end up in what you dictate.)
// Nor for what is said over other sound: asked to expect "JARVIS", Whisper wrote it in front of a film's line (measured),
// and what begins with its name counts as said to JARVIS.
const sttPath = (mode, noisy) => '/api/speech/stt?' + (mode === 'dictate' || mode === 'wake' || noisy ? 'plain=1' : 'hint=' + encodeURIComponent(heardName()));
async function hear(sound, mode, noisy) {   // one retry if the speech service asks us to slow down
  for (let attempt = 0; ; attempt++) {
    try { return (await post(sttPath(mode, noisy), sound.buffer)).text || ''; }
    catch (error) { if (!error.busy || attempt) throw error; await pause(1500); }
  }
}
/* Was that the PC's own sound? A video, a film or music playing on this PC reaches the microphone like a voice does.
   The app knows how loud the PC's own sound was at each moment and compares (jcc/pcsound.py). The answer:
   pc: it was the PC, ignore it.  playing + heard: something is playing and the microphone can hear it, so only what is
   said to JARVIS by name counts until it stops. */
let ownVoiceAt = 0, toldPlaying = 0;
async function judge(mode, when) {
  if (!when || (mode === 'barge' && !overWork)) return null;      // (said over JARVIS's own voice: that is told apart by its words)
  const before = when.start - 3200 < ownVoiceAt ? [] : A.levels(when.start - 3000, when.start - 20);   // not while JARVIS's own (cancelled-out) voice was playing
  try { return await api('/api/voice', { action: 'echo', start: when.start, levels: A.levels(when.start, when.end), before }); }
  catch { return null; }
}
// While something is playing on the PC's speakers, only what is said to JARVIS by name counts.
function addressed(text, mode, room) {
  const said = (text || '').trim(), called = said.match(wakeWord());
  if (called) return mode === 'confirm' ? called[1].trim() : said;
  if ((said || room) && Date.now() - toldPlaying > 20000) {
    toldPlaying = Date.now();
    hint((room ? 'There is other sound in the room. ' : 'Something is playing on this PC. ') + 'Start with “' + (options.assistant?.name || 'JARVIS') + '” so I know you mean me.');
  }
  return '';
}
// The helper that listens for JARVIS's name all the time (it hears it over a film and across a room) is running. Then
// the window need not send the room's sound anywhere to find out whether its name was in it.
const helperHears = () => !!(speech.shortcuts && speech.shortcuts.wake && speech.shortcuts.wake_engine === 'neural');
// Other people are talking (JARVIS was not meant, twice within two minutes): for a while only what is said to it by name
// counts, so their conversation is neither sent anywhere nor answered.
let passedOver = [], nameOnlyUntil = 0;
function notForMe() {
  A.overheard();   // (and that is what the room sounds like: the next thing has to stand out from it)
  const now = Date.now(); passedOver = [...passedOver.filter(t => now - t < 120000), now];
  if (passedOver.length >= 2) { passedOver = []; nameOnlyUntil = now + 300000; }
}
function localCapture(mode, settings = {}) {   // Whisper: record what is said here, then have it transcribed
  let early = null, stamp = 0, tried = false;
  const transcribe = (sound, noisy) => post(sttPath(mode, noisy), sound.buffer).then(d => d.text || '').catch(() => null);
  // A finished sentence ends the turn after about half a second of quiet; an unfinished one ("set a timer for…") is given longer.
  const feed = A.detector({
    endMs: mode === 'dictate' ? 1100 : mode === 'confirm' ? 500 : 840, pauseMs: 240, maxMs: mode === 'dictate' ? 60000 : 30000, longMs: mode === 'dictate' ? 60000 : 12000,
    // Over other sound, without the untouched listener (see nova-audio.js): you are expected to speak (you pressed the
    // button, or JARVIS asked), or nothing else is listening for its name. Otherwise its name begins what you say.
    guess: () => mode === 'dictate' || mode === 'confirm' || startedByYou || !helperHears(), faintBelow: mode === 'command' ? 4 : 0, ...settings,
    onStart: () => { clearTimeout(restTimer); settings.onStart?.(); if (mode !== 'wake') { capYou.textContent = '…'; hint(''); } },
    // Start transcribing during the first pause, so the answer is ready sooner. Once per sentence, to stay well inside the service's limits.
    onPause: (sofar, when) => {
      if (tried) return; tried = true;
      const mine = ++stamp, sound = sofar();
      // First ask whether this is the PC's own sound; only a person's words are sent to be transcribed.
      const text = judge(mode, when).then(verdict => {
        if (!verdict || !verdict.pc) return transcribe(sound, when.noisy);
        if (stamp === mine && capture?.feed === feed) { feed.reset(); early = null; tried = false; capYou.textContent = ''; }
        return null;
      });
      early = { mine, text };
      if (mode === 'barge') text.then(said => {   // "stop", said over JARVIS: acted on now
        if (stamp !== mine || capture?.feed !== feed || !said || !STOP_NOW.test(said.trim())) return;
        feed.reset(); early = null; tried = false; capture = null; capYou.textContent = said.trim(); doUi('rest', '', true);
      });
      // (Not after its name alone: "Hey JARVIS…" is the start of a sentence, so wait for the rest.)
      if (mode !== 'dictate') text.then(said => { if (stamp === mine && early?.mine === mine && said && /[.!?…]["')\]]?$/.test(said.trim()) && (mode !== 'command' || withoutName(said.trim()))) feed.finish(); });
    },
    onResume: () => { stamp++; early = null; },
    onDrop: () => {
      tried = false; early = null;
      if (mode === 'barge') { capture = null; noteFalseStart(); speaker.hold(false); if (overWork) { overWork = false; carryOn(true); } }
      else if (mode !== 'wake' && capture) capYou.textContent = '';
    },
    onEnd: async (sound, said, when) => {
      const ready = early && early.mine === stamp ? early.text : null; early = null; tried = false;
      // The room itself (a film on another device, people talking) and no end found to it, or other people talking and
      // nobody has said JARVIS's name: not a sound of it is sent anywhere. Its name, said over it, is heard by the helper
      // that listens for the name, and what follows is taken from there (nameHeard below).
      if (mode === 'command' && helperHears() && !startedByYou && (when.forced || (Date.now() < nameOnlyUntil && !(askedSomething && Date.now() - quietSince < 30000)))) {
        if (capture?.feed === feed) { capYou.textContent = ''; addressed('', mode, true); }
        return;
      }
      const verdict = await judge(mode, when);
      if (verdict && verdict.pc) {   // the PC's own sound: not a word of it is used, and listening (or the work) simply carries on
        if (capture?.feed === feed) capYou.textContent = '';
        if (mode === 'barge' && overWork) { capture = null; overWork = false; carryOn(true); }
        return;
      }
      if (mode === 'barge') capture = null;
      else if (mode !== 'wake') { capture = null; if (mode !== 'dictate') setPhase('thinking'); }
      try {
        let text = ready ? await ready : null; if (text === null) text = await hear(sound, mode, when.noisy);
        // While something plays on the PC and the microphone can hear it, only what is said to JARVIS by name counts. Where the
        // browser takes the PC's sound out of the microphone, "cannot tell" means it is not heard there.
        if (verdict && verdict.playing && (verdict.heard === true || (verdict.heard !== false && !A.echoAll)) && (mode === 'command' || mode === 'confirm')) text = addressed(text, mode);
        // Other sound in the room and no end was found to what was "said": only what is said to JARVIS by name counts.
        else if (when.forced && (mode === 'command' || mode === 'confirm')) text = addressed(text, mode, true);
        // The "got it" sound is for real words only: a cough or a door must not make JARVIS chime.
        if (mode !== 'wake' && mode !== 'barge' && (mode === 'command' ? withoutName((text || '').trim()) : (text || '').trim())) chime('heard');
        heard(text, mode, !!when.noisy || !!when.faint, !!when.near, !!when.faint);
      }
      catch (error) {
        if (mode === 'wake') { engineDown.whisper = Date.now() + 30000; return; }
        if (mode === 'barge') { speaker.hold(false); if (overWork) { overWork = false; carryOn(true); } else if (!speaker.active() && voiceMode && options.hands_free) listen('command'); return; }
        engineDown.whisper = Date.now() + (error.busy ? 60000 : 600000);   // step aside for a while, then try Whisper again
        notify(error.message + (engine() ? ' Using the built-in listening for a moment. Please say that again.' : ''));
        if (engine()) listen(mode); else if (mode === 'dictate') endDictation(); else setPhase('idle');
      }
    },
  });
  return feed;
}
let socket = null;
async function liveCapture(mode) {   // ElevenLabs: the words appear while you are still speaking
  const { token } = await api('/api/speech', { action: 'token', kind: 'realtime_scribe' });
  const query = new URLSearchParams({ model_id: speech.settings.stt_model || 'scribe_v3_live', audio_format: 'pcm_16000', commit_strategy: 'vad',
    vad_silence_threshold_secs: mode === 'dictate' ? '1.1' : '0.6', token });
  const link = new WebSocket(speech.socket + '/v1/speech-to-text/realtime?' + query); socket = link;
  let held = [], opened = false;
  const fail = () => { if (socket === link) { socket = null; engineDown.eleven = Date.now() + 600000; if (capture?.mode === mode) { capture = null; listen(mode); } } };
  link.onopen = () => { opened = true; };
  link.onerror = fail; link.onclose = () => { if (socket === link && capture?.mode === mode) fail(); };
  link.onmessage = e => {
    let m; try { m = JSON.parse(e.data); } catch { return; }
    if (m.message_type === 'partial_transcript') { clearTimeout(restTimer); capYou.textContent = m.text || '…'; }
    else if (/^committed_transcript/.test(m.message_type || '')) { if ((m.text || '').trim()) { capture = null; stopLive(); chime('heard'); if (mode !== 'dictate') setPhase('thinking'); heard(m.text, mode); } }
    else if (/error|exceeded|limited|unaccepted/.test(m.message_type || '')) fail();
  };
  return (frame) => {
    held.push(frame);
    if (held.length < 5 || !opened || link.readyState !== 1) { if (held.length > 150) held.shift(); return; }
    const bytes = new Uint8Array(A.join(held).buffer); held = [];
    let binary = ''; for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    link.send(JSON.stringify({ message_type: 'input_audio_chunk', audio_base_64: btoa(binary), commit: false, sample_rate: 16000 }));
  };
}
function stopLive() { const link = socket; socket = null; try { link?.close(); } catch {} }
let recognizer = null;
function browserCapture(mode) {
  recognizer = new Recognition(); recognizer.lang = speech.settings.language && speech.settings.language !== 'auto' ? speech.settings.language : (navigator.language || 'en-US');
  recognizer.interimResults = true; recognizer.continuous = false; recognizer.maxAlternatives = 1;
  let finalText = ''; const mine = recognizer;
  recognizer.onresult = e => { let interim = ''; finalText = ''; for (const result of e.results) { if (result.isFinal) finalText += result[0].transcript; else interim += result[0].transcript; } clearTimeout(restTimer); capYou.textContent = (finalText + ' ' + interim).trim(); };
  recognizer.onerror = e => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') { notify('JARVIS needs permission to use the microphone. Allow it when the window asks, then try again.'); setVoice(false); }
    else if (e.error === 'network') notify('The built-in listening needs an internet connection.');
  };
  recognizer.onend = () => { if (recognizer === mine) recognizer = null; if (capture?.mode !== mode || capture.recognizer !== mine) return; capture = null; if (mode !== 'dictate' && finalText.trim()) setPhase('thinking'); heard(finalText, mode); };
  try { recognizer.start(); } catch {}
  return mine;
}
async function listen(mode = 'command', again = false) {   // again: carrying on after a noise, quietly and without extra time
  if (capture && capture.mode === mode) return;
  stopCapture();
  const how = engine();
  if (!how) { notify('Listening is not available in this window. Type instead, or press Win+H to dictate.'); if (mode === 'dictate') dictating = false; return; }
  if (mode !== 'dictate') { speaker.hush(); setPhase('listening', mode === 'confirm' ? 'Say yes or no' : ''); capYou.textContent = ''; }
  capture = { mode, feed: null };
  const mine = capture;
  try {
    if (how === 'browser') { A.micStart().then(() => micSync()).catch(() => {}); mine.recognizer = browserCapture(mode); }
    else {
      await A.micStart(); micSync(); if (capture !== mine) return;
      mine.feed = how === 'whisper' ? localCapture(mode) : await liveCapture(mode); if (capture !== mine) return stopLive();
      if (how === 'whisper' && wake.talking()) { mine.feed.prime(wake.sofar()); wake.reset(); capYou.textContent = '…'; }   // keep what you had already begun to say
    }
  } catch (error) {
    if (capture === mine) capture = null;
    if (how !== 'browser' && !/permission|microphone/i.test(error.message)) { engineDown[how] = Date.now() + 600000; if (engine()) return listen(mode); }
    notify(error.message); if (mode === 'dictate') endDictation(); else setVoice(false); return;
  }
  if (mode !== 'dictate' && !again) chime('listen');
  clearTimeout(restTimer);
  if (mode === 'command') {
    if (!again) restBy = Date.now() + awakeMs();
    restTimer = setTimeout(() => { if (capture === mine && !(mine.feed?.talking?.())) { stopCapture(); setPhase('idle'); hint(speech.settings.wake ? 'Asleep. Say “Hey ' + (options.assistant?.name || 'JARVIS') + '” when you need me.' : 'Asleep. Press Space or tap Talk when you need me.'); } }, Math.max(500, restBy - Date.now()));
  }
  animate();
}
// An idle session (no task running, nothing new asked) stays awake this long, then sleeps until it hears its name.
// (0 minutes: awake until it is told "go to sleep". A whole day stands in for "never", so the timer below stays simple.)
const awakeMs = () => !options.hands_free ? 14000 : Number(options.sleep_minutes) === 0 ? 86400000 : Math.max(1, Number(options.sleep_minutes) || 15) * 60000;
let startedByYou = false, askedSomething = false;   // you pressed Talk or said its name; JARVIS's last reply ended in a question
function stopCapture() {
  clearTimeout(restTimer);
  const old = capture; capture = null; stopLive();
  if (old?.recognizer) { try { old.recognizer.abort(); } catch {} }
}
// noisy: said over other sound in the room; near: by someone plainly nearer than it; faint: it hardly stood out from
// what surrounded it, so it is most likely that other sound itself (a line of a film)
function heard(text, mode, noisy, near, faint) {
  text = (text || '').trim();
  if (mode === 'wake') return wakeHeard(text);
  if (mode === 'barge') {
    const wasWorking = overWork; overWork = false;
    // Was that you, or JARVIS's own voice coming back through the microphone? Only real words from you stop it.
    if (!text || echoOfMe(text)) { noteFalseStart(); speaker.hold(false); carryOn(wasWorking); return; }
    // Said while JARVIS was working (not speaking): it may have been said to someone else in the room. It is taken as
    // meant for JARVIS when it has its name in it, or is plainly a correction ("no, I meant...", "wait", "not that one").
    if (wasWorking && !wakeWord().test(text) && !CORRECTS.test(text)) { hint('Say “' + (options.assistant?.name || 'JARVIS') + '” first if that was for me.'); carryOn(true); return; }
    return void interrupt(text, noisy);
  }
  if (mode === 'dictate') { if (text) N.setDraft(($('message').value ? $('message').value.replace(/\s*$/, ' ') : '') + text); endDictation(); return; }
  capYou.textContent = text;
  if (mode === 'confirm') {
    if (!confirmOpen) return afterSpeech();
    // A yes lets something happen, so it has to be its owner's. With other sound in the room (a film, a call, another
    // device) and a voice that is not plainly the one near the microphone, a bare "yes" could be anybody's: it counts
    // only with JARVIS's name in front, or pressed in the window. A "no" is safe whoever said it.
    if (YES.test(text) && !NO.test(text)) {
      if (noisy && !near && !wakeWord().test(text)) {
        const name = options.assistant?.name || 'JARVIS';
        hint('There is other sound in the room. Say “' + name + ' yes”, or press Yes, so I know it is you.');
        return voiceMode ? listen('confirm') : undefined;
      }
      return answerConfirm(true);
    }
    if (NO.test(text)) return answerConfirm(false);
    return voiceMode ? listen('confirm') : undefined;
  }
  const named = wakeWord().test(text), bare = withoutName(text);
  // Said to JARVIS for certain: by name, in answer to its own question, or straight after you started the listening yourself.
  // Anything else was picked up by the open microphone and may be you talking to someone else; JARVIS judges that itself.
  const direct = named || !voiceMode || !options.hands_free || (!faint && (startedByYou || (askedSomething && Date.now() - quietSince < 30000)));
  startedByYou = false;
  text = bare; capYou.textContent = text;
  if (!text) {   // a noise, or only its name: keep listening for as long as it would have anyway, without a sound
    if (voiceMode && options.hands_free && Date.now() < restBy - 500) listen('command', true);
    else { setPhase('idle'); if (voiceMode) hint(speech.settings.wake ? 'Say “Hey ' + (options.assistant?.name || 'JARVIS') + '” when you need me.' : ''); }
    return;
  }
  // Other people are talking: what is not said to JARVIS by name is left alone for a while (see notForMe above).
  if (!direct && Date.now() < nameOnlyUntil) { capYou.textContent = ''; addressed('', mode, true); if (voiceMode && options.hands_free && Date.now() < restBy - 500) listen('command', true); else setPhase('idle'); return; }
  hint(''); send(text, true, { ...(direct ? {} : { heard: true }), ...(noisy ? { noisy: true } : {}), ...(near ? { near: true } : {}) }).catch(() => { if (voiceMode) setPhase('idle'); });
}

/* ---------- interrupting by talking, and the wake word ---------- */
let wakeTimes = [], wakeLoop = null, interrupting = false;
// The moment you start talking over JARVIS its voice drops; it stops only once real words from you have been heard.
// It falls silent the moment you start. But if the microphone keeps picking up its own voice (two false starts within a few
// seconds), pausing each time would make it stutter: then it only turns itself down, for the next half minute.
let falseStarts = [], gentleUntil = 0;
const noteFalseStart = () => { const now = Date.now(); falseStarts = [...falseStarts.filter(t => now - t < 8000), now]; if (falseStarts.length >= 2) { gentleUntil = now + 30000; falseStarts = []; } };
const barge = localCapture('barge', { start: 5, minMs: 160, endMs: 600, floor: 0.035, factor: 4.5,
  onStart: () => { if (Date.now() < gentleUntil) A.duck(0.2); else speaker.hold(true); capture = { mode: 'barge', feed: barge }; } });
// Said over JARVIS, these end what it is saying and doing at the first short pause, without waiting for the sentence to end.
const STOP_NOW = /^\W*(?:(?:hey|ok|okay)?\s*jarvis\W*)?(?:stop|stop it|stop that|stop now|stop talking|wait|hold on|cancel|cancel that|quiet|be quiet|enough|that's enough|never ?mind|shut up|pause)\W*$/i;
async function interrupt(text, noisy) {
  interrupting = true; speaker.hush(); capYou.textContent = text; hint(''); setPhase('thinking');
  try {
    const running = focus && turns.get(focus);
    // What it had already done stays done: the AI is told, so it neither repeats it nor claims to have undone it.
    const done = running ? running.steps.slice(-8) : null;
    if (running) { await api('/api/voice', { action: 'stop', chat: running.chat }).catch(() => {}); for (let i = 0; i < 60 && turns.has(running.id); i++) await pause(50); }
    await send(text, true, { ...(done ? { interrupts: done } : {}), ...(noisy ? { noisy: true } : {}) });
  } catch { if (voiceMode) setPhase('idle'); }
  finally { interrupting = false; }
}
// While JARVIS is working on something (not speaking), it still listens. The moment you start to speak, nothing new is
// begun (what is being done at that instant is finished); once it is known what you said, the work is stopped and the
// new request taken, or, if that was not meant for JARVIS, the work carries on.
const CORRECTS = /^\W*(?:no\b|nope\b|wait\b|stop\b|cancel\b|actually\b|not that\b|not this\b|not the\b|i said\b|i meant\b|i mean\b|instead\b|never ?mind\b|hold on\b|wrong\b|that'?s wrong\b|that is wrong\b|go back\b|undo\b|don'?t\b|do not\b)/i;
let overWork = false;
const working = () => { const turn = focus && turns.get(focus); return voiceMode && phase === 'thinking' && turn && turn.spoken ? turn : null; };
function holdWork(on) { const turn = focus && turns.get(focus); if (turn) api('/api/voice', { action: 'hold', chat: turn.chat, on: !!on }).catch(() => {}); }
function carryOn(wasWorking) {
  if (wasWorking) { holdWork(false); capYou.textContent = ''; if (voiceMode && focus && turns.has(focus)) setPhase('thinking'); else if (voiceMode) afterSpeech(); return; }
  if (!speaker.active() && voiceMode) { if (options.hands_free) listen('command'); else setPhase('idle'); }
}
const during = localCapture('barge', { start: 5, minMs: 200, endMs: 700,
  onStart: () => { overWork = true; holdWork(true); capture = { mode: 'barge', feed: during }; capYou.textContent = '…'; hint('Listening…'); } });
// JARVIS's name was heard by the helper that listens for it, while this window holds a spoken conversation. What is
// being said is taken from the name on (the last seconds of the microphone are kept for this), whatever else is
// sounding in the room, and it counts as said to JARVIS. Said while JARVIS speaks or works, it interrupts.
const ring = [];
function nameHeard(at) {
  if (!voiceMode || muted || dictating || engine() !== 'whisper' || !A.micOn || confirmOpen) return;
  if (capture && capture.named && Date.now() - capture.named < 4000) return;      // the same "Hey JARVIS", heard twice
  const from = at * 1000 - 1500, kept = ring.filter(([when]) => when >= from), sound = A.join(kept.map(([, frame]) => frame));
  if (sound.length < 3200) return;
  const over = speaker.active() || !!working(), mode = over ? 'barge' : 'command';
  if (speaker.active()) speaker.hold(true);
  overWork = !!working(); if (overWork) holdWork(true);
  stopCapture(); startedByYou = true;
  const feed = localCapture(mode, { busyMaxMs: 7000 });
  const mine = capture = { mode, feed, named: Date.now() };
  feed.prime(sound, kept.map(([, , real]) => real === undefined ? -1 : real)); capYou.textContent = '…'; hint('');
  if (!over) setPhase('listening');
  // In a room with other sound an end may never be found by listening. So what has been said since the name is written
  // down after a couple of seconds, and again a little later: a first sentence that is whole and has stayed the same is
  // the request, and is acted on without waiting for more.
  let settled = '';
  const peek = async () => {
    if (capture !== mine || !feed.talking()) return;
    const text = await post(sttPath(mode, feed.room().busy), feed.sofar().buffer).then(d => d.text || '').catch(() => null);
    if (capture !== mine || !feed.talking()) return;
    const whole = ((withoutName((text || '').trim()) || '').match(/^\s*(.{3,200}?[.!?])(?:\s|$)/) || [])[1] || '';
    if (whole && whole === settled && !/\b(?:for|to|and|or|the|a|an|of|in|on|at|with|by|from|about|that|my|is|are|then|but|if|as|into)[.!?…]*$/i.test(whole)) {
      const over = feed.room().noisy, near = feed.near();
      capture = null; feed.reset(); chime('heard');
      return heard((options.assistant?.name || 'JARVIS') + ', ' + whole, mode, over, near);
    }
    settled = whole; setTimeout(peek, 1700);
  };
  const room = feed.room();
  if (room.busy || room.n < 50) setTimeout(peek, 2300);   // (n < 50: the room is not known yet; it may well be full of sound)
}
const wake = localCapture('wake', { maxMs: 9000 });
// Whenever none of the listeners above is listening (JARVIS is thinking, or asleep), this one follows what the room
// sounds like, so that the next one knows it from its first moment. Nothing it hears is kept or sent anywhere.
const ambient = A.detector({});
// The tray helper normally listens for the wake word (even with no window open). The window only does it itself when that helper is not running.
const wakeWanted = () => speech.settings.wake && DIRECT && !muted && !dictating && !(speech.shortcuts && speech.shortcuts.wake);
function wakeHeard(text) {
  const match = text.match(wakeWord()); if (!match) return;
  const rest = match[1].trim();
  if (!voiceMode) setVoice(true, true);
  if (rest.length > 2) { capYou.textContent = rest; setPhase('thinking'); send(rest, true).catch(() => setPhase('idle')); } else listen('command');
}
let beat = 0;
let toldRoom = 0;
function route(frame, loud, real) {   // real: how loud that moment really was (the untouched microphone), where known
  if (++beat % 10 === 0) settle();   // the microphone's steady pulse keeps things moving when the window is hidden
  // Other sound in the room, and no way to tell you from it by how near you are: say once in a while how to be heard.
  if (beat % 100 === 0 && capture?.mode === 'command' && !startedByYou && helperHears() && Date.now() - toldRoom > 300000) {
    const room = capture.feed?.room?.();
    if (room && room.busy && !room.truly && !capture.feed.talking()) { toldRoom = Date.now(); addressed('', 'command', true); }
  }
  if (voiceMode) { ring.push([Date.now(), frame, real]); if (ring.length > 220) ring.shift(); } else if (ring.length) ring.length = 0;
  if (muted) return;
  if (A.speaking()) ownVoiceAt = Date.now();
  if (capture) { capture.feed?.(frame, loud, real); return; }
  // (Its own voice is not in what the microphone hears: the window takes its own sound out, and where the browser can, all the PC's sound.)
  if (speaker.active()) { if (voiceMode && speech.settings.barge_in && (speaker.natural() || A.echoAll) && engine() === 'whisper') barge(frame, loud, real); else if (speaker.natural() || A.echoAll) ambient(frame, loud, real); return; }
  if (working() && speech.settings.barge_in && engine() === 'whisper') { during(frame, loud, real); return; }
  if (wakeWanted() && engine() === 'whisper' && phase !== 'thinking') {
    const now = Date.now(); wakeTimes = wakeTimes.filter(t => now - t < 60000);
    if (wakeTimes.length < 10) { const was = wake.talking(); wake(frame, loud, real); if (was && !wake.talking()) wakeTimes.push(now); return; }
  }
  ambient(frame, loud, real);
}
function browserWake() {   // without Whisper, the browser listens for the wake word
  if (wakeLoop || !Recognition || engine() !== 'browser' || !wakeWanted() || voiceMode) return;
  const r = new Recognition(); wakeLoop = r; r.continuous = true; r.interimResults = false; r.lang = navigator.language || 'en-US';
  r.onresult = e => { const said = e.results[e.results.length - 1][0].transcript; if (wakeWord().test(said)) { try { r.abort(); } catch {} wakeHeard(said); } };
  r.onend = () => { wakeLoop = null; setTimeout(browserWake, 600); }; r.onerror = () => {};
  try { r.start(); } catch { wakeLoop = null; }
}
let routed = null, meterTimer = 0;
async function micSync() {
  const need = voiceMode || dictating || meterTimer || (wakeWanted() && engine() === 'whisper');   // (meterTimer: the microphone test in the settings)
  if (need && engine() !== 'browser') { try { await A.micStart(); if (!routed) routed = A.hear(route); } catch (error) { if (voiceMode || dictating) notify(error.message); } }
  else if (need && A.micOn && !routed) routed = A.hear(route);
  else if (!need && A.micOn) { routed = null; A.micStop(); }
  if (wakeWanted() && !voiceMode) browserWake(); else if (wakeLoop && voiceMode) { try { wakeLoop.abort(); } catch {} }
  tellWaiting();
}
document.addEventListener('visibilitychange', () => micSync());

/* ---------- voice chat on and off ---------- */
async function setVoice(on, quiet) {
  if (on === voiceMode) return;
  voiceMode = on; body.classList.toggle('nv-voice', on); N.refreshMode?.();
  voiceB.classList.toggle('on', on); voiceB.dataset.tip = on ? 'Leave voice chat' : 'Talk with JARVIS out loud';
  if (on) {
    A.unlock(); muted = false; muteB.classList.remove('on'); capYou.textContent = capMe.textContent = '';
    if (!quiet) startedByYou = true;   // you opened the voice chat: the first thing said is said to JARVIS
    if (!MINI) hint(TRY[Math.floor(Math.random() * TRY.length)]);
    api('/api/speech', { action: 'warm' }).catch(() => {});
    await loadSpeech(); speaker.retry(); engineDown = {};
    if (!engine()) { setPhase('idle', 'Listening is not available here. Type below; JARVIS will still speak.'); return; }
    await micSync();
    if (!voiceMode) return;
    if (quiet) return;
    if (turns.size) { wantListen = true; setPhase('thinking'); } else listen('command');
  } else {
    stopCapture(); speaker.hush(); setPhase('idle'); hint(''); await micSync();
    if (current) openChat(current).catch(() => {});
  }
}
function toggleTalk() { startedByYou = true; if (!voiceMode) return setVoice(true); if (speaker.active()) { speaker.hush(); listen('command'); } else if (capture) { stopCapture(); setPhase('idle'); } else listen('command'); }
async function startDictation() {
  if (dictating) return endDictation();
  if (voiceMode) return toggleTalk();
  await loadSpeech(); dictating = true; dictateB.classList.add('on'); dictateB.dataset.tip = 'Listening. Click again to finish.'; A.unlock(); chime('listen');
  await listen('dictate'); animate();
}
function endDictation() { dictating = false; dictateB.classList.remove('on'); dictateB.dataset.tip = 'Speak your message instead of typing it'; stopCapture(); micSync(); }

/* ---------- sending a message to the fast assistant ---------- */
function doUi(what, say, spoken) {
  const [kind, value] = what.split(':');
  if (MINI && !['rest', 'sleep', 'end'].includes(kind)) return;   // panels, themes and the like belong to the app window
  if (kind === 'pane') { if (voiceMode) setVoice(false); N.openPane(value); }
  else if (kind === 'new-chat') N.newChat?.();
  else if (kind === 'theme') N.setTheme?.(value);
  else if (kind === 'fullscreen') N.setFull?.(true);
  else if (kind === 'close-panel') N.closePanel();
  else if (kind === 'rest') {   // "stop": drop what it was doing and saying. The session stays awake for the next thing.
    stopNow(); if (voiceMode && options.hands_free && !muted) listen('command'); else rest(); return;
  }
  else if (kind === 'sleep') { stopNow(); rest(); return; }   // "go to sleep": wait to be called by name
  else if (kind === 'end') { endSession(spoken); return; }    // "end session": leave voice chat
  if (say && spoken && options.speak) speaker.say(say); else if (voiceMode && options.hands_free) listen('command'); else if (voiceMode) setPhase('idle');
}
function stopNow() { N.assistantStop?.().catch(() => {}); speaker.hush(); stopCapture(); wasSpeaking = false; if (confirmOpen) answerConfirm(false); }
// Leaving voice chat. A window that "Hey JARVIS" opened by itself, and that nobody has touched, closes again; saying
// "Hey JARVIS" brings it straight back.
let leaving = false, leaveTimer = 0, touched = false;
const OPENED_BY_VOICE = DIRECT && new URLSearchParams(location.search).has('listen');
addEventListener('pointerdown', () => { touched = true; }, true); addEventListener('keydown', e => { if (e.isTrusted) touched = true; }, true);
function leave() {
  leaving = false; clearTimeout(leaveTimer);
  setVoice(false);
  if (OPENED_BY_VOICE && !touched) setTimeout(() => { try { window.close(); } catch {} }, 250);
}
function endSession(spoken) {
  stopNow();
  if (!voiceMode) return leave();
  if (spoken && options.speak) { leaving = true; setPhase('speaking'); speaker.say('Goodbye.'); leaveTimer = setTimeout(leave, 5000); }
  else leave();
}
async function takeSpoken(text) {   // a request that was already heard and transcribed outside this window
  // Answer first; the voice chat (and the one-time microphone permission) is set up alongside, never in the way.
  if (!voiceMode) setVoice(true, true);
  stopCapture(); speaker.hush(); capYou.textContent = text; hint(''); setPhase('thinking');
  send(text, true).catch(() => { if (voiceMode) setPhase('idle'); });
}
function rest() {   // "stop", "never mind", the Stop button: be quiet and wait to be asked again
  speaker.hush(); stopCapture(); wasSpeaking = false;
  if (voiceMode) { setPhase('idle'); hint(speech.settings.wake ? 'Say “Hey ' + (options.assistant?.name || 'JARVIS') + '” or press Space to talk again.' : 'Press Space or tap Talk when you need me.'); }
}
async function send(text, spoken, extra = {}) {
  const picked = String($('model')?.value || 'auto'), model = picked.startsWith('claude:') ? picked.slice(7) : picked.startsWith('api:') ? picked.slice(4) : undefined;
  expecting = true;
  try {
    const started = await api('/api/voice', { action: 'say', text, chat: current || null, spoken: !!spoken, model, project: current ? undefined : (selectedProject || undefined), ...extra });
    if (started.ui) { doUi(started.ui, started.say, spoken); return started; }
    if (started.chat !== current) { current = started.chat; localStorage.setItem('jcc-chat', current); }
    lastMessages = ''; const fresh = await api('/api/chat?id=' + encodeURIComponent(started.chat)); if (fresh.id === current) renderChat(fresh);
    refresh().catch(() => {});
    return started;
  } catch (error) { toast(error.message); if (voiceMode) { hint(error.message); if (options.speak) speaker.say(error.message); } throw error; }
  finally { expecting = false; }
}
N.assistantSend = (text, extra) => send(text, false, extra);
N.assistantUsable = attachments => $('mode').value !== 'code' && !String($('model')?.value || '').startsWith('codex:') && !(attachments.uploads || []).some(u => u.image_id);
N.assistantLive = rid => turns.has(rid);
N.assistantStop = async () => {
  speaker.hush();
  const mine = [...turns.values()].find(t => t.chat === current); if (!mine) return false;
  await api('/api/voice', { action: 'stop', chat: mine.chat }); return true;
};

/* ---------- "shall I?" ---------- */
function answerConfirm(approve) {
  const open = confirmOpen; if (!open) return; confirmOpen = null; stopCapture();
  api('/api/voice', { action: 'confirm', id: open.dataset.id, approve }).then(() => N.permissionsChanged?.()).catch(() => {});
  open.close(); hint(approve ? 'Doing it…' : 'Okay, I will not.'); if (voiceMode) setPhase('thinking');
}
// Answered on its card in the chat (nova-permissions.js): the spoken question is over too.
N.confirmAnswered = (id, approve) => {
  if (confirmOpen?.dataset.id !== id) return;
  const open = confirmOpen; confirmOpen = null; stopCapture(); open.close();
  hint(approve ? 'Doing it…' : 'Okay, I will not.'); if (voiceMode) setPhase('thinking');
};
function askConfirm(event) {
  if (confirmOpen?.dataset.id === event.id) return;
  if (confirmOpen) confirmOpen.close();
  if (!MINI) {
    // As in Claude: the question is a card at the end of its chat, with its answers on it. Nothing else stops, and the
    // reply carries on as soon as it is answered (by the card, or out loud). The small listening window keeps its box.
    confirmOpen = { dataset: { id: event.id }, close() {} };
    N.permissionsChanged?.();
    if (event.chat && event.chat !== current) notify('JARVIS asks you something in another chat: ' + event.question, 'Open', () => openChat(event.chat).catch(error => toast(error.message)));
    chime('notice');
    const turn = [...turns.values()].find(t => t.chat === event.chat);
    if (shouldSpeak(turn)) {
      stopCapture(); speaker.hush(); wantListen = true;
      const asked = confirmOpen;
      (speaker.active() || Date.now() - quietSince < 2000 ? Promise.resolve({}) : api('/api/voice', { action: 'playing' }).catch(() => ({}))).then(now => { if (confirmOpen === asked) speaker.say(event.question + (now.playing ? ' Say ' + (options.assistant?.name || 'JARVIS') + ' yes, or ' + (options.assistant?.name || 'JARVIS') + ' no.' : ' Say yes or no.')); });
    } else if (voiceMode) listen('confirm');
    return;
  }
  const why = event.kind === 'careful' ? '<p class="nv-careful-note">' + SHIELD + '<span>JARVIS is being extra careful: this chat has read a web page, a file or your screen, which can contain text written to trick an AI.</span></p>' : '';
  const open = confirmOpen = dialog('<h2>' + esc(event.question) + '</h2>' + (event.detail ? '<pre class="easy-technical">' + esc(event.detail) + '</pre>' : '') + why +
    '<p>JARVIS will only do this if you say yes.</p><div class="actions"><button class="plain" data-no>No</button><button class="primary" data-yes>Yes, do it</button></div>', 'nv-ask');
  confirmOpen.dataset.id = event.id;
  confirmOpen.querySelector('[data-yes]').onclick = () => answerConfirm(true);
  confirmOpen.querySelector('[data-no]').onclick = () => answerConfirm(false);
  confirmOpen.addEventListener('cancel', () => answerConfirm(false));
  chime('notice');
  const turn = [...turns.values()].find(t => t.chat === event.chat);
  if (shouldSpeak(turn)) {
    stopCapture(); speaker.hush(); wantListen = true;
    // While something is playing on the PC, a "yes" only counts with its name in front, so a film cannot say yes for you.
    // (Not asked while JARVIS itself is talking or has only just stopped: that is the PC's sound too.)
    (speaker.active() || Date.now() - quietSince < 2000 ? Promise.resolve({}) : api('/api/voice', { action: 'playing' }).catch(() => ({}))).then(now => { if (confirmOpen === open) speaker.say(event.question + (now.playing ? ' Say ' + (options.assistant?.name || 'JARVIS') + ' yes, or ' + (options.assistant?.name || 'JARVIS') + ' no.' : ' Say yes or no.')); });
  }
  else if (voiceMode) listen('confirm');
}

/* ---------- careful mode ---------- */
const carefulChip = el('button', { class: 'nv-careful hidden', type: 'button', data: { tip: 'JARVIS asks before changing anything in this chat. Click to learn why.' } }, SHIELD + '<span>Careful mode</span>');
document.querySelector('.topbar')?.append(carefulChip);
carefulChip.onclick = () => {
  const d = dialog('<h2>Careful mode is on for this chat</h2><p>This chat has read something from outside: a web page, a file, your screen or the clipboard. Such content can hide instructions written to trick an AI into doing harm.</p><p>So for the rest of this chat JARVIS asks you before it changes anything on your PC or sends anything out. Looking and answering stay instant.</p><p>A new chat starts normally again.</p><div class="actions"><button class="plain" data-new>Start a new chat</button><button class="primary">Got it</button></div>');
  d.querySelector('.primary').onclick = () => d.close(); d.querySelector('[data-new]').onclick = () => { d.close(); N.newChat?.(); };
};
const carefulChats = new Set();
setInterval(() => { carefulChip.classList.toggle('hidden', !(current && (chat?.id === current && chat?.careful === true || carefulChats.has(current)))); }, 600);

/* ---------- which AI is answering ----------
   While Claude's allowance is used up a stand-in answers, and a request that nothing can answer waits. A small chip says so. */
const clockTime = when => new Date(when * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
const brainChip = el('button', { class: 'nv-careful nv-brain hidden', type: 'button' }, icon('spark') + '<span></span>');
document.querySelector('.topbar')?.append(brainChip);
let brain = {};
function showBrain(now) {
  brain = now || {};
  const waiting = (brain.waiting || []).length, out = brain.until && brain.until * 1000 > Date.now();
  brainChip.classList.toggle('hidden', !waiting && !out);
  if (!waiting && !out) return;
  brainChip.querySelector('span').textContent = waiting ? waiting + (waiting === 1 ? ' request waiting' : ' requests waiting') : 'Stand-in until ' + clockTime(brain.until);
  brainChip.dataset.tip = out ? brain.out + ' has reached its limit until ' + clockTime(brain.until) + '. Click for details.' : 'Click for details.';
}
brainChip.onclick = () => {
  const waiting = brain.waiting || [], out = brain.until && brain.until * 1000 > Date.now();
  const d = dialog('<h2>' + (out ? esc(brain.out) + ' is resting until ' + esc(clockTime(brain.until)) : 'Waiting requests') + '</h2>' +
    (out ? '<p>Its usage allowance is used up for now. Until it is back, JARVIS answers with another AI you have connected, and tells you when it does. You can connect more under <b>AI models</b>.</p>' : '') +
    (waiting.length ? '<p>These could not be answered by anything just now. JARVIS carries on with them by itself:</p><ul class="nv-waiting">' +
      waiting.map(w => '<li><span>' + esc(w.text) + '<small>at about ' + esc(clockTime(w.until)) + '</small></span><button class="plain" data-unwait="' + esc(w.id) + '">Do not</button></li>').join('') + '</ul>' : '') +
    '<div class="actions"><button class="plain" data-models>AI models</button>' + (waiting.length ? '<button class="plain" data-now>Try now</button>' : '') + '<button class="primary" data-ok>Got it</button></div>');
  d.querySelector('[data-ok]').onclick = () => d.close();
  d.querySelector('[data-models]').onclick = () => { d.close(); openSettings('models'); };
  const now = d.querySelector('[data-now]');
  if (now) now.onclick = async () => { try { const got = await api('/api/voice', { action: 'resume' }); notify(got.taken ? 'Carrying on now.' : 'Nothing can answer yet. JARVIS will carry on as soon as something can.'); } catch (error) { toast(error.message); } d.close(); };
  d.querySelectorAll('[data-unwait]').forEach(b => b.onclick = async () => { try { await api('/api/voice', { action: 'unwait', id: b.dataset.unwait }); b.closest('li').remove(); if (current) openChat(current).catch(() => {}); } catch (error) { toast(error.message); } });
};
N.waitingAction = async (action, id) => {      // the buttons on a reply that is waiting
  try {
    if (action === 'now') { const got = await api('/api/voice', { action: 'resume' }); notify(got.taken ? 'Carrying on now.' : 'Nothing can answer yet. JARVIS will carry on as soon as something can.'); }
    else { await api('/api/voice', { action: 'unwait', id }); if (current) openChat(current).catch(() => {}); }
  } catch (error) { toast(error.message); }
};
N.compactChat = async () => {
  if (!current) return toast('Open a conversation first.');
  try { await api('/api/voice', { action: 'compact', chat: current }); notify('Compacting this conversation…'); }
  catch (error) { toast(error.message); }
};
/* The other AI services the owner has connected, for the model pickers. */
let services = [];
/* Research: who does it. Left to JARVIS, it is the service made for research when one is connected, otherwise Claude with
   its web search. Perplexity's choices are depths of research (its "effort levels"). */
const DEPTHS = [['fast', 'Quick', 'One fact or a short summary, in seconds'], ['low', 'Standard', 'Everyday questions that need current information'],
  ['medium', 'Thorough', 'Many sources, over several rounds of searching'], ['high', 'Deep', 'Expert-level and as complete as it can be. Takes minutes.'],
  ['xhigh', 'Agentic', 'Open-ended work that also runs code. Takes long.'], ['ultra', 'Exhaustive', 'The widest search there is. Takes longest and costs most.']];
N.loadServices = () => loadServices();
N.researchChoices = () => {
  const perplexity = services.some(s => s.id === 'perplexity' && s.connected);
  const list = [{ value: 'auto', label: 'Automatic', note: perplexity ? 'Perplexity, thorough. If it cannot, Claude with its web search.' : 'Claude Sonnet, with its web search' }];
  if (perplexity) for (const [id, name, note] of DEPTHS) list.push({ value: 'perplexity:' + id, label: name, note, group: 'Perplexity (charged to your Perplexity account)' });
  for (const [id, name, note] of [['sonnet', 'Claude Sonnet', 'Balanced'], ['opus', 'Claude Opus', 'Stronger reasoning'], ['fable', 'Claude Fable', 'The strongest, and the slowest']])
    list.push({ value: 'claude:' + id, label: name, note, group: 'Claude, with its web search (your Claude plan)' });
  const chosen = options.research && list.some(c => c.value === options.research) ? options.research : 'auto';
  return { chosen, list, perplexity };
};
N.setResearch = async value => { options = { ...options, ...(await api('/api/voice', { action: 'settings', settings: { research: value } })) }; };
let servicesProblem = '';
async function loadServices(look) {
  try { services = (await api('/api/providers', { action: 'list', look: !!look })).items; servicesProblem = ''; } catch (error) { servicesProblem = error.message || 'The list could not be read.'; }
  fillPicker(); return services;
}
function fillPicker() {
  const select = $('model'); if (!select) return;
  let group = select.querySelector('optgroup[data-ai]');
  const on = services.filter(s => s.connected && s.model && s.tools !== false);
  if (!on.length) { group?.remove(); return; }
  if (!group) { group = document.createElement('optgroup'); group.dataset.ai = '1'; group.label = 'Other AI services'; select.append(group); }
  const keep = select.value;
  group.replaceChildren(...on.map(s => { const o = document.createElement('option'); o.value = 'api:' + s.id + ':' + s.model; o.textContent = s.name.split(' (')[0] + ' · ' + s.model.split('/').pop(); return o; }));
  if ([...select.options].some(o => o.value === keep)) select.value = keep;
}
const earlierPicker = window.updateModelPicker; window.updateModelPicker = d => { earlierPicker?.(d); fillPicker(); };
N.aiChanged = () => loadServices(false);

/* ---------- events from the assistant ---------- */
function handle(event) {
  const k = event.k, turn = turns.get(event.id);
  if (k === 'phase') { if (MINI && !voiceMode && event.w !== WINDOW && event.kind !== 'mini') mirror(event.phase); return; }
  if (k === 'start') {
    const made = { id: event.id, chat: event.chat, spoken: event.spoken, text: '', said: 0, steps: [] }; turns.set(event.id, made);
    const shown = MINI && !voiceMode && event.spoken;   // a conversation held by the app window, shown here while it is in the background
    if (shown && event.say) capYou.textContent = event.say;
    if (expecting || event.chat === current || shown) { focus = event.id; capMe.textContent = ''; hint(''); body.classList.add('nv-working'); if (voiceMode) setPhase('thinking'); }
  } else if (k === 'text' && turn) {
    turn.text += event.t; N.liveUpdate?.(turn.id, turn.text);
    if (focus === turn.id) { capMe.textContent = speakable(turn.text).slice(-260); speakProgress(turn, false); }
  } else if (k === 'lead' && turn) {
    // First a word that the request was heard ("On it."), the moment the AI is taking more than a second. What it then
    // starts on ("Opening Netflix.") is shown, and said only when that word was not said just before it: one thing at a
    // time in the ear. (Only a first step that was really said counts as said: what the AI reports afterwards is then
    // not held back as a repeat of it.)
    const justSaid = !event.ack && turn.ackAt && Date.now() - turn.ackAt < 4000;
    if (event.ack) turn.ackAt = Date.now(); else if (!justSaid) turn.lead = event.t;
    if (focus === turn.id) { capMe.textContent = event.t; if (shouldSpeak(turn) && !justSaid) speaker.say(event.t); }
  } else if (k === 'step' && turn) {
    turn.steps.push(event.t); N.liveUpdate?.(turn.id, undefined, turn.steps);
    if (focus === turn.id) hint(event.t + '…');
  } else if (k === 'confirm') askConfirm(event);
  else if (k === 'confirmed' && confirmOpen?.dataset.id === event.id) { confirmOpen.close(); confirmOpen = null; }
  else if (k === 'careful') carefulChats.add(event.chat);
  else if (k === 'wake') A.unlock();   // "Hey JARVIS" or the Talk shortcut, somewhere on the PC: pickUp() below goes and takes it
  else if (k === 'name') nameHeard(Number(event.at) || Date.now() / 1000);   // its name, heard during this conversation
  // "JARVIS, stop", "go to sleep" or "end session", heard by the helper that listens for the name (it hears them even while
  // JARVIS itself is talking), or the small window's End button. Every window is told; the one holding the conversation acts.
  else if (k === 'ui' && event.all) { if (voiceMode || speaker.active() || leaving) doUi(event.do, '', !!event.spoken); }
  else if (k === 'notice') {
    if (MINI && document.hidden) { if (options.speak && event.say !== false && event.ask) speaker.say(event.text); return; }   // out of sight: said, and Windows shows it
    if (event.ask) api('/api/voice', { action: 'took', id: event.ask }).catch(() => {});   // tell the app it was shown here, so Windows need not show it too
    chime('notice'); notify(event.text);
    if (event.kind === 'reminder' || event.kind === 'timer') N.hook?.('reminder');
    if (options.speak && (event.say === undefined ? (voiceMode || speech.settings.wake) : (event.say && voiceMode))) speaker.say(event.text);
    if (event.kind === 'switch' || event.kind === 'waiting' || event.kind === 'resumed') N.aiChanged?.();
  }
  else if (k === 'done' && event.status === 'ignored') {
    // That was not meant for JARVIS (you were talking to someone else): nothing is said, shown or kept, and listening carries on.
    turns.delete(event.id);
    if (focus === event.id) {
      focus = null; capMe.textContent = ''; capYou.textContent = ''; body.classList.remove('nv-working');
      notForMe();
      hint(Date.now() < nameOnlyUntil ? 'Other people are talking, so I will wait until I hear “' + (options.assistant?.name || 'JARVIS') + '”.'
        : 'Not for me, so I stayed out of it. Start with “' + (options.assistant?.name || 'JARVIS') + '” if it was.');
      if (voiceMode && options.hands_free && !muted && Date.now() < restBy - 500) listen('command', true); else if (voiceMode) setPhase('idle');
    }
    if (event.gone && event.chat === current) { current = ''; localStorage.removeItem('jcc-chat'); lastMessages = ''; renderChat(null); }
    else if (event.chat === current) api('/api/chat?id=' + encodeURIComponent(current)).then(c => { if (c.id === current) { lastMessages = ''; renderChat(c); } }).catch(() => {});
    refresh().catch(() => {});
  }
  else if (k === 'done') {
    const mine = focus === event.id;
    if (turn) { if (!turn.text) turn.text = event.status === 'done' ? event.text : ''; if (mine && event.status !== 'cancelled') speakProgress(turn, true); turns.delete(event.id); }
    if (mine) {
      lastTurnAt = Date.now();
      if (event.status === 'done') N.hook?.('answer');
      askedSomething = /\?\s*$/.test((event.text || '').trim());
      focus = null; capMe.textContent = speakable(event.text).slice(-320); hint(''); body.classList.remove('nv-working');
      if (event.status === 'failed') { hint(event.text); chime('error'); if (shouldSpeak(turn)) speaker.say('Sorry, that did not work.'); }
      if (event.status === 'paused') hint(event.text);   // waiting for an AI to be available again: it was said when it happened
      if (event.status === 'cancelled') { wasSpeaking = false; if (voiceMode && !interrupting && !capture) setPhase('idle'); }   // you pressed Stop: wait to be asked again
      else if (!speaker.active()) { wasSpeaking = false; afterSpeech(); } else setTimeout(settle, 400);
    }
    if (event.chat === current) api('/api/chat?id=' + encodeURIComponent(current)).then(c => { if (c.id === current) { lastMessages = ''; renderChat(c); } }).catch(() => {});
    refresh().catch(() => {});
  }
}
// Something was said after "Hey JARVIS", or the Talk shortcut was pressed. The app keeps it until a window comes and takes it,
// so it reaches exactly one window and is never lost to a window that has just been closed.
let pickedUp = false, picking = Promise.resolve(), attendTimer = 0, lastTurnAt = 0;
/* The small window showing a conversation that the app window is holding in the background: its state and its words, no sound. */
function mirror(next) {
  if (!['idle', 'listening', 'thinking', 'speaking'].includes(next)) return;
  body.classList.toggle('nv-listening', next === 'listening'); body.classList.toggle('nv-thinking', next === 'thinking'); body.classList.toggle('nv-speaking', next === 'speaking');
  captions.dataset.phase = next; capState.textContent = { idle: '', listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking…' }[next];
  window.NovaCore?.set({ energy: next === 'listening' ? 0.55 : next === 'thinking' ? 0.9 : next === 'speaking' ? 0.7 : 0.25 });
  if (next === 'idle') { capYou.textContent = ''; capMe.textContent = ''; }
}
if (MINI) {
  // Two small buttons: open the app itself, and end the conversation (the window then goes away by itself).
  const bar = el('div', { class: 'nv-mini-bar' });
  const openB = el('button', { class: 'nv-icon', type: 'button', 'aria-label': 'Open JARVIS', data: { tip: 'Open JARVIS' } }, icon('full'));
  const endB = el('button', { class: 'nv-icon', type: 'button', 'aria-label': 'End', data: { tip: 'End this conversation' } }, icon('x'));
  openB.onclick = () => fetch('/api/window', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN }, body: JSON.stringify({ show: 'main' }) }).catch(() => {});
  // (A conversation shown here may be held by the app window: then that window is told to end it.)
  endB.onclick = () => { if (voiceMode) endSession(false); else api('/api/voice', { action: 'control', what: 'end' }).catch(() => {}); };
  bar.append(openB, endB); body.append(bar);
  // It can be put anywhere: taken hold of (not by a button) and moved a little, it follows the pointer until it is let go.
  // The app moves the window itself (see jcc/mini.py), so nothing has to be sent while it moves.
  let grip = null;
  addEventListener('pointerdown', e => { grip = e.button === 0 && !e.target.closest('button') ? [e.clientX, e.clientY] : null; });
  addEventListener('pointermove', e => { if (grip && Math.hypot(e.clientX - grip[0], e.clientY - grip[1]) > 4) { grip = null; api('/api/window', { mini: 'drag' }).catch(() => {}); } });
  addEventListener('pointerup', () => { grip = null; });
}
function pickUp(listenAnyway) {
  picking = picking.then(async () => {
    if (MINI && current && Date.now() - lastTurnAt > 20 * 60000) current = '';   // a new conversation, not yesterday's
    const waiting = await api('/api/voice', { action: 'pending', kind: KIND }).catch(() => ({}));
    if (waiting.text) { pickedUp = true; clearTimeout(attendTimer); A.unlock(); takeSpoken(waiting.text); }
    else if (waiting.attend) {
      // Its name was said and nothing else yet. The tray helper is already recording what comes next (so no word is lost
      // while this window gets ready) and will pass it on; if that never comes, this window listens itself.
      pickedUp = true; A.unlock(); if (!voiceMode) await setVoice(true, true);
      stopCapture(); speaker.hush(); capYou.textContent = ''; hint(''); setPhase('listening');
      clearTimeout(attendTimer); attendTimer = setTimeout(() => { if (voiceMode && !capture && !turns.size && phase === 'listening') { startedByYou = true; listen('command'); } }, 11000);
    }
    else if (waiting.listen || (listenAnyway && !pickedUp)) {
      clearTimeout(attendTimer); startedByYou = true; A.unlock();
      // Its name was said and then nothing: only then does JARVIS speak first. It listens as soon as it has asked.
      if (waiting.nudge && options.speak && !muted) { if (!voiceMode) await setVoice(true, true); stopCapture(); capYou.textContent = ''; hint(''); wantListen = true; speaker.say('Yes?'); }
      else if (!voiceMode) setVoice(true); else if (!capture) listen('command');
    }
  });
  return picking;
}
async function pump() {
  for (;;) {
    try {
      const data = await api('/api/voice/events?since=' + Math.max(0, since) + '&wait=' + (since < 0 ? 0 : 20) + '&w=' + WINDOW + '&kind=' + KIND);
      options = data.settings; showBrain(data.brain);
      if (N.lightHint !== options.light_now) { N.lightHint = options.light_now; N.applyLight?.(options.light_now); }
      if (since < 0) { since = data.next; if (data.busy) body.classList.add('nv-working'); if (data.confirm) askConfirm(data.confirm); if (data.waiting) pickUp(false); continue; }
      since = data.next; data.events.forEach(handle); if (data.waiting) pickUp(false);
    } catch { await new Promise(resolve => setTimeout(resolve, 2500)); }
  }
}

/* ---------- controls ---------- */
const dictateB = el('button', { class: 'nv-icon', id: 'nv-dictate', type: 'button', 'aria-label': 'Dictate your message', data: { tip: 'Speak your message instead of typing it' } }, icon('mic'));
const voiceB = el('button', { class: 'nv-icon', id: 'nv-voice-toggle', type: 'button', 'aria-label': 'Voice chat with JARVIS', data: { tip: 'Talk with JARVIS out loud', key: 'Ctrl+Space' } }, icon('pulse'));
N.micButton?.replaceWith(dictateB); dictateB.after(voiceB);
dictateB.onclick = () => startDictation().catch(error => { endDictation(); notify(error.message); });
voiceB.onclick = () => setVoice(!voiceMode);
talkB.onclick = () => { if (muted) muteB.click(); else toggleTalk(); };
muteB.onclick = () => { muted = !muted; muteB.classList.toggle('on', muted); muteB.querySelector('span').textContent = muted ? 'Unmute' : 'Mute'; if (muted) { stopCapture(); setPhase('idle'); } else listen('command'); };
holdB.onclick = () => { N.assistantStop().catch(() => {}); rest(); };
typeB.onclick = () => { rest(); hint(''); $('message').focus(); };
leaveB.onclick = () => setVoice(false);
document.addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '') || document.activeElement?.isContentEditable;
  if ((e.ctrlKey || e.metaKey) && e.code === 'Space') { e.preventDefault(); setVoice(!voiceMode); }
  else if (e.code === 'Space' && voiceMode && !typing && !document.querySelector('dialog[open]')) { e.preventDefault(); toggleTalk(); }
  else if (e.key === 'Escape' && voiceMode && !document.querySelector('dialog[open]')) { if (speaker.active() || turns.size || capture) holdB.click(); else setVoice(false); }
}, true);

/* ---------- settings ---------- */
// The brains the owner may pick for the assistant: left to JARVIS, one of Claude's models, or a connected AI service.
const brainChoices = () => [['auto', 'Automatic: the right model for each request (recommended)'], ['haiku', 'Claude Haiku: the quickest'], ['sonnet', 'Claude Sonnet: stronger, a little slower'],
  ['opus', 'Claude Opus: very capable, slower'], ['fable', 'Claude Fable: the most capable, uses the most allowance'],
  ...services.filter(s => s.connected && s.model && s.tools !== false).map(s => [s.id + ':' + s.model, s.name.split(' (')[0] + ': ' + s.model.split('/').pop()])];
const row = (label, control, note) => '<label class="nv-field"><span>' + label + (note ? '<small>' + note + '</small>' : '') + '</span>' + control + '</label>';
const check = (id, label, note) => '<label class="assistant-check"><input type="checkbox" id="' + id + '"> <span>' + label + (note ? '<small>' + note + '</small>' : '') + '</span></label>';
const pick = (id, entries) => '<select id="' + id + '">' + entries.map(([value, text]) => '<option value="' + esc(value) + '">' + esc(text) + '</option>').join('') + '</select>';
// The sections of Settings, in groups as Claude has them, and the words each can be found by.
const SECTIONS = [[['connect', 'Connections', 'keys'], ['models', 'AI models & accounts', 'spark'], ['usage', 'Usage', 'clock']],
  [['appearance', 'Appearance', 'palette'], ['assistant', 'Assistant', 'shield'], ['voice', 'Voice', 'mic'], ['email', 'Email', 'note'], ['people', 'Assistants', 'layers']],
  [['skills', 'Skills', 'box'], ['mods', 'Customize', 'sliders'], ['updates', 'Updates', 'retry']],
  [['everyday', 'Everyday use', 'gear'], ['memory', 'Chats & memory', 'note'], ['advanced', 'Advanced', 'code']]];
const FINDS = { everyday: 'text size movement startup sign in windows project preferences workspace desktop app', memory: 'chats import export backup restore memory browser connection history',
  advanced: 'expert terminal diagnostics developer tools controls', appearance: 'theme dark light colour color chat view transcript verbose steps detail', connect: 'keys api claude codex groq gemini openai elevenlabs perplexity connect sign in microphone muted helpers', models: 'model ai gpt claude chatgpt codex account sign in log in subscription api key research who answers fast',
  usage: 'allowance tokens cost spend limits left', assistant: 'mode permissions ask auto manual plan bypass pc control computer persona name light theme sleep standin resume',
  voice: 'microphone speakers listening speaking wake word hey jarvis language whisper dictation sound', email: 'mail gmail outlook send', people: 'assistants personas helpers',
  skills: 'skills packs scan install', mods: 'commands hooks panels status line slash mods', updates: 'version update install restart signed' };
async function openSettings(tab = 'assistant') {
  await loadSpeech();
  // Laid out like Claude's settings: the sections in a list on the left (with a search), the one chosen on the right.
  const nav = SECTIONS.map(group => group.map(([id, label, glyph]) => '<button type="button" data-tab="' + id + '">' + icon(glyph) + '<span>' + label + '</span></button>').join('')).join('<hr>');
  const d = dialog('<div class="nv-set-head"><h2>Settings</h2><button class="nv-icon" data-close aria-label="Close">' + icon('x') + '</button></div>' +
    '<div class="nv-set-main"><aside class="nv-set-side"><label class="nv-set-search">' + icon('search') + '<input type="search" placeholder="Search" aria-label="Search settings"></label>' +
    '<nav class="nv-set-tabs">' + nav + '</nav><button type="button" class="nv-set-foot" data-keys>API keys' + icon('arrow') + '</button></aside><section class="nv-set-right"><h3 class="nv-set-title"></h3><div class="nv-set-body"></div></section></div>', 'nv-settings');
  const pane = d.querySelector('.nv-set-body'), saved = () => notify('Saved.');
  let showing = '';   // the tab on screen. A tab that was waiting for an answer checks this before it draws, so it never writes over another tab.
  d.querySelector('[data-close]').onclick = () => d.close();
  const plugged = () => { if (pane.isConnected && pane.querySelector('#vs-mic')) voiceTab(); };   // something was plugged in or pulled out: show the new list
  window.addEventListener('nova-devices', plugged); d.addEventListener('close', () => window.removeEventListener('nova-devices', plugged));
  const setSpeech = async values => {
    try { speech = { ...speech, ...(await api('/api/speech', { action: 'settings', settings: values })) }; await A.use(speech.settings.mic || '', speech.settings.speaker || '').catch(() => {}); saved(); micSync(); }
    catch (error) { toast(error.message); }
  };
  const setAssistant = async values => { try { options = { ...options, ...(await api('/api/voice', { action: 'settings', settings: values })) }; saved(); } catch (error) { toast(error.message); } };
  const bind = (id, read, write, apply) => { const node = pane.querySelector('#' + id); if (!node) return; if (node.type === 'checkbox') node.checked = !!read; else node.value = read ?? ''; node.onchange = () => apply({ [write]: node.type === 'checkbox' ? node.checked : node.value }); };

  async function voiceTab() {
    const s = speech.settings, listenNames = { whisper: speech.whisper_label || 'Whisper', eleven: 'ElevenLabs live transcription', browser: 'the listening built into this window' };
    const browserVoices = (window.speechSynthesis ? speechSynthesis.getVoices() : []).filter(v => v.lang.toLowerCase().startsWith((navigator.language || 'en').split('-')[0].toLowerCase()));
    let voices = []; if (speech.configured) { try { voices = (await api('/api/speech/voices')).voices; } catch (error) { toast(error.message); } }
    const usage = speech.usage ? (speech.usage.plan ? speech.usage.plan[0].toUpperCase() + speech.usage.plan.slice(1) + ' plan · ' : '') + speech.usage.percent + '% of this month’s allowance used' : 'Connected';
    // Microphones and speakers, by the names Windows gives them. The Windows default comes first and is the default.
    const sound = await A.devices().catch(() => ({ mics: [], speakers: [], named: false }));
    if (showing !== 'voice') return;
    const choices = (list, chosen, usual) => [['', 'Windows default' + (usual ? ' — ' + usual : '')], ...list.map(d => [d.name, d.name]),
      ...(chosen && !list.some(d => d.name === chosen) ? [[chosen, chosen + ' (not connected: using the Windows default)']] : [])];
    const soundRows = '<h3>Microphone and speakers</h3>' +
      row('Microphone', pick('vs-mic', choices(sound.mics, s.mic, sound.defaultMic)), 'Used for voice chat, dictation and “Hey JARVIS”') +
      (speech.mic_muted ? '<p class="small nv-muted-mic"><b>Windows has this microphone muted</b>, so JARVIS hears nothing. ' +
        '<button class="plain" type="button" data-unmute>' + icon('mic') + 'Unmute</button></p>' : '') +
      row('Speakers', pick('vs-speaker', choices(sound.speakers, s.speaker, sound.defaultSpeaker)), 'Where JARVIS speaks and plays its sounds') +
      '<div class="nv-sound"><button class="plain" type="button" data-mic-test>' + icon('mic') + 'Test the microphone</button><div class="nv-meter hidden" aria-hidden="true"><i></i></div>' +
      '<button class="plain" type="button" data-speaker-test>' + icon('speak') + 'Test the speakers</button></div>' +
      (sound.named ? '' : '<p class="small">Device names appear once JARVIS has been allowed to use the microphone. Press “Test the microphone” to allow it.</p>') +
      // (Telling you from a film in the room needs the untouched listener, which the browser gives for the Windows default microphone only.)
      ((A.micOn && !A.truly) || (s.mic && sound.defaultMic && s.mic !== sound.defaultMic) ? '<p class="small">With a film or music playing in the room, JARVIS tells your voice from it by how near you are. That works with the microphone Windows uses by default. With this one, start with “' +
        esc(options.assistant?.name || 'JARVIS') + '” while something is playing.</p>' : '');
    pane.innerHTML = '<div class="nv-status"><div><b>Listening</b><span>' + esc(listenNames[engine()] || 'not available') + '</span></div><div><b>Speaking</b><span>' +
      (speech.speak === 'eleven' ? 'ElevenLabs' + (s.voice_name ? ' · ' + esc(s.voice_name) : '') : A.speakerChosen ? 'Windows’ own voice, on your chosen speakers' : 'the voice built into this window') + '</span></div><button class="plain" data-test>' + icon('speak') + 'Test both</button></div><div class="nv-test hidden"></div>' +
      soundRows + '<h3>Listening</h3>' +
      row('How JARVIS hears you', pick('vs-listen', [['auto', 'Automatic (best available)'], ['whisper', 'Whisper' + (speech.whisper ? '' : ' (needs a free Groq key)')], ['eleven', 'ElevenLabs live' + (speech.configured ? '' : ' (needs your key)')], ['browser', 'Built in (no key needed)']])) +
      row('The language you speak', pick('vs-language', Object.entries(speech.languages || { en: 'English' }))) +
      row('Names and unusual words', '<input id="vs-words" maxlength="300" placeholder="For example: Asha, Jaipur, Zerodha">', 'Helps JARVIS spell them correctly') +
      '<h3>Speaking</h3>' + check('vs-speak', 'Speak replies out loud in voice chat') +
      check('vs-duck', 'Lower other sounds while you talk to JARVIS', 'Other programs get quieter while JARVIS listens, and go back to normal as soon as it thinks, works or speaks. JARVIS’s own voice is never lowered.') +
      (speech.configured
        ? row('Voice', pick('vs-voice', [...(s.voice_id && !voices.some(v => v.id === s.voice_id) ? [[s.voice_id, s.voice_name || 'Your chosen voice']] : []), ...voices.map(v => [v.id, v.name + (v.about ? ' — ' + v.about : '')])])) +
          row('Or paste a voice ID', '<input id="vs-voiceid" maxlength="40" spellcheck="false" placeholder="From a voice’s page in ElevenLabs">', 'For a voice that is not in the list') + row('Style', pick('vs-model', Object.entries(speech.models || {}))) +
          row('Speed', pick('vs-speed', [['0.85', 'Slower'], ['1', 'Normal'], ['1.1', 'A little faster'], ['1.2', 'Fastest']]))
        : A.speakerChosen
        ? '<p class="small">On chosen speakers JARVIS speaks with Windows’ own voice. The more natural voices built into this window can only play on the Windows default; an ElevenLabs voice plays on any speakers.</p>' +
          row('Speed', pick('vs-speed', [['0.85', 'Slower'], ['1', 'Normal'], ['1.1', 'A little faster'], ['1.2', 'Fastest']]))
        : row('Voice', pick('vs-bvoice', browserVoices.map(v => [v.name, v.name.replace(/Microsoft | Online \(Natural\)/g, '') + (/natural/i.test(v.name) ? ' · natural' : '')]))) +
          row('Speed', pick('vs-brate', [['0.9', 'Slower'], ['1.05', 'Normal'], ['1.2', 'Faster'], ['1.4', 'Fastest']]))) +
      '<h3>Conversation</h3>' + check('vs-hands', 'Keep listening after each reply', 'A natural back-and-forth. Switch off to tap the microphone each time.') +
      row('Go to sleep after', pick('vs-sleep', [['1', '1 minute'], ['5', '5 minutes'], ['15', '15 minutes'], ['30', '30 minutes'], ['60', '1 hour'], ['0', 'Never: only when I say “go to sleep”']]),
        'With nothing being done and nothing new asked. “Hey JARVIS” wakes it again.') +
      '<p class="small">Say <b>stop</b> to end what JARVIS is doing or saying, <b>go to sleep</b> to make it wait for its name, and <b>end session</b> to leave voice chat. ' +
      'While a video, a film or music is playing on this PC, JARVIS ignores that sound and only takes what you say to it by name.</p>' +
      check('vs-barge', 'Let me interrupt by talking', 'JARVIS falls silent the moment you start, and “stop” ends what it is saying. While it is working, saying its name or a correction (“no, I meant…”) stops the work and takes the new request. Use headphones if it cuts itself off.') +
      check('vs-duck', 'Turn the PC’s sound down while I speak', 'After “Hey JARVIS”, a film or music playing on this PC is turned down until you have finished speaking, so it does not drown what you say.') +
      check('vs-wake', 'Wake word: say “Hey JARVIS” at any time', (speech.shortcuts && speech.shortcuts.wake_problem ? esc(speech.shortcuts.wake_problem) + ' ' : speech.shortcuts && speech.shortcuts.wake ? 'Listening now' + (speech.shortcuts.wake_mic ? ' on ' + esc(speech.shortcuts.wake_mic) : '') + '. ' : '') +
        'JARVIS listens on this PC only, even with this window closed. Nothing is sent anywhere until it hears its name; then that one sentence is transcribed. Windows shows the microphone as in use while this is on.') +
      check('vs-sounds', 'Soft sounds when listening starts and stops') +
      '<h3>From anywhere in Windows</h3><div class="nv-keys">' + [['Talk to JARVIS', 'Ctrl+Alt+Space', 'talk'], ['Dictate into the app you are using', 'Ctrl+Alt+D', 'dictate'], ['Open JARVIS', 'Ctrl+Alt+J', 'open'], ['Stop everything', 'Ctrl+Alt+Backspace', 'stop']]
        .map(([what, usual, name]) => { const now = (speech.shortcuts || {}).keys, missing = now && !now[name]; return '<span>' + what + (missing ? '<small> — not available: other apps use these shortcuts</small>' : '') + '</span><kbd>' + esc(((now && now[name]) || usual).replace(/\+/g, ' + ')) + '</kbd>'; }).join('') + '</div>' +
      '<h3>ElevenLabs natural voice</h3>' + (speech.configured
        ? '<p class="nv-ok">' + icon('check') + esc(usage) + '</p><div class="actions"><button class="plain" data-forget>Remove key</button></div>'
        : '<p>A paid ElevenLabs plan gives JARVIS a far more natural voice. Create a key at elevenlabs.io (Developers, then API Keys) and paste it here. It is kept in Windows Credential Manager, never in a file or a chat.</p>' +
          '<div class="nv-keyrow"><input id="vs-key" type="password" autocomplete="off" spellcheck="false" placeholder="Paste your ElevenLabs key"><button class="primary" data-key>Connect</button></div>');
    bind('vs-listen', s.listen, 'listen', setSpeech); bind('vs-language', s.language, 'language', setSpeech); bind('vs-words', s.words, 'words', setSpeech);
    const setSound = async values => { await setSpeech(values); if (pane.isConnected && pane.querySelector('#vs-mic')) voiceTab(); };   // redraw: the voice rows depend on the speakers
    bind('vs-mic', s.mic, 'mic', setSound); bind('vs-speaker', s.speaker, 'speaker', setSound);
    const unmute = pane.querySelector('[data-unmute]');
    if (unmute) unmute.onclick = async () => {   // its owner pressed Unmute: Windows unmutes the microphone JARVIS uses
      unmute.disabled = true;
      try {
        const done = await api('/api/speech', { action: 'unmute' });
        speech.mic_muted = !!done.mic_muted;
        notify(done.ok ? 'The microphone is unmuted.' : 'Windows did not unmute the microphone. Unmute it in Windows: Settings, System, Sound, Input.');
      } catch (error) { toast(error.message); }
      voiceTab();
    };
    const meter = pane.querySelector('.nv-meter'), micTest = pane.querySelector('[data-mic-test]');
    micTest.onclick = async () => {   // ten seconds of a moving bar, so you can see that the chosen microphone hears you
      if (meterTimer) return;
      try { await A.micStart(); } catch (error) { return toast(error.message); }
      if (!sound.named) { micSync(); voiceTab(); return; }         // the names are known now: show them
      const borrowed = !routed, stop = borrowed ? A.hear(() => {}) : null, until = Date.now() + 10000;
      meter.classList.remove('hidden'); micTest.lastChild.textContent = 'Speak now…';
      meterTimer = setInterval(() => {
        const bar = meter.firstElementChild; if (bar) bar.style.width = Math.min(100, Math.round(Math.sqrt(A.micLevel) * 260)) + '%';
        if (Date.now() > until || !meter.isConnected) { clearInterval(meterTimer); meterTimer = 0; if (stop) stop(); meter.classList.add('hidden'); if (micTest.isConnected) micTest.lastChild.textContent = 'Test the microphone'; micSync(); }
      }, 60);
    };
    pane.querySelector('[data-speaker-test]').onclick = () => { A.unlock(); speaker.hush(); speaker.retry(); chime('notice'); setTimeout(() => speaker.say('This is how I sound on these speakers.'), 700); };
    bind('vs-speak', options.speak, 'speak', setAssistant); bind('vs-duck', options.duck !== false, 'duck', setAssistant); bind('vs-hands', options.hands_free, 'hands_free', setAssistant);
    const sleep = pane.querySelector('#vs-sleep'); if (sleep) { sleep.value = String(options.sleep_minutes ?? 15); sleep.onchange = () => setAssistant({ sleep_minutes: Number(sleep.value) }); }
    bind('vs-barge', s.barge_in, 'barge_in', setSpeech); bind('vs-wake', s.wake, 'wake', setSpeech); bind('vs-sounds', s.sounds, 'sounds', setSpeech);
    bind('vs-duck', s.duck !== false, 'duck', setSpeech);
    bind('vs-model', s.tts_model, 'tts_model', setSpeech);
    const speed = pane.querySelector('#vs-speed'); if (speed) { speed.value = String(s.speed); speed.onchange = () => setSpeech({ speed: Number(speed.value) }); }
    const voice = pane.querySelector('#vs-voice'); if (voice) { voice.value = s.voice_id || voices[0]?.id || ''; voice.onchange = () => setSpeech({ voice_id: voice.value, voice_name: voice.selectedOptions[0].textContent.split(' — ')[0] }); }
    const pasted = pane.querySelector('#vs-voiceid');
    if (pasted) pasted.onchange = async () => {
      const id = pasted.value.trim(); if (!id) return;
      if (!/^[A-Za-z0-9]{8,40}$/.test(id)) return toast('A voice ID is about twenty letters and numbers, copied from the voice’s page in ElevenLabs.');
      await setSpeech({ voice_id: id, voice_name: voices.find(v => v.id === id)?.name || 'Your chosen voice' }); voiceTab();
    };
    const local = pane.querySelector('#vs-bvoice'); if (local) { local.value = pickVoice()?.name || ''; local.onchange = () => { store.set('nv-voice-name', local.value); saved(); }; }
    const rate = pane.querySelector('#vs-brate'); if (rate) { rate.value = store.get('nv-voice-rate', '1.05'); rate.onchange = () => { store.set('nv-voice-rate', rate.value); saved(); }; }
    const connect = pane.querySelector('[data-key]');
    if (connect) connect.onclick = async () => {
      const input = pane.querySelector('#vs-key'); connect.disabled = true; connect.textContent = 'Checking…';
      try { speech = { ...speech, ...(await api('/api/speech', { action: 'key', which: 'elevenlabs', value: input.value })) }; input.value = ''; speaker.retry(); await loadSpeech(); notify('ElevenLabs is connected.'); voiceTab(); }
      catch (error) { toast(error.message); connect.disabled = false; connect.textContent = 'Connect'; }
    };
    const forget = pane.querySelector('[data-forget]');
    if (forget) forget.onclick = async () => { if (!(await N.confirmBox({ title: 'Remove the ElevenLabs key?', text: 'JARVIS will go back to the built-in voice. You can add the key again at any time.', ok: 'Remove', danger: true }))) return; try { await api('/api/speech', { action: 'forget', which: 'elevenlabs' }); await loadSpeech(); voiceTab(); } catch (error) { toast(error.message); } };
    pane.querySelector('[data-test]').onclick = async e => {
      const button = e.currentTarget;   // (kept: once the event is over the browser no longer says which button it was)
      const out = pane.querySelector('.nv-test'); button.disabled = true; out.classList.remove('hidden'); out.textContent = 'Checking… this takes a few seconds.';
      A.unlock(); speaker.hush(); speaker.retry(); speaker.say('Hello. This is how I sound.');
      try {
        const report = await api('/api/speech', { action: 'test' }), lines = [];
        if (report.listening) lines.push(report.listening.ok ? 'Listening works: a test sentence was understood in ' + report.listening.seconds + ' seconds.' : 'Listening problem: ' + (report.listening.problem || 'the test sentence was heard as “' + report.listening.heard + '”.'));
        if (report.speaking) lines.push(report.speaking.ok ? 'The ElevenLabs voice works: sound started after ' + report.speaking.first_audio_seconds + ' seconds.' : 'Voice problem: ' + report.speaking.problem);
        out.innerHTML = lines.map(line => '<p>' + esc(line) + '</p>').join('');
      } catch (error) { out.textContent = error.message; }
      button.disabled = false;
    };
  }
  function assistantTab() {
    pane.innerHTML = '<h3>What JARVIS may do</h3>' + check('as-pc', 'Let JARVIS control this computer', 'Open apps, press buttons, type, run commands and manage files') +
      row('Mode', pick('as-ask', [['sending', 'Auto (recommended)'], ['all', 'Manual'], ['edits', 'Accept edits'], ['plan', 'Plan'], ['bypass', 'Bypass permissions'],
        ...(options.ask === 'risky' ? [['risky', 'Ask before risky things (older setting)']] : [])]),
        'How much JARVIS asks before it acts, as in Claude Code. Also the chip in the message bar, and Shift+Tab there. You can answer out loud: “yes” or “no”') +
      '<p class="small nv-never">' + SHIELD + '<span>Never done, whatever you choose: typing passwords or card numbers, reading saved passwords, and acting on banking, payment or password-manager windows. In every mode but Bypass permissions, JARVIS asks before paying, sending a message or email, deleting, and commands that install or download something. With Bypass permissions it asks nothing.</span></p>' +
      '<h3>About you</h3><label>Anything JARVIS should always keep in mind<textarea id="as-persona" rows="3" maxlength="1200" placeholder="For example: Call me Sam. Keep answers short. I am learning Python."></textarea></label>' +
      '<p class="small">JARVIS also remembers things you tell it (“remember that…”). They are in the note <b>System / JARVIS Memory</b> in your vault, where you can read and edit them.</p>' +
      '<h3>This computer</h3>' + row('Light mode', pick('as-light', [['auto', 'Automatic (on for PCs with 8 GB or less)'], ['on', 'On — use less memory'], ['off', 'Off']]), 'Fewer effects and only one AI kept ready');
    bind('as-pc', options.pc_control, 'pc_control', setAssistant); bind('as-ask', options.ask, 'ask', values => setAssistant(values).then(() => N.permissionsChanged?.()));
    bind('as-persona', options.persona, 'persona', setAssistant); bind('as-light', options.light, 'light', setAssistant);
  }
  async function peopleTab() {
    let data; try { data = await api('/api/assistants'); } catch (error) { if (showing === 'people') pane.textContent = error.message; return; }
    if (showing !== 'people') return;
    pane.innerHTML = '<p>Give JARVIS different roles, each with its own name, instructions and voice. The one in use answers every new message and its name is the wake word.</p><div class="nv-people">' +
      data.items.map(a => '<div class="nv-person' + (a.id === data.active ? ' on' : '') + '"><div><b>' + esc(a.name) + '</b><small>' + esc(a.instructions ? a.instructions.slice(0, 90) : a.id === 'jarvis' ? 'Your everyday assistant' : 'No special instructions') + '</small></div>' +
        (a.id === data.active ? '<span class="nv-tag">In use</span>' : '<button class="plain" data-use="' + esc(a.id) + '">Use</button>') + '<button class="nv-icon" data-edit="' + esc(a.id) + '" aria-label="Edit">' + icon('edit') + '</button></div>').join('') +
      '</div><div class="actions"><button class="primary" data-add>' + icon('plus') + 'New assistant</button></div>';
    pane.querySelectorAll('[data-use]').forEach(b => b.onclick = async () => { try { await api('/api/assistants', { action: 'use', id: b.dataset.use }); saved(); peopleTab(); } catch (error) { toast(error.message); } });
    const edit = async (item) => {
      let voices = []; if (speech.configured) { try { voices = (await api('/api/speech/voices')).voices; } catch {} }
      if (showing !== 'people') return;
      pane.innerHTML = '<h3>' + (item.id ? 'Edit ' + esc(item.name) : 'New assistant') + '</h3>' + row('Name', '<input id="pe-name" maxlength="40" placeholder="For example: Coach">') +
        '<label>What should this assistant be like?<textarea id="pe-text" rows="5" maxlength="2000" placeholder="For example: You are my strict study coach. Keep me on my plan, quiz me, and never let me skip maths."></textarea></label>' +
        row('AI model', pick('pe-model', [['', 'Same as usual'], ...brainChoices().slice(1)])) +
        (voices.length ? row('Voice', pick('pe-voice', [['', 'Same as usual'], ...voices.map(v => [v.id, v.name])])) : '') +
        '<div class="actions">' + (item.id && item.id !== 'jarvis' ? '<button class="plain" data-remove>Remove</button>' : '') + '<button class="plain" data-back>Cancel</button><button class="primary" data-save>Save</button></div>';
      pane.querySelector('#pe-name').value = item.name || ''; pane.querySelector('#pe-text').value = item.instructions || ''; pane.querySelector('#pe-model').value = item.model || '';
      const voice = pane.querySelector('#pe-voice'); if (voice) voice.value = item.voice_id || '';
      pane.querySelector('[data-back]').onclick = peopleTab;
      pane.querySelector('[data-save]').onclick = async () => {
        try { await api('/api/assistants', { action: 'save', assistant: { id: item.id || undefined, name: pane.querySelector('#pe-name').value, instructions: pane.querySelector('#pe-text').value, model: pane.querySelector('#pe-model').value,
          voice_id: voice?.value || '', voice_name: voice?.value ? voice.selectedOptions[0].textContent : '', use: !item.id } }); saved(); peopleTab(); } catch (error) { toast(error.message); }
      };
      const remove = pane.querySelector('[data-remove]');
      if (remove) remove.onclick = async () => { if (!(await N.confirmBox({ title: 'Remove ' + item.name + '?', text: 'Its instructions will be deleted. Your chats stay.', ok: 'Remove', danger: true }))) return; try { await api('/api/assistants', { action: 'remove', id: item.id }); peopleTab(); } catch (error) { toast(error.message); } };
    };
    pane.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => edit(data.items.find(a => a.id === b.dataset.edit)));
    pane.querySelector('[data-add]').onclick = () => edit({});
  }
  async function emailTab() {
    let mail = speech.mail || {}; try { mail = await api('/api/mail'); } catch {}
    if (showing !== 'email') return;
    pane.innerHTML = mail.connected
      ? '<p class="nv-ok">' + icon('check') + 'Connected as ' + esc(mail.address) + '</p><p>When you ask JARVIS to send an email, it shows you the exact message, waits for your yes, and then sends it from this address.</p><div class="actions"><button class="plain" data-off>Disconnect</button></div>'
      : '<p>Without a connected account, JARVIS writes the message where you write your mail, shows it to you as a draft, and sends it once you say yes.</p>' +
        row('Write my emails in', pick('em-through', [['auto', 'Automatic: Gmail if I use it, otherwise my mail app'], ['gmail', 'Gmail, in my browser'], ['app', 'The mail app on this PC (Outlook, Mail)']]),
          'You can also just say “in Gmail” or “with Outlook”') +
        '<h3>Or connect an account</h3><p>Then JARVIS sends directly, without opening anything. It still shows you the exact message and waits for your yes.</p>' +
        row('Your email address', '<input id="em-address" type="email" autocomplete="off" placeholder="you@gmail.com">') + row('Your name', '<input id="em-name" maxlength="60" placeholder="Shown as the sender">') +
        row('App password', '<input id="em-pass" type="password" autocomplete="off" spellcheck="false">', 'Not your normal password') +
        '<details class="nv-how"><summary>How to get an app password</summary><p><b>Gmail:</b> turn on 2-Step Verification in your Google Account, then open myaccount.google.com/apppasswords, create one called JARVIS, and paste the 16 letters here.</p><p><b>Yahoo, iCloud, Zoho:</b> look for “app password” in the account’s security settings.</p><p><b>Outlook and Hotmail</b> no longer allow this; JARVIS uses your mail app for those.</p><p>The password is kept in Windows Credential Manager, never in a file or a chat.</p></details>' +
        '<div class="actions"><button class="primary" data-on>Connect</button></div>';
    const off = pane.querySelector('[data-off]'), on = pane.querySelector('[data-on]');
    bind('em-through', options.mail || 'auto', 'mail', setAssistant);
    if (off) off.onclick = async () => { try { await api('/api/mail', { action: 'disconnect' }); emailTab(); } catch (error) { toast(error.message); } };
    if (on) on.onclick = async () => {
      on.disabled = true; on.textContent = 'Checking…';
      try { await api('/api/mail', { action: 'connect', address: pane.querySelector('#em-address').value, password: pane.querySelector('#em-pass').value, name: pane.querySelector('#em-name').value }); notify('Email is connected.'); emailTab(); }
      catch (error) { toast(error.message); on.disabled = false; on.textContent = 'Connect'; }
    };
  }
  /* The skills library: packs of playbooks for the coding agents. Every pack is scanned before it is kept; its owner decides what is switched on. */
  const VERDICT = { SAFE: ['ok', 'Scanned: nothing found'], CAUTION: ['needed', 'Scanned: caution'], DO_NOT_INSTALL: ['problem', 'Scanned: do not install as a whole'] };
  async function skillsTab(open = '') {
    let data; try { data = await api('/api/skills', { action: 'list' }); } catch (error) { if (showing === 'skills') pane.textContent = error.message; return; }
    if (showing !== 'skills') return;
    const adding = data.adding || {}, busy = adding.status === 'working';
    const one = p => {
      const [state, words] = VERDICT[p.verdict.recommendation] || [p.verdict.safe ? 'ok' : 'needed', 'Scanned'];
      const counts = Object.entries(p.counts).filter(([, n]) => n).map(([kind, n]) => n + ' ' + kind + (n === 1 ? '' : 's')).join(', ');
      return '<div class="nv-link nv-pack" data-id="' + esc(p.id) + '" data-state="' + state + '"><span class="nv-dot"></span><div class="nv-link-text"><b>' + esc(p.name) + '</b>' +
        '<small>' + esc(counts) + ' · from ' + esc(p.source) + '</small><span class="nv-link-status">' + esc(words) + ' (risk ' + p.verdict.score + ' of 100, ' + (p.verdict.mode === 'full' ? 'deep scan' : 'quick scan') + ')</span>' +
        '<small>' + p.clean + ' with nothing found, ' + p.flagged + ' flagged' + (p.unscanned ? ', ' + p.unscanned + ' not scanned (kept off)' : '') + '. <b>' + p.on + ' switched on.</b></small>' +
        (p.verdict.complete === false || p.unscanned ? '<small>The scan of this pack did not finish' + (p.unscanned ? ' for ' + p.unscanned + ' of its items' : '') + '. “Scan again” goes through it a part at a time.</small>' : '') + '</div>' +
        '<div class="nv-link-do"><button class="primary" data-clean' + (p.clean ? '' : ' disabled') + '>Switch on the clean ones</button><button class="plain" data-details>Choose</button>' +
        (p.on ? '<button class="plain" data-off>All off</button>' : '') + '<button class="plain" data-rescan' + (busy || !data.scanner ? ' disabled' : '') + '>Scan again</button><button class="plain" data-remove>Remove</button></div></div>';
    };
    pane.innerHTML = '<p>Playbooks, reviewers, commands and rules that people share for coding agents. When a coding job starts, JARVIS offers the agent the few that fit the task. ' +
      'A library of hundreds costs a job a few dozen tokens: an agent only reads the one it needs.</p>' +
      (data.scanner ? '' : '<p class="nv-careful-note">' + SHIELD + '<span>SkillSpector is not installed, so nothing can be added: JARVIS never keeps a pack that has not been scanned.</span></p>') +
      '<h3>Add a pack</h3><div class="nv-keyrow"><input id="sk-source" spellcheck="false" placeholder="https://github.com/… or a folder or .zip on this PC"' + (busy ? ' disabled' : '') + '><button class="primary" data-add' + (busy || !data.scanner ? ' disabled' : '') + '>' + (busy ? 'Scanning…' : 'Scan and add') + '</button></div>' +
      '<p class="small">The pack is fetched once and scanned with SkillSpector. It is added switched off; you choose what to use. Nothing in a pack is ever run: hooks and scripts are left out.</p>' +
      (busy ? '<p class="small" role="status"><i class="nv-spin"></i> ' + esc(adding.step || 'Fetching and scanning ' + (adding.source || 'the pack') + '…') +
        ' A large pack is scanned a part at a time and can take up to an hour; you can keep using JARVIS meanwhile.</p>' : '') +
      (adding.status === 'failed' ? '<p class="nv-careful-note">' + SHIELD + '<span>' + esc(adding.error) + '</span></p>' : '') +
      '<h3>Your packs</h3>' + (data.packs.length ? data.packs.map(one).join('') : '<p class="small">None yet.</p>') + '<div class="nv-pack-items"></div>';
    if (busy) setTimeout(() => { if (showing === 'skills' && pane.isConnected) skillsTab(open); }, 2500);
    const add = pane.querySelector('[data-add]'), source = pane.querySelector('#sk-source');
    add.onclick = async () => { if (!source.value.trim()) return source.focus(); try { await api('/api/skills', { action: 'add', source: source.value.trim() }); skillsTab(); } catch (error) { toast(error.message); } };
    source.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); add.click(); } };
    const act = async (payload, done) => { try { const got = await api('/api/skills', payload); if (done) notify(done(got)); skillsTab(payload.action === 'remove' ? '' : payload.id); } catch (error) { toast(error.message); } };
    for (const line of pane.querySelectorAll('.nv-pack')) {
      const id = line.dataset.id, pack = data.packs.find(p => p.id === id);
      line.querySelector('[data-clean]').onclick = async () => {
        if (pack.needs_owner && !(await N.confirmBox({ title: 'Use the clean items of ' + pack.name + '?', ok: 'Switch them on',
          text: 'SkillSpector’s verdict on this pack as a whole is “' + pack.verdict.recommendation.replace(/_/g, ' ').toLowerCase() + '” (risk ' + pack.verdict.score + ' of 100), because of the ' + pack.flagged +
            ' flagged items. The ' + pack.clean + ' items in which nothing was found would be switched on; the flagged ones stay off.' }))) return;
        act({ action: 'switch', id, on: true }, got => got.changed + ' switched on.');
      };
      const off = line.querySelector('[data-off]'); if (off) off.onclick = () => act({ action: 'switch', id, on: false }, () => 'All switched off.');
      line.querySelector('[data-rescan]').onclick = async () => {
        if (!(await N.confirmBox({ title: 'Scan ' + pack.name + ' again?', ok: 'Scan again',
          text: 'Every item is scanned afresh with SkillSpector, a part at a time. With hundreds of items that takes up to an hour. What is switched on stays on only if it is still found clean.' }))) return;
        try { await api('/api/skills', { action: 'rescan', id }); skillsTab(); } catch (error) { toast(error.message); }
      };
      line.querySelector('[data-remove]').onclick = async () => { if (await N.confirmBox({ title: 'Remove ' + pack.name + '?', text: 'Its files are removed from JARVIS. You can add it again later.', ok: 'Remove', danger: true })) act({ action: 'remove', id }); };
      line.querySelector('[data-details]').onclick = () => details(id);
    }
    async function details(id) {
      const box = pane.querySelector('.nv-pack-items'); box.textContent = 'Loading…';
      let pack; try { pack = await api('/api/skills', { action: 'pack', id }); } catch (error) { box.textContent = error.message; return; }
      const draw = filter => {
        const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
        const rows = pack.items.filter(i => words.every(w => (i.name + ' ' + i.description + ' ' + i.kind).toLowerCase().includes(w))).slice(0, 120);
        box.querySelector('.nv-pack-list').innerHTML = rows.map(i => '<label class="nv-skill" data-risk="' + i.risk + '"><input type="checkbox" data-name="' + esc(i.name) + '" data-kind="' + i.kind + '"' + (i.on ? ' checked' : '') + (i.risk === 'unscanned' ? ' disabled title="Not scanned yet, so it cannot be used. Scan the pack again."' : '') + '>' +
          '<span><b>' + esc(i.name) + '</b> <em>' + i.kind + '</em>' + (i.risk === 'clean' ? '' : i.risk === 'unscanned' ? '<i class="nv-flag">not scanned</i>' : '<i class="nv-flag">' + i.found + ' flagged</i>') + '<small>' + esc(i.description || 'No description') + '</small>' +
          (i.findings?.length ? '<small class="nv-found">' + i.findings.slice(0, 3).map(f => esc(f.severity + ': ' + f.kind + ' (' + f.what + ')')).join(' · ') + '</small>' : '') + '</span></label>').join('') ||
          '<p class="small">Nothing matches.</p>';
        box.querySelectorAll('.nv-skill input').forEach(input => input.onchange = async () => {
          const item = pack.items.find(i => i.name === input.dataset.name && i.kind === input.dataset.kind), flagged = item.risk !== 'clean';
          if (input.checked && flagged && !(await N.confirmBox({ title: 'Use ' + item.name + ' although it was flagged?', ok: 'Use it anyway', danger: true,
            text: 'SkillSpector found: ' + item.findings.map(f => f.severity + ' ' + f.kind + ' (' + f.what + ')').join('; ') + '. Only switch it on if you have read it and trust it.' }))) { input.checked = false; return; }
          try { await api('/api/skills', { action: 'switch', id, names: [item.name], kind: item.kind, on: input.checked, flagged }); item.on = input.checked; saved(); }
          catch (error) { input.checked = !input.checked; toast(error.message); }
        });
      };
      box.innerHTML = '<h3>' + esc(pack.name) + '</h3><input class="nv-pack-find" placeholder="Search these ' + pack.items.length + ' items" aria-label="Search">' + '<div class="nv-pack-list"></div>';
      box.querySelector('.nv-pack-find').oninput = event => draw(event.target.value);
      draw(''); box.scrollIntoView({ block: 'nearest' });
    }
    if (open && data.packs.some(p => p.id === open)) details(open);
  }
  /* Which AI answers, and the other AI services that can stand in for it. */
  async function modelsTab(opened = '') {
    // Drawn at once from what is already known. Then the list is read again, with a look for model servers running on
    // this PC (a few seconds when there is none), and drawn again, unless a key is being typed in at that moment.
    const known = services.length > 0;
    if (known) drawModels(opened, true);
    await loadServices(true);
    if (showing !== 'models' || !pane.isConnected) return;
    const typing = [...pane.querySelectorAll('.nv-keyrow:not(.hidden) input')].some(input => input.value || input === document.activeElement);
    if (known && typing) return void pane.querySelector('.nv-set-wait')?.remove();
    if (!services.length) {
      pane.innerHTML = '<p class="nv-ct-warn">The list of AI services could not be read' + (servicesProblem ? ': ' + esc(servicesProblem) : '.') + '</p><div class="settings-buttons"><button class="plain" data-again>Try again</button></div>';
      pane.querySelector('[data-again]').onclick = () => show('models');
      return;
    }
    drawModels(opened, false);
  }
  // After connecting or disconnecting one: the list as it is now, without looking round the PC again.
  const refreshModels = async () => { await loadServices(false); if (showing === 'models' && pane.isConnected) drawModels('', false); };
  // Accounts (jcc/accounts.py): each one says whether it is signed in; Sign in starts its own sign-in page.
  async function drawAccounts(spot, fresh) {
    if (!spot) return;
    let rows = [];
    try { rows = (await api('/api/accounts', { action: 'status', fresh: !!fresh })).accounts; } catch (error) { spot.innerHTML = '<p class="small">' + esc(error.message) + '</p>'; return; }
    if (!spot.isConnected) return;
    spot.innerHTML = rows.map(a => '<div class="nv-field nv-account" data-account="' + esc(a.id) + '"><span>' + esc(a.name) + '<small>' + esc(a.about) + '</small>' +
      '<small class="nv-account-state ' + (a.signed_in ? 'ok' : '') + '">' + (a.signed_in ? 'Signed in' + (a.how ? ' ' + esc(a.how) : '') : a.installed ? 'Not signed in' : esc(a.install)) + '</small></span>' +
      '<div class="nv-account-do">' + (!a.installed ? '' : a.signed_in ? '<button class="plain" type="button" data-sign-out>Sign out</button>' : '<button class="primary" type="button" data-sign-in>Sign in</button>') +
      (a.installed ? '<button class="plain" type="button" data-recheck>Check</button>' : '') + '</div></div>').join('');
    for (const line of spot.querySelectorAll('[data-account]')) {
      const id = line.dataset.account, name = rows.find(a => a.id === id)?.name || id;
      const inB = line.querySelector('[data-sign-in]'), outB = line.querySelector('[data-sign-out]'), again = line.querySelector('[data-recheck]');
      if (inB) inB.onclick = async () => {
        inB.disabled = true;
        try {
          await api('/api/accounts', { action: 'sign_in', id });
          notify('Sign in to ' + name + ' on the page that opened in your browser. This shows it once it is done.');
          // It is asked again a few times while the sign-in page is open.
          for (const wait of [8000, 15000, 30000, 60000]) setTimeout(() => { if (spot.isConnected) drawAccounts(spot, true); }, wait);
        } catch (error) { toast(error.message); inB.disabled = false; }
      };
      if (outB) outB.onclick = async () => {
        if (!(await N.confirmBox({ title: 'Sign out of ' + name + '?', text: 'JARVIS (and the ' + (id === 'claude' ? 'Claude Code' : 'Codex') + ' app itself) can no longer use your ' + name + ' subscription until you sign in again.', ok: 'Sign out', danger: true }))) return;
        outB.disabled = true;
        try { await api('/api/accounts', { action: 'sign_out', id }); notify('Signed out of ' + name + '.'); } catch (error) { toast(error.message); }
        drawAccounts(spot, true);
      };
      if (again) again.onclick = () => { again.disabled = true; drawAccounts(spot, true); };
    }
  }
  function drawModels(opened, looking) {
    const one = s => '<div class="nv-link nv-ai" data-id="' + esc(s.id) + '" data-state="' + (s.connected ? 'ok' : 'off') + '"><span class="nv-dot"></span>' +
      '<div class="nv-link-text"><div class="nv-ai-name"><b>' + esc(s.name) + '</b>' + (s.free ? '<span class="nv-tag">Free key</span>' : '') + (s.local ? '<span class="nv-tag">On this PC</span>' : '') +
      '</div><small>' + esc(s.about) + '</small><span class="nv-link-status">' + (s.connected ? 'Connected' : s.local ? 'Not running' : 'Not connected') + '</span>' +
      (s.connected ? '<label class="nv-ai-model">Model <select data-model></select></label>' : '') +
      '<div class="nv-keyrow ' + (opened === s.id ? '' : 'hidden') + '">' + (s.id === 'custom' ? '<input data-name maxlength="40" placeholder="A name for it"><input data-address spellcheck="false" placeholder="Its address, https://…/v1">' : '') +
      (s.local ? '' : '<input data-key type="password" autocomplete="off" spellcheck="false" placeholder="Paste the key here" aria-label="Key for ' + esc(s.name) + '">') + '<button class="primary" data-save>' + (s.local ? 'Look for it' : 'Save') + '</button></div></div>' +
      '<div class="nv-link-do">' + (s.connected ? '<button class="plain" data-off>Disconnect</button>' : '<button class="primary" data-connect>' + (s.local ? 'Check' : 'Connect') + '</button>') +
      (s.get && !s.connected ? '<a class="plain" href="' + esc(s.get) + '" target="_blank" rel="noopener">' + (s.local ? 'Get it' : 'Get a key') + '</a>' : '') + '</div></div>';
    const on = services.filter(s => s.connected), rest = services.filter(s => !s.connected);
    pane.innerHTML = '<h3>Accounts</h3><p class="small">Sign in with your own subscription, as in T3 Code: no key needed. Each one signs in on its own page, in your browser.</p><div class="nv-accounts" data-accounts><p class="small nv-set-wait"><i class="nv-spin"></i>Asking each one whether it is signed in…</p></div>' +
      '<h3>Who answers</h3>' + row('JARVIS’s brain', pick('mo-model', brainChoices()), 'For talking, quick questions and controlling the PC. Building software has its own choice, next to the message box.') +
      check('mo-standin', 'When that AI reaches its usage limit, carry on with another one', 'The same request simply continues with the next connected AI, and JARVIS tells you. It switches back by itself when the limit is over.') +
      check('mo-resume', 'If nothing can answer, carry on by itself as soon as something can', 'The request waits, and is picked up where it stopped. You are told when it happens.') +
      '<h3>API keys: connected</h3>' + (on.length ? on.map(one).join('') : '<p class="small">None yet. Connect at least one so that JARVIS can keep going when Claude’s allowance runs out. Groq and Gemini have free keys.</p>') +
      '<h3>API keys: more AI services</h3>' + (looking ? '<p class="small nv-set-wait"><i class="nv-spin"></i>Looking for models running on this PC…</p>' : '') + rest.map(one).join('') +
      '<p class="small">A key is kept in Windows Credential Manager on this PC and sent only to the service it belongs to. JARVIS never buys anything: paid services charge your own account with them.</p>';
    bind('mo-model', options.model, 'model', setAssistant); bind('mo-standin', options.standin !== false, 'standin', setAssistant); bind('mo-resume', options.resume !== false, 'resume', setAssistant);
    drawAccounts(pane.querySelector('[data-accounts]'));
    for (const line of pane.querySelectorAll('.nv-ai')) {
      const id = line.dataset.id, service = services.find(s => s.id === id), box = line.querySelector('.nv-keyrow'), save = line.querySelector('[data-save]');
      const connect = line.querySelector('[data-connect]'), off = line.querySelector('[data-off]'), model = line.querySelector('[data-model]');
      if (connect) connect.onclick = () => { if (service.local) return save.click(); box.classList.remove('hidden'); connect.remove(); box.querySelector('input').focus(); };
      save.onclick = async () => {
        const key = box.querySelector('[data-key]'); if (key && !key.value.trim()) return key.focus();
        save.disabled = true; save.textContent = 'Checking…';
        try {
          await api('/api/providers', { action: 'connect', id, key: key?.value || '', address: box.querySelector('[data-address]')?.value || '', name: box.querySelector('[data-name]')?.value || '' });
          notify(service.name + ' is connected.'); refreshModels();
        } catch (error) { toast(error.message); save.disabled = false; save.textContent = service.local ? 'Look for it' : 'Save'; }
      };
      box.querySelectorAll('input').forEach(input => input.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); save.click(); } });
      if (off) off.onclick = async () => {
        if (!(await N.confirmBox({ title: 'Disconnect ' + service.name + '?', text: 'JARVIS stops using it. You can connect it again at any time.', ok: 'Disconnect', danger: true }))) return;
        try { await api('/api/providers', { action: 'disconnect', id }); refreshModels(); } catch (error) { toast(error.message); }
      };
      if (model) {
        model.innerHTML = '<option value="' + esc(service.model) + '">' + esc(service.model || 'Reading its models…') + '</option>'; model.value = service.model;
        api('/api/providers', { action: 'models', id }).then(got => {
          if (!model.isConnected) return;
          model.replaceChildren(...got.models.map(name => { const o = document.createElement('option'); o.value = o.textContent = name; return o; })); model.value = service.model || got.models[0] || '';
        }).catch(error => { if (model.isConnected && !service.model) model.innerHTML = '<option value="">' + esc(error.message) + '</option>'; });
        model.onchange = async () => { try { await api('/api/providers', { action: 'model', id, model: model.value }); saved(); loadServices(); } catch (error) { toast(error.message); } };
      }
    }
  }
  /* Mods: the owner's own commands, what happens when, panels beside the chat, and the status line (jcc/mods.py). */
  async function modsTab() {
    let data;
    try { data = await api('/api/mods', { action: 'list' }); } catch (error) { if (showing === 'mods') pane.textContent = error.message; return; }
    if (showing !== 'mods') return;
    const act = async (payload, done) => { try { await api('/api/mods', payload); await N.loadMods?.(); if (done) notify(done); if (showing === 'mods') modsTab(); } catch (error) { toast(error.message); } };
    const choices = (map, chosen) => Object.entries(map).map(([value, label]) => '<option value="' + value + '"' + (value === chosen ? ' selected' : '') + '>' + esc(label[0].toUpperCase() + label.slice(1)) + '</option>').join('');
    const command = c => '<div class="nv-link nv-mod" data-command="' + esc(c.name) + '" data-state="ok"><span class="nv-dot"></span><div class="nv-link-text"><b>/' + esc(c.name) + '</b><small>' + esc(c.about || c.text.slice(0, 110)) +
      '</small></div><div class="nv-link-do"><button class="plain" data-edit>Change</button><button class="plain" data-remove>Remove</button></div></div>';
    const hook = h => '<div class="nv-link nv-mod" data-hook="' + h.id + '" data-state="' + (h.on ? 'ok' : 'off') + '"><span class="nv-dot"></span><div class="nv-link-text"><b>When ' + esc(data.when[h.when]) + ': ' + esc(data.do[h.do]) +
      '</b><small>' + esc(h.text) + '</small></div><div class="nv-link-do"><button class="plain" data-switch>' + (h.on ? 'Switch off' : 'Switch on') + '</button><button class="plain" data-remove>Remove</button></div></div>';
    const panel = p => '<div class="nv-link nv-mod" data-panel="' + p.id + '" data-state="ok"><span class="nv-dot"></span><div class="nv-link-text"><b>' + esc(p.name) + '</b><small>Beside the chat, among the panels</small></div>' +
      '<div class="nv-link-do"><button class="plain" data-open>Open</button><button class="plain" data-remove>Remove</button></div></div>';
    pane.innerHTML = '<h3>Commands</h3><p class="small">Type / in the message box and pick one. A command stands for a longer request. Write $ARGUMENTS where whatever you type after its name should go.</p>' +
      (data.commands.map(command).join('') || '<p class="small">None of your own yet.</p>') +
      '<div class="nv-mod-form"><div class="nv-mod-row"><input id="md-name" maxlength="31" placeholder="name (one word)" spellcheck="false" aria-label="The command\'s name"><input id="md-about" maxlength="160" placeholder="What it does (shown in the list)" aria-label="What it does"></div>' +
      '<textarea id="md-text" rows="3" maxlength="6000" aria-label="What JARVIS should do" placeholder="What JARVIS should do. For example: Summarise what I did today from my notes, in three short points. $ARGUMENTS"></textarea><button class="primary" id="md-save">Save command</button></div>' +
      (data.packs.length ? '<p class="small">' + data.packs.length + ' more from your switched-on skill packs: ' + data.packs.slice(0, 12).map(c => '/' + esc(c.name)).join(', ') + (data.packs.length > 12 ? '…' : '') + '</p>' : '') +
      '<h3>When something happens</h3>' + (data.hooks.map(hook).join('') || '<p class="small">Nothing set up yet. For example: when a coding job is finished, say “Your build is ready.”</p>') +
      '<div class="nv-mod-form"><div class="nv-mod-row"><select id="md-when" aria-label="When">' + choices(data.when) + '</select><select id="md-do" aria-label="What happens">' + choices(data.do) + '</select></div>' +
      '<div class="nv-mod-row"><input id="md-hook" maxlength="300" placeholder="What to show or say, or the command to run (/name …)" aria-label="What to show, say or run"><button class="primary" id="md-hook-save">Add</button></div></div>' +
      '<h3>Panels</h3>' + (data.panels.map(panel).join('') || '<p class="small">None yet. Open something JARVIS made (a page, an app, a diagram) in the Artifacts panel and press Pin: it stays beside the chat as a panel of your own.</p>') +
      '<h3>Status line</h3>' + check('md-status', 'Show a line under the message box', 'What you want in view at a glance') +
      '<div class="nv-mod-items">' + Object.entries(data.status_items).map(([id, label]) => '<label><input type="checkbox" data-item="' + id + '"' + (data.status.items.includes(id) ? ' checked' : '') + '> ' + esc(label) + '</label>').join('') + '</div>' +
      '<p class="small">Mods are kept on this PC. A hook can show a note, say something or run one of your commands. It cannot run programs.</p>';
    const field = id => pane.querySelector('#' + id);
    field('md-save').onclick = () => { if (!field('md-name').value.trim()) return field('md-name').focus(); if (!field('md-text').value.trim()) return field('md-text').focus();
      act({ action: 'command', name: field('md-name').value, about: field('md-about').value, text: field('md-text').value }, 'Saved. Type /' + field('md-name').value.trim().replace(/^\//, '').toLowerCase() + ' to use it.'); };
    for (const line of pane.querySelectorAll('[data-command]')) {
      const found = data.commands.find(c => c.name === line.dataset.command);
      line.querySelector('[data-edit]').onclick = () => { field('md-name').value = found.name; field('md-about').value = found.about; field('md-text').value = found.text; field('md-text').focus(); };
      line.querySelector('[data-remove]').onclick = async () => { if (await N.confirmBox({ title: 'Remove /' + found.name + '?', text: 'You can add it again at any time.', ok: 'Remove', danger: true })) act({ action: 'uncommand', name: found.name }); };
    }
    field('md-hook-save').onclick = () => { if (!field('md-hook').value.trim()) return field('md-hook').focus(); act({ action: 'hook', when: field('md-when').value, do: field('md-do').value, text: field('md-hook').value }); };
    field('md-hook').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); field('md-hook-save').click(); } };
    for (const line of pane.querySelectorAll('[data-hook]')) {
      const found = data.hooks.find(h => h.id === line.dataset.hook);
      line.querySelector('[data-switch]').onclick = () => act({ action: 'hook_switch', id: found.id, on: !found.on });
      line.querySelector('[data-remove]').onclick = () => act({ action: 'unhook', id: found.id });
    }
    for (const line of pane.querySelectorAll('[data-panel]')) {
      const found = data.panels.find(p => p.id === line.dataset.panel);
      line.querySelector('[data-open]').onclick = () => { d.close(); N.openPane('mod-' + found.id); };
      line.querySelector('[data-remove]').onclick = async () => { if (await N.confirmBox({ title: 'Remove the panel “' + found.name + '”?', text: 'It is taken away from beside the chat.', ok: 'Remove', danger: true })) act({ action: 'unpanel', id: found.id }); };
    }
    const status = () => act({ action: 'status', on: field('md-status').checked, items: [...pane.querySelectorAll('[data-item]:checked')].map(box => box.dataset.item) });
    field('md-status').checked = data.status.on; field('md-status').onchange = status;
    pane.querySelectorAll('[data-item]').forEach(box => box.onchange = status);
  }
  /* What has been used: each account's allowance, the voice, the other AI services, and JARVIS's own answers. */
  // Updates (jcc/updates.py): which version this is, whether a newer one is out, how updates happen, and installing now.
  async function updatesTab() {
    let u;
    try { u = await api('/api/updates'); } catch (error) { if (showing === 'updates') pane.textContent = error.message; return; }
    if (showing !== 'updates') return;
    const when = at => at ? new Date(at * 1000).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '';
    const result = u.result || {};
    let said;
    if (u.managed) said = 'This copy of JARVIS is ' + esc(u.managed) + '.';
    else if (u.installing) said = 'Installing JARVIS ' + esc(u.installing.version) + '… JARVIS restarts by itself in a minute or two.';
    else if (u.available && u.ready) said = '<b>JARVIS ' + esc(u.latest) + ' is ready.</b> ' + (u.mode === 'auto' ? 'It is installed the next time JARVIS starts, or now:' : 'Install it when it suits you:');
    else if (u.available && u.signed) said = '<b>JARVIS ' + esc(u.latest) + ' is out.</b> ' + (u.downloading ? 'It is being fetched…' : 'It is fetched when you install it.');
    else if (u.available) said = '<b>JARVIS ' + esc(u.latest) + ' is out.</b> ' + esc(u.problem);
    else if (u.problem) said = esc(u.problem);
    else if (u.checked_at) said = 'This is the newest version.';
    else said = 'JARVIS has not looked for updates yet.';
    const outcome = result.version ? (result.ok ? 'Updated from ' + esc(result.from || '?') + ' to ' + esc(result.version) + ' on ' + esc(when(result.at)) + '.'
      : 'The update to ' + esc(result.version) + ' did not work' + (result.rolled_back ? ', so JARVIS went back to ' + esc(result.from || 'the version before') : '') + ': ' + esc(result.problem)) : '';
    pane.innerHTML = '<h3>Updates</h3><p>This is <b>JARVIS ' + esc(u.current) + '</b>.</p><p class="nv-update-said">' + said + '</p>' +
      (outcome ? '<p class="small">' + outcome + '</p>' : '') +
      (u.managed ? '' : '<div class="nv-sound"><button class="plain" type="button" data-update-check>' + icon('retry') + 'Check now</button>' +
        (u.available && u.signed && !u.installing ? '<button type="button" data-update-install>' + icon('down') + 'Install and restart</button>' : '') + '</div>') +
      (u.checked_at ? '<p class="small">Last looked: ' + esc(when(u.checked_at)) + (u.page ? ' · <a href="' + esc(u.page) + '" target="_blank" rel="noopener noreferrer">the release page</a>' : '') + '</p>' : '') +
      (u.available && u.notes ? '<details class="nv-update-notes"><summary>What is new in ' + esc(u.latest) + '</summary><pre>' + esc(u.notes) + '</pre></details>' : '') +
      (u.managed ? '' : row('How updates happen', pick('up-mode', [['auto', 'Automatically: fetch it, and install it the next time JARVIS starts'], ['ask', 'Tell me, and I choose when to install'], ['off', 'Never look for updates']]))) +
      '<p class="small">JARVIS asks GitHub, where its releases are published, once a day. Nothing about you is sent. An update is installed only when ' +
      'its signature from JARVIS’s maker checks out, and if the new version does not start, JARVIS goes back to the one you had.</p>';
    const mode = pane.querySelector('#up-mode');
    if (mode) { mode.value = u.mode; mode.onchange = async () => { try { await api('/api/updates', { action: 'mode', mode: mode.value }); notify('Saved.'); } catch (error) { toast(error.message); } }; }
    const again = pane.querySelector('[data-update-check]');
    if (again) again.onclick = async () => {
      again.disabled = true; again.lastChild.textContent = 'Looking…';
      try { await api('/api/updates', { action: 'check' }); } catch (error) { toast(error.message); }
      if (showing === 'updates') updatesTab();
    };
    const install = pane.querySelector('[data-update-install]');
    if (install) install.onclick = async () => {
      if (!(await N.confirmBox({ title: 'Install JARVIS ' + u.latest + ' now?', text: 'JARVIS closes, installs the new version and starts again. Your chats, notes, settings and keys are kept. This window reconnects by itself.', ok: 'Install and restart' }))) return;
      install.disabled = true; install.lastChild.textContent = 'Fetching and installing…';
      try { await api('/api/updates', { action: 'install' }); notify('Installing JARVIS ' + u.latest + '. It restarts by itself in a minute or two.'); }
      catch (error) { toast(error.message); install.disabled = false; install.lastChild.textContent = 'Install and restart'; }
      if (showing === 'updates') updatesTab();
    };
  }
  async function usageTab(again) {
    let data;
    try { data = await api('/api/usage', { days: 7, refresh: again === true }); } catch (error) { if (showing === 'usage') pane.textContent = error.message; return; }
    if (showing !== 'usage') return;
    const number = n => Number(n || 0).toLocaleString(), when = at => at ? new Date(at * 1000).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : '';
    const day = at => at ? new Date(at * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' }) : '';
    const bar = (label, used, note) => { const part = Math.max(0, Math.min(100, Number(used) || 0)); return '<div class="nv-use"><div class="nv-use-top"><b>' + esc(label) + '</b><span>' + esc(note) + '</span></div>' +
      '<div class="nv-use-bar" role="progressbar" aria-label="' + esc(label) + '" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(part) + '"><i data-level="' + (part >= 90 ? 'high' : part >= 70 ? 'mid' : 'low') + '" style="width:' + part + '%"></i></div></div>'; };
    const windowName = w => w.minutes === 300 || /five hour/i.test(w.name) ? 'Five-hour window' : w.minutes === 10080 || /^seven day$|secondary/i.test(w.name) ? 'Weekly' :
      /seven day (\w+)/i.test(w.name) ? 'Weekly, ' + w.name.match(/seven day (\w+)/i)[1] : w.name[0].toUpperCase() + w.name.slice(1);
    const account = (title, got) => {
      const rows = (got?.windows || []).map(w => bar(windowName(w), w.used_percent, Math.round(w.used_percent) + '% used' + (w.reset_at ? ' · new allowance ' + when(w.reset_at) : ''))).join('');
      return '<div class="nv-use-group"><h4>' + esc(title) + '</h4>' + (rows || '<p class="small">' + esc(got?.error || 'Not read yet.') + '</p>') +
        (rows && got?.error ? '<p class="small">Could not be read again just now: ' + esc(got.error) + '</p>' : '') + '</div>';
    };
    const read = Math.max(data.accounts?.claude?.at || 0, data.accounts?.codex?.at || 0);
    // JARVIS's own answers, added up by AI. (A service that says what each answer cost is shown with the money too.)
    const by = new Map();
    for (const row of data.turns || []) {
      const key = row.engine + ' · ' + row.model, sum = by.get(key) || { engine: row.engine, model: row.model, requests: 0, input: 0, cached: 0, written: 0, output: 0, cost: 0, first: 0 };
      sum.requests += row.requests; sum.input += row.input; sum.cached += row.cached; sum.written += row.written; sum.output += row.output; sum.cost += row.cost || 0;
      sum.first += (row.first || 0) * row.requests; by.set(key, sum);
    }
    const names = { claude: 'Claude', groq: 'Groq', gemini: 'Gemini', openai: 'OpenAI', xai: 'Grok', perplexity: 'Perplexity', deepseek: 'DeepSeek', mistral: 'Mistral', openrouter: 'OpenRouter' };
    const lines = [...by.values()].sort((a, b) => b.requests - a.requests);
    const table = lines.length ? '<table class="nv-use-table"><thead><tr><th>AI</th><th>Answers</th><th>New input</th><th>From cache</th><th>Output</th><th>First words</th><th>Charged</th></tr></thead><tbody>' +
      lines.map(s => '<tr><td>' + esc((names[s.engine] || s.engine) + ' · ' + String(s.model).split('/').pop()) + '</td><td>' + number(s.requests) + '</td><td>' + number(s.input + s.written) + '</td><td>' + number(s.cached) +
        '</td><td>' + number(s.output) + '</td><td>' + (s.first ? (s.first / s.requests).toFixed(1) + ' s' : '—') + '</td><td>' + (s.engine === 'claude' ? 'Your plan' : s.cost ? '$' + s.cost.toFixed(s.cost < 1 ? 3 : 2) : '—') + '</td></tr>').join('') +
      '</tbody></table><p class="small">Tokens are the pieces of text an AI reads and writes. “From cache” is text it had already read in the same conversation, which costs about a tenth. Claude’s answers come out of your Claude plan’s allowance, shown above; nothing is charged for each one.</p>'
      : '<p class="small">Nothing yet. Every answer JARVIS gives from now on is counted here.</p>';
    const free = data.free || {}, freeNames = { groq: 'Groq', gemini_lite: 'Gemini Flash-Lite', gemini_flash: 'Gemini Flash' };
    const freeRows = Object.entries(free).filter(([, f]) => f && f.requests_cap).map(([id, f]) => bar(freeNames[id] || id, 100 * f.requests / f.requests_cap, number(f.requests) + ' of ' + number(f.requests_cap) + ' requests today')).join('');
    const perplexity = lines.filter(s => s.engine === 'perplexity'), spent = perplexity.reduce((sum, s) => sum + s.cost, 0), asked = perplexity.reduce((sum, s) => sum + s.requests, 0);
    const linked = services.some(s => s.id === 'perplexity' && s.connected);
    const voice = data.voice;
    pane.innerHTML = '<div class="nv-status nv-link-head"><div><b>Usage</b><span>' + (data.reading ? 'Reading your accounts…' : read ? 'Accounts read ' + esc(when(read)) + '.' : 'Your accounts have not been read yet.') + '</span></div>' +
      '<button class="plain" data-again' + (data.reading ? ' disabled' : '') + '>' + icon('retry') + (data.reading ? 'Reading…' : 'Read again') + '</button></div>' +
      '<h3>Your accounts</h3>' + account('Claude', data.accounts?.claude) + account('Codex (ChatGPT)', data.accounts?.codex) +
      '<h3>Voice</h3>' + (voice ? bar('ElevenLabs' + (voice.plan ? ' · ' + voice.plan[0].toUpperCase() + voice.plan.slice(1) + ' plan' : ''), voice.percent,
        number(voice.used) + ' of ' + number(voice.limit) + ' characters this month' + (voice.renews ? ' · new allowance ' + day(voice.renews) : '')) : '<p class="small">ElevenLabs is not connected, or its key may not read the allowance.</p>') +
      '<h3>Research with Perplexity</h3>' + (linked || asked ? '<p class="nv-use-line"><b>' + number(asked) + (asked === 1 ? ' report' : ' reports') + '</b> in the last ' + data.days + ' days' +
        (spent ? ', <b>$' + spent.toFixed(spent < 1 ? 3 : 2) + '</b> as Perplexity reported for each one' : '') + '.</p><p class="small">Perplexity charges your own account with it for each answer. It does not tell an app like JARVIS what is left on that account: ' +
        '<a href="https://www.perplexity.ai/account/api" target="_blank" rel="noopener">see it on Perplexity’s own page</a>.</p>'
        : '<p class="small">Not connected. Research is done by Claude with its web search. <button class="link" data-open-models>Connect Perplexity</button> for wider searches with sources.</p>') +
      (freeRows ? '<h3>Free allowances JARVIS keeps to</h3>' + freeRows + '<p class="small">Used for small jobs behind the scenes (sorting requests, listening). JARVIS stops at these numbers so that a free key is never overrun.</p>' : '') +
      '<h3>JARVIS’s own answers, last ' + data.days + ' days</h3>' + table;
    pane.querySelector('[data-again]').onclick = () => { usageTab(true); setTimeout(() => { if (showing === 'usage' && pane.isConnected) usageTab(); }, 6000); };
    const models = pane.querySelector('[data-open-models]'); if (models) models.onclick = () => show('models');
    if (data.reading) setTimeout(() => { if (showing === 'usage' && pane.isConnected) usageTab(); }, 3000);
  }
  /* Everything JARVIS can be connected to, in one place: what is working, what is not, and how to connect the rest. */
  async function connectTab(checked = {}, busy = new Set()) {
    let data;
    try { data = await api('/api/connections'); } catch (error) { if (showing === 'connect') pane.textContent = error.message; return; }
    if (showing !== 'connect') return;
    const total = data.summary, words = { ok: 'Connected', off: 'Not connected', needed: 'Needed', problem: 'Needs attention' };
    const head = total.problems.length ? total.problems.join(', ') + (total.problems.length > 1 ? ' need' : ' needs') + ' attention.'
      : total.needed.length ? 'Still to connect: ' + total.needed.join(', ') + '.' : 'Everything JARVIS needs is connected.';
    const one = item => {
      const result = checked[item.id], state = result ? (result.ok ? 'ok' : 'problem') : item.state;
      return '<div class="nv-link" data-id="' + esc(item.id) + '" data-state="' + state + '"><span class="nv-dot" title="' + words[state] + '"></span>' +
        '<div class="nv-link-text"><b>' + esc(item.name) + '</b><small>' + esc(item.about) + '</small>' +
        '<span class="nv-link-status">' + esc(busy.has(item.id) ? 'Checking…' : result ? result.status : item.status) + '</span>' + (item.detail && !result && !busy.has(item.id) ? '<small>' + esc(item.detail) + '</small>' : '') +
        (item.how && state !== 'ok' ? '<small class="nv-link-how">' + esc(item.how) + '</small>' : '') +
        (item.key ? '<div class="nv-keyrow hidden"><input type="password" autocomplete="off" spellcheck="false" placeholder="Paste the key here" aria-label="Key for ' + esc(item.name) + '"><button class="primary" data-save>Save</button></div>' : '') + '</div>' +
        '<div class="nv-link-do">' + (item.key && state !== 'ok' ? '<button class="primary" data-connect>Connect</button>' : '') +
        (item.check ? '<button class="plain" data-check' + (busy.has(item.id) ? ' disabled' : '') + '>Check</button>' : '') + (item.open ? '<button class="plain" data-open="' + esc(item.open) + '">' + (state === 'ok' ? 'Change' : 'Set up') + '</button>' : '') +
        (item.user ? '<button class="plain" data-user>Whose accounts</button>' : '') +
        (item.settings ? '<button class="plain" data-settings>Open settings</button>' : '') + (item.remove ? '<button class="plain" data-remove>Remove</button>' : '') + '</div></div>';
    };
    pane.innerHTML = '<div class="nv-status nv-link-head"><div><b>' + total.connected + ' of ' + total.of + ' connected</b><span>' + esc(head) + '</span></div>' +
      '<button class="plain" data-check-all>' + icon('check') + 'Check everything</button></div>' +
      data.groups.map(([id, title]) => { const mine = data.items.filter(item => item.group === id); return mine.length ? '<h3>' + esc(title) + '</h3>' + mine.map(one).join('') : ''; }).join('') +
      '<p class="small">Keys and passwords are kept in Windows Credential Manager on this PC. They are never written to a file, a note or a chat.</p>';
    const redraw = () => { if (pane.isConnected && pane.querySelector('.nv-link')) connectTab(checked, busy); };
    const run = async id => {   // each answer is shown as soon as it arrives
      busy.add(id); delete checked[id]; redraw();
      try { checked[id] = await api('/api/connections', { action: 'check', id }); } catch (error) { checked[id] = { ok: false, status: error.message }; }
      busy.delete(id); redraw();
    };
    for (const line of pane.querySelectorAll('.nv-link')) {
      const id = line.dataset.id, item = data.items.find(found => found.id === id), box = line.querySelector('.nv-keyrow');
      const connect = line.querySelector('[data-connect]'), save = line.querySelector('[data-save]'), check = line.querySelector('[data-check]');
      if (connect) connect.onclick = () => { box.classList.remove('hidden'); connect.remove(); box.querySelector('input').focus(); };
      if (save) save.onclick = async () => {
        const input = box.querySelector('input'); if (!input.value.trim()) return input.focus();
        save.disabled = true; save.textContent = 'Checking…';
        try { speech = { ...speech, ...(await api('/api/speech', { action: 'key', which: item.key, value: input.value })) }; input.value = ''; speaker.retry(); engineDown = {}; await loadSpeech(); notify(item.name + ' is connected.'); delete checked[id]; connectTab(checked, busy); }
        catch (error) { toast(error.message); save.disabled = false; save.textContent = 'Save'; }
      };
      if (box) box.querySelector('input').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); save.click(); } };
      if (check) check.onclick = () => run(id);
      const remove = line.querySelector('[data-remove]');
      if (remove) remove.onclick = async () => {
        if (!(await N.confirmBox({ title: 'Remove the key for ' + item.name + '?', text: 'You can add it again at any time.', ok: 'Remove', danger: true }))) return;
        try { await api('/api/speech', { action: 'forget', which: item.key }); await loadSpeech(); delete checked[id]; connectTab(checked, busy); } catch (error) { toast(error.message); }
      };
      const whose = line.querySelector('[data-user]');
      if (whose) whose.onclick = async () => {   // at Composio, accounts are connected under a name ("user id"): usually "default"
        const user = await N.ask({ title: 'Whose accounts', label: 'The name your accounts are connected under at Composio (usually “default”)', value: item.user, ok: 'Save' });
        if (!user || user === item.user) return;
        try { await api('/api/connections', { action: 'accounts_user', user }); notify('Saved.'); connectTab(checked, busy); } catch (error) { toast(error.message); }
      };
      const open = line.querySelector('[data-open]'); if (open) open.onclick = () => show(open.dataset.open);
      const settings = line.querySelector('[data-settings]'); if (settings) settings.onclick = () => { d.close(); $('info')?.click(); };
    }
    const all = pane.querySelector('[data-check-all]');
    if (busy.size) { all.disabled = true; all.lastChild.textContent = 'Checking…'; }
    all.onclick = () => { for (const item of data.items) if (item.check && !busy.has(item.id)) run(item.id); };
  }
  // Appearance, as in Claude: the theme, and how much of its work JARVIS shows in a chat.
  function appearanceTab() {
    const seg = (name, value, choices) => '<div class="nv-segrow" role="radiogroup" data-seg="' + name + '">' + choices.map(([v, label]) => '<button type="button" role="radio" data-v="' + v + '" class="' + (v === value ? 'on' : '') + '" aria-checked="' + (v === value) + '">' + label + '</button>').join('') + '</div>';
    const rowHtml = (label, note, control) => '<div class="nv-field"><span>' + label + '<small>' + note + '</small></span>' + control + '</div>';
    pane.innerHTML = rowHtml('Theme', 'Follow Windows, or always light or dark.', seg('theme', N.store.get('nv-theme', 'system'), [['system', 'System'], ['light', 'Light'], ['dark', 'Dark']])) +
      rowHtml('Default chat view', 'Normal shows each piece of work as one line you can open; Verbose shows every step.', seg('transcript', N.store.get('nv-transcript', 'normal'), [['normal', 'Normal'], ['verbose', 'Verbose']]));
    pane.querySelectorAll('[data-seg]').forEach(group => group.querySelectorAll('button').forEach(b => b.onclick = () => {
      group.querySelectorAll('button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', String(x === b)); });
      if (group.dataset.seg === 'theme') N.setTheme(b.dataset.v); else { N.store.set('nv-transcript', b.dataset.v); N.refreshMode?.(); }
      saved();
    }));
  }
  // The older settings, shown in place: their own part of the page is lent to this section while it is on screen.
  const lent = { node: null, home: null, next: null };
  const giveBack = () => { if (!lent.node) return; lent.home?.insertBefore(lent.node, lent.next && lent.next.parentNode === lent.home ? lent.next : null); lent.node = null; };
  d.addEventListener('close', giveBack);
  const olderTab = (section, before) => () => {
    giveBack();
    const node = document.getElementById('settings-body'), dlg = document.getElementById('settings-dialog');
    if (!node || !dlg || typeof window.openSettings !== 'function') { pane.innerHTML = '<p class="small">These settings could not be shown. Close Settings and open it again.</p>'; return; }
    lent.node = node; lent.home = node.parentNode; lent.next = node.nextSibling;
    window.openSettings(section);
    if (dlg.open) dlg.close();
    pane.replaceChildren(...(before ? [before()] : []), node);
  };
  // Advanced: the switch for the advanced tools in the window, and the expert controls themselves, here.
  const advancedTab = olderTab('usage', () => {
    const wrap = el('div', { class: 'nv-advanced' });
    const row = el('label', { class: 'assistant-check' }, '<input type="checkbox" data-advanced> <span>Show advanced tools in the window<small>The terminal, detailed diagnostics and every expert control, beside the chat.</small></span>');
    const box = row.querySelector('input'); box.checked = !document.body.classList.contains('everyday');
    box.onchange = () => { const toggle = document.getElementById('easy-experience'); if (toggle && box.checked === document.body.classList.contains('everyday')) toggle.click(); saved(); };
    const start = el('div', { class: 'nv-set-row' }, '<span><b>Getting started</b><small>A first command to try, a microphone test, how to talk to JARVIS and what to allow.</small></span><button class="plain" type="button">Show</button>');
    start.querySelector('button').onclick = () => { d.close(); N.gettingStarted?.(); };
    const remove = el('div', { class: 'nv-set-row' }, '<span><b>Uninstall JARVIS</b><small>Removes the app and its shortcuts. Your notes, settings and chats are kept unless you choose otherwise.</small></span><button class="plain nv-danger" type="button">Uninstall…</button>');
    remove.querySelector('button').onclick = () => uninstall();
    wrap.append(row, start, remove);
    return wrap;
  });
  async function uninstall() {
    let plan; try { plan = await api('/api/uninstall', { action: 'plan' }); } catch (error) { return toast(error.message); }
    if (!plan.can) return toast(plan.why);
    const ask = dialog('<h2>Uninstall JARVIS?</h2><p>The app and its shortcuts are removed, and JARVIS closes.</p>' +
      '<label class="assistant-check"><input type="checkbox" data-del-data> <span>Also delete my settings and chats<small>' + esc(plan.data) + ' goes to the ' + esc(plan.bin) + '.</small></span></label>' +
      (plan.vault ? '<label class="assistant-check"><input type="checkbox" data-del-notes> <span>Also delete my notes<small>' + esc(plan.vault) + ' goes to the ' + esc(plan.bin) + '.</small></span></label>' : '') +
      '<p class="small">Keys you saved stay in ' + (plan.bin === 'Trash' ? 'the Keychain' : 'Windows Credential Manager') + '. To use JARVIS again, download and install it again.</p>' +
      '<div class="actions"><button class="plain" data-no>Cancel</button><button class="primary nv-danger" data-yes>Uninstall</button></div>');
    ask.querySelector('[data-no]').onclick = () => ask.close();
    ask.querySelector('[data-yes]').onclick = async () => {
      const yes = ask.querySelector('[data-yes]'); yes.disabled = true; yes.textContent = 'Uninstalling…';
      try {
        const r = await fetch('/api/uninstall', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-JCC-Token': TOKEN, 'X-JCC-Sure': 'uninstall' },
          body: JSON.stringify({ action: 'start', delete_data: !!ask.querySelector('[data-del-data]')?.checked, delete_notes: !!ask.querySelector('[data-del-notes]')?.checked }) });
        const answer = await r.json(); if (!r.ok) throw Error(answer.error || 'JARVIS could not be uninstalled.');
        ask.querySelector('.actions').innerHTML = '<p>JARVIS is being removed and will close in a moment. Thank you for trying it.</p>';
      } catch (error) { yes.disabled = false; yes.textContent = 'Uninstall'; toast(error.message); }
    };
  }
  const tabs = { everyday: olderTab('app'), memory: olderTab('memory'), advanced: advancedTab, connect: connectTab, voice: voiceTab, models: modelsTab, skills: skillsTab, mods: modsTab, usage: usageTab, assistant: assistantTab, people: peopleTab, email: emailTab,
    updates: updatesTab, appearance: appearanceTab };
  // A tab that has to ask for something says so while it waits: no tab is ever simply empty.
  const show = name => {
    giveBack();                // (a section that borrows the older settings page borrows it again)
    showing = name; d.querySelectorAll('.nv-set-tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name)); pane.replaceChildren(); pane.scrollTop = 0;
    d.querySelector('.nv-set-title').textContent = (SECTIONS.flat().find(([id]) => id === name) || [, ''])[1]; tabs[name]();
    setTimeout(() => { if (showing === name && pane.isConnected && !pane.firstChild) pane.innerHTML = '<p class="small nv-set-wait"><i class="nv-spin"></i>One moment…</p>'; }, 250);
  };
  d.querySelectorAll('.nv-set-tabs button').forEach(b => b.onclick = () => show(b.dataset.tab));
  d.querySelector('[data-keys]').onclick = () => show('connect');        // (keys are kept with the connections)
  // Search: the sections whose name or settings match what is typed; Enter opens the first of them.
  const search = d.querySelector('.nv-set-search input');
  search.oninput = () => {
    const q = search.value.trim().toLowerCase();
    d.querySelectorAll('.nv-set-tabs button').forEach(b => { const [id, label] = SECTIONS.flat().find(([x]) => x === b.dataset.tab); b.classList.toggle('hidden', !!q && !(label + ' ' + (FINDS[id] || '')).toLowerCase().includes(q)); });
    d.querySelectorAll('.nv-set-tabs hr').forEach(hr => hr.classList.toggle('hidden', !!q));
  };
  search.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); d.querySelector('.nv-set-tabs button:not(.hidden)')?.click(); } };
  show(tabs[tab] ? tab : tab === 'usage' ? 'usage' : 'assistant');
}
N.voiceSettings = openSettings; N.setVoice = setVoice;
N.voiceState = () => ({ phase, voiceMode, engine: engine(), listening: capture?.mode || '', turns: turns.size, focus: !!focus, speaking: speaker.active(), natural: speaker.natural(), muted, dictating, asking: !!confirmOpen }); N.speakText = text => { A.unlock(); speaker.hush(); speaker.say(text); };

/* ---------- recordings attached to a chat are written out as text ---------- */
N.transcribe = async file => {
  if (file.size > 25_000_000) throw new Error('That recording is larger than 25 MB. Shorten it or use a smaller format such as MP3.');
  return (await post('/api/speech/transcribe?name=' + encodeURIComponent(file.name), await file.arrayBuffer())).text;
};

/* ---------- pictures made by the assistant ---------- */
const pictures = new Map();
async function hydrate(root) {
  for (const img of root.querySelectorAll('img[data-jarvis-image]:not([src])')) {
    const id = img.dataset.jarvisImage;
    try { if (!pictures.has(id)) { const d = await api('/api/voice/image?id=' + encodeURIComponent(id)); pictures.set(id, 'data:' + d.mime + ';base64,' + d.data); } img.src = pictures.get(id); } catch { img.alt = 'Picture unavailable'; }
  }
}
new MutationObserver(() => hydrate($('messages'))).observe($('messages'), { childList: true, subtree: true });

if (window.speechSynthesis) speechSynthesis.onvoiceschanged = () => {};
setPhase('idle'); pump();
loadSpeech().then(() => micSync());

// Once per version: an update that is ready (or a version just installed) is mentioned, with where to find more.
setTimeout(async () => {
  let u; try { u = await api('/api/updates'); } catch { return; }
  const told = store.get('nv-update-told', ''), result = u.result || {};
  if (result.version && told !== 'done:' + result.version + ':' + result.at) {
    store.set('nv-update-told', 'done:' + result.version + ':' + result.at);
    if (result.ok) notify('JARVIS was updated to ' + result.version + '.');
    else notify('The update to ' + result.version + ' did not work' + (result.rolled_back ? ', so JARVIS went back to the version you had' : '') + '. Settings, Updates says why.');
  } else if (!u.managed && u.mode !== 'off' && u.available && u.signed && told !== 'ready:' + u.latest) {
    store.set('nv-update-told', 'ready:' + u.latest);
    notify('JARVIS ' + u.latest + ' is out. ' + (u.mode === 'auto' ? 'It is installed the next time JARVIS starts, or now from Settings, Updates.' : 'Install it from Settings, Updates.'));
  }
}, 8000);
loadServices(false);
// Opened by "Hey JARVIS" or the Talk shortcut. If something was already said, answer it; otherwise listen.
if (DIRECT && new URLSearchParams(location.search).has('listen')) setTimeout(() => pickUp(true), 600);
})();
