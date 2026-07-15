// Setup, trial flow, manual probe, nav, response circle. Vanilla JS.
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function wavTrim(canvasId, timesId, wrapId) {
  const canvas = $(canvasId);
  const ctx = canvas.getContext("2d");
  const times = $(timesId);
  const wrap = $(wrapId);
  let peaks = [], duration = 0, a = 0, b = 0, active = false, dragging = null;
  let loadSerial = 0;

  function draw() {
    const w = canvas.width, h = canvas.height;
    ctx.fillStyle = "#0f1116";
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = "#4a5570";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < peaks.length; i++) {
      const x = (i + 0.5) * w / peaks.length;
      const half = peaks[i] * (h / 2 - 3);
      ctx.moveTo(x, h / 2 - half);
      ctx.lineTo(x, h / 2 + half);
    }
    ctx.stroke();

    if (!active || duration <= 0) return;
    const ax = a / duration * w;
    const bx = b / duration * w;
    ctx.fillStyle = "rgba(43,108,255,.22)";
    ctx.fillRect(ax, 0, bx - ax, h);
    ctx.fillStyle = "#2b6cff";
    ctx.fillRect(ax - 2, 0, 4, h);
    ctx.fillRect(bx - 2, 0, 4, h);
  }

  function update() {
    times.textContent = `A ${a.toFixed(2)}s · B ${b.toFixed(2)}s / dur ${duration.toFixed(2)}s`;
    draw();
  }

  async function load(name) {
    const serial = ++loadSerial;
    if (!name.toLowerCase().endsWith(".wav")) {
      active = false;
      peaks = [];
      duration = 0;
      a = b = 0;
      wrap.classList.add("hidden");
      return;
    }
    try {
      const response = await fetch(`/api/wavinfo?name=${encodeURIComponent(name)}`);
      const info = await response.json();
      if (!response.ok) throw new Error(info.error || "Unable to load WAV information.");
      if (serial !== loadSerial) return;
      peaks = info.peaks;
      duration = info.duration;
      a = 0;
      b = duration;
      active = true;
      wrap.classList.remove("hidden");
      update();
    } catch (e) {
      if (serial !== loadSerial) return;
      active = false;
      peaks = [];
      duration = 0;
      a = b = 0;
      wrap.classList.add("hidden");
      alert(e.message);
    }
  }

  function pointerTime(ev) {
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
    return x / rect.width * duration;
  }

  canvas.addEventListener("pointerdown", (ev) => {
    if (!active || duration <= 0) return;
    const t = pointerTime(ev);
    dragging = Math.abs(t - a) <= Math.abs(t - b) ? "a" : "b";
    canvas.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });

  canvas.addEventListener("pointermove", (ev) => {
    if (!dragging || !active) return;
    const t = pointerTime(ev);
    const gap = Math.min(0.05, duration);
    if (dragging === "a") a = Math.max(0, Math.min(t, b - gap));
    else b = Math.min(duration, Math.max(t, a + gap));
    update();
  });

  function endDrag(ev) {
    if (!dragging) return;
    if (canvas.hasPointerCapture(ev.pointerId)) canvas.releasePointerCapture(ev.pointerId);
    dragging = null;
  }
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  return {
    load,
    region() {
      return active ? [a, b] : null;
    },
  };
}

// ---- nav ----
document.querySelectorAll("nav button").forEach(b => b.onclick = () => showView(b.dataset.view));
function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === name));
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.dataset.view === name));
  if (name === "report") loadSessions();
}

