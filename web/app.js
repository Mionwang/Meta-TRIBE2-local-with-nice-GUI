'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const dropZone = $('#dropZone');
const fileInput = $('#fileInput');
const jobPanel = $('#jobPanel');
const results = $('#results');
const video = $('#reelVideo');
const audio = $('#sourceAudio');
const textInput = $('#textInput');
const allowed = new Set(['mp4','mov','mkv','webm','avi','wav','mp3','flac','ogg','m4a','png','jpg','jpeg','webp','bmp','txt']);
const KIND_LABEL = {video: 'Video', audio: 'Audio', image: 'Image', text: 'Text'};

const state = {
  activeJob: null,
  busy: false,          // true from the moment a request is sent, closes the double-submit gap
  jobStartedAt: null,
  charts: [],
  activeMedia: null,
  currentResult: null,
  library: [],
  libraryKind: '',
  libraryExpanded: false,
};

/* ---------------- storage helpers (never let storage break the app) ---------------- */
const store = {
  get(area, key) { try { return window[area].getItem(key); } catch (_) { return null; } },
  set(area, key, value) { try { window[area].setItem(key, value); } catch (_) { /* ignore */ } },
  del(area, key) { try { window[area].removeItem(key); } catch (_) { /* ignore */ } },
};

/* ---------------- formatting ---------------- */
function fmtTime(value) {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return '—';
  if (n < 60) return `${n.toFixed(n % 1 ? 1 : 0)}s`;
  const m = Math.floor(n / 60);
  const s = Math.floor(n % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}
function fmtScore(value) {
  const n = Number(value);
  return value == null || !Number.isFinite(n) ? '—' : n.toFixed(0);
}
function clock(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600), m = Math.floor(total / 60) % 60, s = total % 60;
  const mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}
function fmtDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso || '';
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  const time = date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  if (sameDay) return `Today ${time}`;
  return `${date.toLocaleDateString([], {day: 'numeric', month: 'short'})} ${time}`;
}

async function readJson(response) {
  // A server crash can return HTML; don't surface "Unexpected token <" to the user.
  try { return await response.json(); } catch (_) { return {}; }
}

let toastTimer = null;
function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 2600);
}

/* ---------------- theme ---------------- */
let palette = {};
function readPalette() {
  const css = getComputedStyle(document.documentElement);
  const names = ['grid','tick','valley','surface','text-3','line-strong','accent',
    'c-attention','c-orienting','c-sustained','c-visual','c-auditory','c-cognitive','c-semantic','c-self','c-value'];
  palette = Object.fromEntries(names.map(n => [n, css.getPropertyValue(`--${n}`).trim()]));
  palette.font = getComputedStyle(document.body).fontFamily;
}
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('meta[name="theme-color"]').content = theme === 'light' ? '#f6f6f4' : '#0b0c0e';
  store.set('localStorage', 'tribeTheme', theme);
  readPalette();
  state.charts.forEach(chart => chart.draw());
}
$('#themeToggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'));
readPalette();

