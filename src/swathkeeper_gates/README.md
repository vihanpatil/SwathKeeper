# swathkeeper-gates

Pre-registered evidence gates over an ArduPilot flight log. You write pass/fail bars in a YAML file, hash it before
the run, and the tool judges a DataFlash `.bin` against it: one JSON verdict, one exit code. A bar the log cannot
measure reads `could not tell`, which never scores green. Version 0.3.0 reads DataFlash only. It has published verdicts on exactly the three public logs in `examples/`, and a measurability probe ran it on 40 more public logs on 2026-11-10.
Read [What this does NOT claim](https://github.com/vihanpatil/SwathKeeper/blob/main/src/swathkeeper_gates/README.md#what-this-does-not-claim) first.

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
this repository, before this file reached main, with no checkout of this repo. On 0.3.0 the walkthrough's `run`
output is unchanged (re-run 2026-11-11, exit 0), and on every push CI writes this exact bars file (checked by
sha256), registers it against the Tarot log as step 3 does, and requires exit 0 with the bar line and badge of step 4.

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

Save this as `bars.yaml`. It asks: did any battery sample fall below 18.6 V? There is no template command; for all
five kinds, copy [`examples/tarot_x4/bars.yaml`](https://github.com/vihanpatil/SwathKeeper/blob/main/examples/tarot_x4/bars.yaml).

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
the bars file (`--prereg PATH` names another). A typo (`bound: min`) refuses `run` with exit 2, the refusal JSON
still written to `--out`. `inspect` on a file that is not DataFlash refuses with exit 2 (`run` with the walkthrough's
pinned sidecar refuses LOG_MISMATCH first). A PX4 ULog refuses too: this version ships no PX4 adapter.

```
$ swathkeeper-gates run --log tarot.bin --bars bars.yaml --out verdict.json    # with bound: min
swathkeeper-gates: refused: bar batt_floor.params.bound: 'min' is not one of ['floor', 'ceiling']
gates: refused
$ swathkeeper-gates inspect --log random.file
swathkeeper-gates: refused: unknown log format: magic 441688cd is neither DataFlash (a395) nor ULog
```

### 5. Optional: the GitHub Action

It fails the step exactly when the tool exits 1 or 2; see [its README](https://github.com/vihanpatil/SwathKeeper/blob/main/.github/actions/swathkeeper-gates/README.md).

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
| `provenance` | `{text, param?}`. `text` says where the limit came from. `param` names a PARM whose logged value(s) the verdict prints beside the limit; it never changes the verdict (when the limit follows a parameter, it must name that one). |
| `scope` | `{armed, modes}`, both required. `armed: true` judges known-armed intervals only, `null` the whole log; `false` refuses. Without the `assume` key, `armed: true` reads EVIDENCE_INSUFFICIENT whenever the scope reaches before the first ARM row (arming before it is ABSENT, rule 4), and every log has such a stretch; with the key, see Declared assumptions below. `modes: [names]` judges only those modes, `null` any mode. Names must be spelt as pymavlink spells them for the vehicle resolved from the log's firmware string (e.g. `LOITER`, `ALT_HOLD`), or the run refuses; with the vehicle unresolved, every bar that names a mode reads `EVIDENCE_INSUFFICIENT`, and so does `mode_transitions` even when it names no mode. |
| `min_n` | an integer of at least 1; required, no default |
| `params` | per kind, below |

| Kind | `params` | Judges | n counts |
|---|---|---|---|
| `series_bound` | `channel` (one of the 16 below), `bound` (`floor` or `ceiling`), `limit` (a number, or `{param, scale?, accept}`: see A limit that follows the log's own parameter) | every sample of every instance in scope against `limit` | samples in scope, all instances (judged samples only, when the limit follows a parameter) |
| `gnss_quality` | `fix_min`, `sats_min`, `max_outage_s` | FAIL if a run of rows below `fix_min` or `sats_min` spans more than `max_outage_s` on any instance (0 = any such row). A run is measured to the next qualifying row, so one bad row at 5 Hz spans 0.2 s. `fix_type` is the AP_GPS Status enum (3 = 3D fix). | rows in scope |
| `containment` | `source` (`log` or `yaml`), `polygon?`, `alt_max_rel_home_m?`, `exclusions?` | `log`: the FENCE_RADIUS cylinder about home and FENCE_ALT_MAX. FENCE_TYPE bits 4 (polygon) and 8 (minimum altitude) are not judged, so the Tarot geofence PASS covers the circle and the altitude cap only. `yaml`: needs a `polygon` of at least 3 `[lat, lon]`, not self-intersecting. `exclusions` are `{lat, lon, radius_m}` circles. Polygon and circles are judged on every segment between samples, never across a gap. | judged segments between consecutive samples |
| `mode_transitions` | `allowed` | every observed transition is a listed `[from, to]` pair; `"*"` is any mode, `<start>` (only as a `from`) the log's start. A transition across a loss has an unknown `from`: FAIL if no mode could be allowed into the observed mode, judged and counted if every mode could, otherwise not judged and the bar reads EI (see lost writes below). | transitions after the startup row |
| `no_events` | `kinds` (only `error` in 0.3.0), `ignore?` | zero ERR rows outside the `ignore` list of `[Subsys, ECode]` pairs | drop-free seconds of scope |

```
position.lat  position.lon  position.alt_amsl_m  position.alt_rel_home_m  velocity.groundspeed_mps
gnss.fix_type  gnss.nsats  gnss.hdop  gnss.gps_week  gnss.gps_ms  battery.voltage_v  battery.current_a
ekf.vel_ratio  ekf.pos_ratio  ekf.hgt_ratio  ekf.mag_ratio
```

**The loader is strict.** It refuses a duplicate key at any depth (plain PyYAML keeps the last one silently), the
merge key `<<`, any unknown or missing key, a boolean where a number belongs (`yes`), a non-finite number, and any
number whose text is not plain decimal (`022`, `0x12`, `1_8.6`, `.inf`). An invalid file is never registered.

## How a bar is decided (a fixed order: the first rule that matches wins)

Four causes make a bar **blind**: (a) the mode is unknown for more than 1.0 s before the first MODE row, which
applies to every bar that names a mode and to `mode_transitions` (1.0 s or less is only a note); (b) no PRESENT
position, gnss or battery stream exists to witness the logger, which applies to `mode_transitions` and `no_events`;
(c) for `mode_transitions`, a loss (defined under lost writes below) in its base range, unless its allowed set
admits every transition, and a loss that cuts a transition the tool cannot judge, even when that loss lies outside
the base range; (d) for a `series_bound` whose limit follows a parameter, any in-scope sample whose limit cannot be
used (A limit that follows the log's own parameter, below).

1. Something the bar needs is ABSENT: `EVIDENCE_INSUFFICIENT`. That is a needed stream or column; the arming, mode or
   vehicle the scope needs; for `containment` with `source: log`, the fence or home; for `no_events`, `dsf_dropped_max`;
   without the `assume` key, an `armed: true` scope that reaches before the first ARM row; for `mode_transitions`, an unresolved vehicle.
2. No window of the scope exists, and a log hole touches the base range or a blind cause applies: `EVIDENCE_INSUFFICIENT`.
3. No window of the scope exists: `NOT_APPLICABLE`. The absence is measured.
4. Any judged sample violates the bar: `FAIL`, whatever n is. A measured red is red.
5. A non-finite sample, a gap or a log hole in scope, a blind cause, or n below `min_n`: `EVIDENCE_INSUFFICIENT`.
   The exception: a loss does not void an unarmed `mode_transitions` bar whose allowed set admits every transition.
6. Otherwise: `PASS`.

EI and NA never print a measured number, so a thin-sample value cannot be quoted. A gap is a step longer than
max(1 s, 5 × the instance's median sample period); a log hole is an interior byte skip, or a gap in every present
raw series (position, gnss, battery) at once. In a QA probe on 2026-11-09 (not a committed verdict), the public
ArduPlane log, whose first MODE row is 1.281 s after the log start, read EI with zero gaps on a mode-scoped bar and on
a `[["*", "*"]]` `mode_transitions` bar (rule 5). A mode-scoped bar whose scope could reach a loss, or an
armed-scoped bar where arming is unsure, gets two passes of this order (a sure and a wide scope) and one combined
verdict; see lost writes below.

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
gates: <word> · m/n measured[ · k declared (f FAIL, e EI[, n NA])][ · k assumed][ (post-hoc) | (unregistered)]
```

`m/n measured` counts the bars that read PASS or FAIL. `k assumed` counts the assumption names the bars file declares,
whether or not they applied to this log. `(post-hoc)`: the sidecar pins this log's hash, so the bars were written
after the log existed. `(unregistered)`: no sidecar was found, so the bars could have been written after the result
was known. No suffix means a matching sidecar that pins no log: it proves the bars text was registered, not when.
Pinning the log with `--log` proves the log existed first and costs the `(post-hoc)` suffix.

## Declared reds (`--declared`)

```yaml
schema: swathkeeper-declared/1.0
declared:
  - {bar: batt_floor, verdict: FAIL, reason: "names the evidence, not the symptom", expires: 2027-01-31}
```

The set of (bar, verdict) reds must equal the set of live declarations: a red nobody declared is `undeclared`, a
declaration nothing matches is `vacuous` (exit 1, `fail`), and on or after `expires` an entry declares nothing.
`verdict` is `FAIL`, `EVIDENCE_INSUFFICIENT` or `NOT_APPLICABLE`; a declared PASS, a second entry for one bar, an entry
naming no bar, or an EI/NA on a `should` bar refuses. The file's hash is in the verdict, matched declarations on the badge.

## Declared assumptions (`assume`)

`assume` is an optional top-level key of the bars file: a list of names from a closed set of two. This section describes
`arming_before_first_arm_row`; `limit_before_first_parm_row` (0.3.0) is described under A limit that follows the log's
own parameter. An unknown name, a duplicate or an empty list refuses, and so does a name no bar uses: the first needs a
bar with `armed: true`, the second a bar whose limit follows a parameter. It is part of the bars text, so `prereg`
hashes it; a tool older than a name refuses a file using it.

> Before the first ARM row the vehicle is in the opposite state of that row: armed before a first disarm, disarmed before a first arm. A log with no ARM row is not covered: arming stays ABSENT. The tool does not verify this.

**What it changes.** Only bars with `scope.armed: true`, and only when the log has ARM rows. The stretch before the
first ARM row joins the armed set if that row is a disarm, and the could-not-tell for "arming ABSENT before the first
ARM row" no longer fires. Nothing in `inspect` or the verdict's `streams` block changes.

**Lost writes and arming** (with or without the key). Arming is unsure (a) between two consecutive ARM rows of the
same state (a row is provably missing), (b) from a loss that ends at or after the first ARM row until the next ARM
row, and (c) with the key, from the log's start to the end of any loss that starts at or before the first ARM row.
An armed-scoped bar is then judged on a sure and a wide scope exactly as a mode-scoped bar is; `mode_transitions`
with `armed: true` is judged on the sure scope and reads could not tell where the two differ, unless it already FAILs.

**Where it prints.** The verdict's top-level `assumptions` list (always present, `[]` when none) holds `name`, `text`,
`applied`, `detail` and `log_disarmed`. `applied: true` means the log had ARM rows, not that the assumption changed a
verdict; `log_disarmed` is the log's own LOG_DISARMED values, printed as context and read by no rule. On a log
with ARM rows every armed-scoped result's note says "arming before t=… s assumed armed|disarmed (assume: arming_before_first_arm_row)".
The badge gains ` · k assumed` (k = names declared) on every verdict from that bars file.

**Example**, an armed-scoped bar on the Tarot log (final 0.2.0 build, 2026-11-10):
```yaml
schema: swathkeeper-bars/1.0
contract: swathkeeper-flightlog/1.0
assume: [arming_before_first_arm_row]
bars:
  - id: batt_floor_armed
    kind: series_bound
    severity: must
    provenance: {text: "log PARM BATT_LOW_VOLT, while armed", param: BATT_LOW_VOLT}
    scope: {armed: true, modes: null}
    min_n: 30
    params: {channel: battery.voltage_v, bound: floor, limit: 18.6}
```
```
  PASS                   must   batt_floor_armed     n=1261      measured=23.48213005065918
gates: pass · 1/1 measured · 1 assumed (unregistered)
```

Exit 0. Its `detail`: "first ARM row at t=836.274 s is a disarm: armed before it; 15 firmware-dropped writes in
[709.278, 710.184] s (DSF.Dp): [t0, 710.184] judged both ways". Without the `assume` line the same bar reads
`EVIDENCE_INSUFFICIENT`, `gates: could not tell · 0/1 measured (unregistered)`, exit 1, with the note "arming is
ABSENT before the first ARM row at t=836.274 s (rule 4) and the scope reaches there".

**What it does not handle.** It is an assumption about the firmware's arming state. A logger silence shorter than
max(1 s, 5 sample periods) is not a loss, so a file opened by a failed arm and followed by a refused first arm can
leave a short disarmed stretch assumed armed; that errs towards a red, never a green. A log without DSF rows reports
no dropped rows. Firmware other than Copter 4.5.5 is assumed, not read. A log with no ARM row stays could not tell.

## A limit that follows the log's own parameter

Since 0.3.0 a `series_bound` limit may be a mapping instead of a number. The limit is then `scale` times the value
the log's own PARM rows give for `param`, so one bars file can judge flights flown at different settings.

```yaml
params: {channel: velocity.groundspeed_mps, bound: ceiling, limit: {param: WP_SPD, scale: 1.1, accept: [1.0, 5.0]}}
```

| Key | Value |
|---|---|
| `param` | a parameter name, `[A-Z][A-Z0-9_]{0,15}`. Names are never aliased. |
| `scale?` | a finite number above 0, default 1. A unit conversion goes here: the tool does not know a parameter's unit. |
| `accept` | required: `[LO, HI]`, the closed range of raw parameter values the bar is written for. `scale` times each end must be finite. |

The mapping is legal only at `series_bound.params.limit`. A `provenance.param` naming a different parameter refuses.
A 0.2.0 tool refuses the mapping.

**What the bar means.** "The vehicle stayed within its own logged configuration", for a configuration inside
`accept`. It does not say that configuration was safe. Registration no longer fixes the number: it fixes the formula
and the envelope from `scale` x LO to `scale` x HI, and the log supplies the value.

**How a sample is judged.** Its candidates are the latest PARM row of the parameter strictly before it, plus any row
on its own timestamp. It is a violation only if it breaks `scale` x every candidate, clean only if it breaks none.
A sample is not judged when:

- it sits at or before the parameter's first PARM row: the startup dump takes time, and the value before it is not logged;
- a loss (a DSF.Dp drop interval or a log hole) meets the stretch from that previous row to the sample: a change row
  may be lost in it, and a parameter is logged at startup and then only when it changes, so often no later row re-pins it;
- a candidate lies outside `accept`: a disabled threshold such as `BATT_LOW_VOLT 0`, or a configuration the bar was
  not written for. The note says how many of those samples break the logged value anyway;
- a candidate row's value is not finite, or two rows on the sample's timestamp disagree about the verdict.

One unjudged sample in scope makes the bar read `could not tell`, unless another sample is a certain violation: that
stays FAIL, and its note names the unjudged samples too. n counts judged samples only. A parameter with no PARM row
in the log reads `could not tell`.

**The assumption `limit_before_first_parm_row`** is the second name `assume` accepts. Its fixed text:

> Up to and including its first PARM row, a parameter a bar takes from PARM held that row's value, and no row of it was lost in a DSF.Dp drop interval that begins at or before that row or at the log's start, including the part of that interval after the row. Not covered: a first row more than 5 s after the log's start, log holes, and later drop intervals; these losses, which the log counts or shows, still read could not tell. The tool does not verify this.

With it, a sample at or before the first row is judged against that row's value, and a drop interval that begins at
or before that row, or at the log's start, no longer makes the limit unsure. A log hole, a later drop interval and a
first row more than 5 s after the log's start are never covered. It changes no mode or arming judgement.

**What prints.** Each such result carries `limit_in_log`: `rows` (the first 8 `[t_s, value]` rows by time, `null` for
a non-finite value), `n_rows`, and `at_worst`, the limit the worst sample was judged against (`null` unless the
verdict is PASS or FAIL). On PASS and FAIL the note leads with the arithmetic. The assumption's entry in `assumptions`
gives each followed parameter's first row and the drop intervals it discarded.

**Example**, the walkthrough's battery floor following the Tarot's own `BATT_LOW_VOLT` (0.3.0, 2026-11-11):

```yaml
schema: swathkeeper-bars/1.0
contract: swathkeeper-flightlog/1.0
assume: [limit_before_first_parm_row]
bars:
  - id: batt_floor
    kind: series_bound
    severity: must
    provenance: {text: "the log's own BATT_LOW_VOLT, accepted for a 6S pack at 3.0 to 3.6 V per cell", param: BATT_LOW_VOLT}
    scope: {armed: null, modes: null}
    min_n: 30
    params: {channel: battery.voltage_v, bound: floor, limit: {param: BATT_LOW_VOLT, accept: [18.0, 21.6]}}
```

```
$ swathkeeper-gates run --log tarot.bin --bars bars.yaml --out verdict.json
  PASS                   must   batt_floor           n=1419      measured=23.48213005065918
gates: pass · 1/1 measured · 1 assumed (unregistered)
```

Exit 0. The note leads with `limit 18.6 = 1 x BATT_LOW_VOLT 18.6 (PARM row at t=709.297 s)`, and the assumption's
detail reads `BATT_LOW_VOLT: first PARM row at t=709.297 s; removed 15 firmware-dropped writes in [709.278, 710.184] s (DSF.Dp)`.
Without the `assume` line the same file reads `gates: could not tell · 0/1 measured (unregistered)`, exit 1: the
interval in which the Tarot's 15 writes were dropped holds `BATT_LOW_VOLT`'s first row, so the limit is unsure for
all 1419 samples.

**Names and units change between releases.** `WPNAV_SPEED` is in cm/s through Copter 4.6.3 and `WP_SPD` in m/s from
Copter 4.7.0 (read from the ArduPilot source at those tags). A bar naming one reads `could not tell` on a log that
carries the other.

## What the adapter reads, and lost writes

POS, GPS, BAT, XKF4, NKF4, NKF9, MODE, ARM, ERR, DSF, PARM, MSG, VER, ORGN; not GPS2, BAT2 or CURR. Velocity keeps GPS
rows with Status ≥ 3, ekf rows with SS ≠ 0; `alt_rel_home_m` starts at the first ORGN home row; arming before the
first ARM row is ABSENT unless the bars file declares `assume` (above). Zero ERR rows is EMPTY by a lead ruling
(ADR-023) that extends one source read at tag Copter-4.5.5 to every vehicle's release `V4.5.<n>` firmware string
with no suffix, when `LOG_BACKEND_TYPE` is logged, constant and == 1 and an ERR format is defined in the log;
otherwise events are ABSENT. The citation is in the docstring of `adapters/ardupilot.py`.

A **loss** is an interval in which `DSF.Dp` rose (the firmware dropped writes it does not locate) or a log hole; a
MODE or ARM row may be inside it. After a loss the mode is unsure until the next MODE row (or the log's end).

- **Mode-scoped bars** (and armed-scoped ones, as above) are then judged on the sure scope (the observed windows
  minus the unsure stretch) and the wide scope (plus it): FAIL if the sure scope fails, PASS only if both pass,
  otherwise `EVIDENCE_INSUFFICIENT`. On such a PASS the printed `measured` is the wide scope's worst value and n is
  the sure scope's count; the note gives both (Tarot `speed_ceiling_loiter`: sure 2.421 on n=591, wide 2.421 on n=709).
- **`mode_transitions`**: a transition whose span contains a loss has an unknown `from`. It is a FAIL if no mode
  could be allowed into the observed mode, judged and counted if every mode could, and otherwise not judged, and the
  bar reads EI. A loss in the bar's base range also makes it EI, unless the allowed set admits every transition.
- **Unscoped** `series_bound`, `gnss_quality` and `containment` bars are judged as before and print the note
  `N firmware-dropped writes in [a, b] s (DSF.Dp), not located; judged across (design §3.3)` (on the Tarot: 15, in
  [709.278, 710.184] s); `no_events` still excludes the interval from its drop-free seconds ("excluded from n").
- **A log whose DSF is ABSENT** cannot count its dropped writes: mode- and armed-dependent results carry the note "DSF
  ABSENT: dropped writes are not counted; judged as if the firmware dropped none (log holes still count)"; the note alone
  changes no verdict.

## The three scored examples

Each holds `SOURCE.json` (url, sha256, size, licence), `bars.yaml`, its sidecar and `verdict.json`, never the log;
the Tarot dir also holds `badge.svg`. CI re-fetches each log by sha256 and requires byte identity with the committed
verdict apart from three leaves it excludes and shape-checks (`tool.python`, `tool.deps.PyYAML`,
`allowlist.run_date_utc`). On 2026-11-09, from the install above, the 0.1.0 Tarot verdict reproduced on every scalar
leaf (363) except `allowlist.run_date_utc`. The committed verdicts below are 0.3.0's: every verdict, n and badge in
them is what 0.2.0 printed.

| Directory | Log | Badge | Exit |
|---|---|---|---|
| [`examples/tarot_x4/`](https://github.com/vihanpatil/SwathKeeper/tree/main/examples/tarot_x4/) | Tarot X4, ArduCopter V4.5.5 | `gates: could not tell · 7/8 measured (post-hoc)` | 1 |
| [`examples/plane_nofix/`](https://github.com/vihanpatil/SwathKeeper/tree/main/examples/plane_nofix/) | ArduPlane V4.7.0-beta5, no GPS fix | `gates: fail · 1/5 measured (post-hoc)` | 1 |
| [`examples/pymavlink_test_bin/`](https://github.com/vihanpatil/SwathKeeper/tree/main/examples/pymavlink_test_bin/) | pymavlink `test.BIN`, ArduPlane V3.8.2-dev | `gates: could not tell · 3/6 measured (post-hoc)` | 1 |

None of the three reads `pass`. The Tarot's 15 dropped writes fall in the first 0.9 s of its log, so its
mode-transition bar (a `must`) reads could not tell and its other seven bars pass. Five of those seven carry the
"judged across" note above, `speed_ceiling_loiter` the sure/wide note, and `no_errors` the excluded-from-n note.

## Measured limits (corpus probe, 2026-11-10)

40 public DataFlash logs: 14 SITL logs from ArduPilot's autotest and 26 from 13 public GitHub repositories, which
by their own content are 15 real-hardware logs, 2 SITL logs, 2 synthetic teaching fixtures and 7 unclassified. 7 are
refused (pre-2015 logs with no timestamped contract record) and 33 judged. With 15 loose-limit bars per log, so that
a PASS or FAIL means the bar was measurable, 130 of 495 verdicts were measurable without the `assume` key and 180 of
495 with it. Why the tool could not tell, in this order: (i) a log that starts at boot has no GPS fix, EKF solution
or home at first, so a whole-log bar is voided by the gap at its start: the whole-log speed bar on 8 of the 14
autotest logs (two hardware logs lost it to mid-log holes instead); scope such bars to armed or to a mode. (ii)
`armed: true` was measurable on 1 of 165 verdicts without the key and on 51 of 75 with it on the 15 logs that have
ARM rows; the 18 logs with no ARM row stay at 0 of 90. (iii) `no_events` never read PASS, 0 of 33: the firmware
reading that lets zero ERR rows count covers 4.5.x releases only, and 18 logs carry ERR rows (the bar fails on any
ERR row unless its code is in `ignore`). (iv) 6 of the 10 real-hardware logs that count drops carry a drop interval,
as do both SITL logs found on GitHub and none of the 14 autotest logs; 7 of those 8 drop only at startup, and a
transition bar allowing only the modes each log used lost 5 of its 19 measurable logs to them. A convenience sample,
one autotest run, ArduCopter-heavy; the mode-scoped probe bar uses each log's dominant mode
(`eval/results/gates_corpus_20261110/`).

**Parameter-following limits, same corpus, 2026-11-11.** Four unscoped bars per judged log, following `WPNAV_SPEED`,
`WP_SPD`, `BATT_LOW_VOLT` and `FS_EKF_THRESH`: 23 of 132 verdicts were measurable without
`limit_before_first_parm_row` and 36 of 132 with it. All 13 it changed went from could not tell to PASS, on four logs
whose startup drops overlap the parameter dump and two with samples at or before the parameter's first row. Most of what stays could not tell is not
the limit's doing. Of the 96 such verdicts with the key, 37 lack the bar's stream and 32 name a parameter the log does
not carry (13 logs carry `WPNAV_SPEED`, 12 `WP_SPD`, none both); among the other 27, 26 name a gap or hole in scope, 6 a
loss that may hide a parameter row, 5 too few samples and 2 a `BATT_LOW_VOLT` of 0, outside `accept` (a verdict can name
several). The `WP_SPD` bar was measurable on no corpus log. The limits are realistic, so the 5 FAILs are measurements
against a waypoint-speed or failsafe parameter in every mode, not findings about a vehicle.

**This project's own flights, 2026-11-10 and 2026-11-11.** 20 SITL logs of the SwathKeeper drone, not public: with a
literal 4.4 m/s ceiling, 7 pass, 12 fail and 1 could not tell, because the flights were commanded at 4, 5 and 6 m/s.
With the ceiling following each log's `WP_SPD` inside the booked range (1.0 to 5.0 m/s) and the key declared, 13 pass,
none fails, and 7 read could not tell: the six flights commanded at 6.0 m/s, outside that range, and one run killed
before it logged a disarm. No verdict there says anything about bird clearance: a DataFlash log carries no bird
(`eval/results/gates_dogfood_20261110/`).

## What this does NOT claim

- The tool comes from a sim-demonstrated drone repo. Its authors have flown nothing real, and that drone's own
  avoidance breached its 3.00 m bar on all three live sim flights (closest approach 0.0393 / 0.0391 / 0.0067 m);
  two passed the gates of the day and were called strikes by a gate written afterwards, the third was
  pre-registered as a possible FAIL, and it failed. The tool is that method, not evidence that the drone works.
- A verdict claims nothing beyond what it prints: these bars, this file (by sha256), this parser version, this date.
  PASS means every measured sample met the bar; between samples it says nothing, except where `containment` judges
  segments, and never across a gap. A PASS says nothing about any vehicle's safety. The tool has published verdicts on
  exactly the three public logs in `examples/`; the probe above ran it on 40 more and on 20 SITL logs of this
  project's own drone, and it reads no other format.
- Before the Tarot bars were written, the authors had seen its modes, error count, GNSS status, peak altitude and
  first battery and EKF rows. The build's draft run printed the measured values of six of the eight bars, and the
  first registered verdict printed all eight before the file was re-registered. So the Tarot results are
  demonstrations, not tests. Its bars were registered after the log existed (post-hoc), and its bars, sidecar and
  verdict were first committed together, so git orders nothing there. A 142 s low hover was expected to pass them,
  and under 0.2.0 it does not: the dropped writes in its first 0.9 s leave its mode-transition bar unable to tell.
- Pre-registration binds a run to a text, not a date (step 3); the sidecar's `written_utc` is recorded as untrusted.
- A limit that follows a parameter judges the LOGGED configuration only. ArduPilot does not log every change (read at
  tag Copter-4.5.5): a value set in memory without a save, which is what a script's `param:set` does, writes no PARM
  row; a row can be refused without being counted in DSF.Dp, for example one written from another thread while the
  startup dump runs; and drops after the last DSF row are never reported. A saved change can take effect before its row
  is written. None of this is visible to the tool, with or without the assumption. A PASS says the vehicle obeyed the
  values the log shows, inside the range the author accepted, and nothing about whether those values were safe.
- A truncated log reads as a shorter flight; only a pinned log hash ties a verdict to a file. DataFlash has no
  checksum, so a corrupted record with an intact header decodes as values. Never exercised on: a real EKF2 log with
  a core column, a multi-home log, or `LOG_BACKEND_TYPE` other than 1. The three scored examples contain no
  mid-flight Dp rise (one probe log does).

The why, with each rejected alternative: [`docs/design/GATES_TOOL_DESIGN.md`](https://github.com/vihanpatil/SwathKeeper/blob/main/docs/design/GATES_TOOL_DESIGN.md).
What the build measured, and the open items: ADR-023 and its amendments in [`docs/DECISIONS.md`](https://github.com/vihanpatil/SwathKeeper/blob/main/docs/DECISIONS.md).
