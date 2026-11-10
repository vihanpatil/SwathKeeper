"""swathkeeper_gates' verdict (design §5, §6, §9): the exit/badge table row for row, the exact-set
declared-red comparison, the declared file's refusals, and the JSON's required keys. Each red-first
assertion names the mutant it was shown failing against.
"""
import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swathkeeper_gates import allowlist, cli  # noqa: E402
from swathkeeper_gates import verdict as V  # noqa: E402
from swathkeeper_gates import bars as B  # noqa: E402
from swathkeeper_gates.bars import EI, FAIL, NA, PASS  # noqa: E402
from swathkeeper_gates.contract import Refusal  # noqa: E402
from test_gates_adapter import flight_rows, write_synthetic_log  # noqa: E402

TODAY = dt.date(2026, 11, 5)
REGISTERED = {"status": "HASH_MATCH", "post_hoc": False}


def results(*pairs):
    return [{"id": f"b{i}", "severity": sev, "verdict": v} for i, (sev, v) in enumerate(pairs)]


def decl(bar, verdict, expires=dt.date(2027, 1, 31)):
    return {"bar": bar, "verdict": verdict, "reason": "names the evidence", "expires": expires}


def outcome(res, declared=(), prereg=REGISTERED, assumed=0):
    return V.outcome(res, allowlist.compare(res, list(declared), TODAY), prereg, None, assumed)


class TestTheTable(unittest.TestCase):
    def test_row_1_no_red_and_a_pass(self):
        self.assertEqual(outcome(results(("must", PASS), ("should", EI))), (0, "gates: pass · 1/2 measured"))

    def test_row_2_every_red_matches_a_live_declaration(self):
        res = results(("must", PASS), ("must", FAIL), ("must", EI))
        self.assertEqual(outcome(res, [decl("b1", FAIL), decl("b2", EI)]),
                         (0, "gates: pass · 2/3 measured · 2 declared (1 FAIL, 1 EI)"))

    def test_row_3_undeclared_vacuous_expired_or_mismatched_is_fail(self):
        res = results(("must", PASS), ("should", FAIL))
        for name, declared in (("undeclared", []), ("vacuous", [decl("b1", FAIL), decl("b0", FAIL)]),
                               ("expired", [decl("b1", FAIL, expires=TODAY)]), ("mismatch", [decl("b1", EI)])):
            with self.subTest(name):   # mutant: subset (reds within the declarations pass) -> vacuous red
                code, badge = outcome(res, declared)
                self.assertEqual((code, badge.split(" · ")[0]), (1, "gates: fail"))

    def test_row_4_an_undeclared_must_ei_or_na_or_no_must_pass_could_not_tell(self):
        self.assertEqual(outcome(results(("must", PASS), ("must", NA))), (1, "gates: could not tell · 1/2 measured"))
        self.assertEqual(outcome(results(("should", EI), ("should", EI))), (1, "gates: could not tell · 0/2 measured"))
        # G241 (design amendment) mutant: any PASS, not a must PASS, reads pass -> red
        self.assertEqual(outcome(results(("should", PASS), ("must", FAIL)), [decl("b1", FAIL)]),
                         (1, "gates: could not tell · 2/2 measured · 1 declared (1 FAIL, 0 EI)"))

    def test_row_5_a_refusal_and_the_suffixes(self):
        self.assertEqual(V.outcome([], None, None, "a reason"), (2, "gates: refused"))
        res = results(("must", PASS))
        self.assertEqual(outcome(res, prereg={"status": "HASH_MATCH", "post_hoc": True})[1], "gates: pass · 1/1 measured (post-hoc)")
        self.assertEqual(outcome(res, prereg={"status": "NOT_REGISTERED", "post_hoc": False})[1],
                         "gates: pass · 1/1 measured (unregistered)")
        self.assertEqual(outcome(results(("must", PASS), ("must", FAIL)), [decl("b1", FAIL)], {"status": "HASH_MATCH", "post_hoc": True},
                                 1), (0, "gates: pass · 2/2 measured · 1 declared (1 FAIL, 0 EI) · 1 assumed (post-hoc)"))   # A7

    def test_the_exact_set_lists_every_leftover(self):
        res = results(("must", PASS), ("must", FAIL), ("must", NA))
        a = allowlist.compare(res, [decl("b1", FAIL), decl("b0", FAIL), decl("b2", NA, expires=TODAY)], TODAY)
        self.assertEqual((a["matched"], a["undeclared"], a["vacuous"], a["expired"]),
                         ([["b1", FAIL]], [["b2", NA]], [["b0", FAIL]], [["b2", NA]]))


