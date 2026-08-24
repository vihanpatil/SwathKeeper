---
name: image-rebuild-pending-scipy
description: 2026-08-24 — sim image gained python3-scipy; the image MUST be rebuilt before the next avoidance-with-real-detection flight can be booked
metadata:
  type: project
---

`sim/docker/Dockerfile` gained `python3-scipy` (jammy 1.8.0) on 2026-08-24, and
`scripts/fly_pipeline.sh preflight` now hard-fails if `scipy.ndimage` is not importable in the
`fieldguard-sim` container. Until `bash scripts/sim_docker_build.sh` + `bash scripts/sim_docker_run.sh`
are run, **`up` refuses** — by design.

**Why:** `scipy.ndimage` is the morphology inside the ADOPTED ADR-003 am.7 NDVI blob detector
(`fieldguard_planning.ndvi_detect`, per-bird FNR 0.000). A numpy reimplementation would be a
different detector wearing the same verdict, and a runtime `pip install scipy` was explicitly
rejected as a band-aid (non-reproducible, re-runs every session).

**How to apply:** before pricing/booking a Docker session that runs `avoidance_node --detect`,
confirm the rebuild happened. Version-transfer caveat: jammy ships scipy **1.8.0**,
`requirements-eval.txt` pins **1.18.0**, this host has 1.13.1 — the runbook's second preflight
re-scores the am.7 clip in-container and requires bit-identical boxes. `sim/docker/Dockerfile.ci`
was deliberately NOT changed (build-only image; it never runs the detector), so CI does not
exercise this import path.

See [[project_ci_pipeline]], [[reference_pinned_versions]].
