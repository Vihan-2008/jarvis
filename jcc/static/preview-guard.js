// The first thing that runs in a sealed preview page (jcc/gui.py puts it at the top of the page, before anything the page
// brought). The rules the page is served with already refuse every request to the internet: pictures, data, code, forms,
// windows. Two things are outside what those rules can refuse, and are closed here:
//   - WebRTC, which can carry a few words to any server on the internet;
//   - frames inside the page: a frame is a fresh start, and this script would not be in it.
// Everything it needs later is taken hold of now, while the page is still as the browser made it, so the page's own code
// cannot change what this does.
(function () {
  'use strict';
  var W = window, D = document, up = W.parent, apply = Reflect.apply, define = Object.defineProperty, own = Object.getOwnPropertyDescriptor, create = Object.create;
  var post = up.postMessage, has = String.prototype.indexOf, lower = String.prototype.toLowerCase, cut = String.prototype.slice;
  // The window is told (only that it happened) when something was stopped, so it can offer to allow the internet.
  function tell() { try { apply(post, up, [{ jarvisPreview: 'blocked' }, '*']); } catch (e) {} }
  W.addEventListener('securitypolicyviolation', function (event) { var what = '' + event.blockedURI; if (apply(has, what, ['http']) === 0 || apply(has, what, ['ws']) === 0) tell(); });

  // No WebRTC (and nothing else that opens a connection of its own).
  var names = Object.getOwnPropertyNames(W);
  for (var i = 0; i < names.length; i++) {
    if (/^(webkit)?RTC|^WebTransport$/.test(names[i])) try { define(W, names[i], { value: undefined, writable: false, enumerable: false, configurable: false }); } catch (e) {}
  }

  // No frames inside the page, wherever they are put: each is taken out before it can load.
  var FRAMES = 'iframe,frame,object,embed,portal,fencedframe', OPTIONS = create(null);
  OPTIONS.childList = true; OPTIONS.subtree = true;
  var inDocument = Document.prototype.querySelectorAll, inTree = DocumentFragment.prototype.querySelectorAll, count = own(NodeList.prototype, 'length').get;
  var drop = Element.prototype.remove, watch = MutationObserver.prototype.observe, trees = [D];
  function sweep() {
    for (var t = 0; t < trees.length; t++) {
      try {
        var found = apply(t ? inTree : inDocument, trees[t], [FRAMES]), n = apply(count, found, []);
        for (var f = 0; f < n; f++) { apply(drop, found[f], []); tell(); }
      } catch (e) {}
    }
  }
  var seen = new MutationObserver(sweep);
  apply(watch, seen, [D, OPTIONS]);
  // A shadow tree is looked into as well: the page cannot make one without this hearing of it (and none can be made
  // by copying an element, which would make one this had not heard of)...
  var attach = Element.prototype.attachShadow;
  define(Element.prototype, 'attachShadow', { writable: false, configurable: false, value: function attachShadow(init) {
    var asked = Object(init), plain = create(null);
    plain.mode = '' + asked.mode; plain.clonable = false;
    if (asked.delegatesFocus) plain.delegatesFocus = true;
    if (asked.serializable) plain.serializable = true;
    if (asked.slotAssignment !== undefined) plain.slotAssignment = '' + asked.slotAssignment;
    var tree = apply(attach, this, [plain]);
    try { define(trees, trees.length, { value: tree, writable: true, enumerable: true, configurable: true }); apply(watch, seen, [tree, OPTIONS]); } catch (e) {}
    return tree;
  } });
  // ...and the kind that is written as markup (which could be closed to this script) is not made at all. In the page as
  // it was sent the word for it has been taken out already; here it is refused in markup the page writes as it goes.
  var tail = '';
  function hidden(text) { return apply(has, apply(lower, text, []), ['shadowrootmode']) >= 0; }
  function written(method) {
    return function () {
      var text = '';
      for (var a = 0; a < arguments.length; a++) text += '' + arguments[a];
      if (hidden(tail + text)) { tell(); return; }       // (text is one plain string by now: what is judged is what is handed on)
      tail = apply(cut, tail + text, [-13]);
      return apply(method, this, [text]);
    };
  }
  function parsed(method) {
    return function (markup) { var text = '' + markup; if (hidden(text)) { tell(); text = ''; } return apply(method, this, [text]); };
  }
  define(Document.prototype, 'write', { writable: false, configurable: false, value: written(Document.prototype.write) });
  define(Document.prototype, 'writeln', { writable: false, configurable: false, value: written(Document.prototype.writeln) });
  var places = [[W.Element && Element.prototype, 'setHTMLUnsafe'], [W.ShadowRoot && ShadowRoot.prototype, 'setHTMLUnsafe'], [W.Document, 'parseHTMLUnsafe']];
  for (var p = 0; p < places.length; p++) {
    if (places[p][0] && typeof places[p][0][places[p][1]] === 'function') define(places[p][0], places[p][1], { writable: false, configurable: false, value: parsed(places[p][0][places[p][1]]) });
  }
})();
