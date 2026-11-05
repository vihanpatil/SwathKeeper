# The evidence-gate tool: design note (it becomes an ADR once built and scored)

**Status: DESIGN. Nothing is built and nothing has been scored.** Option C, step 1 (ADR-022 amendment 4;
`docs/ROADMAP.md` *Next up*). The build is scored against this note, the same way ADR-021 was scored
against [`DEPTH_SEGMENTER_DESIGN.md`](DEPTH_SEGMENTER_DESIGN.md). Every number here is either measured
(with how and when) or labelled a budget. **Owner:** lead (design) → software-engineer (steps 2-5) →
qa (each step). The ADR is written AFTER the tool is built and scored, and it carries its cut.

**Revision 2 (2026-11-05, after QA review G211–G227; QA's verdict on revision 1: "do not build as written").**
Changed: an `integrity` record and a per-stream gap rule (§2); `series_bound` cut to `{channel, bound, limit}`,
every sample, no `stat`/quantiles/`per_window`; a fixed decision order with NaN and gaps as EI; `min_n ≥ 1`;
B8 counts drop-free seconds; mode names validated per vehicle; every GNSS/BAT instance and EKF core (NKF9
too); arming's initial state and empty `events` ABSENT until cited; prereg auto-discovered, `(post-hoc)`;
badge word `could not tell`; demo limits from the log's PARM; a strict YAML loader; CI installs the package;
step 5 diffs every result. Cut: `attitude`, `mission`, the logged fence polygon. Dispositions: §12.

**The one sentence.** `pip install swathkeeper-gates[ardupilot]` and three commands take a stranger's
`.bin` and a YAML file of bars hashed before the run, and produce a JSON verdict and an exit code. In
that verdict "could not tell" is a fourth word, never a green, and every acknowledged red is named exactly.

**The promise this keeps.** The private one-pager (`docs/outreach/ONE_PAGE_EXPLAINER.md`, gitignored)
says: *"This tooling does not exist for your log format today."* The tool makes that sentence false
for ArduPilot DataFlash, and for PX4 ULog if the stretch adapter ships. It makes no other change to that page.

## 0. Facts this design rests on (measured 2026-11-05)

- **No gate in this repo emits JSON** (ROADMAP *Next up*, item 3). The verdict format is new.
- **The house exit convention is 0 / 1 / 2**: `scripts/check_live_flight_log.py` 0 valid, 1 invalid, 2 argparse's
  refusal; `scripts/predict_bird_visibility.py` (617-624, ADR-016): a refusal "is neither the PASS (0) nor the FAIL (1)".
- **The declared-red rule has three failure modes**, undeclared, vacuous and expired (`tests/test_known_red_allowlist.py`),
  because two undeclared reds rode behind one declared red for 16 days.
- **Installed** (`.venv`, `importlib.metadata`): pymavlink **2.4.50**, pyulog **1.3.0**, PyYAML **6.0.3**, Python **3.12.12**.
- **The parsers fail quietly** (QA, measured): DFReader skips a zeroed 400 kB block with "Skipped 400014 bad bytes"
  and goes on (records 99,521 → 91,839, an 11.3 s hole in POS/BAT/GPS/XKF4), keeps no skip counter, and defaults to
  a Plane (`DFReader.py:793`). PyYAML `safe_load` keeps the LAST duplicate key; `NO`/`ON` load as bools, `1e3` as a string.
- **CI's `planning-and-eval` job installs `requirements-eval.txt` only** (`ci.yml:59`: numpy, scipy, markdown).
- **tests:src = 26,320 / 6,854 = 3.84** against the 3.70 cap (ADR-022 am. 1). The ratio is OVER.

## 1. The package

| Decision | Why (one sentence) | Rejected |
|---|---|---|
| `src/swathkeeper_gates/`, distribution `swathkeeper-gates` | A new name touches no ADR-011 identifier and says what it is | Inside `fieldguard_planning`: a stranger would install a drone stack to read a log |
| Core = stdlib + PyYAML; `[ardupilot]` = pymavlink, `[px4]` = pyulog | The core (contract, bars, verdict) parses no binary, so it needs no parser | pymavlink in the core: it taxes PX4 users and direct callers |
| **It imports nothing from `fieldguard_planning`, and the reverse holds too** | What transfers is the doctrine (windows, segments, exact-set), not the `/fg`-shaped functions | Reusing the gate functions: the wheel would need `fieldguard_planning`, numpy and the scenario code |
| Nothing under `scripts/`, `tests/` or `examples/` goes into the wheel | The wheel is the tool and nothing else | A "batteries" wheel with the demo inside |
| One root `pyproject.toml`, setuptools ≥ 61, `packages.find where=["src"] include=["swathkeeper_gates*"]` | The include filter keeps `src/fieldguard_planning` out without moving it | hatch/poetry: a second build tool for one package |
| Parsers pinned `==` (`pymavlink==2.4.50`, `pyulog==1.3.0`); `PyYAML>=6.0.3,<7` | The parser *is* the instrument; the YAML loader is ours (§3.1) | `==` everywhere breaks environments over a non-instrument |
| `requires-python = ">=3.10"`, only if step 5's CI tests 3.10 and 3.12 | A floor nobody has run is a claim; otherwise `>=3.12` | No floor |

The verdict records the versions that actually ran (§5): the pin is a promise, the verdict its proof.

```
pyproject.toml                  # declares swathkeeper-gates and nothing else; console script below
src/swathkeeper_gates/
  __init__.py                   # __version__, CONTRACT = "swathkeeper-flightlog/1.0"
  contract.py                   # FlightLog: streams, PRESENT/EMPTY/ABSENT, integrity, gap rule, monotone check
  adapters/__init__.py          # sniff magic bytes -> adapter; missing extra -> refusal naming the extra
  adapters/ardupilot.py         # pymavlink DFReader -> FlightLog
  adapters/px4.py               # pyulog -> FlightLog (stretch; ships only with its test, §9)
  bars.py                       # strict YAML loader, closed schema, sha256, the five bar kinds
  allowlist.py                  # declared-red YAML: load, expiry, exact-set comparison
  verdict.py                    # assemble the JSON, the exit code, the badge string
  cli.py                        # `swathkeeper-gates run | prereg | inspect`
```

## 2. The flight-log contract: `swathkeeper-flightlog/1.0`

1. **One clock.** `t_s` is source boot time in seconds (DataFlash `TimeUS`, ULog `timestamp`, × 1e-6). Within each
   **contract stream and instance** it must be non-decreasing, else a **refusal** naming stream, instance and row.
   Non-contract types are not checked: the Plane log's FMTU steps backwards and must not refuse it. No re-sorting.
2. **SI units, degrees for angles and lat/lon, one source message per field**, named in `source`. No fallback.
3. **Every stream is PRESENT** (n ≥ 1 rows), **EMPTY** (zero rows, legal *only* for `events` and only where the
   adapter cites that the source writes the record whenever the event happens), or **ABSENT** with a reason. A
   missing column in a PRESENT stream is ABSENT. **ABSENT is never 0, never NaN-filled, never a default.**
4. **No inference.** Arming state before the first ARM row is **ABSENT**, and zero ERR rows make `events`
   **ABSENT**, until step 2 cites AP_Logger at the logged firmware for both (§11). Revision 1's inference is withdrawn.
5. **Integrity is measured and printed:** `bytes_skipped` = file size − Σ decoded record lengths (the adapter sums;
   DFReader keeps no counter), `dsf_dropped_max` = max `DSF.Dp` with the DSF row times, and pyulog's `dropouts`
   [(t_s, duration_s)]. **The gap rule:** for each (stream, instance) a bar reads, with median sample period p, any
   gap inside the bar's scope longer than **max(1 s, 5p)** makes that bar EI, its [t0, t1) printed. Instances are
   separate streams (XKF4's two cores interleaved measure p = 0.0 s; each alone, 0.1 s). *Worked example, the demo
   log:* POS, BAT and each XKF4 core p = 0.1 s (max gap 0.100 s), GPS p = 0.2 s (max gap 0.221 s), so the threshold
   is 1 s and nothing fires. `DSF.Dp` is **15** at the first DSF row (710.18 s; ~1 Hz, 141 rows) and never rises,
   so all 15 drops lie in [709.28, 710.18] s, armed and pre-takeoff, invisible to the gap rule because POS kept its
   0.1 s cadence. On QA's zeroed-block copy the rule fires on the 11.2-11.4 s gaps in every series stream.
6. **NaN is not a value.** A NaN input sample in scope makes the bar EI (`min([1, nan])` is 1 and `nan < x` is False,
   so NaN never violates). ArduPilot writes NaN on purpose (`POS.RelOriginAlt`); the demo has 0 in every bar column.

| Record | Fields | ArduPilot DataFlash | PX4 ULog topic | ABSENT when |
|---|---|---|---|---|
| `meta` | vehicle, firmware, hardware, `records_decoded`, per-type counts | `MSG`/`VER`; **vehicle from the firmware string only** (`ArduCopter`, `ArduPlane`, `ArduRover`, `ArduSub`), never DFReader's default | `msg_info_dict`; vehicle from `MAV_TYPE` | unresolved: `vehicle` ABSENT → every mode-scoped bar and B7 EI |
| `integrity` | rule 5 | rule 5 | `dropouts` | no DSF rows: `dsf_dropped_max` ABSENT → B8 EI |
| `position` | lat, lon, alt_amsl_m, alt_rel_home_m | `POS` (Lat, Lng, Alt, RelHomeAlt) | `vehicle_global_position`; rel = alt − `home_position.alt` | no POS (the Plane log has none); rel ABSENT with no home |
| `velocity` | groundspeed_mps **per GNSS instance** | `GPS.Spd`, every `I` | `vehicle_gps_position.vel_m_s`, every multi_id | no GNSS record |
| `mode` | events (t_s, name, num) | `MODE` ModeNum, names from pymavlink's table for the resolved vehicle | `vehicle_status.nav_state` changes, a table pinned in the adapter | zero MODE rows |
| `arming` | events (t_s, armed), initial state | `ARM.ArmState`; before the first row ABSENT (rule 4) | `vehicle_status.arming_state`, sampled (2 = armed), measured from row 1 | no ARM rows |
| `gnss` | fix_type, nsats, hdop, gps_week/ms **per instance** | `GPS`, every `I` (the Plane log has only `I=1`, GPS_PRIMARY=1) | `vehicle_gps_position`, every multi_id | no GNSS record |
| `battery` | voltage_v, current_a **per instance** | `BAT`, every `Inst` | `battery_status`, every multi_id | no BAT. A logged 0.0 V is a value |
| `ekf` | vel/pos/hgt/mag ratio **per core** | EKF3 `XKF4` by `C`; EKF2 `NKF4` = core 0, `NKF9` = core 1 (test.BIN: no `C`) | `estimator_status`, every multi_id | none of those |
| `events` | (t_s, kind, code, text) | `ERR` (Subsys, ECode) → `error`; zero rows ABSENT (rule 4) | `failsafe_flags` rising edges → `failsafe`; logged messages with `log_level − 48 ≤ 3` → `error` (pyulog 1.3.0 gives the raw ASCII byte: 52 = WARNING) | unmappable; a level byte outside `'0'..'7'` |
| `home` | lat, lon, alt_amsl | `ORGN` Type 1 | `home_position` | none |
| `params` | name → [(t_s, value)] | `PARM` | initial + changed parameters | none |
| `fence` | circle_radius_m, alt_max_m | `PARM` FENCE_ENABLE/TYPE/RADIUS/ALT_MAX: bit 1 alt max, bit 2 circle (URL cited in the adapter); bit 4 (polygon) **printed as not judged** — v1 reads no `FNCE` | ABSENT | disabled, unlogged, or changed in flight |

**Mode windows** are `[t_mode_i, t_mode_{i+1})`; the last ends at the log's last `t_s`. **Armed intervals** are
built the same way from `arming`, and are ABSENT before the first ARM row.

## 3. The bars

### 3.1 The YAML schema: `swathkeeper-bars/1.0`

```yaml
schema: swathkeeper-bars/1.0
contract: swathkeeper-flightlog/1.0    # major version must match the tool's, else refusal
bars:
  - id: batt_floor                     # [a-z0-9_]{1,40}, unique in the file
    kind: series_bound                 # one of the five kinds in 3.3
    severity: must                     # must | should
    provenance: {text: "log PARM BATT_LOW_VOLT; instantaneous, stricter than the 10 s timer", param: BATT_LOW_VOLT}
    scope: {armed: null, modes: null}  # both keys REQUIRED; armed: true | null; modes: [names] | null
    min_n: 30                          # REQUIRED integer >= 1, no default
    params: {channel: battery.voltage_v, bound: floor, limit: 18.6}
```
**The loader is strict.** A PyYAML `SafeLoader` subclass refuses a duplicate key at any depth (`limit: 18.6` then
`limit: 0` must not load 0 behind a reader who sees 18.6). The schema is **closed**: an unknown key refuses. Numbers
must be int or float and **not bool** (`1e3`, a string under YAML 1.1, refuses; so does `yes`). Mode names must be
strings (`NO`/`ON` load as booleans and refuse) **and** appear in the resolved vehicle's mode table, else refusal;
with the vehicle unresolved they cannot be checked and every mode-scoped bar reads EI, never NA. `armed: false`
refuses (no v1 bar wants disarmed-only, and it reads as "don't care"). `provenance.param` prints the log's own PARM
value beside the limit and any disagreement; it never changes the verdict.

### 3.2 How a bar is decided. The order is fixed; the first rule that matches wins.

1. **EVIDENCE_INSUFFICIENT** if an input stream or column is ABSENT, or the scope needs `arming`/`mode` and it is
   ABSENT, or modes are named and `vehicle` is ABSENT. A mode scope on a log with no MODE is **never** NA.
2. **NOT_APPLICABLE** if the scope stream is PRESENT and no window matches. The absence is *measured*.
3. **FAIL** if any judged sample (non-NaN, any instance or core) or judged B6 segment violates the bar, **whatever
   n is**. A measured red is red, and no EI below can mask it.
4. **EVIDENCE_INSUFFICIENT** if a NaN lies in scope (rule 6), a gap fires (rule 5), or n < `min_n`.
5. **PASS.**

For EI and NA, `measured` is `null` and the note carries n, the reason and any gap: a thin-sample number is never
printed where a reader could quote it. **Every sample, every instance:** `bound: floor` passes only if every sample in
scope is ≥ `limit`, `ceiling` only if every one is ≤ it. Every-sample *is* the worst window, so the house per-window
lesson — the 2026-08-25 take's whole-flight median 3.417 m/s passed a 5.0 m/s booking while the encounter window
read **9.012 m/s** (ADR-020 am. 3) — is kept by construction: a 5.0 ceiling fails on the 9.012 sample however the
windows pool. The verdict prints the instances/cores present and used, and the worst one's value.

### 3.3 The catalogue: 8 bars over 5 kinds (the v1 ceiling)

| # | Bar (kind) | What it asks | Denominator n | EI / NA | Demo-MUST |
|---|---|---|---|---|---|
| B1 | `alt_floor` (`series_bound`, `position.alt_rel_home_m`, floor) | Never below X m over home in scope | position rows in scope | rel-alt ABSENT (no home) / NA: no matching window | — |
| B2 | `speed_ceiling` (`series_bound`, `velocity.groundspeed_mps`, ceiling) | Never faster than X in the named modes, every sample of every GNSS instance | GNSS rows in scope, and the window count | MODE or vehicle ABSENT when modes are named / NA: no window of the mode | **yes** |
| B3 | `battery_floor` (`series_bound`, `battery.voltage_v`, floor) | No sample of any pack below X | BAT rows in scope, all instances | BAT ABSENT | **yes** |
| B4 | `ekf_ceiling` (`series_bound`, one `ekf.*_ratio` per bar, ceiling) | No innovation ratio above X on **any logged core** | EKF rows × cores in scope | EKF ABSENT. AP SV/SP/SH/SM and PX4 test ratios are **not** declared commensurable | — |
| B5 | `gnss_quality` | A row qualifies if fix ≥ F and sats ≥ N; FAIL if a run of non-qualifying rows on any instance spans > `max_outage_s` (0 = every row) | GNSS rows in scope, all instances | GNSS ABSENT; missing rows are the gap rule's (EI), never an outage | **yes** |
| B6 | `geofence` (`containment`) | Every **segment** between consecutive position samples stays inside the inclusion area (a YAML polygon, or the log's home cylinder) and outside every YAML exclusion circle; every sample at or below `alt_max` when the fence has one (YAML or FENCE_ALT_MAX). Reports the minimum signed margin in metres | position segments in scope | fence ABSENT for `source: log`; home ABSENT for a cylinder; a segment across a gap is **not judged** → EI | — |
| B7 | `mode_transitions` | Every observed transition is in `allowed: [[from, to], ...]` (`"*"`, `<start>`; names validated as in 3.1) | transitions observed | MODE or vehicle ABSENT | **yes** |
| B8 | `no_events` | Zero `events` of the listed kinds outside `ignore` codes | **drop-free seconds of scope** (minus DSF intervals in which Dp rose, `dropouts`, fired gaps); PASS needs ≥ `min_n` s | events ABSENT (incl. zero ERR rows until cited); `dsf_dropped_max` ABSENT | **yes** |

B6's cylinder and `alt_max` are exact on samples (on a straight chord, distance from a centre and altitude peak at an
endpoint); the concave polygon and exclusion circles need segments — R8's lesson: a 0.5 m point sweep false-passed
**16 of 1420** unsafe sloped legs (ADR-022 am. 2/3). B6 never bridges a gap: a chord across a hole is a guess about
the path. B5 judges every instance, so a configured second receiver that never gets a fix fails B5 with its `I`
named. B4's all-cores rule is **decided** (losing: primary-only from `XKF4.PI`; a failing standby core is still a
finding). **Demo-MUST** means the bar exists before the first public post; B1, B4, B6 can follow.

### 3.4 Cut from v1, with the losing case

- `closest_approach` as its own bar (losing case: it is this repo's signature gate): folded into B6's exclusion
  circles, because the minimum margin to a circle *is* the closest approach.
- **Revision 2:** `stat`/`op`, quantiles and `per_window` (losing case: a p95 forgives one glitch sample; but
  `{stat: max, op: ">="}` inverts a bar, a pooled median repeats the 0.683× mistake, and a rule-3/4 swap survived
  the old test plan); B5's percent-of-rows (a stat by another name); the `attitude` and `mission` streams (losing
  case: `inspect` showed them; no bar read either); the fence polygon from `FNCE` (losing case: FENCE_TYPE 7 sets
  the bit; but the demo logs no FNCE rows, so it would ship untested).
- Also cut: tilt, vibration, clipping, mission-progress, waypoint and terrain-relative bars. Each returns only with a cut.

## 4. Pre-registration

`swathkeeper-gates prereg --bars bars.yaml [--log FLIGHT.bin]` writes `bars.yaml.prereg.json` {schema:
swathkeeper-prereg/1.0, bars_sha256, tool_version, written_utc, log_sha256?}, hashed over the file's **raw bytes**
(rejected: canonicalised YAML, code that could make two texts hash equal). It refuses to overwrite a sidecar.

**`run` discovers `<bars>.prereg.json` beside the bars file**, as `check_live_flight_log.py` finds
`<stem>.booking.json`; `--prereg` may name another path. Status words: **`HASH_MATCH`** (both hashes printed),
**`NOT_REGISTERED`** (no sidecar: suffix `(unregistered)`), **`MISMATCH`** (refusal, both hashes printed). A
malformed sidecar refuses. A pinned `log_sha256` refuses any other file (closing *log shopping*) and proves the log
existed when the bars were registered, so badge and verdict print **`(post-hoc)`**. Unpinned HASH_MATCH: no suffix.

**What this proves, and what it does not.** It binds a run to a text, not to a date: the date claim is the sidecar's
git commit, which a committer can forge. **v1 RECORDS, it does not ASSERT.** The verdict prints `log_gpst_start`
(first row with GWk > 0, labelled **GPS time, not UTC**: the 18 s leap offset is not applied, and no-fix rows carry
GWk 0) and the sidecar's `written_utc`, labelled untrusted; step 5's Action adds the commit time. The demo log was
flown 2024-08-05 (its filename), so its bars necessarily postdate it: the demo is `(post-hoc)` and says so.

**The blindness ledger for the demo log, disclosed.**
- *Lead's selection pass and the researcher:* message counts; modes AltHold → Loiter; one disarm; zero ERR; GNSS
  status 4, 26-27 sats on the rows sampled. **Correction:** revision 1 said "4 sparse GNSS samples"; the log has
  **709 GPS rows at ~5 Hz** (QA). The researcher reported 29 sats and a 4.3 m maximum above home.
- *QA's review:* the first-row BAT.Volt (**24.34 V**, pre-takeoff), the first XKF4 rows of both cores, the first GPS
  Spd (0.021 m/s), the first POS row, DSF.Dp, the EV ids, and PARM FENCE_RADIUS 150, LOIT_SPEED 1250, WPNAV_SPEED
  500, BATT_LOW_TIMER 10, BATT_FS_VOLTSRC 0, LOG_DISARMED 0.
- *Lead's revision pass:* PARM only (BATT_LOW_VOLT 18.6, BATT_CRT_VOLT 17.7, FENCE_ENABLE 1, FENCE_TYPE 7,
  FENCE_ALT_MAX 120, FENCE_MARGIN 2, FLTMODE1-6 = 0,0,2,2,5,5, FS_EKF_THRESH 0.8) and structure (row counts, sample
  periods, maximum gaps, the ARM row). **Nobody read a minimum or maximum of any blind bar.**