// ---- response circle (shared by trial + probe) ----
function makeCircle(onPick) {
  const NS = "http://www.w3.org/2000/svg", R = 150, C = 180;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 360 360");
  svg.setAttribute("width", "360"); svg.setAttribute("height", "360");
  const mk = (t, a, txt) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (txt != null) e.textContent = txt; return e; };
  const xy = (az, r) => [C + r * Math.sin(az * Math.PI / 180), C - r * Math.cos(az * Math.PI / 180)];

  svg.appendChild(mk("circle", { cx: C, cy: C, r: R, fill: "#fff", stroke: "#bbb", "stroke-width": 2 }));

  for (let h = 0; h < 12; h++) {
    const az = h * 30, [tx, ty] = xy(az, R - 22);
    const [tickA, tickB] = [xy(az, R), xy(az, R - 8)];
    svg.appendChild(mk("line", { x1: tickA[0], y1: tickA[1], x2: tickB[0], y2: tickB[1], stroke: "#ccc" }));
    svg.appendChild(mk("text", { x: tx, y: ty + 4, "text-anchor": "middle", fill: "#8a93a6",
      "font-size": 12 }, h === 0 ? 12 : h));
  }

  [["正前 (面向)", 0], ["你的右", 90], ["你的正後方", 180], ["你的左", -90]].forEach(([t, az]) => {
    const [x, y] = xy(az, R + 16);
    svg.appendChild(mk("text", { x, y: y + 4, "text-anchor": "middle", "font-weight": 700,
      fill: "#334" }, t));
  });

  const ray = mk("line", { x1: C, y1: C, x2: C, y2: C, stroke: "#2b6cff", "stroke-width": 2, opacity: 0 });
  const target = mk("circle", { cx: C, cy: C, r: 7, fill: "#e04", opacity: 0 });
  const marker = mk("circle", { cx: C, cy: C, r: 8, fill: "#2b6cff", opacity: 0 });
  svg.appendChild(ray); svg.appendChild(target); svg.appendChild(marker);

  svg.appendChild(mk("circle", { cx: C, cy: C, r: 16, fill: "#dde3ee", stroke: "#889" }));
  svg.appendChild(mk("polygon", { points: `${C},${C - 22} ${C - 6},${C - 10} ${C + 6},${C - 10}`, fill: "#556" }));
  svg.style.cursor = "crosshair";

  svg.addEventListener("click", (ev) => {
    const pt = svg.getBoundingClientRect();
    const scale = 360 / pt.width;
    const dx = (ev.clientX - pt.left) * scale - C, dy = (ev.clientY - pt.top) * scale - C;
    if (Math.hypot(dx, dy) < 20) return;
    const az = Math.round(Math.atan2(dx, -dy) * 180 / Math.PI * 10) / 10;
    setMarker(az);
    onPick(az);
  });
  function setMarker(az) {
    const [mx, my] = xy(az, R);
    marker.setAttribute("cx", mx); marker.setAttribute("cy", my); marker.setAttribute("opacity", 1);
    ray.setAttribute("x2", mx); ray.setAttribute("y2", my); ray.setAttribute("opacity", 1);
  }
  function setTarget(az) {
    const [tx, ty] = xy(az, R);
    target.setAttribute("cx", tx); target.setAttribute("cy", ty); target.setAttribute("opacity", 1);
  }
  function reset() {
    marker.setAttribute("opacity", 0); target.setAttribute("opacity", 0); ray.setAttribute("opacity", 0);
  }
  return { svg, setMarker, setTarget, reset };
}

// ---- setup ----
let devices = [];
const setupTrim = wavTrim("setup-wave", "setup-wave-times", "setup-wavtrim");
const probeTrim = wavTrim("probe-wave", "probe-wave-times", "probe-wavtrim");

async function initSetup() {
  devices = await (await fetch("/api/devices")).json();
  const fill = (sel) => {
    sel.innerHTML = "";
    for (const d of devices) {
      const o = document.createElement("option");
      const tag = d.supports_8ch ? "8ch OK" : `${d.channels}ch`;
      o.value = d.index; o.textContent = `${d.name} (${tag})`;
      o.dataset.usable = d.supports_8ch ? "1" : "0"; o.dataset.name = d.name;
      sel.appendChild(o);
    }
  };
  fill($("device")); fill($("probe-device"));
  checkDevice($("device"), $("device-warn"), $("outmode"));
  checkDevice($("probe-device"), $("probe-device-warn"), $("probe-outmode"));

  const stims = await (await fetch("/api/stimuli")).json();
  const fillS = (sel) => {
    sel.innerHTML = "";
    stims.forEach(s => {
      const o = document.createElement("option");
      o.value = s;
      o.textContent = s;
      sel.appendChild(o);
    });
  };
  fillS($("stimulus"));
  fillS($("probe-stimulus"));
  fillS($("abx-a-stim"));
  fillS($("abx-b-stim"));
  $("stimulus").onchange = () => setupTrim.load($("stimulus").value);
  $("probe-stimulus").onchange = () => probeTrim.load($("probe-stimulus").value);
  setupTrim.load($("stimulus").value);
  probeTrim.load($("probe-stimulus").value);

  $("device").onchange = () => checkDevice($("device"), $("device-warn"), $("outmode"));
  $("probe-device").onchange = () => checkDevice($("probe-device"), $("probe-device-warn"), $("probe-outmode"));
  $("outmode").onchange = () => {
    checkDevice($("device"), $("device-warn"), $("outmode"));
    estimateDuration();
  };
  $("probe-outmode").onchange = () =>
    checkDevice($("probe-device"), $("probe-device-warn"), $("probe-outmode"));
  ["step", "reps"].forEach(id => $(id).oninput = estimateDuration);
  estimateDuration();
}

function checkDevice(sel, warnEl, outmodeSel) {
  const usable = sel.selectedOptions[0]?.dataset.usable === "1";
  if (outmodeSel.value === "bed71" && !usable) {
    warnEl.textContent = "This endpoint will not accept an 8-channel stream. Enable 7.1 or a spatial-sound APO (Atmos/Sonic) on it before starting.";
    warnEl.classList.remove("hidden");
    return false;
  }
  warnEl.classList.add("hidden");
  return true;
}

