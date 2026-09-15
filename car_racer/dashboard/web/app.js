"use strict";

const POLL_MS = 1000;

const $ = (id) => document.getElementById(id);

const status = $("status");
const statusText = $("status-text");

const fmtLap = (v) => (v && v > 0 && v < 90 ? v.toFixed(2) + "s" : "—");
const fmtDist = (px) => (px > 0 ? (px / 20).toFixed(0) + " m" : "—"); // PX_PER_METER = 20

// ---------- графики ----------
const palette = [
  "#4f8cff", "#3ecf8e", "#ffb457", "#ef5d6c", "#9b7bff",
  "#2bc9c9", "#f7d154", "#ff7b9c", "#8fe388", "#c792ea",
];

let charts = {};
function ensureCharts() {
  if (typeof Chart === "undefined") return false;
  if (Object.keys(charts).length) return true;

  charts.fitness = new Chart($("chart-fitness"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "max", data: [], borderColor: "#3ecf8e", backgroundColor: "rgba(62,207,142,0.1)", fill: true, tension: 0.25, pointRadius: 0 },
      { label: "mean", data: [], borderColor: "#4f8cff", backgroundColor: "rgba(79,140,255,0.08)", fill: true, tension: 0.25, pointRadius: 0 },
      { label: "min", data: [], borderColor: "#8b93a7", borderDash: [4, 3], fill: false, tension: 0.25, pointRadius: 0 },
    ]},
    options: baseOptions("Фитнес по поколениям"),
  });

  charts.species = new Chart($("chart-species"), {
    type: "bar",
    data: { labels: [], datasets: [] },
    options: Object.assign(baseOptions("Виды по поколениям"), {
      scales: {
        x: { stacked: true, ticks: { color: "#8b93a7" }, grid: { color: "#1c2230" } },
        y: { stacked: true, beginAtZero: true, ticks: { color: "#8b93a7" }, grid: { color: "#1c2230" } },
      },
      plugins: { legend: { labels: { color: "#8b93a7" } } },
    }),
  });

  charts.progress = new Chart($("chart-progress"), {
    type: "line",
    data: { labels: [], datasets: [
      { label: "лучший круг (с)", data: [], borderColor: "#ffb457", yAxisID: "y", tension: 0.25, pointRadius: 0 },
      { label: "дистанция (м)", data: [], borderColor: "#3ecf8e", yAxisID: "y1", tension: 0.25, pointRadius: 0 },
    ]},
    options: Object.assign(baseOptions("Прогресс навыка"), {
      scales: {
        x: { ticks: { color: "#8b93a7" }, grid: { color: "#1c2230" } },
        y: { position: "left", ticks: { color: "#8b93a7" }, grid: { color: "#1c2230" } },
        y1: { position: "right", ticks: { color: "#8b93a7" }, grid: { drawOnChartArea: false } },
      },
    }),
  });

  return true;
}

function baseOptions(title) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: {
      legend: { labels: { color: "#8b93a7" } },
      title: { display: true, text: title, color: "#e6e9f0" },
    },
    scales: {
      x: { ticks: { color: "#8b93a7" }, grid: { color: "#1c2230" } },
      y: { beginAtZero: true, ticks: { color: "#8b93a7" }, grid: { color: "#1c2230" } },
    },
  };
}

function renderCharts(history) {
  if (!ensureCharts()) return;
  const labels = history.map((h) => h.generation);

  const setLine = (chart, idx, data) => {
    chart.data.labels = labels;
    chart.data.datasets[idx].data = data;
  };

  setLine(charts.fitness, 0, history.map((h) => h.fitness_max));
  setLine(charts.fitness, 1, history.map((h) => h.fitness_mean));
  setLine(charts.fitness, 2, history.map((h) => h.fitness_min));

  const maxSpecies = Math.max(1, ...history.map((h) => (h.species_sizes ? h.species_sizes.length : 0)));
  const speciesDatasets = [];
  for (let i = 0; i < maxSpecies; i++) {
    speciesDatasets.push({
      label: `вид ${i + 1}`,
      data: history.map((h) => (h.species_sizes && h.species_sizes[i]) || 0),
      backgroundColor: palette[i % palette.length],
      stack: "s",
    });
  }
  charts.species.data.labels = labels;
  charts.species.data.datasets = speciesDatasets;

  const lapData = history.map((h) => (h.best_lap_time > 0 && h.best_lap_time < 90 ? +h.best_lap_time.toFixed(2) : null));
  const distData = history.map((h) => +(h.max_distance_px / 20).toFixed(0));
  setLine(charts.progress, 0, lapData);
  setLine(charts.progress, 1, distData);

  charts.fitness.update();
  charts.species.update();
  charts.progress.update();
}

