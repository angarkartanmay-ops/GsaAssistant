// N.O.V.A. HUD: chat, live core, systems, tasks, alerts. On a phone (via Tailscale) the mic
// records on the phone and photos/files can be attached to whatever you post.
(() => {
  const $ = (id) => document.getElementById(id);
  const log = $("log"), input = $("input"), coreState = $("coreState");
  let ws, streamEl = null, state = "offline", level = 0, targetLevel = 0, reconnectDelay = 1000;
  let remote = !["localhost", "127.0.0.1"].includes(location.hostname);
  let pendingFiles = [];   // inbox names to attach to the next message
  document.body.classList.toggle("remote", remote);

  // Everything rendered with innerHTML goes through esc() first, quotes included, so mail,
  // chat and model text can never inject markup or break out of an attribute.
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmt(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  }
  function add(kind, text) {
    const el = document.createElement("div");
    el.className = "msg " + kind;
    if (kind === "bot") el.innerHTML = `<span class="who">NOVA</span><span class="body">${fmt(text)}</span>`;
    else el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }
  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
  function say(text) {
    const names = pendingFiles.map((f) => f.name).filter(Boolean);
    if (!text.trim() && !names.length) return;
    add("user", text + (names.length ? `\n📎 ${pendingFiles.map((f) => f.label).join(", ")}` : ""));
    send({ type: "chat", text, attachments: names });
    clearFiles();
    streamEl = null;
  }
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
    return r;
  }

  // ---------- attachments ----------
  function renderChips() {
    const box = $("chips");
    box.innerHTML = "";
    box.hidden = !pendingFiles.length;
    pendingFiles.forEach((f, i) => {
      const chip = document.createElement("div");
      chip.className = "file-chip" + (f.name ? "" : " busy");
      chip.innerHTML = `<span>${esc(f.label)}${f.name ? "" : " (uploading)"}</span><button type="button" aria-label="Remove">×</button>`;
      chip.querySelector("button").onclick = () => { pendingFiles.splice(i, 1); renderChips(); };
      box.appendChild(chip);
    });
  }
  function clearFiles() { pendingFiles = []; renderChips(); }
  $("attachBtn").addEventListener("click", () => $("fileInput").click());
  $("fileInput").addEventListener("change", async (e) => {
    for (const file of e.target.files) {
      const entry = { label: file.name, name: null };
      pendingFiles.push(entry); renderChips();
      const fd = new FormData(); fd.append("file", file, file.name);
      try {
        const r = await api("/api/upload", { method: "POST", body: fd });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || "upload failed");
        entry.name = j.name;
      } catch (err) {
        pendingFiles.splice(pendingFiles.indexOf(entry), 1);
        add("tool", `upload failed: ${err.message}`);
      }
      renderChips();
    }
    e.target.value = "";
  });

  // ---------- microphone ----------
  let recorder = null, chunks = [];
  function pickMime() {
    for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
    }
    return "";
  }
  async function toggleRecording() {
    const btn = $("micBtn");
    if (recorder && recorder.state === "recording") { recorder.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      add("tool", "this browser can't record audio (needs the https Tailscale address)"); return;
    }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { add("tool", "microphone permission denied"); return; }
    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      btn.classList.remove("live"); btn.classList.add("busy"); setState("thinking");
      const type = recorder.mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      const fd = new FormData();
      fd.append("audio", new Blob(chunks, { type }), `voice.${ext}`);
      fd.append("attachments", JSON.stringify(pendingFiles.map((f) => f.name).filter(Boolean)));
      clearFiles();
      try {
        const r = await api("/api/voice", { method: "POST", body: fd });
        const j = await r.json();
        if (j.audio_url) new Audio(j.audio_url).play().catch(() => {});
      } catch (err) { if (err.message !== "login") add("tool", "voice upload failed"); }
      btn.classList.remove("busy");
    };
    recorder.start();
    btn.classList.add("live"); setState("listening");
  }
  $("micBtn").addEventListener("click", () => (remote ? toggleRecording() : send({ type: "mic" })));

  // ---------- controls ----------
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); say(input.value); input.value = ""; });
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
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => { reconnectDelay = 1000; setState("idle"); refresh(); };
    ws.onclose = (e) => {
      setState("offline");
      if (e.code === 4401) { location.href = "/login"; return; }
      setTimeout(connect, reconnectDelay); reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    };
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      switch (ev.type) {
        case "hello":
          $("brand").textContent = ev.name;
          $("speakToggle").checked = ev.speak;
          remote = ev.remote; document.body.classList.toggle("remote", remote);
          if (!log.children.length) add("bot", ev.greeting);
          setPending(ev.pending);
          break;
        case "state":
          setState(ev.state);
          if (!remote) $("micBtn").classList.toggle("live", ev.state === "listening");
          break;
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
        case "transcript": add("user", "🎙 " + ev.text); break;
        case "level": targetLevel = ev.value; break;
        case "notify": alertItem(ev.title, ev.body); break;
      }
    };
  }

  // ---------- side panels ----------
  async function refresh() {
    try {
      const s = await (await api("/api/status")).json();
      const ul = $("systems"); ul.innerHTML = "";
      for (const [k, v] of Object.entries(s.connectors)) {
        const li = document.createElement("li");
        li.className = v.ok ? "ok" : "bad";
        li.innerHTML = `<span><span class="dot"></span>${esc(k)}</span><span class="detail" title="${esc(String(v.detail || ""))}">${esc(String(v.detail || ""))}</span>`;
        ul.appendChild(li);
      }
      const wa = s.connectors.whatsapp;
      if (wa && wa.detail === "scan QR") {
        const q = await (await api("/api/whatsapp/qr")).json();
        if (q.dataUrl) { $("qrImg").src = q.dataUrl; $("qrBox").hidden = false; }
      } else $("qrBox").hidden = true;
    } catch { /* server restarting */ }
    refreshTasks();
  }
  async function refreshTasks() {
    try {
      const tasks = await (await api("/api/tasks")).json();
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
  const C = (a) => `rgba(79,209,255,${a})`, W2 = (a) => `rgba(255,181,71,${a})`;
  let t = 0;
  function frame() {
    t += 0.016 * (SPEED[state] || 0.3);
    level += (targetLevel - level) * 0.25;
    if (state !== "speaking" && state !== "listening") targetLevel *= 0.92;
    const W = canvas.width, c = W / 2, R = W * 0.25;
    ctx.clearRect(0, 0, W, W);
    const alpha = state === "offline" ? 0.25 : 1;
    const breath = 0.5 + 0.5 * Math.sin(t * 2.2);

    const g = ctx.createRadialGradient(c, c, R * 0.1, c, c, R * 1.9);
    g.addColorStop(0, C(0.5 * alpha));
    g.addColorStop(0.35, C((0.14 + level * 0.25) * alpha));
    g.addColorStop(1, C(0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(c, c, R * 1.9, 0, Math.PI * 2); ctx.fill();

    ctx.beginPath();
    const pts = 160;
    for (let i = 0; i <= pts; i++) {
      const a = (i / pts) * Math.PI * 2;
      const n = Math.sin(a * 6 + t * 3) * 0.5 + Math.sin(a * 11 - t * 5) * 0.3 + Math.sin(a * 3 + t) * 0.2;
      const r = R * (1.02 + n * (0.03 + level * 0.22));
      const x = c + Math.cos(a) * r, y = c + Math.sin(a) * r;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.strokeStyle = C(0.85 * alpha); ctx.lineWidth = 2 * dpr; ctx.stroke();

    const s = ctx.createRadialGradient(c - R * 0.25, c - R * 0.3, R * 0.05, c, c, R * 0.78);
    s.addColorStop(0, `rgba(230,250,255,${alpha})`);
    s.addColorStop(0.3, C(alpha));
    s.addColorStop(1, `rgba(4,40,60,${alpha})`);
    ctx.fillStyle = s; ctx.beginPath(); ctx.arc(c, c, R * (0.62 + breath * 0.03 + level * 0.08), 0, Math.PI * 2); ctx.fill();

    const rings = [[1.32, 14, 1, C], [1.55, 7, -1.6, W2], [1.75, 40, 0.6, C]];
    for (const [k, segs, dir, col] of rings) {
      const span = (Math.PI * 2) / segs;
      for (let i = 0; i < segs; i++) {
        const a0 = i * span + t * dir, a1 = a0 + span * (k === 1.75 ? 0.25 : 0.62);
        ctx.beginPath(); ctx.arc(c, c, R * k, a0, a1);
        ctx.strokeStyle = col((k === 1.55 ? 0.55 : 0.3) * alpha);
        ctx.lineWidth = (k === 1.55 ? 3 : 1.5) * dpr; ctx.stroke();
      }
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("/sw.js").catch(() => {});
  connect();
})();
