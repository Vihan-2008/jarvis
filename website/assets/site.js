/* JARVIS website: the theme toggle, the download button for the visitor's system, and the particle orb.
   Everything else on the site works without this file. No network requests, no cookies, no tracking. */
(function () {
  'use strict';
  var root = document.documentElement;
  var KEY = 'jarvis-site-theme';
  var lightQuery = window.matchMedia ? matchMedia('(prefers-color-scheme: light)') : null;
  var motionQuery = window.matchMedia ? matchMedia('(prefers-reduced-motion: reduce)') : null;

  root.classList.remove('no-js');
  root.classList.add('js');

  /* ---------- theme: dark by default, follows the system, a choice is remembered ---------- */
  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function remember(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* storage may be blocked */ } }
  function shown() {
    var t = root.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return lightQuery && lightQuery.matches ? 'light' : 'dark';
  }
  function apply() { root.setAttribute('data-shown', shown()); orbs.forEach(function (o) { o.refresh(); }); }
  var first = saved();
  if (first === 'light' || first === 'dark') root.setAttribute('data-theme', first);
  var orbs = [];
  apply();
  if (lightQuery && lightQuery.addEventListener) lightQuery.addEventListener('change', apply);

  /* ---------- the download button picks the visitor's system ---------- */
  function system() {
    var p = ((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '') + ' ' + (navigator.userAgent || '');
    if (/iPhone|iPad|iPod|Android/i.test(p)) return '';
    if (/Win/i.test(p)) return 'windows';
    if (/Mac/i.test(p)) return 'mac';
    return '';
  }

  /* ---------- the orb: a sphere of points, like the app's core, drawn on a 2D canvas ---------- */
  function Orb(canvas, opts) {
    var ctx = canvas.getContext && canvas.getContext('2d');
    if (!ctx) { canvas.parentNode.classList.add('still-fallback'); this.refresh = function () {}; return; }
    var COUNT = opts.count, pts = new Float32Array(COUNT * 4), golden = Math.PI * (3 - Math.sqrt(5));
    for (var i = 0; i < COUNT; i++) {
      var k = (i * 7919) % COUNT, y = 1 - (k + 0.5) / COUNT * 2, rad = Math.sqrt(1 - y * y), a = k * golden;
      pts[i * 4] = Math.cos(a) * rad; pts[i * 4 + 1] = y; pts[i * 4 + 2] = Math.sin(a) * rad; pts[i * 4 + 3] = (i * 0.61803398875) % 1;
    }
    var raf = 0, visible = true, start = 0, clock = 2.2, last = 0, size = 0;
    function smooth(e0, e1, x) { var t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); }
    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2), side = Math.round((canvas.clientWidth || 300) * dpr);
      if (side !== size && side > 0) { size = canvas.width = canvas.height = side; }
    }
    function draw(t) {
      resize();
      if (!size) return;
      var light = shown() === 'light', w = size, half = w / 2;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, w, w);
      ctx.globalCompositeOperation = light ? 'source-over' : 'lighter';
      var ry = t * 0.11, cy = Math.cos(ry), sy = Math.sin(ry), rx = -0.22, cx = Math.cos(rx), sx = Math.sin(rx);
      var base = w / opts.dot;
      for (var i = 0; i < COUNT; i++) {
        var px = pts[i * 4], py = pts[i * 4 + 1], pz = pts[i * 4 + 2], seed = pts[i * 4 + 3];
        var n = Math.sin(px * 1.9 + t * 0.55 + Math.sin(py * 2.3 - t * 0.35)) * Math.cos(pz * 1.7 - t * 0.45 + Math.sin(px * 1.3 + t * 0.2)) * 0.8;
        var n2 = Math.sin(px * 3.6 - t * 0.7) * Math.sin(py * 3.1 + pz * 2.2 + t * 0.3);
        var qx, qy, qz, halo = seed > 0.86;
        if (halo) {
          var band = (seed * 37) % 1, ang = seed * 400 + t * (0.25 + band * 0.35), r2 = 1.22 + band * 0.2 + n2 * 0.04;
          var hx = Math.cos(ang) * r2, hy = (band - 0.5) * 0.16 + n * 0.05, hz = Math.sin(ang) * r2;
          var tilt = 0.42 + Math.floor(seed * 3) * 0.9, ct = Math.cos(tilt), st = Math.sin(tilt);
          qx = hx; qy = hy * ct + hz * st; qz = -hy * st + hz * ct;
        } else {
          var r = 1 + 0.08 * n + 0.025 * n2;
          qx = px * r; qy = py * r; qz = pz * r;
        }
        var x1 = qx * cy + qz * sy, z1 = -qx * sy + qz * cy;
        var y2 = qy * cx - z1 * sx, z2 = qy * sx + z1 * cx;
        var z = z2 + 3.6, depth = Math.min(1, Math.max(0, (1.9 - z2) / 3.2));
        var X = half + x1 * 2.5 / z * half, Y = half - y2 * 2.5 / z * half;
        var s = base * (0.55 + 0.75 * ((seed * 91) % 1) + Math.max(n, 0) * 0.9) * (0.55 + depth * 0.9) * (halo ? 0.8 : 1);
        var m = smooth(-0.55, 0.6, n + py * 0.45), pe = smooth(0.25, 0.85, n2) * 0.75;
        var cr = 0.55 + (0.33 - 0.55) * m, cg = 0.47 + (0.83 - 0.47) * m, cb = 1 + (0.93 - 1) * m;
        cr += (1 - cr) * pe; cg += (0.62 - cg) * pe; cb += (0.48 - cb) * pe;
        if (light) { cr *= 0.42; cg *= 0.36; cb *= 0.62; }
        var alpha = (0.2 + depth * 0.8) * (halo ? 0.55 : 1) * (light ? 0.9 : 0.62);
        ctx.fillStyle = 'rgba(' + (cr * 255 | 0) + ',' + (cg * 255 | 0) + ',' + (cb * 255 | 0) + ',' + alpha.toFixed(3) + ')';
        ctx.beginPath(); ctx.arc(X, Y, Math.max(0.4, s / 2), 0, 6.2832); ctx.fill();
      }
    }
    function still() { return (motionQuery && motionQuery.matches) || document.hidden || !visible; }
    function frame(now) {
      raf = 0;
      if (still()) { draw(clock); return; }
      var dt = last ? Math.min(0.05, (now - last) / 1000) : 0; last = now;
      clock += dt * 0.75;
      draw(clock);
      raf = requestAnimationFrame(frame);
    }
    function go() { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } }
    this.refresh = go;
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) { visible = entries[0].isIntersecting; if (visible) go(); }).observe(canvas);
    }
    document.addEventListener('visibilitychange', go);
    window.addEventListener('resize', go);
    if (motionQuery && motionQuery.addEventListener) motionQuery.addEventListener('change', go);
    go();
  }

  function ready() {
    var toggle = document.querySelector('.theme-toggle');
    if (toggle) {
      toggle.hidden = false;
      var label = function () { toggle.setAttribute('aria-label', shown() === 'light' ? 'Switch to the dark theme' : 'Switch to the light theme'); };
      label();
      toggle.addEventListener('click', function () {
        var next = shown() === 'light' ? 'dark' : 'light';
        root.setAttribute('data-theme', next); remember(next); apply(); label();
      });
      if (lightQuery && lightQuery.addEventListener) lightQuery.addEventListener('change', label);
    }

    var main = document.getElementById('download-main');
    if (main) {
      var sys = system(), text = main.querySelector('[data-label]'), hint = document.getElementById('download-hint');
      if (sys === 'windows') {
        main.href = main.getAttribute('data-windows');
        text.textContent = 'Download for Windows';
        if (hint) hint.textContent = 'JARVIS-Setup.exe. Other systems and the zip are on the download page.';
      } else if (sys === 'mac') {
        main.href = main.getAttribute('data-mac');
        text.textContent = 'Download for macOS';
        if (hint) hint.textContent = 'JARVIS.dmg, new on Mac. Other systems are on the download page.';
      }
    }

    var canvases = document.querySelectorAll('canvas[data-orb]');
    for (var i = 0; i < canvases.length; i++) {
      var small = canvases[i].getAttribute('data-orb') === 'small';
      orbs.push(new Orb(canvases[i], small ? { count: 900, dot: 120 } : { count: 2200, dot: 190 }));
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
