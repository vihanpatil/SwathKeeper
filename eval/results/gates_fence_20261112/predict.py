"""What the RULED fence loss rule (ADR-023 am. 5, tool 0.4.0) reads on each log, derived BEFORE a 0.4.0 tool exists.
Usage (python -I): predict.py OUT.json LABEL=LOG ...   Uses the 0.3.0 adapter for the streams, the PARM rows, the DSF
drop intervals and the log holes; reads the ORGN Type 1 ticks itself. For a log whose fence and home are PRESENT it
applies the ruled rule to every position sample of an unscoped `containment` bar with `source: log`:
  a source's cause at t: "pre" if t <= its first row, else "unsure" if a loss (a, b) has a <= t and b >= the latest
  row tick strictly before t; cylinder sources FENCE_ENABLE, FENCE_TYPE, FENCE_RADIUS, home; altitude-cap sources
  FENCE_ENABLE, FENCE_TYPE, FENCE_ALT_MAX, plus "pre" (home) where RelHomeAlt is masked; no key removes anything.
It does not compute margins: a verdict is predicted EI where a sample is unjudged and 0.3.0 read PASS."""
import bisect, json, sys
from pymavlink import mavutil
from swathkeeper_gates.adapters import load
from swathkeeper_gates.contract import PRESENT, Refusal, gap_threshold, log_holes

HOME, ORDER = "home (ORGN Type 1)", ("FENCE_ENABLE", "FENCE_TYPE", "FENCE_RADIUS", "FENCE_ALT_MAX", "home (ORGN Type 1)")
r6 = lambda x: round(x, 6)


def cause(t, T, lost):
    if t <= T[0]:
        return "pre", []
    p = T[bisect.bisect_left(T, t) - 1]
    hit = [x for x in lost if x[0] <= t and x[1] >= p]
    return ("unsure", hit) if hit else (None, [])


def one(path):
    try:
        log = load(path)
    except Refusal as e:
        return {"refused": str(e)[:160]}
    out = {"t0": log.t0, "fence": log.fence["state"], "fence_reason": log.fence.get("reason"), "home": log.home["state"],
           "drop_intervals": log.integrity["drop_intervals"], "holes": log_holes(log)}
    pos = log.streams["position"]
    if log.fence["state"] != PRESENT or log.home["state"] != PRESENT or pos.state != PRESENT:
        return out
    m, homes = mavutil.mavlink_connection(path, dialect="ardupilotmega"), []
    while (x := m.recv_match(type=["ORGN"])) is not None:
        if getattr(x, "Type", None) == 1:
            homes.append(r6(x.TimeUS * 1e-6))
    typ = log.fence["fence_type"]
    T = {n: sorted({t for t, _ in log.params[n]}) for n in ORDER[:4]}
    T[HOME] = sorted(set(homes))
    assert not [x for x in log.meta.get("params_nonfinite", ()) if x[1] in ORDER], "a non-finite FENCE_* row: not handled here"
    lost = ([(a, b, f"{k} firmware-dropped writes in [{a:.3f}, {b:.3f}] s (DSF.Dp)") for a, b, k in log.integrity["drop_intervals"]]
            + [(a, b, f"a log hole [{a:.3f}, {b:.3f}] s") for a, b in out["holes"]])
    src = {q: s for q, s, bit in (("cylinder", ORDER[:3] + (HOME,), 2), ("altitude cap", ORDER[:2] + (ORDER[3],), 1)) if typ & bit}
    d = pos.data[0]
    ts, alt = d["t_s"], d.get("alt_rel_home_m", [0.0] * len(d["t_s"]))
    buckets, judged = {}, []
    for t, a in zip(ts, alt):
        ok = True
        for q, names in src.items():
            held = {n: cause(t, T[n], lost) for n in names}
            if q == "altitude cap" and a is None:
                held[HOME] = ("pre", [])
            for c in ("pre", "unsure"):
                who = [n for n in ORDER if held.get(n, (None,))[0] == c]
                if who:
                    b = buckets.setdefault((q, c), {"k": 0, "t1": t, "t2": t, "names": set(), "losses": set()})
                    b["k"], b["t1"], b["t2"] = b["k"] + 1, min(b["t1"], t), max(b["t2"], t)
                    b["names"] |= set(who)
                    b["losses"] |= {x for n in who for x in held[n][1]}
                    ok = False
                    break
        judged.append(ok)
    thr = gap_threshold(ts)
    seg = [r6(y - x) <= thr for x, y in zip(ts, ts[1:])]
    parts = []
    for q in src:
        for c in ("pre", "unsure"):
            b = buckets.get((q, c))
            if b:
                names = ", ".join(n for n in ORDER if n in b["names"])
                losses = "; ".join(x[2] for x in sorted(b["losses"]))
                parts.append(f"{q}: {b['k']} at or before the first row of {names}, t in [{b['t1']:.3f}, {b['t2']:.3f}] s" if c == "pre" else
                             f"{q}: {b['k']} where a loss meets [previous row, sample] of {names} and may hide a row ({losses}), "
                             f"t in [{b['t1']:.3f}, {b['t2']:.3f}] s")
    N = judged.count(False)
    out.update(fence_type=typ, first_rows={n: T[n][0] for n in T}, n_pos=len(ts), pos_first=ts[0],
               n_today=sum(seg), n_ruled=sum(s and a and b for s, a, b in zip(seg, judged, judged[1:])), N=N,
               buckets={f"{q} {c}": b["k"] for (q, c), b in buckets.items()},
               blind_line=f"fence not usable on {N} sample(s): " + "; ".join(parts) if N else None)
    return out


res = {}
for arg in sys.argv[2:]:
    label, path = arg.split("=", 1)
    res[label] = one(path)
    if "N" in res[label]:
        print(label, {k: res[label][k] for k in ("n_today", "n_ruled", "N", "buckets")}, "\n  ", res[label]["blind_line"], flush=True)
json.dump(res, open(sys.argv[1], "w"), indent=1, sort_keys=True)
