# VOID — do not use for absolute yields or as a baseline

F5b, the host-quiet re-fly of F5a (ADR-013 amendment 7). Host verified quiet throughout (16 load
samples, peak single container 52.2 % for ≤15 s), yet `red/ci` reproduced F5a's shortfall
(17.31 % vs F4's 31.09 %) — which converted the working theory from "host burst" to **environment
drift**: the F1–F4 baseline was measured on a Docker VM running `fieldguard-sim` alone; this flight
ran against 13 containers. A same-day interleaved bench A/B then measured the UNINSTRUMENTED code
at 7.19–15.58 % on this host, exonerating the L0 instrumentation and confirming drift as the cause.

**What this clip IS valid for:** ratio-level counter evidence. `nir_camera_info_frames` 676/676
(NIR ticks at full 5 Hz — transport-limited, settled), histogram 70/70 `ge_tick` (slop lever dead,
second independent flight), received→written 100 % with `on_ndvi_wall_ms` p95 7.9 ms. Tree gate
correctly reported `PASS (vacuous)` on the 15-cell map. See
`eval/results/testflight_gate_20260822T033735Z.json` and ADR-013 amendment 7.
