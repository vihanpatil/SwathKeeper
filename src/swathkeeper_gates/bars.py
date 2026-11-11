"""Bars (design §3): the strict YAML loader, the closed `swathkeeper-bars/1.0` schema, and the five kinds.

A kind only MEASURES (its windows, n, any violation, non-finite samples, its stream's gaps); `_decide`
applies §3.2's fixed order to every kind and adds the log's holes (byte skips, and gaps in every raw series stream
at once: contract.log_holes), so the order and the hole rule live in exactly one place. Stdlib + PyYAML.
"""
import bisect
import hashlib
import math
import re

import yaml

from . import CONTRACT
from .contract import (ABSENT, PRESENT, SERIES, TICK_S, Refusal, armed_windows, fired_gaps, gap_threshold, hits,
                       in_windows, intersect, log_holes, median_period, merge, mode_windows, r6, subtract, unsure, witnessed)

PASS, FAIL, EI, NA = "PASS", "FAIL", "EVIDENCE_INSUFFICIENT", "NOT_APPLICABLE"
SCHEMA = "swathkeeper-bars/1.0"
CONTRACT_RE = re.compile(r"swathkeeper-flightlog/1\.(\d+)")     # the major must match the tool's (minor: G249)
ID_RE = re.compile(r"[a-z0-9_]{1,40}")
PARAM_RE = re.compile(r"[A-Z][A-Z0-9_]{0,15}")
INT_TEXT = re.compile(r"-?(0|[1-9][0-9]*)")
FLOAT_TEXT = re.compile(r"-?[0-9]+\.[0-9]+([eE][-+]?[0-9]+)?|-?[0-9]+[eE][-+]?[0-9]+")
M_PER_DEG = 111318.84502145034    # ArduPilot's LOCATION_SCALING_FACTOR (m per 1e-7 deg) x 1e7
ASSUME = "arming_before_first_arm_row"     # A1/A2: the closed set of declarable assumptions, and their fixed text
ASSUMPTIONS = {ASSUME: "Before the first ARM row the vehicle is in the opposite state of that row: armed before a first "
                       "disarm, disarmed before a first arm. A log with no ARM row is not covered: arming stays ABSENT. "
                       "The tool does not verify this.",
               "limit_before_first_parm_row": "Up to and including its first PARM row, a parameter a bar takes from PARM "
               "held that row's value, and no row of it was lost in a DSF.Dp drop interval that begins at or before that row "
               "or at the log's start, including the part of that interval after the row. Not covered: a first row more than "
               "5 s after the log's start, log holes, and later drop intervals; these losses, which the log counts or shows, "
               "still read could not tell. The tool does not verify this."}
LIMIT_ASSUME = "limit_before_first_parm_row"
PARM_DUMP_S = 5.0                 # the limit assumption applies only to a first PARM row this close to t0 (v2.1 D2)
MODE_PREFIX_S = 1.0               # longer than this before the first MODE row: mode-scoped bars are EI (G234)


class _Strict(yaml.SafeLoader):
    """SafeLoader that refuses a duplicate key at any depth (PyYAML keeps the LAST one silently, design §0),
    the merge key `<<`, and any number whose source text is not plain decimal: YAML 1.1 reads `022` as 18,
    `18:36` as 1116 and `0x12`, `1_8.6`, `.inf` and `.nan` as numbers too (G236)."""

    def construct_mapping(self, node, deep=False):
        seen = []
        for k, _ in node.value:
            key = self.construct_object(k, deep=True)
            if k.tag == "tag:yaml.org,2002:merge" or key in seen:
                raise Refusal(f"duplicate or merge key {key!r} at line {k.start_mark.line + 1}")
            seen.append(key)
        return super().construct_mapping(node, deep=deep)

    def number(self, node, rx, cast):
        if not rx.fullmatch(node.value):
            raise Refusal(f"number {node.value!r} at line {node.start_mark.line + 1} is not plain decimal")
        return cast(node.value)


_Strict.add_constructor("tag:yaml.org,2002:int", lambda ld, n: ld.number(n, INT_TEXT, int))
_Strict.add_constructor("tag:yaml.org,2002:float", lambda ld, n: ld.number(n, FLOAT_TEXT, float))


def load_yaml(raw, what):
    try:
        return yaml.load(raw, Loader=_Strict)
    except (yaml.YAMLError, ValueError) as e:      # ValueError: an impossible date such as 2027-13-01
        raise Refusal(f"{what}: invalid YAML: {e}") from None


def check(v, spec, where):
    """A closed-schema interpreter (§3.1). A dict spec is a closed mapping (a key ending in '?' is optional,
    any other is required, an unknown key refuses); a tuple is the set of allowed strings; [spec, n] is a
    list of at least n items of spec; a callable validates (and raises)."""
    if isinstance(spec, dict):
        if not isinstance(v, dict):
            raise Refusal(f"{where}: expected a mapping, got {v!r}")
        keys = {k.rstrip("?"): k for k in spec}
        missing = sorted(k for k, raw in keys.items() if not raw.endswith("?") and k not in v)
        unknown = sorted(map(str, set(v) - set(keys)))
        if missing or unknown:
            raise Refusal(f"{where}: missing keys {missing}, unknown keys {unknown}")
        for k in v:
            check(v[k], spec[keys[k]], f"{where}.{k}")
    elif isinstance(spec, tuple):
        if not isinstance(v, str) or v not in spec:
            raise Refusal(f"{where}: {v!r} is not one of {list(spec)}")
    elif isinstance(spec, list):
        if not isinstance(v, list) or len(v) < spec[1]:
            raise Refusal(f"{where}: expected a list of at least {spec[1]} item(s), got {v!r}")
        for i, x in enumerate(v):
            check(x, spec[0], f"{where}[{i}]")
    else:
        spec(v, where)
    return v


def num(lo=None, hi=None, integer=False):
    """int or float and never bool (`yes` loads as True) nor a string (`1e3` is one under YAML 1.1); finite."""
    def f(v, where):
        ok = isinstance(v, int) if integer else isinstance(v, (int, float))
        if isinstance(v, bool) or not ok or not math.isfinite(v) or not (lo is None or v >= lo) or not (hi is None or v <= hi):
            raise Refusal(f"{where}: {v!r} is not a finite {'integer' if integer else 'number'} in [{lo}, {hi}]")
    return f


