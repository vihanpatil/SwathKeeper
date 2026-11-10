"""swathkeeper_gates' ArduPilot adapter against DataFlash bytes this file writes itself (design §9, D9).

`write_synthetic_log` packs FMT records and rows with `struct` (no third-party bytes), and `flight_rows`
builds a clean 30 s Copter flight at 10 Hz: POS, GPS x2 instances, BAT x2, XKF4 x2 cores, MODE, ARM,
DSF, PARM, ORGN, MSG. The other three test_gates_*.py files import both from here. Every test is
red-first: the mutant it was shown failing against is named beside its assertion.
"""
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from swathkeeper_gates import adapters  # noqa: E402
from swathkeeper_gates.contract import ABSENT, EMPTY, PRESENT, Refusal, log_holes, streams_map  # noqa: E402

LAT0, LON0, T0 = 53.0, 10.0, 1.0
M_PER_DEG = 111318.84502145034
# DataFlash format char -> (struct code, the factor an SI value is multiplied by when WRITTEN)
CHARS = {"Q": ("Q", 0), "B": ("B", 0), "H": ("H", 0), "I": ("I", 0), "f": ("f", 0), "M": ("B", 0),
         "L": ("i", 1e7), "c": ("h", 100), "e": ("i", 100), "N": ("16s", 0), "Z": ("64s", 0)}
FMTS = {"PARM": (32, "QNf", "TimeUS,Name,Value"), "MSG": (33, "QZ", "TimeUS,Message"),
        "POS": (34, "QLLff", "TimeUS,Lat,Lng,Alt,RelHomeAlt"), "GPS": (35, "QBBIHBcf", "TimeUS,I,Status,GMS,GWk,NSats,HDop,Spd"),
        "BAT": (36, "QBff", "TimeUS,Inst,Volt,Curr"), "XKF4": (37, "QBccccI", "TimeUS,C,SV,SP,SH,SM,SS"),
        "NKF4": (38, "QccccI", "TimeUS,SV,SP,SH,SM,SS"), "NKF9": (39, "QccccI", "TimeUS,SV,SP,SH,SM,SS"),
        "MODE": (40, "QMBB", "TimeUS,Mode,ModeNum,Rsn"), "ARM": (41, "QB", "TimeUS,ArmState"),
        "ERR": (42, "QBB", "TimeUS,Subsys,ECode"), "DSF": (43, "QI", "TimeUS,Dp"),
        "ORGN": (44, "QBLLe", "TimeUS,Type,Lat,Lng,Alt"), "FMTU": (45, "QBNN", "TimeUS,FmtType,UnitIds,MultIds")}
PARAMS = {"FENCE_ENABLE": 1, "FENCE_TYPE": 3, "FENCE_RADIUS": 150, "FENCE_ALT_MAX": 100, "LOG_BACKEND_TYPE": 1}
STD = ((0.0, "MODE", 0), (0.5, "ARM", 1), (10.0, "MODE", 2), (20.0, "MODE", 5))   # STABILIZE, ALT_HOLD, LOITER


def us(t):
    return round((T0 + t) * 1e6)


def latlon(x_east, y_north):
    """Local metres about home -> degrees (the inverse of the tool's equirectangular ENU)."""
    return LAT0 + y_north / M_PER_DEG, LON0 + x_east / (M_PER_DEG * math.cos(math.radians(LAT0)))


def write_synthetic_log(path, rows, formats=FMTS):
    """rows = [(message, {column: SI value})] in file order -> a DataFlash file: every FMT first, then rows."""
    out = bytearray()
    for name, (tid, fmt, cols) in formats.items():
        length = 3 + struct.calcsize("<" + "".join(CHARS[c][0] for c in fmt))
        out += b"\xa3\x95\x80" + struct.pack("<BB4s16s64s", tid, length, name.encode(), fmt.encode(), cols.encode())
    for name, vals in rows:
        tid, fmt, cols = formats[name]
        packed = [v.encode() if isinstance(v, str) else v if CHARS[c][0] == "f" else round(v * (CHARS[c][1] or 1))
                  for c, v in zip(fmt, (vals[k] for k in cols.split(",")))]
        out += b"\xa3\x95" + bytes([tid]) + struct.pack("<" + "".join(CHARS[c][0] for c in fmt), *packed)
    Path(path).write_bytes(bytes(out))
    return path


