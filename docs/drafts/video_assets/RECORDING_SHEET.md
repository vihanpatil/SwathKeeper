# RECORDING SHEET — SwathKeeper demo video (7 shots, 3:10)

Operator sheet for recording `docs/drafts/DEMO_VIDEO_SCRIPT.md` (revision 2, 2026-08-26). Written
2026-09-11 against branch `feat/depth-segmenter` @ `c2a08a7`; QA-checked the same day at `7d03af7`,
after PR #32 merged to `main` (08:13 UTC) — every artifact cited below is on `main`. Every number below was copied from a
committed artifact or `README.md` on that date and is cited; **re-verify on the day** (section 6).

Claims ceiling for everything spoken or shown: **sim-demonstrated, evidence-gated** (`README.md`,
ADR-019 / ADR-022). The drone is the worked example; the method — pre-registered evidence gates —
is what the video shows. No "product", "customer", "field-ready", "essential" or "pay for" language.

---

## 1. Pre-roll checklist (from the script's header — confirm all five before rolling)

1. GitHub Pages is enabled and the dashboard URL in the closing card resolves (Settings → Pages →
   GitHub Actions), not the local `http.server` fallback.
   `https://vihanpatil.github.io/SwathKeeper/dashboard/` — the Pages workflow is
   `.github/workflows/pages.yml`. **Verified 2026-09-11:** PR #32 merged 08:13 UTC, the `pages.yml`
   run on `main` succeeded (38 s), `gh api repos/vihanpatil/SwathKeeper/pages` reports
   `build_type: workflow, public: true`, and the dashboard URL returns **HTTP 200**. Re-check on the
   day: `curl -sS -o /dev/null -w "%{http_code}\n" https://vihanpatil.github.io/SwathKeeper/dashboard/`.
2. All **three** bird-clearance breaches (0.0393 m / 0.0391 m / 0.0067 m) are represented on screen
   or in narration where the script currently names only the 2026-08-25 one. **Covered on screen by
   the G card, state 2** (its last line lists all three) — so shot 5 must reach state 2. Source:
   `README.md` results table row "Bird clearance — three live avoidance flights, three breaches".
3. No "product," "customer," or field-readiness language anywhere in the narration — this is a
   portfolio piece, not a pitch; see `README.md`'s claims ceiling.
   Check: `grep -n -iE 'product|customer|field-ready|essential|pay for' docs/drafts/DEMO_VIDEO_SCRIPT.md`
   (the shot-2 column of the shot list still contains one such note — it is a stage direction, not
   narration; do not read it).
4. Every spoken number is re-verified against its source artifact on the day (section 6 below; the
   CPA figures moved on 2026-08-26 when the vertex-only geometry was fixed).
5. The forward depth camera is described as **built and scored, never flown** if it is mentioned at
   all. The narration as scripted does not mention it; shot 7 says "a forward-facing sensor is now
   in scope", which is correct as written.

Also, before rolling:
- `brew install ffmpeg` and render asset H (section 4). ffmpeg is **not** installed on this host as
  of 2026-09-11.
- Screen resolution / capture region 1920×1080. Both cards are fixed 1920×1080 stages that scale to
  the window; record them fullscreen in a browser (File → open the `.html`; macOS fullscreen
  ⌃⌘F; hide the beat indicator with **H**).
- Dashboard served either from Pages or locally: `python3 -m http.server 8000` from the repo root,
  then `http://localhost:8000/dashboard/`. The page defaults to the **2026-08-25 flight**
  (`live_flight_log_20260825T210402Z`, last in `dashboard/data/manifest.json`) and the clip
  `real_flight_20260825T205705Z` — both are the flight of the story; do not switch the picker.

---

## 2. Dashboard controls — what exists (read from `dashboard/index.html` + `dashboard/app.js`)

