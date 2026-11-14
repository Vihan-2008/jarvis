/* NOVA core: a living particle sphere drawn on the GPU. No libraries, no network.
   window.NovaCore = { mount(canvas), set({energy, light, docked, code}), pulse(), still(bool) }
   It has two forms: the living sphere, and (code: true) a block of points gathered into lines, for coding. */
window.NovaCore = (() => {
  const VERT = `
precision highp float;
attribute vec3 aPos;
attribute float aSeed;
uniform float uTime, uEnergy, uPulse, uSize, uVoice, uBeat, uCode;
uniform mediump float uLight;
uniform vec2 uTilt;
varying vec3 vColor;
varying float vAlpha;
// Simplex noise by Ian McEwan and Stefan Gustavson (MIT licence).
vec4 permute(vec4 x){return mod(((x*34.0)+1.0)*x,289.0);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0);const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.0-g;vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+2.0*C.xxx;vec3 x3=x0-1.0+3.0*C.xxx;
  i=mod(i,289.0);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=1.0/7.0;vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0;vec4 s1=floor(b1)*2.0+1.0;vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
mat3 rotY(float a){float c=cos(a),s=sin(a);return mat3(c,0.0,-s,0.0,1.0,0.0,s,0.0,c);}
mat3 rotX(float a){float c=cos(a),s=sin(a);return mat3(1.0,0.0,0.0,0.0,c,s,0.0,-s,c);}
void main(){
  float t=uTime;
  vec3 p=aPos;
  float halo=step(0.86,aSeed);
  float flow=0.16+uEnergy*0.5;
  float n=snoise(p*1.35+vec3(0.0,t*flow*0.6,t*flow));
  float n2=snoise(p*3.1-vec3(t*flow*1.2,0.0,t*0.2));
  float wave=sin(length(p.xy)*5.0-uPulse*9.0)*uPulse*(1.0-uPulse)*1.4;
  // While JARVIS speaks, rings of movement run out from the middle in time with the voice.
  float talk=uVoice*(0.10+0.13*sin(length(p.xy)*6.5-uBeat*7.0)+0.07*sin(p.y*11.0+uBeat*11.0));
  float r=1.0+(0.07+uEnergy*0.24)*n+(0.02+uEnergy*0.07)*n2+wave*0.22+talk;
  vec3 q=p*r;
  float shown=1.0,lit=0.0,rowAt=p.y;
  if(uCode>0.001&&halo<0.5){
    // Coding: the same points drawn onto a block and gathered into rows on its faces, like lines of code: each line
    // starts at its own indent, runs to its own length and has gaps between its words. A bright line moves down the
    // block as if it were being written.
    vec3 a=abs(p);
    float m=max(a.x,max(a.y,a.z));
    vec3 c=p/m;
    float side=step(a.y,m-0.0001);                      // 1 on the four sides, 0 on the top and the bottom
    float face=side>0.5?(a.x>a.z?(p.x>0.0?1.0:2.0):(p.z>0.0?3.0:4.0)):(p.y>0.0?5.0:6.0);
    float R=5.0;
    float across=side>0.5?c.y:c.z;                       // which row a point is in
    float along=side>0.5?(a.x>a.z?c.z:c.x):c.x;          // where it is along that row
    float row=floor(across*R+0.5);
    float h1=fract(sin(row*12.9898+face*78.233)*43758.5453);
    float h2=fract(sin(row*39.3468+face*11.135)*24634.6345);
    float indent=-0.86+floor(h1*3.0)*0.2;
    float end=indent+0.5+h2*1.1;
    float word=fract(sin(dot(vec3(row,floor((along+1.0)*5.0),face),vec3(12.9898,78.233,37.719)))*43758.5453);
    shown=step(indent,along)*step(along,min(end,0.9))*step(0.2,word)*step(abs(row),R-0.5);
    // Each line has a little height (a band of points, not a hair), and what is not part of a line stays as a faint
    // fill, so the block keeps its body. The block's edges are drawn as they are.
    float mid=a.x+a.y+a.z-m-min(a.x,min(a.y,a.z));
    float edge=smoothstep(0.93,0.985,mid/m);
    float band=(row+(across*R-row)*0.36)/R;
    if(side>0.5)c.y=mix(band,c.y,edge);else c.z=mix(band,c.z,edge);
    shown=max(mix(0.07,1.0,shown),edge*0.85);
    vec3 block=mix(normalize(c),c,0.8)*0.8;
    float head=R-fract(t*0.11+face*0.137)*(2.0*R+3.0)+1.0;
    lit=smoothstep(1.3,0.0,abs(row-head));
    block*=1.0+0.012*n+talk*0.6+lit*0.02;
    q=mix(q,block,uCode);
    rowAt=mix(p.y,row/R,uCode);
  }
  if(halo>0.5){
    float band=fract(aSeed*37.0);
    float ang=aSeed*400.0+t*(0.25+band*0.35)*(1.0+uEnergy*1.6);
    // (coding) the rings are drawn in dashes
    float cut=6.2831853/18.0;
    ang=mix(ang,floor(ang/cut)*cut+fract(ang/cut)*cut*0.45,uCode);
    float rad=1.22+band*0.2+n2*0.04;
    q=vec3(cos(ang)*rad,(band-0.5)*0.16+n*0.05,sin(ang)*rad);
    q=rotX(0.42+floor(aSeed*3.0)*0.9)*q;
  }
  q=rotY(t*0.11+uTilt.x*0.6)*q;
  q=rotX(-0.22-0.16*uCode+uTilt.y*0.45)*q;
  float z=q.z+3.6;
  gl_Position=vec4(q.xy*2.5/z,0.0,1.0);
  float depth=clamp((1.9-q.z)/3.2,0.0,1.0);
  gl_PointSize=uSize*(0.55+0.75*fract(aSeed*91.0)+max(n,0.0)*0.9*(1.0-0.8*uCode)+uEnergy*0.35+uVoice*0.55+lit*uCode*0.9)*(0.55+depth*0.9)*(halo>0.5?0.8:1.0)*mix(1.0,0.86,uCode);
  vec3 violet=vec3(0.55,0.47,1.0),cyan=vec3(0.33,0.83,0.93),peach=vec3(1.0,0.62,0.48);
  vec3 c=mix(violet,cyan,smoothstep(-0.55,0.6,n+p.y*0.45));
  c=mix(c,peach,smoothstep(0.25,0.85,n2+uEnergy*0.35)*0.75*(1.0-0.85*uCode));
  // (coding) cooler, like a terminal: mint running to violet down the block, and the line being written in warm white
  vec3 mint=vec3(0.30,0.93,0.72);
  c=mix(c,mix(violet,mint,smoothstep(-0.9,0.8,rowAt)),uCode*0.85);
  c=mix(c,vec3(1.0,0.9,0.7),lit*uCode*0.8);
  c=mix(c,c*vec3(0.42,0.36,0.62),uLight);
  vColor=c;
  vAlpha=(0.2+depth*0.8)*(halo>0.5?0.55:1.0)*mix(0.62,0.9,uLight)*(1.0+uVoice*0.5)*mix(1.0,shown*(0.95+lit*0.5),uCode);
}`;
  const FRAG = `
precision mediump float;
varying vec3 vColor;varying float vAlpha;uniform mediump float uLight;
void main(){
  float d=length(gl_PointCoord-0.5);
  float a=smoothstep(0.5,0.08,d)*vAlpha;
  gl_FragColor=mix(vec4(vColor*a,a),vec4(vColor,a),uLight);
}`;
  const COUNT = 26000;
  let gl = null, canvas = null, prog = null, raf = 0, loc = {}, start = performance.now();
  let energy = 0.2, energyTarget = 0.2, light = 0, pulse = 1, pulseAt = -10, docked = false, frozen = false;
  let lite = false;
  let tiltX = 0, tiltY = 0, tx = 0, ty = 0, drawCount = COUNT, slow = 0, lastFrame = 0, clock = 0, voice = 0, voiceTarget = 0, beat = 0;
  let code = 0, codeTarget = 0;                    // 0: the living sphere. 1: its coding form, a block of lines of points.
  // Since when this window has not been the one in use (another program has the keyboard); 0 while it is in use. A window
  // that is not in use and has nothing going on draws only a few times a second, and after a minute rests altogether.
  // (JARVIS's windows are drawn even while other windows cover them, so this is what keeps an idle one from costing anything.)
  let away = 0, due = false;                       // due: something was changed, so one more picture is drawn even while resting
  const REST_GAP = 100, REST_AFTER = 60000;
  const quiet = () => voice < 0.01 && voiceTarget === 0 && energyTarget < 0.5 && performance.now() - pulseAt > 1400;

  function compile(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
    return shader;
  }
  function build() {
    prog = gl.createProgram();
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    const data = new Float32Array(COUNT * 4), golden = Math.PI * (3 - Math.sqrt(5));
    // Seeds are shuffled so drawing fewer points still covers the whole sphere evenly.
    for (let i = 0; i < COUNT; i++) {
      const k = (i * 7919) % COUNT, y = 1 - (k + 0.5) / COUNT * 2, radius = Math.sqrt(1 - y * y), angle = k * golden;
      data[i * 4] = Math.cos(angle) * radius;
      data[i * 4 + 1] = y;
      data[i * 4 + 2] = Math.sin(angle) * radius;
      data[i * 4 + 3] = (i * 0.61803398875) % 1;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    const pos = gl.getAttribLocation(prog, 'aPos'), seed = gl.getAttribLocation(prog, 'aSeed');
    gl.enableVertexAttribArray(pos); gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(seed); gl.vertexAttribPointer(seed, 1, gl.FLOAT, false, 16, 12);
    for (const name of ['uTime', 'uEnergy', 'uPulse', 'uSize', 'uLight', 'uTilt', 'uVoice', 'uBeat', 'uCode']) loc[name] = gl.getUniformLocation(prog, name);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
  }
  function resize() {
    if (!canvas) return;
    const side = docked ? (lite ? 112 : 160) : Math.round(Math.min(canvas.clientWidth || 400, lite ? 420 : 760) * (lite ? 1 : Math.min(window.devicePixelRatio || 1, 2)));
    if (canvas.width !== side) { canvas.width = canvas.height = side; gl.viewport(0, 0, side, side); }
  }
  function frame(now) {
    raf = 0;
    if (!gl || document.hidden) return;
    // Draw less often when little is happening, and always on light settings, to spare weak hardware.
    const resting = away && quiet();
    if (resting && now - away > REST_AFTER && !due) { lastFrame = 0; return; }   // asleep until wake(): used again, or something happens
    due = false;
    const gap = resting ? REST_GAP : lite ? 32 : (docked && quiet() ? 48 : 0);
    if (gap && lastFrame && now - lastFrame < gap) { raf = requestAnimationFrame(frame); return; }
    const dt = Math.min(0.05, (now - (lastFrame || now)) / 1000); lastFrame = now;
    if (!frozen) {
      clock += dt * (0.55 + energy * 1.1);
      // Adapt to slower machines by drawing fewer points instead of dropping frames.
      if (dt > (gap ? gap / 1000 + 0.014 : 0.024)) { if (++slow > 30 && drawCount > 2400) { drawCount = Math.round(drawCount * 0.7); slow = 0; } } else if (slow > 0) slow--;
    }
    energy += (energyTarget - energy) * Math.min(1, dt * 2.6);
    voice += (voiceTarget - voice) * Math.min(1, dt * 22); beat += dt * (1 + voice * 2);
    code += (codeTarget - code) * Math.min(1, dt * 3.4); if (Math.abs(codeTarget - code) < 0.002) code = codeTarget;
    tiltX += (tx - tiltX) * Math.min(1, dt * 3); tiltY += (ty - tiltY) * Math.min(1, dt * 3);
    pulse = Math.min(1, (now - pulseAt) / 1400);
    resize();
    gl.blendFunc(light > 0.5 ? gl.SRC_ALPHA : gl.ONE, light > 0.5 ? gl.ONE_MINUS_SRC_ALPHA : gl.ONE);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform1f(loc.uTime, clock); gl.uniform1f(loc.uEnergy, energy); gl.uniform1f(loc.uPulse, pulse);
    gl.uniform1f(loc.uLight, light); gl.uniform2f(loc.uTilt, tiltX, tiltY); gl.uniform1f(loc.uVoice, voice); gl.uniform1f(loc.uBeat, beat); gl.uniform1f(loc.uCode, code);
    gl.uniform1f(loc.uSize, canvas.width / (docked ? 58 : 205) * (lite ? 1.45 : 1));
    gl.drawArrays(gl.POINTS, 0, docked ? Math.min(drawCount, lite ? 1800 : 5200) : drawCount);
    const settled = Math.abs(energyTarget - energy) < 0.004 && pulse >= 1 && Math.abs(tx - tiltX) < 0.002 && voice < 0.004 && voiceTarget === 0 && code === codeTarget;
    if (!frozen || !settled) raf = requestAnimationFrame(frame);
  }
  function wake() { if (!raf && gl && !document.hidden) { lastFrame = 0; raf = requestAnimationFrame(frame); } }
  return {
    mount(target) {
      canvas = target;
      try {
        gl = canvas.getContext('webgl', { alpha: true, antialias: false, premultipliedAlpha: true, powerPreference: 'high-performance' });
        if (!gl) throw Error('WebGL unavailable');
        build();
      } catch (error) { gl = null; return false; }
      canvas.addEventListener('webglcontextlost', event => { event.preventDefault(); cancelAnimationFrame(raf); raf = 0; });
      canvas.addEventListener('webglcontextrestored', () => { try { build(); wake(); } catch { gl = null; } });
      document.addEventListener('visibilitychange', wake);
      window.addEventListener('resize', () => { due = true; wake(); });
      window.addEventListener('pointermove', event => {
        tx = (event.clientX / innerWidth - 0.5) * (docked ? 0.25 : 1); ty = (event.clientY / innerHeight - 0.5) * (docked ? 0.25 : 1);
        if (away) away = performance.now();        // the pointer is over it: looked at, so not asleep yet
        if (frozen) return; wake();
      }, { passive: true });
      away = document.hasFocus() ? 0 : performance.now();
      window.addEventListener('blur', () => { away = performance.now(); });
      window.addEventListener('focus', () => { away = 0; wake(); });
      wake();
      return true;
    },
    set(options) {
      if (options.energy !== undefined) energyTarget = options.energy;
      if (options.light !== undefined) light = options.light ? 1 : 0;
      if (options.docked !== undefined) docked = options.docked;
      if (options.code !== undefined) codeTarget = options.code ? 1 : 0;
      due = true; wake();
    },
    pulse() { pulseAt = performance.now(); wake(); },
    light(value) { lite = !!value; drawCount = lite ? Math.min(drawCount, 4200) : COUNT; due = true; wake(); },
    // True when the browser is drawing without a real graphics card.
    get software() {
      if (!gl) return true;
      try { const info = gl.getExtension('WEBGL_debug_renderer_info'); const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : ''; return /swiftshader|llvmpipe|software|basic render/i.test(name); } catch { return false; }
    },
    voice(value) { voiceTarget = Math.max(0, Math.min(1, value || 0)); wake(); },
    still(value) { frozen = !!value; wake(); },
    get ok() { return !!gl; }
  };
})();
