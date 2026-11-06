"""`swathkeeper-gates inspect | prereg | run` (design §7). No network.

Exit 0 and 1 are verdicts and 2 is a refusal (§5). An unexpected error is 2 as well, never 1: a crash is
not a FAIL. Its traceback still goes to stderr, and `run` still writes the refusal JSON.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import sys
import traceback
from importlib import metadata
from pathlib import Path

from . import CONTRACT, __version__, adapters, allowlist
from . import bars as B
from . import verdict as V
from .contract import TICK_S, Refusal, streams_map

PREREG = "swathkeeper-prereg/1.0"
SHA = B.string(re.compile(r"[0-9a-f]{64}"), "a sha256 hex digest")
SIDECAR = {"schema": (PREREG,), "bars_sha256": SHA, "tool_version": B.STR, "written_utc": B.STR, "log_sha256?": SHA}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _need(path):
    if not os.path.isfile(path):
        raise Refusal(f"log not found: {path}")
    return path


def _tool(log=None):
    deps = {"PyYAML": metadata.version("PyYAML"), **(log.meta["parser"] if log else {})}
    return {"version": __version__, "python": platform.python_version(), "deps": deps}


def _source(path, log, sha):
    m = log.meta
    return {"path": Path(path).name, "sha256": sha, "size_bytes": os.path.getsize(path), "format": m["format"],
            "adapter": m["adapter"], "vehicle": m["vehicle"], "firmware": m["firmware"], "hardware": m["hardware"],
            "absent": m["absent"], "duration_s": round(log.t1 - TICK_S - log.t0, 6),
            "records_decoded": m["records_decoded"], "record_counts": m["counts"], "log_gpst_start": m["log_gpst_start"]}


def cmd_inspect(a):
    log = adapters.load(_need(a.log))
    sys.stdout.write(V.dumps({"source": _source(a.log, log, _sha(a.log)), "integrity": log.integrity,
                              "streams": streams_map(log)}))
    return 0


def cmd_prereg(a):
    _, sha = B.load_bars(a.bars)          # an invalid bars file is never registered
    doc = {"schema": PREREG, "bars_sha256": sha, "tool_version": __version__,
           "written_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if a.log:
        doc["log_sha256"] = _sha(_need(a.log))
    side = a.bars + ".prereg.json"
    try:
        with open(side, "x") as f:
            f.write(json.dumps(doc, indent=1) + "\n")
    except FileExistsError:
        raise Refusal(f"{side} exists: prereg never overwrites a sidecar") from None
    except OSError as e:
        raise Refusal(f"cannot write {side}: {e}") from None
    print(f"registered {Path(a.bars).name} sha256 {sha}"
          + (f", pinned to log sha256 {doc['log_sha256']} (post-hoc)" if a.log else "") + f" -> {Path(side).name}")
    return 0


def _unique(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate key in {keys}")
    return dict(pairs)


def _prereg(a, v, bars_sha, log_sha):
    """§4. `<bars>.prereg.json` is discovered beside the bars file; --prereg names another. `status` is
    NOT_REGISTERED, HASH_MATCH, or one of three refusals: MALFORMED (the sidecar), MISMATCH (bars hash) and
    LOG_MISMATCH (the pinned log hash, G248). The block is in `v` before any refusal, so it prints both hashes."""
    side = Path(a.prereg or a.bars + ".prereg.json")
    v["prereg"] = p = {"status": "NOT_REGISTERED", "sidecar": None, "sidecar_sha256": None, "bars_sha256": bars_sha,
                       "bars_sha256_registered": None, "log_sha256_pinned": None, "post_hoc": False,
                       "written_utc_untrusted": None}
    if not side.is_file():
        if a.prereg:
            raise Refusal(f"--prereg {a.prereg}: no such file")
        return
    raw = side.read_bytes()
    try:
        doc = B.check(json.loads(raw, object_pairs_hook=_unique), SIDECAR, "sidecar")
    except (ValueError, Refusal) as e:
        p["status"] = "MALFORMED"
        raise Refusal(f"malformed sidecar {side.name}: {e}") from None
    p.update(sidecar=side.name, sidecar_sha256=hashlib.sha256(raw).hexdigest(), bars_sha256_registered=doc["bars_sha256"],
             log_sha256_pinned=doc.get("log_sha256"), written_utc_untrusted=doc["written_utc"])
    if doc["bars_sha256"] != bars_sha:
        p["status"] = "MISMATCH"
        raise Refusal(f"prereg MISMATCH: {side.name} registered bars sha256 {doc['bars_sha256']}; "
                      f"the bars file is {bars_sha}")
    p["status"] = "HASH_MATCH"
    if p["log_sha256_pinned"] and p["log_sha256_pinned"] != log_sha:
        p["status"] = "LOG_MISMATCH"
        raise Refusal(f"the sidecar pins log sha256 {p['log_sha256_pinned']}; this log is {log_sha} (§4: no log shopping)")
    p["post_hoc"] = bool(p["log_sha256_pinned"])


def cmd_run(a):
    v = V.new(CONTRACT, _tool())
    try:
        log_sha = _sha(_need(a.log))
        bars, bars_sha = B.load_bars(a.bars)
        v["bars"] = {"path": Path(a.bars).name, "sha256": bars_sha, "schema": B.SCHEMA}
        _prereg(a, v, bars_sha, log_sha)
        declared, dsha = allowlist.load(a.declared, bars) if a.declared else ([], None)
        log = adapters.load(a.log)
        v.update(tool=_tool(log), source=_source(a.log, log, log_sha), integrity=log.integrity, streams=streams_map(log))
        B.check_modes(bars, log)
        v["results"] = B.evaluate(bars, log)
        today = dt.datetime.now(dt.timezone.utc).date()
        v["allowlist"] = {"path": a.declared and Path(a.declared).name, "sha256": dsha,
                          **allowlist.compare(v["results"], declared, today)}
    except Exception as e:                # noqa: BLE001 -- every failure to judge is a refusal (exit 2), never a 1
        if not isinstance(e, Refusal):
            traceback.print_exc()
        v["refusal"] = str(e) if isinstance(e, Refusal) else f"internal error, no verdict: {type(e).__name__}: {e}"
        v["results"] = []
    v["exit_code"], v["badge"] = V.outcome(v["results"], v["allowlist"], v["prereg"], v["refusal"])
    try:
        Path(a.out).write_text(V.dumps(v))
    except OSError as e:
        print(f"swathkeeper-gates: cannot write --out {a.out}: {e}", file=sys.stderr)
        return 2
    for r in v["results"]:
        print(f"  {r['verdict']:<22} {r['severity']:<6} {r['id']:<20} n={r['n']:<9} measured={r['measured']}")
    if v["refusal"]:
        print(f"swathkeeper-gates: refused: {v['refusal']}", file=sys.stderr)
    print(v["badge"])
    return v["exit_code"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swathkeeper-gates", description="Pre-registered evidence gates over a "
                                 "flight log. Exit 0 pass, 1 fail or could not tell, 2 refused.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inspect", help="print the source, integrity and streams blocks").add_argument("--log", required=True)
    p = sub.add_parser("prereg", help="hash a bars file before the run (writes <bars>.prereg.json)")
    p.add_argument("--bars", required=True)
    p.add_argument("--log", help="pin the log's sha256 too: the verdict then says (post-hoc)")
    p = sub.add_parser("run", help="judge a log against bars; writes the JSON verdict to --out")
    for flag in ("--log", "--bars", "--out"):
        p.add_argument(flag, required=True)
    p.add_argument("--declared", help="swathkeeper-declared/1.0 YAML naming the acknowledged reds")
    p.add_argument("--prereg", help="a sidecar elsewhere than <bars>.prereg.json")
    a = ap.parse_args(argv)
    try:
        return {"inspect": cmd_inspect, "prereg": cmd_prereg, "run": cmd_run}[a.cmd](a)
    except Refusal as e:
        print(f"swathkeeper-gates: refused: {e}", file=sys.stderr)
        return 2
    except Exception:                     # noqa: BLE001 -- see the module docstring
        traceback.print_exc()
        print("swathkeeper-gates: internal error, no verdict (exit 2)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
