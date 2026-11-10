"""The flight-log contract `swathkeeper-flightlog/1.0` (design §2): what an adapter fills, and the time
rules every bar reads through. Stdlib only.

Times are source boot seconds. Windows are half-open [a, b); `FlightLog.t1` is one clock tick (1 us)
past the last record, so [t0, t1) holds every row.
"""
import bisect
import statistics
from dataclasses import dataclass, field

PRESENT, EMPTY, ABSENT = "PRESENT", "EMPTY", "ABSENT"
TICK_S = 1e-6
# The series streams and their columns: the ONE list a bar's `channel` is validated against (§3.1).
SERIES = {
    "position": ("lat", "lon", "alt_amsl_m", "alt_rel_home_m"),
    "velocity": ("groundspeed_mps",),
    "gnss": ("fix_type", "nsats", "hdop", "gps_week", "gps_ms"),
    "battery": ("voltage_v", "current_a"),
    "ekf": ("vel_ratio", "pos_ratio", "hgt_ratio", "mag_ratio"),
}


class Refusal(Exception):
    """Exit 2 (§5): these inputs will not be judged. The message is the reason the JSON prints."""


@dataclass
class Stream:
    """One §2 record. `data` maps instance -> {"t_s": [...], <column>: [...]}. A column the source
    lacks is named in `absent_cols` and is never zero- or NaN-filled (rule 3)."""
    state: str
    source: str
    reason: str | None = None
    data: dict = field(default_factory=dict)
    absent_cols: dict = field(default_factory=dict)
    note: str | None = None

    @property
    def n(self):
        return sum(len(d["t_s"]) for d in self.data.values())


@dataclass
class FlightLog:
    meta: dict        # vehicle/firmware/hardware (None, with meta["absent"][key] the reason), mode_table
    integrity: dict   # bytes skipped (interior/trailing), byte holes, dsf_dropped_max, drop_intervals (rule 5)
    streams: dict     # SERIES names + "mode", "arming", "events" -> Stream
    home: dict        # {state, lat, lon, alt_amsl_m | reason}
    params: dict      # name -> [(t_s, value)]
    fence: dict       # {state, circle_radius_m, alt_max_rel_home_m, polygon_bit | reason}
    t0: float
    t1: float


def series(name, source, rows, cols, absent_cols=None):
    """A PRESENT stream from (instance, t_s, values) rows in file order. A clock that steps backwards
    inside one stream instance is a refusal naming it (rule 1); nothing is ever re-sorted."""
    data = {}
    for inst, t, vals in rows:
        d = data.setdefault(inst, {"t_s": [], **{c: [] for c in cols}})
        if d["t_s"] and t < d["t_s"][-1]:
            raise Refusal(f"non-monotone clock in {name} instance {inst}: row {len(d['t_s'])} has "
                          f"t={t:.6f} s after t={d['t_s'][-1]:.6f} s (contract rule 1)")
        d["t_s"].append(t)
        for c, v in zip(cols, vals):
            d[c].append(v)
    return Stream(PRESENT, source, data=data, absent_cols=absent_cols or {})


def median_period(ts):
    return statistics.median(b - a for a, b in zip(ts, ts[1:])) if len(ts) > 1 else 0.0


def gap_threshold(ts):
    """Rule 5: a gap is longer than max(1 s, 5p), p = this instance's own median sample period."""
    return max(1.0, 5.0 * median_period(ts))


def in_windows(ts, windows):
    """Indices of the samples inside the half-open windows."""
    for a, b in windows:
        yield from range(bisect.bisect_left(ts, a), bisect.bisect_left(ts, b))


def fired_gaps(ts, windows):
    """Rule 5 inside a bar's scope. The window edges count: a stream that starts late or stops early
    inside the scope has a hole there too (the clipped edge is never longer than the true gap)."""
    thr, out = gap_threshold(ts), []
    for a, b in windows:
        seq = [a, *ts[bisect.bisect_left(ts, a):bisect.bisect_left(ts, b)], b]
        out += [(x, y) for x, y in zip(seq, seq[1:]) if y - x > thr]
    return out


RAW = ("position", "gnss", "battery")      # the series that log every row; velocity and ekf drop rows (G230)


