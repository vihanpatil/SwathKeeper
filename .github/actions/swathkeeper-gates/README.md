# `swathkeeper-gates` — the GitHub Action

Runs [`swathkeeper-gates`](../../../src/swathkeeper_gates/) (`run --log … --bars … --out …`) on a flight log and a
YAML file of bars in your workspace, writes the JSON verdict, exposes the badge string and the exit code as outputs,
and **fails the step exactly when the tool does**: exit 1 (`fail`, or `could not tell`) and exit 2 (`refused`).
Nothing in the Action softens that. The design is `docs/design/GATES_TOOL_DESIGN.md`; the record is ADR-023 and
its amendment 1 in `docs/DECISIONS.md`.

```yaml
- uses: actions/checkout@v4          # your repo: the log and the bars live here
- uses: vihanpatil/SwathKeeper/.github/actions/swathkeeper-gates@main   # pin a SHA for a stable tool version
  id: gates
  with:
    log: flights/2026-11-05.bin      # ArduPilot DataFlash
    bars: flights/bars.yaml          # swathkeeper-bars/1.0; register it FIRST: swathkeeper-gates prereg --bars … --log …
    out: verdict.json                # default
    # declared: flights/declared.yaml   # the acknowledged reds, exact set, each with an expiry
- run: echo "${{ steps.gates.outputs.badge }} (exit ${{ steps.gates.outputs.exit-code }})"
  if: always()                       # outputs are written before the step exits, so they survive a red
```

| Output | Meaning |
|---|---|
| `exit-code` | the tool's exit code, verbatim: `0` pass, `1` fail or could not tell, `2` refused |
| `badge` | the verdict's badge string, e.g. `gates: could not tell · 7/8 measured (post-hoc)`; `gates: refused` on exit 2 |
| `verdict` | the path of the JSON verdict (the `out` input) |

**Two runner facts to know.** The Action runs `actions/setup-python` for `python-version` (default 3.12), so a job that already
set up a different Python sees it change for later steps — pass the same version. GitHub does not enforce a composite input's
`required: true`; `run.sh` checks `log`, `bars` and `out` itself and refuses (exit 2, outputs written) when one is empty.

**What it does not claim.** A green step means *this* log (by sha256, in the verdict) met every bar in *these*
bars (by sha256) that could be measured, under the parser versions the verdict records. It fetches nothing: the
caller provides the log and the bars. It is not a flight-safety assessment of any vehicle. A badge that reads
`(unregistered)` means no `<bars>.prereg.json` sidecar was found beside the bars — the bars could have been
written after the result was known — and `(post-hoc)` means the sidecar also pins the log, so the bars necessarily
postdate the flight. Both are printed on purpose. The tool itself has run on exactly the three public logs in
`examples/` and on no other vehicle or format; `could not tell` is a fourth word and never scores green.
