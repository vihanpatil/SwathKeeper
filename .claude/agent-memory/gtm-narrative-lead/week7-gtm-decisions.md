---
name: week7-gtm-decisions
description: Week 7 GTM ground rules the user set on 2026-08-26 — audience, demo format, dashboard shape, and the review-before-ship rule for the README
metadata:
  type: project
---

Week 7 (dashboard, demo video, README/GTM) went **ACTIVE 2026-08-26** — user chose option A
(Week 7 now, forward sensor + re-fly after). Recorded in `docs/ROADMAP.md` Next-up 1/6 and
`docs/DECISIONS.md` ADR-017 am. 1.

**The four decisions the user made, which govern everything I write:**
1. **Audience: robotics / autonomy hiring managers first.** Applied-ML and ag-tech framings are
   secondary; lead with the reactive loop and the safety-verification arc, not NDVI.
2. **Demo format: a narrated 2-3 minute walkthrough**, voiceover recorded by the *user*. Scripts
   must read naturally when spoken aloud, first person, engineer-showing-their-work — never a
   marketing read. Spell numbers the way they are *said* ("six point seven millimetres").
3. **Dashboard = static client-side HTML on GitHub Pages** (ADR-018), one click from the README:
   flight replay + avoidance event log + NDVI overlay. No server, no CDN.
4. **Nothing outward-facing ships without user review.** README/doc shaping is collaborative, not
   delegated — produce review-ready drafts in `docs/drafts/`, never edit `README.md` directly
   until the user has reacted.

**Why:** the user's standing directive is to be looped in on all README/doc shaping (attached to
the ADR-017 am. 1 sequencing decision), and the honest-measurement story is fragile to
over-polishing — a rosier draft would undo the thing that makes it valuable.

**How to apply:** open any Week-7 task by re-reading `docs/ROADMAP.md` "Where we are" and the
newest `docs/BUILD_LOG.md` entry for fresh numbers ([[headline-metrics]] decays fast), draft into
`docs/drafts/`, list the decisions the user should react to first, and list what I could not source
rather than filling the gap. Story selection: [[safety-asterisk-and-story-bank]]; wording rules:
[[narrative-guardrails]].

**Ruling 002 RATIFIED 2026-08-26 (ADR-019) — it rewrites "What I'd do next" in every outward doc.**
The ordered program is now: (1) forward **depth** camera on its own aperture, replay-specced
(≥1.25 s resolving lead, 17.8–38.7 m forward horizon at flown speeds; tilt stays rejected);
(2) a **bar-clearing bird dodge** booked only behind the no-failure-theater gate (offline predictor
on the new sensor's `camera_info` clears 3.00 m with ≥1.3× lead margin on the conservative plant —
the next take is *designed* to pass); (3) the **mapped-wire corridor demo** (fresh per-field survey,
never a GIS layer; metres of buffer from 0.15–1.4 m catenary sag; no camera wire detection
promised). Week 7 shrinks to its user-gated remainder: voiceover, README application, Pages.

**Full README draft (all §C sections written) lives at `docs/drafts/README_FULL.md`**, contract at
`docs/drafts/README_SKELETON.md` (§A frozen verbatim, §B approved first-person).

**Standing narrative spine ratified by the user (Council Ruling 001):** the *evidence culture* is
the asset — the flagship flight failed its own pre-registered safety gate, the team then measured
offline that no speed makes the nadir sensor safe, and the roadmap redirected on that measurement.
Headline sentence: **"the system found its own sensor's limit and refused to fly what it can't
pass."** Framing constraints that travel with it: no startup narrative (sim-only, solo,
portfolio-honest); "small dynamic intruder, exercised on scripted birds" (birds have no commercial
referent); the NDVI detector is scaffolding, the seam is the product surface; one honest line about
the SwathKeeper/`fieldguard` code-identifier split (ADR-011).
</content>
</invoke>
