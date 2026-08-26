'use strict';
/* SwathKeeper dashboard — vanilla JS, no framework, no CDN, no build step.
 *
 * THE RULE THIS FILE OBEYS: every figure it renders is computed here, in the browser, from the
 * artifacts under data/ (copies of the committed evidence) — or is a verbatim line from a gate that
 * ran on the host. Nothing is typed in. Where a number has a denominator, the denominator is shown.
 * Where the page derives a headline the project also gates on host-side (trees imaged, canopy-grade,
 * median lift), it recomputes it AND compares itself with that gate's committed output, and says so
 * in red if the two disagree. See scripts/build_dashboard_data.py for the data pipeline.
 *
 * RENDERING IS THREE LAYERS, because a full redraw per animation frame was visibly laggy:
 *   STATIC  (offscreen) — field, cells, lanes, trees, the whole flown path, event markers, the CPA
 *                         crosshair. Repainted only when the flight, the layer toggles or the
 *                         canvas size change.
 *   TRAIL   (offscreen) — the "flown so far" line, EXTENDED by the few segments each frame adds
 *                         rather than restroked from tick 0. Cleared and rebuilt only on a backward
 *                         seek.
 *   LIVE    (on screen) — composite the two, then the handful of moving things: drone, birds,
 *                         latched setpoint, event pulses, hover highlight.
 * Per-frame DOM writes are held to the scrubber thumb and the timeline cursor; text, table
 * highlighting and the encounter card only touch the DOM when the TICK changes, not every frame.
 *
 * WHAT MOVES SMOOTHLY AND WHAT DOES NOT — this is an honesty boundary, not a style choice:
 *   * the DRONE is interpolated between logged telemetry samples. Telemetry samples a continuous
 *     trajectory, so reading between two samples is a fair visual reading. Labelled on the view.
 *   * the BIRDS are NOT interpolated. They are stepped between applied `set_pose` poses, ~0.44 s
 *     apart, because that is literally how Gazebo moved them (ADR-012) and it is what the safety
 *     gate measures the closest approach against. Smoothing them would put the bird somewhere the
 *     render never showed it — and, at the CPA instant, somewhere that contradicts the measured
 *     0.0067 m. A fading trail of recent poses gives the eye the motion instead.
 */

// ------------------------------------------------------------------ tiny DOM helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
function el(tag, cls, txt) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt !== undefined && txt !== null) n.textContent = String(txt);
  return n;
}
const sgn = (v, d = 4) => (v === null || v === undefined) ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(d);
const pct = (n, d) => d ? (100 * n / d).toFixed(2) + ' %' : 'EVIDENCE INSUFFICIENT (no denominator)';

// ------------------------------------------------------------------ state
const S = {
  data: null, flightId: null, clipId: null,
  idx: 0, playing: false, speed: 1, lastFrame: 0,
  layers: { grid: true, lanes: true, trees: true, path: true, events: true, birds: true },
  trim: true,             // open on the airborne window; the whole log stays reachable
  ndviMode: 'ndvi',
  hover: null, tour: -1, view: 'replay',
};

// ------------------------------------------------------------------ load
async function getJSON(p) { const r = await fetch(p); if (!r.ok) throw new Error(p + ': HTTP ' + r.status); return r.json(); }
async function getText(p) { const r = await fetch(p); if (!r.ok) throw new Error(p + ': HTTP ' + r.status); return r.text(); }

async function boot() {
  let d;
  try {
    const [manifest, field, verdicts, clipIndex] = await Promise.all(
      ['data/manifest.json', 'data/field.json', 'data/verdicts.json', 'data/clips/index.json'].map(getJSON));
    d = { manifest, field, verdicts, clips: {}, flights: {} };
    await Promise.all(Object.entries(verdicts.flights).map(async ([stem, v]) => {
      const log = await getJSON('data/' + v.log);
      const marker = v.marker ? await getText('data/' + v.marker) : null;
      const truth = (v.schema_version >= 2) ? await getJSON('data/truth/' + stem + '.json').catch(() => null) : null;
      d.flights[stem] = { stem, v, log, marker, truth };
    }));
    await Promise.all(Object.entries(clipIndex.clips).map(async ([name, c]) => {
      const [heatmap, meta, treeCheck] = await Promise.all([c.heatmap, c.meta, c.tree_check].map(p => getJSON('data/' + p)));
      d.clips[name] = { name, heatmap, meta, treeCheck };
    }));
  } catch (err) {
    return bootError(err);
  }
  S.data = d;
  S.flightId = d.manifest.flights[d.manifest.flights.length - 1];
  S.clipId = d.manifest.clips[0];
  $('#boot').hidden = true;
  $('#app').hidden = false;
  wire();
  renderAll();
}

function bootError(err) {
  const b = $('#boot');
  b.className = 'boot';
  b.textContent = '';
  const isFile = location.protocol === 'file:';
  b.appendChild(el('h2', null, isFile ? 'This page needs a web server — one command.' : 'Could not load the evidence files.'));
  if (isFile) {
    b.appendChild(el('p', null,
      'You opened it straight off disk (file://), and browsers refuse fetch() on file:// URLs for security. '
      + 'The page is fully static — it just needs something to serve the files. From the repository root:'));
    b.appendChild(el('pre', null, 'python3 -m http.server 8000\n# then open http://localhost:8000/dashboard/'));
    b.appendChild(el('p', 'note', 'Nothing is uploaded anywhere; the server is local and reads the files you already have.'));
  } else {
    b.appendChild(el('p', null, 'The page loaded but an artifact under data/ did not. If you are running from a clone, rebuild it:'));
    b.appendChild(el('pre', null, 'python3 scripts/build_dashboard_data.py'));
  }
  b.appendChild(el('p', 'note', 'Error: ' + err.message));
}

// ------------------------------------------------------------------ per-flight derived model
function flight() { return S.data.flights[S.flightId]; }

/** The policy parameters a flight ACTUALLY flew, and where they were read from. Schema-2 logs
 *  record them in the run block; schema-1 logs only ever wrote them into each maneuver's debug
 *  dict. Falling back to today's defaults would draw a historical flight with today's threat
 *  cylinder, so the provenance is carried and shown. */
function flightParams(log) {
  if (log.run && log.run.policy_params) return { params: log.run.policy_params, from: 'run.policy_params (schema-2 run block)' };
  const mv = log.events.find(e => e.kind === 'maneuver' && e.debug && e.debug.params);
  if (mv) return { params: mv.debug.params, from: `maneuver debug.params at tick ${mv.tick} (schema-1 log: no run block)` };
  return { params: S.data.field.policy_params_defaults, from: 'PolicyParams DEFAULTS — this log recorded none, so these are not what it flew' };
}

/** Everything about one GUIDED encounter that the page can compute from the log itself.
 *  The headline is deliberately NOT "total distance moved": over the 2026-08-25 encounter the
 *  vehicle travelled 3.95 m, essentially all of it the cruise it was already doing. What the dodge
 *  bought is the component ALONG the commanded direction, and that is the number worth showing. */
function encounterFacts(m, g) {
  const a = Math.max(0, g.from - 1), b = Math.min(m.n - 1, g.to - 1);
  const p0 = m.path[a], p1 = m.path[b];
  // The commanded point: the first LATCH of the encounter, or — on the schema-1 logs, which predate
  // the latch — the first maneuver's own setpoint. Same thing either way: the point the executor
  // actually commanded on the tick the encounter opened.
  const cmd = m.events.find(e => ['latch', 'relatch', 'maneuver'].includes(e.kind)
    && e.tick >= g.from && e.tick <= g.to && Array.isArray(e.setpoint_enu));
  const dx = p1[0] - p0[0], dy = p1[1] - p0[1];
  const total = Math.hypot(dx, dy);
  let along = null, across = null, commanded = null;
  if (cmd) {
    const ux = cmd.setpoint_enu[0] - p0[0], uy = cmd.setpoint_enu[1] - p0[1];
    commanded = Math.hypot(ux, uy);
    if (commanded > 0) {
      along = (dx * ux + dy * uy) / commanded;
      across = Math.abs(-dx * uy + dy * ux) / commanded;
    }
  }
  return {
    from: g.from, to: g.to, trigger: g.trigger,
    dur_s: m.stamps ? m.stamps[b] - m.stamps[a] : null,
    ticks: g.to - g.from,
    total_m: total, along_m: along, across_m: across, commanded_m: commanded,
    setpoint: cmd ? cmd.setpoint_enu : null,
    maneuvers: m.events.filter(e => e.kind === 'maneuver' && e.tick >= g.from && e.tick <= g.to).length,
  };
}

function model(f) {
  if (f._m) return f._m;
  const log = f.log;
  const path = log.flown_path_enu.filter(p => Array.isArray(p) && p.length >= 3);
  const stamps = (log.run && Array.isArray(log.run.tick_stamp_sim_s)) ? log.run.tick_stamp_sim_s : null;
  const events = log.events.filter(e => e.kind !== 'proceed');
  const loopKinds = new Set(['detection', 'takeover', 'latch', 'relatch', 'maneuver', 'hold', 'resume', 'gate_reject', 'divert_audit_summary']);
  const ledger = log.coverage_ledger;
  const covered = ledger.filter(r => r.status === 'covered').length;
  const debt = ledger.filter(r => r.status === 'debt').length;
  // Real playback rate: schema-2 logs carry measured sim seconds, so ticks/second is measured.
  // Schema-1 logs carry no time axis at all — 5 Hz is the node's NOMINAL control rate, labelled as
  // such everywhere it is used, and never printed as if it were seconds this flight measured.
  let ticksPerSec = 5.0, spanSim = null;
  if (stamps && stamps.length > 1) { spanSim = stamps[stamps.length - 1] - stamps[0]; ticksPerSec = (stamps.length - 1) / spanSim; }
  const guided = [];
  let open = null;
  for (const e of events) {
    if (e.kind === 'takeover') open = { from: e.tick, to: null };
    else if (e.kind === 'resume' && open) { open.to = e.tick; open.trigger = e.trigger; guided.push(open); open = null; }
  }
  if (open) { open.to = path.length; open.trigger = null; open.unterminated = true; guided.push(open); }
  const m = {
    path, stamps, events, ledger, covered, debt, guided, ticksPerSec, spanSim,
    loopEvents: events.filter(e => loopKinds.has(e.kind)),
    debtEvents: events.filter(e => e.kind === 'debt'),
    n: path.length, air: f.v.airborne,
    ...flightParams(log),
  };
  m.encounters = guided.map(g => encounterFacts(m, g));
  m.seekable = m.loopEvents.filter(e => e.kind !== 'divert_audit_summary').map(e => e.tick - 1);
  f._m = m;
  return m;
}

const tickOf = idx => Math.floor(idx) + 1;
function posAt(m, idx) {
  const i = Math.max(0, Math.min(m.n - 1, Math.floor(idx)));
  const j = Math.min(m.n - 1, i + 1);
  const t = idx - i;
  const a = m.path[i], b = m.path[j];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}