function withAlpha(color, alpha) {
  const hex = color.replace('#', '');
  if (!/^[0-9a-f]{6}$/i.test(hex)) return color;
  const n = parseInt(hex, 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${alpha})`;
}

/* ---------------- composer ---------------- */
function selectTab(which) {
  const isText = which === 'text';
  $('#tabFile').classList.toggle('active', !isText);
  $('#tabText').classList.toggle('active', isText);
  $('#tabFile').setAttribute('aria-selected', String(!isText));
  $('#tabText').setAttribute('aria-selected', String(isText));
  $('#filePane').classList.toggle('hidden', isText);
  $('#textPane').classList.toggle('hidden', !isText);
  if (isText) textInput.focus();
}
$('#tabFile').addEventListener('click', () => selectTab('file'));
$('#tabText').addEventListener('click', () => selectTab('text'));

function updateCharCount() {
  $('#charCount').textContent = `${textInput.value.length.toLocaleString()} / 10,000`;
}
textInput.addEventListener('input', () => { updateCharCount(); store.set('sessionStorage', 'tribeDraft', textInput.value); });
const draft = store.get('sessionStorage', 'tribeDraft');
if (draft) { textInput.value = draft; updateCharCount(); }

/* ---------------- job panel ---------------- */
function setJobMode(mode) {
  jobPanel.classList.toggle('is-error', mode === 'error');
  jobPanel.classList.toggle('is-idle', mode === 'cancelled');
  $('#cancelJob').classList.toggle('hidden', mode !== 'running');
  $('#dismissJob').classList.toggle('hidden', mode === 'running');
  $('#jobEyebrow').textContent = {running: 'Analyzing', error: 'Needs attention', cancelled: 'Cancelled'}[mode];
}

function showJob(name, stage, progress, log = [], mode = 'running') {
  jobPanel.classList.remove('hidden');
  setJobMode(mode);
  $('#jobName').textContent = name || 'Your input';
  $('#jobMessage').textContent = stage;
  $('#progressFill').style.width = `${Math.max(4, Math.min(progress, 100))}%`;
  $$('#stepList li').forEach((li, i, all) => {
    const at = Number(li.dataset.at);
    const next = all[i + 1] ? Number(all[i + 1].dataset.at) : 101;
    li.classList.toggle('done', progress >= next);
    li.classList.toggle('now', mode === 'running' && progress >= at && progress < next);
  });
  const logEl = $('#jobLog');
  const nearBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 30;
  logEl.textContent = log.join('\n');
  if (nearBottom) logEl.scrollTop = logEl.scrollHeight;
  tickClock();
}

function tickClock() {
  if (state.jobStartedAt && state.activeJob) $('#elapsedClock').textContent = clock(Date.now() - state.jobStartedAt);
}
setInterval(tickClock, 1000);

function showError(message, name = 'Could not analyze this input') {
  showJob(name, message, 100, [], 'error');
  jobPanel.scrollIntoView({behavior: 'smooth', block: 'center'});
}

function endJob() {
  state.activeJob = null;
  state.busy = false;
  store.del('sessionStorage', 'tribeJob');
  refreshStatus();
}

async function upload(file, pastedText = '') {
  if (state.busy || state.activeJob) { toast('An analysis is already running. Cancel it or wait for it to finish.'); return; }
  const extension = file ? (file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '') : '';
  if ((!file && !pastedText.trim()) || (file && !allowed.has(extension))) {
    showError(file ? `.${extension || '?'} files aren't supported. Use video, audio, image or TXT.` : 'Paste some text first.');
    return;
  }
  if (file && file.size > 1024 ** 3) { showError('The file is larger than 1 GB. Try a shorter or compressed export.'); return; }
  state.busy = true;
  state.jobStartedAt = Date.now();
  showJob(file?.name || 'Pasted text', 'Sending to the local analyzer…', 4);
  jobPanel.scrollIntoView({behavior: 'smooth', block: 'center'});
  try {
    const form = new FormData();
    if (file) form.append('file', file);
    else form.append('text', pastedText.trim());
    const response = await fetch('/api/analyze', {method: 'POST', body: form});
    const payload = await readJson(response);
    if (!response.ok) throw new Error(payload.error || `Upload failed (${response.status}).`);
    state.activeJob = payload.job_id;
    store.set('sessionStorage', 'tribeJob', state.activeJob);
    refreshStatus();
    await pollJob(state.activeJob);
  } catch (error) {
    showError(error.message || 'Could not send this input to the analyzer.', file?.name || 'Pasted text');
    endJob();
  }
}

async function pollJob(jobId) {
  if (jobId !== state.activeJob) return;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {cache: 'no-store'});
    if (!response.ok) throw new Error('The analysis session ended (the server may have restarted). Try again.');
    const job = await response.json();
    state.busy = true;
    if (job.created_ms) state.jobStartedAt = job.created_ms;
    if (job.status === 'cancelled') {
      showJob(job.name, 'Analysis cancelled.', job.progress, job.log || [], 'cancelled');
      endJob();
      return;
    }
    if (job.status === 'error') {
      showJob(job.name, job.error || 'Check the technical log below.', job.progress, job.log || [], 'error');
      endJob();
      return;
    }
    showJob(job.name, job.status === 'queued' ? 'Waiting for the GPU…' : job.stage, job.progress, job.log || []);
    if (job.status === 'done') {
      const took = (job.finished_ms || Date.now()) - (job.started_ms || job.created_ms || state.jobStartedAt);
      endJob();
      await loadResult(job.result_id);
      $('#resultTiming').textContent = `Completed in ${clock(took)}`;
      $('#resultTiming').classList.remove('hidden');
      jobPanel.classList.add('hidden');
      store.del('sessionStorage', 'tribeDraft');
      await loadLibrary();
      return;
    }
    setTimeout(() => pollJob(jobId), 900);
  } catch (error) {
    showError(error.message);
    endJob();
  }
}

$('#cancelJob').addEventListener('click', async () => {
  const jobId = state.activeJob;
  if (!jobId) return;
  $('#cancelJob').disabled = true;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {method: 'POST'});
    if (!response.ok) toast((await readJson(response)).error || 'Could not cancel.');
  } finally {
    $('#cancelJob').disabled = false;
  }
});
$('#dismissJob').addEventListener('click', () => jobPanel.classList.add('hidden'));