So **B1, B5, B7 and B8 are not blind** (demonstrations, not evidence); **B2-in-Loiter, B3, B4 and B6's margin are
blind** (first rows only). **Demo limits come from the log's own PARM** — what the vehicle flew:
- B2: Loiter, ceiling **12.5 m/s** (LOIT_SPEED 1250 cm/s; WPNAV_SPEED governs neither AltHold nor Loiter, and AltHold
  has no speed parameter, so no AltHold speed bar). B3: floor **18.6 V** (BATT_LOW_VOLT) — an **instantaneous**
  floor, stricter than the firmware's failsafe, which acts only after BATT_LOW_TIMER = 10 s (BATT_FS_VOLTSRC 0 = raw volts).
- B6: cylinder **150 m**, alt_max **120 m** (FENCE_RADIUS, FENCE_ALT_MAX); the polygon bit printed as not judged.
  B7: among FLTMODE {Stabilize, AltHold, Loiter}. B5 (fix ≥ 3, sats ≥ 6, `max_outage_s: 0`) and B8: author's choice.
- The template (`24_safety_setup.param`: FENCE_RADIUS 350, commented "start with a 150m fence radius"; `10_battery`,
  `22_flight_modes`) is cited **only as the author's intent**; 350 vs 150 is printed.
- **Pre-registered consequences of rule 4:** the only ARM row is the disarm at 836.27 s (LOG_DISARMED 0 suggests
  logging began at arming — uncited), so demo bars use `armed: null`; unless step 2 cites ERR semantics, demo B8 (a
  must) reads EI and the demo prints `could not tell`. That is reported, not tuned.