function clockLabel(m, idx) {
  const tk = tickOf(idx);
  if (m.stamps) return `t_sim ${m.stamps[Math.min(m.stamps.length - 1, tk - 1)].toFixed(3)} s · tick ${tk}/${m.n}`;
  return `tick ${tk}/${m.n} — ticks, not seconds`;
}
/** The window playback runs over: the airborne one unless the viewer asked for the whole log. */
const playRange = m => S.trim && m.air && m.air.found
  ? [m.air.first_motion_tick - 1, m.air.last_motion_tick - 1] : [0, m.n - 1];

// ------------------------------------------------------------------ view transform + primitives
function makeView(w, h) {
  const poly = S.data.field.polygon_m, pad = 6;
  const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
  const bb = { x0: Math.min(...xs) - pad, y0: Math.min(...ys) - pad, x1: Math.max(...xs) + pad, y1: Math.max(...ys) + pad };
  const s = w / (bb.x1 - bb.x0);
  return {
    w, h, s, bb,
    P: (x, y) => [(x - bb.x0) * s, (bb.y1 - y) * s],
    inv: (px, py) => [bb.x0 + px / s, bb.y1 - py / s],
  };
}
const ASPECT = () => {
  const poly = S.data.field.polygon_m, pad = 6;
  const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
  return (Math.max(...xs) - Math.min(...xs) + 2 * pad) / (Math.max(...ys) - Math.min(...ys) + 2 * pad);
};
function line(c, V, pts, color, width, dash) {
  if (pts.length < 2) return;
  c.save(); c.strokeStyle = color; c.lineWidth = width; c.lineJoin = 'round'; c.lineCap = 'round';
  if (dash) c.setLineDash(dash);
  c.beginPath();
  for (let i = 0; i < pts.length; i++) { const [x, y] = V.P(pts[i][0], pts[i][1]); i ? c.lineTo(x, y) : c.moveTo(x, y); }
  c.stroke(); c.restore();
}
function disc(c, V, x, y, r, fill, stroke) {
  const [px, py] = V.P(x, y);
  c.beginPath(); c.arc(px, py, r, 0, 6.2832);
  if (fill) { c.fillStyle = fill; c.fill(); }
  if (stroke) { c.strokeStyle = stroke; c.lineWidth = 1.2; c.stroke(); }
}
function ring(c, V, x, y, rm, stroke, dash, width) {
  const [px, py] = V.P(x, y);
  c.save(); c.strokeStyle = stroke; c.lineWidth = width || 1; if (dash) c.setLineDash(dash);
  c.beginPath(); c.arc(px, py, rm * V.s, 0, 6.2832); c.stroke(); c.restore();
}

// ------------------------------------------------------------------ layered renderer
const R = { w: 0, h: 0, dpr: 1, V: null, static: null, trail: null, key: '', trailIdx: -1 };
const EVCOLOR = {
  detection: '#fbbf24', takeover: '#a78bfa', latch: '#f472b6', relatch: '#f472b6',
  maneuver: '#34d399', hold: '#fbbf24', resume: '#38bdf8', gate_reject: '#f87171',
  divert_audit_summary: '#8fa0b3', debt: '#8fa0b3',
};
const evColor = e => (e.kind === 'maneuver' && e.verdict !== 'accepted') ? '#f87171' : (EVCOLOR[e.kind] || '#8fa0b3');
const off = (w, h, dpr) => {
  const c = document.createElement('canvas');
  c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
  c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
  return c;
};

function ensureLayers() {
  const cv = $('#map');
  const w = Math.max(320, cv.clientWidth || 900), h = Math.round(w / ASPECT());
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const key = [S.flightId, w, h, dpr, JSON.stringify(S.layers)].join('|');
  if (key === R.key && R.static) return false;
  if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  cv.style.height = h + 'px';
  R.w = w; R.h = h; R.dpr = dpr; R.V = makeView(w, h); R.key = key;
  R.static = off(w, h, dpr); R.trail = off(w, h, dpr); R.trailIdx = -1;
  paintStatic(R.static.getContext('2d'), R.V);
  return true;
}

/** Everything that does not move: drawn once per (flight, size, layer set). */
function paintStatic(c, V) {
  const F = S.data.field, m = model(flight());
  c.clearRect(0, 0, V.w, V.h);
  c.save(); c.beginPath();
  F.polygon_m.forEach((p, i) => { const [x, y] = V.P(p[0], p[1]); i ? c.lineTo(x, y) : c.moveTo(x, y); });
  c.closePath();
  const g = c.createLinearGradient(0, 0, 0, V.h);
  g.addColorStop(0, '#101c17'); g.addColorStop(1, '#0c1512');
  c.fillStyle = g; c.fill();
  c.strokeStyle = '#31473b'; c.lineWidth = 1.5; c.stroke(); c.restore();

  if (S.layers.grid) {
    c.save(); c.strokeStyle = 'rgba(255,255,255,0.04)'; c.lineWidth = 1;
    const cs = F.cell_size_m, bb = V.bb;
    for (let x = 0; x <= 200; x += cs) {
      if (x < bb.x0 || x > bb.x1) continue;
      const [px, y0] = V.P(x, bb.y0), [, y1] = V.P(x, bb.y1);
      c.beginPath(); c.moveTo(px, y0); c.lineTo(px, y1); c.stroke();
    }
    for (let y = 0; y <= 200; y += cs) {
      if (y < bb.y0 || y > bb.y1) continue;
      const [x0, py] = V.P(bb.x0, y), [x1] = V.P(bb.x1, y);
      c.beginPath(); c.moveTo(x0, py); c.lineTo(x1, py); c.stroke();
    }
    c.restore();
  }
  if (S.layers.lanes) line(c, V, F.missions.boustrophedon.xy_m, 'rgba(120,200,255,0.26)', 1.5, [7, 5]);
  if (S.layers.trees) {
    for (const t of F.trees) {
      ring(c, V, t.pos_m[0], t.pos_m[1], t.obstacle_radius_m, 'rgba(74,222,128,0.35)', [3, 3]);
      disc(c, V, t.pos_m[0], t.pos_m[1], Math.max(2.5, t.canopy_radius_m * V.s), 'rgba(74,222,128,0.5)');
    }
  }
  if (S.layers.path) line(c, V, m.path, 'rgba(56,189,248,0.20)', 1.5);
  for (const gd of m.guided) line(c, V, m.path.slice(gd.from - 1, gd.to), 'rgba(244,114,182,0.75)', 3);
  if (S.layers.events) {
    for (const e of m.loopEvents) {
      if (e.kind === 'divert_audit_summary') continue;
      const p = eventXY(m, e);
      if (p) disc(c, V, p[0], p[1], e.kind === 'detection' ? 2.6 : 3.4, evColor(e), 'rgba(0,0,0,0.55)');
    }
  }
  const cpa = cpaMark(flight(), m);
  if (cpa) {
    const [px, py] = V.P(cpa.xy[0], cpa.xy[1]);
    c.save(); c.strokeStyle = '#f87171'; c.lineWidth = 1.6;
    c.beginPath(); c.arc(px, py, 11, 0, 6.2832); c.stroke();
    c.beginPath(); c.moveTo(px - 17, py); c.lineTo(px + 17, py); c.moveTo(px, py - 17); c.lineTo(px, py + 17); c.stroke();
    c.fillStyle = '#f87171'; c.font = '700 11px ui-monospace,monospace';
    c.fillText(`CPA ${cpa.value.toFixed(4)} m`, px + 19, py - 7); c.restore();
  }
}

/** The "flown so far" line, extended by the segments this frame added instead of restroked. */
function extendTrail(V, idx) {
  const m = model(flight()), c = R.trail.getContext('2d');
  const to = Math.floor(idx);
  if (to < R.trailIdx) { c.clearRect(0, 0, V.w, V.h); R.trailIdx = -1; }
  if (to <= R.trailIdx) return;
  const from = Math.max(0, R.trailIdx);
  c.save(); c.strokeStyle = '#38bdf8'; c.lineWidth = 2.2; c.lineJoin = 'round'; c.lineCap = 'round';
  c.beginPath();
  for (let i = from; i <= to; i++) { const [x, y] = V.P(m.path[i][0], m.path[i][1]); i === from ? c.moveTo(x, y) : c.lineTo(x, y); }
  c.stroke(); c.restore();
  R.trailIdx = to;
}

function eventXY(m, e) {
  if (e.kind === 'detection' && Array.isArray(e.position_enu)) return e.position_enu;
  return m.path[Math.min(m.n - 1, Math.max(0, e.tick - 1))];
}

function drawReplay() {
  const cv = $('#map');
  if (!cv || cv.clientWidth === 0) return;
  ensureLayers();
  const V = R.V, c = cv.getContext('2d'), f = flight(), m = model(f);
  c.setTransform(R.dpr, 0, 0, R.dpr, 0, 0);
  c.clearRect(0, 0, V.w, V.h);
  extendTrail(V, S.idx);
  c.drawImage(R.static, 0, 0, V.w, V.h);
  c.drawImage(R.trail, 0, 0, V.w, V.h);

  const p = posAt(m, S.idx);
  const i0 = Math.floor(S.idx);
  if (S.idx > i0) line(c, V, [m.path[i0], p], '#38bdf8', 2.2);   // the fractional tip

  // the latched dodge setpoint currently commanded
  const sp = S.layers.events ? activeSetpoint(m, tickOf(S.idx)) : null;
  if (sp) {
    line(c, V, [p, sp], 'rgba(244,114,182,0.8)', 1.3, [4, 4]);
    const [px, py] = V.P(sp[0], sp[1]);
    c.save(); c.strokeStyle = '#f472b6'; c.lineWidth = 2;
    c.beginPath(); c.moveTo(px - 6, py - 6); c.lineTo(px + 6, py + 6);
    c.moveTo(px + 6, py - 6); c.lineTo(px - 6, py + 6); c.stroke(); c.restore();
  }

  // event pulses: a marker flares as playback crosses its tick
  if (S.layers.events) {
    for (const e of m.loopEvents) {
      if (e.kind === 'divert_audit_summary') continue;
      const d = Math.abs(S.idx - (e.tick - 1));
      if (d > 12) continue;
      const k = 1 - d / 12, xy = eventXY(m, e);
      if (!xy) continue;
      c.save(); c.globalAlpha = 0.10 + 0.55 * k; c.strokeStyle = evColor(e); c.lineWidth = 2;
      const [px, py] = V.P(xy[0], xy[1]);
      c.beginPath(); c.arc(px, py, 5 + 16 * (1 - k), 0, 6.2832); c.stroke();
      c.restore();
    }
  }

  // birds — stepped applied poses, with a fading trail of the recent ones (never interpolated)
  if (S.layers.birds) {
    for (const b of birdsAt(f, m, S.idx)) {
      for (let k = 0; k < b.trail.length; k++) {
        c.save(); c.globalAlpha = 0.10 + 0.16 * (k / Math.max(1, b.trail.length));
        disc(c, V, b.trail[k][0], b.trail[k][1], 3.5, '#fbbf24'); c.restore();
      }
      ring(c, V, b.pos[0], b.pos[1], m.params.threat_radius_m, 'rgba(251,191,36,0.13)');
      disc(c, V, b.pos[0], b.pos[1], 5.5, b.estimate ? 'rgba(251,191,36,0.4)' : '#fbbf24', '#1a1206');
      const [px, py] = V.P(b.pos[0], b.pos[1]);
      c.save(); c.fillStyle = '#fbbf24'; c.font = '600 11px ui-monospace,monospace';
      c.fillText(`${b.id}  z ${b.pos[2].toFixed(2)} m`, px + 10, py + 3.5); c.restore();
    }
  }

  // drone
  const q = posAt(m, Math.min(m.n - 1, S.idx + 1));
  const ang = Math.atan2(-(q[1] - p[1]), q[0] - p[0]);
  const [px, py] = V.P(p[0], p[1]);
  c.save(); c.translate(px, py); c.rotate(ang);
  c.fillStyle = '#ffffff'; c.shadowColor = 'rgba(56,189,248,.9)'; c.shadowBlur = 10;
  c.beginPath(); c.moveTo(10, 0); c.lineTo(-6.5, 6); c.lineTo(-3.5, 0); c.lineTo(-6.5, -6); c.closePath(); c.fill();
  c.restore();
  c.save(); c.fillStyle = '#e8eff7'; c.font = '600 11px ui-monospace,monospace';
  c.fillText(`drone  z ${p[2].toFixed(2)} m`, px + 12, py - 9); c.restore();

  if (S.hover) {
    const [hx, hy] = V.P(S.hover.xy[0], S.hover.xy[1]);
    c.save(); c.strokeStyle = '#e8eff7'; c.lineWidth = 1.5; c.globalAlpha = .8;
    c.beginPath(); c.arc(hx, hy, 10, 0, 6.2832); c.stroke(); c.restore();
  }
}