def string(rx=None, what="a non-empty string"):
    def f(v, where):
        if not isinstance(v, str) or not v.strip() or (rx is not None and not rx.fullmatch(v)):
            raise Refusal(f"{where}: {v!r} is not {what}")
    return f


def fixed(*specs):
    def f(v, where):
        if not isinstance(v, list) or len(v) != len(specs):
            raise Refusal(f"{where}: expected a list of {len(specs)}, got {v!r}")
        for i, (x, sp) in enumerate(zip(v, specs)):
            check(x, sp, f"{where}[{i}]")
    return f


def _follows(b):
    """Does this bar's limit follow the log's own parameter (0.3.0)?"""
    return isinstance(b["params"].get("limit"), dict)


def _limit(v, where):
    """A finite number, or the log's own PARM rows of `param` times `scale`, usable only inside `accept` (0.3.0). A
    mapping is legal only here: every other numeric field is num(), which refuses one."""
    if isinstance(v, bool) or not isinstance(v, (int, float, dict)) or (not isinstance(v, dict) and not math.isfinite(v)):
        raise Refusal(f"{where}: {v!r} is not a finite number or a mapping {{param, scale?, accept}}")
    if isinstance(v, dict):
        check(v, {"param": string(PARAM_RE, "a parameter name of [A-Z][A-Z0-9_]{0,15}"), "scale?": _scale,
                  "accept": fixed(num(), num())}, where)
        if v["accept"][0] > v["accept"][1]:
            raise Refusal(f"{where}.accept: low {v['accept'][0]!r} > high {v['accept'][1]!r}")
        if not all(math.isfinite(v.get("scale", 1) * x) for x in v["accept"]):      # G369: S*v must stay a JSON number
            raise Refusal(f"{where}: scale x accept is not finite")


