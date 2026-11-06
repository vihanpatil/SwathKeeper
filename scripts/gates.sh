#!/usr/bin/env bash
# scripts/gates.sh -- every HOST-SIDE CI gate, run locally, each scored against its EXPECTED state.
#
# Mirrors .github/workflows/ci.yml's `validate-config`, `planning-and-eval`, `gates-tool` (its 3.12 leg;
# the 3.10 leg runs only in CI) and `docs-site` jobs: the same commands in the same order (the `pip
# install` steps run as `uv pip install` into the pinned .venv, which has no pip). Every step runs
# regardless of earlier failures, as CI's `if: always()` does. Not mirrored: actions/upload-artifact
# (not a gate), the two `uses: ./.github/actions/swathkeeper-gates` steps (a composite action needs
# the runner; tests/test_ci_evidence_gate.py runs its run.sh instead) and `build-test-sim`
# (manual-dispatch, needs the GHCR image). The gates-tool reproduction row FETCHES ~7 MB (three public
# logs, by sha256) and is the one row here that needs the network. Rows CI lacks: the tests:src cap
# (ADR-022 am. 1) and a check that the gate outputs left the tree as they found it.
#
# Expected states: every step PASS except the two DECLARED reds --
#   * the host-side suite fails on EXACTLY test_step_passes_on_the_committed_evidence
#     (tests/test_ci_evidence_gate.py), and
#   * check_live_flight_log.py over the committed logs exits 1 with EXACTLY the 2026-08-25 take INVALID.
# The KNOWN_RED allowlist step is expected PASS: it is what proves the failing set is the declared one.
# Exit 0 iff every row matches its expected state; else 1, with the mismatches and their log paths.
# A mismatch is never "fixed" here by moving an expectation -- that is a reviewed diff with an ADR.
#
# Logs: ${TMPDIR:-/tmp}/swathkeeper_gates/<step>.log. Runtime: minutes, mostly the planning suite
# (suite totals have one home: tests/README.md).
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 2

if [ ! -x "$REPO_ROOT/.venv/bin/python" ]; then
  echo "[gates] REFUSED: $REPO_ROOT/.venv/bin/python is missing. /usr/bin/python3 on this Mac is the" >&2
  echo "        Xcode stub, so the gates need the pinned venv. Create it:" >&2
  echo "          uv venv --python /opt/homebrew/bin/python3.12 .venv" >&2
  echo "          uv pip install --python .venv/bin/python -r requirements-eval.txt pyyaml pytest" >&2
  exit 2
fi
export PATH="$REPO_ROOT/.venv/bin:$PATH"

LOG_DIR="${TMPDIR:-/tmp}"; LOG_DIR="${LOG_DIR%/}/swathkeeper_gates"
mkdir -p "$LOG_DIR" || exit 2
RATIO_CAP="3.70"
DECLARED_HOST_RED="test_step_passes_on_the_committed_evidence"
DECLARED_INVALID_LOG="live_flight_log_20260825T210402Z.json"
# Outputs the steps below write inside the repo; each must be gitignored before we run its writer.
SPIKE_OUTPUTS="sim/spike/out/spike_seed42 eval/results/spike_scores.json eval/results/ground_truth.json eval/results/overlays eval/results/detections_ndvi.json eval/results/detections_rgb.json"
DOCS_OUTPUTS="docs-site"
# Tree areas the gates could write into (concurrent doc edits in .claude/, docs/, *README.md are not ours).
TREE_SCOPE="eval sim src config tests scripts dashboard docs-site examples .github"

# pip install -> uv pip install into the venv (uv venvs ship no pip); python -m pip as a fallback.
pip_install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$REPO_ROOT/.venv/bin/python" "$@"
  else
    python -m pip install "$@"
  fi
}

