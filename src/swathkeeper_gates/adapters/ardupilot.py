"""ArduPilot DataFlash (.bin) -> swathkeeper-flightlog/1.0 through pymavlink's DFReader (pinned ==2.4.50:
the parser is the instrument, design §1). Each stream comes from the ONE message the §2 table names;
nothing is defaulted, inferred or re-sorted, and every byte is accounted for: DFReader keeps no skip
counter, so each skip is located from the offset jump between two decoded records and becomes a HOLE on
the record clock, however short (G229); bytes after the last record are `bytes_skipped_trailing`.

Units: DFReader applies the format-character multipliers (c/C/e/E x0.01, L x1e-7 deg) and never an FMTU
multiplier, so a value column stored as a bare integer would be in unknown units: it is ABSENT. Old logs
without an instance column read it as instance 0 (GPS without I, BAT without Inst); EKF2's NKF4 is core
0 and NKF9 core 1. GPS2, BAT2 and CURR are not contract messages and are not read. Vehicle and version
come from the firmware string in VER.FWS / MSG only, never DFReader's Plane default.

A channel keeps only rows that measured something (G230), cited at tag Copter-4.5.5:
* velocity: GPS rows with Status >= 3. AP_GPS::GPS_Status (libraries/AP_GPS/AP_GPS.h): 0 NO_GPS, 1 NO_FIX,
  2 GPS_OK_FIX_2D, 3 GPS_OK_FIX_3D, 4 _DGPS, 5 _RTK_FLOAT, 6 _RTK_FIXED. The gnss stream keeps every row.
* ekf: XKF4/NKF4/NKF9 rows with SS != 0. SS is "Filter solution status" (AP_NavEKF3 and AP_NavEKF2
  LogStructure.h), the nav_filter_status bitmask (libraries/AP_NavEKF/AP_Nav_Common.h): 0 = no bit set, not
  even "attitude estimate is valid".
* alt_rel_home_m: none before the first ORGN Type 1 row (home); with no home the column is ABSENT.

Firmware citations (design §11.1 items 1-2), read at tag Copter-4.5.5:
* events. AP_Logger::Write_Error (libraries/AP_Logger/AP_Logger.cpp) builds the ERR packet and calls
  WriteCriticalBlock -> AP_Logger_Backend::WritePrioritisedBlock(..., is_critical=true)
  (libraries/AP_Logger/AP_Logger_Backend.cpp) -> AP_Logger_File::_WritePrioritisedBlock
  (libraries/AP_Logger/AP_Logger_File.cpp). Critical blocks bypass the rate limiter and the
  reserved-space check; the only losses of an ERR while armed are counted in _dropped (startup messages
  unfinished; buffer space < size), which DSF.Dp reports (Write_AP_Logger_Stats_File, cumulative per log
  file, 1 Hz). The uncounted gates (writes disabled, backend uninitialised, no open file or a recent open
  error, disarmed with LOG_DISARMED=0) stop EVERY stream, so they appear as a gap in every raw series stream at
  once, which contract.log_holes' intersection turns into a hole B7/B8 must respect. So zero ERR rows is
  EMPTY only inside the citation's premise (G238): a release V4.5.<n> firmware string with no suffix, and
  LOG_BACKEND_TYPE logged, constant and == 1 (bit 0 File only; the cited path is AP_Logger_File's).
* arming. ARM rows come only from AP_Arming::Log_Write_Arm / Log_Write_Disarm, called by AP_Arming::arm() /
  disarm() on a successful transition (event-only; a failed arm writes nothing). Every transition starts from
  the opposite state: arm() returns early if already armed and disarm() if already disarmed, and rows are
  written only on success. With LOG_DISARMED=0 the base arm() sets armed and writes the row BEFORE
  AP_Arming_Copter::arm() calls AP::logger().set_vehicle_armed(true), so AP_Logger_Backend::ShouldLog can
  refuse the arm row while the disarm row is written. But logging persists 15 s after a disarm or a failed arm
  and 150 s after a failsafe-type disarm (AP_Arming::check_forced_logging -> set_long_log_persist); an arm row
  IS written inside a persistence window and after a file's first armed write (ShouldLog's critical
  `have_logged_armed && !LOG_FILE_DSRMROT` path), so only a file's FIRST arm outside a persistence window is
  refused; and a watchdog-armed reboot forces LOG_DISARMED=1 in RAM (AP_Logger::Init). So the initial state
  stays ABSENT (rule 4) unless a bars file declares `assume: [arming_before_first_arm_row]` (bars.ASSUMPTIONS).
"""
import contextlib
import math
import os
import re
import sys
from collections import Counter
from importlib import metadata