def flight_rows(seconds=30, banner="ArduCopter V4.5.5 (synthetic)", track=lambda t: (t, 50.0, 5.0), events=STD,
                params=PARAMS, geo=latlon, home_at=0.0):
    """A clean flight: east at 1 m/s 50 m north of home, 5 m up. Modes STABILIZE, ALT_HOLD, LOITER (Copter)."""
    rows = [("MSG", {"TimeUS": us(0), "Message": banner})] if banner else []
    rows += [("PARM", {"TimeUS": us(0), "Name": n, "Value": v}) for n, v in params.items()]
    for k in range(seconds * 10 + 1):
        t = k / 10
        rows += [("ORGN", {"TimeUS": us(t), "Type": 1, "Lat": LAT0, "Lng": LON0, "Alt": 10.0})] * (round(home_at * 10) == k)
        for et, name, v in events:
            if round(et * 10) == k:
                rows.append((name, {"TimeUS": us(t), **({"Mode": v, "ModeNum": v, "Rsn": 1} if name == "MODE" else
                                                        {"ArmState": v} if name == "ARM" else {"Subsys": v, "ECode": 1})}))
        x, y, alt = track(t)
        lat, lon = geo(x, y)
        rows.append(("POS", {"TimeUS": us(t), "Lat": lat, "Lng": lon, "Alt": 10.0 + alt, "RelHomeAlt": alt}))
        rows += [("BAT", {"TimeUS": us(t), "Inst": i, "Volt": 24.0 + i / 10, "Curr": 10.0}) for i in (0, 1)]
        rows += [("XKF4", {"TimeUS": us(t), "C": c, "SV": 0.1, "SP": 0.1, "SH": 0.1, "SM": 0.1, "SS": 1}) for c in (0, 1)]
        if k % 2 == 0:
            rows += [("GPS", {"TimeUS": us(t), "I": i, "Status": 4, "GMS": round(t * 1000), "GWk": 2300, "NSats": 12,
                              "HDop": 0.8, "Spd": 3.0}) for i in (0, 1)]
        if k % 10 == 0:
            rows.append(("DSF", {"TimeUS": us(t), "Dp": 0}))
    return rows


def edit(rows, name, t, inst=None, **cols):
    """The rows with `name` at time t (and instance `inst`, if given) changed."""
    hit = lambda n, v: n == name and v["TimeUS"] == us(t) and inst in (None, v.get("I", v.get("Inst", v.get("C"))))
    return [(n, {**v, **cols} if hit(n, v) else v) for n, v in rows]


def gps(rows, start, end, **cols):
    """GPS rows with start <= t < end changed (both instances)."""
    return [(n, {**v, **cols} if n == "GPS" and us(start) <= v["TimeUS"] < us(end) else v) for n, v in rows]


def parse(rows, formats=FMTS):
    with tempfile.TemporaryDirectory() as d:
        return adapters.load(write_synthetic_log(Path(d) / "f.bin", rows, formats))


def surgery(rows, fn):
    """Parse `rows` written to bytes after fn(bytearray) corrupted them in place."""
    with tempfile.TemporaryDirectory() as d:
        path = write_synthetic_log(Path(d) / "z.bin", rows)
        raw = bytearray(path.read_bytes())
        fn(raw)
        path.write_bytes(bytes(raw))
        return adapters.load(path)


def at_time(raw, t):
    """Byte offset of the first record stamped t (past the FMT records)."""
    return raw.find(struct.pack("<Q", us(t)), 89 * len(FMTS)) - 3


