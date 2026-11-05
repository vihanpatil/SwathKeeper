#!/usr/bin/env bash
# scripts/state.sh -- the one-screen "where are we" brief for SwathKeeper.
#
# Intended as a Claude Code SessionStart hook and as the `/standup` skill's injected context, and
# for a human opening a terminal: branch + divergence, open PRs with their CI rollup (UNDECLARED reds
# shouted), main's last CI run, Pages, Docker, host python, the outreach count, the tests:src cap and
# the ROADMAP's own "Where we are" date. Pure bash (3.2-safe: no assoc arrays, no mapfile), no
# python, read-only. Every section degrades to "unavailable (<why>)" instead of failing; only the
# gh/curl sections need the network, and each external call is time-boxed so the whole brief stays
# under ~10 s. Run from anywhere: it resolves the repo from its own location.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || { echo "state: cannot cd to repo root"; exit 0; }

PAGES_URL="https://vihanpatil.github.io/SwathKeeper/dashboard/"
DECLARED_RED_JOB="Planning tests + eval spike harness (numpy/scipy)"   # declared reds live inside it
RATIO_CAP="3.70"

# run_t SECS CMD... -- run CMD with a wall-clock cap (macOS has no `timeout`). stdout/stderr pass
# through; the watchdog's own fds go to /dev/null so a $(...) capture never waits on it.
run_t() {
  local t="$1"; shift
  "$@" &
  local pid=$!
  ( sleep "$t"; kill "$pid" 2>/dev/null ) >/dev/null 2>&1 &
  local wd=$!
  wait "$pid"; local rc=$?
  kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
  return "$rc"
}

have() { command -v "$1" >/dev/null 2>&1; }

echo "== SwathKeeper state ($(date '+%Y-%m-%d %H:%M %Z')) =="

# --- git ------------------------------------------------------------------------------------------
if have git && git rev-parse --git-dir >/dev/null 2>&1; then
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
  head="$(git log -1 --format='%h %cd' --date=short 2>/dev/null)"
  dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  if up="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
    set -- $(git rev-list --left-right --count "$up...HEAD" 2>/dev/null)
    div="vs $up: +${2:-?} ahead / -${1:-?} behind"
  elif git rev-parse --verify -q origin/main >/dev/null; then
    set -- $(git rev-list --left-right --count "origin/main...HEAD" 2>/dev/null)
    div="NO UPSTREAM (unpushed); vs origin/main: +${2:-?} / -${1:-?}"
  else
    div="no upstream, no origin/main"
  fi
  echo "git:     $branch @ $head | $div | dirty files: $dirty"
  mainref=""
  for r in origin/main main; do git rev-parse --verify -q "$r" >/dev/null && { mainref="$r"; break; }; done
  if [ -n "$mainref" ]; then
    ct="$(git log -1 --format=%ct "$mainref" 2>/dev/null)"
    echo "main:    last commit $(git log -1 --format='%h %cd' --date=short "$mainref") ($(( ( $(date +%s) - ct ) / 86400 )) days ago, $mainref)"
  else
    echo "main:    unavailable (no main ref)"
  fi
else
  echo "git:     unavailable (not a git checkout or git missing)"
fi

# --- GitHub: open PRs + CI rollup, main's last run --------------------------------------------------
if ! have gh; then
  echo "PRs:     unavailable (gh not installed)"
  echo "CI main: unavailable (gh not installed)"
else
  prs="$(run_t 5 gh pr list --state open --json number,title,headRefName \
           --jq '.[] | "\(.number)\t\(.headRefName)\t\(.title)"' 2>/dev/null)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "PRs:     unavailable (gh pr list failed or timed out: offline / unauthenticated?)"
  elif [ -z "$prs" ]; then
    echo "PRs:     none open"
  else
    echo "PRs:"
    while IFS="$(printf '\t')" read -r num headref title; do
      [ -n "$num" ] || continue
      # one line per (job, conclusion); runs = the Actions run ids those jobs came from
      roll="$(run_t 4 gh pr view "$num" --json statusCheckRollup --jq \
        '.statusCheckRollup[] | "\(.name)\t\(.conclusion // .status)\t\(.detailsUrl // "" | capture("runs/(?<r>[0-9]+)").r // "")"' \
        2>/dev/null)" || { echo "  #$num $headref -- CI rollup unavailable (gh pr view failed)"; continue; }
      summary=""; undeclared=""; runs=""
      jobs="$(printf '%s\n' "$roll" | cut -f1,2 | sort -u)"
      while IFS="$(printf '\t')" read -r jname jconc; do
        [ -n "$jname" ] || continue
        case "$jname" in
          "Validate tiger-team config"*) short="validate";;
          "Planning tests"*)             short="planning";;
          "Docs site"*)                  short="docs";;
          "Headless Gazebo"*)            short="sim-smoke";;
          *)                             short="$jname";;
        esac
        case "$jconc" in
          FAILURE|CANCELLED|TIMED_OUT|ACTION_REQUIRED|STARTUP_FAILURE)
            if [ "$jname" = "$DECLARED_RED_JOB" ]; then
              summary="$summary $short=FAIL(declared)"
            else
              summary="$summary $short=$jconc"; undeclared="$undeclared $short"
            fi;;
          *) summary="$summary $short=$jconc";;
        esac
      done <<EOF
