# Spike: NDVI-direct vs. synthetic-RGB detection (resolves ADR-003)

Owner: `perception-ml-engineer` · Reviewer: `tech-lead` · Time-box: **3 working days (Week 1–2)**
Status: **CLOSED 2026-08-04** — decided (ADR-003: NDVI-direct); numbers recorded in `docs/DECISIONS.md` ADR-003 and this file's
"Outcome" section.

> **FROZEN RECORD — do not edit.** Kept for the decision trail: this is what was asked, how it was
> measured, and what came back. The one open item it leaves behind — re-running the same harness on
> the real Gazebo render — is tracked in ADR-003 and `docs/ROADMAP.md`, not here.

This is a **de-risking spike, not a research program.** The goal is one framing decision backed by
one number, not a tuned detector. Do not design detector architecture beyond the classical-CV
baseline described here until this question is answered.

---

## 1. The question and why it matters

A real NDVI camera captures **Red + NIR**, not RGB. Off-the-shelf detectors (YOLO, etc.) are
trained on RGB and don't apply directly to a two-band NDVI frame. Before committing perception
effort, we must decide *what frame the detector actually consumes*:

- **(a) NDVI-direct** — run detection on the NDVI-rendered frame itself. The detection signal is
  **vegetation-index contrast**: a bird is a low-NDVI blob against a high-NDVI canopy. This is
  faithful to the single-NDVI-camera hardware we actually have (ADR-000 sensor reality).
- **(b) Synthetic RGB pass** — render an extra RGB camera in sim purely for perception, keep NDVI
  for health mapping only. Easier (unlocks off-the-shelf RGB detectors) but **less faithful**: it
  quietly assumes a second sensor / band the real drone does not have.

