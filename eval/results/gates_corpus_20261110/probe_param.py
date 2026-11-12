"""Probe parameter-following limits (tool 0.3.0) over the corpus. Usage: probe_param.py TOOL_BIN CORPUS_DIR RESULTS_DIR [key]
Four unscoped bars whose limit follows a logged parameter; with `key` the bars file declares
limit_before_first_parm_row. PASS/FAIL = the limit was knowable and the bar measured; EI = could not tell.
The limits are realistic, not loose, so a FAIL here is a measurement against a waypoint-speed or failsafe parameter in
every mode, NOT a finding about a vehicle. Written and committed 2026-11-11 before a 0.3.0 tool existed to run it."""
import json, os, subprocess, sys
tool, corpus, results = sys.argv[1:4]
key = len(sys.argv) > 4 and sys.argv[4] == "key"
B = "  - {{id: {i}, kind: series_bound, severity: {s}, provenance: {{text: probe, param: {p}}}, scope: {{armed: null, modes: null}}, " \
    "min_n: 10, params: {{channel: {c}, bound: {b}, limit: {{param: {p}, scale: {k}, accept: [{lo}, {hi}]}}}}}}\n"
BARS = ("schema: swathkeeper-bars/1.0\ncontract: swathkeeper-flightlog/1.0\n"
        + ("assume: [limit_before_first_parm_row]\n" if key else "") + "bars:\n"
        + B.format(i="speed_wpnav", s="should", p="WPNAV_SPEED", c="velocity.groundspeed_mps", b="ceiling", k="0.011", lo="100.0", hi="2000.0")
        + B.format(i="speed_wp", s="should", p="WP_SPD", c="velocity.groundspeed_mps", b="ceiling", k="1.1", lo="1.0", hi="20.0")
        + B.format(i="batt_low", s="must", p="BATT_LOW_VOLT", c="battery.voltage_v", b="floor", k="1.0", lo="5.0", hi="60.0")
        + B.format(i="ekf_thresh", s="should", p="FS_EKF_THRESH", c="ekf.vel_ratio", b="ceiling", k="1.0", lo="0.5", hi="1.0"))
rows = []
for m in json.load(open(os.path.join(corpus, "manifest.json"))):
    d = os.path.join(results, m["id"]); os.makedirs(d, exist_ok=True)
    bars, out = os.path.join(d, "bars.yaml"), os.path.join(d, "verdict.json")
    open(bars, "w").write(BARS)
    r = subprocess.run([tool, "run", "--log", os.path.join(corpus, m["id"], "log.bin"), "--bars", bars, "--out", out],
                       capture_output=True, text=True, timeout=900)
    v = json.load(open(out))
    rows.append({"id": m["id"], "exit": r.returncode, "badge": v["badge"], "refusal": v["refusal"],
                 "firmware": (v.get("source") or {}).get("firmware"), "assumptions": v["assumptions"],
                 "results": {x["id"]: {"verdict": x["verdict"], "n": x["n"], "measured": x["measured"],
                                       "limit_in_log": x.get("limit_in_log"), "note": x["note"]} for x in v["results"]}})
    print(m["id"], r.returncode, v["badge"] if not v["refusal"] else "REFUSED: " + v["refusal"][:90])
json.dump(rows, open(os.path.join(results, "probe_param.json"), "w"), indent=1)