def _scale(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        raise Refusal(f"{where}: {v!r} is not a finite number > 0")


def _armed(v, where):
    if v is not True and v is not None:          # identity, not equality: 1 == True
        raise Refusal(f"{where}: {v!r} is not true or null (false refuses: no v1 bar wants disarmed-only, "
                      "and it reads as \"don't care\")")


STR, LAT, LON, INT0 = string(), num(-90, 90), num(-180, 180), num(0, integer=True)
PARAMS = {
    "series_bound": {"channel": tuple(f"{s}.{c}" for s, cs in SERIES.items() for c in cs), "bound": ("floor", "ceiling"),
                     "limit": _limit},
    "gnss_quality": {"fix_min": INT0, "sats_min": INT0, "max_outage_s": num(0)},
    "containment": {"source": ("log", "yaml"), "polygon?": [fixed(LAT, LON), 3], "alt_max_rel_home_m?": num(),
                    "exclusions?": [{"lat": LAT, "lon": LON, "radius_m": num(0)}, 0]},
    "mode_transitions": {"allowed": [fixed(STR, STR), 1]},
    "no_events": {"kinds": [("error",), 1], "ignore?": [fixed(INT0, INT0), 0]},
}
BAR = {"id": string(ID_RE, "an id of [a-z0-9_]{1,40}"), "kind": tuple(PARAMS), "severity": ("must", "should"),
       "provenance": {"text": STR, "param?": STR},
       "scope": {"armed": _armed, "modes": lambda v, where: v is None or check(v, [STR, 1], where)},
       "min_n": num(1, integer=True), "params": lambda v, where: None}      # params: checked per kind below
DOC = {"schema": (SCHEMA,), "contract": string(CONTRACT_RE, "swathkeeper-flightlog/1.x (the tool's major)"),
       "bars": [BAR, 1], "assume?": [tuple(ASSUMPTIONS), 1]}


def validate(doc):
    """A loaded bars document -> its bars, or a refusal naming the first thing wrong (§3.1, §5)."""
    bars = check(doc, DOC, "bars file")["bars"]
    if int(CONTRACT_RE.fullmatch(doc["contract"])[1]) > int(CONTRACT.rsplit(".", 1)[1]):
        raise Refusal(f"bars file: the bars file needs {doc['contract']}; this tool speaks {CONTRACT}")
    for b in bars:
        w, p = f"bar {b['id']}", check(b["params"], PARAMS[b["kind"]], f"bar {b['id']}.params")
        if [x["id"] for x in bars].count(b["id"]) > 1:
            raise Refusal(f"{w}: duplicate id")
        if {"*", "<start>"} & set(b["scope"]["modes"] or ()):
            raise Refusal(f"{w}.scope.modes: '*' and '<start>' are only for mode_transitions' allowed pairs")
        if b["kind"] == "containment" and ((p["source"] == "yaml") != ("polygon" in p) or
                                           ("alt_max_rel_home_m" in p and p["source"] == "log")):
            raise Refusal(f"{w}: source yaml needs a polygon (and may set alt_max_rel_home_m, judged on RelHomeAlt); "
                          "source log takes both from FENCE_RADIUS / FENCE_ALT_MAX, also relative to home")
        xy = [_enu(p["polygon"][0])(*v) for v in p.get("polygon", ())]
        e = list(zip(xy, xy[1:] + xy[:1]))
        if any(_crosses(*e[i], *e[k]) for i in range(len(e)) for k in range(i + 2, len(e) - (i == 0))):
            raise Refusal(f"{w}: the polygon intersects itself, so its inside is undefined")
        x = b["provenance"].get("param")
        if _follows(b) and x is not None and x != p["limit"]["param"]:
            raise Refusal(f"{w}: provenance.param {x!r} differs from the limit's parameter {p['limit']['param']!r}")
        if any(to == "<start>" for _, to in p.get("allowed", ())):
            raise Refusal(f"{w}: <start> is only ever a `from`")
    if not any(b["severity"] == "must" for b in bars):
        raise Refusal("bars file: zero `must` bars")
    assume = doc.get("assume", [])
    if len(set(assume)) < len(assume):
        raise Refusal(f"bars file.assume: duplicate name in {assume}")
    for name in assume:                          # each declared name must be used by some bar, for its own reason
        used, why = USES[name]
        if not any(used(b) for b in bars):
            raise Refusal(f"bars file.assume: {[name]} is an assumption no bar uses ({why})")
    return [{**b, "assume": tuple(assume)} for b in bars]       # the file's assumptions travel with each bar, unprinted


USES = {ASSUME: (lambda b: b["scope"]["armed"], "no bar has scope.armed: true"),
        LIMIT_ASSUME: (_follows, "no bar's limit follows a parameter")}


def load_bars(path):
    """-> (bars, sha256 of the file's RAW bytes, which is what prereg registers, §4)."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise Refusal(f"cannot read bars: {e}") from None
    return validate(load_yaml(raw, "bars")), hashlib.sha256(raw).hexdigest()


def check_modes(bars, log):
    """§3.1: every mode name must be in the resolved vehicle's table, spelt as pymavlink spells it ('*' and
    '<start>' only inside allowed pairs). With the vehicle unresolved nothing can be checked, and every bar that
    names a mode reads EI."""
    table = log.meta.get("mode_table")
    if not table:
        return
    names = set(table.values())
    for b in bars:
        pairs = [m for pair in b["params"].get("allowed", ()) for m in pair if m not in ("*", "<start>")]
        bad = [m for m in list(b["scope"]["modes"] or []) + pairs if m not in names]
        if bad:
            raise Refusal(f"bar {b['id']}: mode {bad[0]!r} is not in the {log.meta['vehicle']} mode table "
                          f"{sorted(names)}")


def evaluate(bars, log):
    holes = log_holes(log)
    return [_judge(b, KIND[b["kind"]], log, holes) for b in bars]


def _losses(log, holes):
    """Where a MODE or ARM row may be missing (G257, G314): each DSF.Dp rise and each log hole, as (a, b, what)."""
    return ([(a, b, f"{k} firmware-dropped writes in [{a:.3f}, {b:.3f}] s (DSF.Dp)")
             for a, b, k in log.integrity["drop_intervals"]] + [(a, b, f"a log hole [{a:.3f}, {b:.3f}] s") for a, b in holes])


def _judge(bar, kind, log, holes):
    """G257 R2 / A4: where the mode (contract.unsure) or arming (_arming) is unsure, a scoped bar is judged on the SURE
    scope (without it) and the WIDE scope (with it). The true scope lies between them and every kind is monotone in its
    scope, so: FAIL iff the sure pass FAILs, PASS iff both PASS, else EI; B7 is judged on the sure scope and blind where
    they differ. What prints is the sure pass's, except that a PASS quotes the wide pass's worst (G318)."""
    lost = _losses(log, holes)
    u, arm = unsure(log, lost), _arming(bar, log, lost)
    j = kind(bar, log, holes, ("sure", u, arm))
    if j["absent"] or (bar["scope"]["modes"] is None and not bar["scope"]["armed"]):
        return _decide(bar, j, log, holes)
    w = kind(bar, log, holes, ("wide", u, arm))
    if w["windows"] == j["windows"] and not w["absent"]:
        return _decide(bar, j, log, holes)
    near = [(x, s) for x, s in zip(lost, u) if intersect([s], j["reach"])] if bar["kind"] != "mode_transitions" and \
        bar["scope"]["modes"] is not None else []
    spans = lambda w_: ", ".join(f"[{a:.3f}, {b:.3f})" for a, b in merge(w_))
    parts = ([f"mode not known over {spans(s for _, s in near)} s ({'; '.join(x[2] for x, _ in near)} may hide a MODE row)"]
             if near else []) + ([f"arming not known over {spans(arm['u'])} s ({'; '.join(arm['why'])})"] if arm and arm["u"] else [])
    if bar["kind"] == "mode_transitions":                       # A4: B7 on the sure scope, blind where it differs
        j["blind"].append("; ".join(parts))
        return _decide(bar, j, log, holes)
    (sv, why, gaps) = _order(bar, j, holes)
    wv, wwhy, _ = _order(bar, w, holes)
    v = sv if sv == FAIL or sv == wv == PASS else EI
    at = f" at t={w['at'][0]:.3f} s" if w["at"] else ""
    found = (f"passes too: sure worst {j['measured']:.6g} on n={j['n']}; wide worst {w['measured']:.6g} on n={w['n']}"
             if v == PASS else f"passes too: n={w['n']}" if wv == PASS else
             f"has a violation{at}, which may or may not be in scope" if wv == FAIL else f"reads {wv}: {wwhy}")
    j["info"].append(f"{'; '.join(parts)}: judged without it; the wide scope (with it) {found}")
    if v == PASS:                                   # G318/G329: the wide pass's bound leads, as `measured` quotes it
        j["measured"], j["worst"], j["lim"], why = w["measured"], w["worst"], w["lim"], \
            f"wide scope (quoted): {w['note']}; sure scope: {why}"
    return _decide(bar, j, log, holes, (v, why if v == sv else f"the sure scope reads {sv}", gaps))


# ---- §3.2: the fixed order. The first rule that matches wins. --------------------------------------------
def _order(bar, j, holes):
    j["gaps"] += [("log", None, a, b) for a, b in holes                    # G229/G231/G251; B7 is blind instead (G320)
                  if hits((a, b), j["windows"]) and bar["kind"] != "mode_transitions"]
    gaps = [{"stream": s, "instance": i, "t0": r6(a), "t1": r6(b)} for s, i, a, b in j["gaps"]]
    unseen = [f"hole [{a:.3f}, {b:.3f}] s" for a, b in holes if hits((a, b), j["base"])] + j["blind"]
    ei = [x for x in (j["nan"] and f"{j['nan']} non-finite (NaN/inf) sample(s) in scope (rule 6)",
                      gaps and f"{len(gaps)} gap(s) or hole(s) in scope (rule 5)",
                      j["n"] < bar["min_n"] and f"n {j['n']} < min_n {bar['min_n']}") if x] + j["blind"]
    if j["absent"]:
        v, why = EI, j["absent"]                                                        # rule 1
    elif not j["windows"] and unseen:                       # G233: an absence across a hole is not measured
        v, why = EI, "no window of the scope, and the absence is not measured: " + "; ".join(unseen[:5])
    elif not j["windows"]:
        v, why = NA, ("the scope stream is PRESENT and no window of the scope exists (measured"      # rule 2, A5
                      + (", given the assumption)" if j["given"] else ")"))
    elif j["violated"]:
        v, why = FAIL, j["note"]                                    # rule 3: a measured red, whatever n is
    elif ei:
        v, why = EI, "; ".join(ei)                                                      # rule 4
    else:
        v, why = PASS, j["note"]                                                        # rule 5
    return v, why, gaps


def _decide(bar, j, log, holes, decided=None):
    v, why, gaps = decided or _order(bar, j, holes)
    scoped = bar["scope"]["modes"] or bar["scope"]["armed"] or bar["kind"] == "mode_transitions" or _follows(bar)
    for a, b, k in log.integrity["drop_intervals"]:    # G257: B8 excludes it, R1-R3 judge it, the rest say so
        mine = [a, b, k] in j["removed"]                # D5 / G371: a drop the limit key removed; G372: none on an ABSENT bar
        if not j["absent"] and hits((a, b), j["base"]) and (bar["kind"] == "no_events" or not scoped or mine):
            j["info"].append(f"{k} firmware-dropped writes in [{a:.3f}, {b:.3f}] s (DSF.Dp), not located; "
                             f"{'excluded from n' if bar['kind'] == 'no_events' else 'judged across'} (design §3.3)"
                             + (f" for the limit (assume: {LIMIT_ASSUME})" if mine else ""))
    if log.integrity["dsf_dropped_max"] is None and scoped and not j["absent"]:          # G321
        j["info"].append("DSF ABSENT: dropped writes are not counted; judged as if the firmware dropped none (log holes "
                         "still count)")
    near = [(a, b) for a, b, _ in log.integrity["holes"] if j["at"] and a - j["at"][1] <= j["at"][0] <= b + j["at"][1]]
    if v == FAIL and near:                                            # G265: no checksum, so it may be garbage
        j["info"].append(f"the deciding sample at t={j['at'][0]:.3f} s sits beside a byte hole at "
                         f"[{near[0][0]:.3f}, {near[0][1]:.3f}] s: value unverifiable")
    if v == FAIL:                                     # G373: a FAIL still says which samples the limit did not judge
        j["info"] += [x for x in j["blind"] if x.startswith(f"limit {bar['params']['limit']['param']} not usable")] \
            if _follows(bar) else []
    shown, lim = v in (PASS, FAIL), bar["params"].get("limit")       # EI/NA never print a number a reader could quote (§3.2)
    name, lead, out = bar["provenance"].get("param"), [], {}
    if _follows(bar):
        rows = _parm_rows(log, lim["param"])
        out = {"limit_in_log": {"rows": [[r6(t), x] for t, x in rows[:8]], "n_rows": len(rows),
                                "at_worst": j["lim"][0] if shown else None}}
        lead = [f"limit {j['lim'][0]:.6g} = {lim.get('scale', 1):g} x {lim['param']} {j['lim'][1]:.6g} (PARM row at "
                f"t={j['lim'][2]:.3f} s)"] if shown else []
    return {"id": bar["id"], "kind": bar["kind"], "severity": bar["severity"], "verdict": v,
            "measured": j["measured"] if shown else None, "bar": bar["params"], "n": j["n"], "min_n": bar["min_n"],
            "scope": bar["scope"], "instances_used": sorted(j["used"]), "worst_instance": j["worst"] if shown else None,
            "gaps": gaps, "note": "; ".join(lead + [f"n={j['n']}", why] + j["info"]), "provenance": bar["provenance"],
            "param_in_log": name and {"name": name, "values": sorted({x for _, x in log.params.get(name, ())}) or None},
            **out}


def _start(bar, log, side):
    j = {"windows": [], "base": [], "absent": None, "blind": [], "info": [], "n": 0, "violated": False,
         "measured": None, "worst": None, "nan": 0, "gaps": [], "used": set(), "note": None, "at": None, "given": False,
         "lim": None, "removed": []}
    scope, wins = bar["scope"], [(log.t0, log.t1)]
    j["base"] = j["reach"] = wins
    if scope["armed"]:
        s = log.streams["arming"]
        if s.state != PRESENT:
            return {**j, "absent": f"the scope needs arming, which is {s.state}: {s.reason}"}
        arm, first = side[2], side[2]["first"]      # A4: "could the scope be here" asks the WIDE arming set
        j["base"], j["reach"], j["given"] = arm["wide"], merge(arm["wide"] + [(log.t0, first)]), arm["assume"]
        if arm["assume"]:                                                                                # A5
            j["info"].append(f"arming before t={first:.3f} s assumed {'disarmed' if arm['s1'] else 'armed'} (assume: {ASSUME})")
    if scope["modes"] is not None:
        why = _mode_absent(log)
        if why:
            return {**j, "absent": why}
        _mode_prefix(log, j)
        seen = [(a, b) for a, b, m in mode_windows(log) if m in scope["modes"]]
        if bar["kind"] != "mode_transitions":      # G257 R2 / G311: _judge's sure scope, and its wide one to the log's ends
            seen = subtract(seen, intersect(side[1], j["base"])) if side[0] == "sure" else seen + side[1]
        wins = merge(intersect(wins, seen))
    if scope["armed"]:
        if not arm["assume"] and intersect(wins, [(log.t0, first)]):
            return {**j, "absent": f"arming is ABSENT before the first ARM row at t={first:.3f} s (rule 4) "
                                   "and the scope reaches there"}
        wins = merge(intersect(wins, arm[side[0]]))
    j["windows"] = wins
    return j


def _arming(bar, log, lost):
    """A3/A4: an `armed: true` scope's armed set, sure (A minus U_arm) and wide (A plus U_arm); None unless arming is
    PRESENT. Each ARM row pins the state just BEFORE it (every transition starts from the opposite state), so U_arm is:
    between two consecutive rows of the same state (a row is provably missing); from a loss ending at or after the first
    row to the next row; and, under the assumption, the stretch BEFORE a loss starting at or before the first row (G339)."""
    if not bar["scope"]["armed"] or log.streams["arming"].state != PRESENT:
        return None
    d, (A, first), assume = log.streams["arming"].data[0], armed_windows(log), ASSUME in bar["assume"]
    ts, st, pre = d["t_s"], d["armed"], [(a, b, x) for a, b, x in lost if a <= first]
    u = [(p, q, f"ARM rows at t={p:.3f} and {q:.3f} s are both {'arms' if a else 'disarms'}: a row is missing between them")
         for p, q, a, b in zip(ts, ts[1:], st, st[1:]) if a == b]
    u += [(a, (ts[bisect.bisect_right(ts, b):] or [log.t1])[0], x) for a, b, x in lost if b >= first]
    u += [(log.t0, r6(max(b for _, b, _ in pre) + TICK_S), "; ".join(x for *_, x in pre))] if assume and pre else []
    span = merge(intersect([(a, b) for a, b, _ in u], [(log.t0, log.t1)]))
    A = merge(A + [(log.t0, first)] * (assume and not st[0]))
    return {"sure": subtract(A, span), "wide": merge(A + span), "first": first, "assume": assume, "s1": st[0],
            "u": span, "why": [x for *_, x in u]}


def assumptions(bars, log):
    """A6: one object per declared assumption, saying what it did on THIS log (LOG_DISARMED is context, never read)."""
    s, out, lost = log.streams["arming"], [], _losses(log, log_holes(log))
    for name in bars[0]["assume"]:
        if name == LIMIT_ASSUME:              # per followed NAME: its first row, and the losses the key removed
            names = list(dict.fromkeys(b["params"]["limit"]["param"] for b in bars if _follows(b)))
            det = [_param_detail(next(b for b in bars if _follows(b)), log, n) for n in names]
            out.append({"name": name, "text": ASSUMPTIONS[name], "applied": any(ok for _, ok in det),
                        "detail": " | ".join(d for d, _ in det)})
            continue
        if s.state != PRESENT:
            detail = f"{s.reason}: not applied, arming stays ABSENT"
        else:
            first, pre = s.data[0]["t_s"][0], [x for x in lost if x[0] <= s.data[0]["t_s"][0]]
            detail = (f"first ARM row at t={first:.3f} s is {'an arm: disarmed' if s.data[0]['armed'][0] else 'a disarm: armed'}"
                      f" before it" + (f"; {'; '.join(x[2] for x in pre)}: [t0, {max(x[1] for x in pre):.3f}] judged both ways"
                                       if pre else ""))
        out.append({"name": name, "text": ASSUMPTIONS[name], "applied": s.state == PRESENT, "detail": detail,
                    "log_disarmed": sorted({x for _, x in log.params.get("LOG_DISARMED", ())}) or None})
    return out


def _mode_prefix(log, j):
    """G234/G258: the stretch before the first MODE row has no known mode; longer than MODE_PREFIX_S it is EI."""
    pre = r6(log.streams["mode"].data[0]["t_s"][0] - log.t0)          # G374: a span, on the grid
    text = f"mode unknown for {pre:.3f} s before the first MODE row"
    if pre > MODE_PREFIX_S:
        j["blind"].append(f"{text} (rule 4)")
    else:
        j["info"].append(f"{text} (<= {MODE_PREFIX_S} s: left out of the scope)")


def _witness(log, j):
    """B7/B8 see the logger's silences only through the raw series streams (contract.log_holes)."""
    if not witnessed(log):
        j["blind"].append("no unfiltered series stream (POS/GPS/BAT) to witness logger liveness")