## 5. The verdict: `swathkeeper-verdict/1.0` (JSON), its exit codes and its badge

Keys: `schema`, `contract`; `tool` {version, python, deps that ran}; `source` {path, sha256, size_bytes, format,
adapter, vehicle, firmware, hardware, duration_s, records_decoded, log_gpst_start}; `integrity`; `streams` (the
`inspect` map); `bars` {path, sha256, schema}; `prereg` {status, sidecar_sha256, log_sha256_pinned, post_hoc};
`results`, one per bar in file order {id, kind, severity, verdict, measured, bar {channel, bound, limit}, n, min_n,
scope, instances_used, worst_instance, gaps, note, provenance, param_in_log}; `allowlist` {path, sha256,
run_date_utc, declared, red, undeclared, vacuous, expired}; `exit_code`, `badge`, `refusal` (null or a reason; on a
refusal `results` is empty and the file is still written when `--out` is writable).

A verdict is `PASS | FAIL | EVIDENCE_INSUFFICIENT | NOT_APPLICABLE`. **Red** = FAIL (either severity) or EI/NA on a
**must** bar; a `should` EI/NA is printed only. **m/n measured** = bars with a PASS or FAIL, of n total.

| Outcome | Exit | Badge word |
|---|---|---|
| no red, ≥ 1 PASS, nothing declared | **0** | `pass` |
| every red matches a live declaration exactly (bar and verdict), ≥ 1 PASS | **0** | `pass` (+ `k declared (f FAIL, e EI)`) |
| any undeclared FAIL, or a declaration that is vacuous, expired or verdict-mismatched | **1** | `fail` |
| exit 1 otherwise: undeclared must EI/NA, or zero PASS | **1** | `could not tell` |
| **refusal** (list below) | **2** | `refused` |