| Control | Where | Fact |
|---|---|---|
| **Playback speed** | Flight replay tab, transport row, `<select id="speed">` labelled "speed" | **Exists.** Options **0.25×, 1×, 4×, 16×** (`index.html`; `app.js` line 850 multiplies the tick advance by `S.speed`). Shot 2's ~4× and shot 5's ~0.25× are both real options. |
| Play / pause | ▶ button or **Space** | one rAF loop; the drone marker is interpolated between logged samples (smooth); birds step between applied `set_pose` poses (not interpolated, by design) |
| Scrubber | range input under the map | tick index; hatched regions = parked, before/after the airborne window |
| **Jump to encounter** | button beside ▶ | seeks to **7 ticks before the closest-approach tick** (`jumpToEncounter`: `seek(cpa.tick − 1 − 6)`) → tick **984**; the encounter is takeover tick **991** → resume **995** |
| Step | **→ / ←** one tick, **Shift** ×25 | works on every tab |
| Next event | **E** (Shift+E previous) | steps through takeover / latch / maneuver / hold / resume / gate_reject events |
| Tabs | **1** replay · **2** avoidance log · **3** NDVI health map | playback **stops when you leave the replay tab** (`show()`), so on the Avoidance-log tab you step with E / →, you do not "play" |
| Event rows | Avoidance log tab | the current row is highlighted (`highlightRow` adds class `here`) as the tick changes; clicking a row seeks the replay to that tick |
| Encounter card | appears on the map during the encounter | **static text**, not a ticking readout: "It passed 0.0067 m horizontally and 4.03 m vertically from bird_0 — over the top of it…" |
| Closest approach | red dot + label on the map; red vertical-gap line on the altitude strip | drawn, not animated |
| Layers | replay side panel | grid · lanes · trees · path · events · birds — **there is no NDVI heatmap layer on the replay view**; the heatmap is on tab 3 and is drawn all at once |
| Ledger | "What this flight measured" facts panel | **static** row "coverage ledger 720 covered / 0 debt" — no count-up animation |
| Tree markers | NDVI tab | all 18 drawn in one paint — no one-by-one landing |
| 5-step tour | "Take the 5-step tour" button | steps: field → the loop takes the vehicle → closest approach → why the gate says INVALID → the ledger + NDVI tab; step 5 switches to the NDVI view (usable as a motion element for shot 4) |

Consequences for the shot list (be honest in the edit, do not fake it in the capture):
- Shot 2's "heatmap fills in behind the path" is **not** a dashboard behaviour. Capture the replay at
  4× (path draws itself), then capture tab 3 separately; composite or cut in post.
- Shot 4's counting ledger and one-by-one tree markers are **post-production** (mask reveal over a
  capture of tab 3, or a caption counter). The dashboard values to reveal are 720 / 0 and 18/18.
- Shot 5's "readout ticks down to 0.0067 m" is **post-production**; the dashboard gives the
  converging markers at 0.25× and the static card. If a live number is wanted on screen, add it as a
  caption from the SAFETY_FINDING table.

Timing facts for the replay (from `eval/results/live_flight_log_20260825T210402Z.json`
`run.tick_stamp_sim_s`): 1858 ticks, sim time 43.518 → 303.683 s = **260.2 s** of flight, median
**0.16 s/tick**. So the whole flight is ~**65 s at 4×**, ~**16 s at 16×**, and at **0.25×** one tick
takes ~0.64 s of wall time (the 984 → 995 encounter window ≈ 7–8 s on screen).

---

## 3. Shot by shot

Narration paragraphs are copied verbatim from the script's section (b). `[beat]` marks a pause.

### Shot 1 — 0:00, 18 s — asset H, onboard flyover

- **Open:** `docs/drafts/video_assets/H_flyover.mp4` (render it first — section 4). Drone's-eye view
  over the crop rows; a tree row crosses frame. The clip runs **26.84 s** at the 25 fps command below
  (671 frames at 5 Hz played 5× real time); take the first ~18 s or pick the tree-row crossing.
