# Safety scenarios — spec format, the coverage-debt ledger invariant, and the starter set

Owner: `qa-safety-reviewer`. This directory holds **reproducible, fixed-seed safety scenarios**, each
carrying an explicit **PASS/FAIL safety property**. It is the QA scaffolding built in Week 2 so the
Weeks 3-4 reactive-avoidance loop is testable from day one — specifically so it is *impossible* for
the loop to **silently skip a coverage cell** or **silently miss a bird** without a test going red.

"No 'it works' without a metric or a reproducible scenario" (CLAUDE.md). A scenario here IS that
reproducible scenario; `eval/score.py` and `src/fieldguard_planning/{coverage,geofence}.py` provide
the metrics.

---

## 1. Scenario spec format

One YAML per scenario (flat in this directory, matching `spike_birds.yaml`). The Week 3-4 loop, when
run on a scenario, writes its artifacts to `eval/scenarios/<name>/` (at least `flight_log.json`).

```yaml
name: <slug>                     # also the output subdir: eval/scenarios/<slug>/
kind: coverage | detection | geofence
adversarial: true | false
status: runnable-now | pending-avoidance-loop
seed: <int>                      # fixed; birds are scripted (no runtime randomness) so this is exact

safety_property:
  id: <slug>
  statement: <one sentence, the thing that must hold>
  metric: <coverage.check_ledger | coverage_from_path | geofence | score.per_bird_track_fnr>
  pass_when: <condition>
  fail_when: <condition — the real-world consequence if violated>

setup:
  mission: config/missions/boustrophedon.waypoints
  field_polygon: config/field_polygon.json
  static_obstacles: config/static_obstacles.json
  birds: <inline trajectory list OR a ref to config/birds/*.json>

runner:
  now: <test id if runnable now, else null>
  pending_on: <what artifact must exist to activate — usually eval/scenarios/<name>/flight_log.json>
  activates: <test id in tests/fieldguard_planning/test_safety_scenarios_pending.py>
```

The pending tests are **self-activating**: they skip only while `eval/scenarios/<name>/flight_log.json`
is absent, and go live the instant the loop produces one — no test edits required in Week 3.

---

## 2. The coverage-debt ledger invariant (THE core property, executable)

CLAUDE.md's central correctness claim is: *avoidance never silently drops a coverage cell.* That is
vague until we pin what "cell" and "dropped" mean. Here is the concrete, checkable contract —
implemented in `fieldguard_planning.coverage.check_ledger`, asserted by
`tests/fieldguard_planning/test_coverage.py` (now) and
`test_safety_scenarios_pending.py::TestNoSilentlySkippedCell` (Week 3-4).

**The grid.** The field polygon is partitioned into a *canonical, deterministic* grid
(`build_grid`, default 2.5 m cells → 720 cells over the 75×60 field). Same polygon + cell size ⇒
byte-identical cell set and ids. "cell_i_j" means the same square in a test, a scenario, and a log.

**Terminal statuses.** Each cell ends the mission with exactly one terminal status:
- `covered` — the flown path imaged the cell (its center fell within the camera swath of some leg).
- `debt` — the cell was not imaged and is *explicitly recorded as outstanding coverage debt*.

`requeued` is **an event, not a terminal status.** A cell dropped by one avoidance and re-added to
the plan is logged as a `requeue_event`; it terminates `covered` if later imaged, else `debt`.

