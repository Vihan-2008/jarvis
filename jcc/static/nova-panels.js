/* NOVA panels: file explorer and editor, preview, interactive terminal, in-panel browser,
   screenshots and computer control. Each lives in the side panel next to the chat. */
(() => {
'use strict';
const N = window.Nova; if (!N) return;
const { icon, el, notify, confirmBox, ask, registerPane, openPane, store } = N;
const pane = (id, cls, html) => { const node = el('section', { id: 'tool-nv' + id, class: 'tool-content nv-pane hidden ' + cls }, html); N.panel.append(node); return node; };
const iconButton = (name, label, tipText) => el('button', { class: 'nv-icon', type: 'button', 'aria-label': label, data: { tip: tipText || label } }, icon(name));
const textButton = (name, label, tipText, cls = 'plain') => el('button', { class: cls, type: 'button', data: { tip: tipText } }, (name ? icon(name) : '') + label);

/* ================= Files: browse, create and edit ================= */
const files = pane('files', 'nv-files', '<div class="nv-tree-col"><div class="nv-tree-head"><span id="nv-files-name">Files</span></div><div class="nv-tree" id="nv-tree"></div></div><div class="nv-edit-col"><div class="nv-edit-head" id="nv-edit-head"><i class="nv-dirty" data-tip="You have changes that are not saved yet"></i><b id="nv-file-name">No file open</b></div><div class="nv-blank" id="nv-file-blank"></div><div class="nv-editor hidden" id="nv-editor"><div class="nv-gutter" id="nv-gutter">1</div><textarea id="nv-code" spellcheck="false" wrap="off" aria-label="File contents"></textarea></div></div>');
const tree = files.querySelector('#nv-tree'), code = files.querySelector('#nv-code'), gutter = files.querySelector('#nv-gutter'), editHead = files.querySelector('#nv-edit-head');
const newFileB = iconButton('plus', 'New file', 'Create a new file in this project'), reloadB = iconButton('retry', 'Refresh', 'Reload the list of files');
files.querySelector('.nv-tree-head').append(newFileB, reloadB);
const previewB = textButton('eye', 'Preview', 'See this page working'), attachB = textButton('clip', 'Add to chat', 'Send this file along with your next message'), saveB = textButton('check', 'Save', 'Save your changes to the file', 'primary');
saveB.dataset.key = 'Ctrl+S'; editHead.append(previewB, attachB, saveB);
let picked = '', openFile = null, original = '', folder = '';
const project = () => scope() || picked;
const dirty = () => openFile && code.value !== original;
function markDirty() { editHead.classList.toggle('dirty', !!dirty()); saveB.disabled = !dirty(); }
function lines() { const count = code.value.split('\n').length; if (gutter.dataset.count !== String(count)) { gutter.dataset.count = count; gutter.textContent = Array.from({ length: count }, (_, i) => i + 1).join('\n'); } gutter.scrollTop = code.scrollTop; }
function showEditor(on) { files.querySelector('#nv-editor').classList.toggle('hidden', !on); files.querySelector('#nv-file-blank').classList.toggle('hidden', on); for (const b of [previewB, attachB, saveB]) b.classList.toggle('hidden', !on); }
function blank(html) { showEditor(false); files.querySelector('#nv-file-blank').innerHTML = html; }
async function listInto(host, path) {
  const data = await api('/api/files?project=' + encodeURIComponent(project()) + '&path=' + encodeURIComponent(path));
  host.replaceChildren();
  for (const entry of data.entries || []) {
    const node = el('button', { class: 'nv-node', type: 'button', data: { path: entry.path, dir: entry.directory ? '1' : '' } }, (entry.directory ? '<svg class="i nv-tw" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>' + icon('folder') : icon('file')) + '<span>' + esc(entry.name) + '</span>');
    if (entry.directory) node.setAttribute('aria-expanded', 'false');
    if (openFile?.path === entry.path) node.classList.add('on');
    host.append(node);
    if (entry.directory) host.append(el('div', { class: 'nv-kids hidden' }));
  }
  if (!host.children.length) host.append(el('div', { class: 'nav-empty' }, 'This folder is empty.'));
}
async function loadTree() {
  const key = project();
  files.querySelector('#nv-files-name').textContent = key ? projectName(key) : 'Files';
  newFileB.classList.toggle('hidden', !key); reloadB.classList.toggle('hidden', !key);
  if (!key) {
    tree.innerHTML = '<div class="nav-empty">Choose a project to see its files.</div>' + (state?.projects || []).map(p => '<button class="nv-node" type="button" data-pick="' + esc(p.key) + '">' + icon('folder') + '<span>' + esc(p.name) + '</span></button>').join('');
    blank('Files live inside projects.<br>Pick a project on the left, or make a new one.<br><br><button class="plain" data-action="project">' + icon('plus') + 'New project</button>');
    return;
  }
  await listInto(tree, '');
  if (!openFile) blank('Choose a file on the left to read or edit it.<br>Use ' + icon('plus') + ' to create a new file.<br><br>You can also ask JARVIS in the chat to create or change files for you.');
}
async function open(path) {
  if (dirty() && !await confirmBox({ title: 'Leave without saving?', text: 'Your changes to ' + openFile.path + ' have not been saved.', ok: 'Discard changes', danger: true })) return;
  const data = await api('/api/files?project=' + encodeURIComponent(project()) + '&path=' + encodeURIComponent(path));
  if (data.text === undefined) return;
  openFile = { project: project(), path }; original = data.text; code.value = data.text; code.scrollTop = 0;
  files.querySelector('#nv-file-name').textContent = path; showEditor(true); markDirty(); lines();
  previewB.classList.toggle('hidden', !/\.(html?|svg)$/i.test(path));
  tree.querySelectorAll('.nv-node').forEach(n => n.classList.toggle('on', n.dataset.path === path));
}
async function save() {
  if (!openFile || !dirty()) return;
  const result = await api('/api/files/save', { project: openFile.project, path: openFile.path, text: code.value });
  original = code.value; markDirty();
  notify(result.redacted ? 'Saved. Anything that looked like a password or key was masked for safety.' : 'Saved ' + openFile.path + '.');
  if (result.redacted) await open(openFile.path);
}
tree.addEventListener('click', async e => {
  const node = e.target.closest('.nv-node'); if (!node) return;
  try {
    if (node.dataset.pick) { picked = node.dataset.pick; openFile = null; return await loadTree(); }
    if (node.dataset.dir) {
      const kids = node.nextElementSibling, opening = node.getAttribute('aria-expanded') !== 'true';
      node.setAttribute('aria-expanded', String(opening)); kids.classList.toggle('hidden', !opening); folder = opening ? node.dataset.path : folder;
      if (opening && !kids.dataset.loaded) { kids.dataset.loaded = '1'; await listInto(kids, node.dataset.path); }
    } else await open(node.dataset.path);
  } catch (error) { toast(error.message); }
});
newFileB.onclick = async () => {
  const name = await ask({ title: 'New file', label: 'File name', value: folder ? folder + '/' : '', placeholder: 'For example: notes.txt or pages/about.html', ok: 'Create' });
  if (!name) return;
  try { const made = await api('/api/files/save', { project: project(), path: name, text: '', create: true }); await loadTree(); await open(made.path); code.focus(); notify('Created ' + made.path + '.'); } catch (error) { toast(error.message); }
};
reloadB.onclick = () => loadTree().catch(error => toast(error.message));
saveB.onclick = () => save().catch(error => toast(error.message));
attachB.onclick = () => { if (!openFile) return; if (dirty()) return toast('Save the file first, so JARVIS sees your latest changes.'); window.jarvisFiles.push({ ...openFile }); renderAttachments(); notify('Added to your next message.'); $('message').focus(); };
previewB.onclick = () => N.preview({ code: code.value, lang: 'html', run: true, title: openFile.path });
code.addEventListener('input', () => { markDirty(); lines(); });
code.addEventListener('scroll', () => { gutter.scrollTop = code.scrollTop; }, { passive: true });
code.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save().catch(error => toast(error.message)); }
  if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); code.setRangeText('    ', code.selectionStart, code.selectionEnd, 'end'); markDirty(); }
});
addEventListener('beforeunload', e => { if (dirty()) e.preventDefault(); });
registerPane({ id: 'files', label: 'Files', icon: 'folder', top: true, node: files, tip: 'Browse, create and edit the files in a project', show: async () => { if (openFile && openFile.project !== project()) { openFile = null; } await loadTree(); } });

/* ================= Artifacts: what has been made, shown beside the chat =================
   A page, a picture, a diagram, a small app, a document, slides, a sheet, a chart or a whiteboard opens here, working,
   next to the conversation. It can be looked at as its code, changed, copied, saved in several forms, or opened in a
   window of its own. Every version is kept in the library (jcc/artifacts.py): they can be stepped through, and an
   earlier one can be made the current one again. Ordinary code from a reply opens here too. */