def _mode_absent(log):
    s = log.streams["mode"]
    if s.state != PRESENT:
        return f"mode {s.state}: {s.reason}"
    if not log.meta.get("mode_table"):
        return f"vehicle ABSENT ({log.meta['absent'].get('vehicle')}): mode names cannot be resolved"
    return None


def _absent(s, name, cols):
    if s.state != PRESENT:
        return f"{name} {s.state}: {s.reason}"
    return next((f"{name}.{c} ABSENT: {s.absent_cols[c]}" for c in cols if c in s.absent_cols), None)


def _unmeasured(v):
    return isinstance(v, float) and not math.isfinite(v)      # NaN and +/-inf are not values (rule 6, G237)


def _scan(j, name, s, cols):
    """Every sample in scope as (instance, window, t, values), values None for a non-finite sample. Rule 5's gaps
    and rule 6's NaN/inf are counted into `j` HERE, so no kind can forget either. A value None inside `values` is
    an excluded sample the adapter says measured nothing (G240)."""
    if s.note:
        j["info"].append(f"{name}: {s.note}")          # what the adapter excluded (G230, G240, G256)
    for inst, d in s.data.items():
        j["gaps"] += [(name, inst, a, b) for a, b in fired_gaps(d["t_s"], j["windows"])]
        for w in j["windows"]:
            for i in in_windows(d["t_s"], [w]):
                vals = [d[c][i] for c in cols]
                j["nan"] += any(map(_unmeasured, vals))
                j["used"].add(inst)
                yield inst, w, d["t_s"][i], None if any(map(_unmeasured, vals)) else vals


