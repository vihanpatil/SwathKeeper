#!/usr/bin/env python3
"""Do the committed example verdicts REPRODUCE on freshly fetched copies of their logs? (ADR-023 am. 1, option C step 5)

    python3 scripts/check_gates_examples.py --fetched "$dir" examples/tarot_x4 examples/plane_nofix ...

`$dir/<name>/<basename>` is the log that ci.yml's `gates-tool` job just fetched with `curl -fL` from
`examples/<name>/SOURCE.json`'s url into a fresh temp dir, saved under the url's own unquoted basename so the
verdict's `source.path` diffs like every other leaf (this script NEVER fetches; design §8: no third-party log
is committed, and a unit test never downloads). For each example directory, in this order, every step printed:

  1. SOURCE.json's url must be a commit-pinned https://raw.githubusercontent.com/<owner>/<repo>/<40-hex sha>/ path
     (a branch, a short sha or another host is a FAIL: the pin is the fixture), and across the examples the pinned
     sha256s must be distinct (two dirs holding one log would count as two reproductions);
  2. the fetched bytes must hash to SOURCE.json's sha256 at its size_bytes -- any mismatch is a hard FAIL that
     prints both hashes, and the tool is NOT run on those bytes;
  3. SOURCE.json, the pinned sidecar `bars.yaml.prereg.json` and the committed verdict must name the SAME log
     sha256; the sidecar's bars_sha256, the verdict's `bars.sha256` and `prereg.bars_sha256_registered` must all be
     sha256(bars.yaml), and the verdict's `prereg.sidecar_sha256` must be sha256(the committed sidecar) -- so an
     edited bars file with a re-registered sidecar (QA G267) fails HERE, by name, before any run;
  4. `swathkeeper-gates run` (the console script on PATH, as a stranger would run it) judges the fetched log
     against the committed bars.yaml, its exit code captured as a VALUE (1 is the correct verdict on two of the
     three logs); a refusal is a FAIL, and the fresh verdict must read prereg HASH_MATCH, post_hoc, `(post-hoc)`;
  5. the committed verdict.json must be BYTE-IDENTICAL to the canonical serialisation (`json.dumps(indent=1)`
     + newline, the tool's own) of the fresh run -- every result's verdict, n and measured value, every bar
     limit, the integrity block, the streams map, the badge, the exit code (QA G266: the pre-registered
     `results[*].{verdict,n}` diff let 337 of 363 Tarot leaves drift unseen), and the FILE itself: a duplicate
     key, a smuggled path-shaped key, `1418.0` for `1418`, `false` for `0`, a deleted empty container all
     survive a parsed-JSON comparison and none survives bytes (QA G277). A leaf-by-leaf diff is printed first
     so a drift is named. Exactly three leaves are EXCLUDED, because they differ by construction between the
     committing host and a CI leg, and each must still be PRESENT on both sides and match a fixed shape:
     `tool.python` (3.10 and 3.12 both run), `tool.deps.PyYAML` (a range pin, not an instrument -- design §1)
     and `allowlist.run_date_utc`. SOURCE.json and the sidecar are read refusing duplicate keys, and all three
     committed JSON files must be in canonical form;
  6. if `badge.svg` is committed beside the verdict, a fresh render of the FRESH badge must equal it byte for byte.

Denominator first: the number of example directories is printed and zero is a FAIL. Exit 0 iff every example
reproduces; 1 on any FAIL; 2 when it could not judge at all (no --fetched dir, tool not on PATH). stdlib only.
It imports nothing from `swathkeeper_gates` (the tool is exercised through its CLI, which is the contract) and
nothing from `fieldguard_planning` (ADR-023: the two packages never meet).
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import urllib.parse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_gates_badge import render_svg  # noqa: E402

TAG = "[gates-examples]"
BADGE_LABELS = {"tarot_x4": "tarot_x4 · public log"}   # the README badge; other examples carry no SVG today
PINNED_URL = re.compile(r"^https://raw\.githubusercontent\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[0-9a-f]{40}/[^?#]+$")  # ASCII owner/repo (G285)
# leaf -> (why it may differ, the shape BOTH values must still have). Printed on every run, never diffed; a value
# that is absent or off-shape is a FAIL (QA G278: an excluded leaf is not a free-text slot; G283: the shape is the
# contract's own -- a matrix leg, the PyYAML pin, a real date that is today).
EXCLUDED = {
    "tool.python": ("the interpreter -- the job runs 3.10 and 3.12", re.compile(r"^3\.(10|12)\.\d{1,3}$")),
    "tool.deps.PyYAML": ("a range pin >=6.0.3,<7, not an instrument (design §1)", re.compile(r"^6\.\d{1,3}(\.\d{1,3})?$")),
    "allowlist.run_date_utc": ("today", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
}
ABSENT = object()
# What a verdict word must mean for each kind's `measured` (the tool's own semantics, bars.py): a PASS whose number
# sits on the wrong side of its own bar is a self-contradicting result -- the one artifact a byte-identical
# reproduction cannot see, a buggy tool committed together with its regenerated verdicts (QA G284).
def _consistent(kind, bar, measured):
    """-> True iff `measured` satisfies the bar (PASS-side); False iff it violates it; None if not judgeable here."""
    if not isinstance(measured, (int, float)) or isinstance(measured, bool):
        return None
    if kind == "series_bound":
        if bar.get("bound") == "floor":
            return measured >= bar["limit"]
        if bar.get("bound") == "ceiling":
            return measured <= bar["limit"]
        return None
    if kind == "gnss_quality":
        return measured <= bar.get("max_outage_s", 0)
    if kind == "containment":
        return measured >= 0
    if kind in ("mode_transitions", "no_events"):
        return measured == 0
    return None


def excluded_ok(key, cv, fv, python_leg, today):
    """The extra meaning each excluded leaf carries beyond its regex (G283). -> None if fine, else the reason."""
    if key == "tool.python" and python_leg and not fv.startswith(python_leg + "."):
        return f"the fresh run reports python {fv!r} but this job's matrix leg is {python_leg!r}"
    if key == "tool.deps.PyYAML":
        for v in (cv, fv):
            if not (6, 0, 3) <= tuple(int(x) for x in v.split(".")) < (7,):
                return f"PyYAML {v!r} is outside the pin >=6.0.3,<7"
    if key == "allowlist.run_date_utc":
        try:
            c, f = dt.date.fromisoformat(cv), dt.date.fromisoformat(fv)
        except ValueError as e:
            return f"not a date: {e}"
        if not c <= f:
            return f"the committed run date {cv} is AFTER the fresh one {fv}"
        if f != today:
            return f"the fresh run date {fv} is not today ({today.isoformat()} UTC)"
    return None


def url_is_pinned(url) -> bool:
    """A commit-pinned https raw.githubusercontent.com path: no `..`/`%2e` (curl normalises `<sha>/../main/x` to a
    branch path, QA G279), no query, no fragment, no empty segment."""
    return (isinstance(url, str) and bool(PINNED_URL.match(url)) and ".." not in url and "%2e" not in url.lower()
            and "//" not in url[len("https://"):])


def url_basename(url: str) -> str:
    return urllib.parse.unquote(url.rsplit("/", 1)[-1])


def _unique(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate key in {sorted(k for k in keys if keys.count(k) > 1)}")
    return dict(pairs)


def canonical(obj) -> str:
    """The tool's own serialisation (swathkeeper_gates.verdict.dumps): indent 1, ASCII, no NaN, one trailing newline."""
    return json.dumps(obj, indent=1, allow_nan=False) + "\n"


