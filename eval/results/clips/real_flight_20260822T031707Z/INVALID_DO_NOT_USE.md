# VOID — do not use for absolute yields or as a baseline

F5a, the first instrumented-baseline attempt (ADR-013 amendment 7). A 12-container Supabase stack
(unrelated user project) STARTED on the shared Docker VM 68 s into this flight (03:17:48–03:20:10Z)
and halved both image bands together. Exposure control was in band (`camera_info_frames` 690) and
RTF normal (~0.545) — neither gate detects host contention, which is itself a finding.

**What this clip IS valid for:** ratio-level counter evidence (load-independent). First live
measurement of `nir_camera_info_frames` (689/690 → NIR render exonerated), the unpaired-red
histogram (79/79 `ge_tick` → slop lever dead), recorder attribution (received→written 100 %,
`on_ndvi_wall_ms` p95 17.3 ms → recorder logic + disk exonerated). See the gate record
`eval/results/testflight_gate_20260822T032143Z.json` and ADR-013 amendment 7.