/* ---------------- charts ---------------- */
const CHARTS = [
  {canvas: '#attentionChart', fill: true, valleys: true, series: [
    {key: 'attention', label: 'Attention proxy', color: 'c-attention', width: 2.4},
    {key: 'orienting_attention', label: 'Orienting', color: 'c-orienting'},
    {key: 'sustained_attention', label: 'Sustained', color: 'c-sustained'},
  ]},
  {canvas: '#sensoryChart', series: [
    {key: 'visual_engagement', label: 'Visual', color: 'c-visual', kinds: ['video', 'image']},
    {key: 'auditory_engagement', label: 'Auditory', color: 'c-auditory', kinds: ['video', 'audio', 'text']},
  ]},
  {canvas: '#cognitiveChart', series: [
    {key: 'cognitive_engagement', label: 'Cognitive', color: 'c-cognitive'},
    {key: 'semantic_load', label: 'Semantic', color: 'c-semantic'},
    {key: 'self_relevance', label: 'Self-relevance', color: 'c-self'},
    {key: 'virality_proxy', label: 'Value (virality proxy)', color: 'c-value', dashed: true, off: true,
     title: 'Uncalibrated value-region curve. Experimental only.'},
  ]},
];

function createChart(canvas, rows, series, options = {}) {
  const wrap = canvas.parentElement;
  const tooltip = $('.chart-tooltip', wrap);
  const ctx = canvas.getContext('2d');
  const margin = {left: 34, right: 10, top: 12, bottom: 26};
  const firstTime = Number(rows[0]?.time ?? 0);
  const lastTime = Number(rows[rows.length - 1]?.time ?? firstTime + 1);
  const span = Math.max(1, lastTime - firstTime);
  let hover = -1;
  let size = {w: 0, h: 0, plotW: 0, plotH: 0};
  const xAt = t => margin.left + (Number(t) - firstTime) / span * size.plotW;
  const yAt = v => margin.top + (100 - Math.max(0, Math.min(100, Number(v)))) / 100 * size.plotH;
  const visible = () => series.filter(s => !s.off);

  function path(key) {
    ctx.beginPath();
    rows.forEach((row, i) => { const x = xAt(row.time), y = yAt(row[key]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  }

  function draw() {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    const w = Math.max(rect.width, 180), h = Math.max(rect.height, 140), dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    size = {w, h, plotW: w - margin.left - margin.right, plotH: h - margin.top - margin.bottom};
    ctx.clearRect(0, 0, w, h);

    if (options.valleys?.length) {
      ctx.fillStyle = palette.valley;
      for (const v of options.valleys) {
        const a = xAt(Math.max(firstTime, v.start_s)), b = xAt(Math.min(lastTime, v.end_s));
        ctx.fillRect(a, margin.top, Math.max(2, b - a), size.plotH);
      }
    }

    ctx.font = `10.5px ${palette.font}`;
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (const tick of [0, 50, 100]) {
      const y = Math.round(yAt(tick)) + .5;
      ctx.strokeStyle = palette.grid; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(w - margin.right, y); ctx.stroke();
      ctx.fillStyle = palette.tick; ctx.fillText(String(tick), margin.left - 8, y);
    }
    ctx.textBaseline = 'top';
    // Round time ticks (1, 2, 5, 10, 15, 30 s …) instead of odd fractions like 7.7s.
    const maxTicks = Math.max(2, Math.min(7, Math.floor(size.plotW / 80)));
    const step = [0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600].find(s => span / s <= maxTicks) || span;
    for (let t = Math.ceil(firstTime / step) * step; t <= lastTime + 1e-6; t += step) {
      const x = xAt(t);
      ctx.textAlign = x - margin.left < 12 ? 'left' : (w - margin.right - x < 12 ? 'right' : 'center');
      ctx.fillText(fmtTime(Math.round(t * 10) / 10), x, h - margin.bottom + 9);
    }

    const shown = visible();
    if (options.fill && rows.length > 1 && shown[0] === series[0]) {
      const color = palette[series[0].color];
      const grad = ctx.createLinearGradient(0, margin.top, 0, h - margin.bottom);
      grad.addColorStop(0, withAlpha(color, .22)); grad.addColorStop(1, withAlpha(color, 0));
      path(series[0].key);
      ctx.lineTo(xAt(rows[rows.length - 1].time), yAt(0)); ctx.lineTo(xAt(rows[0].time), yAt(0)); ctx.closePath();
      ctx.fillStyle = grad; ctx.fill();
    }
    // Draw secondary series first so the primary sits on top.
    [...shown].reverse().forEach(s => {
      path(s.key);
      ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      ctx.strokeStyle = palette[s.color];
      ctx.lineWidth = s.width || 1.6;
      ctx.globalAlpha = s.width ? 1 : .9;
      ctx.setLineDash(s.dashed ? [5, 4] : []);
      ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
    });

    const playhead = options.playhead && state.activeMedia && state.activeMedia.getAttribute('src') ? state.activeMedia.currentTime : null;
    if (playhead != null && playhead >= firstTime && playhead <= lastTime + 1) {
      const x = Math.round(xAt(Math.min(playhead, lastTime))) + .5;
      ctx.strokeStyle = palette.accent; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, margin.top - 4); ctx.lineTo(x, h - margin.bottom); ctx.stroke();
      ctx.fillStyle = palette.accent;
      ctx.beginPath(); ctx.moveTo(x - 4, margin.top - 8); ctx.lineTo(x + 4, margin.top - 8); ctx.lineTo(x, margin.top - 3); ctx.closePath(); ctx.fill();
    }
    if (hover >= 0 && rows[hover]) {
      const x = Math.round(xAt(rows[hover].time)) + .5;
      ctx.strokeStyle = palette['line-strong']; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, margin.top); ctx.lineTo(x, h - margin.bottom); ctx.stroke(); ctx.setLineDash([]);
      shown.forEach(s => {
        ctx.beginPath(); ctx.arc(x, yAt(rows[hover][s.key]), 3.6, 0, Math.PI * 2);
        ctx.fillStyle = palette[s.color]; ctx.fill();
        ctx.strokeStyle = palette.surface; ctx.lineWidth = 1.6; ctx.stroke();
      });
    }
  }

  function nearest(clientX) {
    const rect = canvas.getBoundingClientRect();
    const position = Math.max(0, Math.min(1, (clientX - rect.left - margin.left) / Math.max(1, size.plotW)));
    const target = firstTime + position * span;
    let chosen = 0, distance = Infinity;
    rows.forEach((row, i) => { const d = Math.abs(Number(row.time) - target); if (d < distance) { distance = d; chosen = i; } });
    return chosen;
  }

  function showTip(clientX, clientY) {
    hover = nearest(clientX);
    draw();
    const row = rows[hover];
    tooltip.replaceChildren();
    const head = document.createElement('div'); head.className = 'tooltip-time'; head.textContent = fmtTime(row.time);
    tooltip.appendChild(head);
    visible().forEach(s => {
      const line = document.createElement('div'); line.className = 'tooltip-row';
      const label = document.createElement('span');
      const dot = document.createElement('i'); dot.style.setProperty('--swatch', palette[s.color]);
      label.append(dot, s.label);
      const value = document.createElement('b'); value.textContent = fmtScore(row[s.key]);
      line.append(label, value); tooltip.appendChild(line);
    });
    tooltip.classList.remove('hidden');
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left, y = clientY - rect.top;
    const left = x + 16 + tooltip.offsetWidth > size.w ? x - tooltip.offsetWidth - 16 : x + 16;
    tooltip.style.left = `${Math.max(4, left)}px`;
    tooltip.style.top = `${Math.max(4, Math.min(y - 20, size.h - tooltip.offsetHeight - 4))}px`;
  }
  function hideTip() { hover = -1; tooltip.classList.add('hidden'); draw(); }

  canvas.addEventListener('pointermove', e => showTip(e.clientX, e.clientY));
  canvas.addEventListener('pointerleave', hideTip);
  canvas.addEventListener('click', e => seek(Number(rows[nearest(e.clientX)].time)));
  const observer = new ResizeObserver(() => draw());
  observer.observe(wrap);
  draw();
  return {draw, series, disconnect: () => observer.disconnect()};
}

function buildLegend(index, chart) {
  const legend = $(`.legend[data-chart="${index}"]`);
  legend.replaceChildren();
  chart.series.forEach(s => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = s.dashed ? 'dashed' : '';
    button.setAttribute('aria-pressed', String(!s.off));
    button.title = s.title || `Show or hide ${s.label}`;
    const swatch = document.createElement('i'); swatch.style.setProperty('--swatch', `var(--${s.color})`);
    button.append(swatch, s.label);
    button.addEventListener('click', () => {
      if (!s.off && chart.series.filter(x => !x.off).length === 1) { toast('At least one series stays visible.'); return; }
      s.off = !s.off;
      button.setAttribute('aria-pressed', String(!s.off));
      store.set('localStorage', `tribeSeries:${s.key}`, s.off ? 'off' : 'on');
      chart.draw();
    });
    legend.appendChild(button);
  });
}

