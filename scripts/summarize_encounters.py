#!/usr/bin/env python3
"""Tabulate a batch of `fly_pipeline.sh encounter` runs: one row per run folder under
eval/results/encounters/, read from the run's own record and checker output. Nothing is re-scored here;
the numbers are the checker's own lines, quoted. A run with no record or no gt_cpa line is listed as such,
never dropped -- a batch that hides its failures is not a batch.

    python3 scripts/summarize_encounters.py [--since 20261110T190000Z] [--out eval/results/encounters/BATCH.md]
"""
from __future__ import annotations

import argparse
import hashlib
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
           "status": "no record",
           # booked-take columns (None on an unbooked experiment): the checker's own lines, never recomputed
           "booking": None, "booked_speed_mps": None, "verdict": None, "gt_cpa_gated_m": None,
           "freeze_debit_m": None, "range_error_p95_m": None, "range_error_unambiguous_n": None,
           "range_error_frames": None, "frustum": None, "window_speed_ratio": None, "window_median_mps": None,
           "detect_p95_ms": None, "detect_max_ms": None, "static_birds_min_m": None,
           "flight_log": None, "flight_log_sha256": None}
    recs = sorted(run_dir.glob("encounter_*.json"))
    if not recs:
        return row
    rec = json.loads(recs[-1].read_text())
    row.update(record=recs[-1].name, speed_mps=rec.get("experiment_speed_mps"), birds=rec.get("birds_config"),
               checker_exit=rec.get("checker_exit"), status=rec.get("result"))
    bk = rec.get("booking")
    if isinstance(bk, dict):
        row["booking"] = Path(str(bk.get("path", ""))).name or None
        row["booked_speed_mps"] = bk.get("booked_speed_mps")
    out = rec.get("checker_output") or []
    for line in out:
        m = re.search(r"^\[check_live_flight_log\] (VALID|INVALID|ACKNOWLEDGED|FAIL)\b", line)
        if m and row["verdict"] is None:
            row["verdict"] = m.group(1)
        m = re.search(r"gt_cpa_gated_m ([0-9.]+) m = gt_cpa_m minus a ([0-9.]+) m freeze debit", line)
        if m:
            row["gt_cpa_gated_m"] = float(m.group(1)); row["freeze_debit_m"] = float(m.group(2))
        m = re.search(r"range_estimate_error_m over (\d+) rendered frame\(s\).*?p95 ([0-9.]+) m, max [0-9.]+ m, min [0-9.]+ m over the (\d+) unambiguously placed sample", line)
        if m:
            row["range_error_frames"] = int(m.group(1)); row["range_error_p95_m"] = float(m.group(2))
            row["range_error_unambiguous_n"] = int(m.group(3))
        m = re.search(r"frustum containment: (\d+) of (\d+) detection", line)
        if m:
            row["frustum"] = f"{m.group(1)}/{m.group(2)}"
        m = re.search(r"ENCOUNTER window speed .*?median ([0-9.]+) m/s = ([0-9.]+)x booked", line)
        if m:
            row["window_median_mps"] = float(m.group(1)); row["window_speed_ratio"] = float(m.group(2))
        m = re.search(r"detect wall time p95 ([0-9.]+) ms \(bar 25\) max ([0-9.]+) ms", line)
        if m:
            row["detect_p95_ms"] = float(m.group(1)); row["detect_max_ms"] = float(m.group(2))
        if "SCORED THERE as static obstacles" in line:
            for d in re.findall(r"bird_\d+ ([0-9.]+) m", line):
                v = float(d)
                row["static_birds_min_m"] = v if row["static_birds_min_m"] is None else min(row["static_birds_min_m"], v)
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
            row["flight_log"] = logs[-1].name
            row["flight_log_sha256"] = hashlib.sha256(logs[-1].read_bytes()).hexdigest()
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
    ap.add_argument("--encounters-dir", type=Path, default=ENC_DIR,
                    help="the run folders to read (default eval/results/encounters/ of this checkout)")
    args = ap.parse_args(argv)
    enc_dir = args.encounters_dir
    runs = sorted(d for d in enc_dir.iterdir() if d.is_dir() and d.name >= args.since) if enc_dir.is_dir() else []
    rows = [one_run(d) for d in runs]
    if args.birds:
        rows = [r for r in rows if r["birds"] and args.birds in r["birds"]]
    cpas = [r["gt_cpa_m"] for r in rows if r["gt_cpa_m"] is not None]
    cleared = sum(1 for c in cpas if c >= BAR_M)
    booked = bool(rows) and all(r["booking"] for r in rows)
    if booked:
        # a BOOKED batch is read on the GATED number and the checker's verdict word, not on the raw gt_cpa_m
        gated = [r["gt_cpa_gated_m"] for r in rows if r["gt_cpa_gated_m"] is not None]
        valid = [r for r in rows if r["verdict"] == "VALID"]
        valid_clear = [r for r in valid if r["gt_cpa_gated_m"] is not None and r["gt_cpa_gated_m"] >= BAR_M]
        lines = [f"# BOOKED encounter batch — {len(rows)} run(s), {len(valid)} VALID under the flight-log gate, "
                 f"**{len(valid_clear)} of {len(rows)} VALID at or above the {BAR_M:.2f} m bar on the GATED closest approach**", "",
                 "Every row is a BOOKED take: `scripts/fly_pipeline.sh encounter --booking <artifact>` typed the booked WP_SPD and "
                 "`check_live_flight_log.py --booking` scored the run on its own bird track with every bar of the flight-log gate "
                 "(booked speed, acquisition, range error, frustum, static map, runtime, truth resolution). `verdict` is the "
                 "checker's first word; `gt_cpa_gated_m` is gt_cpa_m minus the freeze debit — THE number gated. A run that is not "
                 "VALID is listed with its exit code and never dropped. Sim-demonstrated, evidence-gated; one scenario.", "",
                 "| run (UTC) | booking | booked m/s | verdict | exit | gt_cpa_m | gt_cpa_gated_m | debit m | acquired m | range err p95 m (n unamb/frames) | frustum | window ×booked | detect p95/max ms | static birds min m | cross-course m | take/resume | run |",
                 "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            fd = ", ".join(f"{v:.1f}" for v in r["first_detection_m"]) or "—"
            cc = ", ".join(f"{v:.2f}" for v in r["cross_course_m"]) or "—"
            def f(v, fmt):
                return "—" if v is None else format(v, fmt)
            g = r["gt_cpa_gated_m"]
            gated_s = "—" if g is None else (f"**{g:.3f}**" if g >= BAR_M else f"{g:.3f} ✗")
            rng = ("—" if r["range_error_p95_m"] is None else
                   f"{r['range_error_p95_m']:.4f} ({r['range_error_unambiguous_n']}/{r['range_error_frames']})")
            det = "—" if r["detect_p95_ms"] is None else f"{r['detect_p95_ms']:.3f} / {r['detect_max_ms']:.3f}"
            lines.append(f"| {r['run']} | {r['booking'] or '—'} | {f(r['booked_speed_mps'], '.1f')} | {r['verdict'] or '—'} | "
                         f"{r['checker_exit'] if r['checker_exit'] is not None else '—'} | {f(r['gt_cpa_m'], '.4f')} | {gated_s} | "
                         f"{f(r['freeze_debit_m'], '.4f')} | {fd} | {rng} | {r['frustum'] or '—'} | "
                         f"{f(r['window_speed_ratio'], '.3f')} | {det} | {f(r['static_birds_min_m'], '.3f')} | {cc} | "
                         f"{r['takeovers']}/{r['resumes']} | {r['status']} |")
        if gated:
            lines += ["", f"gated: min {min(gated):.4f} m · median {statistics.median(gated):.4f} m · max {max(gated):.4f} m · "
                      f"VALID {len(valid)}/{len(rows)} · VALID and ≥ {BAR_M:.2f} m gated {len(valid_clear)}/{len(rows)}"]
        if cpas:
            lines += [f"raw gt_cpa_m: min {min(cpas):.4f} m · median {statistics.median(cpas):.4f} m · max {max(cpas):.4f} m"]
        not_valid = [r for r in rows if r["verdict"] != "VALID"]
        if not_valid:
            lines += ["", "Not VALID: " + "; ".join(f"{r['run']} ({r['verdict'] or 'no verdict'}, exit {r['checker_exit']})"
                                                     for r in not_valid)]
    else:
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