- **Motion:** the footage itself. Title card fades in over it at ~0:10 without stopping it.
- **Cut:** at 0:18, on a lane change if there is one.
- **Fact check:** `meta.json` for the clip says `synthetic: false`, generator
  `src/fieldguard_planning/record_node.py (live real-render recorder)` — it is the actual onboard
  camera of the simulated vehicle.

> This is a crop-survey drone flying a field the way a lawnmower cuts grass — lane after lane, until
> every square metre has been looked at. It's built entirely in simulation; this is its actual
> onboard camera. The interesting part is what happens when something gets in the way. `[beat]`

### Shot 2 — 0:18, 26 s — asset A, dashboard replay wide at ~4×

- **Open:** dashboard, **Flight replay** tab (key **1**), flight `live_flight_log_20260825T210402Z`
  (default). Scrub to the start of the airborne window (or press "Take the 5-step tour" → step 1
  seeks to the first motion tick, then Esc).
- **Control:** set **speed → 4×**, press **Space**. The blue path draws itself lane by lane over the
  dashed planned lanes and the green tree geofences.
- **Heatmap:** not on this view — capture tab **3** (NDVI health map, key 3) separately for the
  composite (section 2).
- **Cut:** at 0:44, mid-lane, straight into shot 3 (same view, scrubbed).

> Commercial ag drones already fly surveys like this, but they fly a route planned before takeoff
> and stick to it. Mine has to handle things the flight plan never knew about. And afterwards it has
> to prove it still covered the whole field — because a strip of crop nobody looked at is a strip
> nobody knows is dying. `[beat]`

### Shot 3 — 0:44, 34 s — asset A, replay at the encounter + event log; asset C cut-in at ~1:02 for 3 s

- **Open:** replay tab. Click **Jump to encounter** (lands on tick 984, seven ticks before closest
  approach). Set **speed → 1×** (or 0.25× if the pink stretch is too quick), **Space**. The pink
  GUIDED stretch and the pink X (latched setpoint) draw; the encounter card appears.
- **Event rows:** switch to **Avoidance log** (key **2**); playback stops there by design — press
  **E** repeatedly so the rows light up one at a time (detection → takeover → latch/maneuver →
  resume), each highlighted as the current row. Capture that as a second pass and composite beside
  the map, or cut between them.
