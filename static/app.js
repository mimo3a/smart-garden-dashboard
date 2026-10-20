'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let _config = { sensors: [], thresholds: {} };
let _selectedSensor = null;   // { dev, ch, name }
let _timeMinutes = 15;
let _charts = { moisture: null, temp: null, battery: null };

// Must match the max_points sent to /api/history so bucket width is exact.
const MAX_POINTS = 300;

// ── DOM helpers ───────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

function showBanner(msg, isError) {
  const el = $('status-banner');
  el.textContent = msg;
  el.className = 'status-banner ' + (isError ? 'banner-error' : 'banner-info');
}

function hideBanner() {
  $('status-banner').className = 'status-banner hidden';
}

// ── API fetch ─────────────────────────────────────────────────────────────────
async function apiFetch(path) {
  const r = await fetch(path);
  if (!r.ok) throw Object.assign(new Error(r.statusText), { status: r.status });
  return r.json();
}

// ── Config + sensor grid ──────────────────────────────────────────────────────
async function loadConfig() {
  try {
    _config = await apiFetch('/api/config');
  } catch {
    _config = { sensors: [], thresholds: {} };
  }
}

function sensorKey(dev, ch) {
  return dev + ':' + ch;
}

function buildSensorGrid() {
  const grid = $('sensor-grid');
  grid.textContent = '';

  if (_config.sensors.length === 0) {
    const p = document.createElement('p');
    p.textContent = 'Keine Sensoren konfiguriert.';
    grid.appendChild(p);
    return;
  }

  _config.sensors.forEach(s => {
    const card = document.createElement('div');
    card.className = 'sensor-card';
    card.dataset.dev = s.dev;
    card.dataset.ch = s.ch;

    const nameEl = document.createElement('span');
    nameEl.className = 'sensor-name';
    nameEl.textContent = s.name || ('Sensor ' + sensorKey(s.dev, s.ch));

    const valEl = document.createElement('span');
    valEl.className = 'sensor-value';
    valEl.id = 'sv-' + sensorKey(s.dev, s.ch);
    valEl.textContent = '–';

    const barTrack = document.createElement('div');
    barTrack.className = 'sensor-bar-track';
    const barFill = document.createElement('div');
    barFill.className = 'sensor-bar-fill';
    barFill.id = 'sb-' + sensorKey(s.dev, s.ch);
    barTrack.appendChild(barFill);

    card.appendChild(nameEl);
    card.appendChild(valEl);
    card.appendChild(barTrack);
    card.addEventListener('click', () => selectSensor(s));
    grid.appendChild(card);
  });

  if (_config.sensors.length > 0 && _selectedSensor === null) {
    selectSensor(_config.sensors[0]);
  }
}

function selectSensor(sensor) {
  _selectedSensor = sensor;

  document.querySelectorAll('.sensor-card').forEach(card => {
    const match = card.dataset.dev == sensor.dev && card.dataset.ch == sensor.ch;
    card.classList.toggle('selected', match);
  });

  $('chart-moisture-title').textContent =
    'Bodenfeuchte – ' + (sensor.name || sensorKey(sensor.dev, sensor.ch));

  updateCharts();
}