Why it matters: this choice sets the fidelity of the entire perception → avoidance loop (priority
#1). Picking (b) for convenience would make our headline demo depend on a sensor the hardware
doesn't have — an interview liability. So the bar is: **default to (a) unless the evidence says the
NDVI-only signal is not safe enough**, where "safe enough" is defined by false-negative rate below.

**Recommended default going in: (a) NDVI-direct.** The spike exists to try to *falsify* that
default cheaply, not to rubber-stamp it.

---

## 2. The two candidate approaches — what each concretely requires in sim

### (a) NDVI-direct  *(recommended starting point)*
- **Sim needs:** the NDVI camera render already on the roadmap (Red + synthetic NIR → per-pixel
  NDVI = (NIR − Red)/(NIR + Red)). No extra sensor.
- **Perception input:** single-channel NDVI image (float, ~[−1, 1]).
- **Signal hypothesis:** birds are non-vegetation → low/negative NDVI blobs against a high-NDVI
  canopy background. Threshold + blob-detect.
- **Fidelity:** matches real hardware exactly. Nothing to walk back later.
- **Risk it's testing:** is the NDVI contrast of a bird-vs-canopy strong and stable enough to
  detect reliably, or does it wash out (e.g. dark soil, shadows, bare patches also read low-NDVI →
  false positives; a bird over already-low-NDVI ground → false negative)?

### (b) Synthetic RGB pass  *(fallback if (a) fails the bar)*
- **Sim needs:** a second co-located camera publishing an RGB image, **plus** the NDVI camera.
  More sim wiring, a second image topic, and an explicit "this is a sensor we don't have" caveat.
- **Perception input:** standard 3-channel RGB.
- **Fidelity:** low for the primary arm — but note (b) is *also* exactly the NDVI+RGB
  **comparison-arm** config the project already plans to run. So even if (a) wins, the RGB render is
  not wasted: it becomes the second-sensor arm that quantifies what an added camera buys.
- **Risk it's testing:** none about the drone we have; it's the easy-mode baseline that tells us the
  *ceiling* — how much detection performance we give up by staying NDVI-only.

Running both on the **same clip** is what makes this a decision, not a vibe: (b) is the ceiling,
(a) is the faithful option, and the gap between them is the price of fidelity.

---

## 3. The decision metric

One labeled sim clip, three numbers, one threshold.

### What counts as a "detection"
A detection is a 2D bounding box (or blob centroid + radius) in the image emitted by the pipeline
for a given frame. A detection is a **true positive** if its box overlaps a ground-truth bird box
with **IoU ≥ 0.3** (loose IoU on purpose — for avoidance we care about *"there is a bird roughly
there,"* not pixel-tight localization). One GT bird matched by ≥1 detection = TP; a GT bird with no
matching detection = **false negative**; a detection matching no GT bird = false positive.

### Ground truth: how we label it from sim
We do **not** hand-label pixels. The birds are scripted Gazebo actors, so ground truth is free:
*[2026-08-18: superseded — per ADR-012 the birds are static SDF models teleported along the same
committed waypoints by `scripts/drive_birds.py`; the trajectories, and therefore this
free-ground-truth argument, are unchanged.]*
- Log each bird actor's world pose per frame from the sim.
- Project it through the (known, simulated) camera intrinsics + the drone pose from SITL telemetry
  into image coordinates → a GT box per visible bird per frame.
- A small script (`eval/label_from_sim.py`, stub below) emits `ground_truth.json`:
  `{frame_id, [ {bird_id, bbox, visible} ] }`.
- Visibility gate: drop GT boxes for birds outside the frustum or fully occluded, so we don't
  penalize the detector for birds it physically cannot see.

This makes labels exact and reproducible (fixed seed), which is the whole point of doing it in sim.

### The three numbers (per approach, on the same clip)
- **Precision** = TP / (TP + FP) — how much we cry wolf.
- **Recall** = TP / (TP + FN) — how many birds we catch.
- **False-negative rate (FNR)** = FN / (TP + FN) = 1 − recall, **reported separately and treated as
  the safety-critical metric.** A missed bird is a potential collision; a false positive is a
  wasteful dodge. These are not symmetric and we will not average them into one score.

Frame-level metrics, then also report a **per-bird-track FNR**: across the clip, was each bird
detected on ≥1 frame *before* closest approach? A bird never detected until impact is the worst
case and gets called out explicitly.

### Pass/fail: the threshold that picks (a) over (b)
Default is (a). We **keep (a)** unless it is clearly unsafe relative to (b). Concretely, on the spike clip:

- **Pick (a) (NDVI-direct)** if NDVI-direct achieves **per-bird FNR ≤ 0.10** (each bird detected on
  at least one pre-closest-approach frame ≥ 90% of the time) **and** its FNR is **within 0.10
  (absolute) of approach (b)'s** FNR. I.e. NDVI-only catches essentially the same birds RGB does.
- **Pick (b) (synthetic RGB) — or escalate** if NDVI-direct per-bird FNR **> 0.10** *and* (b) is
  materially better (FNR gap > 0.10). That means the faithful sensor genuinely can't see the
  threat and we need the extra band. This is a `product-lead` escalation (fidelity vs. safety),
  recorded as a tradeoff in DECISIONS.md — not a silent call.
- Precision is a **secondary** tiebreak: if both approaches clear the FNR bar, prefer (a) on
  fidelity even at somewhat lower precision (extra dodges are cheap; the avoidance loop and the
  static-map sanity check can suppress false positives later).

Thresholds are deliberately loose — this is a go/no-go on framing, not a tuned model. If the
numbers land in an ambiguous middle band, the tie goes to **(a) + a follow-up**, not to expanding
the spike.

---

## 4. The minimal experiment

Smallest thing that produces the metric.

### Sim assets needed from `robotics-sim-engineer`  *(the critical dependency)*
1. **One short scripted-bird clip, ~20–40 s, fixed seed**, drone flying a straight leg over canopy
   with **2–3 birds** crossing the field of view at varying range (matches the MVP 2–3 bird scope).
2. **Rendered twice from the same flight/seed:**
   - NDVI frames (Red + NIR → NDVI), and
   - RGB frames from a co-located camera.
   Same poses, same timestamps, so (a) and (b) are compared on identical events.
3. **Per-frame logs:** bird actor world poses, drone pose/telemetry, and camera intrinsics — so
   `eval/label_from_sim.py` can generate ground-truth boxes. Rosbag or plain CSV/JSON is fine.

That's it. No trees needed for this spike (static obstacles are out of scope per ADR-001), no
avoidance, no full mission. A single straight leg over canopy with birds is enough.

### Classical-CV baseline first (no trained model)
Before any network, the (a) detector is deliberately dumb:
1. Compute NDVI per pixel (already have it) or, for (b), a comparable RGB heuristic.
2. **Threshold** to isolate low-vegetation pixels (bird candidates against high-NDVI canopy).
3. **Morphological open/close** to denoise + **connected-components / blob detection** for candidate
   boxes; filter by area to drop specks and huge regions.
4. (Optional, cheap) frame-to-frame blob association for the per-track metric.

If this baseline already clears the FNR bar, we are **done** — no trained model is justified yet,
and introducing one now would be unjustified complexity (a claim we'd have to defend in review).
Any future model must beat this baseline on the same harness to earn its place.

### Eval harness stub under `eval/`
Minimal, headless, emits numbers. To be created when the clip lands (not before — this is scoping):

```
eval/
  label_from_sim.py     # sim poses + intrinsics + telemetry -> ground_truth.json (GT boxes/frame)
  baseline_ndvi.py      # NDVI threshold + blob detector -> detections.json
  baseline_rgb.py       # same-shape detector on the RGB pass -> detections.json  (approach b)
  score.py              # detections.json + ground_truth.json -> precision, recall, FNR,
                        #   per-bird-track FNR; prints a table, writes results/ (gitignored)
  scenarios/
    spike_birds.yaml    # points at the clip + seed so the run is reproducible
```

`score.py` is the reusable core — it's the seed of the permanent eval harness the project needs for
every later "does avoidance work" claim, so it outputs the same metric family
(precision / recall / **FNR**) the eval README already commits to. Coordinate with
`devops-reliability-engineer` to wire `score.py` into CI once it stabilizes.

---

## 5. Time-box and decision criteria

**Time-box: 3 working days**, gated on the sim clip being available. Rough split:
- Day 1: `label_from_sim.py` + confirm GT boxes visually overlay the birds on a few frames.
- Day 2: `baseline_ndvi.py` and `baseline_rgb.py` + `score.py`; get numbers out.
- Day 3: interpret, write the Outcome section, update ADR-003.

**The spike ends when** we have precision / recall / **FNR** for (a) and (b) on the same clip, and
one of these fires:
- (a) clears the FNR bar and is within 0.10 FNR of (b) → **adopt (a)**, close ADR-003 as accepted.
- (a) misses the FNR bar and (b) is materially better → **escalate to `product-lead`** (fidelity vs.
  safety), record the tradeoff, likely adopt (b) *or* (a)+RGB-assist.
- numbers are ambiguous → **default to (a) + a scoped follow-up ticket**; do **not** extend the spike.

**Explicitly out of scope for this spike:** detector architecture beyond the blob baseline, model
training, avoidance behavior, trees/static obstacles, multi-bird flocks, NDVI+depth. Those wait
until the framing question is settled.

---

## Outcome  *(landed 2026-08-04, perception-ml-engineer)*

Ran end-to-end on the Week-2 spike clip via the new `eval/` harness (`label_from_sim.py` →
`baseline_ndvi.py` / `baseline_rgb.py` → `score.py`; reproduce with `eval/run_spike.sh`).

- **Clip / seed used:** `sim/spike/out/spike_seed42` — seed 42, 30s @ 10fps, 640×480, 3 scripted
  birds (`bird_0` clean canopy, `bird_1` crossing bare-soil patch = the false-negative hard case,
  `bird_2` far + near static clutter). **SYNTHETIC stand-in, not yet a Gazebo render** (`meta.json`
  `synthetic:true`). GT projection independently verified against the generator's own boxes to
  **0.007 px** max disagreement (sub-pixel → GT trusted; the Day-1 projection check passed).
- **Precision / recall / FNR — approach (a) NDVI-direct:** **0.445 / 0.981 / 0.019** (TP 53, FP 66,
  FN 1). Threshold `NDVI < 0.05` + morphology + blob, no trained model.
- **Precision / recall / FNR — approach (b) synthetic RGB:** **1.000 / 0.981 / 0.019** (TP 53, FP 0,
  FN 1). Same blob pipeline on min-channel `min(R,G,B) > 110`.
- **Per-bird-track FNR (a) / (b):** **0.000 / 0.000** — every bird, including `bird_1` over soil,
  detected on ≥1 frame before closest approach (12/12 frames for `bird_1`). The feared NDVI
  wash-out did **not** occur: the bird reads negative NDVI, cleanly below the soil patch (~0.15).
- **The one FN is shared** by both approaches (`bird_0`, 16/17 visible frames) — a single
  tiny-blob entry frame, not a safety miss (bird caught on 16 other frames, well before approach).
- **The (a) precision gap is fully explained:** 66/66 of NDVI-direct's false positives are the one
  *static* `clutter_0` feature (bird-sized negative-NDVI mulch/rock) — zero random-noise FPs. This
  is exactly what the planned **static-obstacle map sanity-check** (and blob motion-tracking, since
  clutter doesn't move) is designed to suppress. Extra dodges are cheap; a missed bird is not.
- **Decision:** **ADOPT (a) NDVI-direct.** It clears the per-bird FNR bar (0.000 ≤ 0.10) and its
  frame FNR is *identical* to RGB (gap 0.000 ≤ 0.10). Per §3, fidelity wins the precision tiebreak;
  the RGB arm is retained as the NDVI+RGB **comparison arm**, not thrown away.
- **Caveat (must carry into the ADR):** these are **synthetic** numbers — they validate the harness
  and give a strong first signal, but ADR-003 should be **confirmed against the real Gazebo NDVI
  render** before being treated as final. Strong enough to make the framing call **provisionally
  now** (default (a) was never in real danger of being falsified here); re-run `eval/run_spike.sh`
  on the real render to confirm.
- **ADR-003 updated:** yes — recorded 2026-08-04 with the numbers + synthetic-clip caveat.
