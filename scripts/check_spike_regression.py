#!/usr/bin/env python3
"""CI regression gate for the ADR-003 spike (docs/SPIKE_ndvi_vs_rgb.md) -- devops-owned.

Reads the machine-readable eval/results/spike_scores.json that eval/score.py already writes (does
NOT reinvent a new output format -- see eval/score.py `main()`), and asserts the NDVI-direct arm
hasn't regressed on the fixed seed-42 synthetic clip:

  approaches.a_ndvi_direct.per_bird_track_fnr <= 0.0    -- headline, safety-critical
  approaches.a_ndvi_direct.fnr                <= 0.02   -- frame-level FNR, secondary
  approaches.a_ndvi_direct.precision          >= 0.40   -- secondary

per-bird-track FNR = fraction of birds NOT detected on at least one frame before closest approach
(eval/score.py:14-15) -- the number qa-safety-reviewer/perception-ml-engineer care about most. On
the pinned seed-42 clip this baseline is 0.0 (see .claude/agent-memory/devops-reliability-engineer
for the reference run). A nonzero value here means either the detector regressed or the harness/
clip generation stopped being deterministic -- both are build-breaking for this portfolio repo.

The two SECONDARY bars exist because the headline metric is coarse: the clip has 3 birds, so
per-bird-track FNR only moves in steps of 0.333 and real detector quality can slide a long way
while it still reads 0.000. Frame FNR catches "we still touch every bird, but on far fewer
frames"; precision catches a false-positive storm (every FP is a wasted dodge -- ADR-003 accepted
0.445 precision only because the FPs were one explainable static clutter feature, not noise).
Both bars sit a small honest margin on the failing side of the current measured values, so float
jitter passes and a genuine slide fails -- see BARS for those values and when they were measured.

This is deliberately a narrow, cheap check (not a re-implementation of score.py's own
PER_BIRD_FNR_BAR / FNR_GAP_BAR decision-rule bars) -- it exists to catch DRIFT from the known-good
baseline, not to re-litigate the ADR-003 decision.

Usage:
    python3 scripts/check_spike_regression.py eval/results/spike_scores.json
"""
import argparse
import json
import sys
from collections import namedtuple
from pathlib import Path

APPROACH = "a_ndvi_direct"
METRIC = "per_bird_track_fnr"   # kept for callers/greps that referenced the single-metric gate
EXPECTED_MAX = 0.0              # baseline on seed 42 (docs/SPIKE_ndvi_vs_rgb.md)

MAX = "max"   # value must be <= bar
MIN = "min"   # value must be >= bar

# metric  -- key inside approaches.<APPROACH> as eval/score.py writes it
# sense   -- MAX or MIN
# bar     -- the CI bar
# why     -- what a breach means, printed on FAIL
Bar = namedtuple("Bar", "metric sense bar why")

# Measured on the pinned seed-42 synthetic clip, 2026-08-04 (eval/results/spike_scores.json; the
# same numbers ADR-003 quotes): per_bird_track_fnr 0.000, fnr 0.0185 (1 miss / 54 bird-frames),
# precision 0.4454 (53 TP / 66 FP). Bars are set with a small honest margin BELOW that measured
# performance -- 0.0185 -> 0.02 and 0.4454 -> 0.40 -- so re-running the harness never fails on
# rounding, but a real quality slide does. Tighten these if the real-Gazebo re-run (ADR-003's
# still-open confirmation) lands better numbers; never loosen one to make a red build green.
BARS = (
    Bar(METRIC, MAX, EXPECTED_MAX,
        "a bird that used to be detected before closest approach is now missed. This is "
        "safety-critical (docs/SPIKE_ndvi_vs_rgb.md); investigate before merging."),
    Bar("fnr", MAX, 0.02,
        "frame-level FNR slid below the 2026-08-04 baseline (0.0185) -- birds are being caught on "
        "fewer frames, which shrinks the reaction margin even while per-bird-track FNR still "
        "reads 0.000."),
    Bar("precision", MIN, 0.40,
        "precision slid below the 2026-08-04 baseline (0.4454) -- more false positives means more "
        "wasted dodges, and ADR-003 only accepted this precision because the FPs were one "
        "explainable static clutter feature."),
)


def _breaches(bar, value):
    """True if `value` fails `bar`. Split out so the sense logic is tested, not re-derived."""
    return value > bar.bar if bar.sense is MAX else value < bar.bar


def check_scores(data, approach=APPROACH, bars=BARS):
    """Apply every bar to one approach in a parsed spike_scores.json.

    Returns (report_lines, failures): `report_lines` is the per-metric readout for stdout,
    `failures` the human-readable reasons for stderr. Empty `failures` == the gate passes. Pure --
    no printing, no exiting, no filesystem -- so the bars are unit-testable with synthetic dicts.
    """
    report_lines, failures = [], []

    approaches = data.get("approaches", {}) if isinstance(data, dict) else {}
    metrics = approaches.get(approach)
    if not isinstance(metrics, dict):
        failures.append(f"'{approach}' missing from approaches ({sorted(approaches)}) -- "
                        f"baseline_ndvi.py output or its 'approach' field may have changed; "
                        f"update this script or eval/baseline_ndvi.py to match.")
        return report_lines, failures

    for bar in bars:
        value = metrics.get(bar.metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            failures.append(f"'{bar.metric}' missing (or not a number) in approaches.{approach} "
                            f"-- eval/score.py's output schema changed; update this script.")
            continue
        op = "<=" if bar.sense is MAX else ">="
        report_lines.append(f"{approach}.{bar.metric} = {value:.4f} (bar: {op} {bar.bar})")
        if _breaches(bar, value):
            failures.append(f"{bar.metric} = {value:.4f} breaches the bar ({op} {bar.bar}) on the "
                            f"pinned seed-42 clip -- {bar.why}")

    return report_lines, failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scores_json", type=Path, nargs="?",
                     default=Path("eval/results/spike_scores.json"))
    args = ap.parse_args(argv)   # argv=None -> sys.argv, so the CLI contract is unchanged

    if not args.scores_json.exists():
        print(f"[check_spike_regression] FAIL: {args.scores_json} does not exist -- "
              f"did eval/run_spike.sh run before this step?", file=sys.stderr)
        return 1

    data = json.loads(args.scores_json.read_text())
    report_lines, failures = check_scores(data)

    for line in report_lines:
        print(f"[check_spike_regression] {line}")
    for failure in failures:
        print(f"[check_spike_regression] FAIL: {failure} (in {args.scores_json})", file=sys.stderr)
    if failures:
        return 1

    print("[check_spike_regression] PASS: no regression on the fixed-seed spike baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