function updateSensorCards(channels) {
  const map = {};
  channels.forEach(c => { map[sensorKey(c.dev, c.ch)] = c; });

  _config.sensors.forEach(s => {
    const key = sensorKey(s.dev, s.ch);
    const valEl = $('sv-' + key);
    const barEl = $('sb-' + key);
    if (!valEl) return;
    const c = map[key];
    const card = valEl.closest('.sensor-card');

    if (!c) {
      valEl.textContent = '–';
      if (barEl) { barEl.style.width = '0%'; barEl.className = 'sensor-bar-fill'; }
      card && card.classList.remove('sensor-err', 'sensor-warn');
    } else if (c.status === 'err') {
      valEl.textContent = 'Sensorfehler';
      if (barEl) { barEl.style.width = '0%'; barEl.className = 'sensor-bar-fill sensor-bar-err'; }
      card && card.classList.add('sensor-err');
      card && card.classList.remove('sensor-warn');
    } else {
      const pct = c.moisture_pct != null ? c.moisture_pct : null;
      valEl.textContent = pct != null ? pct.toFixed(1) + ' %' : '–';
      card && card.classList.remove('sensor-err');

      if (barEl) {
        const w = pct != null ? Math.min(100, Math.max(0, pct)).toFixed(1) + '%' : '0%';
        barEl.style.width = w;
        const min = _config.thresholds.soil_moisture_min_percent;
        const warn = min != null && pct != null && pct < min;
        barEl.className = 'sensor-bar-fill ' + (warn ? 'sensor-bar-warn' : 'sensor-bar-ok');
        card && card.classList.toggle('sensor-warn', warn);
      }
    }
  });
}

// ── Header stats ──────────────────────────────────────────────────────────────
function fmt(val, unit, decimals = 1) {
  return val != null ? val.toFixed(decimals) + ' ' + unit : '–';
}

function updateHeader(data) {
  $('air-temp').textContent = fmt(data.air_temp_c, '°C');
  $('soil-temp').textContent = fmt(data.soil_temp_c, '°C');

  const pct = data.battery_percent;
  $('battery-pct').textContent = pct != null ? pct.toFixed(0) + ' %' : '–';
  $('battery-voltage').textContent = data.battery_voltage != null
    ? data.battery_voltage.toFixed(2) + ' V' : '';

  const bar = $('battery-bar');
  if (pct != null) {
    bar.style.width = Math.min(100, Math.max(0, pct)).toFixed(1) + '%';
    bar.className = 'batt-fill ' + (pct < 20 ? 'batt-low' : pct < 50 ? 'batt-mid' : 'batt-ok');
  } else {
    bar.style.width = '0%';
    bar.className = 'batt-fill';
  }

  $('source').textContent = data.source || '–';
  $('last-ts').textContent = data.ts ? new Date(data.ts).toLocaleString('de-AT') : '–';
}

// ── Latest poll ───────────────────────────────────────────────────────────────
async function pollLatest() {
  try {
    const data = await apiFetch('/api/latest');
    hideBanner();
    updateHeader(data);
    updateSensorCards(data.channels || []);
  } catch (err) {
    if (err.status === 404) {
      showBanner('Warte auf erste Messung …', false);
    } else {
      showBanner('Verbindungsfehler – bitte Seite neu laden.', true);
    }
  }
}

// ── Time-axis helpers ─────────────────────────────────────────────────────────

// Formats a numeric epoch-ms tick value for the x-axis label.
function tickLabel(val) {
  const d = new Date(val);
  if (_timeMinutes <= 360) {
    return d.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString('de-AT', { day: '2-digit', month: '2-digit' }) + ' ' +
         d.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' });
}

// Converts API rows to {x: epochMs, y: value} points.
function toPoints(rows, getValue) {
  return rows.map(r => ({ x: new Date(r.ts).getTime(), y: getValue(r) }));
}

// Inserts a single null-y sentinel between consecutive points whose time gap
// exceeds thresholdMs so that Chart.js (spanGaps:false) draws a break.
function injectGapNulls(points, thresholdMs) {
  if (points.length < 2) return points;
  const result = [points[0]];
  for (let i = 1; i < points.length; i++) {
    if (points[i].x - points[i - 1].x > thresholdMs) {
      result.push({ x: (points[i].x + points[i - 1].x) / 2, y: null });
    }
    result.push(points[i]);
  }
  return result;
}

// ── Charts ────────────────────────────────────────────────────────────────────

function xScaleOpts() {
  return {
    type: 'linear',
    ticks: {
      maxTicksLimit: 6,
      color: '#9ca3af',
      maxRotation: 0,
      callback: tickLabel,
    },
    grid: { color: '#374151' },
  };
}

function yScaleOpts(extraOpts) {
  return {
    ticks: { color: '#9ca3af' },
    grid: { color: '#374151' },
    ...extraOpts,
  };
}

function makeDataset(label, color, fill = true) {
  return {
    label,
    data: [],
    borderColor: color,
    backgroundColor: color + '33',
    borderWidth: 2,
    pointRadius: 2,
    tension: 0.3,
    fill,
    spanGaps: false,
  };
}

function makeLineChart(canvasId, datasets, yExtra, legendDisplay = false) {
  return new Chart($(canvasId), {
    type: 'line',
    data: { datasets },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      plugins: {
        legend: {
          display: legendDisplay,
          labels: { color: '#9ca3af', boxWidth: 14 },
        },
      },
      scales: {
        x: xScaleOpts(),
        y: yScaleOpts(yExtra),
      },
    },
  });
}

