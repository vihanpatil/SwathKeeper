#!/usr/bin/env python3
"""CI regression gate for the ADR-003 spike (docs/SPIKE_ndvi_vs_rgb.md) -- devops-owned.

Reads the machine-readable eval/results/spike_scores.json that eval/score.py already writes (does
NOT reinvent a new output format -- see eval/score.py `main()`), and asserts the headline
safety-critical metric hasn't regressed on the fixed seed-42 synthetic clip:

  approaches.a_ndvi_direct.per_bird_track_fnr == 0.0

per-bird-track FNR = fraction of birds NOT detected on at least one frame before closest approach
(eval/score.py:14-15) -- the number qa-safety-reviewer/perception-ml-engineer care about most. On
the pinned seed-42 clip this baseline is 0.0 (see .claude/agent-memory/devops-reliability-engineer
for the reference run). A nonzero value here means either the detector regressed or the harness/
clip generation stopped being deterministic -- both are build-breaking for this portfolio repo.

This is deliberately a narrow, cheap check (not a re-implementation of score.py's own
PER_BIRD_FNR_BAR / FNR_GAP_BAR decision-rule bars) -- it exists to catch DRIFT from the known-good
baseline, not to re-litigate the ADR-003 decision.

Usage:
    python3 scripts/check_spike_regression.py eval/results/spike_scores.json
"""
import argparse
import json
import sys
from pathlib import Path

APPROACH = "a_ndvi_direct"
METRIC = "per_bird_track_fnr"
EXPECTED_MAX = 0.0  # baseline on seed 42 (docs/SPIKE_ndvi_vs_rgb.md); regressions must be investigated


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scores_json", type=Path, nargs="?",
                     default=Path("eval/results/spike_scores.json"))
    args = ap.parse_args()

    if not args.scores_json.exists():
        print(f"[check_spike_regression] FAIL: {args.scores_json} does not exist -- "
              f"did eval/run_spike.sh run before this step?", file=sys.stderr)
        return 1

    data = json.loads(args.scores_json.read_text())
    approaches = data.get("approaches", {})
    if APPROACH not in approaches:
        print(f"[check_spike_regression] FAIL: '{APPROACH}' missing from {args.scores_json} "
              f"approaches ({sorted(approaches)}) -- baseline_ndvi.py output or its 'approach' "
              f"field may have changed; update this script or eval/baseline_ndvi.py to match.",
              file=sys.stderr)
        return 1

    value = approaches[APPROACH].get(METRIC)
    if value is None:
        print(f"[check_spike_regression] FAIL: '{METRIC}' missing from approaches.{APPROACH} in "
              f"{args.scores_json} -- eval/score.py's output schema changed; update this script.",
              file=sys.stderr)
        return 1

    print(f"[check_spike_regression] {APPROACH}.{METRIC} = {value:.4f} "
          f"(regression bar: <= {EXPECTED_MAX})")
    if value > EXPECTED_MAX:
        print(f"[check_spike_regression] FAIL: {METRIC} regressed above {EXPECTED_MAX} on the "
              f"pinned seed-42 clip -- a bird that used to be detected before closest approach is "
              f"now missed. This is safety-critical (docs/SPIKE_ndvi_vs_rgb.md); investigate before "
              f"merging.", file=sys.stderr)
        return 1

    print("[check_spike_regression] PASS: no regression on the fixed-seed spike baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
