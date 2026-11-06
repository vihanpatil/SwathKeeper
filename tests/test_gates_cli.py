"""swathkeeper-gates' CLI in a subprocess (design §7, §9), and the import wall between the two packages.

The subprocess runs `python -m swathkeeper_gates.cli` with PYTHONPATH=src, so it works before and after
`pip install -e .`. Each red-first assertion names the mutant it was shown failing against.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from test_gates_adapter import flight_rows, write_synthetic_log  # noqa: E402
from test_gates_verdict import BARS  # noqa: E402

ENV = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def cli(*args, env=ENV):
    p = subprocess.run([sys.executable, "-m", "swathkeeper_gates.cli", *map(str, args)], capture_output=True,
                       text=True, env=env, cwd=REPO_ROOT, timeout=120)
    return p.returncode, p.stdout, p.stderr


class TestCli(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.log = write_synthetic_log(self.d / "f.bin", flight_rows())
        self.bars, self.out = self.d / "bars.yaml", self.d / "v.json"
        self.bars.write_text(BARS)
        self.run_args = ("run", "--log", self.log, "--bars", self.bars, "--out", self.out)

    def tearDown(self):
        shutil.rmtree(self.d)

    def verdict(self):
        return json.loads(self.out.read_text())

    def test_prereg_then_run_discovers_the_sidecar(self):
        self.assertEqual(cli("prereg", "--bars", self.bars)[0], 0)
        code, out, _ = cli(*self.run_args)
        # mutant: the sidecar is only read when --prereg names it -> NOT_REGISTERED -> red
        self.assertEqual((code, self.verdict()["prereg"]["status"]), (0, "HASH_MATCH"))
        self.assertEqual(out.splitlines()[-1], "gates: pass · 1/2 measured")
        self.assertEqual(cli("prereg", "--bars", self.bars)[0], 2)                # never overwrites a sidecar

    def test_one_edited_byte_refuses_with_both_hashes(self):
        cli("prereg", "--bars", self.bars)
        registered = json.loads((self.d / "bars.yaml.prereg.json").read_text())["bars_sha256"]
        self.bars.write_text(BARS.replace("18.6", "18.5", 1))
        code, _, _ = cli(*self.run_args)
        v = self.verdict()
        self.assertEqual((code, v["prereg"]["status"], v["results"]), (2, "MISMATCH", []))   # mutant: hashes not compared -> red
        self.assertTrue(registered in v["refusal"] and v["bars"]["sha256"] in v["refusal"])

    def test_a_pinned_log_hash_refuses_another_log_and_reads_post_hoc(self):
        cli("prereg", "--bars", self.bars, "--log", self.log)
        self.assertEqual(cli(*self.run_args)[1].splitlines()[-1], "gates: pass · 1/2 measured (post-hoc)")
        other = write_synthetic_log(self.d / "g.bin", flight_rows(seconds=29))
        self.assertEqual(cli("run", "--log", other, "--bars", self.bars, "--out", self.out)[0], 2)   # mutant: pin ignored -> red
        self.assertEqual((self.verdict()["prereg"]["status"], "no log shopping" in self.verdict()["refusal"]), ("LOG_MISMATCH", True))

    def test_every_refusal_exits_2_with_its_reason(self):
        (self.d / "zero.yaml").write_text("schema: swathkeeper-bars/1.0\ncontract: swathkeeper-flightlog/1.0\nbars: []\n")
        hidden = self.d / "no_extra" / "pymavlink"
        hidden.mkdir(parents=True)
        (hidden / "__init__.py").write_text("raise ImportError('hidden by the test')\n")
        (self.d / "x.ulg").write_bytes(b"ULog\x01\x12\x35\x01" + bytes(64))
        no_extra = {**ENV, "PYTHONPATH": f"{hidden.parent}{os.pathsep}{ENV['PYTHONPATH']}"}
        for args, env, why in ((("run", "--log", self.log, "--bars", self.d / "zero.yaml", "--out", self.out), ENV, "at least 1"),
                               (self.run_args, no_extra, "pip install 'swathkeeper-gates[ardupilot]'"),  # mutant: ImportError uncaught
                               (("run", "--log", self.d / "nope.bin", "--bars", self.bars, "--out", self.out), ENV, "log not found"),
                               (("run", "--log", self.log, "--bars", self.bars, "--out", self.d / "no" / "v.json"), ENV,
                                "cannot write --out"),                   # mutant: the write failure returns the verdict's code
                               (("inspect", "--log", self.d / "x.ulg"), ENV, "px4 adapter is not shipped")):
            with self.subTest(why=why):
                code, _, err = cli(*args, env=env)
                self.assertEqual(code, 2)
                self.assertIn(why, err)

    def test_inspect_prints_the_absent_map_and_no_parser_spam(self):
        rows = [(n, {**v, "Status": 1} if n == "GPS" and v["I"] == 1 else v) for n, v in flight_rows() if n != "BAT"]
        log = write_synthetic_log(self.d / "nobat.bin", rows)          # and GPS instance 1 never has a 3D fix
        raw = bytearray(log.read_bytes())
        raw[len(raw) // 2:len(raw) // 2 + 4000] = bytes(4000)
        log.write_bytes(bytes(raw))
        code, out, err = cli("inspect", "--log", log)
        # mutants: DFReader's per-byte prints (G250); streams_map trips on an EMPTY instance's t_s (G256) -> red
        self.assertEqual((code, err), (0, ""))
        v = json.loads(out)
        self.assertEqual((v["streams"].get("battery", {}).get("state"), set(v["streams"]["ekf"]["instances"])), ("ABSENT", {"0", "1"}))
        self.assertEqual((len(v["integrity"]["holes"]), v["streams"]["velocity"]["instances"]["1"]["n"]), (1, 0))


class TestImportWall(unittest.TestCase):
    def test_no_import_crosses_the_two_packages_in_either_direction(self):
        scanned = 0
        for pkg, other in (("swathkeeper_gates", "fieldguard_planning"), ("fieldguard_planning", "swathkeeper_gates")):
            for f in sorted((REPO_ROOT / "src" / pkg).rglob("*.py")):
                scanned += 1
                for node in ast.walk(ast.parse(f.read_text())):
                    names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                             [node.module or ""] if isinstance(node, ast.ImportFrom) else
                             [node.value] if isinstance(node, ast.Constant) and isinstance(node.value, str) else [])
                    # mutants: `import fieldguard_planning`, importlib.import_module("fieldguard_planning.geom"),
                    # __import__("fieldguard_planning") in a gates module (G252) -> red
                    self.assertFalse([n for n in names if re.fullmatch(rf"{other}(\.\w+)*", n)], f"{f} imports {other}")
        self.assertGreater(scanned, 20)          # the scan saw both packages (vacuity guard)

    def test_a_run_loads_no_fieldguard_planning_module(self):
        # G263: the scan above matches whole strings only ("fieldguard_" + "planning" survives it); this sees what loads
        code = ("import sys; from swathkeeper_gates import cli; cli.main(['run', '--log', sys.argv[1], '--bars', sys.argv[2], "
                "'--out', sys.argv[3]]); print(sorted(m for m in sys.modules if m.startswith('fieldguard_planning')))")
        with tempfile.TemporaryDirectory() as d:
            log, bars = write_synthetic_log(Path(d) / "f.bin", flight_rows()), Path(d) / "b.yaml"
            bars.write_text(BARS)
            p = subprocess.run([sys.executable, "-c", code, str(log), str(bars), str(Path(d) / "v.json")],
                               capture_output=True, text=True, env=ENV, cwd=REPO_ROOT, timeout=120)
        self.assertEqual(p.stdout.splitlines()[-1:], ["[]"])   # mutant: importlib.import_module("fieldguard_" + "planning")


if __name__ == "__main__":
    unittest.main()