**The invariant** (a flight log's `coverage_ledger` is honest iff all hold):
- **P1 — Partition.** Every canonical grid cell appears in the ledger *exactly once*. A cell **absent
  from the ledger is a SILENTLY-SKIPPED cell** — the exact failure this whole property forbids, and
  the loudest fail. Double-logging a cell (duplicate) is also a fail (ambiguous accounting).
- **P2 — Status.** Every terminal status is `covered` or `debt`. `requeued`/unknown ⇒ fail.
- **P3 — Known cells.** No ledger cell id is outside the canonical grid.
- **P4 — No lying.** (Cross-check, `TestNoSilentlySkippedCell`.) A cell marked `covered` must
  *actually* be within swath of the flown path. Prevents a loop from zeroing its debt by fiat.

**What the invariant does and does not require:**
- It does **NOT** require `debt == 0`. Per **ADR-002**, v1 = "avoid, return to next waypoint" is
  *allowed* to leave debt — as long as the debt is **explicit** (present as `debt`, never absent).
  The invariant proves the loop is **honest**, not that it is complete.
- The **stretch goal** (full coverage-debt reconciliation, ADR-002) is the stricter, *separate*
  assertion `debt_count == 0`. Assert that only when testing the stretch behavior.

**Flight-log contract** (what the Week 3-4 loop must emit; mirrored in
`test_safety_scenarios_pending.py` — keep both in sync):

```json
{
  "scenario": "<name>", "seed": 42,
  "cell_size_m": 2.5, "swath_half_width_m": 7.5,
  "flown_path_enu": [[e, n, u], "..."],
  "coverage_ledger": [{"cell_id": "cell_3_7", "status": "covered"}, "..."],
  "requeue_events": [{"cell_id": "cell_3_7", "t_s": 12.4}],
  "detection": {"ground_truth": "<path>", "detections": "<path>"}
}
```

### The swath caveat (do not let coverage rot silently)
`swath_half_width_m = 7.5` = half the 15 m lane spacing. Full coverage HOLDS only if the real
downward NDVI camera's ground swath at 15 m altitude is ≥ 15 m. **Measured 2026-08-18.** The
ADR-007 camera's live `camera_info` from the first real-render flight
(`eval/results/clips/real_flight_20260818T221641Z/meta.json`: `fx = 520.006`, width 640 px) puts
the across-track ground swath at the 15 m mission altitude at `2 · 15 · (320 / 520.006)` = **18.5
m**, i.e. half-width **9.2 m** against the 7.5 m the plan assumes — adjacent lanes overlap by ~3.4
m, so full coverage holds with margin.
`test_coverage.py::test_negative_control_narrow_swath_opens_gaps` still proves the checker detects
inter-lane gaps, so the guard stays if the camera is ever narrowed or the altitude lowered.

---

## 3. Starter scenario set

| scenario | kind | adversarial | property | now / pending |
|---|---|---|---|---|
| `nominal_coverage_baseline` | coverage | no | nominal plan covers every cell; ledger balances | **now** |
| `nominal_geofence_baseline` | geofence | no | only the row-0 lane breaches XY; safe by altitude | **now** |
| `cov_bird_over_cell` | coverage | no | dodge over a cell ⇒ cell covered OR explicit debt | ✅ **activated** |
| `cov_bird_at_turnaround` | coverage | **yes** | dodge during lane reversal drops no cell | ✅ **activated** |
| `cov_two_birds_simultaneous` | coverage | **yes** | back-to-back dodges keep ledger honest | ✅ **activated** |
| `det_bird_crosses_path` | detection | no | per-bird-track FNR == 0 (no missed bird) | pending (Weeks 5-6) |
| `det_bird_over_low_ndvi` | detection | **yes** | FNR == 0 over bare soil (ADR-003 FN risk) | pending (Weeks 5-6) |
| `geo_avoid_into_tree` | geofence | **yes** | dodge never enters a tree band+radius, nor exits field | ✅ **activated** |

_Activated 2026-08-05: `eval/scenarios/generate_flight_logs.py` drives the real policy+executor to
produce each `flight_log.json`, so the matching `test_safety_scenarios_pending.py` assertions now run
and pass. The 2 `det_*` (detection-FNR) scenarios stay pending — they need detection artifacts from the
real NDVI render (Weeks 5-6), not an avoidance flown path; fabricating those would defeat the metric._

**Runnable-now** scenarios are asserted by `tests/fieldguard_planning/test_coverage.py` and
`test_mission_geofence.py` against the *current* mission — they are the baseline the avoidance loop
must not regress below. **Pending** scenarios are asserted by `test_safety_scenarios_pending.py`,
which activates each automatically once its `flight_log.json` exists.

Run everything (now-tests pass, pending-tests skip cleanly):

```bash
python3 -m unittest discover -s tests/fieldguard_planning -v
```

---

## 4. Known open safety gaps

1. **Geofence 3D gate — ✅ CLOSED (Weeks 3-4).** The XY nominal check (`geofence.is_point_excluded`)
   is safe for the 15 m cruise *only* by 11.5 m of vertical separation, so a maneuver that **descends
   into the ≤ 5.5 m tree band** would turn that benign overlap into a strike. The 3D gate
   `geofence.is_safe_3d` now exists and the avoidance policy + executor vet every dodge setpoint through
   it (a point over a tree at altitude is safe; one in the canopy band is rejected → HOLD). The
   `geo_avoid_into_tree` scenario asserts the flown path never enters a tree's radius AND danger band.
2. **Camera swath — ✅ CLOSED (2026-08-18).** Live `camera_info` from the first real-render flight
   gives a 9.2 m across-track half-swath at 15 m altitude against the 7.5 m the mission plan
   assumes — lanes overlap, the coverage guarantee holds. See §2.
3. **Detection realism** — still open. ADR-003's FNR numbers are from a *synthetic* clip;
   `det_bird_over_low_ndvi` must be re-run on the real Gazebo NDVI render before the "no missed
   bird" claim is trusted. The render now exists and real clips are recorded (Gates 0-3 green,
   2026-08-18); what remains is the scored re-run itself — with gap 2 closed, this is genuinely the
   last confirmation-pending item in the project.