let drawQueued = false;
function redrawCharts() {
  if (drawQueued) return;
  drawQueued = true;
  requestAnimationFrame(() => { drawQueued = false; state.charts.forEach(c => c.draw()); updateMediaTime(); });
}

function seek(time) {
  const media = state.activeMedia;
  if (!media || !media.getAttribute('src')) { toast('No playable preview for this input.'); return; }
  media.currentTime = Math.max(0, time);
  redrawCharts();
}

function updateMediaTime() {
  const media = state.activeMedia;
  $('#mediaTime').textContent = media && media.getAttribute('src') && Number.isFinite(media.duration)
    ? `${fmtTime(media.currentTime)} / ${fmtTime(media.duration)}` : '';
}

/* ---------------- results ---------------- */
function stat(label, value, unit, sub, options = {}) {
  const card = document.createElement('div');
  card.className = `stat${options.lead ? ' lead-stat' : ''}`;
  const l = document.createElement('span'); l.className = 'label'; l.textContent = label;
  const v = document.createElement('span'); v.className = `value${options.textValue ? ' text-value' : ''}`; v.textContent = value;
  if (unit) { const u = document.createElement('span'); u.className = 'unit'; u.textContent = unit; v.appendChild(u); }
  card.append(l, v);
  if (options.meter != null && Number.isFinite(Number(options.meter))) {
    const meter = document.createElement('div'); meter.className = 'meter';
    const fill = document.createElement('i'); fill.style.width = `${Math.max(0, Math.min(100, options.meter))}%`;
    meter.appendChild(fill); card.appendChild(meter);
  }
  const s = document.createElement('span'); s.className = 'sub'; s.textContent = sub;
  card.appendChild(s);
  return card;
}

