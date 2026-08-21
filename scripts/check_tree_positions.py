#!/usr/bin/env python3
"""TREE-CHECK: are the 18 known trees where the NDVI heatmap says they are?

This is the gate the runbook's proof standard points at. It answers the question
`cells_imaged` cannot: a stitched map can fill the whole grid and still be *wrong*, because a
mislocated camera paints a plausible field at the wrong coordinates. The all-time-high 697/720
clip (2026-08-18, horizon-facing mount) put 100 % of its canopy signal 9.5-11.9 m from any tree.
Every clip since the ADR-007 amendment-5 mount fix puts 100 % of it at 1.7678 m. A high cell count
with canopy in the wrong place is the WORSE failure, because it looks like the good outcome.

Method (pinned by `tests/fieldguard_planning/test_check_tree_positions.py`, which reproduces the
five published clip figures exactly -- do not "improve" it without moving those numbers on purpose):

  * Every tree centre lands exactly on a 2.5 m grid corner, so its r=1.3 m canopy straddles the
    FOUR cells sharing that corner. Those four ARE the tree's cell set -- which is why the
    historical denominators read 8 and 6 rather than 6 and 5. Each of the four sits 1.7678 m
    (a 2.5 m cell's centre-to-corner distance) from the centre.
  * imaged       := >= 1 of the four cells has a non-null mean_ndvi.
  * canopy-grade := best-of-four mean_ndvi > 0.0 (positive NDVI against this world's negative-NDVI
    soil; ADR-007 Gate 2 predicts soil -0.437 and canopy +0.614 from the band arithmetic).
  * lift         := best-of-four mean_ndvi - the clip's modal soil NDVI (the pure-ground value).

The FAIL condition is the georef-displacement signature and nothing else: a positive-NDVI cell
farther than MAX_DISPLACEMENT_M from EVERY tree centre is canopy drawn where no canopy exists.
Measured separation on the committed clips is unambiguous -- post-fix 1.7678 m, horizon-mount
6.4-11.9 m -- so the 2 m bar sits in an empty gap rather than on a judgement call.

Reads only committed artifacts (the clip's `heatmap/heatmap.json` plus
`config/static_obstacles.json`); no container, no flight, no ROS.

    python3 scripts/check_tree_positions.py eval/results/clips/<clip>
    python3 scripts/check_tree_positions.py eval/results/clips/<clip> --json

Exit 0 = no displacement. Exit 1 = displacement signature, or the clip could not be read.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
OBSTACLES_JSON = REPO_ROOT / "config" / "static_obstacles.json"

# A positive cell farther than this from every tree centre is canopy in a place with no tree.
# Sits in the measured gap between the post-fix 1.7678 m and the horizon-mount 6.3738 m.
MAX_DISPLACEMENT_M = 2.0
CANOPY_NDVI = 0.0          # this world's soil is negative NDVI; anything positive is vegetation
QUAD_TOL_M = 1e-6          # exact half-cell offsets, so the tolerance only absorbs float dust


def load_trees(path: Path = OBSTACLES_JSON) -> list:
    """The tree centres, in the same field frame as the heatmap's cx_m/cy_m."""
    return [o for o in json.loads(path.read_text())["obstacles"] if o.get("type") == "tree"]


def _nearest_tree_m(cell: dict, trees: list) -> float:
    return min(math.hypot(cell["cx_m"] - t["pos_m"][0], cell["cy_m"] - t["pos_m"][1])
               for t in trees)


def analyse(clip_dir: Path, trees: Optional[list] = None) -> dict:
    """Per-tree verdicts + the displacement check, from a clip's stitched heatmap."""
    trees = load_trees() if trees is None else trees
    heatmap = json.loads((clip_dir / "heatmap" / "heatmap.json").read_text())
    cells = heatmap["cells"]
    half = heatmap["cell_size_m"] / 2.0
    imaged_cells = [c for c in cells if c["mean_ndvi"] is not None]
    if not imaged_cells:
        raise ValueError(f"{clip_dir}: heatmap has no imaged cells -- nothing to place")

    # The modal imaged value IS bare ground: soil is most of the field, and every soil cell reads
    # the same physics-predicted constant, so the mode is exact rather than an estimate.
    soil_ndvi, soil_n = Counter(round(c["mean_ndvi"], 6) for c in imaged_cells).most_common(1)[0]

    rows = []
    for tree in trees:
        tx, ty, _ = tree["pos_m"]
        # The four cells sharing this tree's grid corner: centres exactly half a cell away in x
        # AND y. Derived from the cells' own coordinates, so no assumption about the grid origin.
        quad = [c for c in cells
                if abs(abs(c["cx_m"] - tx) - half) < QUAD_TOL_M
                and abs(abs(c["cy_m"] - ty) - half) < QUAD_TOL_M]
        hit = [c for c in quad if c["mean_ndvi"] is not None]
        best = max(hit, key=lambda c: c["mean_ndvi"]) if hit else None
        rows.append({
            "tree_id": tree["id"],
            "pos_m": [tx, ty],
            "quad_cell_ids": [c["cell_id"] for c in quad],
            "imaged": bool(hit),
            "n_quad_cells_imaged": len(hit),
            "best_cell_id": best["cell_id"] if best else None,
            "n_samples": best["n_samples"] if best else 0,
            "mean_ndvi": best["mean_ndvi"] if best else None,
            "lift": (best["mean_ndvi"] - soil_ndvi) if best else None,
            "canopy_grade": bool(best and best["mean_ndvi"] > CANOPY_NDVI),
        })

    positive = [c for c in imaged_cells if c["mean_ndvi"] > CANOPY_NDVI]
    displaced = [{"cell_id": c["cell_id"], "cx_m": c["cx_m"], "cy_m": c["cy_m"],
                  "nearest_tree_m": round(d, 4)}
                 for c, d in ((c, _nearest_tree_m(c, trees)) for c in positive)
                 if d > MAX_DISPLACEMENT_M]
    lifts = sorted(r["lift"] for r in rows if r["canopy_grade"])

    return {
        "clip_dir": str(clip_dir),
        "frames_total": heatmap.get("frames_total"),
        "cells_imaged": heatmap["cells_imaged"],
        "cells_total": heatmap["cells_total"],
        "soil_modal_ndvi": soil_ndvi,
        "soil_modal_cells": soil_n,
        "trees_total": len(trees),
        "trees_imaged": sum(1 for r in rows if r["imaged"]),
        "trees_canopy_grade": sum(1 for r in rows if r["canopy_grade"]),
        "median_lift": statistics.median(lifts) if lifts else None,
        "positive_cells": len(positive),
        "max_displacement_m": MAX_DISPLACEMENT_M,
        "displaced_cells": displaced,
        "passed": not displaced,
        "trees": rows,
    }