function activeSetpoint(m, tick) {
  const g = m.guided.find(g => tick >= g.from && tick <= g.to);
  if (!g) return null;
  let sp = null;
  for (const e of m.events) {
    if (e.tick > tick || e.tick < g.from) continue;
    if ((e.kind === 'latch' || e.kind === 'relatch') && Array.isArray(e.setpoint_enu)) sp = e.setpoint_enu;
  }
  return sp;
}

/** Bird positions at the current instant. Ground truth where a track is bound — stepped at the
 *  instant each pose is CERTAINLY applied, the same rule the safety gate reads the track with.
 *  Otherwise only what the drone itself logged, on the ticks it logged it, labelled an estimate. */
function birdsAt(f, m, idx) {
  const tick = tickOf(idx);
  if (f.truth && f.truth.poses) {
    const t = m.stamps ? m.stamps[Math.min(m.stamps.length - 1, tick - 1)] : null;
    const span = f.truth.span_sim_s;
    if (t === null || !span || t < span[0] || t > span[1]) return [];
    return Object.entries(f.truth.poses).map(([id, rows]) => {
      let pos = f.truth.spawn_m[id]; const trail = [];
      for (const r of rows) {
        if (r[0] > t) break;
        trail.push(pos); pos = [r[1], r[2], r[3]];
      }
      return { id, pos, trail: trail.slice(-6), estimate: false };
    });
  }
  const out = [];
  for (const e of m.events) {
    if (e.kind === 'detection' && e.tick === tick && Array.isArray(e.position_enu)) {
      out.push({ id: (e.track_id || ('det@' + e.frame_id)) + ' (as logged)', pos: e.position_enu, trail: [], estimate: true });
    }
  }
  return out;
}

/** Where to draw the closest-approach marker, and the value the GATE measured there. */
function cpaMark(f, m) {
  const c = f.v.cpa;
  if (!c) return null;
  if (c.gt_cpa_m !== undefined && c.gt_cpa_m !== null && c.tick) {
    const p = m.path[Math.min(m.n - 1, c.tick - 1)];
    return { xy: [p[0], p[1]], value: c.gt_cpa_m, tick: c.tick };
  }
  if (c.cpa_m !== undefined && c.segment_index !== undefined) {
    const a = m.path[c.segment_index], b = m.path[c.segment_index + 1] || a;
    const [bx, by] = c.bird_xy_m;
    const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, ((bx - a[0]) * dx + (by - a[1]) * dy) / L2)) : 0;
    return { xy: [a[0] + t * dx, a[1] + t * dy], value: c.cpa_m, tick: c.segment_index + 1 };
  }
  return null;
}

// ------------------------------------------------------------------ altitude strip
const E = { static: null, w: 0, h: 0, dpr: 1, key: '', y0: 0, y1: 1 };
function ensureElev() {
  const cv = $('#elev');
  if (!cv || cv.clientWidth === 0) return false;
  const w = Math.max(320, cv.clientWidth), h = Math.max(120, Math.round(w * 0.19));
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const key = [S.flightId, w, h, dpr].join('|');
  if (key === E.key && E.static) return true;
  if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  cv.style.height = h + 'px';
  E.w = w; E.h = h; E.dpr = dpr; E.key = key; E.static = off(w, h, dpr);
  paintElev(E.static.getContext('2d'));
  return true;
}
const PADL = 46, PADR = 12, PADT = 12, PADB = 20;
const EX = (i, n) => PADL + (E.w - PADL - PADR) * (i / Math.max(1, n - 1));
const EY = z => PADT + (E.h - PADT - PADB) * (1 - (z - E.y0) / Math.max(1e-6, E.y1 - E.y0));

function paintElev(c) {
  const f = flight(), m = model(f);
  const zs = m.path.map(p => p[2]);
  let hi = Math.max(...zs), lo = 0;
  const birdZ = [];
  if (f.truth && f.truth.poses && m.stamps) {
    for (const rows of Object.values(f.truth.poses)) for (const r of rows) birdZ.push(r[3]);
  } else {
    for (const e of m.events) if (e.kind === 'detection' && e.position_enu) birdZ.push(e.position_enu[2]);
  }
  if (birdZ.length) { hi = Math.max(hi, ...birdZ); lo = Math.min(lo, ...birdZ); }
  E.y0 = Math.min(0, lo - 1); E.y1 = Math.ceil(hi + 2);

  c.clearRect(0, 0, E.w, E.h);
  c.fillStyle = '#080c11'; c.fillRect(0, 0, E.w, E.h);
  // axes
  c.save(); c.font = '10px ui-monospace,monospace'; c.fillStyle = '#5f7186'; c.strokeStyle = 'rgba(255,255,255,.05)';
  for (let z = 0; z <= E.y1; z += 5) {
    const y = EY(z);
    c.beginPath(); c.moveTo(PADL, y); c.lineTo(E.w - PADR, y); c.stroke();
    c.fillText(z + ' m', 8, y + 3.5);
  }
  c.restore();
  // the policy's own vertical threat band around the cruise altitude
  const cruise = m.params.cruise_alt_m, vt = m.params.vertical_threat_m;
  c.save(); c.fillStyle = 'rgba(251,191,36,0.055)';
  c.fillRect(PADL, EY(cruise + vt), E.w - PADL - PADR, EY(cruise - vt) - EY(cruise + vt));
  c.strokeStyle = 'rgba(251,191,36,0.22)'; c.setLineDash([4, 4]); c.lineWidth = 1;
  c.beginPath(); c.moveTo(PADL, EY(cruise + vt)); c.lineTo(E.w - PADR, EY(cruise + vt));
  c.moveTo(PADL, EY(cruise - vt)); c.lineTo(E.w - PADR, EY(cruise - vt)); c.stroke();
  c.fillStyle = 'rgba(251,191,36,0.5)'; c.setLineDash([]); c.font = '10px ui-monospace,monospace';
  c.fillText(`±${vt} m threat band`, PADL + 6, EY(cruise + vt) - 5);
  c.restore();
  // GUIDED windows
  for (const g of m.guided) {
    c.save(); c.fillStyle = 'rgba(244,114,182,0.13)';
    c.fillRect(EX(g.from - 1, m.n), PADT, Math.max(1.5, EX(g.to - 1, m.n) - EX(g.from - 1, m.n)), E.h - PADT - PADB);
    c.restore();
  }
  // bird altitude lines (stepped — that is how set_pose moved them)
  if (f.truth && f.truth.poses && m.stamps) {
    const t2i = t => {
      let lo2 = 0, hi2 = m.stamps.length - 1;
      while (lo2 < hi2) { const mid = (lo2 + hi2) >> 1; if (m.stamps[mid] < t) lo2 = mid + 1; else hi2 = mid; }
      return lo2;
    };
    for (const [id, rows] of Object.entries(f.truth.poses)) {
      const pts = rows.filter(r => r[0] >= m.stamps[0] && r[0] <= m.stamps[m.n - 1]);
      if (pts.length < 2) continue;
      c.save(); c.strokeStyle = 'rgba(251,191,36,0.65)'; c.lineWidth = 1.4; c.beginPath();
      pts.forEach((r, k) => { const x = EX(t2i(r[0]), m.n), y = EY(r[3]); k ? (c.lineTo(x, y)) : c.moveTo(x, y); });
      c.stroke();
      c.fillStyle = 'rgba(251,191,36,0.85)'; c.font = '600 9.5px ui-monospace,monospace';
      c.fillText(id, EX(t2i(pts[0][0]), m.n) + 3, EY(pts[0][3]) - 4);
      c.restore();
    }
  } else {
    for (const e of m.events) {
      if (e.kind !== 'detection' || !e.position_enu) continue;
      c.save(); c.fillStyle = 'rgba(251,191,36,0.8)';
      c.beginPath(); c.arc(EX(e.tick - 1, m.n), EY(e.position_enu[2]), 2, 0, 6.2832); c.fill(); c.restore();
    }
  }
  // drone altitude
  c.save(); c.strokeStyle = '#38bdf8'; c.lineWidth = 1.7; c.beginPath();
  for (let i = 0; i < m.n; i++) { const x = EX(i, m.n), y = EY(zs[i]); i ? c.lineTo(x, y) : c.moveTo(x, y); }
  c.stroke(); c.restore();
  // pre/post-flight shading
  if (m.air && m.air.found) {
    c.save(); c.fillStyle = 'rgba(0,0,0,0.45)';
    if (m.air.pre_flight_ticks) c.fillRect(PADL, PADT, EX(m.air.first_motion_tick - 1, m.n) - PADL, E.h - PADT - PADB);
    if (m.air.post_flight_ticks) {
      const x = EX(m.air.last_motion_tick - 1, m.n);
      c.fillRect(x, PADT, E.w - PADR - x, E.h - PADT - PADB);
    }
    c.restore();
  }
  // the CPA instant
  const cpa = cpaMark(f, m);
  if (cpa) {
    const x = EX(cpa.tick - 1, m.n);
    c.save(); c.strokeStyle = 'rgba(248,113,113,0.85)'; c.lineWidth = 1.3; c.setLineDash([3, 3]);
    c.beginPath(); c.moveTo(x, PADT); c.lineTo(x, E.h - PADB); c.stroke(); c.restore();
    const gt = f.v.cpa;
    if (gt && gt.vertical_sep_m !== undefined) {
      const yD = EY(gt.drone_z_m), yB = EY(gt.bird_z_m);
      c.save(); c.strokeStyle = '#f87171'; c.lineWidth = 2;
      c.beginPath(); c.moveTo(x, yD); c.lineTo(x, yB); c.stroke();
      c.fillStyle = '#f87171'; c.font = '700 10.5px ui-monospace,monospace';
      c.fillText(`${gt.vertical_sep_m.toFixed(2)} m vertical`, x + 6, (yD + yB) / 2 + 3);
      c.restore();
    }
  }
}
function drawElev() {
  if (!ensureElev()) return;
  const cv = $('#elev'), c = cv.getContext('2d'), m = model(flight());
  c.setTransform(E.dpr, 0, 0, E.dpr, 0, 0);
  c.clearRect(0, 0, E.w, E.h);
  c.drawImage(E.static, 0, 0, E.w, E.h);
  const x = EX(S.idx, m.n), p = posAt(m, S.idx);
  c.save(); c.strokeStyle = 'rgba(232,239,247,0.55)'; c.lineWidth = 1;
  c.beginPath(); c.moveTo(x, PADT); c.lineTo(x, E.h - PADB); c.stroke();
  c.fillStyle = '#e8eff7'; c.beginPath(); c.arc(x, EY(p[2]), 3.5, 0, 6.2832); c.fill(); c.restore();
}