const preview = pane('preview', 'nv-preview', '<div class="nv-edit-head"><b id="nv-prev-title">Artifacts</b></div><div id="nv-prev-body" style="flex:1;display:flex;min-height:0"></div>');
const prevHead = preview.querySelector('.nv-edit-head'), prevBody = preview.querySelector('#nv-prev-body');
const homeB = textButton('grid', '', 'Everything that has been made, from every chat');
const listB = textButton('layers', '', 'Everything this conversation has made'), olderB = textButton('', '\u2039', 'The version before this one'), newerB = textButton('', '\u203a', 'The version after this one');
const versionNote = el('span', { class: 'nv-art-version' });
const restoreB = textButton('retry', 'Restore', 'Make this earlier version the current one again. Nothing is lost: it is added as the newest.');
const modeB = textButton('code', 'Show code', 'Switch between how it looks and its code'), editB = textButton('edit', 'Edit', 'Change its text yourself. What you save is a new version.');
const copyB = iconButton('copy', 'Copy', 'Copy its text to the clipboard'), dlB = iconButton('down', 'Download', 'Save it as a file on your computer');
const outB = iconButton('full', 'Open in a window', 'Open it in a window of its own'), pinB = iconButton('layers', 'Pin', 'Keep it beside the chat as a panel of your own');
const moreB = iconButton('more', 'More', 'Save a copy in another form, star it, rename it, or take it out of the library');
// A page shown here is sealed from the internet as well as from JARVIS: it cannot load pictures or data from anywhere, so
// nothing in it can be sent anywhere either. Its owner can allow the internet for the page that is shown.
const SEALED = 'This page is sealed: it cannot load pictures or data from the internet, so nothing in it can be sent anywhere. Allow the internet for this page if you trust what it shows.';
const netB = textButton('globe', 'Allow internet', SEALED);
netB.classList.add('nv-net');
let liveFrame = null;
homeB.classList.add('nv-art-list'); listB.classList.add('nv-art-list'); olderB.classList.add('nv-art-step'); newerB.classList.add('nv-art-step');
homeB.setAttribute('aria-label', 'All artifacts'); listB.setAttribute('aria-label', 'Made in this conversation');
prevHead.prepend(homeB, listB); prevHead.append(olderB, versionNote, newerB, restoreB, modeB, editB, copyB, dlB, netB, outB, pinB, moreB);
const BLANK = { code: '', lang: 'text', run: false, title: 'Artifacts', kind: '', versions: null, at: 0, lib: null, editing: false };
let shown = { ...BLANK }, servedAs = '', servedPage = '';
const RUNS = { html: 'page', htm: 'page', xml: 'page', svg: 'picture', mermaid: 'diagram', jsx: 'app', tsx: 'app', react: 'app', markdown: 'document', md: 'document',
  slides: 'slides', csv: 'sheet', sheet: 'sheet', chart: 'data', whiteboard: 'whiteboard' };