def format_report(result: dict) -> str:
    lines = [f"[check_tree_positions] {Path(result['clip_dir']).name}",
             f"  {result['frames_total']} frames | {result['cells_imaged']}/{result['cells_total']}"
             f" cells imaged | soil modal NDVI {result['soil_modal_ndvi']:+.6f}"
             f" on {result['soil_modal_cells']} cells",
             "",
             "  %-14s %-11s %-10s %6s %9s %9s   %s"
             % ("tree", "pos (x,y)", "cell", "n", "NDVI", "lift", "verdict")]
    for r in result["trees"]:
        x, y = r["pos_m"]
        if not r["imaged"]:
            lines.append("  %-14s (%4.1f,%4.1f) %-10s %6s %9s %9s   %s"
                         % (r["tree_id"], x, y, "--", "--", "--", "--", "NOT IMAGED"))
            continue
        verdict = "CANOPY" if r["canopy_grade"] else "imaged, soil-grade"
        lines.append("  %-14s (%4.1f,%4.1f) %-10s %6d %+9.4f %+9.4f   %s"
                     % (r["tree_id"], x, y, r["best_cell_id"], r["n_samples"],
                        r["mean_ndvi"], r["lift"], verdict))

    median = result["median_lift"]
    lines += ["",
              f"  IMAGED {result['trees_imaged']}/{result['trees_total']}"
              f"   CANOPY-GRADE {result['trees_canopy_grade']}/{result['trees_imaged']}"
              + (f"   MEDIAN LIFT {median:+.4f}" if median is not None else "   MEDIAN LIFT --")]

    n_pos, n_bad = result["positive_cells"], len(result["displaced_cells"])
    if not n_pos:
        lines.append("  DISPLACEMENT: no positive-NDVI cells -- no canopy signal to place.")
    elif n_bad:
        worst = max(result["displaced_cells"], key=lambda c: c["nearest_tree_m"])
        lines.append(f"  DISPLACEMENT: {n_bad}/{n_pos} positive cells are farther than "
                     f"{result['max_displacement_m']:.1f} m from EVERY tree centre "
                     f"(worst {worst['cell_id']} at {worst['nearest_tree_m']:.4f} m).")
    else:
        lines.append(f"  DISPLACEMENT: all {n_pos} positive cells within "
                     f"{result['max_displacement_m']:.1f} m of a tree centre.")

    if result["passed"] and n_pos:
        lines.append("[check_tree_positions] PASS: canopy signal is where the trees are.")
    elif result["passed"]:
        # Exit 0 is honest -- this gate tests placement, and nothing was placed. Saying "PASS:
        # canopy is where the trees are" about a clip with no canopy would be a claim past the
        # evidence, so it says what it actually checked instead.
        lines.append("[check_tree_positions] PASS (vacuous): no canopy signal to mislocate. "
                     "This clip is evidence of nothing; it is not a passing heatmap.")
    else:
        lines.append("[check_tree_positions] FAIL: georef-displacement signature -- canopy drawn "
                     "where no tree exists. The map is mislocated; cells_imaged will look fine. "
                     "See ADR-007 amendment 5 (sensor mount) and the recorder's pose pairing.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip_dir", type=Path, help="a clip directory (reads heatmap/heatmap.json)")
    ap.add_argument("--json", action="store_true", help="emit the result as JSON instead of a table")
    args = ap.parse_args(argv)

    try:
        result = analyse(args.clip_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[check_tree_positions] FAIL: cannot read {args.clip_dir}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2) if args.json else format_report(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