/** Legends are DOM, so they are built once per flight — never inside the frame loop. */
function renderLegends() {
  const f = flight(), m = model(f);
  const put = (sel, items) => {
    const box = $(sel); box.innerHTML = '';
    for (const [col, kind, label] of items) {
      const s = el('span'); s.style.color = col;
      s.appendChild(el('i', kind === 'dot' ? 'dot' : ''));
      s.appendChild(el('span', 'dim', label));
      box.appendChild(s);
    }
  };
  put('#map-legend', [
    ['#38bdf8', 'line', 'flown so far'], ['rgba(56,189,248,0.35)', 'line', 'whole flown path'],
    ['#f472b6', 'line', 'GUIDED — the avoidance loop is flying'],
    ['#fbbf24', 'dot', f.truth && f.truth.poses
      ? 'bird — applied ground-truth pose, stepped (never interpolated)'
      : 'bird position AS LOGGED by the drone (an estimate)'],
    ['#4ade80', 'dot', 'surveyed tree + 2.0 m geofence'],
    ['rgba(120,200,255,0.5)', 'line', 'planned lanes'],
    ['#f87171', 'dot', 'closest approach'],
  ]);
  const gt = f.v.cpa && f.v.cpa.vertical_sep_m !== undefined;
  put('#elev-legend', [
    ['#38bdf8', 'line', 'drone altitude'],
    ['#fbbf24', gt ? 'line' : 'dot', gt ? 'bird altitude (applied ground truth)'
      : 'altitude of each logged detection (an estimate; this log has no bird ground truth)'],
    ['rgba(251,191,36,0.5)', 'line', `±${m.params.vertical_threat_m} m threat band around the ${m.params.cruise_alt_m} m cruise`],
    ['#f87171', 'line', gt ? 'closest approach — the vertical gap the top-down map cannot show'
      : 'closest approach (horizontal only: no ground truth to measure a vertical gap against)'],
    ['rgba(255,255,255,0.25)', 'dot', 'shaded = parked, outside the airborne window'],
  ]);
}

// ------------------------------------------------------------------ verdict header
function renderVerdict() {
  const f = flight(), v = f.v, box = $('#verdict');
  box.className = 'verdict v-' + v.verdict;
  box.innerHTML = '';
  const head = el('div');
  head.appendChild(el('span', 'badge', v.verdict === 'ACKNOWLEDGED' ? 'ACKNOWLEDGED SAFETY FINDING' : v.verdict));
  head.appendChild(el('span', 'dim', '  ' + v.stem + '  ·  schema '
    + (v.schema_version === null ? '1 (legacy, pre-run-block)' : v.schema_version)));
  box.appendChild(head);

  const c = v.cpa || {};
  let title, sub;
  if (c.gt_cpa_m !== undefined && c.gt_cpa_m !== null) {
    title = `Ground-truth closest approach ${c.gt_cpa_m.toFixed(4)} m to ${c.bird_id}, against a ${c.bar_m.toFixed(2)} m bar.`;
    sub = `Gated value ${c.gt_cpa_gated_m.toFixed(4)} m (= ${c.gt_cpa_m.toFixed(4)} − ${c.freeze_debit_m.toFixed(4)} m clock-freeze debit). `
      + `Tick ${c.tick}, t_sim ${c.t_sim_s} s, drone z ${c.drone_z_m.toFixed(2)} m, bird z ${c.bird_z_m.toFixed(2)} m, `
      + `vertical separation ${c.vertical_sep_m.toFixed(2)} m — inside the policy's ±${c.vertical_threat_m} m threat band.`;
  } else if (c.cpa_m !== undefined) {
    title = `Closest approach ${c.cpa_m.toFixed(4)} m to ${c.track_id}, against a ${c.bar_m.toFixed(2)} m bar.`;
    sub = c.basis;
  } else { title = 'No closest-approach evidence in this log.'; sub = ''; }
  box.appendChild(el('h3', null, title));
  if (sub) box.appendChild(el('p', 'headline', sub));
  if (v.verdict === 'INVALID') {
    box.appendChild(el('p', 'note',
      'This take was pre-registered in writing, before it flew, as allowed to fail its own gate — and it did. '
      + 'The marker file was written and the stem was deliberately NOT pinned as acknowledged, so the record '
      + 'stands INVALID (and CI red) until the flight is re-flown behind the open escape-geometry work. '
      + 'The loop detected, decided, latched and dodged on a bird nothing injected; the geometry still lost.'));
  } else if (v.verdict === 'ACKNOWLEDGED') {
    box.appendChild(el('p', 'note',
      'A reviewed, recorded breach: kept as history because it cannot be re-flown, and deliberately never called VALID. '
      + 'Acknowledgement takes two halves — the written finding beside the log AND the stem pinned in the gate '
      + '(a reviewed diff). Both are present for this log.'));
  }
  box.appendChild(el('p', 'note',
    `Acknowledgement takes two halves: written finding beside the log — ${f.marker ? 'PRESENT' : 'absent'}; `
    + `stem pinned in the gate's reviewed ACKNOWLEDGED_BREACH_STEMS — ${v.acknowledged_pin ? 'PINNED' : 'NOT pinned'}. `
    + 'Either half alone acknowledges nothing.'));

  const gl = el('ul', 'gatelines');
  for (const l of v.gate_messages) gl.appendChild(el('li', null, l));
  const dg = el('details');
  dg.appendChild(el('summary', null, `the safety gate's own output, verbatim (${v.gate})`));
  dg.appendChild(gl); box.appendChild(dg);
  if (f.marker) {
    const dm = el('details');
    dm.appendChild(el('summary', null, 'read the written safety finding (' + v.marker.split('/').pop() + ')'));
    dm.appendChild(el('pre', null, f.marker)); box.appendChild(dm);
  }
}

// ------------------------------------------------------------------ pickers + side panel
function renderPickers() {
  const p = $('#flight-picker'); p.innerHTML = '';
  for (const stem of S.data.manifest.flights) {
    const v = S.data.verdicts.flights[stem];
    const b = el('button');
    b.setAttribute('aria-pressed', String(stem === S.flightId));
    b.appendChild(el('span', null, stem.replace('live_flight_log_', '')));
    b.appendChild(el('span', 'pill v-' + v.verdict, v.verdict === 'ACKNOWLEDGED' ? 'ACK' : v.verdict));
    b.onclick = () => selectFlight(stem);
    p.appendChild(b);
  }
  const cp = $('#clip-picker'); cp.innerHTML = '';
  for (const name of S.data.manifest.clips) {
    const b = el('button', null, name.replace('real_flight_', ''));
    b.setAttribute('aria-pressed', String(name === S.clipId));
    b.onclick = () => { S.clipId = name; renderNdvi(); renderPickers(); };
    cp.appendChild(b);
  }
}
function selectFlight(stem) {
  S.flightId = stem; S.playing = false; $('#play').textContent = '▶';
  R.key = ''; E.key = '';
  renderAll();
}