def load_canonical(path: Path):
    """(text, object) of a committed JSON file that refuses duplicate keys and must be in canonical form, or raise.
    Read as BYTES and decoded: `read_text()` would translate CRLF / CR to LF and make "byte-identical" a lie (G282)."""
    text = path.read_bytes().decode("utf-8")
    obj = json.loads(text, object_pairs_hook=_unique)
    if text != canonical(obj):
        raise ValueError(f"{path.name} is not in canonical form (json.dumps indent=1 + newline): re-serialise it, do not hand-edit")
    return text, obj


def set_leaf(obj, dotted: str, value):
    cur = obj
    *parents, last = dotted.split(".")
    for k in parents:
        cur = cur[k]
    cur[last] = value


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def short(sha) -> str:
    return f"{sha[:8]}…{sha[-4:]}" if isinstance(sha, str) and len(sha) == 64 else repr(sha)


def leaves(obj, prefix=""):
    """Every scalar in a JSON document as (dotted path, value); list items as [i]. An EMPTY container is a leaf too
    (`<[]>` / `<{}>`), so a dropped `holes: []` or a `[]` turned `{}` is named, not just caught by the bytes."""
    if isinstance(obj, dict):
        if not obj:
            yield prefix, "<{}>"
        for k, v in obj.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        if not obj:
            yield prefix, "<[]>"
        for i, v in enumerate(obj):
            yield from leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def leaf_diff(committed, fresh):
    """[(path, committed value, fresh value)] over the union of leaves, excluding EXCLUDED. Absent is a difference."""
    a, b = dict(leaves(committed)), dict(leaves(fresh))
    return [(k, a.get(k, ABSENT), b.get(k, ABSENT)) for k in sorted(set(a) | set(b))
            if k not in EXCLUDED and a.get(k, ABSENT) != b.get(k, ABSENT)]