**Badge:** `gates: <word> · m/n measured[ · k declared (f FAIL, e EI)][ (post-hoc) | (unregistered)]`. One must
PASS beside seven should-EI reads `gates: pass · 1/8 measured`; the all-ABSENT `sample.ulg` demo reads `gates: could
not tell · 0/8 measured`, never `fail`. Exit codes are unchanged from revision 1.

**Refusals (exit 2):** missing log path; unwritable `--out` (reason to stderr); unknown magic (not `A3 95`, not
`ULog`); parser extra not installed (named); decode failure before any record; a non-monotone contract stream; bars
YAML invalid — duplicate or unknown key, non-numeric or bool number, `min_n` < 1 or non-integer, `armed: false`,
unknown kind, zero bars, zero `must` bars, duplicate ids, contract major mismatch, a mode name not in the resolved
vehicle's table; malformed sidecar, prereg MISMATCH, pinned log hash mismatch; declared YAML invalid (empty `reason`,
bad `expires`), a declaration naming no bar, a declared PASS, or a declared EI/NA on a `should` bar (never red). One
code with the reason in the JSON replaces the repo's 3 and 4; a typo in a declaration cannot turn a run green.

## 6. The declared-red allowlist (the KNOWN_RED rule, generalised)

```yaml
schema: swathkeeper-declared/1.0
declared:
  - {bar: batt_floor, verdict: FAIL, reason: "names the evidence, not the symptom", expires: 2027-01-31}
```
- The set {(bar, verdict)} of reds must **equal** the set of live declarations; leftovers on either side are listed
  in `undeclared` or `vacuous`. `verdict` is FAIL, EVIDENCE_INSUFFICIENT or NOT_APPLICABLE.
