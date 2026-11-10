"""Classify each corpus log by its OWN content, not by where it was found (QA G343).
sitl = SIM/SIM2 records or 'SITL' in a MSG row; synthetic = a MSG banner that says so; hardware = a '<board> <uid>'
banner (the tool's source.hardware); else unclassified. Usage: classify.py CORPUS_DIR PROBE_JSON OUT_JSON"""
import json, os, re, sys
from pymavlink import DFReader
corpus, probe, out = sys.argv[1:4]
rows = {r["id"]: r for r in json.load(open(probe))}
res = {}
for m in json.load(open(os.path.join(corpus, "manifest.json"))):
    r = DFReader.DFReader_binary(os.path.join(corpus, m["id"], "log.bin")); types, msgs = set(), []
    for _ in range(3_000_000):
        x = r.recv_msg()
        if x is None: break
        t = x.get_type(); types.add(t)
        if t == "MSG" and len(msgs) < 60: msgs.append(str(getattr(x, "Message", "")))
    text = " | ".join(msgs)
    sim = sorted(t for t in types if t in ("SIM", "SIM2", "SIMSTATE"))
    board = next((mm for mm in msgs if re.search(r"\S+ [0-9A-F]{8} [0-9A-F]{8} [0-9A-F]{8}$", mm)), None)
    if "synthetic" in text.lower(): kind, why = "synthetic", next(mm for mm in msgs if "synthetic" in mm.lower())
    elif sim or "SITL" in text: kind, why = "sitl", (", ".join(sim) + " records" if sim else "MSG mentions SITL")
    elif board: kind, why = "hardware", "board banner: " + board.split()[0]
    else: kind, why = "unclassified", "no SIM record, no board banner"
    res[m["id"]] = {"population": m["population"], "kind": kind, "evidence": why, "judged": not rows.get(m["id"], {}).get("refusal")}
json.dump(res, open(out, "w"), indent=1)
from collections import Counter
for pop in ("github", "sitl-autotest"):
    print(pop, "all:", dict(Counter(v["kind"] for v in res.values() if v["population"] == pop)), "| judged:", dict(Counter(v["kind"] for v in res.values() if v["population"] == pop and v["judged"])))
for i, v in sorted(res.items()):
    if v["population"] == "github": print(" ", i, v["kind"], "judged" if v["judged"] else "REFUSED", "-", v["evidence"][:60])
