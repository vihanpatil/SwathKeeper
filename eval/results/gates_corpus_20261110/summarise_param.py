"""EI causes per probe verdict, from the verdict's own note. A verdict can name several causes; `absent` causes are
exclusive (rule 1 ends the note's reason there). Usage: pp_causes2.py probe_param.json..."""
import json, re, sys, collections
LIM = [("pre_first_row", "before the first PARM row"), ("loss", "where a loss meets"), ("outside_accept", "outside accept"),
       ("nonfinite", "PARM row is non-finite"), ("tie", "split the verdict")]
def causes(note):
    if re.match(r"n=\d+; limit parameter \w+ has no PARM row", note): return ["param_absent"]
    m = re.match(r"n=\d+; (\w+) ABSENT", note)
    if m: return ["stream_absent"]
    out = [k for k, s in LIM if s in note]
    if "gap(s) or hole(s) in scope" in note: out.append("gap_or_hole")
    if re.search(r"n \d+ < min_n", note): out.append("min_n")
    if "non-finite (NaN/inf) sample" in note: out.append("nan_sample")
    return out or ["OTHER:" + note[:80]]
for f in sys.argv[1:]:
    rows = [r for r in json.load(open(f)) if not r["refusal"]]
    tot, only_lim, per = collections.Counter(), collections.Counter(), {}
    for bar in ("speed_wpnav", "speed_wp", "batt_low", "ekf_thresh"):
        c = collections.Counter()
        for r in rows:
            x = r["results"][bar]
            if x["verdict"] != "EVIDENCE_INSUFFICIENT": continue
            cs = causes(x["note"])
            for k in cs: c[k] += 1; tot[k] += 1
            lim = {k for k, _ in LIM} & set(cs)
            if lim and set(cs) <= {k for k, _ in LIM} | {"min_n"}: only_lim["+".join(sorted(lim))] += 1
        v = collections.Counter(r["results"][bar]["verdict"] for r in rows)
        per[bar] = (v["PASS"], v["FAIL"], v["EVIDENCE_INSUFFICIENT"], dict(c))
    print("==", f.split("/")[-1], len(rows), "logs")
    for b, x in per.items(): print("  ", b, "PASS", x[0], "FAIL", x[1], "EI", x[2], x[3])
    print("   EI total", sum(x[2] for x in per.values()), "| causes named:", dict(tot))
    print("   EI whose only causes are the limit's (min_n aside):", dict(only_lim), "=", sum(only_lim.values()))
    print("   EI naming any limit cause:", sum(1 for r in rows for b in per if r["results"][b]["verdict"] == "EVIDENCE_INSUFFICIENT" and {k for k, _ in LIM} & set(causes(r["results"][b]["note"]))))