WHY = {"pre": "before the first PARM row", "unsure": "where a loss meets [previous PARM row, sample] and may hide a row",
       "nonfinite": "where a candidate PARM row is non-finite", "outside": "where the parameter is outside accept",
       "tie": "where PARM rows at one timestamp split the verdict"}


def _parm_rows(log, name):
    """Every PARM row of `name` by time, (t, v), v None for a non-finite value: a row of UNKNOWN value (v2.1 D1)."""
    nan = [(t, None) for t, n in log.meta.get("params_nonfinite", ()) if n == name]
    return sorted(log.params.get(name, []) + nan, key=lambda r: r[0])


def _removed(bar, log, t1):
    """The drop intervals LIMIT_ASSUME removes for a parameter whose first row is at t1 (v2.1 D2): none unless declared and
    t1 - t0 <= PARM_DUMP_S (the startup dump); then each DSF interval with a <= t1 or a == t0 (the first starts at file
    open). Log holes are never removed. None = the key does not apply."""
    if LIMIT_ASSUME not in bar["assume"] or r6(t1 - log.t0) > PARM_DUMP_S:     # r6: a difference leaves the 1 us grid
        return None
    return [x for x in log.integrity["drop_intervals"] if x[0] <= t1 or x[0] == log.t0]


def _limit_at(bar, log, holes):
    """-> (t -> (cause or None, C), the drop intervals the key removed), C = [(S*v, v, PARM row time, v in accept)], v None
    for a non-finite row (§3, 0.3.0); or the reason the bar is EI. The log's PARM rows are its LOGGED configuration only:
    a plain set() writes none, and a row can be dropped (counted in DSF.Dp) or refused uncounted (ArduPilot @
    Copter-4.5.5, F1-F3). The losses here are PRIVATE to the limit (D3): no mode or arming judgement sees them. Every time
    is on the adapter's 1 us grid (adapters.ardupilot._t), so a loss bound and a row on one tick are equal."""
    lim = bar["params"]["limit"]
    if not _follows(bar):
        return (lambda t: (None, [(lim, lim, None, True)])), []
    name, S, (lo, hi) = lim["param"], lim.get("scale", 1), lim["accept"]
    rows, by = _parm_rows(log, name), {}
    if not rows:
        return f"limit parameter {name} has no PARM row in this log", []
    for t, v in rows:                               # ALL values at a time: file order is not time order
        by.setdefault(t, []).append((None, None, t, None) if v is None else (S * v, v, t, lo <= v <= hi))
    T = list(by)                                    # _parm_rows sorted them by time
    removed = _removed(bar, log, T[0])
    lost = [(a, b) for a, b, k in log.integrity["drop_intervals"] if [a, b, k] not in (removed or [])] + holes

    def at(t):
        if t <= T[0]:
            return "pre" if removed is None else "unsure" if any(a <= T[0] for a, _ in lost) else None, by[T[0]]
        p = T[bisect.bisect_left(T, t) - 1]
        return "unsure" if any(a <= t and b >= p for a, b in lost) else None, by[p] + by.get(t, [])
    return at, removed or []


