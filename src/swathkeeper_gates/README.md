# swathkeeper-gates

Pre-registered evidence gates over an ArduPilot flight log. You write pass/fail bars in a YAML file, hash it before
the run, and the tool judges a DataFlash `.bin` against it: one JSON verdict, one exit code. A bar the log cannot
measure reads `could not tell`, which never scores green. Version 0.1.0 reads ArduPilot DataFlash only and has run on
exactly the three public logs in `examples/`. Read
[What this does NOT claim](https://github.com/vihanpatil/SwathKeeper/blob/main/src/swathkeeper_gates/README.md#what-this-does-not-claim) first.

## Install

The package is not on PyPI. Install it from GitHub into a virtual environment (Python 3.10 or newer; CI tests 3.10
and 3.12). Without a venv, `uv pip` refuses and a Homebrew pip hits PEP 668.

```sh
python3 -m venv .venv && . .venv/bin/activate   # python3 must be 3.10 or newer: macOS's /usr/bin/python3 is 3.9
uv pip install 'swathkeeper-gates[ardupilot] @ git+https://github.com/vihanpatil/SwathKeeper@main'
pip install 'swathkeeper-gates[ardupilot] @ git+https://github.com/vihanpatil/SwathKeeper@main'   # or this
```

The `[ardupilot]` extra installs the parser, pymavlink, pinned to 2.4.50; without it a `.bin` refuses (exit 2) naming
the extra. Measured 2026-11-09 in a fresh venv (macOS, Python 3.12.12): 3.5 s, installing swathkeeper-gates 0.1.0,
pymavlink 2.4.50, PyYAML 6.0.3, lxml 6.1.3. Every output below was measured from an install at commit ecbe20c of
this repository, before this file reached main, with no checkout of this repo.

## Walkthrough: one public log, one bar

Use your own `.bin`, or the public Tarot X4 log the examples use (ArduCopter V4.5.5, GPL-3.0, 5,197,824 bytes,
pinned in [`examples/tarot_x4/SOURCE.json`](https://github.com/vihanpatil/SwathKeeper/blob/main/examples/tarot_x4/SOURCE.json)):

```sh
curl -fL "https://raw.githubusercontent.com/ArduPilot/MethodicConfigurator/3d14a14353eeb9fca73c82995855bf977a7d5fcc/ardupilot_methodic_configurator/vehicle_templates/ArduCopter/Tarot_X4/2024-08-05%2018-48-54.bin" -o tarot.bin
echo "a4dc00507cc8448c0ce320279e70040de3af3439dd4c3dd5363a7fa388609108  tarot.bin" | sha256sum -c -
```

### 1. Inspect the log

```sh
swathkeeper-gates inspect --log tarot.bin
```

It prints JSON blocks `source`, `integrity` and `streams`, and exits 0 (2 if refused). Each stream is `PRESENT`
(data), `EMPTY` (a measured zero, with its cited reason) or `ABSENT`, and a bar that needs an ABSENT stream reads
`EVIDENCE_INSUFFICIENT`. The Tarot log (1.2 s, 5,635 bytes of JSON): vehicle "ArduCopter", firmware "ArduCopter
V4.5.5", `duration_s` 141.900922; position, velocity, gnss, battery, ekf, mode, arming PRESENT; events EMPTY; home
and fence PRESENT (fence type 7, a 150.0 m circle, 120.0 m altitude max); params PRESENT, n 1197; 10 trailing bytes
skipped, 0 interior, `dsf_dropped_max` 15, `drop_intervals` `[[709.278081, 710.1837, 15]]`.

### 2. Write the bars

Save this as `bars.yaml` (there is no template command; for all five kinds, copy
[`examples/tarot_x4/bars.yaml`](https://github.com/vihanpatil/SwathKeeper/blob/main/examples/tarot_x4/bars.yaml)).
It asks: did any battery sample fall below 18.6 V?

```yaml
schema: swathkeeper-bars/1.0
contract: swathkeeper-flightlog/1.0
bars:
  - id: batt_floor
    kind: series_bound
    severity: must
    provenance: {text: "log PARM BATT_LOW_VOLT; instantaneous, stricter than the 10 s timer", param: BATT_LOW_VOLT}
    scope: {armed: null, modes: null}
    min_n: 30
    params: {channel: battery.voltage_v, bound: floor, limit: 18.6}
```

### 3. Register the bars before the run

```
$ swathkeeper-gates prereg --bars bars.yaml --log tarot.bin
registered bars.yaml sha256 185074c12430389f65ec6f071ab988fc1f4e4d67e3ba0ee2f28183cfea563884, pinned to log sha256 a4dc00507cc8448c0ce320279e70040de3af3439dd4c3dd5363a7fa388609108 (post-hoc) -> bars.yaml.prereg.json
```

Exit 0. The sidecar holds the sha256 of the file's raw bytes and is never overwritten. `--log` pins the log too:
`run` refuses any other log, and the badge says `(post-hoc)`. Commit the sidecar before the run: its commit is the
only date claim, and a committer can forge it.

### 4. Run

```
$ swathkeeper-gates run --log tarot.bin --bars bars.yaml --out verdict.json
  PASS                   must   batt_floor           n=1419      measured=23.48213005065918
gates: pass · 1/1 measured (post-hoc)
```

Exit 0, in 0.4 s. Each line is verdict, severity, id, n (what n counts depends on the kind, table below) and the
measured value (for a floor, the lowest sample); each bar's note is in `verdict.json`. `run` finds the sidecar beside
the bars file (`--prereg PATH` names another). A typo (`bound: min`) refuses with exit 2, the refusal JSON still
written to `--out`:

```
swathkeeper-gates: refused: bar batt_floor.params.bound: 'min' is not one of ['floor', 'ceiling']
gates: refused
```

`inspect` on a file that is not DataFlash refuses with exit 2 (`run` with the walkthrough's pinned sidecar refuses
LOG_MISMATCH first). A PX4 ULog refuses with exit 2 too: 0.1 ships no PX4 adapter, and the message says so.

```
$ swathkeeper-gates inspect --log random.file
swathkeeper-gates: refused: unknown log format: magic 441688cd is neither DataFlash (a395) nor ULog
```

### 5. Optional: the GitHub Action

It fails the step exactly when the tool exits 1 or 2; see
[its README](https://github.com/vihanpatil/SwathKeeper/blob/main/.github/actions/swathkeeper-gates/README.md).

```yaml
- uses: actions/checkout@v4
- uses: vihanpatil/SwathKeeper/.github/actions/swathkeeper-gates@main   # pin a SHA for a stable tool version
  id: gates
  with:
    log: flights/2026-11-05.bin
    bars: flights/bars.yaml
    out: verdict.json
```

## Reference: the bars file (`swathkeeper-bars/1.0`)

Top level: `schema: swathkeeper-bars/1.0`; `contract: swathkeeper-flightlog/1.<minor>` (the major must match the
tool's, and a newer minor refuses); `bars`, a list of at least one bar. Keys marked `?` are optional.

| Key | Value |
|---|---|
| `id` | `[a-z0-9_]{1,40}`, unique in the file |
| `kind` | one of the five kinds below |
| `severity` | `must` or `should` (see exit codes). A file with zero `must` bars refuses. |
| `provenance` | `{text, param?}`. `text` says where the limit came from. `param` names a PARM whose logged value(s) the verdict prints beside the limit; it never changes the verdict. |
| `scope` | `{armed, modes}`, both required. `armed: true` judges known-armed intervals only, `null` the whole log; `false` refuses. `armed: true` reads EVIDENCE_INSUFFICIENT whenever the scope reaches before the first ARM row (arming before it is ABSENT, rule 4). That was all three public logs: on the Tarot and the ArduPlane logs (LOG_DISARMED 0) the arm row is not written, so the only ARM row is the disarm; `test.BIN` has no ARM rows at all. `modes: [names]` judges only those modes, `null` any mode. Names must be spelt as pymavlink spells them for the vehicle resolved from the log's firmware string (e.g. `LOITER`, `ALT_HOLD`), or the run refuses; with the vehicle unresolved, every bar that names a mode reads `EVIDENCE_INSUFFICIENT`, and so does `mode_transitions` even when it names no mode. |
| `min_n` | an integer of at least 1; required, no default |
| `params` | per kind, below |

| Kind | `params` | Judges | n counts |
|---|---|---|---|
| `series_bound` | `channel` (one of the 16 below), `bound` (`floor` or `ceiling`), `limit` | every sample of every instance in scope against `limit` | samples in scope, all instances |
| `gnss_quality` | `fix_min`, `sats_min`, `max_outage_s` | FAIL if a run of rows below `fix_min` or `sats_min` spans more than `max_outage_s` on any instance (0 = any such row). A run is measured to the next qualifying row, so one bad row at 5 Hz spans 0.2 s. `fix_type` is the AP_GPS Status enum (3 = 3D fix). | rows in scope |
| `containment` | `source` (`log` or `yaml`), `polygon?`, `alt_max_rel_home_m?`, `exclusions?` | `log`: the FENCE_RADIUS cylinder about home and FENCE_ALT_MAX. FENCE_TYPE bits 4 (polygon) and 8 (minimum altitude) are not judged, so the Tarot geofence PASS covers the circle and the altitude cap only. `yaml`: needs a `polygon` of at least 3 `[lat, lon]`, not self-intersecting. `exclusions` are `{lat, lon, radius_m}` circles. Polygon and circles are judged on every segment between samples, never across a gap. | judged segments between consecutive samples |
| `mode_transitions` | `allowed` | every observed transition is a listed `[from, to]` pair; `"*"` is any mode, `<start>` (only as a `from`) the log's start | transitions after the startup row |
| `no_events` | `kinds` (only `error` in 0.1), `ignore?` | zero ERR rows outside the `ignore` list of `[Subsys, ECode]` pairs | drop-free seconds of scope |

```
position.lat  position.lon  position.alt_amsl_m  position.alt_rel_home_m  velocity.groundspeed_mps
gnss.fix_type  gnss.nsats  gnss.hdop  gnss.gps_week  gnss.gps_ms  battery.voltage_v  battery.current_a
ekf.vel_ratio  ekf.pos_ratio  ekf.hgt_ratio  ekf.mag_ratio
```

**The loader is strict.** It refuses a duplicate key at any depth (plain PyYAML keeps the last one silently), the
merge key `<<`, any unknown or missing key, a boolean where a number belongs (`yes`), a non-finite number, and any
number whose text is not plain decimal (`022`, `0x12`, `1_8.6`, `.inf`). An invalid file is never registered.

## How a bar is decided (a fixed order: the first rule that matches wins)

Two causes make a bar **blind**: (a) the mode is unknown for more than 1.0 s before the first MODE row, which applies
to every bar that names a mode and to `mode_transitions` (1.0 s or less is only a note); (b) no PRESENT position,
gnss or battery stream exists to witness the logger, which applies to `mode_transitions` and `no_events`.

1. Something the bar needs is ABSENT: `EVIDENCE_INSUFFICIENT`. That is a needed stream or column; the arming, mode
   or vehicle the scope needs; for `containment` with `source: log`, the fence or home; for `no_events`,
   `dsf_dropped_max`; an `armed: true` scope that reaches before the first ARM row; for `mode_transitions`, an
   unresolved vehicle.
2. No window of the scope exists, and a log hole touches the base range (the known-armed intervals for `armed: true`,
   otherwise the whole log) or a blind cause applies: `EVIDENCE_INSUFFICIENT`.
3. No window of the scope exists: `NOT_APPLICABLE`. The absence is measured.
4. Any judged sample violates the bar: `FAIL`, whatever n is. A measured red is red.
5. A non-finite sample, a gap or a log hole in scope, a blind cause, or n below `min_n`: `EVIDENCE_INSUFFICIENT`.
6. Otherwise: `PASS`.

EI and NA never print a measured number, so a thin-sample value cannot be quoted. A gap is a step longer than
max(1 s, 5 × the instance's median sample period); a log hole is an interior byte skip, or a gap in every present
raw series (position, gnss, battery) at once. In a QA probe on 2026-11-09 (not a committed verdict), the public
ArduPlane log, whose first MODE row is 1.281 s after the log start, read EI with zero gaps on a mode-scoped bar and on
a `[["*", "*"]]` `mode_transitions` bar (rule 5).

## Exit codes and the badge

| Exit | Word | When |
|---|---|---|
| 0 | `pass` | no undeclared red, no vacuous or expired declaration, and at least one `must` bar PASSED |
| 1 | `fail` | an undeclared FAIL, or a declaration that is vacuous or expired |
| 1 | `could not tell` | otherwise: an undeclared `must` EI or NA, or no `must` PASS |
| 2 | `refused` | nothing was judged: invalid bars, a sidecar mismatch, an unknown format, a missing extra, a crash |

A red is a FAIL on any bar, or an EI or NA on a `must` bar; a `should` bar's EI or NA is printed only. `could not
tell` exits 1 because a bar that could not be measured is not evidence that it was met. The badge:

```
gates: <word> · m/n measured[ · k declared (f FAIL, e EI[, n NA])][ (post-hoc) | (unregistered)]
```

`m/n measured` counts the bars that read PASS or FAIL. `(post-hoc)`: the sidecar pins this log's hash, so the bars
were written after the log existed. `(unregistered)`: no sidecar was found, so the bars could have been written after
the result was known. No suffix means a matching sidecar that pins no log: it proves the bars text was registered,
not when. Pinning the log with `--log` proves the log existed first and costs the `(post-hoc)` suffix. A malformed
or mismatched sidecar refuses.

## Declared reds (`--declared`)

```yaml
schema: swathkeeper-declared/1.0
declared:
  - {bar: batt_floor, verdict: FAIL, reason: "names the evidence, not the symptom", expires: 2027-01-31}
```

The set of (bar, verdict) reds must equal the set of live declarations: a red nobody declared is `undeclared`, a
declaration nothing matches is `vacuous` (exit 1, `fail`), and on or after `expires` an entry declares nothing.
`verdict` is `FAIL`, `EVIDENCE_INSUFFICIENT` or `NOT_APPLICABLE`; a declared PASS, a second entry for one bar, an entry
naming no bar, or an EI/NA on a `should` bar refuses. The file's hash is in the verdict, and the count of matched
declarations is on the badge.

## What the adapter reads, and dropped writes

POS, GPS, BAT, XKF4, NKF4, NKF9, MODE, ARM, ERR, DSF, PARM, MSG, VER, ORGN; not GPS2, BAT2 or CURR. Velocity keeps GPS
rows with Status ≥ 3, ekf rows with SS ≠ 0; `alt_rel_home_m` starts at the first ORGN home row; arming before the
first ARM row is ABSENT. Zero ERR rows is EMPTY by a lead ruling (ADR-023) that extends one source read at tag
Copter-4.5.5 to every vehicle's release `V4.5.<n>` firmware string with no suffix, when `LOG_BACKEND_TYPE` is
logged, constant and == 1 and an ERR format is defined in the log; otherwise events are ABSENT. The citation is in
the docstring of `adapters/ardupilot.py`. The fence's polygon and minimum-altitude bits are not judged.

When `DSF.Dp` rises, the firmware dropped writes it does not locate. In 0.1 the rise interval is excluded from
`no_events`' drop-free seconds; every other bar whose range it touches is judged across it, with this note (every
other Tarot bar carries it; `no_errors` carries the excluded-from-n form). This behaviour is under review as open
item G257 in ADR-023. If G257 is ruled a hole, the Tarot badge becomes `could not tell`.

```
15 firmware-dropped writes in [709.278, 710.184] s (DSF.Dp), not located; judged across (design §3.3)
```

## The three scored examples

Each holds `SOURCE.json` (url, sha256, size, licence), `bars.yaml`, its sidecar and `verdict.json`, never the log;
the Tarot dir also holds `badge.svg`. CI re-fetches each log by sha256 and requires byte identity with the committed
verdict apart from three leaves it excludes and shape-checks (`tool.python`, `tool.deps.PyYAML`,
`allowlist.run_date_utc`). From the install above, the Tarot verdict reproduced on every scalar leaf (363) except
`allowlist.run_date_utc`.

| Directory | Log | Badge | Exit |
|---|---|---|---|
| [`examples/tarot_x4/`](https://github.com/vihanpatil/SwathKeeper/tree/main/examples/tarot_x4/) | Tarot X4, ArduCopter V4.5.5 | `gates: pass · 8/8 measured (post-hoc)` | 0 |
| [`examples/plane_nofix/`](https://github.com/vihanpatil/SwathKeeper/tree/main/examples/plane_nofix/) | ArduPlane V4.7.0-beta5, no GPS fix | `gates: fail · 1/5 measured (post-hoc)` | 1 |
| [`examples/pymavlink_test_bin/`](https://github.com/vihanpatil/SwathKeeper/tree/main/examples/pymavlink_test_bin/) | pymavlink `test.BIN`, ArduPlane V3.8.2-dev | `gates: could not tell · 3/6 measured (post-hoc)` | 1 |

## What this does NOT claim

- The tool comes from a sim-demonstrated drone repo. Its authors have flown nothing real, and that drone's own
  avoidance breached its 3.00 m bar on all three live sim flights (closest approach 0.0393 / 0.0391 / 0.0067 m);
  two passed the gates of the day and were called strikes by a gate written afterwards, the third was
  pre-registered as a possible FAIL, and it failed. The tool is that method, not evidence that the drone works.
- A verdict claims nothing beyond what it prints: these bars, this file (by sha256), this parser version, this date.
  PASS means every measured sample met the bar; between samples it says nothing, except where `containment` judges
  segments, and never across a gap. A PASS says nothing about any vehicle's safety. The tool has run on exactly the
  three public logs in `examples/`, and on no other vehicle or format.
- Before the Tarot bars were written, the authors had seen its modes, error count, GNSS status, peak altitude and
  first battery and EKF rows. The build's draft run printed the measured values of six of the eight bars, and the
  first registered verdict printed all eight before the file was re-registered. So the Tarot results are
  demonstrations, not tests. Its bars were registered after the log existed (post-hoc), and its bars, sidecar and
  verdict were first committed together, so git orders nothing there. A 142 s low hover was expected to pass them.
- Pre-registration binds a run to a text, not a date: the date claim is the sidecar's git commit, which a committer
  can forge, and the sidecar's `written_utc` is recorded as untrusted.
- A truncated log reads as a shorter flight; only a pinned log hash ties a verdict to a file. DataFlash has no
  checksum, so a corrupted record with an intact header decodes as values. Never exercised on: a real EKF2 log with
  a core column, a multi-home log, a mid-flight Dp rise, or `LOG_BACKEND_TYPE` other than 1.

The why, with each rejected alternative: [`docs/design/GATES_TOOL_DESIGN.md`](https://github.com/vihanpatil/SwathKeeper/blob/main/docs/design/GATES_TOOL_DESIGN.md).
What the build measured, and the open items: ADR-023 and its amendment 1 in
[`docs/DECISIONS.md`](https://github.com/vihanpatil/SwathKeeper/blob/main/docs/DECISIONS.md).
