Consolidated 2026-11-05 from flight-software-engineer, perception-ml-engineer (team v2); entries below keep their original dates and role names.

# software-engineer — memory index

## From flight-software-engineer
- [Node/topic map + coverage-debt/control-param notes](node_topic_map.md) — AP_DDS /ap/* contract, `geom.py` (the ONE point-segment primitive + AIRBORNE_Z_M), both frame decoders, control params (R2/R3 2026-08-24), depth wiring + its TWO startup refusals (exit 3 clock / exit 4 camera_info), two-half breach acknowledgement, test-flight floors
- [Live detection seam (ADR-009) + its offline numbers](detection_seam.md) — one gz clock, apparent-size ray, schema-2 run block, the 3 reviewed pins incl. TRUTH_BINDINGS (G47), why a breaching take reds CI
- [Throughput counters + what they measured](throughput_instrumentation.md) — the slop lever is DEAD, thermal is NOT render-limited, recorder logic drops nothing (2026-08-22)
- [Host-quiet is a flight gate](host_quiet_confound.md) — other Docker containers halved both bands and voided a flight; how to tell host load from a code regression
- [2026-08-25 flight: lead time, not ordering](flight_20260825_lead_time.md) — 0.0067 m CPA measured; nadir FOV gives ~0.4 s of warning and the executor has no maneuver-completion — reshapes R4
- [Plant model + the confound resolved](plant_model_and_confound.md) — the real GUIDED command path, effective a_max 1.05-1.85 vs 2.5, 08-18 fits NO plant, and the ADR-017 sweep's answer: no safe speed exists
- [Evidence-consumption seams](evidence_consumption_seams.md) — gate functions to CALL for verdicts/CPA/tree stats/the 3D mission geofence (R8), the declared bird-less mode `--no-birds` + its 6 falsifiers (incl. the WALL clock) and the missed-bird hole, `displacement_notes()` + the dodge/cruise-leak split (1.8 cm is NOT the GUIDED-window number), airborne-window rule, joins that don't exist, the log carries NO orientation and NO out-of-cylinder detection, + the depth-log bars
- [Red fixtures must fail the gate under test](feedback_red_first_fixtures.md) — the neighbouring-bar confound, the pin that reads its own constant, the fixture that picks the geometry where the mechanism cannot fail; mutate the resolution constant too; a fixture default that reads the module under test breaks the red run at COLLECTION
- [Forward depth camera + its booking gate](forward_depth_booking_gate.md) — /fg/depth/*, the 47.56 m corner horizon, the six-number live CLI, the ONE corner-ray primitive, band 13.05 m, sweeps authorise nothing
- [Booking ↔ flown speed (G128/G135/G137/G138)](booking_speed_enforcement.md) — the param is `WP_SPD` in m/s (sourced), TWO gated medians because the mission median hides the encounter (3.417 vs 9.012 on 08-25)
- [Extractability audit](extractability_audit.md) — what leaves the sim intact, no-packaging/REPO_ROOT costs, the two rival "covered" definitions + the 6.92 vs 7.5 m swath error, ecosystem form facts
- [Gates tool build (option C step 2)](gates_tool_build.md) — DFReader facts the adapter relies on, C-level parser spam, exact byte-skip holes, QA's named-FAIL kill rule, the G257 v0.2.0 sure/wide rule (2026-11-10)
- [Direction reset 2026-09-10](project_direction_20260910.md) — portfolio first, then 10 method conversations; wire program CUT, deletion aggressive, no new gate without retiring one

## From perception-ml-engineer
- [NDVI-vs-RGB spike (ADR-003)](project_ndvi_rgb_spike.md) — CLOSED, ADOPT: the live numbers on both renders, the 0.445 bar, first in-air evidence, and the threshold's FP characterisation
- [Criterion 2 RGB pixel study](project_criterion2_rgb_study.md) — ANSWERED 2026-08-26: RGB's honest ceiling, the GRVI birdness, trunk≡bird_1, and why the arm is not a second sensor (RETIRE-ARM)
- [Sensor horizon vs threat cylinder](project_sensor_horizon.md) — the nadir camera images ≤9 % of the 12 m cylinder; 0.175 s of lead on the 2026-08-25 breach; what R4 must be priced against
- [Bird label timing](project_bird_label_timing.md) — the render lags labels 0.12-0.81 s; only the applied-pose log makes a clip scoreable, and even it leaves ~15 px (IoU 0.51 on the CPA frame)
- [Eval harness core](reference_eval_harness.md) — eval/ pipeline, score.py's TWO refusal guards, the view-dir trick for scoring a clip without mutating it
- [Depth segmenter](project_depth_segmenter.md) — BUILT+SCORED+FIX-ROUND 2026-09-07, ADOPT: the constants and their sweep, the median-flip margin, and the findings that correct both design notes
