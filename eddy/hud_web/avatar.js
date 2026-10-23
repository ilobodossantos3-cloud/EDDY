/* Núcleo holográfico do Eddy: orbe + anéis + nuvem de partículas ligadas + anel de onda.
   Reage ao estado (idle/listening/thinking/speaking/error) e ao nível de áudio. Sem dependências. */
(function () {
  const cv = document.getElementById('avatar');
  const ctx = cv.getContext('2d');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const N = reduce ? 70 : 150;
  const P = [];
  for (let i = 0; i < N; i++) {
    const th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    P.push({ th, ph, r: 0.5 + Math.random() * 0.5, w: 0.6 + Math.random() * 0.8, s: Math.random() });
  }
  const T = {
    idle:      { speed: 0.18, glow: 0.55, pull: 1.0,  wave: 0.0,  ring: 0.2 },
    listening: { speed: 0.35, glow: 0.9,  pull: 0.95, wave: 0.9,  ring: 0.5 },
    thinking:  { speed: 1.5,  glow: 1.0,  pull: 0.72, wave: 0.15, ring: 1.0 },
    speaking:  { speed: 0.5,  glow: 1.0,  pull: 1.0,  wave: 1.0,  ring: 0.6 },
    error:     { speed: 0.9,  glow: 0.9,  pull: 0.85, wave: 0.2,  ring: 0.8 },
  };
  let cur = Object.assign({}, T.idle), target = T.idle, state = 'idle', level = 0, levelT = 0, panic = false;
  let w = 0, h = 0, dpr = 1, t0 = performance.now(), rot = 0;

  function rgbVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  let colA = rgbVar('--core-a', '53,224,255'), colB = rgbVar('--core-b', '120,160,255');

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = cv.clientWidth; h = cv.clientHeight;
    cv.width = Math.max(1, Math.floor(w * dpr)); cv.height = Math.max(1, Math.floor(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  new ResizeObserver(resize).observe(cv); resize();

  function lerp(a, b, k) { return a + (b - a) * k; }
  function noise(x) { return Math.sin(x) * 0.5 + Math.sin(x * 2.3 + 1.7) * 0.3 + Math.sin(x * 4.1 + 0.4) * 0.2; }

  function frame(now) {
    const t = (now - t0) / 1000;
    const dt = Math.min(0.05, (now - (frame.last || now)) / 1000); frame.last = now;
    for (const k in cur) cur[k] = lerp(cur[k], target[k], 0.06);
    level = lerp(level, levelT, 0.3);
    rot += dt * cur.speed;
    const tint = panic ? '255,77,106' : (state === 'error' ? '255,179,71' : colA);
    ctx.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2, R = Math.min(w, h) * 0.42;
    if (R < 20) return requestAnimationFrame(frame);

    // halo
    let g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.25);
    g.addColorStop(0, `rgba(${tint},${0.20 * cur.glow})`); g.addColorStop(0.55, `rgba(${tint},${0.05 * cur.glow})`); g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);

    // anéis
    const rings = [0.64, 0.8, 0.94, 1.08];
    rings.forEach((rr, i) => {
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(rot * (i % 2 ? -1 : 1) * (0.6 + i * 0.25) + i);
      ctx.strokeStyle = `rgba(${tint},${0.18 + 0.35 * cur.ring * (i === 1 ? 1 : 0.6)})`;
      ctx.lineWidth = i === 2 ? 2 : 1;
      ctx.setLineDash(i === 0 ? [2, 7] : i === 1 ? [60, 14, 6, 14] : i === 2 ? [140, 40] : [1, 12]);
      ctx.beginPath(); ctx.arc(0, 0, R * rr * (1 + level * 0.02 * (i + 1)), 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    });
    ctx.setLineDash([]);

    // anel de onda (áudio)
    if (cur.wave > 0.02) {
      ctx.beginPath();
      const base = R * 0.86, amp = R * 0.1 * cur.wave * (0.15 + level * 1.6);
      for (let a = 0; a <= Math.PI * 2 + 0.05; a += 0.05) {
        const r = base + amp * noise(a * 3 + t * 5) + (state === 'speaking' ? amp * 0.4 * Math.sin(a * 9 - t * 8) : 0);
        const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
        a === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.closePath(); ctx.strokeStyle = `rgba(${tint},${0.5 + 0.4 * cur.wave})`; ctx.lineWidth = 1.6;
      ctx.shadowColor = `rgba(${tint},0.9)`; ctx.shadowBlur = 12; ctx.stroke(); ctx.shadowBlur = 0;
    }

    // partículas 3D
    const pts = [];
    const cosT = Math.cos(rot), sinT = Math.sin(rot), tilt = 0.35, ct = Math.cos(tilt), st = Math.sin(tilt);
    for (const p of P) {
      const pulse = cur.pull + (state === 'thinking' ? 0.06 * Math.sin(t * 6 + p.s * 9) : 0) + level * 0.06 * p.s;
      const rr = p.r * pulse;
      let x = rr * Math.sin(p.ph) * Math.cos(p.th + rot * p.w), y = rr * Math.cos(p.ph), z = rr * Math.sin(p.ph) * Math.sin(p.th + rot * p.w);
      const y2 = y * ct - z * st, z2 = y * st + z * ct;
      const persp = 1 / (1.9 - z2 * 0.6);
      pts.push({ x: cx + x * R * persp * 1.15, y: cy + y2 * R * persp * 1.15, z: z2, a: 0.25 + 0.75 * (z2 + 1) / 2 });
    }
    ctx.lineWidth = 0.6;
    const lim = (R * 0.26) ** 2;
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y, d = dx * dx + dy * dy;
      if (d < lim) { ctx.strokeStyle = `rgba(${tint},${(1 - d / lim) * 0.35 * Math.min(pts[i].a, pts[j].a)})`; ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[j].x, pts[j].y); ctx.stroke(); }
    }
    for (const p of pts) { ctx.fillStyle = `rgba(${tint},${p.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, 0.9 + p.a * 1.5, 0, 7); ctx.fill(); }

    // núcleo
    const cr = R * 0.2 * (1 + 0.05 * Math.sin(t * 2.2) + level * 0.35);
    g = ctx.createRadialGradient(cx, cy, 0, cx, cy, cr * 2.4);
    g.addColorStop(0, 'rgba(255,255,255,0.95)'); g.addColorStop(0.25, `rgba(${tint},0.85)`); g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.globalAlpha = 0.55 + 0.45 * cur.glow; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, cr * 2.4, 0, 7); ctx.fill(); ctx.globalAlpha = 1;

    // varrimento
    const sy = cy - R + ((t * 0.18) % 1) * R * 2;
    ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, R * 1.05, 0, 7); ctx.clip();
    const sg = ctx.createLinearGradient(0, sy - 18, 0, sy + 18);
    sg.addColorStop(0, 'rgba(0,0,0,0)'); sg.addColorStop(0.5, `rgba(${tint},0.14)`); sg.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = sg; ctx.fillRect(cx - R * 1.1, sy - 18, R * 2.2, 36); ctx.restore();

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  window.EddyAvatar = {
    setState(s) { state = T[s] ? s : 'idle'; target = T[state]; },
    setLevel(v) { levelT = Math.max(0, Math.min(1, v || 0)); },
    setPanic(on) { panic = !!on; },
    refreshTheme() { colA = rgbVar('--core-a', colA); colB = rgbVar('--core-b', colB); },
  };
})();