from ..contract import ABSENT, EMPTY, PRESENT, TICK_S, FlightLog, Refusal, Stream, series

WANT = ("POS", "GPS", "BAT", "XKF4", "NKF4", "NKF9", "MODE", "ARM", "ERR", "DSF", "PARM", "MSG", "VER", "ORGN")
CLOCK = {"POS", "GPS", "BAT", "XKF4", "NKF4", "NKF9", "MODE", "ARM", "ERR", "DSF"}   # t0/t1 and holes (G244)
FIRMWARE = re.compile(r"(ArduCopter|ArduPlane|ArduRover|ArduSub) V(\d+)\.(\d+)\.\d+(\S*)")
BOARD = re.compile(r"(\S+) [0-9A-F]{8} [0-9A-F]{8} [0-9A-F]{8}$")    # the "<board> <uid>" banner
VALUE_COLS = {"Lat", "Lng", "Alt", "RelHomeAlt", "Spd", "HDop", "Volt", "Curr", "SV", "SP", "SH", "SM"}
SCALED_FMT = set("fdgcCeEL")     # float, or an integer DFReader scales by its format character
EKF = {"vel_ratio": "SV", "pos_ratio": "SP", "hgt_ratio": "SH", "mag_ratio": "SM"}
NOT_READ = {"velocity": ("GPS2",), "gnss": ("GPS2",), "battery": ("BAT2", "CURR")}
ERR_NOTE = ("EMPTY per AP_Logger::Write_Error -> WriteCriticalBlock (cited at tag Copter-4.5.5). File backend "
            "only; silent gates are caught by the gap rule because they stop every stream")


@contextlib.contextmanager
def _mute():
    """DFReader prints a diagnostic per bad byte, its Cython indexer at the C level, so fds 1 and 2 (not just
    sys.stdout/err) point at devnull for the parse (G250). `integrity.holes` replaces what they said."""
    sys.stdout.flush(), sys.stderr.flush()
    saved, null = (os.dup(1), os.dup(2)), os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null, 1), os.dup2(null, 2)
        yield
    finally:
        sys.stdout.flush(), sys.stderr.flush()
        os.dup2(saved[0], 1), os.dup2(saved[1], 2)
        for f in (*saved, null):
            os.close(f)


def _t(m):
    """THE contract time of a record: TimeUS on the 1 us grid. The raw product is not (7_200_000 * 1e-6 is
    7.199999999999999, below the rounded loss bound 7.2 on ~30 % of ticks), which broke same-tick closed ties."""
    return round(m.TimeUS * 1e-6, 6)