const safe = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
// The page a diagram or an app is drawn in. Like every preview it runs sealed off, at its own address: it cannot reach
// JARVIS or the files on this PC. What it needs to draw (Mermaid; React and Babel) it fetches from the web itself.
// (Each library is one exact version, and the browser refuses it unless it is byte for byte the file that was checked.)
const LIBS = {
  mermaid: '<script src="https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js" integrity="sha256-WB7X10vZBI0OOpE2OSfXLvIpQtdyJUayf3zCnjU5Drg=" crossorigin="anonymous"></' + 'script>',
  react: '<script src="https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js" integrity="sha256-2Unxw2h67a3O2shSYYZfKbF80nOZfn9rK/xTsvnUxN0=" crossorigin="anonymous"></' + 'script>' +
    '<script src="https://cdn.jsdelivr.net/npm/react-dom@18.3.1/umd/react-dom.production.min.js" integrity="sha256-NfT5dPSyvNRNpzljNH+JUuNB+DkJ5EmCJ9Tia5j2bw0=" crossorigin="anonymous"></' + 'script>' +
    '<script src="https://cdn.jsdelivr.net/npm/@babel/standalone@7.29.14/babel.min.js" integrity="sha256-qNU5Nbr2NmWqNSBf3MiBhUbGHF0xbJIxM6H5PcrfAPk=" crossorigin="anonymous"></' + 'script>',
};
function diagramPage(code) {
  return '<!doctype html><meta charset="utf-8"><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#fff;font:15px system-ui;color:#333">' +
    '<pre class="mermaid" style="margin:16px">' + safe(code) + '</pre>' + LIBS.mermaid +
    '<script>(async () => { try { if (!window.mermaid) throw new Error("drawing it needs the internet"); mermaid.initialize({ startOnLoad: false, securityLevel: "strict" }); await mermaid.run(); } ' +
    'catch (error) { const note = document.createElement("p"); note.style.cssText = "max-width:36em;padding:24px"; note.textContent = "This diagram could not be drawn: " + String(error.message || error) + ". Its text is under Show code."; document.body.replaceChildren(note); } })();</' + 'script></body>';
}
function appPage(code) {
  // A component written for React: its imports from React become plain names, and what it exports is what is shown.
  let source = code.replace(/^\s*import\s+[^;\n]*from\s+['"]react(?:-dom(?:\/client)?)?['"];?\s*$/gm, '');
  const named = (source.match(/export\s+default\s+(?:function|class)\s+([A-Za-z_]\w*)/) || source.match(/export\s+default\s+([A-Za-z_]\w*)\s*;?\s*$/m) || [])[1]
    || [...source.matchAll(/(?:function|const|class)\s+([A-Z]\w*)/g)].map(m => m[1]).pop() || '';
  source = source.replace(/export\s+default\s+(function|class)\s/, '$1 ').replace(/^\s*export\s+default\s+[A-Za-z_]\w*\s*;?\s*$/m, '').replace(/^\s*export\s+(const|function|class)\s/gm, '$1 ');
  return '<!doctype html><meta charset="utf-8"><body style="margin:0;font-family:system-ui"><div id="root"></div>' +
    LIBS.react +
    '<script>const fail = text => { document.getElementById("root").innerHTML = "<pre style=\\"margin:24px;white-space:pre-wrap;color:#b3261e;font:13px ui-monospace,monospace\\"></pre>"; document.querySelector("pre").textContent = text; };' +
    'window.addEventListener("error", event => fail("This app stopped with an error:\\n" + (event.message || "")));' +
    'try { if (!window.React || !window.ReactDOM || !window.Babel) throw new Error("Showing an app needs the internet (for React). Its code is under Show code.");' +
    'const { useState, useEffect, useRef, useMemo, useCallback, useReducer, useContext, createContext, Fragment, memo, forwardRef, useLayoutEffect, useId } = React;' +
    'const built = Babel.transform(' + JSON.stringify(source).replace(/</g, '\\u003c') + ', { presets: [["typescript", { isTSX: true, allExtensions: true }], "react"], filename: "app.tsx" }).code;' +
    'const App = new Function("React", "useState", "useEffect", "useRef", "useMemo", "useCallback", "useReducer", "useContext", "createContext", "Fragment", "memo", "forwardRef", "useLayoutEffect", "useId", built + ' +
    JSON.stringify('\nreturn typeof ' + (named || 'App') + ' !== "undefined" ? ' + (named || 'App') + ' : null;') + ')(React, useState, useEffect, useRef, useMemo, useCallback, useReducer, useContext, createContext, Fragment, memo, forwardRef, useLayoutEffect, useId);' +
    'if (!App) throw new Error("No component was found to show."); ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App)); } catch (error) { fail(String(error.message || error)); }</' + 'script></body>';
}
const kindOf = () => shown.kind || RUNS[shown.lang] || '';
const drawnHere = () => window.NovaKinds?.KINDS[kindOf()];        // a kind this app draws itself: slides, a sheet, a chart, a whiteboard
const byHand = kind => kind === 'sheet' || kind === 'whiteboard';   // changed where it is shown, not as text
const total = () => (shown.lib ? shown.lib.versions.length : shown.versions ? shown.versions.length : 1);
const latest = () => shown.at === total() - 1;
const when = at => (at ? new Date(at * 1000).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '');
const HINTS = { document: 'Markdown.', slides: 'Markdown. A line with only --- starts the next slide.', sheet: 'One row on each line, commas between the cells. A cell that starts with = is a formula.',
  data: 'JSON: "type" (bar, line, area, pie or scatter), "title", "x" and "series".' };
// The bar above what is shown: which version this is, and what can be done with it.
function drawHead() {
  const kind = kindOf(), runnable = !!kind, own = drawnHere(), many = total() > 1, live = runnable && shown.run && !shown.editing;
  modeB.classList.toggle('hidden', !runnable || shown.editing || kind === 'whiteboard');
  modeB.innerHTML = icon(shown.run ? 'code' : 'eye') + (shown.run ? 'Show code' : own ? own.show : kind === 'document' ? 'Show document' : kind === 'picture' ? 'Show picture' : kind === 'diagram' ? 'Show diagram' : kind === 'app' ? 'Show app' : 'Show page');
  outB.classList.toggle('hidden', !(live && kind !== 'document'));
  pinB.classList.toggle('hidden', !(live && kind !== 'document' && !byHand(kind)));
  netB.classList.toggle('hidden', !(live && !own && kind !== 'document'));
  netB.classList.toggle('on', !!shown.online); netB.classList.remove('nv-wants'); netB.setAttribute('aria-pressed', String(!!shown.online));
  netB.innerHTML = icon('globe') + (shown.online ? 'Internet allowed' : ''); netB.setAttribute('aria-label', shown.online ? 'Internet allowed' : 'Allow internet');
  netB.classList.toggle('plain', !!shown.online); netB.classList.toggle('nv-icon', !shown.online);        // (an icon among the icons until it is switched on)
  netB.dataset.tip = shown.online ? 'This page may load pictures and data from the internet. Click to seal it again.' : SEALED;
  for (const node of [olderB, newerB, versionNote]) node.classList.toggle('hidden', !many);
  if (many) {
    const v = shown.lib?.versions[shown.at], last = shown.lib?.versions[total() - 1];
    versionNote.textContent = 'Version ' + (v ? v.n : shown.at + 1) + ' of ' + (last ? last.n : total()) + (v && v.by === 'you' ? ' \u00b7 yours' : '');
    versionNote.dataset.tip = v ? (v.note || (v.by === 'you' ? 'Your own change' : 'As JARVIS made it')) + ', ' + when(v.at) : '';
    olderB.disabled = shown.at === 0; newerB.disabled = latest();
  }
  restoreB.classList.toggle('hidden', !(shown.lib && many && !latest()) || shown.editing);
  editB.classList.toggle('hidden', !shown.lib || kind === 'whiteboard' || shown.editing);
  for (const node of [copyB, dlB, moreB]) node.classList.toggle('hidden', !shown.code);
  listB.classList.toggle('hidden', !document.querySelector('#messages .nv-artifact'));
  preview.querySelector('#nv-prev-title').textContent = (shown.lib?.starred ? '\u2605 ' : '') + shown.title;
}
function drawPreview() {
  const kind = kindOf(), runnable = !!kind, own = drawnHere();
  drawHead(); liveFrame = null; prevBody.replaceChildren(); servedAs = ''; servedPage = '';
  if (!shown.code && !shown.lib) return void drawNothing();
  if (shown.editing) return void drawEditor();
  if (runnable && shown.run && own) {
    // Drawn by this app itself, from the text: what is in it goes in as words and numbers, never as markup.
    const box = el('div', { class: 'nv-kind nv-kind-' + kind }), hands = byHand(kind) && !!shown.lib && latest();
    prevBody.append(box);
    own.render(box, { code: shown.code, title: shown.title, save: hands ? saveSoon : null,
      note: shown.lib ? 'This is an earlier version, shown as it was. Go to the newest version to change it.' : 'One moment: this can be changed as soon as it is in your library.' });
  }
  else if (runnable && shown.run && kind === 'document') { const page = el('div', { class: 'nv-doc' }); page.innerHTML = window.NovaRich.rich(shown.code); prevBody.append(page); }
  else if (runnable && shown.run) {
    // It runs in a sealed frame: it cannot read JARVIS or your files.
    const frame = el('iframe', { sandbox: 'allow-scripts allow-forms allow-modals' + (shown.online ? ' allow-popups' : ''), title: 'What JARVIS made, working', referrerpolicy: 'no-referrer' });
    liveFrame = frame;
    const page = pageOf();
    prevBody.append(frame); servedPage = page;
    // Served from its own sealed address, so the page gets a separate origin and its own rules.
    api('/api/preview', { html: page, online: !!shown.online }).then(made => { servedAs = made.id; frame.src = '/preview/' + made.id; }).catch(error => { const note = el('pre'); note.textContent = error.message; prevBody.replaceChildren(note); });
  } else { const pre = el('pre'); pre.textContent = shown.code; prevBody.append(pre); }
}
function drawNothing() {
  prevBody.innerHTML = '<div class="nv-blank"><div>When JARVIS makes a page, a picture, a diagram, a document, slides, a sheet or a chart, it opens here. Code from a reply opens here too: press Open on it.' +
    '<div class="nv-wk-start"><button class="plain" data-all>' + icon('grid') + 'Everything that has been made</button></div></div></div>';
  prevBody.querySelector('[data-all]').onclick = () => N.openGallery?.();
}
// Its text, to change by hand. What is saved is a new version; the one before it stays.
function drawEditor() {
  const box = el('div', { class: 'nv-art-edit' }), area = el('textarea', { spellcheck: false, 'aria-label': 'The text of ' + shown.title });
  const bar = el('div', { class: 'settings-buttons' }), hint = el('span', { class: 'small' }), cancel = textButton('', 'Cancel', ''), save = textButton('check', 'Save as a new version', '', 'primary');
  area.value = shown.code; hint.textContent = HINTS[kindOf()] || '';
  bar.append(hint, cancel, save); box.append(area, bar); prevBody.append(box); area.focus();
  cancel.onclick = () => { shown.editing = false; drawPreview(); };
  save.onclick = async () => {
    if (area.value === shown.code) { shown.editing = false; return drawPreview(); }
    save.disabled = true;
    const first = !!shown.fresh;                               // (started empty a moment ago: what is typed takes the starter's place)
    if (await saveCode(area.value, first)) { shown.fresh = false; shown.editing = false; drawPreview(); notify(first ? 'Saved.' : 'Saved as a new version.'); } else save.disabled = false;
  };
}
// The page a thing makes when it stands by itself (to show sealed, open in a window, pin, print or save).
function pageOf() {
  const kind = kindOf(), own = drawnHere();
  if (own) return own.page(shown.code, shown.title);
  if (kind === 'document') return window.NovaKinds ? window.NovaKinds.documentPage(shown.code, shown.title) : '';
  if (kind === 'diagram') return diagramPage(shown.code);
  if (kind === 'app') return appPage(shown.code);
  if (kind === 'picture' && !/<html/i.test(shown.code)) return '<!doctype html><body style="margin:0;display:grid;place-items:center;min-height:100vh">' + shown.code + '</body>';
  return kind ? shown.code : '';
}
const pictureOf = () => (drawnHere()?.picture ? drawnHere().picture(shown.code) : kindOf() === 'picture' && /<svg[\s>]/i.test(shown.code) && !/<html/i.test(shown.code) ? shown.code : '');
/* ---- the library's record of what is shown ---- */
function take(got, keepPlace) {
  const codes = shown.lib && shown.lib.id === got.id ? shown.lib.codes : new Map();
  if (typeof got.code === 'string') codes.set(got.versions[got.versions.length - 1].n, got.code);
  shown.lib = { id: got.id, title: got.title, starred: got.starred, chat: got.chat, versions: got.versions, codes };
  shown.title = got.title; shown.kind = got.kind; shown.lang = got.lang;
  if (!keepPlace) { shown.code = got.code; shown.at = got.versions.length - 1; }
}
async function saveCode(code, amend) {
  if (!shown.lib) { toast('This can be changed as soon as it is in your library. Try again in a moment.'); return false; }
  try { take(await api('/api/artifacts', { action: 'save', id: shown.lib.id, code, amend: !!amend })); N.galleryChanged?.(); return true; }
  catch (error) { toast(error.message); return false; }
}
// What is drawn or typed where it is shown (a whiteboard, a sheet) is kept a moment after the hand stops.
let waiting = null;
function saveSoon(code) {
  shown.code = code; clearTimeout(waiting?.timer);
  const mine = shown;
  waiting = { timer: setTimeout(async () => {
    waiting = null;
    try { const got = await api('/api/artifacts', { action: 'save', id: mine.lib.id, code, amend: true }); if (shown === mine && latest()) { take(got); drawHead(); } N.galleryChanged?.(); }
    catch (error) { toast(error.message); }
  }, 900), now: () => api('/api/artifacts', { action: 'save', id: mine.lib.id, code, amend: true }).then(() => N.galleryChanged?.()).catch(() => {}) };
}
function flush() { if (waiting) { clearTimeout(waiting.timer); const now = waiting.now; waiting = null; now(); } }
// Something opened from a chat: its record in the library is found, so that it has all its versions and can be changed.
async function attach() {
  const mine = shown; if (mine.lib || !mine.versions || !current) return;
  let got; try { got = await api('/api/artifacts', { action: 'find', chat: current, kind: mine.kind, name: mine.title, code: mine.code }); } catch { return; }
  if (!got.found || got.at == null || shown !== mine) return;
  const found = got.found, codes = new Map([[found.versions[got.at].n, mine.code]]);
  codes.set(found.versions[found.versions.length - 1].n, found.code);
  mine.lib = { id: found.id, title: found.title, starred: found.starred, chat: found.chat, versions: found.versions, codes }; mine.at = got.at;
  if (byHand(kindOf()) && shown.run && !shown.editing) drawPreview(); else drawHead();
}
// Everything the open conversation has made, oldest first, gathered into versions (the same kind of thing under the same name).
function gather() {
  const groups = new Map();
  for (const node of document.querySelectorAll('#messages .nv-artifact')) {
    const block = node.querySelector('.nv-code'), key = node.dataset.kind + '\n' + node.dataset.name.toLowerCase();
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ node, kind: node.dataset.kind, name: node.dataset.name, lang: block.dataset.lang, code: block.querySelector('pre code').textContent });
  }
  return [...groups.values()];
}
function showVersion(versions, at, keepMode) {
  const one = versions[at]; flush();
  shown = { ...BLANK, code: one.code, lang: one.lang, kind: one.kind, title: one.name, versions, at, run: keepMode ? shown.run : true, online: false };
  drawPreview(); openPane('preview'); attach();
}
async function step(by) {
  flush();
  if (!shown.lib) { if (shown.versions && shown.versions[shown.at + by]) showVersion(shown.versions, shown.at + by, true); return; }
  const to = shown.at + by, v = shown.lib.versions[to]; if (!v) return;
  let code = shown.lib.codes.get(v.n);
  if (code === undefined) { try { code = (await api('/api/artifacts', { action: 'version', id: shown.lib.id, n: v.n })).code; } catch (error) { return void toast(error.message); } shown.lib.codes.set(v.n, code); }
  shown.code = code; shown.at = to; shown.editing = false; drawPreview();
}
N.artifact = node => { for (const versions of gather()) { const at = versions.findIndex(v => v.node === node); if (at >= 0) return showVersion(versions, at); } };
N.artifactLatest = () => { const all = gather(); if (all.length) { const versions = all[all.length - 1]; showVersion(versions, versions.length - 1); } };
N.preview = options => { flush(); shown = { ...BLANK, title: options.lang === 'text' ? 'Text' : options.lang.toUpperCase() + ' from JARVIS', ...options, online: false }; drawPreview(); openPane('preview'); };
// Something from the library (the gallery opens it this way), at its newest version.
N.openArtifact = async id => {
  flush();
  const got = await api('/api/artifacts', { action: 'get', id });
  shown = { ...BLANK, run: true, online: false }; take(got); drawPreview(); openPane('preview');
};
// Something new, made by hand (a whiteboard, or an empty document, deck or sheet to start from).
N.newArtifact = async (kind, title) => {
  const own = window.NovaKinds?.KINDS[kind];
  const got = await api('/api/artifacts', { action: 'save', kind, title, code: own ? own.blank(title) : '# ' + (title || 'A new document') + '\n\nStart writing here.' });
  N.galleryChanged?.(); flush(); shown = { ...BLANK, run: true, online: false }; take(got);
  if (!byHand(kind)) { shown.editing = true; shown.fresh = true; }
  drawPreview(); openPane('preview');
};
netB.onclick = () => { shown.online = !shown.online; drawPreview(); notify(shown.online ? 'This page may now load from the internet.' : 'This page is sealed from the internet again.'); };
// A sealed page says (only that it happened) when something it wanted from the internet was refused.
addEventListener('message', event => {
  if (!liveFrame || event.source !== liveFrame.contentWindow || !event.data || event.data.jarvisPreview !== 'blocked' || shown.online || netB.classList.contains('nv-wants')) return;
  netB.classList.add('nv-wants');
  netB.dataset.tip = 'This page tried to load something from the internet (a picture or data) and was stopped. ' + SEALED;
});
olderB.onclick = () => step(-1);
newerB.onclick = () => step(1);
homeB.onclick = () => N.openGallery?.();
restoreB.onclick = async () => {
  const v = shown.lib?.versions[shown.at]; if (!v || latest()) return;
  restoreB.disabled = true;
  try {
    const got = await api('/api/artifacts', { action: 'restore', id: shown.lib.id, n: v.n });
    take(got); drawPreview(); N.galleryChanged?.();
    notify('Version ' + v.n + ' is the current one again.' + (got.told ? ' Its chat has been told, so the next change starts from it.' : ''));
    if (got.told && got.chat === current) openChat(current).catch(() => {});
  } catch (error) { toast(error.message); }
  restoreB.disabled = false;
};
editB.onclick = () => { if (!shown.lib) return; flush(); shown.editing = true; drawPreview(); };
listB.onclick = () => N.openPop(listB, p => {
  p.append(el('h5', {}, 'Made in this conversation'));
  const names = window.NovaRich.KIND_NAMES;
  for (const versions of gather().reverse()) {
    const last = versions[versions.length - 1];
    N.item(p, last.name, '', () => showVersion(versions, versions.length - 1), { note: (names[last.kind] || '') + (versions.length > 1 ? ' \u00b7 ' + versions.length + ' versions' : ''), tick: shown.versions === versions || (shown.versions && shown.versions[0]?.node === versions[0].node) });
  }
});
modeB.onclick = () => { flush(); shown.run = !shown.run; drawPreview(); };
copyB.onclick = async () => { await navigator.clipboard.writeText(shown.code); notify('Copied.'); };
outB.onclick = async () => {
  if (servedAs) return void window.open('/preview/' + servedAs, '_blank', 'popup,width=1100,height=780');
  const html = pageOf(); if (!html) return;
  try { const made = await api('/api/preview', { html }); window.open('/preview/' + made.id, '_blank', 'popup,width=1100,height=780'); } catch (error) { toast(error.message); }
};
pinB.onclick = async () => {
  const html = servedPage || pageOf(); if (!html) return;
  const name = await ask({ title: 'Pin as a panel', label: 'Its name', value: shown.title.replace(/\.\w{1,5}$/, ''), ok: 'Pin' }); if (!name) return;
  try { const made = await api('/api/mods', { action: 'panel', name, html, online: !!shown.online }); await N.loadMods?.(); notify('Pinned. It stays among the panels beside the chat.', 'Open', () => openPane('mod-' + made.made)); }
  catch (error) { toast(error.message); }
};
/* The owner's own panels (mods): a page of theirs, pinned from something JARVIS made, that stays beside the chat. Like
   every page JARVIS makes it is shown sealed off, at its own address. */
