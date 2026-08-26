# DRAFT — demo video package for user review (2026-08-26, revision 2)

**Status: DRAFT for review. Nothing recorded, nothing committed to the README.**
Format: **narrated walkthrough, voiceover recorded by the user** — first person, spoken, engineer
showing their work. Never a marketing read.

**Revision 2 restructure (user direction, 2026-08-26):** the video no longer opens on the failure.
It opens on the project — what it is, what it does, what it achieves — then how it works, then the
flight as a story. **The breach is the twist and the payoff, not the hook.**

**Engagement is a hard requirement:** it has to hold a curious sixteen-year-old with no background
*and* a hiring manager who has shipped autonomy. The technique is **dual register** — short
concrete sentences carry momentum, exact numbers and real terms (used sparingly, explained in
passing) carry credibility. Explain *up*: make the real thing vivid, never simplify at the expert's
expense.

**Production rules that follow from that:**

* **Something moves in every shot.** Onboard footage, the replay path drawing itself, the heatmap
  filling in, a slide revealing. No static frame runs longer than ~3 s.
* **No log-scrolling.** Terminal appears exactly once, for ~3 s, and only where it punches.
* **The no-safe-speed result is a designed slide with a progressive reveal**, never a JSON
  screenshot.
* **Document scrolls get ~4 s and one highlighted line**, or become a pull-quote card.

Runtime as scripted: **3:10**. Narration **~470 words** (~148 wpm with the marked beats).

## (a) Shot list

| # | Time | Dur | Footage | On screen — motion is mandatory | Narration |
|---|---|---|---|---|---|
| 1 | 0:00 | 0:18 | **H** — onboard camera flyover (ffmpeg-assembled, airborne window only) | Cold open on the drone's-eye view: crop rows sliding past, a tree row crossing frame. Title card fades in over motion at ~0:10, does not stop it | "This is a crop-survey drone flying a field the way a lawnmower cuts grass — lane after lane, until every square metre has been looked at. It's built entirely in simulation; this is its actual onboard camera. The interesting part is what happens when something gets in the way." |
| 2 | 0:18 | 0:26 | **A** — dashboard replay, wide, playing at ~4× | Top-down field: the flight path draws itself lane by lane and the NDVI heatmap fills in behind it in the same motion. This shot alone should sell the product | "Commercial ag drones already fly surveys like this, but they fly a route planned before takeoff and stick to it. Mine has to handle things the flight plan never knew about. And afterwards it has to prove it still covered the whole field — because a strip of crop nobody looked at is a strip nobody knows is dying." |
| 3 | 0:44 | 0:34 | **A** — replay scrubbed to the encounter, event log beside it; **C** cut-in at ~1:02 for 3 s | Path deviating out of the lane in real time; event rows lighting up one at a time as it happens (detection → takeover → dodge accepted → resume). The 3 s cut-in is the real NDVI frame with the detector's box on the bird — use `gtdet_a_ndvi_direct_ndvi_frame_000964.png` (both boxes, near-coincident) and **not** a ground-truth-only still of frame 965, which reads as a miss it wasn't. Then straight back to motion | "Here's the loop. The camera picks up a bird. My software works out how far away it is from how big it looks, picks a dodge point, checks the whole path it would fly against the surveyed tree rows, then commits to that point — so a flickering detection can't yank the aircraft around mid-manoeuvre. It takes control from the autopilot, dodges, gives control back, and settles the bill: every cell the detour skipped is either re-covered or recorded as debt." |
| 4 | 1:18 | 0:24 | **A** — ledger panel counting up, then **B** heatmap with tree markers dropping in | Coverage counter animating to 720 / 0; then the finished heatmap with the 18 tree markers landing on the bright cells one by one | "On this flight, that all worked. Four dodges accepted, eight more rejected for cutting too close to a tree. Seven hundred and twenty cells covered, zero debt. And from the same flight, the same camera: the crop-health map — all eighteen trees show up, every bright cell within two metres of a real one." |
| 5 | 1:42 | 0:32 | **A** replay, slowed to ~0.25× at the closest-approach moment, drone and bird markers converging; then **G-card** (pull-quote) | The two markers slide together and a distance readout ticks down to `0.0067 m` and holds. Cut to a clean pull-quote card of the pre-registration line — white text, one line highlighted, 4 s | "And on that same flight, the drone passed six point seven millimetres from the bird — horizontally, four metres above it, which is well inside the separation rule. So the flight is invalid: it failed its own safety check. I'd written down before takeoff that this could happen, in the runbook, so it couldn't be reinterpreted afterwards. That's the most valuable thing in the repo — a failure I predicted, caught by a check I'd built the day before." |
| 6 | 2:14 | 0:42 | **F-slide** (progressive reveal) + a 3 s cut of **E** (terminal) at ~2:44 | Slide builds in beats: the camera's downward cone drawn against the danger cylinder (~4 %); then a speed ladder, `10 m/s → STRIKE`, `5 → STRIKE`, `2 → STRIKE`, each row landing red on the beat; then the hover row: `0 m/s → 0.41 s of warning / 1.25 s needed`. Cut 3 s to the abort gate printing **FAIL** at the flown speed, then back | "So why? Not because the dodge was slow. The first time the camera saw that bird was the same instant they were closest: a hundred and seventy-five milliseconds of warning, and none by the time my software could act. It points straight down at the crop, so it covers about four percent of the danger zone. I replayed all three flights through a physics model and swept every speed. Ten metres a second: still a strike. Five. Two. Even from a standstill — the bird brings its own six metres a second, so this camera can never buy more than four tenths of a second, against an escape that needs one and a quarter." |
| 7 | 2:56 | 0:14 | Split card: red CI badge animating in beside the ADR log scrolling ~3 s, then hold on repo + dashboard URLs over a last few seconds of **H** | Ends on motion, not a static card | "No speed makes this geometry safe. So the plan changed on that measurement, not on a hunch: a forward-facing sensor is now in scope, and my pre-flight check refuses every speed I actually fly until it exists. The build badge is red because of it — on purpose. Links below." |

