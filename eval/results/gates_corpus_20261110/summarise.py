"""Aggregate a probe.json: how often each bar kind is measurable, why not, and the dropped-write statistics.
Usage: summarise.py RESULTS_DIR [OTHER_RESULTS_DIR to diff verdicts against]"""
import json, os, re, sys
from collections import Counter, defaultdict
rows = json.load(open(os.path.join(sys.argv[1], "probe.json")))
ok = [r for r in rows if not r.get("refusal")]
print(f"logs {len(rows)}  judged {len(ok)}  refused {len(rows) - len(ok)}")
for r in rows:
    if r.get("refusal"): print(f"  REFUSED {r['id']} {r['source']}: {r['refusal'][:150]}")
pops = sorted({r["population"] for r in ok})
print("\nfirmware:", dict(Counter(re.sub(r"(V\d+\.\d+).*", r"\1", r["firmware"] or "unresolved") for r in ok).most_common()))
print("badge word:", {p: dict(Counter(r["badge"].split("·")[0].replace("gates:", "").strip() for r in ok if r["population"] == p)) for p in pops})
BARS = ["alt_any", "speed_any", "batt_any", "ekf_any", "gnss", "fence", "modes_any", "modes_seen", "no_errors", "speed_in_mode", "batt_armed", "speed_armed", "alt_armed", "ekf_armed", "gnss_armed"]
print("\nbar             " + "".join(f"{p:>30}" for p in pops) + "    (measured = PASS+FAIL / judged logs; then P/F/EI/NA)")
for b in BARS:
    line = f"{b:<16}"
    for p in pops:
        c = Counter(r["results"][b]["verdict"] for r in ok if r["population"] == p); n = sum(c.values())
        m = c["PASS"] + c["FAIL"]
        line += f"{m:>4}/{n:<3} {100 * m / n:5.1f}%  P{c['PASS']} F{c['FAIL']} EI{c['EVIDENCE_INSUFFICIENT']} NA{c['NOT_APPLICABLE']}".rjust(30)
    print(line)
tot = Counter(); 
for r in ok:
    for b in BARS: tot[r["results"][b]["verdict"]] += 1
n = sum(tot.values()); print(f"\nall bars, all logs: measured {tot['PASS'] + tot['FAIL']}/{n} = {100 * (tot['PASS'] + tot['FAIL']) / n:.1f}%   {dict(tot)}")
print("\ncould-not-tell causes (EI/NA), by bar:")
for b in BARS:
    c = Counter()
    for r in ok:
        x = r["results"][b]
        if x["verdict"] in ("EVIDENCE_INSUFFICIENT", "NOT_APPLICABLE"):
            why = (x["note"].split("; ", 1) + [""])[1]
            c[x["verdict"][:2] + ": " + re.sub(r"[-+]?\d+(\.\d+)?", "#", why)[:120]] += 1
    for k, v in c.most_common(4): print(f"  {b:<14} {v:>3}  {k}")
print("\ndropped writes (DSF.Dp):")
dsf = [r for r in ok if r["dsf_rows"]]
with_drop = [r for r in dsf if r["drop_intervals"]]
def startup(r, iv): return r["t_first"] is not None and iv[0] <= r["t_first"] + 0.05
only_start = [r for r in with_drop if all(startup(r, iv) for iv in r["drop_intervals"])]
mid = [r for r in with_drop if any(not startup(r, iv) for iv in r["drop_intervals"])]
for p in pops:
    f = lambda xs: sum(1 for r in xs if r["population"] == p)
    print(f"  {p:<14} judged {f(ok):>2} | DSF present {f(dsf):>2} | any drop interval {f(with_drop):>2} | startup-only {f(only_start):>2} | mid-log drops {f(mid):>2} | no DSF {f(ok) - f(dsf):>2}")
print("  drop counts in logs that have them:", sorted(r["dsf_dropped_max"] for r in with_drop))
print("\narming: logs with >=1 ARM row", sum(1 for r in ok if r["n_arm_rows"]), "of", len(ok), "| LOG_DISARMED values:",
      dict(Counter(str((r["results"]["batt_any"]["param"] or {}).get("values")) for r in ok)))
print("LOG_BACKEND_TYPE values:", dict(Counter(str((r["results"]["no_errors"]["param"] or {}).get("values")) for r in ok)))
print("byte holes: logs with interior holes", sum(1 for r in ok if r["byte_holes"]), "of", len(ok))
print("runtime: median run_s", sorted(r["run_s"] for r in ok)[len(ok) // 2], "max", max(r["run_s"] for r in ok))
if len(sys.argv) > 2:
    other = {r["id"]: r for r in json.load(open(os.path.join(sys.argv[2], "probe.json")))}
    print(f"\nverdict changes vs {sys.argv[2].rstrip('/').rsplit('/', 1)[-1]}:")
    ch = Counter(); badge = Counter()
    for r in ok:
        o = other.get(r["id"])
        if not o or o.get("refusal"): continue
        for b in BARS:
            a, c = o["results"][b]["verdict"], r["results"][b]["verdict"]
            if a != c: ch[(b, a[:4], c[:4])] += 1; print(f"  {r['id']} {r['population']:<14} {b:<14} {a} -> {c}: {r['results'][b]['note'][:150]}")
        wa, wc = o["badge"].split("·")[0], r["badge"].split("·")[0]
        if wa != wc: badge[(wa.strip(), wc.strip())] += 1
    print("  totals:", dict(ch)); print("  badge word changes:", dict(badge))
