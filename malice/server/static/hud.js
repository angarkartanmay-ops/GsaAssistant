// M.A.L.I.C.E. HUD: chat, live core, systems, tasks, alerts.
(() => {
  const $ = (id) => document.getElementById(id);
  const log = $("log"), input = $("input"), coreState = $("coreState"), transcript = $("transcript");
  let ws, streamEl = null, state = "offline", level = 0, targetLevel = 0, reconnectDelay = 1000;

  // ---------- chat rendering ----------
  // Everything rendered with innerHTML goes through esc() first, quotes included, so mail,
  // chat and model text can never inject markup or break out of an attribute.
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmt(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:var(--ember)">$1</a>');
  }
  function add(kind, text) {
    const el = document.createElement("div");
    el.className = "msg " + kind;
    if (kind === "bot") el.innerHTML = `<span class="who">MALICE</span><span class="body">${fmt(text)}</span>`;
    else el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
  function say(text) {
    if (!text.trim()) return;
    add("user", text);
    send({ type: "chat", text });
    streamEl = null;
  }

  $("composer").addEventListener("submit", (e) => { e.preventDefault(); say(input.value); input.value = ""; });
  $("micBtn").addEventListener("click", () => send({ type: "mic" }));
  $("speakToggle").addEventListener("change", (e) => send({ type: "speak", on: e.target.checked }));
  $("muteToggle").addEventListener("change", (e) => send({ type: "mute", on: e.target.checked }));
  $("resetBtn").addEventListener("click", () => { log.innerHTML = ""; send({ type: "reset" }); });
  document.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => say(b.dataset.q)));
  document.querySelectorAll("[data-say]").forEach((b) => b.addEventListener("click", () => { $("confirm").hidden = true; say(b.dataset.say); }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") send({ type: "stop" }); });

  function setPending(p) {
    const box = $("confirm");
    if (p && p.preview) { $("confirmPreview").textContent = p.preview; box.hidden = false; }
    else box.hidden = true;
  }
  function alertItem(title, body) {
    const ul = $("alerts");
    if (ul.firstElementChild && ul.firstElementChild.classList.contains("muted")) ul.innerHTML = "";
    const li = document.createElement("li");
    li.innerHTML = `<span class="t">${esc(title)}</span>${esc(body || "")}`;
    ul.prepend(li);
    while (ul.children.length > 8) ul.lastChild.remove();
  }

  // ---------- websocket ----------
  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => { reconnectDelay = 1000; setState("idle"); refresh(); };
    ws.onclose = () => { setState("offline"); setTimeout(connect, reconnectDelay); reconnectDelay = Math.min(reconnectDelay * 2, 10000); };
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      switch (ev.type) {
        case "hello":
          $("brand").textContent = ev.name;
          $("speakToggle").checked = ev.speak;
          if (!log.children.length) add("bot", ev.greeting);
          setPending(ev.pending);
          break;
        case "state": setState(ev.state); if (ev.state === "listening") $("micBtn").classList.add("live"); else $("micBtn").classList.remove("live"); break;
        case "token":
          if (!streamEl) streamEl = add("bot", "");
          streamEl.querySelector(".body").textContent += ev.text;
          log.scrollTop = log.scrollHeight;
          break;
        case "retract":  // the model announced instead of acting; it is retrying with a tool
          if (streamEl) { streamEl.remove(); streamEl = null; }
          break;
        case "tool":
          if (ev.status === "running") { streamEl = null; add("tool", ev.name.replace(/_/g, " ")); }
          break;
        case "confirm": setPending({ preview: ev.preview }); break;
        case "final":
          if (streamEl) streamEl.querySelector(".body").innerHTML = fmt(ev.text);
          else add("bot", ev.text);
          streamEl = null;
          setPending(ev.pending);
          refreshTasks();
          break;
        case "transcript": add("user", ev.text); transcript.textContent = ""; break;
        case "level": targetLevel = ev.value; break;
        case "notify": alertItem(ev.title, ev.body); break;
      }
    };
  }

  // ---------- side panels ----------
  async function refresh() {
    try {
      const s = await (await fetch("/api/status")).json();
      const ul = $("systems"); ul.innerHTML = "";
      for (const [k, v] of Object.entries(s.connectors)) {
        const li = document.createElement("li");
        li.className = v.ok ? "ok" : "bad";
        li.innerHTML = `<span><span class="dot"></span>${esc(k)}</span><span class="detail" title="${esc(String(v.detail || ""))}">${esc(String(v.detail || ""))}</span>`;
        ul.appendChild(li);
      }
      const wa = s.connectors.whatsapp;
      if (wa && wa.detail === "scan QR") {
        const q = await (await fetch("/api/whatsapp/qr")).json();
        if (q.dataUrl) { $("qrImg").src = q.dataUrl; $("qrBox").hidden = false; }
      } else $("qrBox").hidden = true;
    } catch { /* server restarting */ }
    refreshTasks();
  }
  async function refreshTasks() {
    try {
      const tasks = await (await fetch("/api/tasks")).json();
      const ul = $("tasks"); ul.innerHTML = "";
      if (!tasks.length) { ul.innerHTML = '<li class="muted">none yet</li>'; return; }
      for (const t of tasks.slice(0, 8)) {
        const li = document.createElement("li");
        li.innerHTML = `${esc(t.title)}${t.due ? `<span class="due">due ${esc(t.due)}</span>` : ""}`;
        ul.appendChild(li);
      }
    } catch { /* ignore */ }
  }
  setInterval(refresh, 15000);

  // ---------- the core ----------
  const canvas = $("core"), ctx = canvas.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  function fit() { const r = canvas.getBoundingClientRect(); canvas.width = r.width * dpr; canvas.height = r.width * dpr; }
  window.addEventListener("resize", fit); fit();

  function setState(s) { state = s; coreState.textContent = s; }

  const SPEED = { offline: 0.1, idle: 0.35, listening: 1.0, thinking: 2.4, speaking: 0.8 };
  let t = 0;
  function frame() {
    t += 0.016 * (SPEED[state] || 0.3);
    level += (targetLevel - level) * 0.25;
    if (state !== "speaking" && state !== "listening") targetLevel *= 0.92;
    const W = canvas.width, c = W / 2, R = W * 0.25;
    ctx.clearRect(0, 0, W, W);
    const alpha = state === "offline" ? 0.25 : 1;
    const breath = 0.5 + 0.5 * Math.sin(t * 2.2);

    // glow
    const g = ctx.createRadialGradient(c, c, R * 0.1, c, c, R * 1.9);
    g.addColorStop(0, `rgba(255,60,70,${0.55 * alpha})`);
    g.addColorStop(0.35, `rgba(255,42,61,${(0.16 + level * 0.25) * alpha})`);
    g.addColorStop(1, "rgba(255,42,61,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(c, c, R * 1.9, 0, Math.PI * 2); ctx.fill();

    // waveform ring
    ctx.beginPath();
    const pts = 160;
    for (let i = 0; i <= pts; i++) {
      const a = (i / pts) * Math.PI * 2;
      const n = Math.sin(a * 6 + t * 3) * 0.5 + Math.sin(a * 11 - t * 5) * 0.3 + Math.sin(a * 3 + t) * 0.2;
      const r = R * (1.02 + n * (0.03 + level * 0.22));
      const x = c + Math.cos(a) * r, y = c + Math.sin(a) * r;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.strokeStyle = `rgba(255,90,90,${0.85 * alpha})`; ctx.lineWidth = 2 * dpr; ctx.stroke();

    // core sphere
    const s = ctx.createRadialGradient(c - R * 0.25, c - R * 0.3, R * 0.05, c, c, R * 0.78);
    s.addColorStop(0, `rgba(255,220,210,${alpha})`);
    s.addColorStop(0.25, `rgba(255,70,70,${alpha})`);
    s.addColorStop(1, `rgba(90,0,12,${alpha})`);
    ctx.fillStyle = s; ctx.beginPath(); ctx.arc(c, c, R * (0.62 + breath * 0.03 + level * 0.08), 0, Math.PI * 2); ctx.fill();

    // segmented rings
    const rings = [[1.32, 14, 1], [1.55, 7, -1.6], [1.75, 40, 0.6]];
    for (const [k, segs, dir] of rings) {
      const span = (Math.PI * 2) / segs;
      for (let i = 0; i < segs; i++) {
        const a0 = i * span + t * dir, a1 = a0 + span * (k === 1.75 ? 0.25 : 0.62);
        ctx.beginPath(); ctx.arc(c, c, R * k, a0, a1);
        ctx.strokeStyle = `rgba(255,42,61,${(k === 1.55 ? 0.55 : 0.3) * alpha})`;
        ctx.lineWidth = (k === 1.55 ? 3 : 1.5) * dpr; ctx.stroke();
      }
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  connect();
})();