function renderStats(metrics, kind, rows) {
  const grid = $('#statGrid');
  const duration = rows.length ? Number(rows[rows.length - 1].time) + Number(metrics.time_resolution_s || 1) : null;
  if (kind === 'image') {
    grid.replaceChildren(
      stat('Input', 'Still image', '', 'Shown as a static visual stimulus', {lead: true, textValue: true}),
      stat('Hold time', '6', 's', 'Artificial display duration'),
      stat('Resolution', String(metrics.time_resolution_s || 1), 's', 'Model prediction step'),
      stat('Pathway', 'Visual', '', 'No motion or audio supplied', {textValue: true}),
    );
    return;
  }
  const weak = metrics.weak_sections?.[0];
  grid.replaceChildren(
    stat('Relative start', fmtScore(metrics.hook_strength), '/100', 'First 3 s, vs. the rest of this input', {lead: true, meter: metrics.hook_strength}),
    stat('Later response', fmtScore(metrics.sustained_attention), metrics.sustained_attention == null ? '' : '/100', 'After 3 s, vs. the rest of this input', {meter: metrics.sustained_attention}),
    stat('Weakest section', weak ? `${fmtTime(weak.start_s)}–${fmtTime(weak.end_s)}` : '—', '', 'Lowest attention-proxy span', {textValue: true}),
    stat('Length · volatility', duration ? fmtTime(duration) : '—', '', `${metrics.attention_volatility_z_per_step ?? '—'} z change per step`, {textValue: true}),
  );
}

function insightRow(container, main, side, seekTime) {
  const row = document.createElement(seekTime != null ? 'button' : 'div');
  row.className = 'insight-row';
  if (seekTime != null) { row.type = 'button'; row.title = 'Jump to this moment'; row.addEventListener('click', () => { seek(seekTime); state.activeMedia?.scrollIntoView({behavior: 'smooth', block: 'center'}); }); }
  const title = document.createElement('strong'); title.textContent = main;
  const detail = document.createElement('span'); detail.textContent = side;
  row.append(title, detail);
  container.appendChild(row);
}
function emptyNote(container, text) {
  const p = document.createElement('p'); p.className = 'insight-empty'; p.textContent = text; container.appendChild(p);
}

function mergePeaks(peaks, step) {
  const sorted = [...peaks].sort((a, b) => a.time_s - b.time_s);
  const ranges = [];
  for (const p of sorted) {
    const last = ranges[ranges.length - 1];
    if (last && p.time_s - last.end <= step + 1e-6) { last.end = p.time_s; last.best = Math.max(last.best, p.within_clip_index); }
    else ranges.push({start: p.time_s, end: p.time_s, best: p.within_clip_index});
  }
  return ranges.sort((a, b) => b.best - a.best);
}