const pinned = new Map();
N.pinPanels = list => {
  for (const [id, node] of pinned) if (!list.some(p => p.id === id)) { N.unregisterPane?.('mod-' + id); node.remove(); pinned.delete(id); }
  for (const p of list) {
    if (pinned.has(p.id)) continue;
    const node = pane('mod' + p.id, 'nv-preview', '<div class="nv-edit-head"><b></b></div><div class="nv-mod-body" style="flex:1;display:flex;min-height:0"></div>');
    node.querySelector('b').textContent = p.name;
    const inside = node.querySelector('.nv-mod-body'), again = textButton('retry', 'Start again', 'Load this panel afresh'), gone = textButton('trash', 'Remove', 'Take this panel away');
    node.querySelector('.nv-edit-head').append(again, gone);
    const load = async () => {
      inside.replaceChildren();
      try {
        const got = await api('/api/mods', { action: 'panel_html', id: p.id }), made = await api('/api/preview', { html: got.html, online: !!p.online });   // (as it was when it was pinned)
        const frame = el('iframe', { sandbox: 'allow-scripts allow-forms allow-modals' + (p.online ? ' allow-popups' : ''), title: p.name, referrerpolicy: 'no-referrer' });
        frame.src = '/preview/' + made.id; inside.append(frame);
      } catch (error) { const note = el('pre'); note.textContent = error.message; inside.append(note); }
    };
    again.onclick = load;
    gone.onclick = async () => {
      if (!(await confirmBox({ title: 'Remove the panel “' + p.name + '”?', text: 'It is taken away from beside the chat. What it was made from stays in its conversation.', ok: 'Remove', danger: true }))) return;
      try { await api('/api/mods', { action: 'unpanel', id: p.id }); N.closePanel?.(); await N.loadMods?.(); } catch (error) { toast(error.message); }
    };
    registerPane({ id: 'mod-' + p.id, label: p.name, icon: 'layers', node, tip: 'A panel of your own', show: () => { if (!inside.firstChild) load(); } });
    pinned.set(p.id, node);
  }
};
const fileBase = () => (shown.lib || shown.versions ? shown.title.replace(/\.\w{1,5}$/, '').replace(/[^\w -]+/g, ' ').trim().replace(/\s+/g, '-').slice(0, 50) : '') || 'jarvis-' + Date.now();
function saveBlob(blob, name) { const url = URL.createObjectURL(blob), a = el('a', { href: url, download: name }); a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000); }
dlB.onclick = () => {
  const ext = { html: 'html', htm: 'html', svg: 'svg', python: 'py', py: 'py', javascript: 'js', js: 'js', css: 'css', json: 'json', markdown: 'md', md: 'md', mermaid: 'mmd', jsx: 'jsx', tsx: 'tsx', react: 'jsx',
    csv: 'csv', sheet: 'csv', slides: 'md', chart: 'json', whiteboard: 'json' }[shown.lang] || 'txt';
  if (ext === 'csv' && window.NovaKinds) return saveSheet(false);
  saveBlob(new Blob([shown.code], { type: 'text/plain' }), fileBase() + '.' + ext);
};
// A sheet as a file for a spreadsheet program: such a program runs what a cell says, so nothing this app does not
// itself understand is left for it to run (jcc/static/nova-kinds.js, exportCsv).
function saveSheet(values) {
  const made = window.NovaKinds.exportCsv(shown.code, values);
  saveBlob(new Blob([made.text], { type: 'text/csv' }), fileBase() + (values ? '-values' : '') + '.csv');
  const kept = made.changed ? ' ' + made.changed + (made.changed === 1 ? ' cell that a spreadsheet program would have run was' : ' cells that a spreadsheet program would have run were') + ' saved as plain text.' : '';
  if (values || kept) notify((values ? 'Saved with every formula as its value.' : 'Saved.') + kept);
}
// A picture of it (PNG). The drawing is loaded as an image, so nothing in it can run or fetch anything.
async function savePicture() {
  const text = pictureOf(); if (!text) return;
  try {
    const parsed = new DOMParser().parseFromString(text, 'image/svg+xml'), svg = parsed.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== 'svg' || parsed.querySelector('parsererror')) throw new Error('This picture could not be read.');
    const box = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number), size = name => parseFloat(svg.getAttribute(name)) || 0;
    const w = clampSize(size('width') || box[2] || 800), h = clampSize(size('height') || box[3] || 600);
    svg.setAttribute('width', w); svg.setAttribute('height', h);
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' })), img = new Image();
    try { await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error('This picture could not be drawn.')); img.src = url; }); }
    finally { setTimeout(() => URL.revokeObjectURL(url), 5000); }
    const scale = Math.min(2, 4000 / Math.max(w, h)), canvas = el('canvas', { width: Math.round(w * scale), height: Math.round(h * scale) }), g = canvas.getContext('2d');
    g.fillStyle = '#fff'; g.fillRect(0, 0, canvas.width, canvas.height); g.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(ok => canvas.toBlob(ok, 'image/png')); if (!blob) throw new Error('This picture could not be saved as a PNG.');
    saveBlob(blob, fileBase() + '.png'); notify('Saved as a picture.');
  } catch (error) { toast(error.message || 'This picture could not be saved as a PNG. Save it as a web page instead.'); }
}
const clampSize = v => Math.min(6000, Math.max(16, Math.round(v)));
async function printIt() {
  const html = pageOf(); if (!html) return;
  const go = '<script>addEventListener("load", () => setTimeout(() => print(), 500));</' + 'script>';
  try { const made = await api('/api/preview', { html: /<\/body>/i.test(html) ? html.replace(/<\/body>/i, go + '</body>') : html + go }); window.open('/preview/' + made.id, '_blank', 'popup,width=1000,height=760'); }
  catch (error) { toast(error.message); }
}
moreB.onclick = () => N.openPop(moreB, p => {
  const lib = shown.lib, page = pageOf();
  const sheet = kindOf() === 'sheet' && window.NovaKinds;
  if (page || pictureOf() || sheet) p.append(el('h5', {}, 'Save a copy'));
  if (sheet) N.item(p, 'With values only', 'grid', () => saveSheet(true), { note: 'A CSV file with every formula worked out' });
  if (page) N.item(p, 'As a web page', 'globe', () => { saveBlob(new Blob([page], { type: 'text/html' }), fileBase() + '.html'); notify('Saved as a web page.'); }, { note: 'One file that opens in any browser' });
  if (pictureOf()) N.item(p, 'As a picture', 'cam', savePicture, { note: 'A PNG image' });
  if (page) N.item(p, 'Print, or save as PDF', 'doc', printIt, { note: 'Opens it in a window with the print box' });
  if (lib) {
    if (page || pictureOf() || sheet) p.append(el('hr'));
    const change = async (body, said) => { try { take(await api('/api/artifacts', { ...body, id: lib.id }), true); drawHead(); N.galleryChanged?.(); if (said) notify(said); } catch (error) { toast(error.message); } };
    N.item(p, lib.starred ? 'Take the star off' : 'Star it', 'star', () => change({ action: 'star', on: !lib.starred }, lib.starred ? '' : 'Starred. It is under Starred in Artifacts.'));
    N.item(p, 'Rename', 'edit', async () => { const name = await ask({ title: 'Rename', label: 'Its name', value: lib.title, ok: 'Rename' }); if (name) await change({ action: 'rename', title: name }); });
    if (lib.chat) N.item(p, 'Open the chat that made it', 'chat', () => openChat(lib.chat).catch(() => toast('That chat is no longer there.')));
    N.item(p, 'Take it out of the library', 'trash', async () => {
      if (!(await confirmBox({ title: 'Take \u201c' + lib.title + '\u201d out of the library?', text: 'It and its ' + lib.versions.length + (lib.versions.length === 1 ? ' version go' : ' versions go') + ' from Artifacts.' + (lib.chat ? ' What the chat itself says is not touched.' : ' This cannot be undone.'), ok: 'Take it out', danger: true }))) return;
      try { flush(); await api('/api/artifacts', { action: 'remove', id: lib.id }); shown = { ...BLANK }; drawPreview(); N.galleryChanged?.(); notify('Taken out of the library.'); } catch (error) { toast(error.message); }
    }, { danger: true });
  }
  p.append(el('hr')); N.item(p, 'All artifacts', 'grid', () => N.openGallery?.());
}, { right: true });
registerPane({ id: 'preview', label: 'Artifacts', icon: 'eye', node: preview, tip: 'What JARVIS and you have made (pages, pictures, diagrams, documents, slides, sheets, charts, whiteboards), shown beside the chat',
  show: () => { if (!shown.code && !shown.lib) { const any = gather(); if (any.length) { const versions = any[any.length - 1]; showVersion(versions, versions.length - 1); } else drawPreview(); } } });