def _decode(path):
    try:
        from pymavlink import DFReader
    except ImportError as e:
        raise Refusal(f"the ardupilot adapter needs pymavlink ({e}): "
                      f"pip install 'swathkeeper-gates[ardupilot]'") from None
    rows, counts, nbytes, lo, hi = {k: [] for k in WANT}, Counter(), 0, None, None
    end, pending, holes = 0, [], []        # pending: skips still waiting for the next clock row
    with _mute():
        try:
            r = DFReader.DFReader_binary(path)
            while (m := r.recv_msg()) is not None:
                name, start = m.fmt.name, r.offset - m.fmt.len
                if start != end:           # bytes between two decoded records were not decoded
                    pending.append((hi, start - end))
                end, nbytes = r.offset, nbytes + m.fmt.len
                counts[name] += 1
                if name in rows:
                    rows[name].append(m)
                if name in CLOCK and "TimeUS" in m.fmt.colhash:
                    t = _t(m)
                    holes += [sorted((t if tb is None else tb, t)) + [nb] for tb, nb in pending]   # streams interleave
                    pending, lo, hi = [], t if lo is None else min(lo, t), t if hi is None else max(hi, t)
            defined = {f.name for f in r.formats.values()}
            r.close()
        except Exception as e:
            raise Refusal(f"DataFlash decode failed after {sum(counts.values())} records: {e}") from None
    if lo is None:
        raise Refusal("DataFlash decode found no timestamped contract record")
    holes += [[tb, hi, nb] for tb, nb in pending]       # skips after the last clock row reach the end
    size = os.path.getsize(path)
    integ = {"bytes_skipped": size - nbytes, "bytes_skipped_interior": sum(nb for *_, nb in holes),
             "bytes_skipped_trailing": size - end, "holes": [[round(a, 6), round(b, 6), nb] for a, b, nb in holes]}
    return rows, counts, integ, lo, hi, defined


def _stream(name, rows, sources, inst_col, cols, src=None):
    """One contract stream from `sources` = [(message, instance if the message lacks `inst_col`)];
    an instance of None means the column is required."""
    src = src or f"{' + '.join(m for m, _ in sources)}{f' by {inst_col}' if inst_col else ''} ({', '.join(cols.values())})"
    used = [(msg, dflt) for msg, dflt in sources if rows[msg]]
    if not used:
        return Stream(ABSENT, src, reason=f"no {' / '.join(m for m, _ in sources)} rows")
    absent, plan = {}, []
    for msg, dflt in used:
        f = rows[msg][0].fmt
        if "TimeUS" not in f.colhash:
            return Stream(ABSENT, src, reason=f"{msg} has no TimeUS: v1 reads one clock (rule 1)")
        if inst_col and inst_col not in f.colhash and dflt is None:
            return Stream(ABSENT, src, reason=f"{msg} has no {inst_col} column: instance unidentifiable")
        for c, mc in cols.items():
            if mc not in f.colhash:
                absent[c] = f"{msg} has no {mc} column"
            elif mc in VALUE_COLS and f.format[f.colhash[mc]] not in SCALED_FMT:
                absent[c] = f"{msg}.{mc} is a bare integer ('{f.format[f.colhash[mc]]}'): units unknown"
        plan.append((msg, inst_col if inst_col in f.colhash else None, dflt))
    keep = [(c, mc) for c, mc in cols.items() if c not in absent]
    rows_out = ((getattr(m, ic) if ic else dflt, _t(m), [getattr(m, mc) for _, mc in keep])
                for msg, ic, dflt in plan for m in rows[msg])
    return series(name, src, rows_out, [c for c, _ in keep], absent)


def _measured(rows, msgs, col, ok, what, build):
    """`build(rows)` over only the rows of `msgs` whose `col` says the source measured something (G230). An
    instance with no such row stays, EMPTY (t_s = []), so the window-edge gap rule names it: less evidence must
    never read greener (G256)."""
    kept = {m: [x for x in rows[m] if col in x.fmt.colhash and ok(getattr(x, col))] for m in msgs}
    total, n = sum(len(rows[m]) for m in msgs), sum(map(len, kept.values()))
    s = build({**rows, **kept})
    if total and not n:
        return Stream(ABSENT, s.source, reason=f"0 of {total} {'/'.join(msgs)} rows measured anything: {what}")
    full = build(rows).data
    empty = [i for i in full if i not in s.data]
    for i in empty:
        s.data[i] = {k: [] for k in full[i]}
    s.note = (f"{total - n} of {total} {'/'.join(msgs)} rows excluded: {what}" +
              (f"; instance(s) {empty} have no such row and are EMPTY" if empty else "")) if n < total else None
    return s