function initCharts() {
  _charts.moisture = makeLineChart(
    'chart-moisture',
    [makeDataset('Feuchte %', '#34d399')],
    { min: 0, max: 100 },
  );

  _charts.temp = makeLineChart(
    'chart-temp',
    [
      makeDataset('Lufttemp.', '#f97316', false),
      makeDataset('Bodentemp.', '#60a5fa', false),
    ],
    {},
    true,
  );

  _charts.battery = makeLineChart(
    'chart-battery',
    [makeDataset('Batterie %', '#a78bfa')],
    { min: 0, max: 100 },
  );
}

async function updateCharts() {
  if (!_charts.moisture) return;

  try {
    const rows = await apiFetch('/api/history?minutes=' + _timeMinutes + '&max_points=' + MAX_POINTS);

    // Mirror the backend formula: bucket_secs = floor(minutes*60 / max_points) + 1
    const bucketMs = (Math.floor(_timeMinutes * 60 / MAX_POINTS) + 1) * 1000;
    const gapMs = 2 * bucketMs;

    // Pin x-axis to the chosen window so "24 h" always spans exactly 24 hours.
    const nowMs = Date.now();
    const minMs = nowMs - _timeMinutes * 60 * 1000;
    for (const chart of Object.values(_charts)) {
      if (chart) {
        chart.options.scales.x.min = minMs;
        chart.options.scales.x.max = nowMs;
      }
    }

    // Temperature (two datasets, same x values)
    _charts.temp.data.datasets[0].data =
      injectGapNulls(toPoints(rows, r => r.air_temp_c), gapMs);
    _charts.temp.data.datasets[1].data =
      injectGapNulls(toPoints(rows, r => r.soil_temp_c), gapMs);
    _charts.temp.update('none');

    // Battery
    _charts.battery.data.datasets[0].data =
      injectGapNulls(toPoints(rows, r => r.battery_percent), gapMs);
    _charts.battery.update('none');

    // Moisture – selected sensor only
    if (_selectedSensor) {
      const key = sensorKey(_selectedSensor.dev, _selectedSensor.ch);
      const pts = toPoints(rows, r => {
        const ch = (r.channels || []).find(c => sensorKey(c.dev, c.ch) === key);
        return ch ? ch.moisture_pct : null;
      });
      _charts.moisture.data.datasets[0].data = injectGapNulls(pts, gapMs);
    } else {
      _charts.moisture.data.datasets[0].data = [];
    }
    _charts.moisture.update('none');
  } catch {
    // Keep last data on network error – do not clear charts.
  }
}

// ── Time selector ─────────────────────────────────────────────────────────────
function initTimeSelector() {
  $('time-selector').addEventListener('click', e => {
    const btn = e.target.closest('.time-btn');
    if (!btn) return;
    document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _timeMinutes = parseInt(btn.dataset.minutes, 10);
    updateCharts();
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  await loadConfig();
  buildSensorGrid();
  initTimeSelector();
  initCharts();
  await pollLatest();
  await updateCharts();

  setInterval(pollLatest, 2000);
  setInterval(updateCharts, 10000);
}

document.addEventListener('DOMContentLoaded', init);
