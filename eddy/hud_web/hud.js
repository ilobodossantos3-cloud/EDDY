/* HUD do Eddy: só desenha o estado recebido do núcleo por WebSocket. Sem lógica de negócio. */
(function () {
  const $ = (id) => document.getElementById(id);
  const token = new URLSearchParams(location.search).get('t') || '';
  const STATE_LABEL = { idle: 'EM ESPERA', listening: 'A OUVIR', thinking: 'A PENSAR', speaking: 'A FALAR', error: 'ERRO' };
  let ws, retry = 1000, state = 'idle', pttHeld = false, confirmTimer = null, confirmId = null, hudData = null;
  const liveActions = [];

  /* ---------- relógio ---------- */
  const DIAS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];
  function tick() {
    const d = new Date();
    $('clock').textContent = d.toLocaleTimeString('pt-PT', { hour12: false });
    $('date').textContent = DIAS[d.getDay()] + ' · ' + d.toLocaleDateString('pt-PT');
  }
  setInterval(tick, 1000); tick();

  /* ---------- ligação ---------- */
  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws?t=${encodeURIComponent(token)}`);
    ws.onopen = () => { retry = 1000; $('offline').hidden = true; send({ type: 'hello' }); };
    ws.onclose = () => { $('offline').hidden = false; setTimeout(connect, retry); retry = Math.min(retry * 1.6, 6000); };
    ws.onmessage = (e) => { try { on(JSON.parse(e.data)); } catch (_) {} };
  }

  function on(m) {
    const d = m.data || {};
    switch (m.type) {
      case 'hud': renderHud(d); break;
      case 'state': setState(d.state); break;
      case 'transcript': $('heard').textContent = d.text; break;
      case 'reply': $('said').textContent = d.text; break;
      case 'audio_level':
        if (d.src === 'in') { $('meter').style.width = Math.round(d.level * 100) + '%'; if (state === 'listening') EddyAvatar.setLevel(d.level); }
        else if (state === 'speaking') EddyAvatar.setLevel(d.level);
        break;
      case 'action_pending': pushAction({ summary: d.summary, level: d.level, pending: true }); break;
      case 'action_done': settleAction(d); break;
      case 'action_cancelled': settleAction(d); break;
      case 'confirm_request': showConfirm(d); break;
      case 'confirm_done': hideConfirm(); break;
      case 'panic': document.body.classList.add('is-panic'); EddyAvatar.setPanic(true); toast('PÂNICO: ações de risco desligadas'); break;
      case 'panic_cleared': document.body.classList.remove('is-panic'); EddyAvatar.setPanic(false); break;
      case 'notice': case 'voice_error': case 'voice_fallback': toast(d.text || d.message || 'Voz de reserva ativa'); break;
    }
  }

  function setState(s) {
    state = s || 'idle'; document.body.dataset.state = state;
    $('status').textContent = STATE_LABEL[state] || state.toUpperCase();
    EddyAvatar.setState(state); if (state === 'idle' || state === 'thinking') EddyAvatar.setLevel(0);
    $('mic').classList.toggle('live', state === 'listening');
  }

  /* ---------- painéis ---------- */
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function renderHud(h) {
    hudData = h;
    $('chip-llm').innerHTML = `MODELO <b>${esc(h.llm.where)} · ${esc(h.llm.model)}</b>`;
    $('chip-llm').className = 'chip' + (h.llm.fallback ? ' warn' : '');
    $('chip-voice').innerHTML = `VOZ <b>${esc(h.voice.tts)}</b>`;
    $('chip-voice').className = 'chip' + (h.voice.tts === 'PRIVADO' ? ' ok' : (h.voice.tts === 'SEM VOZ' || h.voice.tts === 'OFF' ? ' warn' : ''));
    $('chip-mode').innerHTML = `MODO <b>${esc(h.panic ? 'PÂNICO' : h.mode)}</b>`;
    $('chip-mode').className = 'chip' + (h.panic ? ' alert' : (h.mode !== 'NORMAL' ? ' warn' : ''));
    $('private').classList.toggle('on', h.voice.tts === 'PRIVADO');
    document.body.classList.toggle('is-panic', !!h.panic); EddyAvatar.setPanic(!!h.panic);
    $('sub').textContent = h.user ? 'ONLINE · ' + h.user.toUpperCase() : 'SISTEMA ONLINE';

    renderBriefing(h.briefing || {});
    const sy = (h.briefing && h.briefing.system) || {}, up = h.uptime;
    const hh = String(Math.floor(up / 3600)).padStart(2, '0'), mm = String(Math.floor(up % 3600 / 60)).padStart(2, '0');
    const rows = [['MODELO', h.llm.profile], ['VOZ', h.voice.tts], ['STT', h.voice.stt], ['NOTAS', h.notes],
      ['CPU / RAM', sy.cpu == null ? '—' : `${sy.cpu}% / ${sy.ram}%`]];
    if (sy.battery != null) rows.push(['BATERIA', sy.battery + '%' + (sy.plugged ? ' ⚡' : '')]);
    rows.push(['ATIVO', `${hh}:${mm}`]);
    $('sys').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');

    $('skills').innerHTML = h.skills.map((s) => `<button title="${esc(s.description)}" data-s="${esc(s.name)}">${esc(s.name)}</button>`).join('');
    renderActions(h.actions);
    if (!['listening', 'speaking', 'thinking'].includes(state)) setState(h.state);
  }

  function renderBriefing(b) {
    $('hi').textContent = b.greeting ? `${b.greeting}${b.name ? ', ' + b.name : ''}` : '—';
    $('dt').textContent = b.date || '';
    const w = b.weather, wx = $('wx');
    if (w) {
      wx.className = 'wx' + (w.rain >= 40 ? ' rain' : '');
      wx.innerHTML = `<div class="t">${w.temp}°</div><div class="d">${esc(w.desc)}${w.place ? ' · ' + esc(w.place) : ''}</div>` +
        `<div class="r">mín <b>${w.min}°</b> · máx <b>${w.max}°</b> · chuva <b class="rn">${w.rain}%</b></div>`;
    } else { wx.className = 'wx na'; wx.textContent = 'Sem dados do tempo (offline ou desligado).'; }
    const plan = b.plan || [];
    $('plan').innerHTML = plan.length ? plan.map((p) => `<li>${esc(p)}</li>`).join('')
      : '<li style="grid-template-columns:1fr;--n:none"><span class="empty">Sem prioridades. Diz «plano de hoje».</span></li>';
    const rem = b.reminders || [];
    $('reminders').innerHTML = rem.length ? rem.map((r) => `<div><b>${esc(r.time)}</b>${esc(r.text)}</div>`).join('') : '<span class="empty">Nada marcado.</span>';
    const news = b.news || [];
    $('news-box').hidden = !news.length; $('news').innerHTML = news.map((n) => `<li>${esc(n)}</li>`).join('');
    const jobs = b.jobs || [];
    $('jobs-box').hidden = !jobs.length; $('jobs').innerHTML = jobs.map((j) => `<div><b>${esc(j.time)}</b>${esc(j.name)}</div>`).join('');
  }

  function renderActions(hist) {
    const rows = [...liveActions.filter((a) => a.pending),
      ...[...(hist || [])].reverse().map((a) => ({ summary: a.action, level: a.level, ok: a.ok !== false && !['negada', 'nao_confirmada', 'cancelada', 'args_invalidos', 'limite_ritmo'].includes(a.outcome), t: (a.ts || '').slice(11, 16) }))].slice(0, 8);
    $('actions').innerHTML = rows.length ? rows.map((a) =>
      `<li class="l${a.level || 1} ${a.pending ? 'pending' : ''} ${a.ok === false ? 'fail' : ''}"><i></i>${esc(a.summary)}<span>${esc(a.t || '')}</span></li>`).join('')
      : '<li><i></i><span>nada ainda</span><span></span></li>';
  }
  function pushAction(a) { liveActions.unshift(a); liveActions.length = Math.min(liveActions.length, 6); renderActions(hudData && hudData.actions); }
  function settleAction(d) {
    const i = liveActions.findIndex((a) => a.pending && a.summary === d.summary);
    if (i >= 0) liveActions.splice(i, 1);
    const hist = (hudData && hudData.actions) || [];
    hist.push({ action: d.summary, level: d.level, ok: d.ok, ts: new Date().toISOString().replace('T', ' ') });
    if (hudData) hudData.actions = hist.slice(-8);
    renderActions(hist);
  }

  /* ---------- confirmação ---------- */
  function showConfirm(d) {
    confirmId = d.id; const c = $('confirm');
    c.className = 'confirm' + (d.level < 3 ? ' l2' : ''); c.hidden = false;
    $('c-level').textContent = 'NÍVEL ' + d.level + ' · CONFIRMAÇÃO'; $('c-sum').textContent = d.summary; $('c-code').textContent = d.code;
    let left = d.timeout_s || 30; $('c-count').textContent = left; clearInterval(confirmTimer);
    confirmTimer = setInterval(() => { left -= 1; $('c-count').textContent = Math.max(left, 0); if (left <= 0) hideConfirm(); }, 1000);
  }
  function hideConfirm() { clearInterval(confirmTimer); $('confirm').hidden = true; confirmId = null; }
  function answer(ok) { if (confirmId) { send({ type: 'confirm', id: confirmId, accept: ok }); hideConfirm(); } }
  $('c-yes').onclick = () => answer(true); $('c-no').onclick = () => answer(false);

  /* ---------- interação ---------- */
  function toast(t) { const e = $('toast'); e.textContent = t; e.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (e.hidden = true), 4500); }
  $('cmd').addEventListener('submit', (e) => { e.preventDefault(); const v = $('cmd-in').value.trim(); if (v) { send({ type: 'text', text: v }); $('cmd-in').value = ''; } });
  $('panic').onclick = () => { send({ type: 'panic' }); };
  $('private').onclick = () => send({ type: 'private', on: !$('private').classList.contains('on') });
  $('skills').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) send({ type: 'skill', name: b.dataset.s }); });
  document.body.addEventListener('click', (e) => { if (document.body.classList.contains('is-panic') && e.target.closest('#chip-mode')) send({ type: 'clear_panic' }); });

  function pttDown() { if (!pttHeld) { pttHeld = true; send({ type: 'ptt_down' }); } }
  function pttUp() { if (pttHeld) { pttHeld = false; send({ type: 'ptt_up' }); } }
  $('mic').addEventListener('pointerdown', (e) => { e.preventDefault(); pttDown(); });
  window.addEventListener('pointerup', pttUp);
  window.addEventListener('keydown', (e) => {
    if (!$('confirm').hidden) { if (e.key === 'Enter') { e.preventDefault(); answer(true); } else if (e.key === 'Escape') answer(false); return; }
    if (e.code === 'Space' && !e.repeat && document.activeElement !== $('cmd-in')) { e.preventDefault(); pttDown(); }
    if (e.key === 'Escape' && e.ctrlKey) send({ type: 'panic' });
  });
  window.addEventListener('keyup', (e) => { if (e.code === 'Space') pttUp(); });
  window.addEventListener('blur', pttUp);

  setInterval(() => send({ type: 'hello' }), 60000);   // refresca o briefing (tempo, lembretes)
  setState('idle'); connect();
})();
