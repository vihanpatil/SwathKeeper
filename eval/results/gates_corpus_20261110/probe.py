"""Run a measurability probe over a corpus with one installed swathkeeper-gates binary.
Usage: probe.py TOOL_BIN CORPUS_DIR RESULTS_DIR. Limits are deliberately loose: a PASS/FAIL means the bar was
MEASURABLE on that log, EI/NA means the tool could not tell / measured an absence. One bar per kind and scope."""
import json, os, subprocess, sys, time
tool, corpus, results = sys.argv[1:4]
manifest = json.load(open(os.path.join(corpus, "manifest.json")))
BARS = """schema: swathkeeper-bars/1.0
contract: swathkeeper-flightlog/1.0
bars:
  - {{id: alt_any, kind: series_bound, severity: should, provenance: {{text: probe}}, scope: {{armed: null, modes: null}}, min_n: 10, params: {{channel: position.alt_rel_home_m, bound: floor, limit: -100000.0}}}}
  - {{id: speed_any, kind: series_bound, severity: should, provenance: {{text: probe}}, scope: {{armed: null, modes: null}}, min_n: 10, params: {{channel: velocity.groundspeed_mps, bound: ceiling, limit: 100000.0}}}}
  - {{id: batt_any, kind: series_bound, severity: must, provenance: {{text: probe, param: LOG_DISARMED}}, scope: {{armed: null, modes: null}}, min_n: 10, params: {{channel: battery.voltage_v, bound: floor, limit: -1.0}}}}
  - {{id: ekf_any, kind: series_bound, severity: should, provenance: {{text: probe}}, scope: {{armed: null, modes: null}}, min_n: 10, params: {{channel: ekf.vel_ratio, bound: ceiling, limit: 100000.0}}}}
  - {{id: gnss, kind: gnss_quality, severity: should, provenance: {{text: probe}}, scope: {{armed: null, modes: null}}, min_n: 10, params: {{fix_min: 3, sats_min: 6, max_outage_s: 5}}}}
  - {{id: fence, kind: containment, severity: should, provenance: {{text: probe}}, scope: {{armed: null, modes: null}}, min_n: 10, params: {{source: log}}}}
  - {{id: modes_any, kind: mode_transitions, severity: must, provenance: {{text: probe}}, scope: {{armed: null, modes: null}}, min_n: 1, params: {{allowed: [["*", "*"]]}}}}
  - {{id: modes_seen, kind: mode_transitions, severity: should, provenance: {{text: "probe, only the modes this log used"}}, scope: {{armed: null, modes: null}}, min_n: 1, params: {{allowed: {seen}}}}}
  - {{id: no_errors, kind: no_events, severity: must, provenance: {{text: probe, param: LOG_BACKEND_TYPE}}, scope: {{armed: null, modes: null}}, min_n: 10, params: {{kinds: [error]}}}}
  - {{id: speed_in_mode, kind: series_bound, severity: should, provenance: {{text: "probe, dominant mode"}}, scope: {{armed: null, modes: ["{mode}"]}}, min_n: 10, params: {{channel: velocity.groundspeed_mps, bound: ceiling, limit: 100000.0}}}}
  - {{id: batt_armed, kind: series_bound, severity: should, provenance: {{text: probe}}, scope: {{armed: true, modes: null}}, min_n: 10, params: {{channel: battery.voltage_v, bound: floor, limit: -1.0}}}}
  - {{id: speed_armed, kind: series_bound, severity: should, provenance: {{text: probe}}, scope: {{armed: true, modes: null}}, min_n: 10, params: {{channel: velocity.groundspeed_mps, bound: ceiling, limit: 100000.0}}}}
  - {{id: alt_armed, kind: series_bound, severity: should, provenance: {{text: probe}}, scope: {{armed: true, modes: null}}, min_n: 10, params: {{channel: position.alt_rel_home_m, bound: floor, limit: -100000.0}}}}
  - {{id: ekf_armed, kind: series_bound, severity: should, provenance: {{text: probe}}, scope: {{armed: true, modes: null}}, min_n: 10, params: {{channel: ekf.vel_ratio, bound: ceiling, limit: 100000.0}}}}
  - {{id: gnss_armed, kind: gnss_quality, severity: should, provenance: {{text: probe}}, scope: {{armed: true, modes: null}}, min_n: 10, params: {{fix_min: 3, sats_min: 6, max_outage_s: 5}}}}
"""
def run(args):
    t = time.time(); r = subprocess.run([tool, *args], capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout, r.stderr, round(time.time() - t, 2)
rows = []
for m in manifest:
    log, d = os.path.join(corpus, m["id"], "log.bin"), os.path.join(results, m["id"]); os.makedirs(d, exist_ok=True)
    row = {k: m[k] for k in ("id", "population", "source", "path", "size_bytes", "sha256")}
    code, out, err, dt = run(["inspect", "--log", log])
    row["inspect_exit"], row["inspect_s"] = code, dt
    if code != 0:
        row["refusal"] = err.strip().splitlines()[-1][:300] if err.strip() else "?"; rows.append(row); print(m["id"], "REFUSED", row["refusal"][:120]); continue
    ins = json.loads(out); open(os.path.join(d, "inspect.json"), "w").write(out)
    wins = ins["streams"]["mode"].get("windows") or []
    dur = {}
    for a, b, name in wins:
        if name: dur[name] = dur.get(name, 0) + (b - a)
    mode = max(dur, key=dur.get) if dur else "AUTO"
    seen = "[" + ", ".join(f'["*", "{m}"]' for m in sorted(dur)) + "]" if dur else '[["*", "*"]]'
    bars = os.path.join(d, "bars.yaml"); open(bars, "w").write(BARS.format(mode=mode, seen=seen))
    code, out, err, dt = run(["run", "--log", log, "--bars", bars, "--out", os.path.join(d, "verdict.json")])
    v = json.load(open(os.path.join(d, "verdict.json")))
    src, integ, st = ins["source"], ins["integrity"], ins["streams"]
    row.update(run_exit=code, run_s=dt, badge=v["badge"], refusal=v["refusal"], vehicle=src["vehicle"], firmware=src["firmware"],
               duration_s=src["duration_s"], dominant_mode=mode, n_mode_rows=st["mode"]["n"], n_arm_rows=st["arming"]["n"],
               states={k: s.get("state") for k, s in st.items()}, events_reason=(st["events"].get("reason") or "")[:160],
               dsf_rows=integ.get("dsf_rows"), dsf_dropped_max=integ.get("dsf_dropped_max"), drop_intervals=integ.get("drop_intervals"),
               byte_holes=len(integ.get("holes") or []), bytes_skipped_interior=integ.get("bytes_skipped_interior"),
               t_first=min((i["t_first"] for s in st.values() for i in (s.get("instances") or {}).values() if i.get("t_first") is not None), default=None),
               results={r["id"]: {"verdict": r["verdict"], "n": r["n"], "note": r["note"], "param": r["param_in_log"]} for r in v["results"]})
    rows.append(row)
    print(m["id"], f"{dt:6.1f}s", (src["firmware"] or "?")[:26].ljust(26), v["badge"] if not v["refusal"] else "REFUSED: " + v["refusal"][:90])
json.dump(rows, open(os.path.join(results, "probe.json"), "w"), indent=1)
