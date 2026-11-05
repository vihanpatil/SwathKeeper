---
name: portfolio-decision-2026-09-10
description: The owner's 2026-09-10 end-to-end-audit decision (portfolio first, market-test the pre-registered-gate METHOD, wire program cut, NDVI frozen) and the README truth-pass baseline it produced — read before any future GTM work
metadata:
  type: project
---

## THE DECISION (owner, 2026-09-10, after a full-repo audit)

SwathKeeper is a **portfolio project first.** After the honesty-and-scope floor lands, the owner
tests the market for the **METHOD** — pre-registered flight-evidence gates (a booking gate that
catches a real speed violation, a CPA gate that calls a bird strike before the flight is flown, a
dashboard that recomputes its own verdicts) — with **~10 conversations** with ArduPilot/PX4 autonomy
teams, labs, and Part-108-minded integrators, **before writing more code.** The drone-as-product path
(closing the control loop in sim, ≥20 seeded headless encounters clearing 3.00 m) is **deferred**
behind that market test, not abandoned. The **ADR-019 mapped-wire-corridor program is CUT from
scope** (not deferred — cut, so it doesn't get re-proposed). An NDVI/crop-health **analytics
product is REJECTED** (ADR-019 already called plain NDVI a commodity; the world has no health
variation to demonstrate anyway). Honesty is **widened, not narrowed**: all three bird-clearance
breaches now live on the front page, the INVALID verdict and the declared-red CI stay, deletion of
stale/duplicate material is aggressive.

**Why this matters for GTM specifically:** three independent critics (an agtech market strategist, a
principal autonomy engineer/hiring manager, and a founder/investor) converged on the same read — the
bird-dodge drone has no reachable buyer (every shipping ag OEM already ships radar detect-and-avoid;
bird strike is an insurance line, not a feature line), NDVI-as-sold is commoditized at
$1,900–2,000/yr with real imagery this project doesn't have, and **the one asset a stranger would
pay for is the verification discipline itself** — pre-registration, gates that catch themselves
failing, a booking gate that caught a real 1.8× tuning violation. That reframes who "the buyer" is
for any future pitch: not a farmer, not an ag-drone integrator — an autonomy/robotics team doing sim
V&V. Lead pitches with the gate/evidence story, not the drone-as-product story.

## The honesty baseline this produced (README truth pass, same session)

Applied directly to `README.md` (this agent's file). Re-verify before quoting elsewhere — these are
current as of `feat/depth-segmenter` @ `6bb1371` + this session's edits, not re-derived from a fresh
`eval/` run:

- **Three live avoidance flights, three breaches, same 3.00 m bar** (gate's current segment-path CPA
  recompute, all now disclosed in the README results table and narrative, not just the third):
  0.0393 m (2026-08-18, scripted `--demo`, ACKNOWLEDGED, exit 0) · 0.0391 m (2026-08-23, scripted
  `--demo`, ACKNOWLEDGED, exit 0) · 0.0067 m (2026-08-25, real self-detection, **INVALID**, exit 1).
  The marker-file numbers (0.0597 / 0.0518 m) are the *pre-2026-08-26* vertex-only geometry; the
  segment-path recompute is the current, lower number — quote the segment number.
- **The open-loop finding, stated first-person as the project's own discovery (new to the README —
  it was previously undisclosed there entirely):** on the 2026-08-25 take, GUIDED authority window
  **0.434 s**, achieved lateral displacement **0.018 m** against a **10 m** commanded divert. Nothing
  gates commanded-vs-achieved displacement — `verdict="accepted"` is a hardcoded constant. This is
  now the README's stated reason the next engineering quarter (if any) is closing the control loop,
  not adding sensors. Source: `docs/DECISIONS.md` ADR-013 am. 12 addendum;
  `eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md`.
- **"Detector rate 99.92 %" is relabelled pipeline liveness everywhere it's quoted**: 1301/1302
  frames *reached* the detector; it only *fired* on 2 of those frames (2 boxes) — the two frames all
  flight with the bird in the image. Never call 99.92 % a detection-quality number again.
- **No replan, no requeue** — ADR-002 scoped both out for v1. The architecture diagram's boxes are
  now labelled RESUME / LEDGER, not REPLAN / REQUEUE. The old "116 at-risk cells recovered across 4
  diverts" line is **gone** — it was one divert-audit summary listing 34 distinct cell_ids once per
  divert on a flight that closed 720/720 anyway, not a recovery count. Don't resurrect it without
  reframing what it actually measures.
- **"Adopted over a learned model" is gone** — no learned model was ever built or scored. The correct
  claim is "adopted over the RGB comparison arm on the same harness" (ADR-003 criterion 2).
- **The "81" number is the sweep's speed axis alone** (2–10 m/s), not a cross-product with escape
  candidates and plant models — say "81 mission speeds, each checked against every escape candidate
  and three plant models," never "81 combinations/cells/configurations."
- **Forward depth camera: built, scored, never flown** — new README section. Commissioned (ADR-020,
  6 gates D1–D6, booking gate PASS at 5.0 m/s / 1.780× margin). Scored (ADR-021): 85 stations of a
  cluttered, hand-labelled render, parked/static/noiseless, all 7 pre-registered bars PASS, range p95
  0.108 m. Cluttered acquisition measured 46.0 m — this **qualifies** the booking, it does **not**
  raise it, and its clutter robustness is honest only to **28 m** (every rung 30–46 m in that render
  happens to be sky-backed, not clutter-tested — this world's geometry, not a sensor property). Zero
  depth-camera flights exist. Never call this "documented growth path" again — that language predates
  the sensor existing in sim.
- **23 ADRs** (not 19), **9 agents** (not 8 — the 9th is `exec-council`, a Fable-run C-suite tier
  above the tiger team, convened sparingly for direction-level calls).
- **CI**: red on exactly one declared test
  (`tests/test_ci_evidence_gate.py::TestLiveFlightLogGateHasEvidence::test_step_passes_on_the_committed_evidence`);
  an allowlist test (devops-owned, concurrent with this session) is asserted to catch any other red.
  If that allowlist test doesn't actually exist yet when you next check, the README oversells this —
  verify `.github/workflows/ci.yml` before repeating the claim.
- **Claims ceiling unchanged: "sim-demonstrated, evidence-gated."** New this session: a standalone
  "What this is, and what it is not" block near the top of the README states the sim-lab scope
  plainly (teleported birds with no collision geometry — a strike is physically impossible; NDVI is
  canopy-vs-soil on four typed temperatures, not health; the flying image isn't SHA-pinned; nothing
  has flown on hardware) *before* the highlight bullets, not after.
- **"What's next" (renamed from "What I'd do next") now reads**: (1) finish the floor; (2) the ~10
  conversations, with an explicit kill criterion (0/10 → strong portfolio, no product); (3) only if
  the drone is pursued, close the control loop with a written ≥20-seeded-encounter kill criterion.
  Wire program and further NDVI work are explicitly logged as **cut**, not deferred. No "product"
  word appears in that section.

## Process notes for next time

- **No Bash/file-delete tool was available in this session.** `docs/drafts/README_FULL.md` and
  `README_SKELETON.md` were **stubbed** (overwritten with a one-line "superseded, run `git rm`"
  pointer), not actually deleted — flag this to whoever has shell access next. Check whether they've
  since been removed before assuming they still need it.
- **Cross-file fix owed, not mine to make:** `tests/README.md:12` still names
  `docs/drafts/README_FULL.md` as one of the "four homes" for the suite-total quote. Once that file
  is actually `git rm`'d, that line needs updating (three homes, not four) by whoever owns
  `tests/README.md`.
- The suite-total cell in the README's evidence table (`1599 passed, 1 failed, 2 skipped, 0 xfail`)
  was **left untouched** per the task's instruction that the orchestrator re-quotes it — don't
  "helpfully" update it without checking whether that's still the rule.

See also [[week7-gtm-decisions]] (superseded in part, noted inline) and [[headline-metrics]] (the
2026-08-26 numbers — still correct as *history*, but the breach count and CI sentence there predate
this session; this file is the current baseline).