## (b) Full narration script (spoken, first person — ~470 words)

`[…]` marks a beat, not a word.

> This is a crop-survey drone flying a field the way a lawnmower cuts grass — lane after lane, until
> every square metre has been looked at. It's built entirely in simulation; this is its actual
> onboard camera. The interesting part is what happens when something gets in the way. `[beat]`
>
> Commercial ag drones already fly surveys like this, but they fly a route planned before takeoff
> and stick to it. Mine has to handle things the flight plan never knew about. And afterwards it has
> to prove it still covered the whole field — because a strip of crop nobody looked at is a strip
> nobody knows is dying. `[beat]`
>
> Here's the loop. The camera picks up a bird. My software works out how far away it is from how big
> it looks, picks a dodge point, checks the whole path it would fly against the surveyed tree rows,
> then commits to that point — so a flickering detection can't yank the aircraft around
> mid-manoeuvre. It takes control from the autopilot, dodges, gives control back, and settles the
> bill: every cell the detour skipped is either re-covered or recorded as debt. `[beat]`
>
> On this flight, that all worked. Four dodges accepted, eight more rejected for cutting too close
> to a tree. Seven hundred and twenty cells covered, zero debt. And from the same flight, the same
> camera: the crop-health map — all eighteen trees show up, every bright cell within two metres of a
> real one. `[longer beat — let the map finish]`
>
> And on that same flight, the drone passed six point seven millimetres from the bird — horizontally,
> four metres above it, which is well inside the separation rule. So the flight is invalid: it failed
> its own safety check. I'd written down before takeoff that this could happen, in the runbook, so it
> couldn't be reinterpreted afterwards. That's the most valuable thing in the repo — a failure I
> predicted, caught by a check I'd built the day before. `[beat]`
>
> So why? Not because the dodge was slow. The first time the camera saw that bird was the same
> instant they were closest: a hundred and seventy-five milliseconds of warning, and none by the time
> my software could act. It points straight down at the crop, so it covers about four percent of the
> danger zone. I replayed all three flights through a physics model and swept every speed. `[beat]`
> Ten metres a second: still a strike. `[beat]` Five. `[beat]` Two. `[beat]` Even from a standstill —
> the bird brings its own six metres a second, so this camera can never buy more than four tenths of
> a second, against an escape that needs one and a quarter. `[beat]`
>
> No speed makes this geometry safe. So the plan changed on that measurement, not on a hunch: a
> forward-facing sensor is now in scope, and my pre-flight check refuses every speed I actually fly
> until it exists. The build badge is red because of it — on purpose. Links below.