def _val(v):
    return "<absent>" if v is ABSENT else repr(v)


def _result_id(verdict, path):
    m = re.match(r"results\[(\d+)\]", path)
    if m:
        try:
            return f" (bar {verdict['results'][int(m.group(1))]['id']!r})"
        except (KeyError, IndexError, TypeError):
            pass
    return ""


def check_example(example: Path, fetched_dir: Path, tool: str, log, python_leg="") -> bool:
    """One example directory. Prints every finding under `name:`; returns True iff it reproduces."""
    name = example.name
    ok = True

    def fail(msg):
        nonlocal ok
        ok = False
        log(f"{TAG} FAIL {name}: {msg}")

    try:
        _, source = load_canonical(example / "SOURCE.json")
        sidecar_bytes = (example / "bars.yaml.prereg.json").read_bytes()
        _, sidecar = load_canonical(example / "bars.yaml.prereg.json")
        committed_text, committed = load_canonical(example / "verdict.json")
        bars_bytes = (example / "bars.yaml").read_bytes()
    except (OSError, ValueError) as e:
        fail(f"cannot read the committed example: {e}")
        return False

    # 1. the pin itself
    url = source.get("url")
    if not url_is_pinned(url):
        fail(f"SOURCE.json url is not a commit-pinned raw.githubusercontent.com path (40-hex sha, https, no .., ?, #): {url!r}")
        return False

    # 2. the fetched bytes: one file, under the url's own basename, in this example's sub-dir
    sub = fetched_dir / name
    files = sorted(p for p in sub.iterdir() if p.is_file()) if sub.is_dir() else []
    if len(files) != 1 or files[0].name != url_basename(url):
        fail(f"expected exactly one fetched file named {url_basename(url)!r} under {sub}, found {[p.name for p in files]} "
             f"(the fetch step did not deliver this example's bytes as the step promises)")
        return False
    fetched = files[0]
    got, size = sha256_of(fetched), fetched.stat().st_size
    if got != source.get("sha256") or size != source.get("size_bytes"):
        fail(f"fetched bytes do NOT match SOURCE.json -- sha256 fetched {got} ({size} B) vs pinned "
             f"{source.get('sha256')} ({source.get('size_bytes')} B) from {url}. Not judged.")
        return False
    log(f"{TAG} {name}: fetched {size} B, sha256 {short(got)} == SOURCE.json")

    # 3. the pins agree with each other, and with the committed verdict (G267)
    pinned_log = {"SOURCE.json": source.get("sha256"), "sidecar log_sha256": sidecar.get("log_sha256"),
                  "verdict.json source.sha256": (committed.get("source") or {}).get("sha256")}
    if len(set(pinned_log.values())) != 1:
        fail("the committed pins disagree about WHICH log this is: " + ", ".join(f"{k} {short(v)}" for k, v in pinned_log.items()))
    bars_sha = hashlib.sha256(bars_bytes).hexdigest()
    vprereg = committed.get("prereg") or {}
    pinned_bars = {"sha256(bars.yaml)": bars_sha, "sidecar bars_sha256": sidecar.get("bars_sha256"),
                   "verdict.json bars.sha256": (committed.get("bars") or {}).get("sha256"),
                   "verdict.json prereg.bars_sha256_registered": vprereg.get("bars_sha256_registered")}
    if len(set(pinned_bars.values())) != 1:
        fail("the committed bars.yaml is not the one the verdict was judged under (an edit + a re-registered sidecar "
             "is exactly this): " + ", ".join(f"{k} {short(v)}" for k, v in pinned_bars.items()))
    side_sha = hashlib.sha256(sidecar_bytes).hexdigest()
    if vprereg.get("sidecar_sha256") != side_sha:
        fail(f"the committed sidecar (sha256 {short(side_sha)}) is not the one the verdict recorded "
             f"({short(vprereg.get('sidecar_sha256'))}): the sidecar was re-registered after the verdict")
    if not ok:
        return False
    log(f"{TAG} {name}: SOURCE.json, sidecar and verdict agree -- log {short(got)}, bars {short(bars_sha)}, sidecar {short(side_sha)}; "
        f"committed exit {committed.get('exit_code')} '{committed.get('badge')}' by python {(committed.get('tool') or {}).get('python')} "
        f"deps {(committed.get('tool') or {}).get('deps')}")

    # 4. the fresh run
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "verdict.json"
        proc = subprocess.run([tool, "run", f"--log={fetched}", f"--bars={example / 'bars.yaml'}", f"--out={out}"],
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
    log(f"{TAG} {name}: {Path(tool).name} exit {rc}, badge '{fresh.get('badge')}', python {(fresh.get('tool') or {}).get('python')} "
        f"deps {(fresh.get('tool') or {}).get('deps')}")
    if fresh.get("refusal"):
        fail(f"the fresh run REFUSED: {fresh['refusal']}")
    prereg = fresh.get("prereg") or {}
    if prereg.get("status") != "HASH_MATCH" or not prereg.get("post_hoc") or not str(fresh.get("badge", "")).endswith("(post-hoc)"):
        fail(f"the fresh run did not bind to the pinned sidecar: prereg {prereg.get('status')}, post_hoc {prereg.get('post_hoc')}, "
             f"badge '{fresh.get('badge')}' (expected HASH_MATCH, post_hoc, '… (post-hoc)')")
    if rc != committed.get("exit_code"):
        fail(f"the PROCESS exited {rc} but the committed verdict says exit_code {committed.get('exit_code')} "
             f"(the CLI's exit is part of the contract, not only the JSON)")
    for r in fresh.get("results") or []:
        if r.get("verdict") in ("PASS", "FAIL"):
            ok_side = _consistent(r.get("kind"), r.get("bar") or {}, r.get("measured"))
            if ok_side is not None and ok_side != (r["verdict"] == "PASS"):
                fail(f"result {r.get('id')!r} ({r.get('kind')}) reads {r['verdict']} with measured={r.get('measured')!r} against "
                     f"bar {r.get('bar')}: the number CONTRADICTS the word -- a tool bug committed with its own verdicts (QA G284)")

    # 5. the whole verdict: leaf by leaf (to NAME a drift), then byte for byte (so nothing hides between the leaves)
    a, b = dict(leaves(committed)), dict(leaves(fresh))
    as_committed = copy.deepcopy(fresh)
    today = dt.datetime.now(dt.timezone.utc).date()
    for k, (why, shape) in EXCLUDED.items():
        cv, fv = a.get(k, ABSENT), b.get(k, ABSENT)
        if not all(isinstance(v, str) and shape.match(v) for v in (cv, fv)):
            fail(f"{k}: committed {_val(cv)} / fresh {_val(fv)} -- an excluded leaf must be present on both sides and "
                 f"match {shape.pattern!r}; it is not a free-text slot")
            continue
        reason = excluded_ok(k, cv, fv, python_leg, today)
        if reason:
            fail(f"{k}: committed {_val(cv)} / fresh {_val(fv)} -- {reason}")
            continue
        set_leaf(as_committed, k, cv)
        log(f"{TAG} {name}: not diffed -- {k} committed {_val(cv)} / fresh {_val(fv)} ({why})")
    diffs = leaf_diff(committed, fresh)
    for path, cv, fv in diffs:
        fail(f"{path}{_result_id(committed, path)}: committed {_val(cv)} -> fresh {_val(fv)}")
    try:
        want = canonical(as_committed)
    except ValueError as e:
        fail(f"the fresh verdict cannot be serialised canonically (a non-finite number?): {e}")
        return False
    if committed_text != want:
        cl, wl = committed_text.splitlines(), want.splitlines()
        i = next((i for i in range(max(len(cl), len(wl))) if i >= len(cl) or i >= len(wl) or cl[i] != wl[i]), None)
        fail(f"verdict.json is NOT byte-identical to the canonical serialisation of the fresh run"
             + ("" if diffs else " although every parsed leaf agrees: a duplicate key, a smuggled path-shaped key, a float "
                "for an int, false for 0, or a dropped empty container (QA G277)")
             + f" -- first difference at line {i + 1}: committed {cl[i] if i < len(cl) else '<end>'!r} vs fresh "
               f"{wl[i] if i < len(wl) else '<end>'!r}")
    elif not diffs:
        results = committed.get("results") or []
        log(f"{TAG} {name}: {len(committed_text.encode())} bytes / {len(a)} leaves identical ({len(EXCLUDED)} excluded, shape-checked) -- "
            + ", ".join(f"{r.get('id')} {r.get('verdict')} n={r.get('n')} measured={r.get('measured')}" for r in results))

    # 6. the committed badge, if any
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
    ap.add_argument("--python-leg", default="", help="the CI matrix leg, e.g. 3.10: the fresh verdict's tool.python must be on it")
    a = ap.parse_args(argv)
    log = print
    if a.python_leg:
        log(f"{TAG} matrix leg {a.python_leg}: the fresh tool.python must start with it")
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
    # the pinned logs must be distinct files (G271): two dirs over one log are one reproduction, not two
    shas = {}
    for e in examples:
        try:
            shas.setdefault(load_canonical(e / "SOURCE.json")[1].get("sha256"), []).append(e.name)
        except (OSError, ValueError) as err:
            log(f"{TAG} FAIL {e.name}: cannot read SOURCE.json: {err}", file=sys.stderr)
            return 1
    dupes = {s: n for s, n in shas.items() if len(n) > 1}
    if dupes:
        log(f"{TAG} FAIL: the same pinned log sha256 under more than one example dir: {dupes}", file=sys.stderr)
        return 1
    results = {e.name: check_example(e, fetched, tool, log, a.python_leg) for e in examples}
    good = sum(results.values())
    if good == len(results):
        log(f"{TAG} {good}/{len(results)} examples reproduce their committed verdict, every byte. exit 0")
        return 0
    log(f"{TAG} {good}/{len(results)} examples reproduce; FAILED: {[n for n, r in results.items() if not r]}. exit 1", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