/* ================= Terminal: real interactive consoles, in tabs ================= */
const term = pane('term', '', '<div class="nv-edit-head" style="border:0;padding:0;min-height:36px"><div class="nv-term-tabs" id="nv-term-tabs" role="tablist"></div></div><div class="nv-term" id="nv-term"></div><div class="small" id="nv-term-where">A real PowerShell window running as you. Programs that ask questions or fill the screen work here. Paste with Ctrl+V or right-click.</div>');
const termHead = term.querySelector('.nv-edit-head'), termHost = term.querySelector('#nv-term'), termTabs = term.querySelector('#nv-term-tabs');
const termClear = textButton('', 'Clear', 'Wipe the text on screen. Nothing is undone.'), termStop = textButton('stop', 'Close', 'End this terminal and close its tab');
termHead.append(termClear, termStop);
const terms = []; let activeTerm = null, libs = null, termCount = 0, sendQueue = Promise.resolve();
const loadScript = src => new Promise((resolve, reject) => { const s = el('script', { src }); s.onload = resolve; s.onerror = () => reject(Error('Could not load the terminal.')); document.head.append(s); });
function termTheme() { const light = document.documentElement.dataset.theme === 'light'; return light ? { background: '#fbfbf9', foreground: '#1b1b22', cursor: '#5b4de0', selectionBackground: '#5b4de033', black: '#1b1b22', brightBlack: '#6b6b7a', white: '#55556a', brightWhite: '#1b1b22', yellow: '#946200', brightYellow: '#946200', green: '#1a7f4e', brightGreen: '#1a7f4e', cyan: '#0b7285', brightCyan: '#0b7285', blue: '#3b5bdb', brightBlue: '#3b5bdb', magenta: '#862e9c', brightMagenta: '#862e9c', red: '#c92a2a', brightRed: '#c92a2a' } : { background: '#0b0b0f', foreground: '#e6e6ee', cursor: '#8f80ff', selectionBackground: '#8f80ff44' }; }
async function ensureLibs() {
  libs = libs || (async () => { document.head.append(el('link', { rel: 'stylesheet', href: '/vendor/xterm.css' })); await loadScript('/vendor/xterm.js'); await loadScript('/vendor/addon-fit.js'); })();
  await libs;
}
function drawTermTabs() {
  termTabs.replaceChildren();
  for (const t of terms) { const b = el('button', { class: 'plain' + (t === activeTerm ? ' on' : ''), type: 'button', role: 'tab', data: { tip: 'Commands start in ' + t.cwd } }, esc(t.label)); b.onclick = () => showTerm(t); termTabs.append(b); }
  const add = iconButton('plus', 'New terminal', 'Open another terminal (up to four)'); add.onclick = () => newTerm().catch(error => toast(error.message)); termTabs.append(add);
}
function showTerm(t) { activeTerm = t; for (const other of terms) other.host.classList.toggle('hidden', other !== t); drawTermTabs(); resizeTerm(); t.xterm.focus(); }
let resizeTimer = 0;
function resizeTerm() { const t = activeTerm; if (!t || term.classList.contains('hidden') || !termHost.clientWidth) return; clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { try { t.fit.fit(); if (t.session) api('/api/pty', { action: 'resize', id: t.session, cols: t.xterm.cols, rows: t.xterm.rows }).catch(() => {}); } catch {} }, 60); }
async function pump(t) {
  const id = t.session;
  while (t.session === id) {
    let data;
    try { data = await api('/api/pty?id=' + id + '&since=' + t.position + '&wait=20'); } catch { if (t.session === id) { t.session = null; t.xterm.write('\r\n\x1b[90m[This terminal has ended. Open a new one with +.]\x1b[0m\r\n'); } return; }
    if (t.session !== id) return;
    if (data.reset) t.xterm.reset();
    if (data.data) t.xterm.write(data.data);
    t.position = data.next;
    if (!data.alive) { t.session = null; t.xterm.write('\r\n\x1b[90m[Session ended. Open a new one with +.]\x1b[0m\r\n'); return; }
  }
}
async function newTerm() {
  if (terms.length >= 4) throw Error('Close a terminal before opening another.');
  await ensureLibs();
  const host = el('div', { style: 'height:100%' }); termHost.append(host);
  const xterm = new window.Terminal({ fontFamily: '"Cascadia Code","Cascadia Mono",Consolas,monospace', fontSize: Number(store.get('nv-term-size', '13')) || 13, lineHeight: 1.25, cursorBlink: true, scrollback: 5000, theme: termTheme(), allowProposedApi: false });
  const fit = new window.FitAddon.FitAddon(); xterm.loadAddon(fit); xterm.open(host);
  const want = scope() || '', t = { xterm, fit, host, session: null, position: 0, scope: want, label: (want ? projectName(want) : 'Terminal') + ' ' + (++termCount), cwd: '' };
  terms.push(t); showTerm(t); fit.fit();
  xterm.onData(data => { if (!t.session) return; const id = t.session; sendQueue = sendQueue.then(() => api('/api/pty', { action: 'input', id, data })).catch(() => {}); });
  xterm.attachCustomKeyEventHandler(e => {
    if (e.type !== 'keydown' || !e.ctrlKey) return true;
    const key = e.key.toLowerCase();
    if (key === 'c' && xterm.hasSelection()) { navigator.clipboard.writeText(xterm.getSelection()); return false; }
    if (key === 'v') return false;
    if (key === '=' || key === '+' || key === '-') { const size = Math.max(10, Math.min(22, xterm.options.fontSize + (key === '-' ? -1 : 1))); for (const each of terms) each.xterm.options.fontSize = size; store.set('nv-term-size', String(size)); resizeTerm(); return false; }
    return true;
  });
  host.addEventListener('paste', e => { const text = e.clipboardData?.getData('text'); if (text && t.session) { e.preventDefault(); xterm.paste(text); } });
  host.addEventListener('contextmenu', async e => { e.preventDefault(); try { const text = await navigator.clipboard.readText(); if (text) xterm.paste(text); } catch {} });
  const started = await api('/api/pty', { action: 'start', project: want || null, cols: xterm.cols, rows: xterm.rows });
  t.session = started.id; t.cwd = started.cwd; drawTermTabs(); pump(t); xterm.focus();
  return t;
}
function closeTerm(t) {
  if (!t) return;
  if (t.session) { const id = t.session; t.session = null; api('/api/pty', { action: 'stop', id }).catch(() => {}); }
  t.xterm.dispose(); t.host.remove(); terms.splice(terms.indexOf(t), 1);
  activeTerm = terms[terms.length - 1] || null; if (activeTerm) showTerm(activeTerm); else drawTermTabs();
}
termClear.onclick = () => { activeTerm?.xterm.clear(); activeTerm?.xterm.focus(); };
termStop.onclick = () => closeTerm(activeTerm);
new ResizeObserver(() => resizeTerm()).observe(termHost);
new MutationObserver(() => { for (const t of terms) t.xterm.options.theme = termTheme(); }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
registerPane({ id: 'terminal', label: 'Terminal', icon: 'term', top: true, key: 'Ctrl+`', node: term, tip: 'A real command window for your computer',
  show: async () => { try { if (!terms.length || (activeTerm && !activeTerm.session && terms.length === 1)) { if (terms.length) closeTerm(terms[0]); await newTerm(); } resizeTerm(); activeTerm?.xterm.focus(); } catch (error) { term.classList.add('hidden'); await showTool('terminal'); toast('Using the simple terminal: ' + error.message); } } });

/* ================= Browser: a real browser beside the chat ================= */
const web = pane('web', '', '<div class="nv-web"><div class="nv-web-bar"></div><div class="nv-web-view" id="nv-web-view" tabindex="0"><img id="nv-web-img" alt="Web page" draggable="false" class="hidden"><div class="nv-blank" id="nv-web-blank">Type a web address or a search above and press Enter.<br>Pages open right here, in a private browser that belongs to JARVIS.<br><br><span class="small">Sign-ins you make here stay on this computer. Downloads are switched off.</span></div></div></div>');
const webBar = web.querySelector('.nv-web-bar'), webView = web.querySelector('#nv-web-view'), webImg = web.querySelector('#nv-web-img'), webBlank = web.querySelector('#nv-web-blank');
const webBack = iconButton('chev', 'Back', 'Go back one page'), webFwd = iconButton('chev', 'Forward', 'Go forward one page'), webReload = iconButton('retry', 'Reload', 'Load this page again');
webBack.firstChild.style.transform = 'rotate(90deg)'; webFwd.firstChild.style.transform = 'rotate(-90deg)';
const webForm = el('form', { style: 'flex:1;display:flex;min-width:0' }), webUrl = el('input', { type: 'text', placeholder: 'Search or type a web address', 'aria-label': 'Web address or search', autocomplete: 'off', spellcheck: false });
webForm.append(webUrl);
const webFill = textButton('check', 'Fill sign-in', 'Fill in the sign-in you saved for this site'), webOut = iconButton('globe', 'Open in my own browser', 'Open this page in your usual browser instead');
const webFull = iconButton('full', 'Full screen', 'Fill the whole screen with this page. Press Esc to leave.');
webFill.classList.add('hidden'); webBar.append(webBack, webFwd, webReload, webForm, webFill, webFull, webOut);
// Full screen: from the button here, or when the page itself asks (for example a video player).
let remoteFull = false;
const goFull = () => webView.requestFullscreen().catch(() => notify('Press the full screen button in the browser bar to fill the screen.'));
webFull.onclick = () => document.fullscreenElement === webView ? document.exitFullscreen() : goFull();
document.addEventListener('fullscreenchange', () => { webSize = ''; setTimeout(webResize, 60); if (document.fullscreenElement !== webView && remoteFull) { remoteFull = false; webCall({ action: 'fullscreen_exit' }).catch(() => {}); } });
function webScreen(snap) { if (!!snap.fullscreen === remoteFull) return; remoteFull = !!snap.fullscreen; if (remoteFull && document.fullscreenElement !== webView) goFull(); else if (!remoteFull && document.fullscreenElement === webView) document.exitFullscreen(); }
const webOffer = el('div', { class: 'nv-web-offer hidden', role: 'status' }); web.querySelector('.nv-web').insertBefore(webOffer, webView);
// Tabs, files a page asks for, and downloads.
const webTabs = el('div', { class: 'nv-web-tabs', role: 'tablist' }); web.querySelector('.nv-web').prepend(webTabs);
const webFile = el('input', { type: 'file', class: 'hidden' }); web.append(webFile);
const webAsk = el('div', { class: 'nv-web-offer hidden', role: 'status' }, '<span>This page is asking you for a file.</span><button class="primary" data-file="choose">Choose a file</button><button class="plain" data-file="cancel">Cancel</button>');
web.querySelector('.nv-web').insertBefore(webAsk, webView);
let tabSig = '', seenDownloads = new Map(), askOpen = false;
function webExtras(snap) {
  const tabs = snap.tabs || [], sig = JSON.stringify(tabs);
  if (sig !== tabSig) {
    tabSig = sig; webTabs.replaceChildren();
    for (const tab of tabs) {
      const chip = el('button', { class: 'nv-web-tab' + (tab.active ? ' on' : ''), type: 'button', role: 'tab', data: { tab: tab.id, tip: tab.title } }, '<span>' + esc(tab.title) + '</span><i data-close-tab="' + esc(tab.id) + '" data-tip="Close this tab">×</i>');
      webTabs.append(chip);
    }
    const add = iconButton('plus', 'New tab', 'Open a new tab'); add.dataset.newTab = '1'; webTabs.append(add);
  }
  if (!!snap.file_request !== askOpen) { askOpen = !!snap.file_request; webAsk.classList.toggle('hidden', !askOpen); if (askOpen) { try { webFile.click(); } catch {} } }
  for (const d of snap.downloads || []) {
    if (seenDownloads.get(d.id) === d.state) continue; seenDownloads.set(d.id, d.state);
    notify(d.state === 'started' ? 'Downloading ' + d.name + '…' : d.state === 'saved' ? 'Saved ' + d.name + ' to Downloads\\JARVIS.' : 'Download of ' + d.name + ' was cancelled.');
  }
}
webTabs.addEventListener('click', async e => {
  try {
    const close = e.target.closest('[data-close-tab]'), tab = e.target.closest('[data-tab]');
    if (close) { e.stopPropagation(); await webCall({ action: 'tab_close', id: close.dataset.closeTab }); }
    else if (e.target.closest('[data-new-tab]')) { await webCall({ action: 'tab_new' }); webUrl.value = ''; webUrl.focus(); }
    else if (tab) await webCall({ action: 'tab_switch', id: tab.dataset.tab });
    else return;
    webSeq = -1; webSize = ''; await webResize(); webFrames();
  } catch (error) { toast(error.message); }
});
webAsk.addEventListener('click', e => { const b = e.target.closest('[data-file]'); if (!b) return; if (b.dataset.file === 'choose') webFile.click(); else webCall({ action: 'upload_cancel' }).catch(() => {}); });
webFile.onchange = async () => {
  const file = webFile.files[0]; webFile.value = ''; if (!file) return;
  if (file.size > 25000000) return toast('Choose a file of up to 25 MB.');
  try {
    const r = await fetch('/api/web/upload?name=' + encodeURIComponent(file.name), { method: 'POST', headers: { 'X-JCC-Token': TOKEN, 'Content-Type': 'application/octet-stream' }, body: file });
    const d = await r.json(); if (!r.ok) throw Error(d.error || 'Upload failed'); notify('Gave ' + d.uploaded + ' to the page.');
  } catch (error) { toast(error.message); }
};
let webSeq = -1, webLoop = false, webQueue = [], webFlush = 0, webSize = '';
const webCall = body => api('/api/web', body);
function webPoint(e) { const r = webView.getBoundingClientRect(); return { x: Math.round(e.clientX - r.left), y: Math.round(e.clientY - r.top) }; }
const mods = e => (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
function webSend(event) { webQueue.push(event); if (!webFlush) webFlush = setTimeout(() => { const events = webQueue; webQueue = []; webFlush = 0; webCall({ action: 'input', events }).catch(() => {}); }, 16); }
async function webResize() {
  const w = webView.clientWidth, h = webView.clientHeight; if (!w || !h || web.classList.contains('hidden')) return;
  const key = w + 'x' + h; if (key === webSize) return; webSize = key;
  try { await webCall({ action: 'resize', width: w, height: h, scale: Math.min(2, devicePixelRatio || 1) }); } catch {}
}
async function webFrames() {
  if (webLoop) return; webLoop = true;
  try {
    while (!web.classList.contains('hidden') && !document.hidden) {
      const snap = await api('/api/web/frame?since=' + webSeq + '&wait=10');
      if (!snap.running) { webSeq = -1; webExtras(snap); webImg.classList.add('hidden'); webImg.removeAttribute('src'); webBlank.classList.remove('hidden'); webBlank.textContent = 'Type a web address or a search above and press Enter.'; break; }
      webSeq = snap.seq;
      if (snap.image) { webImg.src = 'data:image/jpeg;base64,' + snap.image; webImg.classList.remove('hidden'); webBlank.classList.add('hidden'); }
      if (document.activeElement !== webUrl && snap.url && snap.url !== 'about:blank') webUrl.value = snap.url;
      webReload.classList.toggle('on', !!snap.loading); webState(snap); webExtras(snap); webScreen(snap);
    }
  } catch {} finally { webLoop = false; }
}
async function webOpen(query) {
  webBlank.innerHTML = '<i class="nv-spin" style="width:22px;height:22px"></i>'; webBlank.classList.remove('hidden'); webImg.classList.add('hidden');
  try { webSize = ''; const d = await webCall({ action: 'open', query }); await webResize(); webUrl.value = d.opened; webSeq = -1; webFrames(); webView.focus(); }
  catch (error) { webBlank.textContent = error.message; toast(error.message); }
}
webForm.onsubmit = e => { e.preventDefault(); if (webUrl.value.trim()) webOpen(webUrl.value.trim()); };
webBack.onclick = () => webCall({ action: 'back' }).catch(error => toast(error.message));
webFwd.onclick = () => webCall({ action: 'forward' }).catch(error => toast(error.message));
webReload.onclick = () => webCall({ action: 'reload' }).catch(error => toast(error.message));
webOut.onclick = () => { if (/^https?:/.test(webUrl.value)) api('/api/browser/open', { query: webUrl.value }).then(() => notify('Opened in your own browser.')).catch(error => toast(error.message)); };
// The page you are looking at joins your next message by itself; the chip in the chat bar shows it.
const pageChip = el('button', { type: 'button', id: 'nv-page-chip', class: 'hidden', data: { tip: 'JARVIS will read this page with your next message. Click to leave it out.' } });
$('attachment-chips').after(pageChip);
let webSite = '', webSkip = '', offerSig = '';
function drawChip() { const on = !!webSite && webSite !== webSkip && !web.classList.contains('hidden'); pageChip.classList.toggle('hidden', !on); if (on) pageChip.innerHTML = icon('globe') + '<span>' + esc(webSite) + '</span>' + icon('x'); }
function webState(snap) {
  webSite = snap.running && /^https?:/.test(snap.url) ? snap.site : ''; if (webSkip && webSkip !== webSite) webSkip = ''; drawChip();
  webFill.classList.toggle('hidden', !snap.can_fill);
  const offer = snap.login_offer, sig = offer ? offer.site + '|' + offer.user : '';
  if (sig !== offerSig) { offerSig = sig; webOffer.classList.toggle('hidden', !offer); if (offer) webOffer.innerHTML = '<span>Save your sign-in for <b>' + esc(offer.site) + '</b>' + (offer.user ? ' (' + esc(offer.user) + ')' : '') + '? It is kept in Windows’ own secure store.</span><button class="primary" data-login="save">Save</button><button class="plain" data-login="dismiss">Not now</button><button class="plain" data-login="never" data-tip="Never offer to save for this site">Never</button>'; }
}
pageChip.onclick = () => { webSkip = webSite; drawChip(); notify('This page will not be sent with your message.'); };
webOffer.addEventListener('click', async e => { const b = e.target.closest('[data-login]'); if (!b) return; try { await webCall({ action: 'login', decision: b.dataset.login }); webOffer.classList.add('hidden'); offerSig = ''; if (b.dataset.login === 'save') notify('Sign-in saved. Use Fill sign-in next time.'); } catch (error) { toast(error.message); } });
webFill.onclick = () => webCall({ action: 'login', decision: 'fill' }).then(() => webView.focus()).catch(error => toast(error.message));
new MutationObserver(drawChip).observe(web, { attributes: true, attributeFilter: ['class'] });
N.pageForSend = async () => { if (pageChip.classList.contains('hidden')) return false; try { const d = await webCall({ action: 'text', auto: true }); if (d.skipped) { notify(d.reason); return false; } return true; } catch { return false; } };
const BUTTONS = ['left', 'middle', 'right'];
webView.addEventListener('pointerdown', e => { webView.focus(); webView.setPointerCapture(e.pointerId); webSend({ t: 'mousePressed', ...webPoint(e), b: BUTTONS[e.button] || 'left', bs: e.buttons, c: e.detail || 1, m: mods(e) }); e.preventDefault(); });
webView.addEventListener('pointerup', e => webSend({ t: 'mouseReleased', ...webPoint(e), b: BUTTONS[e.button] || 'left', bs: e.buttons, c: e.detail || 1, m: mods(e) }));
let lastMove = 0;
webView.addEventListener('pointermove', e => { const now = performance.now(); if (now - lastMove < (e.buttons ? 16 : 50)) return; lastMove = now; webSend({ t: 'mouseMoved', ...webPoint(e), b: e.buttons & 1 ? 'left' : 'none', bs: e.buttons, m: mods(e) }); }, { passive: true });
webView.addEventListener('wheel', e => { e.preventDefault(); webSend({ t: 'mouseWheel', ...webPoint(e), dx: e.deltaX, dy: e.deltaY, m: mods(e) }); }, { passive: false });
webView.addEventListener('contextmenu', e => e.preventDefault());
webView.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') return;
  e.preventDefault(); e.stopPropagation();
  const text = e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey ? e.key : e.key === 'Enter' ? '\r' : '';
  webSend({ t: 'keyDown', key: e.key, code: e.code, vk: e.keyCode, text, m: mods(e) });
});
webView.addEventListener('keyup', e => { e.preventDefault(); webSend({ t: 'keyUp', key: e.key, code: e.code, vk: e.keyCode, m: mods(e) }); });
webView.addEventListener('paste', e => { const text = e.clipboardData?.getData('text'); if (text) { e.preventDefault(); webSend({ t: 'text', text }); } });
new ResizeObserver(() => webResize()).observe(webView);
document.addEventListener('visibilitychange', () => { if (!document.hidden && !web.classList.contains('hidden') && webSeq >= 0) webFrames(); });
registerPane({ id: 'browser', label: 'Browser', icon: 'globe', top: true, node: web, tip: 'Browse the web next to your chat', show: async () => { await webResize(); try { const snap = await api('/api/web/frame?since=-1'); if (snap.running) { webSeq = -1; webFrames(); } } catch {} if (!webImg.getAttribute('src')) webUrl.focus(); } });
registerPane({ id: 'shared', label: 'Shared pages', icon: 'clip', adv: true, tip: 'Pages sent from your own browser with the JARVIS extension', open: () => showTool('browser') });

