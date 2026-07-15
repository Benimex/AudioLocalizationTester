// SVG report rendering + Reports tab logic. No external libs.
const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}

// azimuth (deg, 0=up, clockwise+) -> xy on a circle of radius r centered cx,cy.
function azXY(az, r, cx, cy) {
  const a = az * Math.PI / 180;
  return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
}

// Polar plot: per-azimuth MAE as radius from center. Bigger = worse.
function polarMAE(perAz, step) {
  const W = 360, cx = 180, cy = 180, R = 150;
  const svg = el("svg", { viewBox: `0 0 ${W} ${W}`, width: W, height: W });
  const azes = Object.keys(perAz).map(Number).sort((a, b) => a - b);
  const maxMae = Math.max(30, ...azes.map(a => perAz[a]));
  // rings
  for (let frac = 0.25; frac <= 1; frac += 0.25) {
    svg.appendChild(el("circle", { cx, cy, r: R * frac, fill: "none", stroke: "#e0e0e0" }));
    svg.appendChild(el("text", { x: cx + 3, y: cy - R * frac + 12, fill: "#999" },
      Math.round(maxMae * frac) + "°"));
  }
  // spokes + labels at each grid azimuth
  for (let az = -180; az < 180; az += step) {
    const [ex, ey] = azXY(az, R, cx, cy);
    svg.appendChild(el("line", { x1: cx, y1: cy, x2: ex, y2: ey, stroke: "#f0f0f0" }));
    const [lx, ly] = azXY(az, R + 14, cx, cy);
    svg.appendChild(el("text", { x: lx, y: ly, "text-anchor": "middle", "dominant-baseline": "middle" }, az + "°"));
  }
  // data polygon
  let pts = "";
  for (const az of azes) {
    const [x, y] = azXY(az, R * perAz[az] / maxMae, cx, cy);
    pts += `${x},${y} `;
    svg.appendChild(el("circle", { cx: x, cy: y, r: 3, fill: "#2b6cff" }));
  }
  if (azes.length > 2) svg.appendChild(el("polygon", { points: pts, fill: "rgba(43,108,255,.15)", stroke: "#2b6cff" }));
  return svg;
}

// Confusion heatmap: target bin (rows) x response bin (cols).
function heatmap(hm, grid) {
  const n = grid.length, cell = 26, pad = 42;
  const W = pad + n * cell + 10, H = pad + n * cell + 10;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H });
  const max = Math.max(1, ...hm.flat());
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const v = hm[i][j];
      const t = v / max;
      const col = v === 0 ? "#fafafa" : `rgb(${Math.round(255 - 200 * t)},${Math.round(255 - 120 * t)},255)`;
      svg.appendChild(el("rect", { x: pad + j * cell, y: pad + i * cell, width: cell, height: cell,
        fill: col, stroke: "#eee" }));
      if (v) svg.appendChild(el("text", { x: pad + j * cell + cell / 2, y: pad + i * cell + cell / 2 + 4,
        "text-anchor": "middle" }, v));
    }
    // row label (target) + col label (response)
    svg.appendChild(el("text", { x: pad - 6, y: pad + i * cell + cell / 2 + 4, "text-anchor": "end" }, grid[i]));
    svg.appendChild(el("text", { x: pad + i * cell + cell / 2, y: pad - 6, "text-anchor": "middle" }, grid[i]));
  }
  svg.appendChild(el("text", { x: 12, y: pad + n * cell / 2, "text-anchor": "middle",
    transform: `rotate(-90 12 ${pad + n * cell / 2})`, "font-weight": "700" }, "target"));
  svg.appendChild(el("text", { x: pad + n * cell / 2, y: 14, "text-anchor": "middle", "font-weight": "700" }, "response"));
  return svg;
}

function metricBlock(title, node, desc) {
  const div = document.createElement("div");
  div.className = "metric-block";
  const h = document.createElement("h3");
  h.textContent = title;
  div.appendChild(h);
  if (desc) {
    const p = document.createElement("p");
    p.className = "hint"; p.innerHTML = desc;
    div.appendChild(p);
  }
  div.appendChild(node);
  return div;
}