function renderFacts() {
  const f = flight(), m = model(f), run = f.log.run;
  const box = $('#flight-facts'); box.innerHTML = '';
  const dl = el('dl');
  const row = (k, v, cls, act) => {
    const dt = el('dt', null, k), dd = el('dd', cls, v);
    if (act) { dt.className = 'clicky'; dd.className = (cls || '') + ' clicky'; dt.onclick = act; dd.onclick = act; }
    dl.appendChild(dt); dl.appendChild(dd);
  };
  row('coverage ledger', `${m.covered} covered / ${m.debt} debt`, m.debt ? '' : 'good',
    () => { S.ndviMode = 'coverage'; show('ndvi'); });
  row('ledger cells', `${m.ledger.length} / ${S.data.field.cells.length} grid cells`,
    m.ledger.length === S.data.field.cells.length ? '' : 'bad');
  row('flown path', `${m.n} points`);
  row('airborne window', m.air && m.air.found
    ? `ticks ${m.air.first_motion_tick}–${m.air.last_motion_tick} of ${m.n}` : 'not detected',
    '', () => seek((m.air ? m.air.first_motion_tick - 1 : 0)));
  row('time axis', m.stamps ? `${m.spanSim.toFixed(3)} s of sim time` : 'none (schema-1: ticks only)');
  const nk = k => m.events.filter(e => e.kind === k).length;
  row('avoidance events', String(m.loopEvents.length), '', () => show('events'));
  row('maneuvers accepted', String(nk('maneuver')), '', () => jumpToEncounter());
  row('setpoints refused', `${nk('gate_reject')} gate_reject`);
  row('holds (zero displacement)', String(nk('hold')));
  row('re-latches', String(nk('relatch')));
  if (run && run.detector && run.detector.counters) {
    const k = run.detector.counters;
    row('detector', run.detector.source, '', () => show('events'));
    row('detect rate', `${k.frames_detected_on} / ${k.ndvi_msgs_received} = ${pct(k.frames_detected_on, k.ndvi_msgs_received)}`,
      '', () => show('events'));
    row('frames with a box', `${k.frames_with_detection} (${k.boxes_total} boxes)`);
  }
  row('swath half-width this log used', `${f.log.swath_half_width_m} m`);
  row('camera-derived half-width', `${S.data.field.swath.camera_derived_half_width_m.toFixed(3)} m`);
  box.appendChild(dl);
  box.appendChild(el('p', 'note', S.data.field.swath.note));

  const L = $('#layers'); L.innerHTML = '';
  for (const [key, label] of [['grid', 'canonical 2.5 m cell grid'], ['lanes', 'planned mission lanes'],
  ['trees', 'surveyed trees + geofence'], ['path', 'whole flown path'], ['events', 'events + latched setpoint'],
  ['birds', 'birds']]) {
    const lab = el('label'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = S.layers[key];
    cb.onchange = () => { S.layers[key] = cb.checked; R.key = ''; requestRender(); };
    lab.appendChild(cb); lab.appendChild(el('span', null, label)); L.appendChild(lab);
  }
  const lab = el('label'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = !S.trim;
  cb.onchange = () => { S.trim = !cb.checked; renderTimeline(); requestRender(); };
  lab.appendChild(cb);
  lab.appendChild(el('span', null, m.air && m.air.found
    ? `include the ${m.air.pre_flight_ticks + m.air.post_flight_ticks} parked ticks`
    : 'include pre-flight'));
  L.appendChild(lab);

  $('#timebasis').textContent = (m.stamps
    ? `Time axis: absolute Gazebo sim seconds from run.tick_stamp_sim_s (${m.stamps.length} stamps, `
    + `${m.ticksPerSec.toFixed(2)} ticks/s measured). Playback runs at that measured rate.`
    : 'Time axis: NONE. This schema-1 log records tick indices only, so the scrubber is a tick index and '
    + 'playback runs at the node\'s NOMINAL 5 Hz control rate. Nothing on this view is a measured second.')
    + (m.air && m.air.found && (m.air.pre_flight_ticks || m.air.post_flight_ticks)
      ? ` Playback opens on the airborne window (${m.air.rule.split(';')[0]}); the ${m.air.pre_flight_ticks} parked `
      + `ticks before it and ${m.air.post_flight_ticks} after are hatched on the scrubber and still scrubbable.` : '')
    + ' The drone marker is interpolated between logged samples so the animation is smooth; birds are NOT '
    + 'interpolated (they step between applied set_pose poses, which is how the simulator moved them), and every '
    + 'number — clock, events, closest approach — is read at a logged tick.';
}

// ------------------------------------------------------------------ timeline + transport
function renderTimeline() {
  const f = flight(), m = model(f), tl = $('#timeline');
  tl.innerHTML = '';
  const pctOf = t => 100 * (t - 1) / m.n;
  if (m.air && m.air.found) {
    for (const [a, b] of [[1, m.air.first_motion_tick], [m.air.last_motion_tick, m.n + 1]]) {
      if (b <= a) continue;
      const d = el('div', 'band');
      d.style.cssText = `left:${pctOf(a)}%;width:${pctOf(b) - pctOf(a)}%;background:repeating-linear-gradient(`
        + `-45deg, rgba(255,255,255,.045) 0 5px, transparent 5px 10px)`;
      d.title = 'parked — outside the airborne window';
      tl.appendChild(d);
    }
  }
  for (const g of m.guided) {
    const d = el('div', 'band');
    d.style.cssText = `left:${pctOf(g.from)}%;width:${Math.max(0.4, pctOf(g.to) - pctOf(g.from))}%;`
      + 'background:rgba(244,114,182,0.18)';
    tl.appendChild(d);
  }
  for (const e of m.loopEvents) {
    if (e.kind === 'divert_audit_summary') continue;
    const t = el('div', 'tick');
    t.style.left = `calc(${pctOf(e.tick)}% - 1px)`;
    t.style.background = evColor(e);
    t.title = `tick ${e.tick} · ${e.kind}`;
    tl.appendChild(t);
  }
  const cpa = cpaMark(f, m);
  if (cpa) {
    const t = el('div', 'tick');
    t.style.cssText = `left:calc(${pctOf(cpa.tick)}% - 1px);background:#f87171;height:25px;width:2px;`;
    t.title = 'closest approach'; tl.appendChild(t);
    const lb = el('div', 'tllabel', 'CPA');
    lb.style.left = `${pctOf(cpa.tick)}%`; lb.style.color = '#f87171'; tl.appendChild(lb);
  }
  tl.appendChild(Object.assign(el('div', 'cursor'), { id: 'tl-cursor' }));
  tl.onclick = ev => { const r = tl.getBoundingClientRect(); seek(((ev.clientX - r.left) / r.width) * (m.n - 1)); };

  const sm = $('#scrubmarks'); sm.innerHTML = '';
  if (m.air && m.air.found) {
    for (const [a, b] of [[1, m.air.first_motion_tick], [m.air.last_motion_tick, m.n + 1]]) {
      if (b <= a) continue;
      const d = el('div', 'ground');
      d.style.cssText = `left:${pctOf(a)}%;width:${pctOf(b) - pctOf(a)}%`;
      sm.appendChild(d);
    }
  }
}

// ---- the frame loop: one rAF, coalesced; DOM text only when the TICK changes ----
let rafPending = false, lastTick = -1, lastEnc = null;
function requestRender() { if (!rafPending) { rafPending = true; requestAnimationFrame(frame); } }
function frame(ts) {
  rafPending = false;
  if (S.playing) {
    const m = model(flight()), [lo, hi] = playRange(m);
    const dt = S.lastFrame ? Math.min(0.25, (ts - S.lastFrame) / 1000) : 0;
    S.lastFrame = ts;
    let i = S.idx + dt * m.ticksPerSec * S.speed;
    if (i >= hi) { i = hi; stop(); }
    S.idx = Math.max(lo, i);
  }
  if (S.view === 'replay') { drawReplay(); drawElev(); paintHud(); }
  if (S.playing) requestRender();
}
function stop() { S.playing = false; S.lastFrame = 0; $('#play').textContent = '▶'; }
function seek(i) {
  const m = model(flight());
  S.idx = Math.max(0, Math.min(m.n - 1, i));
  requestRender();
  if (S.view !== 'replay') paintHud();
}
/** Per-frame DOM: two style writes. Everything textual is gated on the tick actually changing. */
function paintHud() {
  const m = model(flight());
  $('#scrub').value = String(S.idx);
  const cur = $('#tl-cursor');
  if (cur) cur.style.left = `${100 * S.idx / Math.max(1, m.n - 1)}%`;
  const tk = tickOf(S.idx);
  if (tk === lastTick) return;
  lastTick = tk;
  $('#clock').textContent = clockLabel(m, S.idx);
  highlightRow(tk);
  renderEncounterCard(m, tk);
}

/** The callout that makes the encounter legible: what was commanded, what was flown, what the gate
 *  measured. Every number computed from this log — including the dodge displacement, which is the
 *  component ALONG the commanded direction, not the distance the cruise carried the vehicle. */
function renderEncounterCard(m, tick) {
  const box = $('#encounter');
  const enc = m.encounters.find(e => tick >= e.from - 2 && tick <= e.to + 8);
  if (!enc) { if (lastEnc !== null) { box.hidden = true; lastEnc = null; } return; }
  if (lastEnc === enc.from) return;
  lastEnc = enc.from;
  const f = flight(), c = f.v.cpa || {};
  box.hidden = false; box.innerHTML = '';
  box.appendChild(el('h4', null, 'Encounter — the loop is flying the vehicle'));
  const p = el('p');
  const add = (t, cls) => p.appendChild(el('span', cls, t));
  add('Dodge commanded ');
  add(enc.commanded_m !== null ? `${enc.commanded_m.toFixed(2)} m` : '(no setpoint logged)', 'num');
  add(` lateral, ${enc.maneuvers} maneuver(s) over ticks ${enc.from}–${enc.to}`);
  add(enc.dur_s !== null ? ` (${enc.dur_s.toFixed(3)} s of GUIDED). ` : ` (${enc.ticks} ticks; this log has no time axis). `);
  if (enc.along_m === null) {
    add('This log records no commanded setpoint for the encounter, so how much of a dodge was flown cannot be measured from it.');
  } else {
    add('The vehicle moved ');
    add(`${enc.total_m.toFixed(2)} m`, 'num');
    add(' over that window: ');
    add(`${enc.along_m.toFixed(4)} m`, 'num');
    add(' of it along the commanded direction, ');
    add(`${enc.across_m.toFixed(2)} m`, 'num');
    add(' across it. ');
    // The qualifier is DERIVED from the ratio, never assumed — these three logs disagree wildly
    // about what the command path did, and a fixed sentence would be wrong on two of them.
    const frac = enc.along_m / enc.commanded_m;
    if (frac < 0) {
      add('That is NEGATIVE — the commanded point lay behind the vehicle\'s motion, so it ended this '
        + 'window farther from the setpoint than it started. Whether that is the plant or the command '
        + 'path is not decidable from a flight log; it took an offline point-mass replay to separate them.');
    } else if (frac < 0.05) {
      add(`That is ${(100 * frac).toFixed(1)} % of the command — effectively none of the commanded dodge `
        + 'had been flown by the time the window ended.');
    } else {
      add(`That is ${(100 * frac).toFixed(1)} % of the command.`);
    }
  }
  box.appendChild(p);
  if (c.gt_cpa_m !== undefined && c.gt_cpa_m !== null) {
    const q = el('p');
    q.appendChild(el('span', null, 'It passed '));
    q.appendChild(el('span', 'num', `${c.gt_cpa_m.toFixed(4)} m`));
    q.appendChild(el('span', null, ' horizontally and '));
    q.appendChild(el('span', 'num', `${c.vertical_sep_m.toFixed(2)} m`));
    q.appendChild(el('span', null, ` vertically from ${c.bird_id} — over the top of it, which a top-down map cannot show. `
      + `The altitude strip below can. This flight FAILED its safety gate for exactly this.`));
    box.appendChild(q);
  } else if (c.cpa_m !== undefined) {
    box.appendChild(el('p', null,
      `Closest approach on this encounter: ${c.cpa_m.toFixed(4)} m horizontally to ${c.track_id}, `
      + `against the policy's own ${c.bar_m.toFixed(2)} m bar. Recorded, acknowledged, never called a pass.`));
  }
  if (enc.trigger) box.appendChild(el('p', null, `Handed back to AUTO on: ${enc.trigger}.`));
}

function jumpToEncounter() {
  const m = model(flight());
  const cpa = cpaMark(flight(), m);
  const t = cpa ? cpa.tick : (m.encounters[0] ? m.encounters[0].from : 1);
  show('replay'); stop(); seek(Math.max(0, t - 1 - 6));
}
function nextEvent(dir) {
  const m = model(flight());
  const here = S.idx;
  const list = dir > 0 ? m.seekable.filter(i => i > here + .5) : m.seekable.filter(i => i < here - .5).reverse();
  if (list.length) { stop(); seek(list[0]); }
}

// ------------------------------------------------------------------ view 2: avoidance log
const EVCOLS = ['tick', 'time', 'event', 'detail', 'geometry'];
function renderEvents() {
  const f = flight(), m = model(f);
  $('#ev-count').textContent = `— ${m.loopEvents.length} of ${m.events.length} non-cruise events (cruise "proceed" ticks omitted)`;
  const cards = $('#runblock'); cards.innerHTML = '';
  const run = f.log.run;
  const card = (title, rows, note) => {
    const c = el('div', 'card'); c.appendChild(el('h3', null, title));
    const dl = el('dl');
    for (const [k, v] of rows) { dl.appendChild(el('dt', null, k)); dl.appendChild(el('dd', null, v)); }
    const wrap = el('div', 'facts');
    wrap.style.border = 'none'; wrap.style.padding = '0'; wrap.style.background = 'none'; wrap.style.boxShadow = 'none';
    wrap.appendChild(dl); c.appendChild(wrap);
    if (note) c.appendChild(el('p', 'note', note));
    cards.appendChild(c);
  };
  if (!run) {
    const c = el('div', 'card'); c.appendChild(el('h3', null, 'run block'));
    c.appendChild(el('p', 'note', 'This schema-1 log predates the run block: no recorded clock source, no detector '
      + 'provenance, no per-tick sim stamps. The gate scores it on the legacy path (CPA against the drone\'s own '
      + 'logged detections) and it is pinned as a reviewed legacy artifact — a log that simply omitted the block '
      + 'would be INVALID, not legacy.'));
    cards.appendChild(c);
  } else {
    const k = run.detector.counters || {};
    card('detector (the ADR-009 seam)', [
      ['source', run.detector.source], ['module', run.detector.module],
      ['threshold', `${run.detector.thresh}${run.detector.thresh_provisional ? ' (PROVISIONAL)' : ''}`],
      ['range model', run.detector.range_model.split(';')[0]],
      ['frames detected on', `${k.frames_detected_on} / ${k.ndvi_msgs_received} = ${pct(k.frames_detected_on, k.ndvi_msgs_received)}`],
      ['dropped: no intrinsics', String(k.dropped_no_intrinsics)],
      ['dropped: no pose pair', String(k.dropped_no_pose_pair)],
      ['dropped: stale pose pair', String(k.dropped_stale_pose_pair)],
      ['detect wall p95 / max', `${k.detect_wall_ms_p95} / ${k.detect_wall_ms_max} ms`],
    ], run.detector.thresh_provenance);
    card('clock', [
      ['source', run.clock.source], ['readings', String(run.clock.readings)],
      ['domain violations', String(run.clock.violations)],
      ['ticks without clock', `${run.clock.ticks_without_clock} / ${run.clock.ticks_total}`],
      ['violation bound', `${run.clock.violation_bound_s} s`],
    ], run.clock.domain);
  }
  card('policy parameters this flight flew', Object.entries(m.params).map(([a, b]) => [a, JSON.stringify(b)]),
    'Read from ' + m.from + '. The safety gate reads the same PolicyParams, so the bar and the control law '
    + 'cannot drift apart.');

  const thead = $('#events thead'), tb = $('#events tbody');
  thead.innerHTML = ''; tb.innerHTML = '';
  const hr = el('tr'); EVCOLS.forEach(c => hr.appendChild(el('th', null, c))); thead.appendChild(hr);
  for (const e of m.loopEvents) {
    const tr = el('tr'); tr.dataset.tick = String(e.tick);
    tr.appendChild(el('td', null, String(e.tick)));
    tr.appendChild(el('td', null, m.stamps ? m.stamps[Math.min(m.stamps.length - 1, e.tick - 1)].toFixed(3) + ' s' : '—'));
    const kd = el('td'); const kk = el('span', 'k', e.kind);
    kk.style.background = evColor(e); kk.style.color = '#0b1016'; kd.appendChild(kk);
    if (e.verdict) kd.appendChild(el('span', 'dim', ' ' + e.verdict));
    if (e.trigger) kd.appendChild(el('span', 'dim', ' ' + e.trigger));
    tr.appendChild(kd);
    tr.appendChild(el('td', 'wrap', evDetail(e)));
    tr.appendChild(el('td', 'wrap', evGeom(e)));
    tr.onclick = () => { show('replay'); stop(); seek(e.tick - 1); };
    tb.appendChild(tr);
  }
  const ex = $('#ev-extra'); ex.innerHTML = '';
  if (m.debtEvents.length) {
    const d = el('details');
    d.appendChild(el('summary', null, `${m.debtEvents.length} coverage-debt events (end-of-flight bookkeeping) — see the NDVI view for the cell join`));
    d.appendChild(el('pre', null, m.debtEvents.map(e => `tick ${e.tick}  ${e.cell_id}  ${e.reason}`).join('\n')));
    ex.appendChild(d);
  }
  const sum = m.events.find(e => e.kind === 'divert_audit_summary');
  if (sum) ex.appendChild(el('p', 'note',
    `Divert audit (written by the executor at shutdown): ${sum.n_diverts} diverts, `
    + `${sum.n_at_risk_cells_recovered} at-risk cells recovered. A COMMANDED setpoint is never recorded as flown — `
    + `the ledger counts only cells the flown path actually covered.`));
  lastTick = -1;
}
function evDetail(e) {
  if (e.kind === 'maneuver') return e.policy_reason || '';
  if (e.kind === 'detection') return `position_enu [${e.position_enu.map(v => v.toFixed(2)).join(', ')}] · confidence ${e.confidence} · source ${e.source} · decision ${e.decision}`;
  if (e.kind === 'latch' || e.kind === 'relatch') return e.reason || '';
  if (e.kind === 'takeover') return `${e.from_mode} → ${e.to_mode} (${e.reason}), at waypoint ${e.wp_index_at_takeover}`;
  if (e.kind === 'resume') {
    const why = e.trigger === 'guided_ceiling'
      ? 'GUIDED CEILING — the mission was handed back because the encounter held GUIDED too long, NOT because the threat cleared'
      : 'the threat cleared';
    return `${why}. Resumed at waypoint ${e.resumed_wp_index} (took over at ${e.wp_index_at_takeover}`
      + `${e.resumed_same_waypoint ? ', same waypoint' : ''})`
      + (e.ticks_in_guided != null ? ` after ${e.ticks_in_guided} tick(s) in GUIDED` : '');
  }
  if (e.kind === 'hold') return (e.reason || '') + ' — a HOLD is zero displacement and honours no clearance bar.';
  if (e.kind === 'gate_reject') return e.reason || '';
  if (e.kind === 'divert_audit_summary') return `${e.n_diverts} diverts, ${e.n_at_risk_cells_recovered} at-risk cells recovered`;
  return '';
}
function evGeom(e) {
  const bits = [];
  if (e.kind === 'maneuver' && e.debug) {
    const d = e.debug;
    if (d.swept_tree_clearance_m !== undefined) bits.push(`swept tree clearance ${d.swept_tree_clearance_m} m (bar ${d.params.lateral_tree_margin_m} m)`);
    if (d.candidates_rejected) {
      bits.push(`${d.candidates_rejected.length} candidate(s) rejected`);
      for (const r of d.candidates_rejected) bits.push(`   ${r.angle_deg}°: ${r.why}`);
    }
    if (d.trigger_range_m !== undefined) bits.push(`trigger range ${d.trigger_range_m} m${d.range_degenerate ? ' — DEGENERATE' : ''}`);
    if (d.n_threats !== undefined) bits.push(`${d.n_threats} threat(s): ${(d.threat_ids || []).join(', ')}`);
    if (e.setpoint_enu) bits.push(`setpoint [${e.setpoint_enu.map(v => v.toFixed(2)).join(', ')}]`);
    if (e.latch_action) bits.push(`latch action: ${e.latch_action}`);
  }
  if (e.kind === 'latch' || e.kind === 'relatch') {
    bits.push(`setpoint [${e.setpoint_enu.map(v => v.toFixed(2)).join(', ')}]`);
    if (e.offset_m != null) bits.push(`moved ${e.offset_m.toFixed(3)} m (threshold ${e.relatch_threshold_m} m)`);
  }
  if (e.kind === 'hold' || e.kind === 'gate_reject') {
    if (e.bird_clearance_m != null) {
      bits.push(`bird clearance ${e.bird_clearance_m} m to ${e.bird_track_id} [CONTEXT, NEVER GATED — bar ${e.min_bird_clearance_m} m]`);
    } else if (e.kind === 'hold') {
      bits.push('no threat named — this hold measured nothing about separation');
    }
    if (e.setpoint_enu) bits.push(`refused setpoint [${e.setpoint_enu.map(v => v.toFixed(2)).join(', ')}]`);
    if (e.obstacle_id) bits.push(`obstacle ${e.obstacle_id}`);
  }
  return bits.join('\n');
}
function highlightRow(tick) {
  let best = null;
  for (const tr of $$('#events tbody tr')) {
    if (tr.classList.contains('here')) tr.classList.remove('here');
    if (Number(tr.dataset.tick) <= tick) best = tr;
  }
  if (best) best.classList.add('here');
}

// ------------------------------------------------------------------ view 3: NDVI health map
/** The tree/canopy analysis, recomputed in the browser from the heatmap cells + surveyed tree
 *  positions. Same rules as scripts/check_tree_positions.py: a tree centre sits on a grid corner, so
 *  its four surrounding cells are its cell set; imaged = any of the four has a value; canopy-grade =
 *  best-of-four > 0 (this world's soil is negative NDVI); lift = best-of-four minus the modal soil
 *  value. Recomputed rather than read so the page cannot show a number it did not derive — and then
 *  cross-checked against that gate's committed output. */
function analyseClip(clip) {
  const cells = clip.heatmap.cells, half = clip.heatmap.cell_size_m / 2;
  const imaged = cells.filter(c => c.mean_ndvi !== null);
  const counts = new Map();
  for (const c of imaged) { const k = Math.round(c.mean_ndvi * 1e6) / 1e6; counts.set(k, (counts.get(k) || 0) + 1); }
  let soil = null, soilN = -1;
  for (const [k, n] of counts) if (n > soilN) { soil = k; soilN = n; }
  const rows = S.data.field.trees.map(t => {
    const [tx, ty] = t.pos_m;
    const quad = cells.filter(c => Math.abs(Math.abs(c.cx_m - tx) - half) < 1e-6 && Math.abs(Math.abs(c.cy_m - ty) - half) < 1e-6);
    const hit = quad.filter(c => c.mean_ndvi !== null);
    const best = hit.length ? hit.reduce((a, b) => (b.mean_ndvi > a.mean_ndvi ? b : a)) : null;
    return {
      tree_id: t.id, pos_m: [tx, ty], imaged: hit.length > 0,
      best_cell_id: best ? best.cell_id : null, n_samples: best ? best.n_samples : 0,
      mean_ndvi: best ? best.mean_ndvi : null, lift: best ? best.mean_ndvi - soil : null,
      canopy_grade: !!(best && best.mean_ndvi > 0),
    };
  });
  const lifts = rows.filter(r => r.canopy_grade).map(r => r.lift).sort((a, b) => a - b);
  const median = lifts.length ? (lifts.length % 2 ? lifts[(lifts.length - 1) / 2]
    : (lifts[lifts.length / 2 - 1] + lifts[lifts.length / 2]) / 2) : null;
  const positive = imaged.filter(c => c.mean_ndvi > 0);
  const nearestTree = c => Math.min(...S.data.field.trees.map(t => Math.hypot(c.cx_m - t.pos_m[0], c.cy_m - t.pos_m[1])));
  return {
    cells_imaged: imaged.length, cells_total: cells.length, soil_modal_ndvi: soil, soil_modal_cells: soilN,
    trees_total: rows.length, trees_imaged: rows.filter(r => r.imaged).length,
    trees_canopy_grade: rows.filter(r => r.canopy_grade).length, median_lift: median,
    positive_cells: positive.length,
    displaced: positive.filter(c => nearestTree(c) > 2.0).map(c => c.cell_id),
    rows,
  };
}

function renderNdvi() {
  const clip = S.data.clips[S.clipId], A = analyseClip(clip), oracle = clip.treeCheck;
  const hm = clip.heatmap, meta = clip.meta, f = flight(), m = model(f);
  const st = $('#ndvi-stats'); st.innerHTML = '';
  const stat = (label, value, sub) => {
    const s = el('div', 'stat'); s.appendChild(el('div', 'l', label));
    s.appendChild(el('div', 'v', value)); if (sub) s.appendChild(el('div', 's', sub)); st.appendChild(s);
  };
  stat('cells imaged', `${A.cells_imaged} / ${A.cells_total}`, `2.5 m grid · ${pct(A.cells_imaged, A.cells_total)}`);
  stat('trees imaged', `${A.trees_imaged} / ${A.trees_total}`, 'surveyed tree centres');
  stat('canopy-grade', `${A.trees_canopy_grade} / ${A.trees_total}`, 'best-of-four cell NDVI > 0');
  stat('median lift', sgn(A.median_lift), `over modal soil ${sgn(A.soil_modal_ndvi)} (${A.soil_modal_cells} cells)`);
  stat('frames that painted', String(hm.frames_painting), `of ${meta.airborne.frames} airborne`);
  stat('painting cadence', `${Number(hm.painting_cadence_hz).toFixed(2)} Hz`, `over ${hm.painting_span_s} s (${hm.painting_time_basis})`);
  stat('canopy placement', A.displaced.length ? `${A.displaced.length} DISPLACED` : 'all within 2.0 m',
    `${A.positive_cells} positive cells vs tree centres`);

  const cc = $('#ndvi-crosscheck'); cc.innerHTML = '';
  const checks = [['cells_imaged', A.cells_imaged, oracle.cells_imaged], ['trees_imaged', A.trees_imaged, oracle.trees_imaged],
  ['trees_canopy_grade', A.trees_canopy_grade, oracle.trees_canopy_grade],
  ['soil_modal_ndvi', A.soil_modal_ndvi, oracle.soil_modal_ndvi],
  ['median_lift', A.median_lift, oracle.median_lift]];
  const bad = checks.filter(([, a, b]) => (typeof a === 'number' && typeof b === 'number') ? Math.abs(a - b) > 1e-9 : a !== b);
  const banner = el('div', 'banner ' + (bad.length ? 'bad' : 'ok'));
  banner.textContent = bad.length
    ? 'CROSS-CHECK FAILED — the browser and ' + oracle.gate + ' disagree on: '
    + bad.map(([k, a, b]) => `${k} (page ${a} vs gate ${b})`).join('; ') + '. Trust neither number until this is fixed.'
    : `Cross-check OK — these figures, recomputed in your browser from ${hm.clip_dir}/heatmap/heatmap.json, `
    + `match ${oracle.gate}'s committed output exactly (${checks.length} quantities).`;
  cc.appendChild(banner);
  cc.appendChild(el('p', 'note',
    `Frame denominators for this clip: ${meta.airborne.frames} airborne frames (z > ${meta.airborne.z_threshold_m} m) `
    + `and ${hm.frames_painting} that actually painted a cell, out of ${meta.num_frames} recorded. `
    + `Quote the first two, never the third: ${meta.num_frames - meta.airborne.frames} of the recorded frames are a `
    + `parked vehicle below the ground plane (teardown was skipped) and update no cell.`));

  const mp = $('#ndvi-mode'); mp.innerHTML = '';
  for (const [key, label] of [['ndvi', 'NDVI value per cell'], ['coverage', 'coverage ledger (covered / debt)'],
  ['both', 'NDVI, with debt cells hatched']]) {
    const lab = el('label'); const rb = el('input'); rb.type = 'radio'; rb.name = 'ndvimode';
    rb.checked = S.ndviMode === key; rb.onchange = () => { S.ndviMode = key; N.key = ''; drawNdvi(); };
    lab.appendChild(rb); lab.appendChild(el('span', null, label)); mp.appendChild(lab);
  }
  mp.appendChild(el('p', 'note', `Ledger overlay uses the selected flight (${f.stem}): `
    + `${m.covered} covered / ${m.debt} debt. Heatmap and ledger join by cell_id on the same canonical grid — `
    + 'but the page does not claim this clip and that flight are the same take: the artifacts share no run id, '
    + 'and Gazebo sim time restarts near zero every run.'));

  $('#tree-method').textContent = 'Each tree centre lands exactly on a grid corner, so the four cells sharing that '
    + 'corner are its cell set. imaged = at least one of the four has a value; canopy-grade = best-of-four > 0 '
    + '(this world\'s soil reads negative NDVI); lift = best-of-four minus the modal soil value. Recomputed here '
    + 'from the heatmap and the surveyed positions.';
  const thead = $('#trees thead'), tb = $('#trees tbody');
  thead.innerHTML = ''; tb.innerHTML = '';
  const hr = el('tr'); ['tree', 'position (x, y)', 'best cell', 'samples', 'NDVI', 'lift', 'verdict']
    .forEach(h => hr.appendChild(el('th', null, h))); thead.appendChild(hr);
  for (const r of A.rows) {
    const tr = el('tr');
    tr.appendChild(el('td', null, r.tree_id));
    tr.appendChild(el('td', null, `(${r.pos_m[0].toFixed(1)}, ${r.pos_m[1].toFixed(1)})`));
    tr.appendChild(el('td', null, r.best_cell_id || '—'));
    tr.appendChild(el('td', null, String(r.n_samples)));
    tr.appendChild(el('td', null, r.mean_ndvi === null ? '—' : sgn(r.mean_ndvi)));
    tr.appendChild(el('td', null, r.lift === null ? '—' : sgn(r.lift)));
    const v = el('td', null, !r.imaged ? 'NOT IMAGED' : (r.canopy_grade ? 'CANOPY' : 'imaged, soil-grade'));
    if (r.canopy_grade) v.style.color = 'var(--good)';
    tr.appendChild(v);
    tb.appendChild(tr);
  }
  S._analysis = A;
  N.key = '';
  drawNdvi();
}

function ndviColor(v, dom) {
  if (v === null) return '#1a2129';
  const t = Math.max(-1, Math.min(1, v / dom));
  if (t < 0) { const k = -t; return `rgb(${Math.round(64 + 128 * k)},${Math.round(56 + 34 * k)},${Math.round(46 + 8 * k)})`; }
  return `rgb(${Math.round(64 - 34 * t)},${Math.round(56 + 174 * t)},${Math.round(46 + 44 * t)})`;
}

const N = { key: '', static: null, w: 0, h: 0, dpr: 1, V: null };
function drawNdvi() {
  const cv = $('#ndvimap');
  if (!cv || cv.clientWidth === 0) return;
  const w = Math.max(320, cv.clientWidth), h = Math.round(w / ASPECT());
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const key = [S.clipId, S.flightId, S.ndviMode, w, h, dpr].join('|');
  if (key !== N.key || !N.static) {
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    cv.style.height = h + 'px';
    N.w = w; N.h = h; N.dpr = dpr; N.V = makeView(w, h); N.key = key; N.static = off(w, h, dpr);
    paintNdvi(N.static.getContext('2d'), N.V);
  }
  const c = cv.getContext('2d');
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, w, h);
  c.drawImage(N.static, 0, 0, w, h);
}
function paintNdvi(c, V) {
  const clip = S.data.clips[S.clipId], hm = clip.heatmap, cs = hm.cell_size_m;
  const vals = hm.cells.map(x => x.mean_ndvi).filter(v => v !== null);
  const dom = Math.max(...vals.map(Math.abs));
  const status = new Map(model(flight()).ledger.map(r => [r.cell_id, r.status]));
  c.clearRect(0, 0, V.w, V.h);
  for (const cell of hm.cells) {
    const [px, py] = V.P(cell.cx_m - cs / 2, cell.cy_m + cs / 2);
    const w = cs * V.s, stv = status.get(cell.cell_id);
    c.fillStyle = (S.ndviMode === 'coverage')
      ? (stv === 'covered' ? 'rgba(52,211,153,0.45)' : (stv === 'debt' ? 'rgba(248,113,113,0.55)' : '#1a2129'))
      : ndviColor(cell.mean_ndvi, dom);
    c.fillRect(px, py, w + 0.6, w + 0.6);
    if (S.ndviMode === 'both' && stv === 'debt') {
      c.save(); c.strokeStyle = 'rgba(248,113,113,0.9)'; c.lineWidth = 1;
      c.beginPath(); c.moveTo(px, py + w); c.lineTo(px + w, py); c.stroke(); c.restore();
    }
  }
  for (const r of S._analysis.rows) {
    ring(c, V, r.pos_m[0], r.pos_m[1], 2.0, 'rgba(255,255,255,0.2)', [2, 3]);
    disc(c, V, r.pos_m[0], r.pos_m[1], 4.5, r.canopy_grade ? '#eaffea' : (r.imaged ? '#8fa0b3' : '#f87171'), '#0b0f12');
  }
  c.save(); c.beginPath();
  S.data.field.polygon_m.forEach((p, i) => { const [x, y] = V.P(p[0], p[1]); i ? c.lineTo(x, y) : c.moveTo(x, y); });
  c.closePath(); c.strokeStyle = 'rgba(255,255,255,0.3)'; c.lineWidth = 1.2; c.stroke(); c.restore();

  const lg = $('#ndvi-legend'); lg.innerHTML = '';
  lg.appendChild(el('span', 'dim', `NDVI ${sgn(-dom, 3)}`));
  const bar = el('span');
  for (let i = 0; i <= 10; i++) {
    const sw = el('i', 'dot');
    sw.style.cssText = `width:17px;height:12px;border:0;border-radius:2px;background:${ndviColor(-dom + 2 * dom * i / 10, dom)}`;
    bar.appendChild(sw);
  }
  lg.appendChild(bar);
  lg.appendChild(el('span', 'dim', sgn(dom, 3)));
  for (const [col, label] of [['#eaffea', 'tree, canopy-grade'], ['#8fa0b3', 'tree, imaged soil-grade'],
  ['#f87171', S.ndviMode === 'coverage' ? 'debt cell' : 'tree not imaged']]) {
    const s = el('span'); s.style.color = col; s.appendChild(el('i', 'dot')); s.appendChild(el('span', 'dim', label)); lg.appendChild(s);
  }
}

// ------------------------------------------------------------------ hover tooltips
function mapHover(ev) {
  const cv = $('#map'), r = cv.getBoundingClientRect();
  if (!R.V) return;
  const px = ev.clientX - r.left, py = ev.clientY - r.top;
  const m = model(flight());
  let hit = null, bestD = 14;
  const test = (xy, text) => {
    const [ax, ay] = R.V.P(xy[0], xy[1]);
    const d = Math.hypot(ax - px, ay - py);
    if (d < bestD) { bestD = d; hit = { xy, text }; }
  };
  for (const t of S.data.field.trees) {
    test([t.pos_m[0], t.pos_m[1]],
      `${t.id}\nsurveyed static obstacle (ADR-001)\ncentre (${t.pos_m[0]}, ${t.pos_m[1]}) m · height ${t.height_m} m\n`
      + `geofence radius ${t.obstacle_radius_m} m · canopy ${t.canopy_radius_m} m`);
  }
  if (S.layers.events) {
    for (const e of m.loopEvents) {
      if (e.kind === 'divert_audit_summary') continue;
      const xy = eventXY(m, e);
      if (xy) test(xy, `tick ${e.tick}${m.stamps ? ` · t_sim ${m.stamps[Math.min(m.stamps.length - 1, e.tick - 1)].toFixed(3)} s` : ''}\n`
        + `${e.kind}${e.verdict ? ' · ' + e.verdict : ''}${e.trigger ? ' · ' + e.trigger : ''}\n${evDetail(e).slice(0, 150)}`);
    }
  }
  const tip = $('#tip');
  S.hover = hit;
  if (!hit) { tip.hidden = true; requestRender(); return; }
  tip.hidden = false;
  tip.textContent = hit.text;
  const [hx, hy] = R.V.P(hit.xy[0], hit.xy[1]);
  tip.style.left = Math.min(R.w - 250, hx + 14) + 'px';
  tip.style.top = Math.max(4, hy - 12) + 'px';
  requestRender();
}

// ------------------------------------------------------------------ tour
const TOUR = [
  { t: 'A 75 × 60 m field, surveyed before takeoff',
    b: 'The 720 grey squares are the canonical 2.5 m coverage cells — the same grid the NDVI map and the '
      + 'coverage ledger both join on. The green dots are 18 surveyed trees with their 2 m geofences: known '
      + 'static obstacles, so the drone never has to detect them. Dashed blue is the planned boustrophedon.',
    go: m => ({ view: 'replay', idx: m.air && m.air.found ? m.air.first_motion_tick - 1 : 0 }) },
  { t: 'The loop takes the vehicle',
    b: 'An NDVI frame off the real render produced a detection nothing injected. The policy ranged it from the '
      + 'apparent-size ray, vetted a dodge against every tree, latched ONE setpoint and switched AUTO → GUIDED. '
      + 'The pink stretch is the vehicle under the avoidance loop; the pink X is the point it was commanded to.',
    go: m => ({ view: 'replay', idx: (m.encounters[0] ? m.encounters[0].from - 1 : 0) - 3 }) },
  { t: 'The closest approach — look at the altitude strip',
    b: 'Top-down, this looks like the drone flew straight through the bird. It did not: it flew OVER it. '
      + 'The altitude strip shows the gap the map flattens away. The dodge was commanded, vetted and flown — '
      + 'and it moved the vehicle centimetres, because the bird was first seen on the tick of closest approach.',
    go: (m, f) => ({ view: 'replay', idx: (cpaMark(f, m) ? cpaMark(f, m).tick - 1 : 0) }) },
  { t: 'Why this take is INVALID, and why that is the point',
    b: 'The safety gate that failed this flight was built the day before it, and the process that built it wrote '
      + 'down, in advance, that the flight might fail it. It did. The marker file is beside the log; the '
      + '"acknowledged" pin is deliberately withheld, so CI stays red until it is re-flown. A gate you only '
      + 'trust when it is green is not a gate.',
    go: () => ({ view: 'replay' }) },
  { t: 'The same flight still produced a full health map',
    b: '720 of 720 cells imaged, all 18 surveyed trees found where the survey says they are, 11 of them reading '
      + 'canopy-grade NDVI. Those numbers are recomputed in your browser and cross-checked against the host-side '
      + 'gate — the green banner is the page checking itself.',
    go: () => ({ view: 'ndvi' }) },
];
function renderTour() {
  const box = $('#tour');
  if (S.tour < 0 || S.tour >= TOUR.length) { box.hidden = true; return; }
  const step = TOUR[S.tour], m = model(flight()), f = flight();
  const to = step.go(m, f) || {};
  if (to.view) show(to.view);
  if (to.idx !== undefined) { stop(); seek(Math.max(0, to.idx)); }
  box.hidden = false; box.innerHTML = '';
  box.appendChild(el('div', 'step', `Step ${S.tour + 1} of ${TOUR.length}`));
  box.appendChild(el('h3', null, step.t));
  box.appendChild(el('p', null, step.b));
  const row = el('div', 'row');
  const prev = el('button', 'ghost', '← Back'); prev.onclick = () => { S.tour--; renderTour(); };
  if (S.tour === 0) prev.disabled = true;
  const next = el('button', 'ghost', S.tour === TOUR.length - 1 ? 'Done' : 'Next →');
  next.onclick = () => { S.tour++; renderTour(); };
  const close = el('button', 'ghost', 'Close'); close.onclick = () => { S.tour = -1; renderTour(); };
  row.appendChild(prev); row.appendChild(el('div', 'spacer')); row.appendChild(close); row.appendChild(next);
  box.appendChild(row);
}

// ------------------------------------------------------------------ footer
function renderAbout() {
  const a = $('#about'); a.innerHTML = '';
  a.appendChild(el('h2', null, 'About this data'));
  a.appendChild(el('p', null, S.data.manifest.what));
  a.appendChild(el('p', null, 'Every source artifact, with the SHA-256 you can verify against your own clone ('
    + S.data.manifest.verify_a_copy + '):'));
  const t = el('table'), th = el('tr');
  ['artifact', 'role', 'bytes', 'sha256'].forEach(h => th.appendChild(el('th', null, h)));
  t.appendChild(th);
  for (const s of S.data.manifest.sources) {
    const tr = el('tr');
    tr.appendChild(el('td', null, s.path));
    tr.appendChild(el('td', null, s.role));
    tr.appendChild(el('td', null, s.bytes.toLocaleString()));
    tr.appendChild(el('td', null, s.sha256.slice(0, 16) + '…'));
    t.appendChild(tr);
  }
  a.appendChild(t);
  a.appendChild(el('p', 'note', 'Provenance is by CONTENT, not by commit: a hash is verifiable from any clone and '
    + 'survives a rebase, where a recorded commit id would only be right until the next one. For the commit that '
    + 'last touched an artifact, run `git log -1 -- <path>` against the paths above.'));
  a.appendChild(el('p', 'note', 'Rebuild with `python3 scripts/build_dashboard_data.py`; '
    + '`--check` fails if this directory has drifted from a fresh build, and CI runs it. '
    + 'The NDVI stitch is offline post-flight (ADR-010) onto the same 2.5 m cell grid as the coverage ledger, '
    + 'so heatmap and ledger join by cell_id. This page is static: no server, no tracking, no network calls.'));
}

// ------------------------------------------------------------------ wiring
function show(name) {
  if (name !== 'replay') stop();      // nothing to animate off the replay view
  S.view = name;
  for (const b of $$('.tab')) b.setAttribute('aria-selected', String(b.dataset.view === name));
  for (const v of ['replay', 'events', 'ndvi']) $('#view-' + v).hidden = (v !== name);
  $('#verdict').hidden = (name === 'ndvi');
  if (name === 'replay') { R.key = ''; E.key = ''; requestRender(); }
  if (name === 'ndvi') { N.key = ''; drawNdvi(); }
}
function wire() {
  for (const b of $$('.tab')) b.onclick = () => show(b.dataset.view);
  $('#play').onclick = () => {
    if (S.playing) return stop();
    const m = model(flight()), [lo, hi] = playRange(m);
    if (S.idx < lo || S.idx >= hi) S.idx = lo;      // play always starts where the flight starts
    S.playing = true; S.lastFrame = 0; $('#play').textContent = '❚❚';
    requestRender();
  };
  $('#jump').onclick = jumpToEncounter;
  $('#tour-start').onclick = () => { S.tour = 0; renderTour(); };
  $('#scrub').oninput = e => { stop(); seek(Number(e.target.value)); };
  $('#speed').onchange = e => { S.speed = Number(e.target.value); };
  $('#map').addEventListener('mousemove', mapHover);
  $('#map').addEventListener('mouseleave', () => { S.hover = null; $('#tip').hidden = true; requestRender(); });
  $('#ndvimap').addEventListener('mousemove', ndviHover);
  let rz;
  window.addEventListener('resize', () => {
    clearTimeout(rz);
    rz = setTimeout(() => { R.key = ''; E.key = ''; N.key = ''; requestRender(); drawNdvi(); }, 120);
  });
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    const k = e.key;
    if (k === ' ') { e.preventDefault(); $('#play').click(); }
    else if (k === 'ArrowRight') { stop(); seek(S.idx + (e.shiftKey ? 25 : 1)); }
    else if (k === 'ArrowLeft') { stop(); seek(S.idx - (e.shiftKey ? 25 : 1)); }
    else if (k === 'e' || k === 'E') nextEvent(e.shiftKey ? -1 : 1);
    else if (k === '1') show('replay');
    else if (k === '2') show('events');
    else if (k === '3') show('ndvi');
    else if (k === 'Escape' && S.tour >= 0) { S.tour = -1; renderTour(); }
  });
}
function ndviHover(ev) {
  const cv = $('#ndvimap'), r = cv.getBoundingClientRect();
  if (!N.V) return;
  const [wx, wy] = N.V.inv(ev.clientX - r.left, ev.clientY - r.top);
  const hm = S.data.clips[S.clipId].heatmap, cs = hm.cell_size_m;
  const status = new Map(model(flight()).ledger.map(x => [x.cell_id, x.status]));
  const cell = hm.cells.find(c => Math.abs(c.cx_m - wx) <= cs / 2 && Math.abs(c.cy_m - wy) <= cs / 2);
  const box = $('#cellinfo'); box.innerHTML = '';
  if (!cell) { box.appendChild(el('p', 'dim', 'Outside the graded field.')); return; }
  const dl = el('dl');
  const row = (k, v) => { dl.appendChild(el('dt', null, k)); dl.appendChild(el('dd', null, v)); };
  row('cell_id', cell.cell_id);
  row('centre', `(${cell.cx_m}, ${cell.cy_m}) m`);
  row('mean NDVI', cell.mean_ndvi === null ? 'not imaged' : sgn(cell.mean_ndvi, 6));
  row('samples', String(cell.n_samples));
  row('lift vs soil', cell.mean_ndvi === null ? '—' : sgn(cell.mean_ndvi - S._analysis.soil_modal_ndvi));
  row('ledger status', status.get(cell.cell_id) || 'not in this ledger');
  box.appendChild(dl);
}

function renderAll() {
  const m = model(flight());
  const [lo] = playRange(m);
  S.idx = lo;
  lastTick = -1; lastEnc = null; $('#encounter').hidden = true;
  $('#scrub').max = String(m.n - 1);
  renderPickers(); renderVerdict(); renderFacts(); renderLegends(); renderTimeline();
  renderEvents(); renderNdvi(); renderAbout();
  requestRender();
  paintHud();
}

boot();
