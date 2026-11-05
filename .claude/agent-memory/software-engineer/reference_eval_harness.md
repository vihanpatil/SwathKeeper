---
name: eval-harness-core
description: Structure and metric contract for the eval/ harness; score.py is the reusable core, and it now has TWO refusal guards (denominator + label provenance)
metadata:
  type: reference
---

Eval harness lives under `eval/` (owned by perception-ml-engineer, CI wiring by
devops-reliability-engineer). Metric contract from `eval/README.md`: precision / recall /
**FNR (safety-critical, separate)**, detection range / lead-time, avoidance success rate,
coverage completeness, single-NDVI vs second-sensor deltas. `results/` is gitignored except a small
evidence allowlist (clip `meta.json`/`poses.jsonl`/`heatmap/`, `bird_drive_*` sidecars AND their
`_applied.jsonl` logs) — commit summary metrics into reports, not raw frames.

Pipeline: `annotate_real_clip.py` (real clips: bird labels from the driver's applied-pose log) →
`label_from_sim.py` (poses → GT boxes via the ONE `ndvi_georef.project_world_point` primitive) →
`baseline_ndvi.py` / `baseline_rgb.py` → `score.py`. One-shot: `eval/run_spike.sh` with `CLIP=` /
`RESULTS=` env overrides.
**Both baselines now resolve their signal per render from `meta.json`** (`baseline_rgb.resolve_birdness`
mirrors `baseline_ndvi.resolve_threshold` and refuses a clip that does not declare `synthetic`):
synthetic = min-channel > 110, real render = GRVI < +0.0322 (2026-08-26, [[criterion2-rgb-study]]).
`rgb_pixel_study.py` is the criterion-2 evidence generator — manual, ~3 min, needs the gitignored
frames; its `results.json` IS committed because the RGB threshold is recomputed from it by test.

**Scoring a real clip without mutating it.** Everything downstream of `annotate_real_clip.py` reads
`<clip>/poses.jsonl` and nothing else, so the documented path is `--in-place`. When that is not
allowed (or the clip is uncommitted flight evidence), front it with a **view directory**: `frames`
and `poses.jsonl` symlinked (the latter at `poses_annotated.jsonl`), `meta.json` copied, and point
`--clip` at the view. `ndvi_path` in the pose lines is clip-relative, so this is transparent, costs
nothing, and leaves the raw recording byte-identical. Worked example:
`eval/results/adr003_20260825/clipview/`. Full 3310-frame NDVI arm runs in ~19 s on the host; the
RGB arm (stdlib PNG decode) ~30 s — neither needs a Docker session.

**The detector itself is NOT in `eval/` (moved 2026-08-24, `eval/blob.py` deleted).** It lives in
`src/fieldguard_planning/ndvi_detect.py` — thresholds, `detect_blobs`, `detect_ndvi` — because the
live avoidance node must run the code ADR-003 amendment 7 measured, not a second copy of it. Both
eval arms import it; `eval/` keeps only the CLIP-shaped concerns (per-render threshold resolution
from `meta.json`, frame IO). If a detector change is ever proposed, the boxes are pinned by
`tests/fieldguard_planning/test_ndvi_detect.py`: hand-derived morphology semantics + three real
NDVI frames committed as a fixture + (where the gitignored clip is on disk) the whole 1256-frame
adopted run, all compared against the committed `eval/results/adr003_20260823/detections_ndvi.json`.

**`score.py` refuses rather than deciding, on two independent grounds — both were live defects:**
1. **Denominator** (`evidence_shortfall`, 2026-08-21): ≥1 visible bird-frame AND every bird in the
   clip seen at least once, checked BEFORE the rates. It used to print `ADOPT` on an empty ground
   truth, four zeros reading as a clean sweep.
2. **Label provenance** (2026-08-22, ADR-003 am. 6): every visible GT box carries `label_src`, and
   `modeled`/`unknown` labels are refused. A full denominator with estimated positions produced a
   confident `AMBIGUOUS → default to (a)` from labels 198 px off the bird. Scoreable sources:
   `generator` (synthetic), `spawn` (static model unmoved — exact), `applied` (driver log).
   See [[bird-label-timing]].

Real-clip regression gate: `tests/fieldguard_planning/test_bird_label_timing.py` runs against the
COMMITTED flagship clip (not a fixture) and pins both halves of the diagnosis — the detections are
birds at a lagged time, and the modelled labels are ≥94.98 px away with IoU 0.000.

**How to apply:** any new "it works" perception/avoidance claim routes through `score.py` and emits
the same metric family; a missed bird (FN) is a safety bug reported apart from false positives,
never blended. Before quoting any rate from a real clip, check what the `labels =` line says.