# --- the CI steps, verbatim bodies (each runs in a subshell under set -euo pipefail, as in CI) -------
# validate-config
s_validate_deps()   { pip_install pyyaml; }
s_validate()        { python scripts/validate_agents.py; }
# planning-and-eval
s_eval_deps()       { pip_install -r requirements-eval.txt; }
s_planning_suite()  { python3 -m unittest discover -s tests/fieldguard_planning -v; }
s_host_suite()      { python3 -m unittest discover -s tests -p 'test_*.py' -v; }
s_known_red() {
  if [ ! -f tests/test_known_red_allowlist.py ]; then
    echo "[ci] FAIL: tests/test_known_red_allowlist.py is gone. This step would have" >&2
    echo "     matched no tests and passed, having asserted nothing about which tests" >&2
    echo "     fail. Restore it or delete this step deliberately." >&2
    exit 1
  fi
  python3 -m unittest discover -s tests -p 'test_known_red_allowlist.py' -v
}
s_scenarios() {
  python3 eval/scenarios/generate_flight_logs.py
  git diff --exit-code eval/scenarios/
}
s_live_logs() {
  shopt -s nullglob
  logs=(eval/results/*flight_log*.json)
  echo "[ci] committed live flight logs matched: ${#logs[@]}"
  if [ "${#logs[@]}" -eq 0 ]; then
    echo "[ci] FAIL: the live flight-log evidence gate matched 0 files. Either the committed" >&2
    echo "     evidence was renamed/deleted or .gitignore stopped re-including" >&2
    echo "     eval/results/live_flight_log_*.json. A gate that validates nothing is not a" >&2
    echo "     gate -- restore the evidence or delete this step deliberately." >&2
    exit 1
  fi
  python3 scripts/check_live_flight_log.py "${logs[@]}"
}
s_generators() {
  python3 scripts/gen_boustrophedon.py -o /tmp/smoke_boustrophedon.waypoints
  python3 scripts/gen_farm_world.py \
    --obstacles-out /tmp/smoke_static_obstacles.json \
    --world-out /tmp/smoke_farm_world.sdf
  python3 scripts/check_mission_geofence.py --help > /dev/null
}
s_geofence()        { python3 scripts/check_mission_geofence.py; }
s_spike_clip()      { python3 sim/spike/gen_spike_clip.py --seed 42 --out sim/spike/out/spike_seed42; }
s_spike_harness()   { bash eval/run_spike.sh; }
s_spike_regress()   { python3 scripts/check_spike_regression.py eval/results/spike_scores.json; }
# gates-tool (ci.yml, ADR-023 am. 1) -- the 3.12 leg, on the host venv
PYTHON_LEG="$(python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"; export PYTHON_LEG
s_gates_install()   { pip_install -e '.[ardupilot]'; swathkeeper-gates --help > /dev/null; }
s_gates_tests()     { python3 -m unittest discover -s tests -p 'test_gates_*.py' -v; }
s_gates_examples() {
  shopt -s nullglob
  sources=(examples/*/SOURCE.json)
  dirs=(examples/*/)
  echo "[ci] committed gate examples matched: ${#sources[@]} (example dirs: ${#dirs[@]})"
  if [ "${#sources[@]}" -ne 3 ]; then
    echo "[ci] FAIL: expected exactly 3 examples/*/SOURCE.json (the pinned public logs), found ${#sources[@]}." >&2
    echo "     This gate may not score green while reproducing fewer verdicts than are committed." >&2
    exit 1
  fi
  if [ "${#dirs[@]}" -ne "${#sources[@]}" ]; then
    echo "[ci] FAIL: ${#dirs[@]} example dirs but ${#sources[@]} SOURCE.json files -- an example without a pinned" >&2
    echo "     log is a verdict nobody can re-fetch (design §8); add its SOURCE.json or remove the dir." >&2
    exit 1
  fi
  fetched="$(mktemp -d)"
  for src in "${sources[@]}"; do
    name="$(basename "$(dirname "$src")")"
    url="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["url"])' "$src")"
    # saved under the url's own (unquoted) basename, so the verdict's source.path diffs like every other leaf
    base="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.unquote(sys.argv[1].rsplit("/", 1)[-1]))' "$url")"
    mkdir -p "$fetched/$name"
    echo "[ci] fetching $name <- $url"
    curl -fsSL --proto '=https' --proto-redir '=https' --retry 3 --retry-delay 5 -o "$fetched/$name/$base" "$url"
  done
  python3 scripts/check_gates_examples.py --fetched "$fetched" --python-leg "${PYTHON_LEG:-}" "${sources[@]%/SOURCE.json}"
}
# docs-site
s_docs_deps()       { pip_install -r requirements-eval.txt; }
s_docs_build()      { python3 scripts/build_docs_site.py; }

# --- bookkeeping (bash 3.2: parallel indexed arrays) ---------------------------------------------
ROW_GATE=(); ROW_RESULT=(); ROW_EXPECT=(); ROW_OK=(); ROW_NOTE=()
add_row() { # gate result expected ok(1/0) note
  ROW_GATE+=("$1"); ROW_RESULT+=("$2"); ROW_EXPECT+=("$3"); ROW_OK+=("$4"); ROW_NOTE+=("$5")
}
STEP_N=0
STEP_TOTAL=20

# run_step KEY LABEL FN -> sets RC, LOG
run_step() {
  STEP_N=$((STEP_N + 1))
  LOG="$LOG_DIR/$1.log"
  printf '[gates] %2d/%d %-58s ' "$STEP_N" "$STEP_TOTAL" "$2 ..."
  local t0; t0=$(date +%s)
  ( set -euo pipefail; "$3" ) > "$LOG" 2>&1
  RC=$?
  echo "exit $RC ($(( $(date +%s) - t0 )) s)"
}

# score a step whose expectation is a plain PASS
expect_pass() { # key label fn
  run_step "$1" "$2" "$3"
  if [ "$RC" -eq 0 ]; then add_row "$2" "PASS" "PASS" 1 ""
  else add_row "$2" "FAIL (exit $RC)" "PASS" 0 "$LOG"; fi
}

# refuse to run a writer whose outputs are not gitignored (it would dirty the tree)
ignored_or_refuse() { # label paths...
  local label="$1"; shift; local p bad=""
  for p in "$@"; do git check-ignore -q "$p" || bad="$bad $p"; done
  if [ -n "$bad" ]; then
    STEP_N=$((STEP_N + 1))
    echo "[gates] $STEP_N/$STEP_TOTAL $label -- REFUSED: not gitignored:$bad"
    add_row "$label" "REFUSED (would dirty tree:$bad)" "PASS" 0 "outputs not gitignored:$bad"
    return 1
  fi
  return 0
}

tree_snapshot() { git status --porcelain --untracked-files=all -- $TREE_SCOPE ':(exclude)**/README.md' 2>/dev/null; }

echo "[gates] SwathKeeper host-side gates -- repo $REPO_ROOT, python $(python --version 2>&1), logs $LOG_DIR"
TREE_BEFORE="$(tree_snapshot)"
SCEN_PREDIRTY=0
git diff --quiet -- eval/scenarios/ || SCEN_PREDIRTY=1

# ===== job: validate-config ======================================================================
expect_pass validate_deps   "validate-config: install pyyaml"                      s_validate_deps
expect_pass validate_agents "validate-config: validate_agents.py"                  s_validate

# ===== job: planning-and-eval ====================================================================
expect_pass eval_deps       "planning: install requirements-eval.txt"              s_eval_deps
expect_pass planning_suite  "planning: planning test suite"                        s_planning_suite

# host-side suite: expected FAIL on exactly the declared test
run_step host_suite "planning: host-side suite (tests/test_*.py)" s_host_suite
failed="$(grep -E '^(FAIL|ERROR): ' "$LOG" | sed -E 's/^(FAIL|ERROR): ([^ ]+).*/\2/' | sort -u | tr '\n' ' ')"
failed="${failed% }"
if [ "$RC" -ne 0 ] && [ "$failed" = "$DECLARED_HOST_RED" ]; then
  add_row "planning: host-side suite (tests/test_*.py)" "FAIL (only $DECLARED_HOST_RED)" "FAIL (declared red)" 1 ""
elif [ "$RC" -eq 0 ]; then
  add_row "planning: host-side suite (tests/test_*.py)" "PASS" "FAIL (declared red)" 0 \
    "the declared red PASSED -- re-read runbook 6a before touching the allowlist; $LOG"
else
  add_row "planning: host-side suite (tests/test_*.py)" "FAIL (exit $RC: ${failed:-no FAIL/ERROR lines})" \
    "FAIL (declared red)" 0 "UNDECLARED failing set: $failed; $LOG"
fi

expect_pass known_red       "planning: KNOWN_RED allowlist = declared reds" s_known_red

# scenario regenerate + diff (CI semantics; on failure leave the diff for the human)
run_step scenarios "planning: scenario logs regenerate + diff" s_scenarios
if [ "$RC" -eq 0 ]; then
  add_row "planning: scenario logs regenerate + diff" "PASS" "PASS" 1 ""
else
  echo "[gates]      eval/scenarios/ differs after regeneration (diff left in place):"
  git diff --stat -- eval/scenarios/ | sed 's/^/[gates]        /'
  note="$LOG"
  [ "$SCEN_PREDIRTY" -eq 1 ] && note="eval/scenarios/ was ALREADY dirty before this run -- the diff may not be the generator's; $LOG"
  add_row "planning: scenario logs regenerate + diff" "FAIL (exit $RC)" "PASS" 0 "$note"
fi

# committed live flight-log evidence: expected exit 1 with exactly the 2026-08-25 take INVALID
run_step live_logs "planning: committed live flight-log evidence" s_live_logs
invalid="$(grep -E '^\[check_live_flight_log\] INVALID: ' "$LOG" | sed -E 's#.*/##' | sort -u | tr '\n' ' ')"
invalid="${invalid% }"
nlogs="$(sed -n 's/^\[ci\] committed live flight logs matched: //p' "$LOG")"
if [ "$RC" -eq 1 ] && [ "$invalid" = "$DECLARED_INVALID_LOG" ]; then
  add_row "planning: committed live flight-log evidence" "FAIL (exit 1; ${nlogs:-?} logs, only 2026-08-25 INVALID)" \
    "FAIL (declared red)" 1 ""
else
  add_row "planning: committed live flight-log evidence" "exit $RC (INVALID: ${invalid:-none}; ${nlogs:-?} logs)" \
    "FAIL (declared red)" 0 "expected exit 1 with only $DECLARED_INVALID_LOG INVALID; $LOG"
fi

expect_pass generators      "planning: smoke-run stdlib generators"                 s_generators
expect_pass geofence        "planning: mission vs tree geofence (3D)"               s_geofence

if ignored_or_refuse "planning: regenerate spike clip (seed 42)" sim/spike/out/spike_seed42; then
  expect_pass spike_clip    "planning: regenerate spike clip (seed 42)"             s_spike_clip
fi
# shellcheck disable=SC2086
if ignored_or_refuse "planning: eval spike harness end-to-end" $SPIKE_OUTPUTS; then
  expect_pass spike_harness "planning: eval spike harness end-to-end"               s_spike_harness
fi
expect_pass spike_regress   "planning: seed-42 headline metric no regression"      s_spike_regress

# ===== job: gates-tool (3.12 leg) ================================================================
expect_pass gates_install   "gates-tool: install .[ardupilot]"                     s_gates_install
expect_pass gates_tests     "gates-tool: unit tests (tests/test_gates_*.py)"       s_gates_tests
run_step gates_examples "gates-tool: 3 pinned logs re-fetched by sha256 + verdicts diffed" s_gates_examples
if [ "$RC" -eq 0 ]; then
  add_row "gates-tool: 3 pinned logs re-fetched by sha256 + verdicts diffed" "PASS" "PASS" 1 ""
elif grep -q "^curl: " "$LOG"; then
  add_row "gates-tool: 3 pinned logs re-fetched by sha256 + verdicts diffed" "FAIL (exit $RC: fetch)" "PASS" 0 \
    "a fetch failed (offline, or an upstream URL moved -- a moved pin is a finding, not a flake); $LOG"
else
  add_row "gates-tool: 3 pinned logs re-fetched by sha256 + verdicts diffed" "FAIL (exit $RC)" "PASS" 0 \
    "a committed verdict did NOT reproduce, or a sha256 mismatched -- read the log before touching examples/; $LOG"
fi

# ===== job: docs-site ============================================================================
expect_pass docs_deps       "docs-site: install requirements-eval.txt"             s_docs_deps
if ignored_or_refuse "docs-site: build (links + heading parity)" $DOCS_OUTPUTS; then
  expect_pass docs_build    "docs-site: build (links + heading parity)"            s_docs_build
fi

# ===== rows CI lacks =============================================================================
STEP_N=$((STEP_N + 1))
echo "[gates] $STEP_N/$STEP_TOTAL tests:src ratio vs $RATIO_CAP cap"
src_n="$(find src -type f -name '*.py' -print0 | xargs -0 cat | wc -l | tr -d ' ')"  # src/**/*.py since ADR-022 am. 4
tst_n="$(find tests -type f \( -name '*.py' -o -name '*.sh' \) -print0 | xargs -0 cat | wc -l | tr -d ' ')"
ratio="$(awk -v t="$tst_n" -v s="$src_n" 'BEGIN { printf "%.2f", t / s }')"
if awk -v r="$ratio" -v c="$RATIO_CAP" 'BEGIN { exit !(r + 0 <= c + 0) }'; then
  add_row "tests:src ratio (ADR-022 am. 1)" "$ratio ($tst_n/$src_n)" "<= $RATIO_CAP" 1 ""
else
  add_row "tests:src ratio (ADR-022 am. 1)" "OVER: $ratio ($tst_n/$src_n)" "<= $RATIO_CAP" 0 \
    "OVER the cap -- every new test file must retire one; the cap is not re-baselined"
fi

STEP_N=$((STEP_N + 1))
echo "[gates] $STEP_N/$STEP_TOTAL gate outputs left the tree untouched"
TREE_AFTER="$(tree_snapshot)"
if [ "$TREE_BEFORE" = "$TREE_AFTER" ]; then
  add_row "tree untouched by gate outputs" "PASS" "PASS" 1 ""
else
  changed="$(diff <(printf '%s\n' "$TREE_BEFORE") <(printf '%s\n' "$TREE_AFTER") | sed -n 's/^> //p' | tr '\n' ';')"
  add_row "tree untouched by gate outputs" "CHANGED" "PASS" 0 \
    "new/changed under ($TREE_SCOPE) during the run (a gate wrote it, or a concurrent edit): ${changed% ;}"
fi

# ===== table =====================================================================================
w=10
i=0; while [ $i -lt ${#ROW_GATE[@]} ]; do [ ${#ROW_GATE[$i]} -gt $w ] && w=${#ROW_GATE[$i]}; i=$((i + 1)); done
rw=6
i=0; while [ $i -lt ${#ROW_RESULT[@]} ]; do [ ${#ROW_RESULT[$i]} -gt $rw ] && rw=${#ROW_RESULT[$i]}; i=$((i + 1)); done
echo
printf '%-*s | %-*s | %s\n' "$w" "gate" "$rw" "result" "expected"
printf '%s\n' "$(printf '%*s' $((w + rw + 26)) '' | tr ' ' '-')"
mism=0
i=0
while [ $i -lt ${#ROW_GATE[@]} ]; do
  mark=""; [ "${ROW_OK[$i]}" = 1 ] || { mark="   <-- MISMATCH"; mism=$((mism + 1)); }
  printf '%-*s | %-*s | %s%s\n' "$w" "${ROW_GATE[$i]}" "$rw" "${ROW_RESULT[$i]}" "${ROW_EXPECT[$i]}" "$mark"
  i=$((i + 1))
done
echo
if [ "$mism" -eq 0 ]; then
  echo "[gates] ALL ${#ROW_GATE[@]} rows in their expected state (the two declared reds included). exit 0"
  echo "[gates] host-side mirror only: build-test-sim and the Linux runner itself are not exercised here."
  exit 0
fi
echo "[gates] $mism MISMATCH(ES):"
i=0
while [ $i -lt ${#ROW_GATE[@]} ]; do
  [ "${ROW_OK[$i]}" = 1 ] || echo "  - ${ROW_GATE[$i]}: got '${ROW_RESULT[$i]}', expected '${ROW_EXPECT[$i]}' -- ${ROW_NOTE[$i]}"
  i=$((i + 1))
done
exit 1
