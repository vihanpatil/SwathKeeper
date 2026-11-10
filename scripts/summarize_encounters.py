#!/usr/bin/env python3
"""Tabulate a batch of `fly_pipeline.sh encounter` runs: one row per run folder under
eval/results/encounters/, read from the run's own record and checker output. Nothing is re-scored here;
the numbers are the checker's own lines, quoted. A run with no record or no gt_cpa line is listed as such,
never dropped -- a batch that hides its failures is not a batch.

    python3 scripts/summarize_encounters.py [--since 20261110T190000Z] [--out eval/results/encounters/BATCH.md]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENC_DIR = REPO_ROOT / "eval" / "results" / "encounters"
BAR_M = 3.0


def one_run(run_dir: Path) -> dict:
    row = {"run": run_dir.name, "record": None, "speed_mps": None, "birds": None, "checker_exit": None,
           "gt_cpa_m": None, "gt_cpa_tick": None, "first_detection_m": [], "guided_windows_s": [],
           "cross_course_m": [], "takeovers": None, "resumes": None, "relatch_refused_in_progress": None,
           "status": "no record"}
    recs = sorted(run_dir.glob("encounter_*.json"))
    if not recs:
        return row
    rec = json.loads(recs[-1].read_text())
    row.update(record=recs[-1].name, speed_mps=rec.get("experiment_speed_mps"), birds=rec.get("birds_config"),
               checker_exit=rec.get("checker_exit"), status=rec.get("result"))
    out = rec.get("checker_output") or []
    for line in out:
        m = re.search(r"gt_cpa_m ([0-9.]+) m to (\S+) at tick (\d+)", line)
        if m:
            row["gt_cpa_m"] = float(m.group(1)); row["gt_cpa_tick"] = int(m.group(3))
        m = re.search(r"first detection at tick \d+, range ([0-9.]+) m", line)
        if m:
            row["first_detection_m"].append(float(m.group(1)))
        m = re.search(r"GUIDED authority ticks \d+ -> \d+ \(takeover -> resume\), \d+ tick step\(s\), ([0-9.]+) s sim", line)
        if m:
            row["guided_windows_s"].append(float(m.group(1)))
        m = re.search(r"of which cross-course dodge ([+-][0-9.]+) m", line)
        if m:
            row["cross_course_m"].append(abs(float(m.group(1))))
        m = re.search(r"relatch_refused_in_progress=(\d+)", line)
        if m:
            row["relatch_refused_in_progress"] = int(m.group(1))
    logs = sorted(run_dir.glob("live_flight_log_*.json"))
    if logs:
        try:
            ev = json.loads(logs[-1].read_text()).get("events") or []
            row["takeovers"] = sum(1 for e in ev if e.get("kind") == "takeover")
            row["resumes"] = sum(1 for e in ev if e.get("kind") == "resume")
        except (OSError, ValueError):
            pass
    if row["gt_cpa_m"] is None and row["status"] not in (None, "no record"):
        row["status"] = f"{row['status']} (no gt_cpa line)"
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default="", help="only run folders named >= this UTC stamp (e.g. 20261110T190000Z)")
    ap.add_argument("--birds", default="", help="only runs whose record names this birds config (substring)")
    ap.add_argument("--out", type=Path, default=None, help="write the markdown table here (also .json beside it)")
    args = ap.parse_args(argv)
    runs = sorted(d for d in ENC_DIR.iterdir() if d.is_dir() and d.name >= args.since) if ENC_DIR.is_dir() else []
    rows = [one_run(d) for d in runs]
    if args.birds:
        rows = [r for r in rows if r["birds"] and args.birds in r["birds"]]
    cpas = [r["gt_cpa_m"] for r in rows if r["gt_cpa_m"] is not None]
    cleared = sum(1 for c in cpas if c >= BAR_M)
    lines = [f"# Encounter batch — {len(rows)} run(s), {len(cpas)} with a measured closest approach, "
             f"**{cleared} of {len(cpas)} at or above the {BAR_M:.2f} m bar**", "",
             "Every row is an UNBOOKED scripted experiment scored by `check_live_flight_log.py` on its own bird track; "
             "`gt_cpa_m` is the checker's own line (before its freeze debit). `run completed` is the launcher's own result "
             "(did the flight fly, land and score); the checker's verdict is its exit code (1 = INVALID/FAIL, the usual for an "
             "unbooked experiment whatever the clearance). Not evidence under the claims ceiling.", "",
             "| run (UTC) | speed m/s | checker exit | gt_cpa_m | first detection m | GUIDED windows s | cross-course m | takeovers/resumes | run completed |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        fd = ", ".join(f"{v:.1f}" for v in r["first_detection_m"]) or "—"
        gw = ", ".join(f"{v:.1f}" for v in r["guided_windows_s"]) or "—"
        cc = ", ".join(f"{v:.2f}" for v in r["cross_course_m"]) or "—"
        cpa = "—" if r["gt_cpa_m"] is None else f"**{r['gt_cpa_m']:.3f}**" if r["gt_cpa_m"] >= BAR_M else f"{r['gt_cpa_m']:.3f}"
        lines.append(f"| {r['run']} | {r['speed_mps'] if r['speed_mps'] is not None else '—'} | {r['checker_exit'] if r['checker_exit'] is not None else '—'} "
                     f"| {cpa} | {fd} | {gw} | {cc} | {r['takeovers']}/{r['resumes']} | {r['status']} |")
    if cpas:
        lines += ["", f"min {min(cpas):.3f} m · median {statistics.median(cpas):.3f} m · max {max(cpas):.3f} m · "
                  f"cleared {cleared}/{len(cpas)}"]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        args.out.write_text(text)
        args.out.with_suffix(".json").write_text(json.dumps(rows, indent=1) + "\n")
        print(f"wrote {args.out} and {args.out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
