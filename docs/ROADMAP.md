# SwathKeeper — Roadmap (living document)

Owner: `product-lead`. Update at each `/standup`. History lives in `docs/BUILD_LOG.md`; decisions
in `docs/DECISIONS.md`; this file is only ever **the current truth and what's next**.

**Deadline status (2026-08-18):** the original ~7-8-week / Europe-trip hard stop is **dropped**
(user decision). Quality over calendar — but the **standing scope guard survives the deadline**:
nothing gets added to scope without something else being cut in the same breath, and every
`/standup` is still measured against protecting the demo + dashboard exit.

## Where we are (2026-08-18)

| Phase | Status |
|---|---|
| Weeks 1-2 — sim foundation + detection decision | ✅ complete (2026-08-04) |
| Weeks 3-4 — reactive avoidance + coverage-debt loop | ✅ complete, **demonstrated live** (2026-08-05) |
| Week 5 — NDVI pipeline | 🟡 in flight: ADR-007 landed, **Gate 0 GREEN live**; fusion/georef/stitch built + tested; Gates 1-3 + real-render numbers pending the batched session |
| Week 6 — real detector on the seam + comparison arm | ⏳ contract locked (ADR-009); implementation gated on the batched session |
| Week 7 — dashboard, demo video, README/GTM | ⏳ not started (deliberately last) |

Test suite: **131 green** (CI also gates seed-42 FNR, scenario-log drift, flight-log evidence).
Public main: current as of PR #13 (2026-08-18). Full narrative of how we got here:
`docs/BUILD_LOG.md`.

## Next up, in order

1. **The ONE batched Docker validation session** (human; runbook: `docs/runbooks/NDVI_VALIDATION.md`
   — resume at **Gate 1**, Gate 0 already passed):
   - Gate 1: `ros_gz` bridge — 4 `/fg/sensor/*` topics, encodings rgb8/mono16, ~5 Hz, intrinsics.
   - Gate 2: canopy ≈ 0.85 > soil ≈ 0.20 > bird ≈ 0.05 with real gaps (`scripts/check_ndvi_bands.py`
     — the flat-NDVI silent-failure check).
   - Gate 3: Week-3 avoidance regression on the NDVI-mounted vehicle model.
   - Then: full boustrophedon flight with `ndvi_node` live; record frames + pose in the spike
     schema; **commit the evidence artifacts** (timestamped logs + clip metadata — the 2026-08-05
     demo log was lost to a clobber; that must not repeat).
   - If time remains: local `Dockerfile.ci` build + in-container smoke (`docs/runbooks/SIM_CI.md`
     human steps 1-2 — these do NOT require anything merged).
2. **Phase C closeout** (agent, 1-2 days after the session):
   - Stitch the recorded flight (`scripts/stitch_ndvi.py`) → committed heatmap artifact
     (**Weeks 5-6 exit criterion 1**).
   - `eval/run_spike.sh` on real frames → ADR-003 confirmed or the delta recorded (**criterion 3**);
     comparison-arm write-up (**criterion 2**). The standing bar is the **synthetic-clip** blob
     precision of 0.445 — the real render has produced no numbers yet.
   - Mechanical doc flips (ADR-007 confirmed banner, statuses).
   - `sim-image.yml` dispatch → `build-test-sim` from main, inside its original timebox; on failure
     apply the documented cut-list (`docs/runbooks/SIM_CI.md`) and move on.
3. **Week 6 go/no-go** (product-lead): real NDVI-blob detector on the `detection_source` seam per
   ADR-009 — only if Phase C lands cleanly; the pre-authorized fallback is scripted detection for
   the demo, recorded in DECISIONS.md if taken.
4. **Week 7:** light dashboard (replay + avoidance log + NDVI overlay on the shared cell grid),
   60-90s demo video, GTM pass (`gtm-narrative-lead`).

## Explicit stretch goals (documented, NOT v1 blockers)
- Full coverage-debt reconciliation (v1 ships "avoid, return to next waypoint" + honest debt,
  ADR-002; AP_DDS exposes no mission-current service at the pinned SHA, so this is genuinely
  harder, not just deferred — source-verified, see ADR-006).
- Scaling from 2-3 birds to a flock / higher obstacle density.
- Second-sensor config promoted from comparison arm to a supported operating mode.
- Live in-node NDVI stitching (offline is the v1 decision, ADR-010).

## Cut / deferred log
_(product-lead records cuts here with date + reason — interview material.)_

- **2026-08-18 — code-identifier rename deferred (ADR-011):** `fieldguard_planning`, `fg_`/`/fg/*`,
  `farmguard_field.sdf`, `fieldguard-sim` image stay under the old name; the `/fg/*` contract is
  embedded in ADR-007 and partially live-verified, and renaming verified interfaces for cosmetics
  re-opens confirmed state for zero functional gain.
- **2026-08-05 — no YOLOv8 bolt-on for resume keywords.** The metric-driven story is stronger:
  a classical blob baseline cleared the safety bar; any learned model must beat it on the same
  harness (the 0.445 synthetic-clip precision bar) before it earns a place.
- **2026-08-05 — no retrofitted startup narrative.** Sim-only, solo, portfolio-honest framing is
  the asset; inflating it converts the honesty in every ADR into an interview red flag.
- **2026-08-05 — colcon/ament packaging of the planning package.** Zero demo value; PYTHONPATH
  works in-container. Restated 2026-08-18 (audit re-confirmed the cut).
