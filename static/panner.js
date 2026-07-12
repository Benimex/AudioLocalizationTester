// Object Panner sandbox (backend C) -- three.js 3D room + Web Audio HRTF.
// Audio runs client-side (PannerNode panningModel='HRTF') so dragging rotates the sound
// SEAMLESSLY in real time (no server round-trip, no buffer restart). Web Audio's listener
// faces -Z with +X right / +Y up, matching our world. Horizontal = drag on floor, height = slider.
(() => {
  const g = (id) => document.getElementById(id);
  const W = 560, H = 400;
  const FLOOR_Y = -1.6, DH_MIN = 0.3, DH_MAX = 3.0, EL_MIN = -40, EL_MAX = 90, DIST_MAX = 3.0;
  const D2R = Math.PI / 180, R2D = 180 / Math.PI;

  let objects = [{ az: 0, y: 0, dh: 1.4 }];
  let active = 0, playing = false;
  let scene, camera, renderer, orbit, raycaster, pointer;
  let spheres = [], dropLines = [], shadows = [];
  let dragging = null, dragPlane;

  const worldPos = (o) => new THREE.Vector3(o.dh * Math.sin(o.az * D2R), o.y, -o.dh * Math.cos(o.az * D2R));
  function backendEl(o) { return Math.max(EL_MIN, Math.min(EL_MAX, Math.atan2(o.y, o.dh) * R2D)); }

  // ================= Web Audio (real-time HRTF) =================
  let actx = null, master = null, voices = [];   // voices[i] = {src, panner, gain}
  let region = { a: 0, b: 0, dur: 0 }, regionBuf = null;   // WAV A/B loop region

  function fillNoise(d, isPink) {
    if (isPink) {                                // Paul Kellet pink filter
      let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
      for (let i = 0; i < d.length; i++) {
        const w = Math.random() * 2 - 1;
        b0 = 0.99886 * b0 + w * 0.0555179; b1 = 0.99332 * b1 + w * 0.0750759;
        b2 = 0.96900 * b2 + w * 0.1538520; b3 = 0.86650 * b3 + w * 0.3104856;
        b4 = 0.55000 * b4 + w * 0.5329522; b5 = -0.7616 * b5 - w * 0.0168980;
        d[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
        b6 = w * 0.115926;
      }
    } else {
      for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * 0.4;
    }
  }

  // Generated stimuli. Pulsed (bursts + gaps) is less fatiguing AND localizes better
  // (onset cues) than a continuous drone. 'cont' keeps the old steady noise.
  function makeStimBuffer(kind) {
    const sr = actx.sampleRate, n = Math.floor(sr * 2.1);
    const buf = actx.createBuffer(1, n, sr), d = buf.getChannelData(0);
    fillNoise(d, kind.indexOf("pink") === 0);
    if (kind.indexOf("cont") >= 0) return buf;
    const click = kind === "click";
    const P = Math.floor((click ? 0.5 : 0.7) * sr);     // period
    const ON = Math.floor((click ? 0.006 : 0.2) * sr);  // burst length
    const RP = Math.max(1, Math.floor((click ? 0.001 : 0.01) * sr)); // raised-cosine ramp
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
  async function loadWav(name) {                  // real game SFX: fetch + decode, mono point source
    if (wavCache[name]) return wavCache[name];
    const ab = await (await fetch(`/stimuli/${encodeURIComponent(name)}`)).arrayBuffer();
    const dec = await actx.decodeAudioData(ab);
    let mono = dec;
    if (dec.numberOfChannels > 1) { mono = actx.createBuffer(1, dec.length, dec.sampleRate); mono.copyToChannel(dec.getChannelData(0), 0); }
    wavCache[name] = mono; return mono;
  }

  function positionPanner(p, o) {
    const v = worldPos(o), t = actx ? actx.currentTime : 0;
    // small ramp = zipper-free but still real-time-seamless
    p.positionX.setTargetAtTime(v.x, t, 0.01);
    p.positionY.setTargetAtTime(v.y, t, 0.01);
    p.positionZ.setTargetAtTime(v.z, t, 0.01);
  }

  async function buildVoices() {
    voices.forEach(v => { try { v.src.stop(); } catch (e) {} });
    voices = [];
    const kind = g("panner-stim").value;
    const isWav = kind.toLowerCase().endsWith(".wav");
    let buf;
    try { buf = isWav ? await loadWav(kind) : makeStimBuffer(kind); }
    catch (e) { buf = makeStimBuffer("white pulse"); }
    objects.forEach(o => {
      const src = actx.createBufferSource(); src.buffer = buf; src.loop = true;
      if (isWav) { src.loopStart = region.a; src.loopEnd = region.b; }  // A/B region
      const panner = actx.createPanner();
      panner.panningModel = "HRTF"; panner.distanceModel = "inverse";
      panner.refDistance = 1; panner.rolloffFactor = 1;
      positionPanner(panner, o);
      const gain = actx.createGain(); gain.gain.value = 0.5;
      src.connect(panner).connect(gain).connect(master);
      src.start(0, isWav ? region.a : 0);
      voices.push({ src, panner, gain });
    });
  }

  async function startAudio() {
    if (!actx) {
      actx = new (window.AudioContext || window.webkitAudioContext)();
      master = actx.createGain(); master.gain.value = 0.9; master.connect(actx.destination);
    }
    await actx.resume();
    const dev = g("panner-device").value;
    if (dev && actx.setSinkId) { try { await actx.setSinkId(dev); } catch (e) {} }
    await buildVoices();
  }
  function stopAudio() { voices.forEach(v => { try { v.src.stop(); } catch (e) {} }); voices = []; }

  // ================= three.js scene =================
  function textSprite(txt, color) {
    const c = document.createElement("canvas"); c.width = 128; c.height = 64;
    const x = c.getContext("2d");
    x.fillStyle = color; x.font = "bold 30px sans-serif"; x.textAlign = "center"; x.textBaseline = "middle";
    x.fillText(txt, 64, 32);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true }));
    sp.scale.set(0.9, 0.45, 1); return sp;
  }

  function makeHead() {
    const grp = new THREE.Group();
    const skin = new THREE.MeshStandardMaterial({ color: 0xccd3e0, roughness: 0.7 });
    const skull = new THREE.Mesh(new THREE.SphereGeometry(0.17, 28, 22), skin);
    skull.scale.set(0.95, 1.12, 1.12); grp.add(skull);
    // prominent nose + face plate on the front (-Z)
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.17, 16), new THREE.MeshStandardMaterial({ color: 0x9aa6bd }));
    nose.position.set(0, -0.01, -0.21); nose.rotation.x = -Math.PI / 2; grp.add(nose);
    const face = new THREE.Mesh(new THREE.CircleGeometry(0.1, 24), new THREE.MeshStandardMaterial({ color: 0x35c0ff, transparent: true, opacity: 0.45 }));
    face.position.set(0, 0.02, -0.166); grp.add(face);              // cyan "this is the face" disc
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0x1c2029 });
    for (const sx of [-1, 1]) {
      const eye = new THREE.Mesh(new THREE.SphereGeometry(0.032, 14, 12), eyeMat);
      eye.position.set(0.055 * sx, 0.05, -0.16); grp.add(eye);
      const ear = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 10), skin);
      ear.position.set(0.17 * sx, 0, 0); ear.scale.set(0.5, 1, 0.8); grp.add(ear);
    }
    // forward arrow -- unambiguous facing from any orbit angle
    grp.add(new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0, 0), 0.75, 0x35c0ff, 0.18, 0.12));
    return grp;
  }

  function buildScene() {
    scene = new THREE.Scene(); scene.background = new THREE.Color(0x1b1e24);
    camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
    camera.position.set(3.6, 3.0, 5.2);
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(W, H); renderer.setPixelRatio(window.devicePixelRatio || 1);
    g("panner-3d").appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.85));
    const dl = new THREE.DirectionalLight(0xffffff, 0.5); dl.position.set(3, 6, 4); scene.add(dl);

    // room a touch larger than the max sphere reach (dh<=3 + radius) so nothing pokes through walls
    const rw = 6.6, rh = 4.6, rd = 6.8, box = new THREE.BoxGeometry(rw, rh, rd);
    const room = new THREE.Mesh(box, new THREE.MeshBasicMaterial({ color: 0x3a4150, transparent: true, opacity: 0.12, side: THREE.BackSide }));
    room.position.y = FLOOR_Y + rh / 2; scene.add(room);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: 0x5a6675 }));
    edges.position.copy(room.position); scene.add(edges);
    const grid = new THREE.GridHelper(rw, 12, 0x44506a, 0x2e3543); grid.position.y = FLOOR_Y; scene.add(grid);
    const ceil = new THREE.GridHelper(rw, 12, 0x39435a, 0x252b38); ceil.position.y = FLOOR_Y + rh; scene.add(ceil);

    scene.add(makeHead());
    const half = { x: rw / 2 - 0.2, z: rd / 2 - 0.2 };
    [["FRONT 0°", "#7fdfff", 0, -half.z], ["BACK 180°", "#fcc", 0, half.z],
     ["R +90°", "#cfc", half.x, 0], ["L -90°", "#ccf", -half.x, 0]]
      .forEach(([t, c, x, z]) => { const s = textSprite(t, c); s.position.set(x, 0.25, z); scene.add(s); });

    orbit = new THREE.OrbitControls(camera, renderer.domElement);
    orbit.enableDamping = true; orbit.target.set(0, 0, 0);
    raycaster = new THREE.Raycaster(); pointer = new THREE.Vector2();
    dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const dom = renderer.domElement;
    dom.addEventListener("pointerdown", onDown);
    dom.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    rebuildSpheres(); animate();
  }

  const COLORS = [0x2b6cff, 0x35c07a, 0xe0c020, 0xe0603a, 0x9a5ad0];
  function rebuildSpheres() {
    [...spheres, ...dropLines, ...shadows].forEach(o => scene.remove(o));
    spheres = []; dropLines = []; shadows = [];
    objects.forEach((o, i) => {
      const col = COLORS[i % COLORS.length];
      const sp = new THREE.Mesh(new THREE.SphereGeometry(0.15, 20, 16), new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.25 }));
      sp.position.copy(worldPos(o)); sp.userData.idx = i; scene.add(sp); spheres.push(sp);
      const line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: col, dashSize: 0.12, gapSize: 0.08, transparent: true, opacity: 0.7 }));
      scene.add(line); dropLines.push(line);
      const sh = new THREE.Mesh(new THREE.CircleGeometry(0.14, 20), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.25 }));
      sh.rotation.x = -Math.PI / 2; scene.add(sh); shadows.push(sh);
    });
    updateDrops();
  }
  function updateDrops() {
    spheres.forEach((sp, i) => {
      const p = sp.position;
      dropLines[i].geometry.setFromPoints([p.clone(), new THREE.Vector3(p.x, FLOOR_Y, p.z)]);
      dropLines[i].computeLineDistances();
      shadows[i].position.set(p.x, FLOOR_Y + 0.01, p.z);
      const on = i === active;
      sp.scale.setScalar(on ? 1.28 : 1.0); sp.material.emissiveIntensity = on ? 0.55 : 0.2;
    });
  }

  // pointer: drag sphere on floor plane, else orbit
  function pick(e) {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    return raycaster.intersectObjects(spheres)[0];
  }
  function onDown(e) {
    const hit = pick(e); if (!hit) return;
    active = hit.object.userData.idx; dragging = active;
    dragPlane.constant = -objects[active].y; orbit.enabled = false;
    syncControls(); renderList(); updateDrops();
  }
  function onMove(e) {
    if (dragging === null) return;
    const r = renderer.domElement.getBoundingClientRect();
    pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const pt = new THREE.Vector3();
    if (!raycaster.ray.intersectPlane(dragPlane, pt)) return;
    const o = objects[dragging];
    o.dh = Math.min(DH_MAX, Math.max(DH_MIN, Math.round(Math.hypot(pt.x, pt.z) * 10) / 10));
    o.az = Math.round(Math.atan2(pt.x, -pt.z) * R2D * 10) / 10;
    spheres[dragging].position.copy(worldPos(o));
    if (voices[dragging]) positionPanner(voices[dragging].panner, o);   // seamless
    updateDrops(); syncControls(); renderList();
  }
  function onUp() { if (dragging !== null) { dragging = null; orbit.enabled = true; } }

  function animate() { requestAnimationFrame(animate); orbit.update(); renderer.render(scene, camera); }

  // side controls
  function renderList() {
    const ul = g("source-list"); ul.innerHTML = "";
    objects.forEach((o, i) => {
      const li = document.createElement("li"); li.className = i === active ? "active-src" : "";
      li.innerHTML = `<span>#${i + 1} &nbsp; az ${o.az}° · h ${o.y}m · ${o.dh}m &nbsp;<em>(el ${Math.round(backendEl(o))}°)</em></span>`;
      const sel = document.createElement("button"); sel.textContent = "edit"; sel.className = "ghost";
      sel.onclick = () => { active = i; syncControls(); renderList(); updateDrops(); };
      const del = document.createElement("button"); del.textContent = "×"; del.className = "ghost";
      del.onclick = () => { if (objects.length > 1) { objects.splice(i, 1); active = 0; rebuildSpheres(); if (playing) buildVoices(); syncControls(); renderList(); } };
      li.append(sel, del); ul.appendChild(li);
    });
  }
  function syncControls() {
    const o = objects[active];
    g("panner-az").value = o.az; g("az-val").textContent = o.az;
    g("panner-y").value = o.y; g("y-val").textContent = o.y.toFixed(1);
    g("panner-dist").value = o.dh; g("dist-val").textContent = o.dh;
    const col = "#" + COLORS[active % COLORS.length].toString(16).padStart(6, "0");
    g("editing-src").innerHTML = `Editing source #${active + 1} <span class="dot" style="background:${col}"></span>`;
  }
  function applyPos() {
    spheres[active].position.copy(worldPos(objects[active]));
    if (voices[active]) positionPanner(voices[active].panner, objects[active]);
    updateDrops(); renderList();
  }

  // ---- WAV player (waveform + A/B loop region) ----
  async function onStimChange() {
    const kind = g("panner-stim").value;
    if (kind.toLowerCase().endsWith(".wav")) {
      try {
        regionBuf = await loadWav(kind);
        region = { a: 0, b: regionBuf.duration, dur: regionBuf.duration };
        g("wav-player").classList.remove("hidden"); drawWave();
      } catch (e) { g("wav-player").classList.add("hidden"); }
    } else { g("wav-player").classList.add("hidden"); }
    if (playing) await buildVoices();
  }

  function drawWave() {
    const c = g("wav-wave"), x = c.getContext("2d"), W = c.width, Hc = c.height;
    x.fillStyle = "#0f1116"; x.fillRect(0, 0, W, Hc);
    if (!regionBuf || !region.dur) return;
    const data = regionBuf.getChannelData(0), n = data.length, step = Math.max(1, Math.floor(n / W));
    x.strokeStyle = "#4a5570"; x.beginPath();
    for (let px = 0; px < W; px++) {
      let mn = 1, mx = -1;
      for (let i = 0; i < step; i++) { const s = data[px * step + i] || 0; if (s < mn) mn = s; if (s > mx) mx = s; }
      x.moveTo(px, (1 - (mx + 1) / 2) * Hc); x.lineTo(px, (1 - (mn + 1) / 2) * Hc);
    }
    x.stroke();
    const ax = region.a / region.dur * W, bx = region.b / region.dur * W;
    x.fillStyle = "rgba(43,108,255,.22)"; x.fillRect(ax, 0, bx - ax, Hc);
    x.fillStyle = "#2b6cff"; x.fillRect(ax - 2, 0, 4, Hc); x.fillRect(bx - 2, 0, 4, Hc);
    g("wav-times").textContent = `A ${region.a.toFixed(2)}s · B ${region.b.toFixed(2)}s · 區間 ${(region.b - region.a).toFixed(2)}s / 全長 ${region.dur.toFixed(2)}s`;
  }

  function setHandle(which, t) {
    if (which === "a") region.a = Math.max(0, Math.min(t, region.b - 0.05));
    else region.b = Math.min(region.dur, Math.max(t, region.a + 0.05));
    drawWave();
    if (playing) voices.forEach(v => { v.src.loopStart = region.a; v.src.loopEnd = region.b; });
  }

  function initWaveCanvas() {
    const c = g("wav-wave"); let drag = null;
    const xToT = (cx) => { const r = c.getBoundingClientRect(); return Math.max(0, Math.min(region.dur, (cx - r.left) / r.width * region.dur)); };
    c.addEventListener("pointerdown", e => { if (!region.dur) return; const t = xToT(e.clientX); drag = Math.abs(t - region.a) <= Math.abs(t - region.b) ? "a" : "b"; setHandle(drag, t); });
    window.addEventListener("pointermove", e => { if (drag) setHandle(drag, xToT(e.clientX)); });
    window.addEventListener("pointerup", () => { drag = null; });
  }

  async function init() {
    actx = new (window.AudioContext || window.webkitAudioContext)();   // suspended until Play
    master = actx.createGain(); master.gain.value = 0.9; master.connect(actx.destination);
    // device list from the browser (Web Audio routes via setSinkId, not WASAPI)
    const sel = g("panner-device"); sel.innerHTML = "";
    const def = document.createElement("option"); def.value = ""; def.textContent = "Default output"; sel.appendChild(def);
    try {
      const outs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "audiooutput");
      outs.forEach(d => { if (d.deviceId && d.deviceId !== "default") { const o = document.createElement("option"); o.value = d.deviceId; o.textContent = d.label || "output"; sel.appendChild(o); } });
    } catch (e) {}
    let stims = ["pink pulse", "white pulse", "click", "pink cont", "white cont"];
    try {
      const wavs = (await (await fetch("/api/stimuli")).json()).filter(s => s.toLowerCase().endsWith(".wav"));
      stims = stims.concat(wavs);
    } catch (e) {}
    g("panner-stim").innerHTML = ""; stims.forEach(s => { const o = document.createElement("option"); o.value = s; o.textContent = s; g("panner-stim").appendChild(o); });

    buildScene(); renderList(); syncControls(); initWaveCanvas();
    g("panner-az").oninput = () => { objects[active].az = +g("panner-az").value; g("az-val").textContent = objects[active].az; applyPos(); };
    g("panner-y").oninput = () => { objects[active].y = +g("panner-y").value; g("y-val").textContent = objects[active].y.toFixed(1); applyPos(); };
    g("panner-dist").oninput = () => { objects[active].dh = +g("panner-dist").value; g("dist-val").textContent = objects[active].dh; applyPos(); };
    g("panner-stim").onchange = onStimChange;
    g("panner-vol").oninput = () => { if (master) master.gain.value = +g("panner-vol").value; };
    g("add-source").onclick = () => { objects.push({ az: 90, y: 0, dh: 1.4 }); active = objects.length - 1; rebuildSpheres(); if (playing) buildVoices(); syncControls(); renderList(); };
    g("panner-play").onclick = async () => { playing = true; g("panner-stop").disabled = false; await startAudio(); };
    g("panner-stop").onclick = () => { playing = false; g("panner-stop").disabled = true; stopAudio(); };
  }

  init();
})();