- An entry with `run_date_utc >= expires` is **expired** (the test's `today >= expires`): it declares nothing, its
  red counts as undeclared. The run date is printed, so the same inputs later can and should give a new verdict.
- **The allowlist is not pre-registered** (acknowledgement follows a finding by definition); its defence is that
  its hash and count are in the verdict and `k declared (f FAIL, e EI)` is on the badge.

## 7. The CLI

```
swathkeeper-gates inspect --log FLIGHT.bin                      # a stranger's first command
swathkeeper-gates prereg  --bars bars.yaml [--log FLIGHT.bin]   # writes bars.yaml.prereg.json
swathkeeper-gates run     --log FLIGHT.bin --bars bars.yaml [--declared declared.yaml] \
                          [--prereg PATH] --out verdict.json   # sidecar auto-discovered
```
`inspect` prints the verdict's `source`, `integrity` and `streams` blocks (one code path; states, n, instances,
t-range, median period, mode windows, armed intervals; exit 0 or 2). `run` requires `--out`, exits per §5. No network.

## 8. The foreign logs

**Fixture rule.** No third-party log is committed (the demo's repo is GPL-3.0, this one Apache-2.0). Each is fetched
at demo/CI time from a SHA-pinned URL into `examples/<name>/SOURCE.json` {url, sha256, size_bytes, licence} and
checked: `curl -fL "$url" -o log && echo "$sha256  log" | sha256sum -c`. Unit tests never fetch.

| Role | Log | Verified 2026-11-05 (own download; QA's matches) |
|---|---|---|
| **Demo (ArduPilot)** | ArduPilot/MethodicConfigurator `@3d14a143`, `.../vehicle_templates/ArduCopter/Tarot_X4/2024-08-05 18-48-54.bin`: a real Tarot X4, ArduCopter V4.5.5, Pixhawk6X, GPL-3.0 | **5,197,824 B**, `a3 95`, sha256 `a4dc00507cc8448c0ce320279e70040de3af3439dd4c3dd5363a7fa388609108`. 141.9 s, 73 types, MODE ×2, ARM ×1 (the disarm, 836.27 s), no CMD/FNCE, ERR 0, GPS 709 rows (`I=0`), BAT `Inst 0`, XKF4 cores 0-1, DSF.Dp 15 |
| Negative (ArduPilot) | ArduPilot/plotjuggler-apbin-plugins `@43a8d812`, `tests/logs/00000001.BIN`: ArduPlane V4.7.0-beta5, LGPL-3.0 | **1,933,312 B**, `a3 95`, sha256 `28dcbac522ceb75eee10f6af37b0d6e342c1dc79e2be1a9f766fe18a14336766`, 52.7 s, 48,341 records. GPS only `I=1`, no fix; no POS, no ORGN; FMTU non-monotone. B5 reads **FAIL** (measured no-fix rows); B1/B6 EI |
| Old message names | ArduPilot/pymavlink `@544d9016`, `tests/test.BIN`: ArduPlane V3.8.2-dev | **65,536 B**, `a3 95`, sha256 `a51f040b…c2bf4`, 1.05 s. EKF2 as NKF4 + **NKF9**, no `C`; no ARM, no VER: step 2's "ABSENT map" check |
| PX4 stretch, scoring | PX4/pyulog `@0b392f84`, `test/sample_px4_events.ulg` (BSD-3-Clause) | **1,563,146 B**, `ULog\x01\x12\x35`, sha256 `4b43a23a…c96678d971451e3d7e`, 31.1 s. **SITL**, armed, nav_state {4, 5, 17}; has GNSS, battery, `failsafe_flags`, `home_position` |
| PX4 stretch, ABSENT demo | PX4/pyulog `@0b392f84`, `test/sample.ulg` | **4,053,364 B**, sha256 `81952e60…a558`, 69.0 s, AUAV_X21. `arming_state` 0 on all 294 rows; no GNSS, no battery: most bars EI by design (QA did not download it) |

Low altitude, a short flight, no mission and no AUTO window are honest features of the demo log. An AUTO-scoped
`should` speed bar reads NOT_APPLICABLE, visibly, because MODE proves there was no AUTO: the fourth word, not a failure.

## 9. Test plan under the tests:src cap

All four files live directly in `tests/`, so CI's `discover -s tests` and the KNOWN_RED child run collect them
(rejected: a `tests/swathkeeper_gates/` root the allowlist does not walk). **CI edit, required:** `pip install -e
.[ardupilot]` in `planning-and-eval`, so the tests neither fail to import (an undeclared red) nor hide behind
`skipUnless` (a green over nothing). Every file is **red-first**: each assertion is shown failing against its mutant.

| File | Proves (the mutation that must turn it red) |
|---|---|
| `test_gates_adapter.py` | A synthetic DataFlash file written by the test (FMT + POS/GPS ×2/MODE/ARM/BAT ×2/XKF4 ×2 cores/NKF4+NKF9/ERR/DSF/PARM, `struct`, no third-party bytes):<br>• each stream from its §2 message; BAT left out → ABSENT, never 0 (mutant: default 0.0);<br>• a backwards TimeUS in a contract stream refuses, a backwards FMTU does not (mutants: sort; check all types);<br>• a zeroed block → `bytes_skipped` > 0 and the gap printed; NKF9 read as core 1; GPS `I=1` alone PRESENT (mutants: NKF4 only; instance 0 only);<br>• no ARM before the first row → initial state ABSENT; a Copter firmware string gives Copter names (mutants: inferred; DFReader default).<br>PX4 ships **only** if its synthetic ULog case (incl. the level byte 52) fits in this file |
| `test_gates_bars.py` | For each kind: PASS clean, FAIL after a one-sample mutation. Plus: **a thin sample with a violation reads FAIL**, not EI (mutant: rules 3/4 swapped); EI never prints PASS or a number; NaN → EI (mutant: plain `min`); a 2 s hole → EI with the gap; the worse of two BAT instances fails; deleting MODE turns NA into EI; a misspelt mode, `NO`, a duplicate key, `1e3`, `min_n: 0` refuse; B6: a concave segment with both ends inside FAILs (mutant: points only), a chord across a gap is EI (mutant: bridge), alt_max judged; B8 below `min_n` drop-free seconds reads EI (mutant: count rows) |
| `test_gates_verdict.py` | The §5 table row for row, badge words included (`could not tell` on all-EI; `m/n measured`); exact-set over undeclared, vacuous, expired and mismatch (mutant: subset); a declared PASS and a declared should-EI refuse; required JSON keys; `PASS` never on an EI/NA result |
| `test_gates_cli.py` | In a subprocess: `prereg` then `run` → HASH_MATCH with the sidecar **auto-discovered** (mutant: `--prereg` required); one edited byte → 2 with both hashes; a pinned log hash refuses another log and prints `(post-hoc)`; zero bars, a missing extra (with the hint), a missing log path and an unwritable `--out` → 2; `inspect` prints the ABSENT map; an AST scan finds no import across the two packages in either direction |

The live gate on foreign bytes is **not** a unit test: it is step 2's committed `examples/tarot_x4/` (SOURCE.json,
bars.yaml, sidecar, verdict.json) and step 5's CI job, which fetches and sha256-checks **all three ArduPilot logs**
and diffs `results[*].{verdict,n}` against each committed verdict, so a `should` bar sliding PASS → EI is caught.

**Budgets** (estimates): src ≤ **1,100 lines** (contract + integrity 170, ardupilot 230, px4 150, adapters/init 30,
bars + loader 250, allowlist 60, verdict 110, cli 90, init 10), ≤ 950 without PX4; tests ≤ **950** in four files.

**The ratio is measured over `src/**/*.py`** (ADR-022 am. 4: "tests:src counts its src and tests"; CLAUDE.md,
`scripts/state.sh` and `scripts/gates.sh` say so from this revision). Projected (26,320 + 950) / (6,854 + 1,100) =
**3.43**, or **3.49** without PX4. **It falls by dilution, not by discipline**: over `src/fieldguard_planning/*.py`
alone it reads 27,270 / 6,854 = **3.98**. No test file is retired, so each step's commit is measured by
`scripts/state.sh` and a commit reading OVER retires a test file in the same commit (step 2 alone: 26,570 / 7,204 = 3.69).

## 10. What this tool does NOT claim (the README reuses this section)

- It comes from a **sim-demonstrated** drone repo. Its authors have flown nothing real, and the drone's own
  avoidance breached its 3.00 m bar on all three live flights (CPA 0.0393 / 0.0391 / 0.0067 m). The tool is the
  method that caught that, not evidence that the drone works.
- A verdict claims **nothing beyond what it prints**: these bars, this file (by sha256), this parser version, this
  date. PASS means every measured sample met the bar; between samples it says nothing, except where B6 judges
  segments, and never across a gap. It has run on **exactly the logs in §8**, and on no other vehicle or format.
- Pre-registration binds the run to a text, not a date (§4). EKF ratios from two autopilots are not comparable.

**QA's public-demo wording, verbatim (2026-11-05):** "One public ArduCopter log we did not fly. Before writing bars
we had seen its modes, error count, GNSS status, peak altitude and first battery/EKF rows, so those results are
demonstrations, not tests. Bars were registered after the log existed (post-hoc). Remaining limits come from the
owner's parameter template, which disagrees with the loaded fence (350 vs 150 m); a 142 s low hover is expected to
pass them. The one real-log FAIL shown is a second public ArduPlane log with no GPS fix."

**The sentence the posts use** is QA's, with the one clause §4 made false replaced: "…Remaining limits come from the
vehicle's own logged parameters (fence 150 m, Loiter speed 12.5 m/s, battery 18.6 V), not the owner's template,
which says 350 m for the fence; a 142 s low hover is expected to pass them. …" (the other sentences unchanged).

## 11. Open: least sure, settle these in the build and do not guess

1. **Firmware assumptions — to be cited or demoted in step 2** (QA's list, verbatim): ARM is written only on a state
   change. ERR is written unconditionally. `RelHomeAlt` before home is set. GPS rows are still written during an
   outage. The meaning of SV/SP vs FS_EKF_THRESH. GWk/GMS is GPS time, 18 s off UTC (and no-fix rows carry GWk 0).
   The startup MODE row is a logger write, not a transition. FENCE_TYPE 7 includes the polygon bit, but no FNCE
   polygon is logged. *(Demoted now: 1-2 by rule 4, 6 by `log_gpst_start`, 8 by the cut; B4's limit waits on 5.)*
2. **The demo's weak pre-registration**: post-hoc, four of eight bars not blind, B8 possibly EI (§4). Whether that is
   acceptable in public posts is a `narrative-lead` and owner question; §10's sentence is the engineering floor.

## 12. Dispositions of QA's review G211–G227 (2026-11-05)

| G | Disposition | How |
|---|---|---|
| G211 | ACCEPTED | §2 rule 5: `integrity` (bytes_skipped, max DSF.Dp, ULog dropouts) + the max(1 s, 5p) per-stream gap rule → EI; B6 never bridges; demo worked example (Dp 15 by 710.18 s) |
| G212 | ACCEPTED | `min_n` integer ≥ 1 or refusal; B8's n is drop-free seconds, PASS only at ≥ `min_n` s |
| G213 | ACCEPTED | mode names validated against the resolved vehicle's table (refusal; catches `NO`/`ON`); vehicle from the firmware string, never DFReader's Plane default; unresolved → EI |
| G214 | ACCEPTED | NKF4 + NKF9 (EKF2), XKF4 by `C` (EKF3); every GNSS and BAT instance, worst wins; instances/cores printed |
| G215 | ACCEPTED-AS-CUT | `series_bound` = {channel, bound, limit}, every sample; stat, quantiles, `per_window`, B5 percent cut (§3.4); FAIL before EI; rule-3/4 swap mutant added |
| G216 | ACCEPTED | §2 rule 6: NaN in scope → EI (after FAIL); NaN mutant in §9 |
| G217 | ACCEPTED | PX4 level = byte − 48, error ≤ 3; a byte outside `'0'..'7'` → `events` ABSENT |
| G218 | ACCEPTED | strict loader: duplicate keys refuse, closed schema, numbers int/float and not bool |
| G219 | ACCEPTED | sidecar auto-discovered; HASH_MATCH / NOT_REGISTERED / MISMATCH (refusal); pinned log → `(post-hoc)`; demo is post-hoc; dates recorded, not asserted |
| G220 | ACCEPTED | demo limits from log PARM (150 m, 120 m, 12.5 m/s Loiter, 18.6 V instantaneous vs the 10 s timer); template = intent only |
| G221 | ACCEPTED | "4 sparse GNSS samples" corrected to 709 rows at ~5 Hz; QA's and the lead's exposures added to the ledger |
| G222 | ACCEPTED | badge words `pass` / `fail` / `could not tell` + `m/n measured` + `k declared (f FAIL, e EI)`; exits unchanged |
| G223 | ACCEPTED | `pip install -e .[ardupilot]` in `planning-and-eval`; revision 1's "no CI edit" withdrawn |
| G224 | ACCEPTED | step 5 diffs `results[*].{verdict,n}` on all three ArduPilot logs |
| G225 | ACCEPTED | refusal list completed (§5); monotone check over contract streams per instance; `armed: false` refuses; GPS time labelled, not UTC |
| G226 | ACCEPTED | B6 judges `alt_max` when the fence has one; the polygon bit printed as not judged |
| G227 | ACCEPTED | ratio over `src/**/*.py` per am. 4 in CLAUDE.md, `state.sh`, `gates.sh`; dilution stated; each step's commit measured, OVER → retire a file |
| Cuts | ACCEPTED-AS-CUT | `attitude`, `mission`, fence polygon from FNCE, quantiles, `per_window` (§3.4) |
| Firmware list | ACCEPTED | §11.1 verbatim; rule 4 demotes arming's initial state and empty `events` to ABSENT now |

No finding is rejected. One input is corrected: QA's public sentence names the template as the source of the limits,
which §4 of this revision made false; §10 keeps QA's text verbatim and gives the corrected clause.