**Delivery notes.** Say "six point seven millimetres," not "0.0067 metres" — spoken decimals
vanish. Shots 1–4 are warm and quick; do **not** foreshadow the failure in the delivery, the twist
only works if shot 4 sounds like a win. Shot 5's first sentence is the pivot: say it flat, no
apology, no drama. The four one-word beats in shot 6 ("Five. Two.") carry the whole slide — leave
the pauses in. The last line of shot 6 is the thesis; slow down for it.

**Honesty checks — restated for this structure, do not edit them out:**

* Shot 3 describes a maneuver ("dodges"), and shot 4 says "four dodges accepted." Neither says the
  drone *avoided* the bird. It didn't.
* **Shots 4 and 5 are explicitly the same flight** — shot 5 opens "and on that same flight."
  Nothing in the wins implies a separate, passing flight exists. There isn't one.
* Shot 5 states **both** halves of the miss distance: 6.7 mm horizontally *and* 4 m of vertical
  separation, inside the rule's band. Saying only the 6.7 mm would read as a 3-D near-miss and would
  be an overclaim in the scary direction — still an overclaim.
* Shot 6's "about four percent" is the measured footprint fraction at *this encounter's* depth, not
  a general sensor spec. The slide must label it as such.
* Nothing anywhere claims avoidance has been verified on the real render.

## (c) Footage inventory

### Exists today — host-side only, no Docker session required