- **Cut-in C at ~1:02, 3 s:** open
  `eval/results/adr003_20260825/overlays/gtdet_a_ndvi_direct_ndvi_frame_000964.png` (640×480 PNG,
  committed) — both boxes, cyan = detector, red = ground truth, near-coincident (IoU 0.826). **Do
  not use a GT-only still of frame 965** (reads as a miss it wasn't — script (c) row C).
- **Cut:** back to motion after the 3 s, then at 1:18 into shot 4.

> Here's the loop. The camera picks up a bird. My software works out how far away it is from how big
> it looks, picks a dodge point, checks the whole path it would fly against the surveyed tree rows,
> then commits to that point — so a flickering detection can't yank the aircraft around
> mid-manoeuvre. It takes control from the autopilot, dodges, gives control back, and settles the
> bill: every cell the detour skipped is either re-covered or recorded as debt. `[beat]`

### Shot 4 — 1:18, 24 s — asset A ledger panel, then asset B heatmap with tree markers

- **Open:** replay tab side panel "What this flight measured" → row **coverage ledger 720 covered /
  0 debt**, **maneuvers accepted 4**; then **NDVI health map** tab (key **3**) — or the tour's step 5,
  which switches to the NDVI view itself.
- **Motion:** the count-up to 720 / 0 and the 18 tree markers landing one by one are **post**
  (section 2). The heatmap image itself is
  `eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.png` (committed) if a clean
  still is preferred over the canvas.
- **Numbers on screen:** 720 / 0 (ledger), 4 accepted / 8 rejected, 18/18 trees, 11 canopy-grade,
  every positive cell within 2.0 m — all from the `README.md` results table.
- **Cut:** at 1:42, on the last tree marker. **Deliver this shot as a win; the pivot is next.**

> On this flight, that all worked. Four dodges accepted, eight more rejected for cutting too close
> to a tree. Seven hundred and twenty cells covered, zero debt. And from the same flight, the same
> camera: the crop-health map — all eighteen trees show up, every bright cell within two metres of a
> real one. `[longer beat — let the map finish]`

### Shot 5 — 1:42, 32 s — asset A replay at ~0.25× to closest approach, then the G card

- **Open:** replay tab, **Jump to encounter**, **speed → 0.25×**, **Space**. The drone marker glides
  over the bird marker (tick 991 = closest approach, `t_sim` 202.775 s); the red closest-approach
  dot and the encounter card ("It passed 0.0067 m horizontally and 4.03 m vertically…") are on
  screen; the altitude strip below shows the 4.03 m vertical gap in red.
- **Then the G card, 4 s:** open `docs/drafts/video_assets/G_preregistration_card.html` fullscreen.
  **State 1** (the quote, one sentence highlighted) under "I'd written down before takeoff…";
  press **→** for **state 2** (0.0067 m against a 3.00 m bar · INVALID · exit 1, plus the
  three-breach line) under "That's the most valuable thing in the repo…". State 2 is what puts all
  three breaches on screen (checklist item 2).
- **Cut:** at 2:14 on the card, hard cut to the F slide.
- **Delivery:** the first sentence is the pivot — flat, no apology. Say "six point seven
  millimetres" and "four metres above it" — both halves (honesty check in the script).

> And on that same flight, the drone passed six point seven millimetres from the bird — horizontally,
> four metres above it, which is well inside the separation rule. So the flight is invalid: it failed
> its own safety check. I'd written down before takeoff that this could happen, in the runbook, so it
> couldn't be reinterpreted afterwards. That's the most valuable thing in the repo — a failure I
> predicted, caught by a check I'd built the day before. `[beat]`

### Shot 6 — 2:14, 42 s — the F slide (progressive reveal) + 3 s of asset E (terminal) at ~2:44

- **Open:** `docs/drafts/video_assets/F_no_safe_speed_slide.html` fullscreen, at beat 0 (title only).
  Press **→** (or click) once per beat; **←** goes back; **R** resets; **H** hides the indicator.
- **Beat cues against the narration:**
  - **→ beat 1** on "The first time the camera saw that bird…" — the 12 m cylinder draws, the
    4.96 × 3.72 m footprint lands, captions (0.175 s / 0.000 s; ≈ 4 %).
  - **→ beat 2** exactly on **"Ten"** — rungs 10, 9, 8, 7, 6 m/s cascade red.
  - **→ beat 3** on **"Five."** — rungs 5, 4, 3.
  - **→ beat 4** on **"Two."** — rung 2 and the verdict line (`speed_at_which_nadir_becomes_safe_mps: null`).
  - **→ beat 5** on "Even from a standstill" — the hover rung (0.41 s of warning, 0.23 m moved) and
    the two big times **0.41 s / 1.25 s**.
  - **→ beat 6** is held back for shot 7's first line, "No speed makes this geometry safe" — the
    forward-vision strip (2.48 m have vs 17.8–38.7 m needed).
- **Asset E cut-in at ~2:44, 3 s (the only terminal in the video):**
  ```
  python3 scripts/predict_bird_visibility.py --speed 9.012
  ```
  prints the per-bird table and ends
  `VERDICT: FAIL -- 3 of 3 birds below the 5-frame floor (median frames in view over the phase sweep at 9.0 m/s, 5.0 Hz): bird_0, bird_1, bird_2.`
  and exits **1** — verified on this host 2026-09-11. 9.012 m/s is the encounter's flown median
  (`docs/DECISIONS.md` ADR-020 am. 3); the script draft used `--speed 9.4`, which was not re-run
  today — use 9.012 or run both. Note this is the bird-**visibility** pre-flight gate (ADR-017 am. 1:
  "§0b now honestly refuses every real booking speed"); do **not** show
  `scripts/predict_forward_lead.py`, the forward-sensor booking gate, which PASSES at 5.0 m/s.
  Make the terminal font large (≥ 18 pt); only the last lines need to read.
- **Cut:** back to the slide after 3 s; at 2:56 press → for beat 6 as shot 7's narration begins.

> So why? Not because the dodge was slow. The first time the camera saw that bird was the same
> instant they were closest: a hundred and seventy-five milliseconds of warning, and none by the time
> my software could act. It points straight down at the crop, so it covers about four percent of the
> danger zone. I replayed all three flights through a physics model and swept every speed. `[beat]`
> Ten metres a second: still a strike. `[beat]` Five. `[beat]` Two. `[beat]` Even from a standstill —
> the bird brings its own six metres a second, so this camera can never buy more than four tenths of
> a second, against an escape that needs one and a quarter. `[beat]`

### Shot 7 — 2:56, 14 s — split card: red CI badge + ADR log scroll, then repo + dashboard URLs over H

- **Open:** (a) the F slide at **beat 6** under the first sentence, then (b) the CI page
  `https://github.com/vihanpatil/SwathKeeper/actions/workflows/ci.yml` (badge:
  `…/ci.yml/badge.svg?branch=main`, red) beside (c) `docs/DECISIONS.md` scrolling ~3 s at ADR-022 as
  texture; then (d) the closing card with `https://github.com/vihanpatil/SwathKeeper` and
  `https://vihanpatil.github.io/SwathKeeper/dashboard/` over the last seconds of `H_flyover.mp4`.
- **Facts behind the badge, if a caption is wanted:** `main` is red on exactly one declared test,
  `tests/test_ci_evidence_gate.py::TestLiveFlightLogGateHasEvidence::test_step_passes_on_the_committed_evidence`;
  `tests/test_known_red_allowlist.py` asserts that this is the only permitted red (`README.md`
  Honest limitations item 4). **Live-verified 2026-09-11** on the post-merge run of `main`
  (`gh run view 34578149336`): the evidence-gate step ends `FAILED (failures=1, skipped=1)` and
  `test_the_failing_set_is_exactly_the_allowlist ... ok` — one red, and it is the declared one.
- **Cut:** end on the moving footage, not a static card.

> No speed makes this geometry safe. So the plan changed on that measurement, not on a hunch: a
> forward-facing sensor is now in scope, and my pre-flight check refuses every speed I actually fly
> until it exists. The build badge is red because of it — on purpose. Links below.

---

## 4. Asset H — the drone's-eye flyover (ffmpeg, host-side, no Docker)

**Airborne frame range, computed 2026-09-11 from
`eval/results/clips/real_flight_20260825T205705Z/poses.jsonl`** (fields: `frame_id`, `t_s`,
`drone.pos_m` = `[x, y, z]` in world ENU metres, z up; `rgb_path`): frames with `z > 1.0 m` are
**`frame_id` 824 → 1494 inclusive, 671 frames, contiguous (no gaps)**, `t_s` 164.8 → 298.8 s
(134.0 s of flight at 5 Hz), z max 15.04 m. `meta.json`'s own `airborne` block agrees:
`z_threshold_m 1.0, frames 671, frames_total 3310, span_s 134.0, cadence_hz 5.0`. `README.md`:
"649 painting frames of 671 airborne"; script (c): "671 of 3310 frames".

**Frame files verified present:** `frames/rgb/frame_000824.png` … `frame_001494.png` → **671 of
671 present, 0 missing** (3310 files in `frames/rgb/` in total); each is a 640×480 PNG. These frames
are on this machine and **not in git** — the rendered mp4 is the deliverable; never link the frames
from the README.

```
brew install ffmpeg
ffmpeg -framerate 25 -start_number 824 -i eval/results/clips/real_flight_20260825T205705Z/frames/rgb/frame_%06d.png -frames:v 671 -vf scale=1920:-2 -c:v libx264 -pix_fmt yuv420p docs/drafts/video_assets/H_flyover.mp4
```

Notes:
- Output length **26.84 s** (671 / 25); the source is 5 Hz, so this plays at **5× real time** —
  faster than the script's "consider 2×". For 2× use `-framerate 10` (67.1 s); for real time
  `-framerate 5`.
- The frames are 4:3, so `scale=1920:-2` yields **1920×1440**; in a 1080p timeline crop to
  1920×1080 (centre) or use `-vf scale=1440:1080` and pad. Run from the repo root.
- Do not commit `H_flyover.mp4` (this is a draft asset; `git status` should stay clean of it).

---

## 5. What is on each card (so the edit can caption it)

**F — `F_no_safe_speed_slide.html`** (source of every number: an HTML comment at the top of the
file). Beats: 1 footprint 4.96 × 3.72 m inside the 12 m cylinder at 4.03 m depth, ≈ 4 %, 0.175 s /
0.000 s; 2–4 the ladder 10 → 2 m/s (lead 0.1550 → 0.3099 s; best escape 0.0124 → 0.0991 m; every rung
STRIKE) and the verdict `speed_at_which_nadir_becomes_safe_mps: null`; 5 hover rung 0.4132 s /
0.2278 m and **0.41 s vs 1.25 s**; 6 forward vision **2.48 m** have vs **17.752 / 27.25 / 38.748 m**
needed at 9.2 m/s. Footer cites `eval/results/replay_point_mass_20260826T160218Z.json` and reads
"81 speed points, swept from 2 to 10 m/s, each checked against every escape direction and three
vehicle-limit assumptions" (required wording, script (c) row F).

**G — `G_preregistration_card.html`.** **On-screen tension to know about (QA, 2026-09-11):** the
verbatim §7 quote in state 1 says "the two historical **~5 cm** bird strikes" while state 2's breach
line reads **0.0393 / 0.0391 m**. Both are right and the quote must stay verbatim — ~5 cm was the
vertex-only CPA geometry known on 2026-08-24; the 2026-08-26 path-segment recompute lowered those two
to 0.0393 / 0.0391 m (`README.md`; commit `c2a08a7`). The card holds ~4 s and the narration never says
"5 cm", so no change was made to the card. If the card is held longer or freeze-framed, add the
caption: *"~5 cm was the vertex-only geometry of the day; the current path-segment recompute reads
0.0393 / 0.0391 m."* State 1: §7 of `docs/runbooks/AVOIDANCE_REAL_DETECTION.md`
verbatim, "This flight may honestly FAIL its own GT-CPA gate." highlighted, attributed with the path
and **written 2026-08-24 (commit 4274b48), flown 2026-08-25**. State 2 adds: **0.0067 m against a
3.00 m bar · INVALID · exit 1**, 4.03 m above bird_0, and the three-breach line
0.0393 / 0.0391 / 0.0067 m.

---

## 6. Numbers on the day — every spoken or shown number, its source, how to re-check

Run from the repo root. `R` = `eval/results/replay_point_mass_20260826T160218Z.json`,
`L` = `eval/results/live_flight_log_20260825T210402Z.json`, `S` = its `.SAFETY_FINDING.md`.

| Spoken / shown | Value | Source | Re-check |
|---|---|---|---|
| "four dodges accepted, eight more rejected" | 4 accepted / 8 rejected candidates | `README.md` results table; `S` "What already passed" | `python3 -c "import json;e=json.load(open('L'))['events'];m=[x for x in e if x.get('kind')=='maneuver'];print(sum(x.get('verdict')=='accepted' for x in m),len(m))"` (rejected candidates are counted inside the maneuver events' gate audit — quote the README figure if the one-liner differs in shape) |
| "seven hundred and twenty cells covered, zero debt" | 720 / 0 | `README.md`; `L` `coverage_ledger` | `python3 -c "import json,collections;print(collections.Counter(r['status'] for r in json.load(open('L'))['coverage_ledger']))"` |
| "all eighteen trees … within two metres" | 18/18 imaged, 11 canopy-grade, all 11 positive cells < 2.0 m | `README.md` results table; `scripts/check_tree_positions.py` on the clip | `python3 scripts/check_tree_positions.py eval/results/clips/real_flight_20260825T205705Z` (see script `--help` for the exact form) |
| "six point seven millimetres … four metres above it" | 0.0067 m horizontal; 4.0300 m vertical (drone z 15.0300, bird z 11.0000) | `S` table; `R` `verdict.q2.rows[4].flown_gt_cpa_m` (**index 4, not 2** — q2 has 5 rows and rows[0..3] are the 2026-08-18 / 2026-08-23 flights; rows[2] reads 0.0391) | `grep -n "0.0067\|4.0300" eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md` |
| "it failed its own safety check … invalid" | INVALID, exit 1 | `S`; `README.md` | `python3 scripts/check_live_flight_log.py eval/results/live_flight_log_20260825T210402Z.json; echo $?` (prints INVALID for an ambiguous truth track and does **not** print the 0.0067 m line — `S` explains) |
| "written down before takeoff" | §7 written 2026-08-24, flown 2026-08-25 | `git log --diff-filter=A -- docs/runbooks/AVOIDANCE_REAL_DETECTION.md` → `4274b48 2026-08-24` | same command |
| "a check I'd built the day before" | GT-CPA gate built the day before the flight | `README.md` "The check that failed the flight hadn't existed eight days earlier. I built it the day before" | read the README paragraph |
| "a hundred and seventy-five milliseconds of warning, and none…" | 0.175 s sensor lead / 0.000 s policy lead | `S` row "sensor lead / policy lead" | `grep -n "0.175 s" eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md` |
| "about four percent" | 4.96 × 3.72 m footprint vs π·12² → 0.041 | `README.md` ("about 4 %"); footprint `docs/ROADMAP.md:48`; halves `R` `tripwire.sensor_horizon` (2.48 / 1.86) | `python3 -c "import math;print(4.96*3.72/(math.pi*144))"` → 0.0408. **Not a discrepancy — resolved 2026-09-11:** the footprint scales with depth, so README's 4 % is the ratio AT THIS ENCOUNTER'S 4.03 m (18.45 / 452.39 = 4.08 %) and ROADMAP/ADR-017's "≤ ~9 % … ever in view" is the ratio at the ±6 m band edge, where the footprint is largest: `4.96·6/4.03 × 3.72·6/4.03 = 40.90 m²`, 40.90 / 452.39 = **9.04 %**. Both are right; quote 4 % only with "at this encounter's depth" attached, which the slide does |
| "12 m" threat cylinder, "±6 m" band, "3.00 m" bar | 12.0 / 6.0 / 3.0 | `L` `run.policy_params` | `python3 -c "import json;print(json.load(open('L'))['run']['policy_params'])"` |
| "all three flights" | 3 logs replayed | `R` `logs_considered` (a list of the 3 log filenames) | `python3 -c "import json;print(len(json.load(open('R'))['logs_considered']))"` → `3` |
| "swept every speed" | 81 mission speeds, 2.0 → 10.0 m/s at 0.1 | `R` `tripwire.speed_sweep` | `python3 -c "import json;s=json.load(open('R'))['tripwire']['speed_sweep'];print(len(s),s[0]['mission_speed_mps'],s[-1]['mission_speed_mps'],any(r['cleared_by_any_plant'] for r in s))"` → `81 2.0 10.0 False` |
| "Ten … Five … Two" (every rung a strike) | e.g. 10 m/s lead 0.1550 s / moved 0.0124 m; 5 m/s 0.2254 / 0.0382; 2 m/s 0.3099 / 0.0991 | `R` `tripwire.speed_sweep[]` `max_lead_s`, `plants.angle_max_ceiling.max_lateral_displacement_m` | `python3 -c "import json;[print(r['mission_speed_mps'],r['max_lead_s'],r['plants']['angle_max_ceiling']['max_lateral_displacement_m']) for r in json.load(open('R'))['tripwire']['speed_sweep'] if r['mission_speed_mps'] in (10.0,5.0,2.0)]"` |
| no safe speed | `speed_at_which_nadir_becomes_safe_mps: null`, `safe_speed_exists_in_2_10_mps: false` | `R` `verdict.q3` | `python3 -c "import json;q=json.load(open('R'))['verdict']['q3'];print({k:q[k] for k in ('safe_speed_exists_in_2_10_mps','speed_at_which_nadir_becomes_safe_mps','bar_m','sensor_horizon_m','cleared_at_hover_limit')})"` |
| "six metres a second" | bird 6.0024 m/s | `R` `tripwire.bird_speed_mps` | in the q3 `why_no_safe_speed` text |
| "four tenths of a second" | 0.4132 s from a hover | `R` `tripwire.hover_limit.max_lead_s`; `README.md` "0.41 s even from a hover" | `python3 -c "import json;print(json.load(open('R'))['tripwire']['hover_limit'])"` |
| "one and a quarter" | 1.25 s cheapest escape | `R` `verdict.q2.rows[4].min_physically_resolving_lead_s` (2026-08-25, angle_max_ceiling; **rows[2] is 2026-08-23 and reads 0.2** — select by `stem`, not index); `README.md` "needs 1.25 s" | `python3 -c "import json;print([(r['stem'],r['min_physically_resolving_lead_s']) for r in json.load(open('R'))['verdict']['q2']['rows']])"` |
| forward vision 17.8–38.7 m vs 2.48 m (F beat 6) | 17.752 / 27.25 / 38.748 m at 9.2 m/s; 2.48 m | `R` `verdict.q3.required_sensor_horizon_m_at_flown_speed`, `sensor_horizon_m`; `README.md` | `python3 -c "import json;q=json.load(open('R'))['verdict']['q3'];print(q['sensor_horizon_m'],q['required_sensor_horizon_m_at_flown_speed'])"` |
| "the build badge is red … on purpose" | exactly one declared red test + allowlist | `README.md` Honest limitations 4; `tests/test_known_red_allowlist.py` | `grep -n "test_step_passes_on_the_committed_evidence" tests/test_known_red_allowlist.py` |
| three breaches (G state 2) | 0.0393 (2026-08-18) · 0.0391 (2026-08-23) · 0.0067 (2026-08-25) | `README.md` results table; `R` `verdict.q2.rows[].flown_gt_cpa_m` | `python3 -c "import json;print([(r['stem'],r['flown_gt_cpa_m']) for r in json.load(open('R'))['verdict']['q2']['rows']])"` |
| asset E verdict | `VERDICT: FAIL`, exit 1 at `--speed 9.012` | run 2026-09-11 | `python3 scripts/predict_bird_visibility.py --speed 9.012; echo $?` |
| 9.012 m/s (why that speed) | encounter median 9.012 m/s = 1.802× a 5.0 m/s booking; whole-flight median 3.417 m/s would pass | `docs/DECISIONS.md` ADR-020 am. 3 (lines ~3996–3997) | `grep -n "9.012" docs/DECISIONS.md` |
| "0.434 s … 0.018 m" (not spoken as scripted; on the dashboard card / README) | GUIDED authority 0.434 s; 0.018 m lateral vs 10 m commanded | `S`; `README.md` results table; ADR-022 | `grep -n "0.434\|0.018 m" eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md` |

Also re-run before recording: `python3 -m pytest tests -q` and confirm the single expected failure
is the declared one (README: 1699 passed, 1 failed, 1 skipped, measured 2026-09-07 — re-quote if it
moved).
