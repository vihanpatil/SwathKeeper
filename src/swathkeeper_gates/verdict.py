"""The verdict `swathkeeper-verdict/1.0`: its exit code and its badge (design §5).

Paths are recorded by BASENAME only (`source.path`, `bars.path`, `allowlist.path`): a committed verdict
must not carry the host's directory layout, and the sha256 beside each name is what identifies the file.
"""
import json

from .bars import EI, FAIL, NA, PASS

SCHEMA = "swathkeeper-verdict/1.0"


def outcome(results, allow, prereg, refusal):
    """-> (exit code, badge). The §5 table, top to bottom."""
    if refusal:
        return 2, "gates: refused"
    undeclared = allow["undeclared"]
    if any(v == FAIL for _, v in undeclared) or allow["vacuous"] or allow["expired"]:
        code, word = 1, "fail"
    elif undeclared or not any(r["verdict"] == PASS and r["severity"] == "must" for r in results):   # G241
        code, word = 1, "could not tell"
    else:
        code, word = 0, "pass"
    badge = f"gates: {word} · {sum(r['verdict'] in (PASS, FAIL) for r in results)}/{len(results)} measured"
    matched = [v for _, v in allow["matched"]]
    if matched:
        na = f", {matched.count(NA)} NA" if NA in matched else ""
        badge += f" · {len(matched)} declared ({matched.count(FAIL)} FAIL, {matched.count(EI)} EI{na})"
    if prereg and prereg["post_hoc"]:
        badge += " (post-hoc)"
    elif prereg and prereg["status"] == "NOT_REGISTERED":
        badge += " (unregistered)"
    return code, badge


def dumps(verdict):
    """Strict JSON: no non-finite float can reach a verdict (the adapter drops non-finite PARM values and every
    kind excludes NaN/inf samples), and one that did would be an internal error, exit 2, never an invalid token."""
    return json.dumps(verdict, indent=1, allow_nan=False) + "\n"


def new(contract, tool):
    """Every §5 key, present from the start, so a refusal's JSON has the same shape as a verdict's."""
    keys = ("source", "integrity", "streams", "bars", "prereg", "allowlist", "exit_code", "badge", "refusal")
    return {"schema": SCHEMA, "contract": contract, "tool": tool, **dict.fromkeys(keys), "results": []}
