---
name: reference-docs-evidence-chain
description: Which committed artifact proves which published SwathKeeper number, the three tree-gate clips that get confused with each other, and the commands that re-verify a docs claim in ~90 s
metadata:
  type: reference
---

Built during the 2026-08-25 docs-revamp audit so a future doc claim can be checked against evidence
without re-deriving the map. Open gaps: [[project-open-safety-gaps]]. Scenario/gate locations:
[[reference-safety-scenario-catalog]].

**THE THREE CLIPS THAT GET CONFUSED.** All three are quoted in the docs, all three are real renders,
and two of them have 624 painting frames + 720/720 cells — which is exactly why they get spliced.
Re-derive with `python3 scripts/check_tree_positions.py eval/results/clips/<clip>`.

| clip | what it proves | tree gate |
|---|---|---|
| `real_flight_20260821T045848Z` | the **canopy-contrast headline +0.8692** (2026-08-21 demo take) | 12/18 imaged, 8 canopy-grade |
| `real_flight_20260822T215516Z` | ADR-013 **am. 10's flagship** — first full-grid map, 935 frames | 18/18 imaged, **14** canopy, 16 positive cells, median +0.5200 |
| `real_flight_20260823T073644Z` | README's **hero heatmap**, the ADR-003 am. 7 scoring clip, 1256 frames | 18/18 imaged, **9** canopy, 12 positive cells, median +0.5402 |

The hero clip is NOT am. 10's flagship, and it is the weaker canopy result of the two. A metrics
table that puts "18/18 trees imaged" next to "+0.8692 median lift" is silently splicing the best
imaging from one flight onto the best contrast from another — check the clip stamp, not the row.

**NUMBER -> ARTIFACT, all verified by reading the file.**
- per-bird-track FNR 0.000 / precision 0.7083 / recall 0.85 / TP 17 FP 7 FN 3 / 20 visible
  bird-frames / 3-of-3 birds / threshold -0.61 PROVISIONAL -> `eval/results/adr003_20260823/spike_scores.json`
  (`approaches.a_ndvi_direct`). The RGB arm's "1.000 FNR" is `b_synthetic_rgb.fnr` — inverted signal
  on this world, never RGB's ceiling.
- 720/720 cells, painting cadence 5.0 Hz, `clip_synthetic: false` -> that clip's `heatmap/heatmap.json`.
- 100 % band delivery -> the clip's `meta.json`: `fuser.red_frames == nir_frames ==
  camera_info_frames == fused_count == 1286`. Judge the lever by that ratio, never by
  `dropped_pair_count: 0`. `meta.dds.shm_capacity_bytes` is where `--shm-size=1g` shows up.
- CPA 0.0518 m (covered 720 / debt 0 / 984 path points) and 0.0597 m (513/207 / 4328) -> the two
  `eval/results/live_flight_log_*.json`, printed by `scripts/check_live_flight_log.py`, exit 0
  because each has BOTH acknowledgement halves.
- "19 detections, 19/19 accepted diverts, takeover at wp 6, resume on `threat_cleared`" -> events in
  `live_flight_log_20260823T004031Z.json` (19 events carry `confidence`, 19 carry `verdict`).
- **All of the above are git-TRACKED** (checked with `git ls-files --error-unmatch`), so README's
  links and its hero `<img>` resolve on GitHub. `scripts/build_docs_site.py` only link-checks
  `<a href>`, never image `src` and never backticked paths — image and code-span paths need a
  manual check.

**~90 s DOC-CLAIM RE-VERIFICATION SET** (all exit 0 on the verified host, 2026-08-25):
`pytest tests -q` (877/2) · both `unittest discover` roots (822 / 57) · `build_docs_site.py`
(20 pages; hard-fails on a broken intra-repo .md link or heading drift) · `check_tree_positions.py`
on the hero clip · `check_live_flight_log.py eval/results/live_flight_log_*.json` ·
`predict_bird_visibility.py --fps 5.0` · the 4-command spike chain (16 s; **does not dirty any
tracked file** — `eval/results/spike_scores.json` at the root is gitignored, the committed evidence
lives in `eval/results/adr003_*/`).