def _param_detail(bar, log, name):
    """The limit assumption's detail for one followed parameter (D2): its first row, and what the key removed."""
    rows = _parm_rows(log, name)
    if not rows:
        return f"{name}: no PARM row", False
    t1 = rows[0][0]
    gone = _removed(bar, log, t1)
    why = ("first row more than 5 s after the log's start: not applied" if gone is None else
           "removed " + "; ".join(f"{k} firmware-dropped writes in [{a:.3f}, {b:.3f}] s (DSF.Dp)" for a, b, k in gone)
           if gone else "no drop interval removed")
    return f"{name}: first PARM row at t={t1:.3f} s; {why}", gone is not None


# ---- the five kinds ------------------------------------------------------------------------------------
def _series_bound(bar, log, holes, side):
    """Every sample of every instance in scope (§3.2): every-sample IS the worst window. A limit that follows a PARM
    row (0.3.0) is judged per sample: unjudged (pre-first-row, unsure, outside accept, a split tie: one blind reason),
    else a VIOLATION iff it breaks S*v for EVERY value v it may have had, CLEAN iff for none."""
    j, p = _start(bar, log, side), bar["params"]
    name, col = p["channel"].split(".")
    s = log.streams[name]
    lim, j["removed"] = _limit_at(bar, log, holes)
    j["absent"] = j["absent"] or _absent(s, name, [col]) or (lim if isinstance(lim, str) else None)
    if j["absent"]:
        return j
    floor, worst, seen, excluded, blind = p["bound"] == "floor", None, set(), 0, {}
    for inst, _, t, vals in _scan(j, name, s, [col]):
        if vals is not None and vals[0] is None:
            excluded += 1
        elif vals is not None:
            x, (cause, C) = vals[0], lim(t)
            cause = cause or ("nonfinite" if any(c[3] is None for c in C) else None)
            m = [] if cause else [((x - c[0]) if floor else (c[0] - x), x if floor else -x, x, c) for c in C]   # < 0: breaks
            cause = cause or ("outside" if not all(c[3] for c in C) else "tie" if len({q[0] < 0 for q in m}) > 1 else None)
            if cause:
                c = blind.setdefault(cause, [0, t, t, 0])
                c[:] = c[0] + 1, min(c[1], t), max(c[2], t), c[3] + (bool(m) and all(q[0] < 0 for q in m))
                continue
            j["n"] += 1
            seen.add(x)
            k = min(m, key=lambda q: q[:2])         # smallest margin; on an exact tie the more extreme x, then scan order
            if worst is None or k[:2] < worst[0][:2]:
                worst = (k, inst, t)
    if excluded:
        j["info"].append(f"{excluded} sample(s) excluded, not values")
    if blind:
        j["blind"].append(f"limit {p['limit']['param']} not usable on {sum(c[0] for c in blind.values())} sample(s): "
                          + "; ".join(f"{c[0]} {WHY[k]}" + (f" ({c[3]} of them break {p['limit'].get('scale', 1):g} x every "
                                      "logged value they may have had)" if k == "outside" else "") +
                                      f", t in [{c[1]:.3f}, {c[2]:.3f}] s" for k, c in blind.items()))
    if worst:
        (margin, _, x, c), inst, t = worst
        j["measured"], j["worst"], j["at"] = x, inst, (t, median_period(s.data[inst]["t_s"]))
        j["violated"], j["lim"] = margin < 0, c[:3] if _follows(bar) else None
        j["note"] = (f"worst {x:.6g} on instance {inst} at t={t:.3f} s, "
                     f"{len(j['windows'])} window(s); instances present {sorted(s.data)}"
                     + (f"; all {j['n']} judged samples equal {x:.6g}" if len(seen) == 1 else ""))
    return j