// ---------- геном ----------
function renderGenome(genome) {
  const canvas = $("genome-canvas");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  if (!genome || !genome.nodes || !genome.nodes.length) {
    ctx.fillStyle = "#8b93a7";
    ctx.font = "14px sans-serif";
    ctx.fillText("данных ещё нет…", 20, 30);
    return;
  }

  const pad = 50;
  const byKey = {};
  genome.nodes.forEach((n) => (byKey[n.key] = n));
  const px = (n) => pad + n.x * (W - 2 * pad);
  const py = (n) => pad + n.y * (H - 2 * pad);

  genome.connections.forEach((c) => {
    const a = byKey[c.from], b = byKey[c.to];
    if (!a || !b) return;
    ctx.strokeStyle = c.weight >= 0 ? "rgba(120,150,200,0.45)" : "rgba(239,93,108,0.45)";
    ctx.lineWidth = Math.min(3, Math.max(0.5, Math.abs(c.weight)));
    ctx.beginPath();
    ctx.moveTo(px(a), py(a));
    ctx.lineTo(px(b), py(b));
    ctx.stroke();
  });

  genome.nodes.forEach((n) => {
    const x = px(n), y = py(n);
    const color = n.type === "input" ? "#3ecf8e" : n.type === "output" ? "#ef5d6c" : "#4f8cff";
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#8b93a7";
    ctx.font = "11px sans-serif";
    if (n.type === "input") ctx.fillText(n.label || "", x - 12, y - 8);
    else if (n.type === "output") ctx.fillText(n.label || "", x + 10, y - 8);
  });
}

// ---------- KPI / синхронизация контролов ----------
function renderKpis(c) {
  $("kpi-generation").textContent = c.generation ?? "—";
  $("kpi-fitness").textContent = (c.max_fitness ?? 0).toFixed(2);
  $("kpi-lap").textContent = fmtLap(c.best_lap_time);
  $("kpi-distance").textContent = fmtDist(c.max_distance_px);
  $("kpi-cl").textContent = c.max_cl ?? "—";
  $("kpi-laps").textContent = c.max_laps ?? "—";
  $("kpi-fps").textContent = c.fps ? c.fps.toFixed(0) : "—";
  $("kpi-left").textContent = c.left_in_group ?? "—";

  $("meta-track").textContent = "трасса: " + (c.track || "—");
  $("meta-paused").textContent = c.paused ? "ПАУЗА" : "";

  const pauseBtn = $("btn-pause");
  pauseBtn.textContent = c.paused ? "Снять паузу" : "Пауза";
  pauseBtn.classList.toggle("active", !!c.paused);

  const fpsBtn = $("btn-fps");
  fpsBtn.textContent = c.unlimited_fps ? "Unlimited FPS: ON" : "Unlimited FPS";
  fpsBtn.classList.toggle("active", !!c.unlimited_fps);

  const followBtn = $("btn-follow");
  followBtn.textContent = c.camera_follow ? "Camera Follow: ON" : "Camera Follow";
  followBtn.classList.toggle("active", !!c.camera_follow);

  const tlBtn = $("btn-tracklines");
  tlBtn.textContent = c.show_track_lines ? "Track Lines: ON" : "Track Lines: OFF";
  tlBtn.classList.toggle("active", !!c.show_track_lines);
}

function syncInputs(c) {
  const map = {
    "field-group": c.group_size,
    "field-visible": c.max_visible,
    "field-pop": c.pop_size,
    "field-fps": c.render_fps,
    "field-grip": c.grip_g,
    "field-mass": c.mass_kg,
    "field-power": c.power_hp,
    "field-zoom": c.zoom,
  };
  for (const [id, v] of Object.entries(map)) {
    const el = $(id);
    if (v !== undefined && v !== null && document.activeElement !== el) {
      el.value = v;
    }
  }

  // Дропдаун трасс: пересобираем только при изменении списка.
  const trackSel = $("field-track");
  const tracks = c.tracks || [];
  const cur = (tracks.length ? tracks.join(",") : "") + "|" + c.track;
  if (trackSel.dataset.cur !== cur && document.activeElement !== trackSel) {
    trackSel.innerHTML = "";
    tracks.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      trackSel.appendChild(opt);
    });
    trackSel.value = c.track || "";
    trackSel.dataset.cur = cur;
  }
}

// ---------- сеть ----------
async function poll() {
  try {
    const res = await fetch("/api/stats", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    status.classList.add("online");
    statusText.textContent = "подключено";
    const c = data.current || {};
    renderKpis(c);
    syncInputs(c);
    renderCharts(data.history || []);
    renderGenome(c.genome);
  } catch (e) {
    status.classList.remove("online");
    statusText.textContent = "нет связи";
  }
}

async function command(action, value) {
  try {
    await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value === undefined ? { action } : { action, value }),
    });
  } catch (e) {
    console.error("command failed", e);
  }
}

// ---------- управление ----------
$("btn-pause").addEventListener("click", () => command("toggle_pause"));
$("btn-fps").addEventListener("click", () => command("toggle_unlimited_fps"));
$("btn-follow").addEventListener("click", () => command("toggle_camera_follow"));
$("btn-tracklines").addEventListener("click", () => command("toggle_track_lines"));
$("btn-restart-group").addEventListener("click", () => command("restart_group"));
$("btn-recompute").addEventListener("click", () => command("recompute_ideal_line"));
$("btn-restart-training").addEventListener("click", () => {
  if (confirm("Перезапустить обучение с нуля?")) command("restart_training");
});

$("field-track").addEventListener("change", (e) => command("set_track", e.target.value));

const fieldActions = {
  "field-group": "set_group_size",
  "field-visible": "set_max_visible",
  "field-pop": "set_pop_size",
  "field-fps": "set_fps",
  "field-grip": "set_grip",
  "field-mass": "set_mass",
  "field-power": "set_power",
};
for (const [id, action] of Object.entries(fieldActions)) {
  const el = $(id);
  el.addEventListener("change", () => {
    const v = parseFloat(el.value);
    if (!Number.isNaN(v)) command(action, v);
  });
}
$("field-zoom").addEventListener("input", (e) => command("set_zoom", parseFloat(e.target.value)));

poll();
setInterval(poll, POLL_MS);