def _firmware(rows):
    """-> vehicle, firmware string, (major, minor), release (no suffix), board, why-vehicle-ABSENT."""
    texts = [m.FWS for m in rows["VER"] if "FWS" in m.fmt.colhash] + [m.Message for m in rows["MSG"]]
    found = {mt.group(0): mt for t in texts if (mt := FIRMWARE.match(t))}
    board = next((mt.group(1) for m in rows["MSG"] if (mt := BOARD.match(m.Message))), None)
    if len(found) != 1:
        why = (f"conflicting firmware strings {sorted(found)}" if found else
               "no ArduCopter/ArduPlane/ArduRover/ArduSub firmware string in VER or MSG")
        return None, None, None, False, board, why
    mt = next(iter(found.values()))
    return mt.group(1), mt.group(0), (int(mt.group(2)), int(mt.group(3))), mt.group(4) == "", board, None


def _fence(params):
    """§2 fence from PARM. FENCE_TYPE bits (https://ardupilot.org/copter/docs/parameters.html#fence-type):
    1 max altitude, 2 circle, 4 polygon (printed as not judged: v1 reads no FNCE), 8 min altitude."""
    v = {}
    for k in ("FENCE_ENABLE", "FENCE_TYPE", "FENCE_RADIUS", "FENCE_ALT_MAX"):
        vals = {x for _, x in params.get(k, ())}
        if len(vals) > 1:
            return {"state": ABSENT, "reason": f"{k} changed in flight: {sorted(vals)}"}
        v[k] = vals.pop() if vals else None
    if v["FENCE_ENABLE"] is None or v["FENCE_TYPE"] is None:
        return {"state": ABSENT, "reason": "FENCE_ENABLE / FENCE_TYPE not logged"}
    if v["FENCE_ENABLE"] == 0:
        return {"state": ABSENT, "reason": "fence disabled (FENCE_ENABLE 0)"}
    typ = int(v["FENCE_TYPE"])
    if not typ & 3 or (typ & 2 and v["FENCE_RADIUS"] is None) or (typ & 1 and v["FENCE_ALT_MAX"] is None):
        return {"state": ABSENT, "reason": f"FENCE_TYPE {typ}: no circle/alt-max bit, or its parameter is unlogged"}
    return {"state": PRESENT, "fence_type": typ, "circle_radius_m": v["FENCE_RADIUS"] if typ & 2 else None,
            "alt_max_rel_home_m": v["FENCE_ALT_MAX"] if typ & 1 else None, "polygon_bit": bool(typ & 4),
            "note": "FENCE_TYPE polygon bit set: not judged (v1 reads no FNCE)" if typ & 4 else None}


def _home(rows):
    homes = {(m.Lat, m.Lng, m.Alt) for m in rows["ORGN"] if getattr(m, "Type", None) == 1}
    if len(homes) != 1:
        return {"state": ABSENT, "reason": f"{len(homes)} distinct ORGN Type 1 rows (v1 judges one fixed home)"}
    (lat, lon, alt), = homes
    return {"state": PRESENT, "lat": lat, "lon": lon, "alt_amsl_m": alt}


def _dsf(integ, dsf, t0):
    """Rule 5. DSF.Dp is cumulative per log file (0 at its start), so each rise is an interval with drops;
    after the last DSF row nothing is known."""
    integ.update(dsf_dropped_max=None, dsf_rows=dsf.n, drop_intervals=[], drops_known_until_s=None,
                 reason=dsf.reason or dsf.absent_cols.get("dp"))
    if dsf.state == PRESENT and "dp" in dsf.data[0]:
        d, prev, tp = dsf.data[0], 0, t0
        for t, dp in zip(d["t_s"], d["dp"]):
            if dp - prev if dp >= prev else dp:          # G323: a decrease is a counter reset, never a negative count
                integ["drop_intervals"].append([round(tp, 6), round(t, 6), dp - prev if dp >= prev else dp])
            prev, tp = dp, t
        integ.update(dsf_dropped_max=max(d["dp"]), drops_known_until_s=round(d["t_s"][-1], 6), reason=None)
    return integ


