---
name: sim-image-state
description: Live state of the fieldguard-sim image + container (scipy gate, --shm-size) — the scipy rebuild is DONE, verified 2026-08-25; what still gates a booked take
metadata:
  type: project
---

**Verified on the host 2026-08-25 (`docker images` / `docker exec`), superseding the
"rebuild pending" state of 2026-08-24:**

- Image `fieldguard-sim:week1` built **2026-08-24 18:25 CDT**; `import scipy.ndimage` succeeds
  (**scipy 1.8.0**, jammy's system package).
- The *running* container `fieldguard-sim` (created 2026-08-22 09:33 CDT) **also** imports
  `scipy.ndimage` 1.8.0 and has **`/dev/shm` = 1.0 G**. So `fly_pipeline.sh preflight`'s scipy
  refusal will NOT fire, and the DDS SHM segments have their ceiling.

**Why this mattered:** `scipy.ndimage` is the morphology inside the ADOPTED ADR-003 am. 7 NDVI blob
detector, so an image without it cannot run `avoidance_node --detect` at all — and a runtime
`pip install scipy` was rejected as a band-aid (non-reproducible, re-runs every session). The
preflight gate is the safety net, not the plan.

**Still open before a booked take** (do not read the above as "cleared"):
- Version transfer: jammy ships scipy **1.8.0**, `requirements-eval.txt` pins **1.18.0**, the host
  has 1.13.1. `docs/runbooks/AVOIDANCE_REAL_DETECTION.md`'s second preflight re-scores the am. 7
  clip *in-container* and requires bit-identical boxes. That check is what actually clears the
  detector, not the import.
- `sim/docker/Dockerfile.ci` deliberately has no scipy (build-only image, never runs the detector),
  so CI does not exercise this import path.
- `--shm-size` is **creation-time only** (no `docker update`), and `sim_docker_run.sh` re-*attaches*
  an existing container — a container from before 2026-08-22 needs `docker rm` + re-run. The
  colcon workspace survives that: it lives on the named volume `fieldguard_ardu_ws`.

See [[project_ci_pipeline]], [[reference_pinned_versions]].