/* ================= Computer: let JARVIS use the mouse and keyboard for one task ================= */
const pc = pane('pc', '', '<div class="tool-heading"><div><h2>Computer control</h2><p>JARVIS can click and type on this computer to carry out one task you give it.</p></div></div><div id="nv-pc-body" style="display:flex;flex-direction:column;gap:12px;min-height:0;flex:1"></div>');
const pcBody = pc.querySelector('#nv-pc-body');
let pcTimer = 0, pcSig = '';
const pcCall = body => api('/api/computer', body);
function pcDraw(d) {
  const sig = JSON.stringify([d.enabled, d.mode, d.running, d.step, d.proposal, d.outcome, d.log.length, d.has_key, d.available]);
  if (sig === pcSig) { const img = pcBody.querySelector('#nv-pc-shot'); if (img && d.image) img.src = 'data:image/png;base64,' + d.image; return; }
  pcSig = sig;
  if (!d.available) { pcBody.innerHTML = '<div class="nv-blank">Computer control works on Windows only.</div>'; return; }
  if (!d.enabled) {
    pcBody.innerHTML = '<div class="settings-box"><h3>Switched off</h3><p>When this is on, you can give JARVIS a task such as “open Notepad and write a shopping list”, and it will move the mouse and type for you.</p><ul><li><b>You stay in charge.</b> By default it shows each step and waits for your OK.</li><li><b>It keeps away from private things.</b> It will not act on sign-in, payment, banking or trading windows, and never types passwords.</li><li><b>You can stop it at any time</b> with the Stop button, or Ctrl+Alt+Backspace from anywhere.</li><li><b>What leaves this computer:</b> a picture of your screen goes to Google’s free Gemini AI for each step, so it can see what to do. Close anything private first.</li></ul><label><input type="checkbox" id="nv-pc-agree"> I understand, and I want to switch this on</label><div class="settings-buttons" style="margin-top:12px"><button class="primary" id="nv-pc-on">Switch on computer control</button></div></div>';
    pcBody.querySelector('#nv-pc-on').onclick = async () => { if (!pcBody.querySelector('#nv-pc-agree').checked) return toast('Tick the box first to confirm you understand.'); try { pcDraw(await pcCall({ action: 'settings', enabled: true, mode: 'ask' })); pcPoll(); } catch (error) { toast(error.message); } };
    return;
  }
  const log = d.log.map(row => '<li><b>' + esc(row.text) + '</b></li>').join('');
  pcBody.innerHTML = (d.has_key ? '' : '<div class="settings-status">Computer control needs the free Gemini key. Add it in Settings first.</div>') +
    (d.running ? '<div class="nv-work live" style="margin:0"><div style="display:flex;align-items:center;gap:10px;padding:10px 14px"><i class="nv-spin"></i><b>Working on: ' + esc(d.task) + '</b><span class="small" style="margin-left:auto">Step ' + d.step + ' of ' + d.max_steps + '</span></div></div>'
      : '<form id="nv-pc-form" class="easy-search" style="margin:0"><input id="nv-pc-task" maxlength="600" placeholder="What should JARVIS do? For example: open Notepad and write a shopping list" aria-label="Task for computer control"><button class="primary">Start</button></form>') +
    (d.proposal ? '<div class="settings-box" style="margin:0;border-color:var(--accent)"><h3>Next step: ' + esc(d.proposal.label) + '</h3><p>' + esc(d.proposal.reason) + '</p>' + (d.mode === 'ask' ? '<div class="settings-buttons"><button class="primary" data-pc="approve" data-tip="Let JARVIS do this one step">Do it</button><button class="plain" data-pc="skip" data-tip="Do not do this step; ask the AI for another">Skip</button></div>' : '') + '</div>' : '') +
    (d.running ? '<div class="settings-buttons"><button class="plain" data-pc="stop" style="border-color:var(--bad);color:var(--bad)" data-tip="Stop right now. Also: Ctrl+Alt+Backspace">' + icon('stop') + 'Stop now</button></div>' : '') +
    (!d.running && d.outcome ? '<div class="settings-status">' + esc(d.outcome) + '</div>' : '') +
    (d.image ? '<img id="nv-pc-shot" alt="What JARVIS last saw on your screen" style="width:100%;border:1px solid var(--line);border-radius:var(--r);min-height:0;object-fit:contain" src="data:image/png;base64,' + d.image + '">' : '') +
    (log ? '<ol class="nv-steps" style="padding:0 0 0 6px;overflow:auto">' + log + '</ol>' : '') +
    '<div class="settings-buttons" style="margin-top:auto"><label style="margin:0"><input type="checkbox" id="nv-pc-ask" ' + (d.mode === 'ask' ? 'checked' : '') + '> Ask me before every step</label><button class="plain" id="nv-pc-off" style="margin-left:auto" data-tip="Turn computer control off again">Switch off</button></div>';
  const form = pcBody.querySelector('#nv-pc-form');
  if (form) form.onsubmit = async e => { e.preventDefault(); const text = pcBody.querySelector('#nv-pc-task').value.trim(); if (!text) return; try { pcDraw(await pcCall({ action: 'start', text })); pcPoll(); } catch (error) { toast(error.message); } };
  pcBody.querySelector('#nv-pc-ask').onchange = async e => { if (!e.target.checked && !await confirmBox({ title: 'Let JARVIS act without asking?', text: 'It will click and type on its own until the task is done or you press Stop. Stay at the computer while it works.', ok: 'Yes, run on its own', danger: true })) { e.target.checked = true; return; } try { await pcCall({ action: 'settings', enabled: true, mode: e.target.checked ? 'ask' : 'auto' }); } catch (error) { toast(error.message); } };
  pcBody.querySelector('#nv-pc-off').onclick = async () => { try { pcSig = ''; pcDraw(await pcCall({ action: 'settings', enabled: false, mode: 'ask' })); } catch (error) { toast(error.message); } };
}
pcBody.addEventListener('click', async e => { const b = e.target.closest('[data-pc]'); if (!b) return; b.disabled = true; try { await pcCall({ action: b.dataset.pc }); await pcRefresh(); } catch (error) { toast(error.message); } });
async function pcRefresh() { const d = await api('/api/computer'); pcDraw(d); return d; }
function pcPoll() { clearTimeout(pcTimer); pcTimer = setTimeout(async () => { if (pc.classList.contains('hidden')) return; try { const d = await pcRefresh(); if (d.running) pcPoll(); } catch {} }, 900); }
registerPane({ id: 'computer', label: 'Step-by-step control', icon: 'cursor', adv: true, node: pc, tip: 'Let JARVIS click and type on this computer for a task you choose', show: async () => { pcSig = ''; const d = await pcRefresh(); if (d.running) pcPoll(); } });