def _run_end(prev, nxt, thr, holes):
    """Where a non-qualifying run whose last row is at `prev` ends, when the next evidence is at `nxt`: there, unless
    a fired gap (which starts at prev) or a hole lies between them. Missing rows are the gap rule's EI, never an
    outage (design B5)."""
    if r6(nxt - prev) > thr:
        return prev
    return min([nxt] + [a for a, b in holes if prev <= a < nxt])     # a hole AFTER the run's last row (G255)


def _gnss_quality(bar, log, holes, side):
    """FAIL if a run of non-qualifying rows on any instance spans more than max_outage_s (0: any such row). A run
    ends at the next qualifying row, at the window's end, or at the start of a gap or hole."""
    j, p, s = _start(bar, log, side), bar["params"], log.streams["gnss"]
    j["absent"] = j["absent"] or _absent(s, "gnss", ["fix_type", "nsats"])
    if j["absent"]:
        return j
    thr = {inst: gap_threshold(d["t_s"]) for inst, d in s.data.items()}
    runs, start, key, prev = [], None, None, None      # runs: (span_s, instance, t_start)
    for inst, w, t, vals in [*_scan(j, "gnss", s, ["fix_type", "nsats"]), (None, None, None, None)]:
        if (inst, w) != key:
            if start is not None:                          # a run open at a window's end
                runs.append((r6(_run_end(prev, key[1][1], thr[key[0]], holes) - start), key[0], start))
            key, start, prev = (inst, w), None, None
        if vals is None:
            continue
        if start is not None and _run_end(prev, t, thr[inst], holes) < t:
            runs.append((r6(_run_end(prev, t, thr[inst], holes) - start), inst, start))
            start = None
        j["n"] += 1
        if vals[0] >= p["fix_min"] and vals[1] >= p["sats_min"]:
            runs += [(r6(t - start), inst, start)] if start is not None else []      # G374: spans on the grid
            start = None
        elif start is None:
            start = t
        prev = t
    worst = max(runs, default=(0.0, None, None))
    j["measured"], j["worst"] = worst[0], worst[1]
    j["at"] = (worst[2], median_period(s.data[worst[1]]["t_s"])) if runs else None
    j["violated"] = any(span > p["max_outage_s"] or p["max_outage_s"] == 0 for span, _, _ in runs)
    j["note"] = (f"{len(runs)} non-qualifying run(s); longest {worst[0]:.3f} s on instance {worst[1]} "
                 f"from t={worst[2]:.3f} s" if runs else "every row in scope qualifies")
    return j


def _containment(bar, log, holes, side):
    """B6. Local metres: equirectangular ENU about the reference point (home for the log's cylinder, the
    first vertex for a YAML polygon), delta-lon wrapped at the antimeridian. The cylinder and the altitude cap
    (above home, on RelHomeAlt) are exact on samples (both peak at a chord's endpoint); the polygon and the
    exclusion circles are judged on every segment between consecutive samples, never across a fired gap or a
    NaN. A segment touching the polygon boundary without crossing it is inside (margin 0); one that crosses
    FAILs, and its depth outside is not computed."""
    j, p, s = _start(bar, log, side), bar["params"], log.streams["position"]
    if p["source"] == "log":
        f, h = log.fence, log.home
        why = (f["state"] != PRESENT and f"fence ABSENT: {f['reason']}") or (h["state"] != PRESENT and f"home ABSENT: {h['reason']}")
        ref, radius, alt_max = (h.get("lat"), h.get("lon")), f.get("circle_radius_m"), f.get("alt_max_rel_home_m")
    else:
        why, ref, radius, alt_max = None, tuple(p["polygon"][0]), None, p.get("alt_max_rel_home_m")
    cols = ["lat", "lon"] + (["alt_rel_home_m"] if alt_max is not None else [])
    j["absent"] = j["absent"] or why or _absent(s, "position", cols)
    if j["absent"]:
        return j
    enu = _enu(ref)
    poly = [enu(*v) for v in p["polygon"]] if p["source"] == "yaml" else None
    edges = list(zip(poly, poly[1:] + poly[:1])) if poly else []
    excl = [(enu(e["lat"], e["lon"]), e["radius_m"]) for e in p.get("exclusions", [])]
    worst, thr, prev, crossed = (math.inf, None, ""), gap_threshold(s.data[0]["t_s"]), None, None

    def margin(m, t, what):
        nonlocal worst
        worst = min(worst, (m, t, what))
        j["violated"] |= m < 0

    for _, w, t, vals in _scan(j, "position", s, cols):
        if vals is None:                                   # never bridge a NaN sample either
            prev = None
            continue
        q = enu(vals[0], vals[1])
        if radius is not None:
            margin(radius - math.hypot(*q), t, "cylinder")
        if alt_max is not None and vals[2] is not None:
            margin(alt_max - vals[2], t, "altitude above home")
        if poly:
            margin((1 if _inside(q, edges) else -1) * min(_pseg(q, *e) for e in edges), t, "polygon")
        for c, r in excl:
            margin(math.dist(q, c) - r, t, "exclusion")
        if prev is not None and prev[2] == w and r6(t - prev[1]) <= thr:   # a longer step is a fired gap: not judged
            j["n"] += 1
            for c, r in excl:
                margin(_pseg(c, prev[0], q) - r, t, "exclusion segment")
            if poly and any(_crosses(prev[0], q, *e) for e in edges):
                j["violated"], crossed = True, crossed or t
            elif poly:
                margin(min(_sseg(prev[0], q, *e) for e in edges), t, "polygon segment")
        prev = (q, t, w)
    if worst[1] is not None:
        j["measured"], j["worst"] = (min(worst[0], 0.0) if crossed else worst[0]), 0
        j["at"] = (crossed or worst[1], median_period(s.data[0]["t_s"]))
        j["note"] = (f"crossed the polygon boundary between samples at t={crossed:.3f} s (depth outside not computed); "
                     if crossed else "") + f"minimum signed margin of the samples and judged segments {worst[0]:.3f} m " \
                     f"({worst[2]}) at t={worst[1]:.3f} s" + (f"; {log.fence['note']}" if p["source"] == "log" and
                                                              log.fence.get("note") else "")
    return j


