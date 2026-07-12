// Setup, trial flow, manual probe, nav, response circle. Vanilla JS.
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

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

  // Clock-face reference (gamer-native): 12=front, 3=right, 6=behind, 9=left. Labels only,
  // response stays continuous -- no quantization to the hour marks.
  for (let h = 0; h < 12; h++) {
    const az = h * 30, [tx, ty] = xy(az, R - 22);
    const [tickA, tickB] = [xy(az, R), xy(az, R - 8)];
    svg.appendChild(mk("line", { x1: tickA[0], y1: tickA[1], x2: tickB[0], y2: tickB[1], stroke: "#ccc" }));
    svg.appendChild(mk("text", { x: tx, y: ty + 4, "text-anchor": "middle", fill: "#8a93a6",
      "font-size": 12 }, h === 0 ? 12 : h));
  }

  // First-person cardinal anchors, outside the rim. Names the counter-intuitive "behind = down".
  [["正前 (面向)", 0], ["你的右", 90], ["你的正後方", 180], ["你的左", -90]].forEach(([t, az]) => {
    const [x, y] = xy(az, R + 16);
    svg.appendChild(mk("text", { x, y: y + 4, "text-anchor": "middle", "font-weight": 700,
      fill: "#334" }, t));
  });

  // Response ray + rim marker (points from the head, so radius is clearly irrelevant).
  const ray = mk("line", { x1: C, y1: C, x2: C, y2: C, stroke: "#2b6cff", "stroke-width": 2, opacity: 0 });
  const target = mk("circle", { cx: C, cy: C, r: 7, fill: "#e04", opacity: 0 });
  const marker = mk("circle", { cx: C, cy: C, r: 8, fill: "#2b6cff", opacity: 0 });
  svg.appendChild(ray); svg.appendChild(target); svg.appendChild(marker);

  // Head icon facing up.
  svg.appendChild(mk("circle", { cx: C, cy: C, r: 16, fill: "#dde3ee", stroke: "#889" }));
  svg.appendChild(mk("polygon", { points: `${C},${C - 22} ${C - 6},${C - 10} ${C + 6},${C - 10}`, fill: "#556" }));
  svg.style.cursor = "crosshair";

  svg.addEventListener("click", (ev) => {
    const pt = svg.getBoundingClientRect();
    const scale = 360 / pt.width;
    const dx = (ev.clientX - pt.left) * scale - C, dy = (ev.clientY - pt.top) * scale - C;
    if (Math.hypot(dx, dy) < 20) return; // ignore clicks on the head
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
  checkDevice($("device"), $("device-warn"));
  checkDevice($("probe-device"), $("probe-device-warn"));

  const stims = await (await fetch("/api/stimuli")).json();
  const fillS = (sel) => { sel.innerHTML = ""; stims.forEach(s => { const o = document.createElement("option"); o.value = s; o.textContent = s; sel.appendChild(o); }); };
  fillS($("stimulus")); fillS($("probe-stimulus"));

  $("device").onchange = () => checkDevice($("device"), $("device-warn"));
  $("probe-device").onchange = () => checkDevice($("probe-device"), $("probe-device-warn"));
  ["step", "reps"].forEach(id => $(id).oninput = estimateDuration);
  estimateDuration();
}

function checkDevice(sel, warnEl) {
  const usable = sel.selectedOptions[0]?.dataset.usable === "1";
  if (!usable) {
    warnEl.textContent = "This endpoint will not accept an 8-channel stream. Enable 7.1 or a spatial-sound APO (Atmos/Sonic) on it before starting; the tool never downmixes.";
    warnEl.classList.remove("hidden");
    return false;
  }
  warnEl.classList.add("hidden");
  return true;
}

function estimateDuration() {
  const n = (360 / +$("step").value) * +$("reps").value;
  const secs = Math.round(n * 7);
  $("duration-est").textContent = `${n} trials, ~${Math.floor(secs / 60)}m ${secs % 60}s at ~7s/trial.`;
}

$("start-practice").onclick = () => startSession("practice");
$("start-main").onclick = () => startSession("main");

async function startSession(mode) {
  const devSel = $("device").selectedOptions[0];
  if (!checkDevice($("device"), $("device-warn"))) return;
  if (!$("participant").value.trim()) { alert("Enter participant ID"); return; }
  const body = {
    participant: $("participant").value.trim(), condition: $("condition").value.trim() || "unlabeled",
    device_index: +devSel.value, device_name: devSel.dataset.name, mode,
    azimuth_step: +$("step").value, reps: +$("reps").value,
    peak_dbfs: +$("peak").value, stimulus: $("stimulus").value,
  };
  const s = await (await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
  runSession({ id: s.session_id, order: s.trial_order, config: s.config, mode, completed: new Set(s.completed) });
}

// resume from Reports tab
document.addEventListener("click", async (e) => {
  const rid = e.target.dataset.resume;
  if (!rid) return;
  const s = await (await fetch(`/api/session/${rid}/resume`)).json();
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
  // first not-yet-done index
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
  await fetch("/api/play", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_index: c.device_index, target_az: az,
      stimulus: c.stimulus, peak_dbfs: c.peak_dbfs, seed: c.seed * 100003 + i }) });
}

function onPick(az) { response = az; $("confirm").disabled = false; }

$("replay").onclick = async () => {
  if (replayed >= 1) return;
  replayed = 1; $("replay").disabled = true;
  $("trial-status").textContent = "Replaying…";
  await playStimulus(sess.order[sess.ptr], sess.ptr);
  timerStart = performance.now(); // timer runs from end of last playback
  $("trial-status").textContent = "Click the perceived direction, then Confirm.";
};

$("confirm").onclick = async () => {
  if (response == null) return;
  const i = sess.ptr, az = sess.order[i];
  const ms = Math.round(performance.now() - timerStart);
  $("confirm").disabled = true; $("replay").disabled = true;
  const t = await (await fetch("/api/trial", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sess.id, trial_index: i, target_az: az,
      response_az: response, replay_count: replayed, response_ms: ms }) })).json();
  sess.completed.add(i);

  if (sess.mode === "practice") {
    circle.setTarget(az);
    $("feedback").classList.remove("hidden");
    $("feedback").innerHTML = `Target <b>${az}°</b> · You said <b>${response}°</b> · Error <b>${t.abs_error}°</b>`;
    await sleep(2500);
  }
  while (paused) await sleep(200);
  await sleep(1000); // between-trial gap
  sess.ptr++;
  nextTrial();
};

async function finishSession() {
  await fetch(`/api/session/${sess.id}/complete`, { method: "POST" });
  $("trial-status").textContent = "";
  alert(`Session complete: ${sess.completed.size} trials committed.`);
  showView("report");
}

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
  if (!checkDevice($("probe-device"), $("probe-device-warn"))) return false;
  await fetch("/api/play", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_index: +devSel.value, target_az: +$("probe-az").value,
      stimulus: $("probe-stimulus").value, peak_dbfs: +$("probe-peak").value,
      seed: Math.floor(Math.random() * 1e9) }) });
  return true;
}

$("probe-play").onclick = probePlay;
$("probe-loop").onclick = async () => {
  if (loopTimer) return;
  if (!await probePlay()) return;
  $("probe-stop").disabled = false;
  loopTimer = setInterval(probePlay, 1450); // ~0.95s stimulus + gap
};
$("probe-stop").onclick = async () => {
  clearInterval(loopTimer); loopTimer = null;
  $("probe-stop").disabled = true;
  await fetch("/api/stop", { method: "POST" });
};

initSetup();
initProbe();