/* ================= Screenshot: attach a picture of a window or screen ================= */
N.screenshot = async () => {
  // JARVIS takes the picture itself: no sharing prompt, and a window is captured even when others cover it.
  let list, screens;
  try { const got = await api('/api/screenshot', { action: 'list' }); list = got.windows; screens = got.screens || []; } catch (error) { return toast(error.message); }
  // With more than one screen each is offered by name (which one "the whole screen" would be is anyone's guess).
  const whole = screens.length > 1
    ? screens.map(s => '<button class="nv-shot" data-whole data-screen="' + Number(s.number) + '">' + icon('full') + '<span><b>' + esc(s.label) + '</b><small>' + esc(s.detail) + '</small></span></button>').join('')
    : '<button class="nv-shot" data-whole>' + icon('full') + '<span><b>The whole screen</b><small>JARVIS steps out of the way for a moment</small></span></button>';
  const d = N.dialog('<h2>Take a screenshot</h2><p>Choose what JARVIS should see. The picture is added to your next message.</p><div class="nv-shots">' + whole +
    list.map(w => '<button class="nv-shot" data-id="' + esc(String(w.id)) + '">' + icon('box') + '<span><b>' + esc(w.title) + '</b></span></button>').join('') +
    '</div><div class="actions"><button class="plain" data-close>Cancel</button></div>', 'nv-shotpick');
  d.querySelector('[data-close]').onclick = () => d.close();
  d.querySelectorAll('.nv-shot').forEach(button => button.onclick = async () => {
    d.close();
    try {
      const made = await api('/api/screenshot', button.dataset.whole !== undefined ? { action: 'take', whole: true, ...(button.dataset.screen ? { screen: Number(button.dataset.screen) } : {}) }
        : { action: 'take', id: Number(button.dataset.id) });
      window.pendingUploads.push({ name: made.name, image_id: made.image_id, mime: made.mime }); renderAttachments();
      notify('Screenshot added to your message.'); $('message').focus();
    } catch (error) { toast(error.message); }
  });
};
})();
