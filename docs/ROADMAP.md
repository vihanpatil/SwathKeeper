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
| Week 5 — NDVI pipeline | 🟢 validation DONE: **all four gates GREEN live** (Gate 0 2026-08-05, Gates 1-3 2026-08-18); mount geometry corrected + gated (ADR-007 am. 5, 2.2 px); first tree-verified heatmaps committed. Recording throughput instrumented + 3× improved 2026-08-21 (5.1× frames, 2.3× cells, ADR-013 am. 6). Open: ADR-003 re-run, and the two-stage frame loss that remains — transport + pairing (am. 6a) |
| Week 6 — real detector on the seam + comparison arm | ⏳ contract locked (ADR-009); implementation gated on the batched session |
| Week 7 — dashboard, demo video, README/GTM | ⏳ not started (deliberately last) |

Test suite: **291 green, 2 skipped** — 258 in `tests/fieldguard_planning` plus 33 host-side launcher
tests in `tests/test_fly_pipeline.py`, which need neither Docker nor tmux. CI discovers both (it ran
only the first until 2026-08-18) and also gates seed-42 FNR, scenario-log drift, flight-log evidence.
Public main: current as of PR #22 (2026-08-20). Full narrative of how we got here:
`docs/BUILD_LOG.md`.

## Next up, in order

1. **Recording throughput — instrumented, 3× better, still the gap (2026-08-21).** Four `test-flight`s, one
   variable at a time, same `test_2lane` mission, with `camera_info_frames` (692 / 699 / 696 / 698)
   as the control that all four saw the same exposure window. The fuser counters built on 2026-08-20
   (ADR-013 am. 5) flew for the first time and **named the starving stage on flight one**: the RGB
   *image* band alone — `red_frames` 73 against 692 `camera_info` messages off the *same sensor
   tick*, with `dropped_pair_count` **0**. Not a render problem, and not the stale-pair guard: for
   the frames that never arrive, a payload-size-dependent transport loss. (Pairing turns out to lose
   a further ~38 % of the frames that *do* arrive — ADR-013 am. 6a, found after these flights.)

   | flight | config | red/ticks | fused | recorded | cells |
   |---|---|---|---|---|---|
   | baseline | as-was | 73 / 692 = **10.5 %** | 45 | 17 | 158 |
   | lever A | bridge QoS best_effort | 126 / 699 = 18.0 % | 78 | 41 | 125 |
   | lever B | preview publish gated | 113 / 696 = 16.2 % | 76 | 36 | 150 |
   | **both (kept)** | A + B | **217 / 698 = 31.1 %** | **129** | **86** | **368 / 720** |

   **Both levers KEPT — nothing reverted.** *A:* the ros_gz bridge publishes images RELIABLE while
   every consumer subscribes BEST_EFFORT, so the reliable half was retransmission machinery for
   ~900 KB samples nobody wanted retransmitted; it is **not settable in the bridge yaml** at the
   pinned SHA (`bridge_config.cpp:28-36` — nine keys, no QoS, unknown keys silently ignored) but is
   a per-topic ROS parameter (`factory.hpp:66-79`), now on the Shell-2 one-liner and verified bound
   before it flew. *B:* `/fg/ndvi/preview` is human-only and **nothing subscribes to it**, yet every
   fused frame paid a colormap plus two 921,600 B copies plus a no-reader publish on the executor
   that should have been draining the RGB subscription; now guarded by `get_subscription_count()`.
   Full record + rejected alternatives: **ADR-013 amendment 6**. Clips
   `eval/results/clips/real_flight_20260821T03{2316,3001,3644,4116}Z`, gate records
   `eval/results/testflight_gate_20260821T03{2657,3342,4029,4504}Z.json`.

   **Honest reading:** recorded frames are up **5.1×** and cells imaged **2.3×** against the same
   day's baseline; 368/720 also beats the previous all-time valid 2-lane best (291 off 48 frames,
   2026-08-18). It is *not* solved, and the remaining loss is in **two** stages, not one: 69 % of RGB
   frames still die in transport, and ~38 % of the survivors then never pair — `red_frames −
   fused_count − dropped_pair_count` = 28 / 48 / 37 / 88 across the four flights, flat across both
   levers because neither touched pairing. End to end that is 12.3 % of sensor ticks reaching the
   clip, so **the next lever is not necessarily another transport lever** (ADR-013 am. 6a).
   Two traps for whoever picks this up: (a) judge levers by
   `red_frames / camera_info_frames`, **not** by `cells_imaged` — lever A's own flight imaged fewer
   cells than baseline (125 vs 158) on 2.4× the frames, purely because its extra frames landed while
   the vehicle was slow (climb, far-end turn), and coverage is bought by frames *spread along the
   lanes* (survey-altitude frames off the takeoff point: 6 → 42); (b) the amendment-4 evidence floor
   (12 frames / 40 cells) was deliberately **not** raised to match the new yield — one healthy run at
   the new config is not enough, and it should rise after a second.
   **Lever already disproven — do not retry:** `camera.update_rate_hz` 5 → 2 (2026-08-19) made
   delivery 16× worse (3 frames / 1 of 720 cells against 48 / 291), with RTF unchanged (0.585 vs
   0.561) and the mission flown identically; `eval/results/testflight_gate_20260819T021136Z.json` vs
   `..._20260818T222031Z.json`, reasons preserved in `config/ndvi_camera.json`'s `update_rate_note`.
2. **The full-coverage demo take** on the tuned stack (runbook: `docs/runbooks/FULL_PIPELINE_DEMO.md`
   — geometry gate + render probe + host quiet + birds after arming + Ctrl-C only after DISARM).
   The one-command launcher now exists (`scripts/fly_pipeline.sh`, ADR-013) with a scripted
   test-flight regression gate (amendment 2, first PASS 2026-08-18) — demo flights still stay
   human-flown at the MAVProxy prompt; the launcher removes the bringup toil around that step.
3. **ADR-003 real-render re-run** (criterion 3) + comparison arm (criterion 2): the annotator
   blocker is FIXED (2026-08-20, ADR-012 amendment 1 — `pose_at`'s loop wrap is now forward-only,
   so pre-driver-start frames label at the spawn pose the static birds actually sit at, instead of
   being flagged unshippable as 17/105 were on the last clip). Still needs the full-coverage
   recording from item 2, then `CLIP=<clip> bash eval/run_spike.sh` and record the numbers against
   the synthetic 0.445 bar.
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