function renderReport(container, data) {
  const m = data.metrics, s = data.session;
  container.innerHTML = "";
  if (!m.n) { container.textContent = "No committed trials."; return; }

  const summary = document.createElement("div");
  summary.className = "metric-block";
  summary.innerHTML = `<h3>Session #${s.id} — ${s.participant} / ${s.condition}</h3>
    <p><span class="big-num">${m.mae}°</span> 平均絕對誤差 (MAE), n=${m.n} 題</p>
    <p class="hint">每題「聽到的方位」與「實際播放方位」差幾度, 全部取平均. 越小越準,
      0 = 完美. 一般虛擬環繞落在 10 到 30 度.</p>
    <table class="mini">
      <tr><td>前後混淆率</td><td><b>${pct(m.fb_rate)}</b></td>
        <td class="hint">把前方聽成後方 (或反之) 的比率. 耳機虛擬環繞最常見的弱點, 越低越好.</td></tr>
      <tr><td>左右混淆率</td><td><b>${pct(m.lr_rate)}</b></td>
        <td class="hint">左右聽反的比率. 正常應接近 0; 偏高代表嚴重問題 (通道接反或演算法異常).</td></tr>
    </table>
    <p><a href="/api/export/${s.id}">下載 CSV (原始逐題資料)</a></p>`;
  container.appendChild(summary);
  container.appendChild(metricBlock("各方位平均誤差 (polar plot)", polarMAE(m.per_az, m.step),
    "每個時鐘方位的平均誤差畫成一圈. 點離圓心越遠 = 該方位越容易被聽錯; 藍色多邊形越縮向中心整體越好. " +
    "看哪個方位特別外凸 = 演算法在那個方向最弱 (通常是正後方與側後)."));
  container.appendChild(metricBlock("混淆矩陣 (confusion matrix)", heatmap(m.heatmap, m.grid),
    "縱軸 = 真正播放的方位, 橫軸 = 受測者實際點的方位. 對角線 (左上到右下) 的格子越集中 = 聽得越準. " +
    "偏離對角線 = 聽錯; 與對角線垂直的另一條斜帶 = 前後鏡像混淆的熱點."));
}

function cmaaStaircase(data) {
  const W = 720, H = 320;
  const left = 52, right = 18, top = 14, bottom = 38;
  const plotW = W - left - right, plotH = H - top - bottom;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H });
  const trials = data.trials;
  const estimate = data.estimate;
  const y = (delta) => top + plotH -
    (Math.log10(Math.max(1, Math.min(60, delta))) / Math.log10(60)) * plotH;
  const x = (index) => left + (trials.length <= 1 ? plotW / 2 : index / (trials.length - 1) * plotW);

  svg.appendChild(el("rect", {
    x: left, y: top, width: plotW, height: plotH,
    fill: "#fff", stroke: "#ccc",
  }));

  for (const tick of [1, 2, 5, 10, 20, 40, 60]) {
    const ty = y(tick);
    svg.appendChild(el("line", {
      x1: left, y1: ty, x2: left + plotW, y2: ty,
      stroke: "#ececec",
    }));
    svg.appendChild(el("text", {
      x: left - 7, y: ty + 4, "text-anchor": "end",
    }, String(tick)));
  }

  for (let tick = 0; tick < trials.length; tick += 5) {
    const tx = x(tick);
    svg.appendChild(el("line", {
      x1: tx, y1: top + plotH, x2: tx, y2: top + plotH + 5,
      stroke: "#777",
    }));
    svg.appendChild(el("text", {
      x: tx, y: top + plotH + 18, "text-anchor": "middle",
    }, String(tick)));
  }

  if (estimate) {
    const bandTop = y(estimate.ci_hi);
    const bandBottom = y(estimate.ci_lo);
    svg.appendChild(el("rect", {
      x: left,
      y: bandTop,
      width: plotW,
      height: Math.max(0, bandBottom - bandTop),
      fill: "rgba(43,108,255,.14)",
    }));
    const thresholdY = y(estimate.threshold);
    svg.appendChild(el("line", {
      x1: left, y1: thresholdY, x2: left + plotW, y2: thresholdY,
      stroke: "#2b6cff", "stroke-width": 2, "stroke-dasharray": "7 5",
    }));
  }

  for (const trial of trials) {
    svg.appendChild(el("circle", {
      cx: x(trial.trial_index),
      cy: y(trial.delta),
      r: 4,
      fill: trial.correct ? "#24934d" : "#d33b3b",
      stroke: "#fff",
      "stroke-width": 1,
    }));
  }

  svg.appendChild(el("text", {
    x: left + plotW / 2, y: H - 5, "text-anchor": "middle",
    "font-weight": "700",
  }, "Trial index"));
  svg.appendChild(el("text", {
    x: 14, y: top + plotH / 2, "text-anchor": "middle",
    transform: `rotate(-90 14 ${top + plotH / 2})`,
    "font-weight": "700",
  }, "Delta (°, log scale)"));
  return svg;
}

function renderCmaaReport(container, data) {
  container.innerHTML = "";
  const s = data.session, estimate = data.estimate;
  if (!data.n || !estimate) {
    container.textContent = "No committed trials.";
    return;
  }

  const summary = document.createElement("div");
  summary.className = "metric-block";
  summary.innerHTML = `<h3>Session #${s.id} — ${s.participant} / ${s.condition}</h3>
    <p><span class="big-num">${estimate.threshold.toFixed(1)}°</span> separation threshold</p>
    <p>CI ${estimate.ci_lo.toFixed(1)}°–${estimate.ci_hi.toFixed(1)}° · n=${data.n}</p>
    <p class="hint">閾值越低代表能分辨越接近的兩個聲音, 分離度越好.</p>`;
  container.appendChild(summary);
  container.appendChild(metricBlock("QUEST staircase", cmaaStaircase(data),
    "每點是一題, 高度是當題角度差, 綠=答對紅=答錯; 線=收斂出的分離度閾值, 越低越好."));
}