class TestDeclaredFile(unittest.TestCase):
    BARS = [{"id": "m", "severity": "must"}, {"id": "s", "severity": "should"}]

    def load(self, entry):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "d.yaml").write_text(f"schema: swathkeeper-declared/1.0\ndeclared:\n  - {entry}\n")
            return allowlist.load(Path(d) / "d.yaml", self.BARS)

    def test_a_good_entry_loads(self):
        entries, _ = self.load("{bar: m, verdict: EVIDENCE_INSUFFICIENT, reason: r, expires: 2027-01-31}")
        self.assertEqual(entries[0]["expires"], dt.date(2027, 1, 31))

    def test_every_entry_that_could_never_match_a_red_refuses(self):
        for entry, why in (("{bar: m, verdict: PASS, reason: r, expires: 2027-01-31}", "PASS"),          # mutant: PASS allowed
                           ("{bar: s, verdict: EVIDENCE_INSUFFICIENT, reason: r, expires: 2027-01-31}", "never red"),  # mutant: check dropped
                           ("{bar: x, verdict: FAIL, reason: r, expires: 2027-01-31}", "names no bar"),
                           ("{bar: m, verdict: FAIL, reason: ' ', expires: 2027-01-31}", "non-empty"),
                           ("{bar: m, verdict: FAIL, reason: r, expires: '2027-01-31'}", "YAML date"),
                           ("{bar: m, verdict: FAIL, reason: r, expires: 2027-13-01}", "invalid YAML"),
                           ("{bar: m, verdict: FAIL, reason: r, expires: 2027-01-31}\n  - {bar: m, verdict: EVIDENCE_"
                            "INSUFFICIENT, reason: r, expires: 2027-01-31}", "a second declaration")):          # Q17
            with self.subTest(why=why), self.assertRaisesRegex(Refusal, why):
                self.load(entry)


BARS = """schema: swathkeeper-bars/1.0
contract: swathkeeper-flightlog/1.0
bars:
  - {id: batt, kind: series_bound, severity: must, provenance: {text: t}, scope: {armed: null, modes: null},
     min_n: 1, params: {channel: battery.voltage_v, bound: floor, limit: 18.6}}
  - {id: thin, kind: series_bound, severity: should, provenance: {text: t}, scope: {armed: null, modes: null},
     min_n: 100000, params: {channel: battery.voltage_v, bound: floor, limit: 18.6}}
"""
KEYS = {"schema", "contract", "tool", "source", "integrity", "streams", "bars", "prereg", "results", "allowlist",
        "exit_code", "badge", "refusal", "assumptions"}
ARMED_BARS = BARS.replace("scope: {armed: null, modes: null},\n     min_n: 1,", "scope: {armed: true, modes: null},\n     min_n: 1,", 1)
RESULT_KEYS = {"id", "kind", "severity", "verdict", "measured", "bar", "n", "min_n", "scope", "instances_used",
               "worst_instance", "gaps", "note", "provenance", "param_in_log"}


class TestTheJson(unittest.TestCase):
    def run_cli(self, log_rows=None, sidecar=None, bars=BARS):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            log = write_synthetic_log(Path(d) / "f.bin", log_rows) if log_rows else Path(d) / "missing.bin"
            (Path(d) / "bars.yaml").write_text(bars)
            if sidecar:
                (Path(d) / "bars.yaml.prereg.json").write_text(sidecar)
            code = cli.main(["run", "--log", str(log), "--bars", str(Path(d) / "bars.yaml"), "--out", str(Path(d) / "v.json")])
            return code, json.loads((Path(d) / "v.json").read_text())

    def test_a_verdict_has_every_key_and_no_number_on_an_ei(self):
        code, v = self.run_cli(flight_rows())
        self.assertEqual((code, set(v), v["badge"]), (0, KEYS, "gates: pass · 1/2 measured (unregistered)"))
        self.assertEqual([set(r) for r in v["results"]], [RESULT_KEYS] * 2)
        self.assertEqual([(r["verdict"], r["measured"] is None) for r in v["results"]], [(PASS, False), (EI, True)])
        self.assertEqual((v["source"]["path"], v["bars"]["path"]), ("f.bin", "bars.yaml"))   # basenames, never host paths

    def test_the_assumptions_block_and_badge_and_an_untouched_arming_stream(self):
        self.assertEqual(self.run_cli(flight_rows())[1]["assumptions"], [])
        code, v = self.run_cli(flight_rows(), bars="assume: [arming_before_first_arm_row]\n" + ARMED_BARS)
        self.assertEqual(v["assumptions"], [{"name": "arming_before_first_arm_row", "text": B.ASSUMPTIONS["arming_before_first_arm_row"],
                                             "applied": True, "detail": "first ARM row at t=1.500 s is an arm: disarmed before it",
                                             "log_disarmed": None}])
        self.assertTrue(B.ASSUMPTIONS["arming_before_first_arm_row"].startswith("Before the first ARM row the vehicle is in the "
                                                                              "opposite state of that row: armed before a first disarm"))
        self.assertEqual((code, v["badge"]), (0, "gates: pass · 1/2 measured · 1 assumed (unregistered)"))  # mutant: applied count
        self.assertEqual(v["streams"]["arming"], self.run_cli(flight_rows(), bars=ARMED_BARS)[1]["streams"]["arming"])
        none = [x for x in flight_rows() if x[0] != "ARM"]
        code, v = self.run_cli(none, bars="assume: [arming_before_first_arm_row]\n" + ARMED_BARS)
        self.assertEqual((v["assumptions"][0]["applied"], v["badge"]), (False, "gates: could not tell · 0/2 measured · 1 assumed (unregistered)"))

    def test_a_refusal_has_the_same_keys_and_no_results(self):
        code, v = self.run_cli()
        self.assertEqual((code, set(v), v["results"], v["badge"]), (2, KEYS, [], "gates: refused"))
        self.assertIn("log not found", v["refusal"])
        sha = "0" * 64
        dup = f'{{"schema": "swathkeeper-prereg/1.0", "bars_sha256": "{sha}", "bars_sha256": "{sha}", "tool_version": "x", "written_utc": "x"}}'
        code, v = self.run_cli(flight_rows(), sidecar=dup)
        self.assertEqual((code, v["prereg"]["status"]), (2, "MALFORMED"))   # Q8 mutant: duplicate keys load -> red; G248


if __name__ == "__main__":
    unittest.main()