def _mode_transitions(bar, log, holes, side):
    """B7. n counts real transitions (row 2 onward); the startup row is checked as `<start> -> first` and reported
    apart. Across a log hole or a DSF.Dp drop interval the `from` is unknown (a MODE row may be in it): the transition
    FAILs if no mode may enter its `to`, is judged if every mode may, else is not judged; either loss in the base range
    makes the bar EI when some hidden row could fail it (G312, G320); with no raw stream to witness the logger, EI."""
    j = _start(bar, log, side)
    j["absent"] = j["absent"] or _mode_absent(log)
    if j["absent"]:
        return j
    if bar["scope"]["modes"] is None:                 # a mode scope already added it in _start
        _mode_prefix(log, j)
    _witness(log, j)
    d, allowed, bad, lost = log.streams["mode"].data[0], bar["params"]["allowed"], [], _losses(log, holes)
    ok = lambda a, b: any(f in ("*", a) and to in ("*", b) for f, to in allowed)
    table = sorted(set(log.meta["mode_table"].values())) + ["UNKNOWN(?)"]   # G330: a hidden UNKNOWN(n) matches only "*"
    if any(not ok(a, b) for a in table for b in table):     # G320: only then can a hidden row fail it (UNKNOWN covers <start>)
        j["blind"] += [f"{x}, not located: a MODE row may be among them" for a, b, x in lost if hits((a, b), j["base"])]
    rsn = d.get("rsn", [None] * len(d["t_s"]))
    names, ts, how = ["<start>"] + d["name"], [log.t0] + d["t_s"], "outside the scope"
    for k in range(1, len(names)):
        if not any(a <= ts[k] < b for a, b in j["windows"]):
            continue
        cut = next((x for a, b, x in lost if a <= ts[k] and b >= ts[k - 1]), None)    # G312/G313: closed-closed overlap
        fine = [ok(f, names[k]) for f in ([names[k - 1]] if cut is None else table + ["<start>"] * (k == 1))]
        some = any(fine) and not all(fine)                     # (iii): some lost `from` is allowed, some is not
        if k == 1:                                                                      # G322
            how = "judged" if cut is None else "not judged (from unknown)" if some else "judged on `to` alone (from unknown)"
        if some:                                    # G326: blind even when the cutting loss lies outside the base
            j["blind"].append(f"{cut}, not located: the mode entering {names[k]} at t={ts[k]:.3f} s may be lost")
            continue
        j["n"] += k > 1
        if not any(fine):
            bad.append(f"{'?' if cut else names[k - 1]} -> {names[k]}{f' (Rsn {rsn[k - 1]})' if rsn[k - 1] is not None else ''} "
                       f"at t={ts[k]:.3f} s" + (f" (from unknown: {cut})" if cut else ""))
    j["measured"], j["violated"] = len(bad), bool(bad)
    j["note"] = ("disallowed: " + "; ".join(bad) if bad else "every judged transition is allowed") + \
        f"; the startup row <start> -> {names[1]} is {how}, never counted in n"
    return j


def _no_events(bar, log, holes, side):
    """B8. n is DROP-FREE SECONDS of scope: the scope up to the last DSF row, minus every interval in which
    DSF.Dp rose and every log hole (§3.3); a log hole in scope also makes the bar EI (an event may be in it), and so
    does having no raw stream to witness the logger. An event anywhere in scope is a measured red."""
    j, p, s, g = _start(bar, log, side), bar["params"], log.streams["events"], log.integrity
    j["absent"] = (j["absent"] or (s.state == ABSENT and f"events ABSENT: {s.reason}")
                   or (g["dsf_dropped_max"] is None and f"dsf_dropped_max ABSENT: {g['reason']}"))
    if j["absent"]:
        return j
    _witness(log, j)
    ignore, hits_ = p.get("ignore", []), []
    if s.state == PRESENT:
        d = s.data[0]
        hits_ = [f"{d['text'][i]} at t={d['t_s'][i]:.3f} s" for i in in_windows(d["t_s"], j["windows"])
                 if d["kind"][i] in p["kinds"] and d["code"][i] not in ignore]
    lossy = [(a, b) for a, b, _ in g["drop_intervals"]]
    free = subtract(intersect(j["windows"], [(log.t0, g["drops_known_until_s"])]), lossy + holes)
    j["n"] = round(sum(b - a for a, b in free), 3)
    j["measured"], j["violated"] = len(hits_), bool(hits_)
    j["note"] = (f"{len(hits_)} event(s) {hits_[:5]}; drop-free {j['n']} s (excluded: Dp rose in {lossy}, log holes, "
                 f"and after the last DSF row at {g['drops_known_until_s']} s); events {s.state}: {s.reason}")
    return j


KIND = {"series_bound": _series_bound, "gnss_quality": _gnss_quality, "containment": _containment,
        "mode_transitions": _mode_transitions, "no_events": _no_events}


# ---- geometry: the ONE point-segment primitive of this package, and what is built on it --------------------
def _enu(ref):
    """Equirectangular local metres about ref = (lat, lon); delta-lon wrapped into [-180, 180) (G232)."""
    k = M_PER_DEG * math.cos(math.radians(ref[0]))
    return lambda lat, lon: (((lon - ref[1] + 180) % 360 - 180) * k, (lat - ref[0]) * M_PER_DEG)


def _pseg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - u * dx, p[1] - a[1] - u * dy)


def _orient(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _crosses(a, b, c, d):
    """Proper crossing of segments ab and cd (touching is not crossing)."""
    return _orient(c, d, a) * _orient(c, d, b) < 0 and _orient(a, b, c) * _orient(a, b, d) < 0


def _sseg(a, b, c, d):
    return 0.0 if _crosses(a, b, c, d) else min(_pseg(a, c, d), _pseg(b, c, d), _pseg(c, a, b), _pseg(d, a, b))


def _inside(q, edges):
    inside = False
    for (x1, y1), (x2, y2) in edges:
        if (y1 > q[1]) != (y2 > q[1]) and q[0] < x1 + (q[1] - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