function renderInsights(metrics) {
  const weakList = $('#weakList'), recoveryList = $('#recoveryList'), peakList = $('#peakList');
  [weakList, recoveryList, peakList].forEach(el => el.replaceChildren());
  const weak = metrics.weak_sections || [];
  const recoveries = metrics.recovery_events || [];
  const step = Number(metrics.time_resolution_s || 1);
  const peaks = mergePeaks(metrics.major_peaks || [], step);
  if (!weak.length) emptyNote(weakList, 'No clear weak section detected.');
  weak.forEach(w => insightRow(weakList, `${fmtTime(w.start_s)}–${fmtTime(w.end_s)}`, `index ${fmtScore(w.mean_within_clip_index)}`, w.start_s));
  if (!recoveries.length) emptyNote(recoveryList, 'No strong recovery at 1-second resolution.');
  recoveries.forEach(r => insightRow(recoveryList, fmtTime(r.time_s), `+${fmtScore(r.gain_index_points)} from ${fmtTime(r.from_valley_s)}`, r.time_s));
  if (!peaks.length) emptyNote(peakList, 'No distinct peak detected.');
  peaks.forEach(p => insightRow(peakList, p.start === p.end ? fmtTime(p.start) : `${fmtTime(p.start)}–${fmtTime(p.end + step)}`, `max ${fmtScore(p.best)}`, p.start));
}

function setLink(id, href) {
  const link = $(id);
  link.classList.toggle('hidden', !href);
  if (href) link.href = href; else link.removeAttribute('href');
}

async function loadResult(resultId, {scroll = true} = {}) {
  let data;
  try {
    const response = await fetch(`/api/results/${encodeURIComponent(resultId)}`, {cache: 'no-store'});
    data = await readJson(response);
    if (!response.ok) throw new Error(data.error || 'Could not read the saved result.');
  } catch (error) {
    toast(error.message);
    return;
  }
  const metrics = data.metrics || {};
  const kind = data.kind || 'video';
  const rows = data.timeline || [];
  state.currentResult = resultId;
  if (location.hash !== `#${resultId}`) history.replaceState(null, '', `#${encodeURIComponent(resultId)}`);

  $('#kindBadge').textContent = KIND_LABEL[kind] || 'Input';
  $('#resultName').textContent = resultId === 'test_reel' ? 'Demo · test_reel.mp4' : (data.name || resultId);
  document.title = `${$('#resultName').textContent} · TRIBE Response Lab`;
  $('#resultTiming').classList.add('hidden');
  $('#resultIntro').textContent = data.explanation || 'Predicted cortical response from the local model.';
  $('#timelineTitle').textContent = kind === 'image' ? 'Static image response' : 'Response timeline';
  $('#sensoryTitle').textContent = kind === 'image' ? 'Visual response' : (kind === 'audio' || kind === 'text') ? 'Auditory response' : 'Visual & auditory';
  $('#timelineHint').classList.toggle('hidden', kind === 'image');
  $('#chartNote').textContent = kind === 'image'
    ? 'A static image held for 6 seconds. Curve variation comes from model context, not changing content.'
    : 'Shaded spans are the weakest sections relative to this input. The index is a within-input rank, not a retention percentage.';
  $('#methodNote').textContent = 'TRIBE v2 predicts cortical activity. These curves are experimental neural proxies ranked within this input, not measured attention, retention or virality.';
  $('#insightGrid').classList.toggle('hidden', kind === 'image');
  renderStats(metrics, kind, rows);
  if (kind !== 'image') renderInsights(metrics);
  setLink('#reportLink', data.files?.['report.html']);
  setLink('#csvLink', data.files?.['attention_timeline.csv']);
  setLink('#jsonLink', data.files?.['metrics.json']);
  setLink('#plotLink', data.files?.['attention_plot.png']);

  // media
  const sourceImage = $('#sourceImage'), sourceText = $('#sourceText'), wrap = $('#videoWrap');
  [video, audio, sourceImage, sourceText, $('#noVideo')].forEach(el => el.classList.add('hidden'));
  video.pause(); audio.pause();
  video.removeAttribute('src'); audio.removeAttribute('src'); sourceImage.removeAttribute('src');
  video.load(); audio.load();
  wrap.classList.remove('audio-only');
  wrap.appendChild(audio);
  state.activeMedia = null;
  $('#sourceTitle').textContent = {video: 'Watch alongside', audio: 'Listen alongside', image: 'Your image', text: 'Your text, read aloud'}[kind] || 'Your input';
  $('#sourceNote').textContent = kind === 'image' ? '' : 'Click any chart or insight to jump to that moment.';
  const showMissing = () => { [video, audio, sourceImage].forEach(el => el.classList.add('hidden')); wrap.classList.remove('audio-only'); $('#noVideo').classList.remove('hidden'); state.activeMedia = null; redrawCharts(); };
  if (kind === 'video' && data.preview_url) {
    video.src = data.preview_url; video.classList.remove('hidden'); state.activeMedia = video;
    video.onerror = showMissing;
  } else if (kind === 'audio' && data.preview_url) {
    audio.src = data.preview_url; audio.classList.remove('hidden'); wrap.classList.add('audio-only'); state.activeMedia = audio;
    audio.onerror = showMissing;
  } else if (kind === 'image' && data.preview_url) {
    sourceImage.src = data.preview_url; sourceImage.classList.remove('hidden');
    sourceImage.onerror = showMissing;
  } else if (kind === 'text') {
    sourceText.textContent = data.text_preview || 'Text preview unavailable.';
    sourceText.classList.remove('hidden');
    if (data.speech_url) { audio.src = data.speech_url; audio.classList.remove('hidden'); state.activeMedia = audio; audio.onerror = () => audio.classList.add('hidden'); }
  } else {
    $('#noVideo').classList.remove('hidden');
  }

  // charts
  state.charts.forEach(c => c.disconnect());
  state.charts = [];
  results.classList.remove('hidden');
  CHARTS.forEach((def, index) => {
    const series = def.series
      .filter(s => !s.kinds || s.kinds.includes(kind))
      .filter(s => rows.length && s.key in rows[0])
      .map(s => {
        const saved = store.get('localStorage', `tribeSeries:${s.key}`);
        return {...s, off: saved ? saved === 'off' : !!s.off};
      });
    if (series.length && series.every(s => s.off)) series[0].off = false;
    const chart = createChart($(def.canvas), rows, series, {
      fill: def.fill, valleys: def.valleys && kind !== 'image' ? metrics.weak_sections : null, playhead: kind !== 'image',
    });
    buildLegend(index, chart);
    state.charts.push(chart);
  });
  $$('.lib-item').forEach(el => el.classList.toggle('current', el.dataset.id === resultId));
  if (scroll) results.scrollIntoView({behavior: 'smooth', block: 'start'});
}