def zeroed(rows, at=None, span=None):
    """-> (log, n bytes zeroed): the first record of type id `at`; or every byte from the first record stamped
    span[0] up to the first stamped span[1]; else 40-50 % of the file."""
    n = []

    def fn(raw):
        if at:
            a = raw.find(bytes([0xA3, 0x95, at]), 89 * len(FMTS))
            b = a + 3 + struct.calcsize("<" + "".join(CHARS[c][0] for c in next(f for i, f, _ in FMTS.values() if i == at)))
        else:
            a, b = (at_time(raw, span[0]), at_time(raw, span[1])) if span else (len(raw) * 4 // 10, len(raw) // 2)
        raw[a:b] = bytes(b - a)
        n.append(b - a)
    return surgery(rows, fn), n[0]


class TestStreams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = parse(flight_rows())

    def test_each_stream_comes_from_its_section_2_message(self):
        st = self.log.streams
        self.assertEqual({k: s.state for k, s in st.items()},
                         {"position": PRESENT, "velocity": PRESENT, "gnss": PRESENT, "battery": PRESENT,
                          "ekf": PRESENT, "mode": PRESENT, "arming": PRESENT, "events": EMPTY})
        self.assertEqual([sorted(st[k].data) for k in ("velocity", "gnss", "battery", "ekf")], [[0, 1]] * 4)
        self.assertAlmostEqual(st["battery"].data[1]["voltage_v"][0], 24.1, places=5)
        self.assertAlmostEqual(st["position"].data[0]["lat"][0], latlon(0, 50)[0], places=7)    # L x1e-7 applied
        self.assertAlmostEqual(st["ekf"].data[1]["vel_ratio"][0], 0.1)                           # c x0.01 applied
        self.assertEqual((st["mode"].data[0]["name"], st["mode"].data[0]["rsn"]), (["STABILIZE", "ALT_HOLD", "LOITER"], [1] * 3))
        self.assertEqual((self.log.meta["version"], self.log.fence["circle_radius_m"], self.log.fence["alt_max_rel_home_m"]),
                         ((4, 5), 150, 100))
        g = self.log.integrity
        self.assertEqual((self.log.home["state"], g["bytes_skipped"], g["holes"], g["dsf_dropped_max"]), (PRESENT, 0, [], 0))

    def test_a_missing_message_or_column_is_absent_never_zero(self):
        log = parse([r for r in flight_rows() if r[0] != "BAT"])
        # mutant "default 0.0" (no BAT rows -> a PRESENT stream of 0.0 V): red
        self.assertEqual((log.streams["battery"].state, log.streams["battery"].data), (ABSENT, {}))
        log = parse(flight_rows(), {**FMTS, "BAT": (36, "QBf", "TimeUS,Inst,Volt")})
        # mutant: a missing column zero-filled -> red
        self.assertIn("current_a", log.streams["battery"].absent_cols)
        self.assertNotIn("current_a", log.streams["battery"].data[0])
        fm = {**FMTS, "BAT": (36, "QBHf", "TimeUS,Inst,Volt,Curr")}
        # mutant: the bare-integer guard removed (raw units read as volts) -> red
        self.assertIn("units unknown", parse(flight_rows(), fm).streams["battery"].absent_cols.get("voltage_v", ""))
        with self.assertRaisesRegex(Exception, "malformed FMT for BAT") as cm:   # G262 mutant: IndexError -> internal error
            parse(flight_rows(), {**FMTS, "BAT": (36, "QBff", "TimeUS,Inst,Volt,Curr,Extra")})
        self.assertIsInstance(cm.exception, Refusal)

    def test_a_backwards_contract_clock_refuses_and_a_backwards_fmtu_does_not(self):
        rows = flight_rows()
        i = next(k for k, (n, v) in enumerate(rows) if n == "POS" and v["TimeUS"] == us(5.0))
        bad = rows[:i] + [("POS", {**rows[i][1], "TimeUS": us(4.0)})] + rows[i + 1:]
        with self.assertRaisesRegex(Refusal, r"non-monotone clock in position instance 0: row 50"):   # mutant: sort -> red
            parse(bad)
        fmtu = [("FMTU", {"TimeUS": us(t), "FmtType": 34, "UnitIds": "s", "MultIds": "F"}) for t in (3.0, -0.5)]
        log = parse(fmtu + rows)
        self.assertEqual(log.streams["position"].state, PRESENT)        # mutant: check all types -> red
        self.assertEqual(log.t0, T0)                                     # G244 mutant: t0 over every type -> red

    def test_every_byte_skip_is_counted_and_located_as_a_hole(self):
        log, n = zeroed(flight_rows())
        g = log.integrity
        self.assertEqual((g["bytes_skipped_interior"], g["bytes_skipped_trailing"]), (g["bytes_skipped"], 0))
        self.assertGreater(g["bytes_skipped"], n // 2)                    # mutant: bytes_skipped = 0 -> red
        self.assertTrue(log_holes(log) and all(y - x > 1.0 for x, y in log_holes(log)))
        log, n = zeroed(flight_rows(), at=40)                             # ONE MODE row (14 bytes), far under 1 s
        # G229 mutant: skips located only by the gap rule -> no hole -> red
        self.assertEqual(([h[2] for h in log.integrity["holes"]], log.streams["mode"].n), ([n], 2))

    def test_ekf2_nkf9_is_core_1_and_gps_instance_1_alone_is_present(self):
        rows = [r for r in flight_rows() if r[0] != "XKF4"]
        rows += [(m, {"TimeUS": us(k / 10), "SV": 0.2, "SP": 0.2, "SH": 0.2, "SM": 0.2, "SS": 1}) for k in range(301) for m in ("NKF4", "NKF9")]
        rows = sorted((r for r in rows if not (r[0] == "GPS" and r[1]["I"] == 0)), key=lambda r: r[1]["TimeUS"])
        log = parse(rows)
        self.assertEqual(sorted(log.streams["ekf"].data), [0, 1])        # mutant: NKF4 only -> red
        self.assertEqual(sorted(log.streams["gnss"].data), [1])          # mutant: instance 0 only -> red
        both = parse(rows + [("XKF4", {"TimeUS": us(30.0), "C": 0, "SV": 0, "SP": 0, "SH": 0, "SM": 0, "SS": 1})])
        self.assertEqual(both.streams["ekf"].state, ABSENT)               # two estimators are never one series

    def test_a_channel_keeps_only_rows_that_measured_something(self):
        log = parse(gps(gps(flight_rows(), 10, 11, Status=1), 11, 12, Status=2))     # a 2D fix is not a 3D fix (G259)
        # G230 mutants: velocity from no-fix rows; ekf from SS-0 rows; Status >= 2 -> red
        self.assertEqual((log.streams["velocity"].n, log.streams["gnss"].n), (282, 302))
        self.assertIn("20 of 302 GPS rows excluded", log.streams["velocity"].note)
        self.assertIn("0 of 302 GPS rows measured", parse(gps(flight_rows(), 0, 99, Status=0)).streams["velocity"].reason)
        core1 = parse([(n, {**v, "SS": 0} if n == "XKF4" and v["C"] == 1 else v) for n, v in flight_rows()])
        # G256 mutant: a fully excluded instance vanishes (and streams_map trips on an empty t_s) -> red
        self.assertEqual((sorted(core1.streams["ekf"].data), streams_map(core1)["ekf"]["instances"].get("1", {}).get("n")), ([0, 1], 0))
        no_sol = [(n, {**v, "SS": 0} if n == "XKF4" else v) for n, v in flight_rows()]
        ekf = parse(no_sol).streams["ekf"]
        self.assertEqual((ekf.state, "no solution (SS 0)" in str(ekf.reason)), (ABSENT, True))

    def test_rel_home_alt_is_a_value_only_once_home_is_set(self):
        pos = parse(flight_rows(home_at=5.0)).streams["position"]
        rel = pos.data[0]["alt_rel_home_m"]
        # G240 mutant: RelHomeAlt before ORGN Type 1 read as a value -> red
        self.assertEqual((rel[:50].count(None), rel[50]), (50, 5.0))
        self.assertIn("before home was set", pos.note)
        self.assertIn("no ORGN Type 1", parse(flight_rows(home_at=99)).streams["position"].absent_cols["alt_rel_home_m"])
        two = flight_rows() + [("ORGN", {"TimeUS": us(30.0), "Type": 1, "Lat": LAT0 + 1e-4, "Lng": LON0, "Alt": 10.0})]
        self.assertEqual(parse(two).home["state"], ABSENT)                # Q9 mutant: >1 distinct home accepted -> red

    def test_arming_is_absent_before_its_first_row_and_never_inferred(self):
        m = streams_map(parse(flight_rows(events=((0.0, "MODE", 0), (5.0, "ARM", 0)))))["arming"]
        # mutant "inferred" (a disarm row implies armed before it): red
        self.assertEqual((m["absent_before_s"], m["armed_intervals"]), (T0 + 5.0, []))
        self.assertEqual(parse(flight_rows(events=())).streams["arming"].state, ABSENT)
        bad = parse(flight_rows(events=((0.0, "MODE", 0), (5.0, "ARM", 2)))).streams["arming"]
        self.assertEqual(bad.state, ABSENT)                               # Q12 mutant: ArmState 2 accepted -> red

    def test_the_vehicle_comes_from_the_firmware_string_only(self):
        self.assertEqual(self.log.streams["mode"].data[0]["name"][2], "LOITER")   # Plane's 5 is FBWA
        log = parse(flight_rows(banner=None))
        # mutant "DFReader default" (an unresolved vehicle read as a Plane): red
        self.assertEqual((log.meta["vehicle"], log.streams["mode"].data[0]["name"]), (None, [None] * 3))
        two = flight_rows() + [("MSG", {"TimeUS": us(30.0), "Message": "ArduPlane V4.5.5 (x)"})]
        self.assertIn("conflicting", parse(two).meta["absent"].get("vehicle", ""))    # Q10

    def test_zero_err_rows_are_empty_only_inside_the_citations_premise(self):
        self.assertEqual(self.log.streams["events"].state, EMPTY)
        no_err_fmt = {k: v for k, v in FMTS.items() if k != "ERR"}
        for name, log in (("V4.7", parse(flight_rows(banner="ArduCopter V4.7.0 (x)"))),        # mutant: version check
                          ("-dev", parse(flight_rows(banner="ArduCopter V4.5.0-dev (x)"))),     # G238
                          ("block backend", parse(flight_rows(params={**PARAMS, "LOG_BACKEND_TYPE": 4}))),
                          ("unlogged backend", parse(flight_rows(params={k: v for k, v in PARAMS.items() if k != "LOG_BACKEND_TYPE"}))),
                          ("no ERR format", parse(flight_rows(), no_err_fmt))):                  # Q6
            with self.subTest(name):
                self.assertEqual(log.streams["events"].state, ABSENT)
        ev = parse(flight_rows(events=((0.0, "MODE", 0), (3.0, "ERR", 16)))).streams["events"]
        self.assertEqual((ev.state, ev.data[0]["kind"], ev.data[0]["code"]), (PRESENT, ["error"], [[16, 1]]))

    def test_dsf_rises_become_drop_intervals_and_a_fence_change_is_absent(self):
        rows = [(n, {**v, "Dp": 3} if n == "DSF" and v["TimeUS"] >= us(11) else v) for n, v in flight_rows()]
        g = parse(rows).integrity
        self.assertEqual((g["dsf_dropped_max"], g["drop_intervals"]), (3, [[T0 + 10, T0 + 11, 3]]))
        late = [(n, {**v, "Dp": 2} if n == "DSF" else v) for n, v in flight_rows() if not (n == "DSF" and v["TimeUS"] < us(5))]
        self.assertEqual(parse(late).integrity["drop_intervals"], [[T0, T0 + 5, 2]])   # Q4 mutant: Dp not 0 at start -> red
        reset = [(n, {**v, "Dp": 5 if v["TimeUS"] < us(20) else 2} if n == "DSF" and v["TimeUS"] >= us(10) else v) for n, v in flight_rows()]
        self.assertEqual(parse(reset).integrity["drop_intervals"], [[T0 + 9, T0 + 10, 5], [T0 + 19, T0 + 20, 2]])   # G323
        zero = [(n, {**v, "Dp": 5 if v["TimeUS"] < us(20) else 0} if n == "DSF" and v["TimeUS"] >= us(10) else v) for n, v in flight_rows()]
        self.assertEqual(parse(zero).integrity["drop_intervals"], [[T0 + 9, T0 + 10, 5]])   # G331: a reset to 0 drops nothing
        rows = flight_rows() + [("PARM", {"TimeUS": us(30.0), "Name": "FENCE_RADIUS", "Value": 50})]
        self.assertIn("changed in flight", parse(rows).fence.get("reason", ""))
        self.assertIn("disabled", parse(flight_rows(params={**PARAMS, "FENCE_ENABLE": 0})).fence.get("reason", ""))
        self.assertIn("no circle/alt-max bit", parse(flight_rows(params={**PARAMS, "FENCE_TYPE": 4})).fence.get("reason", ""))  # Q18

    def test_magic_bytes_route_or_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            for head, why in ((b"ULog\x01\x12\x35\x01", "px4 adapter is not shipped"), (b"\x00\x01\x02\x03", "unknown log format")):
                (Path(d) / "x").write_bytes(head + bytes(64))
                with self.assertRaisesRegex(Refusal, why):
                    adapters.load(Path(d) / "x")


if __name__ == "__main__":
    unittest.main()