def log_holes(log):
    """Where the LOG is missing data, as merged closed [t_before, t_after] intervals: every interior byte skip the
    adapter located, whatever its length (G229), plus where EVERY present raw series instance (position, gnss,
    battery) has a fired interior gap at once (G260 as corrected). A hole in all of them is the logger -- the silent
    gates of the ERR citation stop every stream, so this intersection is what makes its premise hold -- while a
    hole in one stream is that sensor's event, judged per stream by rule 5."""
    out, common = [(a, b) for a, b, _ in log.integrity["holes"]], None
    for name in RAW:
        s = log.streams[name]
        for d in s.data.values() if s.state == PRESENT else ():
            ts, thr = d["t_s"], gap_threshold(d["t_s"])
            gaps = [(x, y) for x, y in zip(ts, ts[1:]) if y - x > thr]
            common = gaps if common is None else intersect(common, gaps)
    return merge(out + (common or []))


def witnessed(log):
    """Can logger liveness be seen at all? Only through a raw series stream."""
    return any(log.streams[name].state == PRESENT for name in RAW)


def merge(windows):
    """Touching or overlapping intervals as one (G228): [a, b) + [b, c) is [a, c), so a segment or an outage
    spanning two consecutive named modes, or a repeated MODE row, is judged whole."""
    out = []
    for a, b in sorted(windows):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def hits(hole, windows):
    """Does the closed hole [x, y] (records at x and y are present, data between them is not) reach a window?"""
    x, y = hole
    return any(x < b and (y > a if y > x else x >= a) for a, b in windows)


def intersect(A, B):
    return [(max(a, c), min(b, d)) for a, b in A for c, d in B if max(a, c) < min(b, d)]


def subtract(A, B):
    out = list(A)
    for c, d in B:
        out = [p for a, b in out for p in ((a, min(b, c)), (max(a, d), b)) if p[0] < p[1]]
    return out


def mode_windows(log):
    """§2: [t_mode_i, t_mode_{i+1}), the last ending at the log's end. (name may be None: vehicle ABSENT.)"""
    d = log.streams["mode"].data.get(0)
    if not d:
        return []
    ts = d["t_s"]
    return list(zip(ts, ts[1:] + [log.t1], d["name"]))


def unsure(log, lost):
    """G257/G314: a MODE row may be missing in each (a, b, ...) of `lost` (drop intervals and log holes), so the mode is
    unsure over [a, t_next), t_next the first MODE row after b, else the log's end. Outside these the rows are the mode."""
    ts = (log.streams["mode"].data.get(0) or {"t_s": []})["t_s"]
    return [(a, (ts[bisect.bisect_right(ts, b):] or [log.t1])[0]) for a, b, *_ in lost]


def armed_windows(log):
    """Known-armed intervals from the ARM rows, and the time before which arming is ABSENT (rule 4)."""
    d = log.streams["arming"].data[0]
    ts = d["t_s"]
    return [(a, b) for a, b, armed in zip(ts, ts[1:] + [log.t1], d["armed"]) if armed], ts[0]


def r6(x):
    return None if x is None else round(x, 6)


def streams_map(log):
    """The `streams` block of `inspect` and of every verdict (§7: one code path)."""
    out = {}
    for name, s in log.streams.items():
        insts = {}
        for inst, d in s.data.items():
            ts = d["t_s"]               # empty: an instance none of whose rows measured anything (G256)
            insts[str(inst)] = {"n": len(ts), "t_first": r6(ts[0] if ts else None), "t_last": r6(ts[-1] if ts else None),
                                "median_period_s": r6(median_period(ts)),
                                "max_gap_s": r6(max((b - a for a, b in zip(ts, ts[1:])), default=0.0))}
        out[name] = {"state": s.state, "source": s.source, "reason": s.reason, "note": s.note, "n": s.n,
                     "instances": insts, "absent_columns": s.absent_cols}
    if log.streams["mode"].state == PRESENT:
        out["mode"]["windows"] = [[r6(a), r6(b), m] for a, b, m in mode_windows(log)]
    if log.streams["arming"].state == PRESENT:
        armed, first = armed_windows(log)
        out["arming"]["armed_intervals"] = [[r6(a), r6(b)] for a, b in armed]
        out["arming"]["absent_before_s"] = r6(first)
    out["home"], out["fence"] = log.home, log.fence
    out["params"] = {"state": PRESENT if log.params else ABSENT, "n": len(log.params)}
    return out
