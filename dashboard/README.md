# SwathKeeper dashboard

The farmer-facing view — flight replay, avoidance event log, NDVI health map — as a **static,
self-contained, client-side page** (ADR-018). No framework, no CDN, no build step, no server-side
anything. It renders entirely from the committed evidence under `data/`, so it works offline and it
publishes to GitHub Pages unchanged.

> It is the proof, not the point. The detect → avoid → replan → requeue loop is the project; this
> page just shows you what that loop actually did, including the flight it failed.

## View it in one command

```bash
python3 -m http.server 8000          # from the repository root
# then open http://localhost:8000/dashboard/
```

Opening `index.html` straight off disk (`file://`) will **not** work — browsers block `fetch()` on
`file://` URLs. The page detects that and tells you the command above instead of failing silently.

### On GitHub Pages

Enable Pages for the repository (Settings → Pages → *Deploy from a branch*, branch `main`,
folder `/ (root)`). The dashboard is then at `https://<user>.github.io/<repo>/dashboard/`. Nothing
else is needed: every path the page fetches is relative, and `data/` is committed.

## The three views

| view | what it shows | what it reads |
|---|---|---|
| **Flight replay** | top-down field, tree geofences, planned lanes, the flown path on a time scrubber, birds, every avoidance event, and the closest-approach instant | `data/flights/*.json`, `data/truth/*.json`, `data/field.json` |
| **Avoidance log** | the event table synced to the scrubber (click a row to seek), the run block (detector, clock, policy parameters), candidate rejections, swept clearances | the same flight log |
| **NDVI health map** | the offline stitch (ADR-010) on the canonical 2.5 m cell grid, per-cell values, trees with canopy grade, and the coverage ledger joined by `cell_id` | `data/clips/*/heatmap.json` + `meta.json`, plus the selected flight's ledger |

Each flight's header carries **its gate verdict, verbatim** — including the 2026-08-25 take, which
reads INVALID because it flew 0.0067 m from a bird against a 3.00 m bar. That is not an oversight in
the page; it is the page working. A safety gate you only trust when it is green is not a safety gate.

**Start with the 5-step tour** (button, top right) if you have two minutes; otherwise press
<kbd>space</kbd> to fly it. Keys: `space` play/pause, `←`/`→` step a tick (`shift` for ×25),
`E` next event, `1`/`2`/`3` switch view.

### Reading the encounter

A top-down map flattens altitude away, so the 2026-08-25 encounter *looks* like the drone drove
through the bird. It flew **over** it — 0.0067 m horizontally, 4.03 m vertically. Three things on
the replay view exist to make that legible rather than confusing:

* live **`z` readouts** beside the drone and every bird marker;
* an **altitude strip** under the map — drone line vs bird lines, with the policy's ±6 m threat band
  shaded and the vertical gap at the closest approach drawn and labelled;
* an **encounter callout** that appears when the scrubber enters a GUIDED window, stating what was
  commanded, how much of it was actually flown along the commanded direction, and what the gate
  measured. Every one of those figures is computed from that flight's own log.

## Where the numbers come from

Every figure is computed **in your browser** from the artifacts under `data/`, or is a verbatim line
printed by a gate that ran on the host. Nothing is typed in. Specifically:

* Verdicts, ground-truth CPA, freeze debit → `scripts/check_live_flight_log.py` (the same gate CI runs).
* Trees imaged / canopy-grade / median lift → recomputed by the page from the heatmap and the
  surveyed tree positions, then **cross-checked against `scripts/check_tree_positions.py`'s committed
  output**. If the two ever disagree, the page says so in red instead of picking one.
* Coverage counts, detector rate, frame denominators → counted from the copied artifacts, always
  shown with their denominator.
* Frame counts are quoted as *airborne* and *painting*, never as the recorder's raw `num_frames`
  (most of which, on the 2026-08-25 clip, is a parked vehicle below the ground plane).

Schema-1 flight logs (2026-08-18, 2026-08-23) carry **no time axis**. Their scrubber is a tick index
and is labelled as such everywhere; the page never presents a tick as a measured second.

### What moves smoothly, and what deliberately does not

The **drone marker is interpolated** between logged telemetry samples, because telemetry samples a
continuous trajectory and reading between two samples is a fair visual reading. It is labelled on
the view, and no *number* is ever interpolated — the clock, the events and the closest approach are
all read at logged ticks.

The **birds are not interpolated.** They step between applied `set_pose` poses roughly 0.44 s apart,
because that is literally how Gazebo moved them (ADR-012) and it is what the safety gate measures
the closest approach against. Smoothing them would put a bird where the render never showed it — and
at the closest-approach instant, somewhere that contradicts the measured 0.0067 m. A fading trail of
recent poses gives the eye the motion instead.

Playback **opens on the airborne window** rather than the parked prologue every log starts with
(2,246 of 4,328 ticks on the 2026-08-18 flight). The window is derived, not hand-picked: the first
tick whose next five telemetry samples all read `z > 1.0 m` — the same threshold the clip recorder
writes into every clip's `meta.airborne` — and the last tick whose preceding five do. **No data is
trimmed**; the parked ticks are hatched on the scrubber, still scrubbable, and a checkbox includes
them in playback.

## Rebuilding `data/`

```bash
python3 scripts/build_dashboard_data.py            # rebuild (idempotent; prints what changed)
python3 scripts/build_dashboard_data.py --check    # exit 1 if the committed tree is stale
```

The build script copies or derives every byte from `eval/results/` and `config/`, and records each
source's SHA-256 in `data/manifest.json` (the page lists them in its footer — verify any of them
with `shasum -a 256 <path>`). `tests/test_build_dashboard_data.py` runs `--check` in CI, so a stale
copy cannot sit in the repository unnoticed. That pin exists because this project has already been
bitten once by a committed copy of a derived artifact drifting away from its source.

Adding a flight or a clip to the dashboard is a reviewed diff: the lists live in `FLIGHT_STEMS` and
`CLIP_NAMES` at the top of the build script, so a stray file dropped into `eval/results/` cannot
become published evidence on its own.

## Files

```
dashboard/
  index.html   page skeleton (no inline data, no external references)
  app.js       all behaviour: load, replay, event log, heatmap, self cross-check
  style.css    one stylesheet
  data/        built by scripts/build_dashboard_data.py — do not hand-edit
```

Three files rather than one, because `app.js` is real logic and a single HTML blob would make it
worse to read for exactly the audience this page is written for. No webfont is vendored: a system
UI stack costs zero bytes, never flashes fallback text, and is already hinted for the reader's
screen — the craft goes into the type scale instead.

**Rendering is three layers,** because a full redraw per animation frame was visibly laggy. The
field, trees, lanes, whole flown path, event markers and CPA crosshair are painted once into an
offscreen canvas; the "flown so far" line lives in a second offscreen canvas that is *extended* by
the segments each frame adds rather than restroked from tick 0; only the drone, birds, setpoint and
event pulses are drawn per frame. Per-frame DOM writes are held to the scrubber thumb and the
timeline cursor — text, table highlighting and the encounter card only touch the DOM when the tick
changes. Measured on the 4,328-tick flight: **7,514 → 55 canvas operations and 21 → 0 DOM node
creations per frame.**
