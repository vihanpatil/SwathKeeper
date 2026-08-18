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
| Week 5 — NDVI pipeline | 🟢 validation DONE: **all four gates GREEN live** (Gate 0 2026-08-05, Gates 1-3 2026-08-18); mount geometry corrected + gated (ADR-007 am. 5, 2.2 px); first tree-verified heatmaps committed. Open: recording throughput + ADR-003 re-run |
| Week 6 — real detector on the seam + comparison arm | ⏳ contract locked (ADR-009); implementation gated on the batched session |
| Week 7 — dashboard, demo video, README/GTM | ⏳ not started (deliberately last) |

Test suite: **131 green** (CI also gates seed-42 FNR, scenario-log drift, flight-log evidence).
Public main: current as of PR #13 (2026-08-18). Full narrative of how we got here:
`docs/BUILD_LOG.md`.

## Next up, in order

1. **Recording throughput** (the last quality gap; truth is proven, coverage is not): fused-frame
   delivery captures only a fraction of each flight (105 frames / 228-586 of 720 cells). First
   lever per config: `camera.update_rate_hz` 5 → 2 (halves render+transport load; at 3 m/s and a
   13.8 m footprint, 2 Hz sim still over-samples). Also candidates: bridge QoS, a leaner
   `ndvi_node` publish path. Measure with the same tree-check + coverage numbers.
2. **The full-coverage demo take** on the tuned stack (runbook: `docs/runbooks/FULL_PIPELINE_DEMO.md`
   — geometry gate + render probe + host quiet + birds after arming + Ctrl-C only after DISARM).
3. **ADR-003 real-render re-run** (criterion 3) + comparison arm (criterion 2): fix
   `eval/annotate_real_clip.py`'s pre-driver-start labels first (clamp t<0 to the spawn pose — the
   annotator already refuses to ship them, 17/105 flagged on the last clip), then
   `CLIP=<clip> bash eval/run_spike.sh` and record the numbers against the synthetic 0.445 bar.
4. **Doc long-tail**: apply the remaining documentation-review fix-list (78 items, ~70 remaining —
   list + exact edits preserved; criticals already applied).
5. **Week 7**: dashboard (replay + avoidance log + NDVI overlay on the shared cell grid), demo
   video, GTM pass.

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