| ID | Asset | Where | Notes |
|---|---|---|---|
| **H** | **Onboard camera video — PROMOTED, now carries the open and the close** | `eval/results/clips/real_flight_20260825T205705Z/frames/rgb/frame_*.png` — **present on this machine, NOT in git** (only `meta.json`, `poses.jsonl` and `heatmap/` are tracked for that clip), 5 Hz | Assemble with `ffmpeg` on the host, no Docker. Local-only is fine for *producing* the video — the rendered file is the deliverable — but **the README must never link these frames**, a fresh clone won't have them. **Airborne window only — 671 of 3310 frames;** the rest is a parked drone below the ground plane after a skipped teardown. Consider 2× speed for the open so the lanes read as motion |
| **A** | **Dashboard captures** — replay, avoidance event log, NDVI overlay | ADR-018 static page, **in build this week** | Critical path: shots 2–5 all lean on it. Needs smooth playback and a scrub-to-timestamp control. Fallback if it slips: animate `flown_path_enu` from `eval/results/live_flight_log_20260825T210402Z.json` as a drawn path over the heatmap |
| **B** | **NDVI heatmap render** | `eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.png` (best on record) | Shot 4. Tree markers should land one by one rather than appearing at once |
| **C** | **Detection overlay stills — SAME FLIGHT, and the only ones in git** | `eval/results/adr003_20260825/overlays/` — 8 PNGs, **committed** (`.gitignore` now allowlists them): `gt_ndvi`/`gt_rgb` for frames 000964 + 000965, and the `gtdet_a_ndvi_direct_{ndvi,rgb}` pairs. Byte-verified against the scored labels and detections | Perception regenerated these since revision 1. **These are the only two frames in the whole flight where the bird was inside the image — and the detector boxed both.** **Shot-choice hazard:** on frame **965** (closest approach) the red ground-truth box sits ~15 px off the rendered bird from applied-pose render lag (IoU 0.511) while the detector's cyan box is tight — **a GT-only still of 965 reads on screen as "the detector missed," which is the opposite of the truth.** Use a `gtdet_*` still (both boxes, cyan = detector, red = GT, chosen for colour-blind separability) or frame **964**, where they nearly coincide (IoU 0.826). The 08-23 overlays are **not** in git (`adr003_*/overlays/` was gitignored as "regenerable," though the 3.8 GB source frames are ignored too) — drop them as the fallback |
| **E** | **Terminal: the abort gate refusing the booking** | `python3 scripts/predict_bird_visibility.py --speed 9.4` → FAIL | 3 s, shot 6. The project's own gate saying no. **This is the only terminal appearance in the video** |
| **F** | **The no-safe-speed slide (designed, progressive reveal)** | Data from `eval/results/replay_point_mass_20260826T160218Z.json` → `verdict.q3` | Build it; do not screenshot JSON. Values: `speed_at_which_nadir_becomes_safe_mps: null`, `max_lead_s 0.4132`, `sensor_horizon_m 2.48`, `required_sensor_horizon_m_at_flown_speed 17.752 – 38.748`. **Footer must cite the artifact and say "81 configurations — speeds × escape directions × three vehicle-limit assumptions,"** so the speed ladder is understood as a slice of the sweep and not the whole experiment |
| **G** | **Pull-quote cards** (replacing document scrolls) | Text from `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §7; `docs/DECISIONS.md` for shot 7's scroll | Shot 5's card: the pre-registration sentence, one line highlighted, 4 s. Shot 7 may scroll the ADR log for ~3 s as texture only |
| **D** | **Terminal: the safety verdict** | `python3 scripts/check_live_flight_log.py …` | **Cut in revision 2** — it was a log-scroll, and shot 5's animated distance readout tells the same fact with motion. Keep it in reserve if the dashboard can't render the closest-approach moment; if used, note that the shipped invocation returns INVALID for an *ambiguous truth track* and does not print the 0.0067 m line (see the SAFETY_FINDING marker) |

### Would need a Docker sim session — OPTIONAL

| ID | Asset | What it adds | Fallback if skipped |
|---|---|---|---|
| **I** | **Gazebo GUI third-person footage** — drone flying lanes, tree rows, the bird crossing | Third-person context: the viewer sees a 3-D physics world with real firmware rather than plots. Best used as a 6–8 s insert under shot 2, cutting from onboard to external | H + the dashboard replay already carry the video. **The whole thing is producible without a sim session** |

**Two things a Gazebo session cannot buy, so nobody books one expecting them:** it is **B-roll, not
evidence** — the committed flight remains the only scored take; and **there is no bookable nadir
avoidance take to film**, because the pre-flight gate now refuses every speed the vehicle actually
flies on this geometry (ADR-017 am. 1). A new avoidance flight waits on the forward sensor.

### Production dependencies to confirm before recording

1. **Dashboard ships with all three views** and screen-captures at a stable frame rate, with scrub
   control and ideally variable playback speed (shot 2 wants ~4×, shot 5 wants ~0.25×). Critical
   path for shots 2–5 — coordinate with whoever is building it.
2. **Two designed assets to build:** the F slide (progressive reveal) and the G pull-quote card.
   Neither exists; both are the difference between "engaging" and "a screen recording."
3. **ffmpeg assembly of asset H** is host-side and can be done today; only asset I needs
   `devops-reliability-engineer` and a Docker session.
4. **Re-verify every spoken number against the artifacts on recording day.** Voiceover is expensive
   to re-cut, and these numbers have moved before — the CPA figures shifted on 2026-08-26 when the
   legacy check's corner-only geometry was fixed.
</content>
</invoke>
