"""The declared-red allowlist `swathkeeper-declared/1.0` (design §6): this repo's KNOWN_RED rule, generalised.

The set {(bar, verdict)} of reds must EQUAL the set of live declarations: a red nobody declared is
`undeclared`, a declaration nothing matches is `vacuous`, and an entry on or past its `expires` date
declares nothing (its red counts as undeclared). A typo can never turn a run green: every malformed
entry is a refusal.
"""
import datetime as dt
import hashlib

from .bars import EI, FAIL, NA, STR, check, load_yaml
from .contract import Refusal

SCHEMA = "swathkeeper-declared/1.0"


def _date(v, where):
    if type(v) is not dt.date:               # a datetime is a date subclass; a quoted string is not one
        raise Refusal(f"{where}: {v!r} is not a YAML date (YYYY-MM-DD, unquoted)")


DOC = {"schema": (SCHEMA,), "declared": [{"bar": STR, "verdict": (FAIL, EI, NA), "reason": STR,
                                          "expires": _date}, 0]}     # a declared PASS refuses here


def load(path, bars):
    """-> (entries, sha256). Refuses whatever could never match a red (§5)."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise Refusal(f"cannot read the declared file: {e}") from None
    entries, severity = check(load_yaml(raw, "declared"), DOC, "declared file")["declared"], {b["id"]: b["severity"] for b in bars}
    for i, e in enumerate(entries):
        if e["bar"] not in severity:
            raise Refusal(f"declared[{i}]: names no bar ({e['bar']!r})")
        if [x["bar"] for x in entries].count(e["bar"]) > 1:
            raise Refusal(f"declared[{i}]: a second declaration for bar {e['bar']!r}")
        if e["verdict"] != FAIL and severity[e["bar"]] == "should":
            raise Refusal(f"declared[{i}]: {e['verdict']} on the should bar {e['bar']!r} is never red")
    return entries, hashlib.sha256(raw).hexdigest()


def compare(results, declared, run_date):
    """The exact-set comparison. `run_date` is printed, so the same inputs later can give a new verdict."""
    red = {(r["id"], r["verdict"]) for r in results
           if r["verdict"] == FAIL or (r["verdict"] in (EI, NA) and r["severity"] == "must")}
    live = {(e["bar"], e["verdict"]) for e in declared if run_date < e["expires"]}
    return {"run_date_utc": run_date.isoformat(),
            "declared": [{**e, "expires": e["expires"].isoformat()} for e in declared],
            "red": sorted(map(list, red)), "matched": sorted(map(list, red & live)),
            "undeclared": sorted(map(list, red - live)), "vacuous": sorted(map(list, live - red)),
            "expired": sorted([e["bar"], e["verdict"]] for e in declared if run_date >= e["expires"])}
