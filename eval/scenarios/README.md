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
The fixtures above were generated with `swath_half_width_m = 7.5` = half the 15 m lane spacing, and
that number was **wrong — corrected 2026-08-25 (ADR-016)**. The 2026-08-18 "measurement" took
`2 · 15 · (320 / 520.006)` = 18.5 m, i.e. the **640 px** axis — but the ADR-007 mount puts image u+
along the flight direction, so lanes are separated across the **480 px** axis. The real cross-track
swath is `2 · (15 − 0.08) · (240 / 520.006)` = **13.772 m** (half-width **6.886 m**), so adjacent
15 m lanes do **not** overlap: they leave a **1.228 m unimaged strip**.
`coverage.DEFAULT_SWATH_HALF_WIDTH_M` is now derived from `config/ndvi_camera.json`
(`coverage.derive_swath_half_width_m`) instead of asserted, and the live node derives it at its own
cruise altitude. The 720/720 claim survives only by quantization — 2.5 m cell CENTRES sit at most
6.25 m from a lane, 0.636 m inside the true swath — which
`test_coverage.py::TestSwathComesFromTheCamera` now pins explicitly, alongside the
`test_negative_control_narrow_swath_opens_gaps` guard that proves the checker detects real gaps.
The committed fixtures here still carry 7.5 and are NOT regenerated by that change: they are
open-loop geometry fixtures, and re-cutting them is the re-fly's business.

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

### These fixtures are OPEN-LOOP: they do not model separation (2026-08-24, ADR-013 amendment 16)

`generate_flight_logs.py` prescribes the drone's position from `nominal_path()` on every tick and
never feeds the executor's commanded setpoint back into the next tick's `DroneState`. There is no
vehicle model here on purpose — the fixture's job is to hold the *stimulus* fixed so the **ledger** is
the only thing under test. Two consequences, stated so nobody has to rediscover them:

1. **`flown_path_enu` is the scripted lawnmower, not an outcome.** It is byte-identical to
   `nominal_path()` — pinned by `tests/test_ci_evidence_gate.py::...test_fixtures_are_open_loop...`.
2. **Their closest approach to the bird is therefore a scenario *parameter*, not a flown result.** The
   birds are parked ON the lane precisely so a dodge is forced, so **all four** sit inside the
   3.00 m `min_bird_clearance_m` bar by construction (0.00 m, 0.00 m, 0.00 m, 1.00 m — measured as
   path *segments*, 2026-08-26; the pre-back-port vertex-only geometry read `cov_bird_at_turnaround`
   at 7.00 m, a fly-through whose detection sat dead-centre of a 15 m leg, 7 m from the nearest
   vertex). Regenerating them under a *changed* control law leaves those four numbers bit-identical
   — measured 2026-08-24, which is the proof that no control law can move them.

**So `scripts/check_live_flight_log.py`'s CPA gate is NOT pointed at this directory, and these files
must NOT carry `SAFETY_FINDING.md` markers.** That gate scores *flown* separation and belongs to live
logs (`eval/results/live_flight_log_*.json`), where the path is telemetry. Filing an authored scenario
parameter as an acknowledged safety finding would dilute the one channel that carries the two real
historical breaches. What CI *does* gate here: the regenerate-and-diff reproducibility step, and the
ledger/geofence assertions in `test_safety_scenarios_pending.py` (kept non-skippable by the
committed-fixture assertion in `tests/test_ci_evidence_gate.py`).

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
2. **Camera swath — ⚠️ REOPENED then DERIVED (2026-08-25, ADR-016).** The 2026-08-18 "CLOSED" read
   the swath off the wrong image axis (9.2 m half-swath is the ALONG-track number). The true
   cross-track half-swath is **6.886 m**, so 15 m lanes leave a 1.228 m unimaged strip; the number
   is now derived from the camera rather than assumed, and 720/720 holds only by cell-centre
   quantization (0.636 m of margin). See §2.
3. **No scenario exercises SEPARATION** — open, and it is the R4 (escape-geometry) shaped hole.
   Every fixture here is open-loop (see §3), so the property "the vehicle stayed ≥ 3.00 m from the
   bird it dodged" has **no scenario in this directory at all** — it is measured only on live flights,
   by `check_live_flight_log.py`'s ground-truth CPA. That is why both historical breaches were found
   by a gate rather than by a test. Closing this needs a fixture that flies the executor's *commanded*
   setpoints (a vehicle model, however crude), which is exactly the R4 work deliberately cut from v1;
   until then, do not read a green scenario suite as evidence of clearance.
4. **Detection realism** — still open. ADR-003's FNR numbers are from a *synthetic* clip;
   `det_bird_over_low_ndvi` must be re-run on the real Gazebo NDVI render before the "no missed
   bird" claim is trusted. The render now exists and real clips are recorded (Gates 0-3 green,
   2026-08-18); what remains is the scored re-run itself — with gap 2 closed, this is genuinely the
   last confirmation-pending item in the project.