['timeupdate', 'seeked', 'loadedmetadata'].forEach(evt => [video, audio].forEach(m => m.addEventListener(evt, redrawCharts)));

/* ---------------- library ---------------- */
const ICONS = {
  video: '<svg viewBox="0 0 16 16"><rect x="1.5" y="3.5" width="9" height="9" rx="2"/><path d="m10.5 7 4-2.5v7l-4-2.5"/></svg>',
  audio: '<svg viewBox="0 0 16 16"><path d="M2 8h1.5M5 5v6M8 2.5v11M11 5.5v5M14 7v2"/></svg>',
  image: '<svg viewBox="0 0 16 16"><rect x="1.5" y="2.5" width="13" height="11" rx="2"/><circle cx="5.5" cy="6.5" r="1.3"/><path d="m2 12 4-3.5 3 2.5 2-1.5 3.5 2.5"/></svg>',
  text: '<svg viewBox="0 0 16 16"><path d="M3 3.5h10M3 6.5h10M3 9.5h7M3 12.5h5"/></svg>',
};

async function loadLibrary() {
  try {
    const response = await fetch('/api/recent?all=1', {cache: 'no-store'});
    if (!response.ok) return;
    state.library = await response.json();
    renderLibrary();
  } catch (_) { /* the library is optional; uploads still work */ }
}

