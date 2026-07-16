// EQ Editor: graphical parametric EQ (FabFilter-style drag + audition + save).
// The pure RBJ math (rbjSos / responseDb) is written so `node` can require it
// standalone for the coefficient golden-value check; all DOM/audio code is guarded
// to the browser. Coefficients are ported verbatim from audio.py _biquad_sos (fs=48000).
(function () {
  "use strict";
  const FS = 48000;

  // ---- pure math (node-requirable) ----
  function rbjSos(f, fs) {
    fs = fs || FS;
    const type = String(f.type).toUpperCase();
    const A = Math.pow(10, f.gain / 40);
    const w0 = 2 * Math.PI * f.fc / fs;
    const cw = Math.cos(w0), sw = Math.sin(w0);
    let b0, b1, b2, a0, a1, a2;
    if (type === "PK") {
      const alpha = sw / (2 * f.q);
      b0 = 1 + alpha * A; b1 = -2 * cw; b2 = 1 - alpha * A;
      a0 = 1 + alpha / A; a1 = -2 * cw; a2 = 1 - alpha / A;
    } else {
      const S = f.q;
      const alpha = sw / 2 * Math.sqrt((A + 1 / A) * (1 / S - 1) + 2);
      const raa = 2 * Math.sqrt(A) * alpha;
      if (type === "LS") {
        b0 = A * ((A + 1) - (A - 1) * cw + raa);
        b1 = 2 * A * ((A - 1) - (A + 1) * cw);
        b2 = A * ((A + 1) - (A - 1) * cw - raa);
        a0 = (A + 1) + (A - 1) * cw + raa;
        a1 = -2 * ((A - 1) + (A + 1) * cw);
        a2 = (A + 1) + (A - 1) * cw - raa;
      } else { // HS
        b0 = A * ((A + 1) + (A - 1) * cw + raa);
        b1 = -2 * A * ((A - 1) + (A + 1) * cw);
        b2 = A * ((A + 1) + (A - 1) * cw - raa);
        a0 = (A + 1) - (A - 1) * cw + raa;
        a1 = 2 * ((A - 1) - (A + 1) * cw);
        a2 = (A + 1) - (A - 1) * cw - raa;
      }
    }
    return [b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0];
  }

  function biquadDb(sos, w) {
    const b0 = sos[0], b1 = sos[1], b2 = sos[2], a1 = sos[3], a2 = sos[4];
    const cw = Math.cos(w), sw = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w);
    const nre = b0 + b1 * cw + b2 * c2, nim = -(b1 * sw + b2 * s2);
    const dre = 1 + a1 * cw + a2 * c2, dim = -(a1 * sw + a2 * s2);
    return 10 * Math.log10((nre * nre + nim * nim) / (dre * dre + dim * dim));
  }

  // Composite response in dB (cascaded |H| summed) including preamp.
  function responseDb(freqs, filters, preamp, fs) {
    fs = fs || FS;
    const soss = filters.map(f => rbjSos(f, fs));
    return freqs.map(fr => {
      const w = 2 * Math.PI * fr / fs;
      let db = preamp || 0;
      for (let i = 0; i < soss.length; i++) db += biquadDb(soss[i], w);
      return db;
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { rbjSos, responseDb, biquadDb };
  }
  if (typeof document === "undefined") return; // node stops here

  // ================= browser UI =================
  const g = (id) => document.getElementById(id);
  const COLORS = ["#2b6cff", "#35c07a", "#e0c020", "#e0603a", "#9a5ad0"];
  const FMIN = 20, FMAX = 20000, DBMAX = 18;
  const LMIN = Math.log10(FMIN), LMAX = Math.log10(FMAX);
  const TICKS = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
  const TICKLBL = ["20", "50", "100", "200", "500", "1k", "2k", "5k", "10k", "20k"];
  const DBLINES = [-18, -12, -6, 0, 6, 12, 18];

  const state = { name: "", preamp: 0, filters: [] };
  let selected = -1, dragging = false;

  const canvas = g("eq-canvas");
  const ctx = canvas.getContext("2d");
  const padL = 44, padR = 14, padT = 14, padB = 26;
  const plotW = canvas.width - padL - padR;
  const plotH = canvas.height - padT - padB;

  const fx = (f) => padL + (Math.log10(f) - LMIN) / (LMAX - LMIN) * plotW;
  const xf = (x) => Math.pow(10, LMIN + (x - padL) / plotW * (LMAX - LMIN));
  const gy = (db) => padT + (DBMAX - db) / (2 * DBMAX) * plotH;
  const yg = (y) => DBMAX - (y - padT) / plotH * (2 * DBMAX);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#fbfbfd"; ctx.fillRect(padL, padT, plotW, plotH);
    ctx.font = "10px sans-serif"; ctx.textBaseline = "middle";

    ctx.strokeStyle = "#e4e6ec"; ctx.fillStyle = "#9096a4";
    for (let i = 0; i < TICKS.length; i++) {
      const x = fx(TICKS[i]);
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke();
      ctx.textAlign = "center"; ctx.fillText(TICKLBL[i], x, padT + plotH + 12);
    }
    for (const db of DBLINES) {
      const y = gy(db);
      ctx.strokeStyle = db === 0 ? "#c2c6d0" : "#e4e6ec";
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
      ctx.textAlign = "right"; ctx.fillStyle = "#9096a4";
      ctx.fillText((db > 0 ? "+" : "") + db, padL - 6, y);
    }

    // composite curve
    const xs = [], freqs = [];
    for (let x = padL; x <= padL + plotW; x++) { xs.push(x); freqs.push(xf(x)); }
    const dbs = responseDb(freqs, state.filters, state.preamp);
    ctx.strokeStyle = "#2b6cff"; ctx.lineWidth = 2; ctx.beginPath();
    for (let i = 0; i < xs.length; i++) {
      const y = clamp(gy(dbs[i]), padT, padT + plotH);
      if (i === 0) ctx.moveTo(xs[i], y); else ctx.lineTo(xs[i], y);
    }
    ctx.stroke(); ctx.lineWidth = 1;

    // filter dots
    state.filters.forEach((f, i) => {
      const x = fx(clamp(f.fc, FMIN, FMAX)), y = clamp(gy(f.gain), padT, padT + plotH);
      ctx.beginPath(); ctx.arc(x, y, i === selected ? 8 : 6, 0, 2 * Math.PI);
      ctx.fillStyle = COLORS[i % COLORS.length]; ctx.fill();
      ctx.strokeStyle = i === selected ? "#111" : "#fff"; ctx.lineWidth = 2; ctx.stroke();
      ctx.lineWidth = 1;
    });
  }

  function nearestDot(x, y) {
    let best = -1, bd = 15 * 15;
    state.filters.forEach((f, i) => {
      const dx = x - fx(clamp(f.fc, FMIN, FMAX)), dy = y - gy(f.gain);
      const d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  }
  function canvasXY(e) {
    const r = canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * canvas.width / r.width,
            (e.clientY - r.top) * canvas.height / r.height];
  }

  canvas.addEventListener("pointerdown", (e) => {
    const [x, y] = canvasXY(e);
    const hit = nearestDot(x, y);
    if (hit >= 0) { selected = hit; dragging = true; canvas.setPointerCapture(e.pointerId); syncUI(); }
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!dragging || selected < 0) return;
    const [x, y] = canvasXY(e);
    const f = state.filters[selected];
    f.fc = clamp(xf(clamp(x, padL, padL + plotW)), FMIN, FMAX);
    f.gain = clamp(yg(clamp(y, padT, padT + plotH)), -DBMAX, DBMAX);
    syncUI(); auditionRefresh();
  });
  const endDrag = () => { dragging = false; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("dblclick", (e) => {
    const [x, y] = canvasXY(e);
    if (nearestDot(x, y) >= 0) return;
    state.filters.push({
      type: "PK",
      fc: clamp(xf(clamp(x, padL, padL + plotW)), FMIN, FMAX),
      gain: clamp(yg(clamp(y, padT, padT + plotH)), -DBMAX, DBMAX),
      q: 1.0,
    });
    selected = state.filters.length - 1; syncUI(); auditionRefresh();
  });
  canvas.addEventListener("wheel", (e) => {
    if (selected < 0) return;
    e.preventDefault();
    const f = state.filters[selected];
    f.q = clamp(f.q * (e.deltaY < 0 ? 1.1 : 1 / 1.1), 0.1, 10);
    syncUI(); auditionRefresh();
  }, { passive: false });
  window.addEventListener("keydown", (e) => {
    if ((e.key === "Delete" || e.key === "Backspace") && selected >= 0
        && !/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) {
      state.filters.splice(selected, 1);
      selected = Math.min(selected, state.filters.length - 1);
      syncUI(); auditionRefresh();
    }
  });
  const dropRow = (i) => {
    state.filters.splice(i, 1);
    if (selected > i) selected -= 1;
    selected = Math.min(selected, state.filters.length - 1);
    syncUI(); auditionRefresh();
  };

  // ---- table ----
  function renderTable() {
    const body = g("eq-rows"); body.innerHTML = "";
    state.filters.forEach((f, i) => {
      const tr = document.createElement("tr");
      if (i === selected) tr.className = "eq-sel";
      const dot = `<span class="dot" style="background:${COLORS[i % COLORS.length]}"></span>`;
      tr.innerHTML =
        `<td>${dot}${i + 1}</td>` +
        `<td><select data-k="type">${["PK", "LS", "HS"].map(t =>
          `<option${t === f.type ? " selected" : ""}>${t}</option>`).join("")}</select></td>` +
        `<td><input data-k="fc" type="number" step="1" value="${round(f.fc, 1)}"></td>` +
        `<td><input data-k="gain" type="number" step="0.5" value="${round(f.gain, 2)}"></td>` +
        `<td><input data-k="q" type="number" step="0.1" value="${round(f.q, 3)}"></td>` +
        `<td><button class="ghost" data-del="1">×</button></td>`;
      tr.addEventListener("pointerdown", () => { if (selected !== i) { selected = i; syncUI(); } });
      tr.querySelectorAll("[data-k]").forEach(el => {
        el.addEventListener("input", () => {
          const k = el.dataset.k;
          if (k === "type") f.type = el.value;
          else {
            const v = parseFloat(el.value);
            if (isFinite(v)) {
              // clamp 同拖曳/滾輪, 保持預覽與伺服器 parse_eqapo 一致
              if (k === "fc") f.fc = clamp(v, FMIN, FMAX);
              else if (k === "gain") f.gain = clamp(v, -DBMAX, DBMAX);
              else f.q = clamp(v, 0.1, 10);
            }
          }
          draw(); auditionRefresh();
        });
      });
      tr.querySelector("[data-del]").addEventListener("click", () => dropRow(i));
      body.appendChild(tr);
    });
  }
  const round = (n, d) => Math.round(n * Math.pow(10, d)) / Math.pow(10, d);

  function syncUI() { draw(); renderTable(); g("eq-preamp").value = round(state.preamp, 2); }

  // ---- preamp ----
  g("eq-preamp").addEventListener("input", () => {
    const v = parseFloat(g("eq-preamp").value);
    if (isFinite(v)) { state.preamp = v; draw(); auditionRefresh(); }
  });
  g("eq-auto").addEventListener("click", () => {
    const freqs = []; for (let x = padL; x <= padL + plotW; x++) freqs.push(xf(x));
    const dry = responseDb(freqs, state.filters, 0);
    state.preamp = round(-Math.max(0, Math.max.apply(null, dry.length ? dry : [0])), 2);
    syncUI(); auditionRefresh();
  });
  g("eq-add").addEventListener("click", () => {
    state.filters.push({ type: "PK", fc: 1000, gain: 0, q: 1.0 });
    selected = state.filters.length - 1; syncUI(); auditionRefresh();
  });

  // ---- save / load ----
  function serialize() {
    const T = { PK: "PK", LS: "LSC", HS: "HSC" };
    const lines = ["Preamp: " + round(state.preamp, 2) + " dB"];
    state.filters.forEach((f, i) => {
      lines.push(`Filter ${i + 1}: ON ${T[f.type] || "PK"} Fc ${round(f.fc, 1)} Hz `
        + `Gain ${round(f.gain, 2)} dB Q ${round(f.q, 3)}`);
    });
    return lines.join("\n") + "\n";
  }

  async function refreshEqLists() {
    let eqs = [];
    try { eqs = await (await fetch("/api/eqs")).json(); } catch (e) {}
    const loadSel = g("eq-load-list"), keep = loadSel.value;
    loadSel.innerHTML = eqs.map(n => `<option>${n}</option>`).join("");
    if (eqs.includes(keep)) loadSel.value = keep;
    // keep the ABX/Preference EQ dropdowns in sync so a just-saved file is selectable
    ["abx-a-eq", "abx-b-eq", "pref-a-eq", "pref-b-eq"].forEach(id => {
      const sel = g(id); if (!sel) return;
      const cur = sel.value;
      sel.innerHTML = `<option value="">無 EQ</option>` + eqs.map(n => `<option>${n}</option>`).join("");
      sel.value = cur;
    });
  }

  g("eq-save-btn").addEventListener("click", async () => {
    const name = g("eq-name").value.trim();
    const status = g("eq-save-status");
    if (!/^[A-Za-z0-9_-]+$/.test(name)) {
      status.textContent = "檔名只能用英數字、底線、連字號."; return;
    }
    try {
      const res = await fetch("/api/eq/save", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, text: serialize() }),
      });
      const j = await res.json();
      if (!res.ok) { status.textContent = "存檔失敗: " + (j.error || res.status); return; }
      state.name = j.name; status.textContent = "已存 " + j.name;
      await refreshEqLists();
      g("eq-load-list").value = j.name;
    } catch (e) { status.textContent = "存檔失敗: " + e; }
  });

  g("eq-load-btn").addEventListener("click", async () => {
    const name = g("eq-load-list").value;
    const status = g("eq-save-status");
    if (!name) return;
    try {
      const res = await fetch("/api/eq/load?name=" + encodeURIComponent(name));
      const j = await res.json();
      if (!res.ok) { status.textContent = "載入失敗: " + (j.error || res.status); return; }
      state.preamp = j.preamp || 0;
      state.filters = (j.filters || []).map(f => ({ type: f.type, fc: f.fc, gain: f.gain, q: f.q }));
      selected = state.filters.length ? 0 : -1;
      g("eq-name").value = name.replace(/\.txt$/i, "");
      status.textContent = "已載入 " + name;
      syncUI(); auditionRefresh();
    } catch (e) { status.textContent = "載入失敗: " + e; }
  });

  // ================= audition (Web Audio, IIRFilterNode chain) =================
  let actx = null, master = null, srcNode = null, nodes = [], currentStim = null, playing = false;
  let lastBuild = 0, pendingBuild = null;

  function pinkPulseBuffer() {
    const sr = actx.sampleRate, n = Math.floor(sr * 2.1);
    const buf = actx.createBuffer(1, n, sr), d = buf.getChannelData(0);
    let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
    for (let i = 0; i < n; i++) {
      const w = Math.random() * 2 - 1;
      b0 = 0.99886 * b0 + w * 0.0555179; b1 = 0.99332 * b1 + w * 0.0750759;
      b2 = 0.96900 * b2 + w * 0.1538520; b3 = 0.86650 * b3 + w * 0.3104856;
      b4 = 0.55000 * b4 + w * 0.5329522; b5 = -0.7616 * b5 - w * 0.0168980;
      d[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
      b6 = w * 0.115926;
    }
    const P = Math.floor(0.7 * sr), ON = Math.floor(0.2 * sr), RP = Math.max(1, Math.floor(0.01 * sr));
    for (let i = 0; i < n; i++) {
      const ph = i % P;
      let env = 0;
      if (ph < ON) env = ph < RP ? 0.5 * (1 - Math.cos(Math.PI * ph / RP))
        : (ph > ON - RP ? 0.5 * (1 - Math.cos(Math.PI * (ON - ph) / RP)) : 1);
      d[i] *= env;
    }
    return buf;
  }

  const wavCache = {};
  async function loadStim(kind) {
    if (kind === "pink") return pinkPulseBuffer();
    if (wavCache[kind]) return wavCache[kind];
    const ab = await (await fetch("/stimuli/" + encodeURIComponent(kind))).arrayBuffer();
    const dec = await actx.decodeAudioData(ab);
    let mono = dec;
    if (dec.numberOfChannels > 1) {
      mono = actx.createBuffer(1, dec.length, dec.sampleRate);
      mono.copyToChannel(dec.getChannelData(0), 0);
    }
    wavCache[kind] = mono; return mono;
  }

  function teardownNodes() {
    if (srcNode) { try { srcNode.stop(); } catch (e) {} }
    nodes.forEach(nd => { try { nd.disconnect(); } catch (e) {} });
    nodes = []; srcNode = null;
  }
  function buildChain() {
    if (!actx || !currentStim) return;
    teardownNodes();
    const src = actx.createBufferSource();
    src.buffer = currentStim; src.loop = true;
    let node = src; nodes.push(src);
    for (const f of state.filters) {
      const s = rbjSos(f, FS);
      let iir;
      try { iir = actx.createIIRFilter([s[0], s[1], s[2]], [1, s[3], s[4]]); }
      catch (e) { continue; }
      node.connect(iir); node = iir; nodes.push(iir);
    }
    const pre = actx.createGain();
    pre.gain.value = Math.pow(10, state.preamp / 20);
    node.connect(pre).connect(master); nodes.push(pre);
    src.start(); srcNode = src;
  }
  function auditionRefresh() {
    if (!playing) return;
    const now = performance.now();
    if (now - lastBuild >= 150) { lastBuild = now; buildChain(); }
    else {
      clearTimeout(pendingBuild);
      pendingBuild = setTimeout(() => { lastBuild = performance.now(); buildChain(); }, 150 - (now - lastBuild));
    }
  }

  async function startAudition() {
    if (!actx) {
      actx = new (window.AudioContext || window.webkitAudioContext)();
      master = actx.createGain(); master.gain.value = 0.9; master.connect(actx.destination);
    }
    await actx.resume();
    const dev = g("eq-device").value;
    if (dev && actx.setSinkId) { try { await actx.setSinkId(dev); } catch (e) {} }
    currentStim = await loadStim(g("eq-stim").value);
    playing = true; g("eq-stop").disabled = false; buildChain();
  }
  function stopAudition() { playing = false; g("eq-stop").disabled = true; teardownNodes(); }

  g("eq-play").addEventListener("click", startAudition);
  g("eq-stop").addEventListener("click", stopAudition);
  g("eq-stim").addEventListener("change", async () => {
    if (playing) { currentStim = await loadStim(g("eq-stim").value); buildChain(); }
  });

  // ---- init ----
  async function init() {
    const stimSel = g("eq-stim"); stimSel.innerHTML = `<option value="pink">pink pulse</option>`;
    try {
      const wavs = (await (await fetch("/api/stimuli")).json()).filter(s => s.toLowerCase().endsWith(".wav"));
      wavs.forEach(s => { const o = document.createElement("option"); o.value = s; o.textContent = s; stimSel.appendChild(o); });
    } catch (e) {}
    const devSel = g("eq-device"); devSel.innerHTML = `<option value="">Default output</option>`;
    try {
      const outs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "audiooutput");
      outs.forEach(d => { if (d.deviceId && d.deviceId !== "default") { const o = document.createElement("option"); o.value = d.deviceId; o.textContent = d.label || "output"; devSel.appendChild(o); } });
    } catch (e) {}
    await refreshEqLists();
    // seed with one filter so the canvas is not empty
    state.filters.push({ type: "PK", fc: 1000, gain: 0, q: 1.0 });
    selected = 0; syncUI();
  }
  init();
})();