function estimateDuration() {
  const step = +$("step").value;
  const positions = $("outmode").value === "stereo" ? Math.floor(180 / step) + 1 : 360 / step;
  const n = positions * +$("reps").value;
  const secs = Math.round(n * 7);
  $("duration-est").textContent = `${n} trials, ~${Math.floor(secs / 60)}m ${secs % 60}s at ~7s/trial.`;
}

async function apiJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function postJson(url, body) {
  return apiJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function setupIdentity() {
  const participant = $("participant").value.trim();
  if (!participant) {
    alert("Enter participant ID");
    return null;
  }
  const devSel = $("device").selectedOptions[0];
  return {
    participant,
    condition: $("condition").value.trim() || "unlabeled",
    device_index: +devSel.value,
    device_name: devSel.dataset.name,
  };
}

$("start-practice").onclick = () => startSession("practice");
$("start-main").onclick = () => startSession("main");
$("start-cmaa").onclick = startCmaa;
$("start-abx").onclick = startAbx;
$("start-ext").onclick = startExt;
$("start-width").onclick = startWidth;

async function startSession(mode) {
  const devSel = $("device").selectedOptions[0];
  if (!checkDevice($("device"), $("device-warn"), $("outmode"))) return;
  if (!$("participant").value.trim()) { alert("Enter participant ID"); return; }
  const body = {
    participant: $("participant").value.trim(), condition: $("condition").value.trim() || "unlabeled",
    device_index: +devSel.value, device_name: devSel.dataset.name, mode,
    azimuth_step: +$("step").value, reps: +$("reps").value,
    peak_dbfs: +$("peak").value, stimulus: $("stimulus").value,
    stim_region: setupTrim.region(),
    output_mode: $("outmode").value,
  };
  const s = await postJson("/api/session", body);
  runSession({ id: s.session_id, order: s.trial_order, config: s.config, mode, completed: new Set(s.completed) });
}

document.addEventListener("click", async (e) => {
  const rid = e.target.dataset.resume;
  if (!rid) return;
  const s = await apiJson(`/api/session/${rid}/resume`);
  runSession({ id: s.session_id, order: s.trial_order, config: s.config,
    mode: s.session.mode, completed: new Set(s.completed) });
});

// ---- trial flow ----
let sess, circle, paused = false;
function runSession(s) {
  sess = s;
  showView("trial");
  $("mode-badge").textContent = s.mode === "practice" ? "PRACTICE (feedback on)" : "MAIN";
  $("circle-wrap").innerHTML = "";
  circle = makeCircle(onPick);
  $("circle-wrap").appendChild(circle.svg);
  sess.ptr = sess.order.findIndex((_, i) => !s.completed.has(i));
  if (sess.ptr < 0) { finishSession(); return; }
  nextTrial();
}

let response = null, replayed = 0, timerStart = 0;
$("pause").onclick = () => { paused = true; $("paused-overlay").classList.remove("hidden"); };
$("resume-btn").onclick = () => { paused = false; $("paused-overlay").classList.add("hidden"); };

async function nextTrial() {
  while (sess.ptr < sess.order.length && sess.completed.has(sess.ptr)) sess.ptr++;
  if (sess.ptr >= sess.order.length) { finishSession(); return; }
  const i = sess.ptr, az = sess.order[i];
  response = null; replayed = 0;
  circle.reset();
  $("confirm").disabled = true; $("replay").disabled = true;
  $("feedback").classList.add("hidden");
  const done = sess.completed.size, total = sess.order.length;
  $("progress").textContent = `Trial ${done + 1} of ${total}`;
  $("trial-status").textContent = "Playing…";
  await playStimulus(az, i);
  timerStart = performance.now();
  $("replay").disabled = false;
  $("trial-status").textContent = "Click the perceived direction, then Confirm.";
}

async function playStimulus(az, i) {
  const c = sess.config;
  await postJson("/api/play", {
    device_index: c.device_index, target_az: az,
    stimulus: c.stimulus, stim_region: c.stim_region, peak_dbfs: c.peak_dbfs,
    seed: c.seed * 100003 + i, output_mode: c.output_mode || "bed71",
  });
}

function onPick(az) { response = az; $("confirm").disabled = false; }

$("replay").onclick = async () => {
  if (replayed >= 1) return;
  replayed = 1; $("replay").disabled = true;
  $("trial-status").textContent = "Replaying…";
  await playStimulus(sess.order[sess.ptr], sess.ptr);
  timerStart = performance.now();
  $("trial-status").textContent = "Click the perceived direction, then Confirm.";
};

$("confirm").onclick = async () => {
  if (response == null) return;
  const i = sess.ptr, az = sess.order[i];
  const ms = Math.round(performance.now() - timerStart);
  $("confirm").disabled = true; $("replay").disabled = true;
  const t = await postJson("/api/trial", {
    session_id: sess.id, trial_index: i, target_az: az,
    response_az: response, replay_count: replayed, response_ms: ms,
  });
  sess.completed.add(i);

  if (sess.mode === "practice") {
    circle.setTarget(az);
    $("feedback").classList.remove("hidden");
    $("feedback").innerHTML = `Target <b>${az}°</b> · You said <b>${response}°</b> · Error <b>${t.abs_error}°</b>`;
    await sleep(2500);
  }
  while (paused) await sleep(200);
  await sleep(1000);
  sess.ptr++;
  nextTrial();
};

async function finishSession() {
  await fetch(`/api/session/${sess.id}/complete`, { method: "POST" });
  $("trial-status").textContent = "";
  alert(`Session complete: ${sess.completed.size} trials committed.`);
  showView("report");
}

// ---- CMAA separation flow ----
let cm = null;
let cmaaSpec = null;
let cmaaTimerStart = 0;
let cmaaReplayed = 0;
let cmaaBusy = false;

async function startCmaa() {
  const devSel = $("device").selectedOptions[0];
  if (!checkDevice($("device"), $("device-warn"), $("outmode"))) return;
  if (!$("participant").value.trim()) { alert("Enter participant ID"); return; }

  const body = {
    participant: $("participant").value.trim(),
    condition: $("condition").value.trim() || "unlabeled",
    device_index: +devSel.value,
    device_name: devSel.dataset.name,
    output_mode: $("outmode").value,
    peak_dbfs: +$("peak").value,
    ref_az: 0,
  };
  try {
    const data = await postJson("/api/cmaa/session", body);
    cm = {
      id: data.session_id,
      config: data.config,
      deviceIndex: +devSel.value,
      practice: [[40, 1], [40, -1], [25, 1], [25, -1]],
      practiceIdx: 0,
      phase: "practice",
    };
    showView("cmaa");
    $("cmaa-done").classList.add("hidden");
    $("cmaa-question").classList.remove("hidden");
    $("cmaa-left").classList.remove("hidden");
    $("cmaa-right").classList.remove("hidden");
    $("cmaa-replay").classList.remove("hidden");
    $("cmaa-feedback").classList.add("hidden");
    beginCmaaPractice();
  } catch (error) {
    alert(error.message);
  }
}

function setCmaaControls(enabled) {
  $("cmaa-left").disabled = !enabled;
  $("cmaa-right").disabled = !enabled;
  $("cmaa-replay").disabled = !enabled || cmaaReplayed >= 1;
}

async function cmaaPlay(spec, seed) {
  const c = cm.config;
  await postJson("/api/cmaa/play", {
    device_index: cm.deviceIndex,
    ref_az: c.ref_az,
    delta: spec.delta,
    high_side: spec.high_side,
    peak_dbfs: c.peak_dbfs,
    output_mode: c.output_mode,
    seed,
  });
}

async function beginCmaaPractice() {
  if (!cm || cm.phase !== "practice") return;
  if (cm.practiceIdx >= cm.practice.length) {
    cm.phase = "main";
    $("cmaa-badge").textContent = "TEST";
    $("cmaa-feedback").classList.add("hidden");
    await loadCmaaState();
    return;
  }

  const [delta, highSide] = cm.practice[cm.practiceIdx];
  cmaaSpec = { delta, high_side: highSide };
  cmaaReplayed = 0;
  cmaaBusy = true;
  setCmaaControls(false);
  $("cmaa-badge").textContent = "PRACTICE";
  $("cmaa-progress").textContent = `Practice ${cm.practiceIdx + 1} of ${cm.practice.length}`;
  $("cmaa-status").textContent = "Playing…";
  $("cmaa-feedback").classList.add("hidden");

  try {
    await cmaaPlay(cmaaSpec, cm.config.seed * 100003 - (cm.practiceIdx + 1));
    cmaaTimerStart = performance.now();
    cmaaBusy = false;
    setCmaaControls(true);
    $("cmaa-status").textContent = "清亮的聲音在左邊還是右邊?";
  } catch (error) {
    cmaaBusy = false;
    $("cmaa-status").textContent = error.message;
  }
}

async function loadCmaaState() {
  if (!cm) return;
  cmaaBusy = true;
  setCmaaControls(false);
  $("cmaa-status").textContent = "Loading…";
  try {
    const state = await apiJson(`/api/cmaa/state/${cm.id}`);
    if (state.done) {
      showCmaaDone(state.estimate, state.n);
      return;
    }
    await beginCmaaMain(state);
  } catch (error) {
    cmaaBusy = false;
    $("cmaa-status").textContent = error.message;
  }
}

async function beginCmaaMain(spec) {
  cmaaSpec = spec;
  cmaaReplayed = 0;
  cmaaBusy = true;
  setCmaaControls(false);
  $("cmaa-badge").textContent = "TEST";
  $("cmaa-progress").textContent = `Trial ${spec.n + 1} (20-40, adaptive)`;
  $("cmaa-status").textContent = "Playing…";
  $("cmaa-feedback").classList.add("hidden");

  try {
    await cmaaPlay(spec, cm.config.seed * 100003 + spec.trial_index);
    cmaaTimerStart = performance.now();
    cmaaBusy = false;
    setCmaaControls(true);
    $("cmaa-status").textContent = "清亮的聲音在左邊還是右邊?";
  } catch (error) {
    cmaaBusy = false;
    $("cmaa-status").textContent = error.message;
  }
}

async function answerCmaa(responseSide) {
  if (!cm || !cmaaSpec || cmaaBusy) return;
  cmaaBusy = true;
  setCmaaControls(false);
  const responseMs = Math.round(performance.now() - cmaaTimerStart);

  if (cm.phase === "practice") {
    const correct = responseSide === cmaaSpec.high_side;
    const sideText = cmaaSpec.high_side === 1 ? "右邊" : "左邊";
    $("cmaa-feedback").textContent = `${correct ? "正確" : "錯誤"} (清亮聲在${sideText})`;
    $("cmaa-feedback").classList.remove("hidden");
    $("cmaa-status").textContent = "";
    await sleep(1600);
    cm.practiceIdx++;
    cmaaBusy = false;
    beginCmaaPractice();
    return;
  }

  $("cmaa-status").textContent = "Saving…";
  try {
    const result = await postJson("/api/cmaa/trial", {
      session_id: cm.id,
      trial_index: cmaaSpec.trial_index,
      delta: cmaaSpec.delta,
      high_side: cmaaSpec.high_side,
      response_side: responseSide,
      response_ms: responseMs,
    });
    if (result.done) {
      showCmaaDone(result.estimate, result.n);
      return;
    }
    cmaaBusy = false;
    await beginCmaaMain(result);
  } catch (error) {
    cmaaBusy = false;
    $("cmaa-status").textContent = error.message;
  }
}

$("cmaa-left").onclick = () => answerCmaa(-1);
$("cmaa-right").onclick = () => answerCmaa(1);

$("cmaa-replay").onclick = async () => {
  if (!cm || !cmaaSpec || cmaaBusy || cmaaReplayed >= 1) return;
  cmaaBusy = true;
  cmaaReplayed = 1;
  setCmaaControls(false);
  $("cmaa-status").textContent = "Replaying…";
  const seed = cm.phase === "practice"
    ? cm.config.seed * 100003 - (cm.practiceIdx + 1)
    : cm.config.seed * 100003 + cmaaSpec.trial_index;
  try {
    await cmaaPlay(cmaaSpec, seed);
    cmaaTimerStart = performance.now();
    cmaaBusy = false;
    $("cmaa-left").disabled = false;
    $("cmaa-right").disabled = false;
    $("cmaa-replay").disabled = true;
    $("cmaa-status").textContent = "清亮的聲音在左邊還是右邊?";
  } catch (error) {
    cmaaBusy = false;
    $("cmaa-status").textContent = error.message;
  }
};

function showCmaaDone(estimate, n) {
  cmaaBusy = false;
  setCmaaControls(false);
  $("cmaa-progress").textContent = `${n} trials complete`;
  $("cmaa-badge").textContent = "DONE";
  $("cmaa-status").textContent = "";
  $("cmaa-feedback").classList.add("hidden");
  $("cmaa-question").classList.add("hidden");
  $("cmaa-left").classList.add("hidden");
  $("cmaa-right").classList.add("hidden");
  $("cmaa-replay").classList.add("hidden");
  $("cmaa-result").innerHTML = `<span class="big-num">${estimate.threshold.toFixed(1)}°</span>
    separation threshold · CI ${estimate.ci_lo.toFixed(1)}°–${estimate.ci_hi.toFixed(1)}° · n=${n}`;
  $("cmaa-done").classList.remove("hidden");
}

$("cmaa-to-report").onclick = () => {
  showView("report");
  loadSessions();
};

// ---- ABX flow ----
let abxSession = null;
let abxState = null;
let abxPlayed = { a: false, b: false, x: false };
let abxTimerStart = 0;
let abxBusy = false;

function setAbxControls() {
  const active = Boolean(abxSession && abxState && !abxState.done);
  $("abx-play-a").disabled = !active || abxBusy;
  $("abx-play-b").disabled = !active || abxBusy;
  $("abx-play-x").disabled = !active || abxBusy;
  const canAnswer = active && !abxBusy &&
    abxPlayed.a && abxPlayed.b && abxPlayed.x;
  $("abx-ans-a").disabled = !canAnswer;
  $("abx-ans-b").disabled = !canAnswer;
}

async function startAbx() {
  const identity = setupIdentity();
  if (!identity) return;
  const spec = (prefix) => ({
    stimulus: $(`abx-${prefix}-stim`).value,
    output_mode: $(`abx-${prefix}-mode`).value,
    az: +$(`abx-${prefix}-az`).value,
    peak_dbfs: +$("peak").value,
    region: null,
  });
  try {
    const data = await postJson("/api/abx/session", {
      ...identity,
      spec_a: spec("a"),
      spec_b: spec("b"),
      n_trials: +$("abx-n").value,
    });
    abxSession = {
      id: data.session_id,
      config: data.config,
      deviceIndex: identity.device_index,
    };
    showView("abx");
    $("abx-done").classList.add("hidden");
    $("abx-status").textContent = "Loading…";
    await loadAbxState();
  } catch (error) {
    alert(error.message);
  }
}

async function loadAbxState() {
  if (!abxSession) return;
  abxBusy = true;
  setAbxControls();
  try {
    const state = await apiJson(`/api/abx/state/${abxSession.id}`);
    beginAbxState(state);
  } catch (error) {
    abxBusy = false;
    $("abx-status").textContent = error.message;
    setAbxControls();
  }
}

function beginAbxState(state) {
  abxState = state;
  if (state.done) {
    showAbxDone(state);
    return;
  }
  abxPlayed = { a: false, b: false, x: false };
  abxBusy = false;
  $("abx-progress").textContent = `Trial ${state.trial_index + 1} of ${state.n_trials}`;
  $("abx-status").textContent = "請先播放 A、B、X.";
  setAbxControls();
}

async function playAbx(which) {
  if (!abxSession || !abxState || abxState.done || abxBusy) return;
  abxBusy = true;
  setAbxControls();
  $("abx-status").textContent = "Playing…";
  try {
    await postJson("/api/abx/play", {
      session_id: abxSession.id,
      trial_index: abxState.trial_index,
      which,
      device_index: abxSession.deviceIndex,
    });
    abxPlayed[which] = true;
    if (which === "x") abxTimerStart = performance.now();
    abxBusy = false;
    $("abx-status").textContent = abxPlayed.a && abxPlayed.b && abxPlayed.x
      ? "判斷 X 是 A 還是 B."
      : "可繼續播放 A、B、X.";
    setAbxControls();
  } catch (error) {
    abxBusy = false;
    $("abx-status").textContent = error.message;
    setAbxControls();
  }
}

$("abx-play-a").onclick = () => playAbx("a");
$("abx-play-b").onclick = () => playAbx("b");
$("abx-play-x").onclick = () => playAbx("x");

async function answerAbx(responseIsA) {
  if (!abxSession || !abxState || abxState.done || abxBusy ||
      !abxPlayed.a || !abxPlayed.b || !abxPlayed.x) return;
  abxBusy = true;
  setAbxControls();
  $("abx-status").textContent = "Saving…";
  try {
    const result = await postJson("/api/abx/trial", {
      session_id: abxSession.id,
      trial_index: abxState.trial_index,
      response_is_a: responseIsA,
      response_ms: Math.round(performance.now() - abxTimerStart),
    });
    beginAbxState(result);
  } catch (error) {
    abxBusy = false;
    $("abx-status").textContent = error.message;
    setAbxControls();
  }
}

$("abx-ans-a").onclick = () => answerAbx(1);
$("abx-ans-b").onclick = () => answerAbx(0);

function showAbxDone(result) {
  abxState = result;
  abxBusy = false;
  setAbxControls();
  $("abx-progress").textContent = `${result.n} trials complete`;
  $("abx-status").textContent = "";
  const verdict = result.p_value < 0.05
    ? "可辨識 (統計顯著)"
    : result.p_value < 0.2
      ? "可能可辨識 (未達顯著)"
      : "無法辨識";
  $("abx-result").textContent =
    `${result.k}/${result.n} 正確 · p=${result.p_value.toFixed(4)} · ${verdict}`;
  $("abx-done").classList.remove("hidden");
}

$("abx-to-report").onclick = () => {
  showView("report");
  loadSessions();
};

// ---- externalization flow ----
let extSession = null;
let extState = null;
let extTimerStart = 0;
let extReplayed = 0;
let extBusy = false;

function setExtControls(enabled) {
  for (let rating = 1; rating <= 5; rating++) {
    $(`ext-r${rating}`).disabled = !enabled;
  }
  $("ext-replay").disabled = !enabled || extReplayed >= 1;
}

async function startExt() {
  const identity = setupIdentity();
  if (!identity) return;
  try {
    const data = await postJson("/api/ext/session", {
      ...identity,
      output_mode: $("outmode").value,
      stimulus: $("stimulus").value,
      peak_dbfs: +$("peak").value,
      azimuth_step: +$("step").value,
      stim_region: setupTrim.region(),
      n_trials: +$("ext-n").value,
    });
    extSession = {
      id: data.session_id,
      config: data.config,
      deviceIndex: identity.device_index,
    };
    showView("ext");
    $("ext-done").classList.add("hidden");
    await loadExtState();
  } catch (error) {
    alert(error.message);
  }
}

async function loadExtState() {
  if (!extSession) return;
  extBusy = true;
  setExtControls(false);
  $("ext-status").textContent = "Loading…";
  try {
    const state = await apiJson(`/api/ext/state/${extSession.id}`);
    if (state.done) {
      showExtDone(state);
      return;
    }
    await beginExtTrial(state);
  } catch (error) {
    extBusy = false;
    $("ext-status").textContent = error.message;
  }
}

async function beginExtTrial(state) {
  extState = state;
  extReplayed = 0;
  extBusy = true;
  setExtControls(false);
  $("ext-progress").textContent = `Trial ${state.trial_index + 1} of ${state.n_trials}`;
  $("ext-status").textContent = "Playing…";
  try {
    await playExt();
    extTimerStart = performance.now();
    extBusy = false;
    setExtControls(true);
    $("ext-status").textContent = "請評分 1–5.";
  } catch (error) {
    extBusy = false;
    $("ext-status").textContent = error.message;
  }
}

function playExt() {
  return postJson("/api/ext/play", {
    session_id: extSession.id,
    trial_index: extState.trial_index,
    device_index: extSession.deviceIndex,
  });
}

$("ext-replay").onclick = async () => {
  if (!extSession || !extState || extState.done || extBusy || extReplayed >= 1) return;
  extBusy = true;
  extReplayed = 1;
  setExtControls(false);
  $("ext-status").textContent = "Replaying…";
  try {
    await playExt();
    extTimerStart = performance.now();
    extBusy = false;
    for (let rating = 1; rating <= 5; rating++) {
      $(`ext-r${rating}`).disabled = false;
    }
    $("ext-replay").disabled = true;
    $("ext-status").textContent = "請評分 1–5.";
  } catch (error) {
    extBusy = false;
    $("ext-status").textContent = error.message;
  }
};

async function answerExt(rating) {
  if (!extSession || !extState || extState.done || extBusy) return;
  extBusy = true;
  setExtControls(false);
  $("ext-status").textContent = "Saving…";
  try {
    const result = await postJson("/api/ext/trial", {
      session_id: extSession.id,
      trial_index: extState.trial_index,
      rating,
      response_ms: Math.round(performance.now() - extTimerStart),
    });
    if (result.done) {
      showExtDone(result);
      return;
    }
    await beginExtTrial(result);
  } catch (error) {
    extBusy = false;
    $("ext-status").textContent = error.message;
  }
}

for (let rating = 1; rating <= 5; rating++) {
  $(`ext-r${rating}`).onclick = () => answerExt(rating);
}

function showExtDone(result) {
  extState = result;
  extBusy = false;
  setExtControls(false);
  $("ext-progress").textContent = `${result.n} trials complete`;
  $("ext-status").textContent = "";
  $("ext-result").textContent = `平均 ${result.mean_rating} / 5 (n=${result.n})`;
  $("ext-done").classList.remove("hidden");
}

$("ext-to-report").onclick = () => {
  showView("report");
  loadSessions();
};

// ---- soundstage-width flow ----
let widthSession = null;
let widthState = null;
let widthTimerStart = 0;
let widthReplayed = 0;
let widthBusy = false;

function setWidthControls(enabled) {
  $("width-first").disabled = !enabled;
  $("width-second").disabled = !enabled;
  $("width-replay").disabled = !enabled || widthReplayed >= 1;
}

async function startWidth() {
  const identity = setupIdentity();
  if (!identity) return;
  try {
    const data = await postJson("/api/width/session", {
      ...identity,
      stimulus: $("stimulus").value,
      peak_dbfs: +$("peak").value,
      stim_region: setupTrim.region(),
      spread_a: +$("width-a-spread").value,
      spread_b: +$("width-b-spread").value,
      outmode_a: $("width-a-mode").value,
      outmode_b: $("width-b-mode").value,
      n_trials: +$("width-n").value,
    });
    widthSession = {
      id: data.session_id,
      config: data.config,
      deviceIndex: identity.device_index,
    };
    showView("width");
    $("width-done").classList.add("hidden");
    await loadWidthState();
  } catch (error) {
    alert(error.message);
  }
}

async function loadWidthState() {
  if (!widthSession) return;
  widthBusy = true;
  setWidthControls(false);
  $("width-status").textContent = "Loading…";
  try {
    const state = await apiJson(`/api/width/state/${widthSession.id}`);
    if (state.done) {
      showWidthDone(state);
      return;
    }
    await beginWidthTrial(state);
  } catch (error) {
    widthBusy = false;
    $("width-status").textContent = error.message;
  }
}

async function playWidthPair() {
  $("width-status").textContent = "Playing 第一段…";
  await postJson("/api/width/play", {
    session_id: widthSession.id,
    trial_index: widthState.trial_index,
    interval: 1,
    device_index: widthSession.deviceIndex,
  });
  await sleep(600);
  $("width-status").textContent = "第二段…";
  await postJson("/api/width/play", {
    session_id: widthSession.id,
    trial_index: widthState.trial_index,
    interval: 2,
    device_index: widthSession.deviceIndex,
  });
}

async function beginWidthTrial(state) {
  widthState = state;
  widthReplayed = 0;
  widthBusy = true;
  setWidthControls(false);
  $("width-progress").textContent = `Trial ${state.trial_index + 1} of ${state.n_trials}`;
  try {
    await playWidthPair();
    widthTimerStart = performance.now();
    widthBusy = false;
    setWidthControls(true);
    $("width-status").textContent = "哪一段的音場比較寬?";
  } catch (error) {
    widthBusy = false;
    $("width-status").textContent = error.message;
  }
}

$("width-replay").onclick = async () => {
  if (!widthSession || !widthState || widthState.done || widthBusy || widthReplayed >= 1) return;
  widthBusy = true;
  widthReplayed = 1;
  setWidthControls(false);
  try {
    await playWidthPair();
    widthTimerStart = performance.now();
    widthBusy = false;
    $("width-first").disabled = false;
    $("width-second").disabled = false;
    $("width-replay").disabled = true;
    $("width-status").textContent = "哪一段的音場比較寬?";
  } catch (error) {
    widthBusy = false;
    $("width-status").textContent = error.message;
  }
};

async function answerWidth(choseFirst) {
  if (!widthSession || !widthState || widthState.done || widthBusy) return;
  widthBusy = true;
  setWidthControls(false);
  $("width-status").textContent = "Saving…";
  try {
    const result = await postJson("/api/width/trial", {
      session_id: widthSession.id,
      trial_index: widthState.trial_index,
      chose_first: choseFirst,
      response_ms: Math.round(performance.now() - widthTimerStart),
    });
    if (result.done) {
      showWidthDone(result);
      return;
    }
    await beginWidthTrial(result);
  } catch (error) {
    widthBusy = false;
    $("width-status").textContent = error.message;
  }
}

$("width-first").onclick = () => answerWidth(1);
$("width-second").onclick = () => answerWidth(0);

function showWidthDone(result) {
  widthState = result;
  widthBusy = false;
  setWidthControls(false);
  $("width-progress").textContent = `${result.n} trials complete`;
  $("width-status").textContent = "";
  const verdict = result.p_value < 0.05
    ? "寬度差異顯著"
    : "無顯著寬度差異";
  $("width-result").textContent =
    `A 判定較寬 ${result.k_a}/${result.n} · p=${result.p_value.toFixed(4)} · ${verdict}`;
  $("width-done").classList.remove("hidden");
}

$("width-to-report").onclick = () => {
  showView("report");
  loadSessions();
};

// ---- probe ----
let probeCircle, loopTimer = null;
function initProbe() {
  $("probe-circle-wrap").innerHTML = "";
  probeCircle = makeCircle((az) => { $("probe-az").value = az; });
  $("probe-circle-wrap").appendChild(probeCircle.svg);
  $("probe-az").oninput = () => probeCircle.setMarker(+$("probe-az").value);
  probeCircle.setMarker(+$("probe-az").value);
}

async function probePlay() {
  const devSel = $("probe-device").selectedOptions[0];
  if (!checkDevice($("probe-device"), $("probe-device-warn"), $("probe-outmode"))) return false;
  const outputMode = $("probe-outmode").value;
  let az = +$("probe-az").value;
  if (outputMode === "stereo") {
    az = Math.max(-90, Math.min(90, az));
    $("probe-az").value = az;
    probeCircle.setMarker(az);
  }
  await postJson("/api/play", {
    device_index: +devSel.value, target_az: az,
    stimulus: $("probe-stimulus").value, stim_region: probeTrim.region(),
    peak_dbfs: +$("probe-peak").value,
    output_mode: outputMode, seed: Math.floor(Math.random() * 1e9),
  });
  return true;
}

$("probe-play").onclick = probePlay;
$("probe-loop").onclick = async () => {
  if (loopTimer) return;
  if (!await probePlay()) return;
  $("probe-stop").disabled = false;
  const region = probeTrim.region();
  const interval = region ? (region[1] - region[0]) * 1000 + 500 : 1450;
  loopTimer = setInterval(probePlay, interval);
};
$("probe-stop").onclick = async () => {
  clearInterval(loopTimer); loopTimer = null;
  $("probe-stop").disabled = true;
  await fetch("/api/stop", { method: "POST" });
};

initSetup();
initProbe();