function renderLibrary() {
  const query = $('#librarySearch').value.trim().toLowerCase();
  const items = state.library.filter(item =>
    (!state.libraryKind || (item.kind || 'video') === state.libraryKind) &&
    (!query || `${item.name} ${item.id}`.toLowerCase().includes(query)));
  $('#recentSection').classList.toggle('hidden', !state.library.length);
  const limit = state.libraryExpanded || query ? items.length : 9;
  const list = $('#recentList');
  list.replaceChildren();
  items.slice(0, limit).forEach(item => {
    const kind = item.kind || 'video';
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'lib-item'; button.dataset.id = item.id;
    button.classList.toggle('current', item.id === state.currentResult);
    const icon = document.createElement('span'); icon.className = 'lib-icon'; icon.innerHTML = ICONS[kind] || ICONS.video;
    const body = document.createElement('span');
    const title = document.createElement('strong'); title.textContent = item.demo ? 'Demo · test_reel.mp4' : item.name; title.title = title.textContent;
    const sub = document.createElement('small'); sub.textContent = `${KIND_LABEL[kind] || kind} · ${fmtDate(item.updated)}`;
    body.append(title, sub);
    const scoreEl = document.createElement('span'); scoreEl.className = 'lib-score';
    if (kind !== 'image' && item.hook != null) {
      scoreEl.textContent = fmtScore(item.hook);
      const label = document.createElement('small'); label.textContent = 'START'; label.style.display = 'block'; label.style.color = 'var(--text-3)';
      scoreEl.appendChild(label);
      scoreEl.title = 'Relative start (first 3 s)';
    }
    button.append(icon, body, scoreEl);
    button.addEventListener('click', () => loadResult(item.id));
    list.appendChild(button);
  });
  if (!items.length) {
    const p = document.createElement('p'); p.className = 'library-empty'; p.textContent = 'No analyses match.'; list.appendChild(p);
  }
  const more = $('#showAll');
  more.classList.toggle('hidden', !!query || items.length <= 9);
  more.textContent = state.libraryExpanded ? 'Show fewer' : `Show all ${items.length}`;
}

$('#librarySearch').addEventListener('input', renderLibrary);
$('#showAll').addEventListener('click', () => { state.libraryExpanded = !state.libraryExpanded; renderLibrary(); });
$$('#kindFilter .seg-btn').forEach(button => button.addEventListener('click', () => {
  state.libraryKind = button.dataset.kind;
  $$('#kindFilter .seg-btn').forEach(b => b.classList.toggle('active', b === button));
  renderLibrary();
}));

/* ---------------- status (GPU) ---------------- */
async function refreshStatus() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (!response.ok) return;
    const info = await response.json();
    const chip = $('#gpuChip');
    if (info.gpu) {
      const used = (info.gpu.mem_used_mb / 1024).toFixed(1), total = (info.gpu.mem_total_mb / 1024).toFixed(0);
      $('#gpuText').textContent = `${info.gpu.name} · ${used}/${total} GB`;
      chip.title = `GPU utilisation ${info.gpu.util}% · memory in use ${used} of ${total} GB`;
      chip.classList.remove('hidden');
    } else {
      chip.classList.add('hidden');
    }
    chip.classList.toggle('busy', info.active_jobs > 0);
  } catch (_) { /* ignore */ }
}
setInterval(() => { if (!document.hidden) refreshStatus(); }, 5000);

/* ---------------- input events ---------------- */
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } });
fileInput.addEventListener('change', e => { const f = e.target.files?.[0]; fileInput.value = ''; if (f) upload(f); });
$('#analyzeText').addEventListener('click', () => upload(null, textInput.value));
textInput.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); upload(null, textInput.value); } });

// Drop anywhere on the page.
let dragDepth = 0;
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
window.addEventListener('dragenter', e => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth++; $('#dropOverlay').classList.remove('hidden'); dropZone.classList.add('dragging'); });
window.addEventListener('dragover', e => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener('dragleave', e => { if (!hasFiles(e)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) { $('#dropOverlay').classList.add('hidden'); dropZone.classList.remove('dragging'); } });
window.addEventListener('drop', e => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth = 0;
  $('#dropOverlay').classList.add('hidden'); dropZone.classList.remove('dragging');
  const file = e.dataTransfer.files?.[0];
  if (file) upload(file);
});

// Keyboard: Space play/pause, arrows step 1 s (Shift = 5 s), T theme.
document.addEventListener('keydown', e => {
  const tag = e.target.tagName;
  if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'VIDEO', 'AUDIO'].includes(tag) || e.target.isContentEditable || e.ctrlKey || e.metaKey || e.altKey) return;
  const media = state.activeMedia;
  if (e.key === 't' || e.key === 'T') { $('#themeToggle').click(); return; }
  if (!media || !media.getAttribute('src') || results.classList.contains('hidden')) return;
  if (e.key === ' ') { e.preventDefault(); media.paused ? media.play().catch(() => {}) : media.pause(); }
  else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    e.preventDefault();
    const step = (e.shiftKey ? 5 : 1) * (e.key === 'ArrowRight' ? 1 : -1);
    seek(Math.min(Number.isFinite(media.duration) ? media.duration : Infinity, media.currentTime + step));
  }
});

/* ---------------- boot ---------------- */
refreshStatus();
loadLibrary().then(() => {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash && /^[A-Za-z0-9_.-]+$/.test(hash)) loadResult(hash, {scroll: false});
});
const savedJob = store.get('sessionStorage', 'tribeJob');
if (savedJob) { state.activeJob = savedJob; state.busy = true; pollJob(savedJob); }