def read(path):
    rows, counts, integ, t0, t_last, defined = _decode(path)
    for name, ms in rows.items():          # a column without a format character would raise mid-read (G262)
        if ms and len(ms[0].fmt.columns) != len(ms[0].fmt.format):
            raise Refusal(f"malformed FMT for {name}: {len(ms[0].fmt.columns)} column names, "
                          f"{len(ms[0].fmt.format)} format characters ({ms[0].fmt.format!r})")
    vehicle, firmware, version, release, board, why = _firmware(rows)
    table = _modes().get(vehicle)
    params, bad_parm = {}, sorted({m.Name for m in rows["PARM"] if not math.isfinite(m.Value)})
    for m in rows["PARM"]:
        if math.isfinite(m.Value):
            params.setdefault(m.Name, []).append((_t(m), m.Value))
    st = {"position": _stream("position", rows, [("POS", 0)], None,
                              {"lat": "Lat", "lon": "Lng", "alt_amsl_m": "Alt", "alt_rel_home_m": "RelHomeAlt"}),
          "velocity": _measured(rows, ["GPS"], "Status", lambda v: v >= 3, "no 3D fix (Status < 3)",
                                lambda rw: _stream("velocity", rw, [("GPS", 0)], "I", {"groundspeed_mps": "Spd"})),
          "gnss": _stream("gnss", rows, [("GPS", 0)], "I", {"fix_type": "Status", "nsats": "NSats",
                                                            "hdop": "HDop", "gps_week": "GWk", "gps_ms": "GMS"}),
          "battery": _stream("battery", rows, [("BAT", 0)], "Inst", {"voltage_v": "Volt", "current_a": "Curr"})}
    if rows["XKF4"] and (rows["NKF4"] or rows["NKF9"]):
        st["ekf"] = Stream(ABSENT, "XKF4 by C | NKF4 + NKF9", reason="both EKF3 (XKF4) and EKF2 (NKF4/NKF9) "
                           "rows: v1 judges one estimator's cores, never two as one")
    else:
        src = [("XKF4", None)] if rows["XKF4"] else [("NKF4", 0), ("NKF9", 1)]
        st["ekf"] = _measured(rows, [m for m, _ in src], "SS", lambda v: v != 0, "EKF reported no solution (SS 0)",
                              lambda rw: _stream("ekf", rw, src, "C", EKF, None if rows["XKF4"] else
                                                 "EKF2: NKF4 = core 0, NKF9 = core 1, or NKF4 by C (SV, SP, SH, SM)"))
    pos, t_home = st["position"], min((_t(m) for m in rows["ORGN"] if getattr(m, "Type", None) == 1), default=None)
    if pos.state == PRESENT and "alt_rel_home_m" in pos.data[0]:
        d = pos.data[0]
        if t_home is None:
            pos.absent_cols["alt_rel_home_m"] = "no ORGN Type 1 row: RelHomeAlt has no home"
            del d["alt_rel_home_m"]
        elif d["t_s"][0] < t_home:
            d["alt_rel_home_m"] = [None if t < t_home else v for t, v in zip(d["t_s"], d["alt_rel_home_m"])]
            pos.note = (f"{sum(t < t_home for t in d['t_s'])} RelHomeAlt samples before home was set (first ORGN "
                        f"Type 1 at t={t_home:.3f} s): not a value")
    for name, others in NOT_READ.items():
        skipped = [f"{counts[o]} {o}" for o in others if counts[o]]
        if skipped and st[name].state == PRESENT:
            st[name].note = "; ".join(filter(None, (st[name].note, f"{', '.join(skipped)} rows not read")))
    st["mode"] = _stream("mode", rows, [("MODE", 0)], None, {"num": "ModeNum", "rsn": "Rsn"})
    if "num" in st["mode"].absent_cols:                  # a MODE record without ModeNum names no mode (corpus log 22)
        st["mode"] = Stream(ABSENT, st["mode"].source, reason=st["mode"].absent_cols["num"])
    if st["mode"].state == PRESENT:
        d = st["mode"].data[0]
        d["name"] = [table.get(n, f"UNKNOWN({n})") if table else None for n in d["num"]]
        st["mode"].note = None if table else f"mode names ABSENT: vehicle unresolved ({why})"
    st["arming"] = _stream("arming", rows, [("ARM", 0)], None, {"armed": "ArmState"})
    if st["arming"].state == PRESENT:
        d = st["arming"].data[0]
        if not set(d["armed"]) <= {0, 1}:
            st["arming"] = Stream(ABSENT, st["arming"].source, reason=f"ArmState outside {{0, 1}}: {sorted(set(d['armed']))}")
        else:
            d["armed"] = [a == 1 for a in d["armed"]]
    st["events"] = _stream("events", rows, [("ERR", 0)], None, {"subsys": "Subsys", "ecode": "ECode"})
    backend = sorted({v for _, v in params.get("LOG_BACKEND_TYPE", ())})
    premise = (f"the citation's premise is a release V4.5.<n> firmware string (this log: {firmware or 'unresolved'}) "
               f"and LOG_BACKEND_TYPE logged, constant and == 1, File only (this log: {backend or 'not logged'})")
    if not rows["ERR"] and version == (4, 5) and release and backend == [1] and "ERR" in defined:
        st["events"] = Stream(EMPTY, st["events"].source, reason=f"zero ERR rows: {ERR_NOTE}; {premise}")
    elif not rows["ERR"]:
        st["events"].reason = f"zero ERR rows outside the citation: {premise}" + ("" if "ERR" in defined else
                                                                                  "; no ERR format defined")
    elif st["events"].state == PRESENT:
        d = st["events"].data[0]
        d["code"] = [[s, e] for s, e in zip(d.pop("subsys"), d.pop("ecode"))]
        d.update(kind=["error"] * len(d["t_s"]), text=[f"ERR Subsys {s} ECode {e}" for s, e in d["code"]])
    gw = min(((t, w, ms) for dd in st["gnss"].data.values() if "gps_week" in dd and "gps_ms" in dd
              for t, w, ms in zip(dd["t_s"], dd["gps_week"], dd["gps_ms"]) if w > 0), default=None)
    absent = {"vehicle": why, "hardware": None if board else "no '<board> <uid>' MSG row",
              "params": bad_parm and f"PARM rows with a non-finite value not read: {bad_parm}"}
    meta = {"format": "ardupilot-dataflash", "adapter": "ardupilot", "vehicle": vehicle, "firmware": firmware,
            "params_nonfinite": [(_t(m), m.Name) for m in rows["PARM"] if not math.isfinite(m.Value)],  # D1
            "version": version, "hardware": board, "mode_table": table, "counts": dict(sorted(counts.items())),
            "records_decoded": sum(counts.values()), "parser": {"pymavlink": metadata.version("pymavlink")},
            "absent": {k: r for k, r in absent.items() if r},
            "log_gpst_start": gw and {"t_s": round(gw[0], 6), "gps_week": gw[1], "gps_ms": gw[2],
                                      "label": "GPS time, not UTC: the 18 s leap offset is not applied"}}
    integ = _dsf(integ, _stream("dsf", rows, [("DSF", 0)], None, {"dp": "Dp"}), t0)
    return FlightLog(meta, integ, st, _home(rows), params, _fence(params), t0, round(t_last + TICK_S, 6))


def _modes():
    from pymavlink import mavutil
    return {"ArduCopter": mavutil.mode_mapping_acm, "ArduPlane": mavutil.mode_mapping_apm,
            "ArduRover": mavutil.mode_mapping_rover, "ArduSub": mavutil.mode_mapping_sub}