$jobs
EOF
      runs="$(printf '%s\n' "$roll" | cut -f3 | grep -E '^[0-9]+$' | sort -u | tr '\n' ' ')"
      [ -n "$summary" ] || summary=" no checks reported"
      echo "  #$num $headref:$summary"
      [ -n "$undeclared" ] && echo "    !!! UNDECLARED RED JOB(S):$undeclared -- NOT the declared planning red !!!"
      [ -n "$runs" ] && echo "    step detail: gh run view <id> (runs: ${runs% })"
    done <<EOF
$prs
EOF
  fi
  last="$(run_t 5 gh run list --branch main --workflow ci.yml --limit 1 \
            --json conclusion,status,createdAt,databaseId \
            --jq '.[0] | "\(.conclusion // .status) \(.createdAt[0:10]) run \(.databaseId)"' 2>/dev/null)"
  if [ -n "$last" ] && [ "$last" != "null" ]; then
    echo "CI main: $last (planning job red is declared; step detail: gh run view <id>)"
  else
    echo "CI main: unavailable (gh run list failed or timed out)"
  fi
fi

# --- Pages ------------------------------------------------------------------------------------------
if have curl; then
  code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$PAGES_URL" 2>/dev/null)"
  case "$code" in
    200) echo "Pages:   200 OK $PAGES_URL";;
    000|"") echo "Pages:   unavailable (no response in 5 s: offline?)";;
    *) echo "Pages:   HTTP $code (NOT 200) $PAGES_URL";;
  esac
else
  echo "Pages:   unavailable (curl missing)"
fi

# --- Docker -----------------------------------------------------------------------------------------
if ! have docker; then
  echo "Docker:  unavailable (docker CLI missing)"
elif ! run_t 4 docker info >/dev/null 2>&1; then
  echo "Docker:  unavailable (daemon not running / not reachable)"
else
  cst="$(run_t 4 docker ps -a --filter 'name=^/?fieldguard-sim$' --format '{{.Status}}' 2>/dev/null | head -1)"
  imgs="$(run_t 4 docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep 'fieldguard-sim' | head -3 | tr '\n' ' ')"
  echo "Docker:  container fieldguard-sim: ${cst:-absent} | image: ${imgs:-none matching fieldguard-sim*}"
fi

# --- host python ------------------------------------------------------------------------------------
if [ -x .venv/bin/python ]; then
  venv="$(run_t 3 .venv/bin/python --version 2>&1 | head -1)"
  venv=".venv/bin/python ${venv:-version unknown}"
else
  venv=".venv/bin/python MISSING (uv venv --python /opt/homebrew/bin/python3.12 .venv)"
fi
if out="$(run_t 3 python3 -c 'print(1)' 2>/dev/null)" && [ "$out" = "1" ]; then
  bare="ok ($(command -v python3))"
else
  bare="BROKEN ($(command -v python3 || echo 'not on PATH'); put .venv/bin on PATH)"
fi
echo "python:  $venv | bare python3: $bare"

# --- outreach (gitignored, private) ----------------------------------------------------------------
if [ -f docs/outreach/TRACKER.md ]; then
  line="$(grep -m1 'Running count' docs/outreach/TRACKER.md | sed -e 's/\*\*//g' -e 's/^[[:space:]-]*//')"
  echo "outreach: ${line:-unavailable (no 'Running count' line in TRACKER.md)}"
else
  echo "outreach: unavailable (docs/outreach/TRACKER.md absent)"
fi

# --- tests:src ratio --------------------------------------------------------------------------------
src_n="$(cat src/fieldguard_planning/*.py 2>/dev/null | wc -l | tr -d ' ')"
tst_n="$(find tests -type f \( -name '*.py' -o -name '*.sh' \) -print0 2>/dev/null | xargs -0 cat 2>/dev/null | wc -l | tr -d ' ')"
if [ "${src_n:-0}" -gt 0 ] 2>/dev/null; then
  echo "tests:src: $(awk -v t="$tst_n" -v s="$src_n" -v c="$RATIO_CAP" \
    'BEGIN { r = t / s; printf "%.2f (%d / %d) vs cap %s -> %s", r, t, s, c, (r > c + 0 ? "OVER" : "under") }')"
else
  echo "tests:src: unavailable (no src/fieldguard_planning/*.py)"
fi

# --- ROADMAP freshness ------------------------------------------------------------------------------
if [ -f docs/ROADMAP.md ]; then
  rd="$(grep -m1 '^## Where we are' docs/ROADMAP.md | sed -n 's/^## Where we are (\(.*\)).*/\1/p')"
  echo "roadmap: 'Where we are' dated ${rd:-unavailable (heading not in '## Where we are (<date>)' form)}"
else
  echo "roadmap: unavailable (docs/ROADMAP.md absent)"
fi
exit 0
