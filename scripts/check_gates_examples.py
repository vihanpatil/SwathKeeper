#!/usr/bin/env python3
"""Do the committed example verdicts REPRODUCE on freshly fetched copies of their logs? (ADR-023 am. 1, option C step 5)

    python3 scripts/check_gates_examples.py --fetched "$dir" examples/tarot_x4 examples/plane_nofix ...

`$dir/<name>.bin` is the log that ci.yml's `gates-tool` job just fetched with `curl -fL` from
`examples/<name>/SOURCE.json`'s url into a fresh temp dir (this script NEVER fetches; design §8: no third-party
log is committed, and a unit test never downloads). For each example directory, in this order, every step printed:

  1. the fetched bytes must hash to SOURCE.json's sha256 at its size_bytes -- any mismatch is a hard FAIL that
     prints both hashes, and the tool is NOT run on those bytes;
  2. SOURCE.json, the pinned sidecar `bars.yaml.prereg.json` and the committed verdict must name the SAME log
     sha256, and the sidecar's bars_sha256 must be sha256(bars.yaml) -- so the fresh run can only read
     HASH_MATCH (post-hoc); a sidecar re-registered after the fact fails here, not silently as NOT_REGISTERED;
  3. `swathkeeper-gates run` (the console script on PATH, as a stranger would run it) judges the fetched log
     against the committed bars.yaml, its exit code captured as a VALUE (1 is the correct verdict on two of the
     three logs), and the fresh verdict must read prereg HASH_MATCH, post_hoc, badge `(post-hoc)`;
  4. results[*].{id, verdict, n}, badge and exit_code are diffed against the committed verdict.json -- the
     pre-registered diff (design §9), so a `should` bar sliding PASS -> EVIDENCE_INSUFFICIENT is a red, not a
     footnote. A `measured` value that moved while verdict and n held is PRINTED as drift and not gated;
  5. if `badge.svg` is committed beside the verdict, a fresh render of the FRESH badge must equal it byte for byte.

Denominator first: the number of example directories is printed and zero is a FAIL. Exit 0 iff every example
reproduces; 1 on any FAIL; 2 when it could not judge at all (no --fetched dir, tool not on PATH). stdlib only.
It imports nothing from `swathkeeper_gates` (the tool is exercised through its CLI, which is the contract) and
nothing from `fieldguard_planning` (ADR-023: the two packages never meet).
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_gates_badge import render_svg  # noqa: E402

TAG = "[gates-examples]"
BADGE_LABELS = {"tarot_x4": "tarot_x4 · public log"}   # the README badge; other examples carry no SVG today


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def short(sha: str) -> str:
    return f"{sha[:8]}…{sha[-4:]}" if len(sha) == 64 else repr(sha)


def key(verdict: dict):
    return [(r.get("id"), r.get("verdict"), r.get("n")) for r in verdict.get("results", [])]


def check_example(example: Path, fetched_dir: Path, tool: str, log) -> bool:
    """One example directory. Prints every finding under `name:`; returns True iff it reproduces."""
    name = example.name
    ok = True

    def fail(msg):
        nonlocal ok
        ok = False
        log(f"{TAG} FAIL {name}: {msg}")

    try:
        source = json.loads((example / "SOURCE.json").read_text())
        sidecar = json.loads((example / "bars.yaml.prereg.json").read_text())
        committed = json.loads((example / "verdict.json").read_text())
        bars_bytes = (example / "bars.yaml").read_bytes()
    except (OSError, ValueError) as e:
        fail(f"cannot read the committed example: {e}")
        return False

    # 1. the fetched bytes
    fetched = fetched_dir / f"{name}.bin"
    if not fetched.is_file():
        fail(f"no fetched log at {fetched} (the fetch step did not deliver this example's bytes)")
        return False
    got, size = sha256_of(fetched), fetched.stat().st_size
    if got != source.get("sha256") or size != source.get("size_bytes"):
        fail(f"fetched bytes do NOT match SOURCE.json -- sha256 fetched {got} ({size} B) vs pinned "
             f"{source.get('sha256')} ({source.get('size_bytes')} B) from {source.get('url')}. Not judged.")
        return False
    log(f"{TAG} {name}: fetched {size} B, sha256 {short(got)} == SOURCE.json")

    # 2. the three pins agree, and the sidecar binds this bars.yaml
    pinned = {"SOURCE.json": source.get("sha256"), "sidecar log_sha256": sidecar.get("log_sha256"),
              "verdict.json source.sha256": (committed.get("source") or {}).get("sha256")}
    if len(set(pinned.values())) != 1:
        fail("the committed pins disagree about WHICH log this is: " + ", ".join(f"{k} {short(v or '')}" for k, v in pinned.items()))
    bars_sha = hashlib.sha256(bars_bytes).hexdigest()
    if sidecar.get("bars_sha256") != bars_sha:
        fail(f"the sidecar registered bars sha256 {short(sidecar.get('bars_sha256') or '')} but bars.yaml is {short(bars_sha)} "
             f"-- the run would refuse (prereg MISMATCH); re-registering silently is not an option here")
    if not ok:
        return False
    log(f"{TAG} {name}: sidecar binds bars {short(bars_sha)} and log {short(got)}; committed verdict exit {committed.get('exit_code')} "
        f"'{committed.get('badge')}' by python {committed.get('tool', {}).get('python')} "
        f"deps {committed.get('tool', {}).get('deps')}")

    # 3. the fresh run
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "verdict.json"
        proc = subprocess.run([tool, "run", "--log", str(fetched), "--bars", str(example / "bars.yaml"), "--out", str(out)],
                              capture_output=True, text=True)
        if not out.is_file():
            fail(f"{tool} exit {proc.returncode} wrote no verdict to --out.\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
            return False
        try:
            fresh = json.loads(out.read_text())
        except ValueError as e:
            fail(f"the fresh verdict is not JSON: {e}")
            return False
    rc = proc.returncode
    log(f"{TAG} {name}: {Path(tool).name} exit {rc}, badge '{fresh.get('badge')}', python {fresh.get('tool', {}).get('python')} "
        f"deps {fresh.get('tool', {}).get('deps')}")
    if fresh.get("refusal"):
        fail(f"the fresh run REFUSED: {fresh['refusal']}")
    prereg = fresh.get("prereg") or {}
    if prereg.get("status") != "HASH_MATCH" or not prereg.get("post_hoc") or not str(fresh.get("badge", "")).endswith("(post-hoc)"):
        fail(f"the fresh run did not bind to the pinned sidecar: prereg {prereg.get('status')}, post_hoc {prereg.get('post_hoc')}, "
             f"badge '{fresh.get('badge')}' (expected HASH_MATCH, post_hoc, '… (post-hoc)')")

    # 4. the pre-registered diff
    if rc != committed.get("exit_code") or fresh.get("exit_code") != committed.get("exit_code"):
        fail(f"exit code: process {rc} / verdict {fresh.get('exit_code')} vs committed {committed.get('exit_code')}")
    if fresh.get("badge") != committed.get("badge"):
        fail(f"badge: fresh '{fresh.get('badge')}' vs committed '{committed.get('badge')}'")
    fk, ck = key(fresh), key(committed)
    if len(fk) != len(ck):
        fail(f"{len(fk)} results fresh vs {len(ck)} committed: {[i for i, _, _ in fk]} vs {[i for i, _, _ in ck]}")
    for f, c in zip(fk, ck):
        if f != c:
            fail(f"result {c[0]!r}: committed {c[1]} n={c[2]} -> fresh {f[0]!r} {f[1]} n={f[2]}")
    for f, c in zip(fresh.get("results", []), committed.get("results", [])):
        if f.get("id") == c.get("id") and (f.get("verdict"), f.get("n")) == (c.get("verdict"), c.get("n")) \
                and f.get("measured") != c.get("measured"):
            log(f"{TAG} DRIFT {name}: {c['id']} measured committed {c.get('measured')} -> fresh {f.get('measured')} "
                f"(verdict and n unchanged; not gated -- the pre-registered diff is results[*].{{verdict,n}})")
    if ok:
        log(f"{TAG} {name}: {len(ck)}/{len(ck)} results identical -- "
            + ", ".join(f"{i} {v} n={n}" for i, v, n in ck))

    # 5. the committed badge, if any
    svg = example / "badge.svg"
    if svg.is_file():
        want = render_svg(BADGE_LABELS.get(name, "swathkeeper-gates"), str(fresh.get("badge")))
        if svg.read_text() != want:
            fail(f"badge.svg differs from a fresh render of the fresh badge '{fresh.get('badge')}' -- regenerate with "
                 f"scripts/render_gates_badge.py, do not edit the SVG")
        else:
            log(f"{TAG} {name}: badge.svg re-rendered identical ({len(want)} bytes)")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetched", required=True, help="directory holding <name>.bin for each example, fetched by the caller")
    ap.add_argument("examples", nargs="*", help="example directories (each with SOURCE.json, bars.yaml, its sidecar, verdict.json)")
    a = ap.parse_args(argv)
    log = print
    examples = [Path(e.rstrip("/")) for e in a.examples]
    log(f"{TAG} committed example dirs: {len(examples)}")
    if not examples:
        log(f"{TAG} FAIL: zero example directories -- this gate would reproduce nothing and may not score green", file=sys.stderr)
        return 1
    fetched = Path(a.fetched)
    if not fetched.is_dir():
        log(f"{TAG} REFUSED: --fetched {fetched} is not a directory", file=sys.stderr)
        return 2
    tool = shutil.which("swathkeeper-gates")
    if not tool:
        log(f"{TAG} REFUSED: `swathkeeper-gates` is not on PATH -- pip install -e '.[ardupilot]' first", file=sys.stderr)
        return 2
    results = {e.name: check_example(e, fetched, tool, log) for e in examples}
    good = sum(results.values())
    if good == len(results):
        log(f"{TAG} {good}/{len(results)} examples reproduce their committed verdict. exit 0")
        return 0
    log(f"{TAG} {good}/{len(results)} examples reproduce; FAILED: {[n for n, r in results.items() if not r]}. exit 1", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