function pct(x) { return x == null ? "n/a" : (x * 100).toFixed(1) + "%"; }

function renderCompare(container, cols) {
  container.innerHTML = "";
  if (!cols.length) { container.textContent = "Select 2+ sessions and click Compare."; return; }

  const locCols = cols.filter(c => c.metrics.type === "loc");
  const cmaaCols = cols.filter(c => c.metrics.type === "cmaa");
  let html = "";

  if (locCols.length) {
    const rows = [
      ["n", c => c.metrics.n],
      ["MAE (°)", c => c.metrics.mae ?? "n/a"],
      ["Front-back conf.", c => pct(c.metrics.fb_rate)],
      ["Left-right conf.", c => pct(c.metrics.lr_rate)],
    ];
    html += "<div class='metric-block'><h3>Comparison</h3>" +
      "<p class='hint'>每欄一個 session, 或相同 condition 多個 session 合併的 POOLED 欄. " +
      "判讀: MAE 低且前後/左右混淆率低的 condition 勝. n = 該欄有效題數.</p>" +
      "<table><tr><th>Metric</th>";
    locCols.forEach(c => html += `<th>${c.label}</th>`);
    html += "</tr>";
    rows.forEach(([name, fn]) => {
      html += `<tr><td>${name}</td>`;
      locCols.forEach(c => html += `<td>${fn(c)}</td>`);
      html += "</tr>";
    });
    html += "</table></div>";
  }

  if (cmaaCols.length) {
    const rows = [
      ["n", c => c.metrics.n],
      ["Threshold (°)", c => c.metrics.threshold == null ? "n/a" : c.metrics.threshold.toFixed(1)],
      ["CI", c => c.metrics.ci_lo == null || c.metrics.ci_hi == null
        ? "n/a" : `${c.metrics.ci_lo.toFixed(1)}°–${c.metrics.ci_hi.toFixed(1)}°`],
    ];
    html += "<div class='metric-block'><h3>Separation (CMAA)</h3>" +
      "<p class='hint'>閾值越低分離度越好.</p><table><tr><th>Metric</th>";
    cmaaCols.forEach(c => html += `<th>${c.label}</th>`);
    html += "</tr>";
    rows.forEach(([name, fn]) => {
      html += `<tr><td>${name}</td>`;
      cmaaCols.forEach(c => html += `<td>${fn(c)}</td>`);
      html += "</tr>";
    });
    html += "</table></div>";
  }

  container.innerHTML = html;
}

// ---- Reports tab wiring ----
async function loadSessions() {
  const list = await (await fetch("/api/sessions")).json();
  const tb = document.querySelector("#session-list tbody");
  tb.innerHTML = "";
  for (const s of list) {
    const tr = document.createElement("tr");
    const status = s.completed ? "complete" : `incomplete`;
    const resume = (!s.completed && s.mode === "main")
      ? `<button data-resume="${s.id}">resume</button>` : "";
    tr.innerHTML = `<td><input type="checkbox" data-sid="${s.id}"></td>
      <td>${s.id}</td><td>${s.participant}</td><td>${s.condition}</td><td>${s.mode}</td>
      <td>${s.n_trials}</td><td>${status}</td><td>${s.created_at.slice(0, 16).replace("T", " ")}</td>
      <td><button data-report="${s.id}" data-mode="${s.mode}">view</button> ${resume}</td>`;
    tb.appendChild(tr);
  }
}

document.addEventListener("click", async (e) => {
  const rep = e.target.dataset.report;
  if (rep) {
    const isCmaa = e.target.dataset.mode === "cmaa";
    const endpoint = isCmaa ? `/api/cmaa/report/${rep}` : `/api/report/${rep}`;
    const data = await (await fetch(endpoint)).json();
    const detail = document.getElementById("report-detail");
    if (isCmaa) renderCmaaReport(detail, data);
    else renderReport(detail, data);
    document.getElementById("compare-detail").innerHTML = "";
  }
  if (e.target.id === "compare-btn") {
    const ids = [...document.querySelectorAll("[data-sid]:checked")].map(c => c.dataset.sid);
    if (!ids.length) return;
    const data = await (await fetch(`/api/compare?ids=${ids.join(",")}`)).json();
    renderCompare(document.getElementById("compare-detail"), data.columns);
    document.getElementById("report-detail").innerHTML = "";
  }
  if (e.target.id === "refresh-sessions") loadSessions();
});
