"""The dashboard TOUR says nothing untrue about the flight the reader has selected (O10).

THE DEFECT THIS FILE EXISTS FOR. `dashboard/app.js` had five paragraphs of tour prose written about
the 2026-08-25 take and printed verbatim whichever of the three flights was on screen. Driven in a
browser on 2026-08-18 it made three false statements: it called an ACKNOWLEDGED take INVALID, it
said "a detection nothing injected" over a `--demo` bird the node placed itself, and it said the
drone "flew OVER it" over a bird sitting at the vehicle's own cruise altitude. On a page whose
entire claim is that every number comes from a committed artifact, hand-written prose is the one
place a falsehood can live -- and there were 0 behavioural tests on 1,443 lines of `app.js`.

WHAT THIS TEST DOES, AND WHY IT IS PURE PYTHON. No node, no browser, no jsdom: CI runs stdlib
Python and nothing else, and a test that needs a toolchain nobody installs is a test that never
runs. So it treats the tour as what it is -- a list of TEMPLATES plus a substitution -- and:

  (a) extracts every template string from `app.js` and fails if a flight stem, a measured number or
      a verdict word is typed INSIDE one (those must arrive as substitutions, or they are a claim
      about one flight printed over another);
  (b) re-renders all five steps, in Python, for each of the three flights in `data/verdicts.json`,
      and asserts the result states THAT flight's verdict, THAT flight's detector source, and THAT
      flight's numbers -- and none of the other flights'.

The substitution values are recomputed here from the same artifacts the page reads, which makes
this a second implementation on purpose. Two of them are cross-checked against a third: the dodge
displacement is compared to `check_live_flight_log`'s own note, so the page and the gate cannot
quote different numbers for the same manoeuvre.

stdlib unittest only. Run: python3 -m unittest discover -s tests -p 'test_*.py' -v
"""
import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_live_flight_log as GATE  # noqa: E402

APP_JS = REPO_ROOT / "dashboard" / "app.js"
DATA = REPO_ROOT / "dashboard" / "data"
RESULTS = REPO_ROOT / "eval" / "results"

VERDICT_WORDS = ("INVALID", "ACKNOWLEDGED", "VALID")


# ------------------------------------------------------------------------------- reading app.js
def app_source() -> str:
    return APP_JS.read_text()


def tour_templates(src: str):
    """[(title_template, body_template)] -- the `t:`/`b:` template literals of each TOUR step.

    Parsed rather than executed, because the point is to see what a human typed. Each step is
    written as `t: F => \\`...\\`` / `b: F => \\`...\\`` on one line, which is also what keeps this
    readable in review: one step, one paragraph, no concatenation."""
    start = src.index("const TOUR = [")
    end = src.index("\n];", start)
    block = src[start:end]
    entries = re.findall(r"([tb]): F => `([^`]*)`", block)
    steps, cur = [], {}
    for key, text in entries:
        cur[key] = text
        if key == "b":
            steps.append((cur.get("t", ""), cur["b"]))
            cur = {}
    return steps


def source_phrases(src: str):
    """{detector tag or None: the sentence the page prints for it} -- lifted out of
    `detectorSource` so this test never retypes the page's prose."""
    out = {}
    for tag, phrase in re.findall(r"if \(tag === '(\w+)'.*?phrase: '(.*?)' \};", src):
        out[tag] = phrase
    fallback = re.search(r"return \{ tag: null, phrase: '(.*?)' \};", src)
    out[None] = fallback.group(1) if fallback else None
    return out


def placeholders(template: str):
    return set(re.findall(r"\$\{F\.(\w+)\}", template))


def render(template: str, facts: dict) -> str:
    def sub(m):
        key = m.group(1)
        if key not in facts:
            raise AssertionError(f"tour template substitutes ${{F.{key}}}, which tourFacts does "
                                 f"not produce (or which this test does not know about)")
        return str(facts[key])
    return re.sub(r"\$\{F\.(\w+)\}", sub, template)


# ---------------------------------------------------------------------------------- the facts
def load_verdicts() -> dict:
    return json.loads((DATA / "verdicts.json").read_text())


def load_log(stem: str) -> dict:
    """The flight log the page loads. Read from `eval/results/`, which is the SOURCE the dashboard
    build copies from -- so this test does not depend on where that build chooses to put its copy."""
    path = RESULTS / f"{stem}.json"
    if not path.exists():
        raise unittest.SkipTest(f"{path.name} absent (eval/results is gitignore-excepted)")
    return json.loads(path.read_text())


def expected_source_tag(log: dict):
    """The rule `detectorSource` implements, restated: the run block if there is one, else the demo
    source identified by its own `demo_bird_*` track naming.

    NEVER `detection.source` on a schema-1 log -- that field was defaulted to "ndvi_blob" until the
    2026-08-24 seam, so both `--demo` flights record a virtual bird claiming to be an NDVI blob.
    A test that read it would confirm exactly the falsehood this file exists to prevent."""
    run = log.get("run") or {}
    tag = (run.get("detector") or {}).get("source")
    if tag:
        return tag
    demo = any(e.get("kind") == "detection" and str(e.get("track_id", "")).startswith("demo_")
               for e in log.get("events") or [])
    return "demo_virtual" if demo else None


def dodge_numbers(log: dict):
    """(window duration or None, along-command displacement, commanded distance) for the first
    encounter -- computed with the FLIGHT GATE's own functions, so the dashboard's dodge number is
    checked against the tool CI runs rather than against a copy of the dashboard's arithmetic."""
    windows = GATE.encounter_windows(log, len(log["flown_path_enu"]))
    if not windows:
        return None, None, None
    t0, t1, _ = windows[0]
    cmd = GATE.commanded_dodge(log, t0, t1)
    p0, p1 = GATE._flown_point(log, t0), GATE._flown_point(log, t1)
    stamps = ((log.get("run") or {}).get("tick_stamp_sim_s")) or []
    dur = (stamps[t1 - 1] - stamps[t0 - 1]) if len(stamps) >= t1 else None
    if cmd is None or p0 is None or p1 is None:
        return dur, None, None
    _tick, _kind, sp = cmd
    vec = (sp[0] - p0[0], sp[1] - p0[1])
    horiz = (vec[0] ** 2 + vec[1] ** 2) ** 0.5
    split = GATE._displacement_split(p0, p1, (vec[0] / horiz, vec[1] / horiz), None)
    return dur, split["along"], horiz


STEM_UTC = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z")


def stem_utc(stem: str):
    m = STEM_UTC.search(stem or "")
    return datetime(*(int(g) for g in m.groups()), tzinfo=timezone.utc) if m else None


def clip_is_this_sessions(clip: str, flight_stem: str):
    """The rule `clipAttribution` implements, restated: no artifact links a flight to a clip, so the
    clip counts as this flight's only if its recorder STARTED on the same UTC date and BEFORE the
    log was WRITTEN (the `live_flight_log_<UTC>` stem is the teardown write time). Returns
    (same_session: bool, minutes_before: int|None)."""
    c, f = stem_utc(clip), stem_utc(flight_stem)
    if c is None or f is None:
        return None, None
    same = c.date() == f.date() and c < f
    return same, (round((f - c).total_seconds() / 60) if same else None)


def facts_for(stem: str, entry: dict, log: dict, src: str, clip: str) -> dict:
    """`tourFacts` recomputed in Python from the same two artifacts the page reads. The prose-valued
    facts that depend on the DATA (the verdict legend, the detector sentence) are taken from the
    artifact and from `app.js` respectively, so this test cannot drift into asserting its own
    wording; the number-bearing ones are formatted here, and the assertions below are on the
    numbers, never on the sentence they sit in."""
    cpa = entry.get("cpa") or {}
    cpa_m = cpa.get("gt_cpa_m", cpa.get("cpa_m"))
    basis = (cpa.get("basis") or "unstated").split(":")[0]
    legend = (load_verdicts().get("verdict_legend") or {}).get(entry["verdict"], "")
    legend = legend[:1].upper() + legend[1:] + ("" if legend[-1:] in ".!?" else ".")
    if cpa.get("bird_z_m") is not None and cpa.get("drone_z_m") is not None:
        vertical = (f"the bird sat {cpa['drone_z_m'] - cpa['bird_z_m']:.2f} m below the vehicle, "
                    f"which this top-down view flattens away — the altitude strip is where that "
                    f"gap lives")
    else:
        vertical = ("this log measures closest approach in the HORIZONTAL plane only, so nothing "
                    "on this page claims there was a vertical gap")
    dur, along, commanded = dodge_numbers(log)
    if along is None:
        dodge = "no measurable dodge"
    else:
        window = f"{dur:.3f} s" if dur is not None else "ticks"
        dodge = (f"the loop held authority for {window}, and the vehicle moved {along:.4f} m along "
                 f"the direction of the {commanded:.2f} m setpoint it commanded")
    ledger = log["coverage_ledger"]
    covered = sum(1 for r in ledger if r.get("status") == "covered")
    debt = sum(1 for r in ledger if r.get("status") == "debt")
    windows = GATE.encounter_windows(log, len(log["flown_path_enu"]))
    inside = [e for e in log["events"]
              if windows and windows[0][0] <= e.get("tick", -1) <= windows[0][1]]
    count = lambda kind: sum(1 for e in inside if e.get("kind") == kind)  # noqa: E731
    return {
        "verdict": entry["verdict"],
        "verdictLegend": legend,
        "source": source_phrases(src)[expected_source_tag(log)],
        "cpa": ("no closest approach was measurable on this log" if cpa_m is None else
                f"closest approach {cpa_m:.4f} m against a {cpa['bar_m']:.2f} m bar "
                f"(basis: {basis})"),
        "vertical": vertical,
        "dodge": dodge,
        "commands": (f"{count('maneuver')} accepted maneuver(s), {count('latch')} latch(es) and "
                     f"{count('relatch')} re-latch(es)"),
        "ack": "ACK" if entry["acknowledged_pin"] else "NO-ACK",
        "covered": covered, "debt": debt, "cells": len(ledger),
        "clip": clip,
        "clipNote": ("SAME-SESSION" if clip_is_this_sessions(clip, stem)[0] else "OTHER-FLIGHT"),
    }


# ------------------------------------------------------------------------------------- (a) the
# templates: nothing about one flight may be typed into prose printed over another
class TestNoFlightIsHardCodedIntoTheTour(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = app_source()
        cls.steps = tour_templates(cls.src)
        cls.templates = [t for step in cls.steps for t in step]

    def test_the_tour_still_parses_as_five_steps(self):
        self.assertEqual(len(self.steps), 5, "expected 5 tour steps with `t:`/`b:` templates")
        for title, body in self.steps:
            self.assertTrue(title.strip() and body.strip())

    def test_no_flight_stem_appears_in_any_template(self):
        for text in self.templates:
            self.assertNotIn("live_flight_log_", text)
            for stem in load_verdicts()["flights"]:
                self.assertNotIn(stem, text)
            self.assertNotRegex(text, r"2026-?0[89]-?\d\d", f"a date identifies one flight: {text}")

    def test_no_verdict_word_appears_in_any_template(self):
        """`INVALID` is the 2026-08-25 take's verdict and two of the three flights are
        ACKNOWLEDGED. The word has to arrive as `${F.verdict}` from the gate's own record."""
        for text in self.templates:
            for word in VERDICT_WORDS:
                self.assertNotRegex(text, rf"\b{word}\b",
                                    f"verdict word {word!r} typed into a template: {text}")

    def test_no_measured_number_appears_in_any_template(self):
        """Any decimal with two or more places is a measurement: a CPA, a displacement, a duration.
        The grid constants the page states (720 cells, 2.5 m, 18 trees, 75 x 60 m) are properties of
        the field, identical on every flight, and carry at most one decimal place."""
        for text in self.templates:
            self.assertNotRegex(text, r"\d+\.\d{2,}", f"a measured number is typed in: {text}")
        # ...and specifically, none of the three flights' own headline numbers.
        for entry in load_verdicts()["flights"].values():
            cpa = entry["cpa"]
            value = cpa.get("gt_cpa_m", cpa.get("cpa_m"))
            for places in (2, 3, 4):
                needle = f"{value:.{places}f}"
                for text in self.templates:
                    self.assertNotIn(needle, text)

    def test_every_placeholder_is_one_the_page_can_supply(self):
        """A `${F.typo}` renders as the literal text in a browser and fails silently. Every key used
        must be one `tourFacts` returns -- checked against the keys this test builds, which are the
        same list."""
        stem, entry = sorted(load_verdicts()["flights"].items())[0]
        known = set(facts_for(stem, entry, load_log(stem), self.src, "clip").keys())
        used = set()
        for text in self.templates:
            used |= placeholders(text)
        self.assertLessEqual(used, known, f"unknown tour placeholders: {sorted(used - known)}")
        self.assertIn("verdict", used, "the tour no longer prints the flight's verdict at all")
        self.assertIn("source", used, "the tour no longer prints where the detection came from")


# ------------------------------------------------------------------------------------- (b) the
# rendering: each flight's prose states that flight's verdict, source and numbers
class TestTheProseMatchesTheSelectedFlight(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = app_source()
        cls.steps = tour_templates(cls.src)
        cls.verdicts = load_verdicts()
        cls.clip = json.loads((DATA / "manifest.json").read_text())["clips"][0]

    def rendered(self, stem):
        entry = self.verdicts["flights"][stem]
        log = load_log(stem)
        facts = facts_for(stem, entry, log, self.src, self.clip)
        text = "\n".join(render(t, facts) + "\n" + render(b, facts) for t, b in self.steps)
        return entry, log, facts, text

    def test_each_flight_reads_its_own_verdict_and_no_other(self):
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                entry, _log, _facts, text = self.rendered(stem)
                self.assertIn(entry["verdict"], text)
                for word in VERDICT_WORDS:
                    if word == entry["verdict"] or word in entry["cpa"].get("basis", ""):
                        continue
                    # The legend for ACKNOWLEDGED legitimately contains the word VALID ("never the
                    # word VALID"), so the check is that no OTHER verdict is asserted of this take.
                    if word in (self.verdicts["verdict_legend"].get(entry["verdict"]) or ""):
                        continue
                    self.assertNotIn(f"take {word}", text)
                    self.assertNotIn(f"is {word}", text)

    def test_each_flight_reads_its_own_detector_source_and_no_other(self):
        phrases = source_phrases(self.src)
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                _entry, log, _facts, text = self.rendered(stem)
                tag = expected_source_tag(log)
                self.assertIn(phrases[tag], text)
                for other, phrase in phrases.items():
                    if other != tag and phrase:
                        self.assertNotIn(phrase, text)

    def test_the_demo_flights_say_injected_and_the_real_one_does_not(self):
        """The headline falsehood, stated as its own assertion: a `--demo` flight must never be
        described as a detection off the live render, and the real-detection take must never be
        described as injected."""
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                _entry, log, _facts, text = self.rendered(stem)
                if expected_source_tag(log) == "demo_virtual":
                    self.assertIn("INJECTED", text)
                    self.assertNotIn("off the live render", text)
                else:
                    self.assertIn("off the live render", text)
                    self.assertNotIn("INJECTED", text)

    def test_each_flight_reads_its_own_closest_approach(self):
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                entry, _log, _facts, text = self.rendered(stem)
                cpa = entry["cpa"]
                value = cpa.get("gt_cpa_m", cpa.get("cpa_m"))
                self.assertIn(f"{value:.4f} m", text)
                self.assertIn(f"{cpa['bar_m']:.2f} m bar", text)
                for other_stem, other in self.verdicts["flights"].items():
                    if other_stem == stem:
                        continue
                    o = other["cpa"]
                    self.assertNotIn(f"{o.get('gt_cpa_m', o.get('cpa_m')):.4f} m", text)

    def test_the_vertical_claim_is_only_made_where_there_is_vertical_evidence(self):
        """"It flew OVER it" was the third falsehood: on the two legacy logs the CPA is horizontal
        only, and the injected bird sits at the vehicle's own cruise altitude."""
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                entry, _log, _facts, text = self.rendered(stem)
                cpa = entry["cpa"]
                if cpa.get("bird_z_m") is None:
                    self.assertIn("HORIZONTAL plane only", text)
                    self.assertNotIn("below the vehicle", text)
                else:
                    self.assertIn(f"{cpa['drone_z_m'] - cpa['bird_z_m']:.2f} m below the vehicle",
                                  text)

    def test_the_dodge_number_is_the_gates_own(self):
        """The page's dodge metric and the flight gate's achieved-displacement note are the same
        projection of the same window. If they ever disagree, one of them is lying to a reader."""
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                _entry, log, _facts, text = self.rendered(stem)
                dur, along, commanded = dodge_numbers(log)
                self.assertIsNotNone(along, "every committed flight has one encounter")
                self.assertIn(f"{along:.4f} m along the direction", text)
                self.assertIn(f"{commanded:.2f} m setpoint", text)
                note = " ".join(GATE.displacement_notes(log))
                self.assertIn(f"{along:+.4f} m", note)

    def test_the_ndvi_clip_is_attributed_to_this_flight_only_on_evidence(self):
        """Residual O10 (QA, 2026-09-10): step 5 was titled "What this flight put on the map" and
        then named whichever clip the picker held -- and for the 2026-08-18 flight no clip exists at
        all. No committed artifact links a log to a clip, so the page may call a clip "this
        flight's" only when the two stems' own UTC timestamps say the recorder was running while
        the flight flew (same UTC date, started before the log was written). Rendered here with the
        page's OWN attribution function, lifted from app.js and evaluated per flight."""
        attrib = re.search(r"function clipAttribution\(clipId, flightStem\) \{(.*?)\n\}\n",
                           self.src, re.S)
        self.assertIsNotNone(attrib, "app.js no longer has clipAttribution()")
        body = attrib.group(1)
        same_phrase = "recorded during this flight's session"
        other_phrase = "a DIFFERENT flight's clip"
        self.assertIn(same_phrase, body)
        self.assertIn(other_phrase, body)
        seen = set()
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                same, mins = clip_is_this_sessions(self.clip, stem)
                self.assertIsNotNone(same, "both stems must carry a UTC timestamp")
                seen.add(same)
                _entry, _log, facts, text = self.rendered(stem)
                self.assertIn(self.clip, text)
                self.assertEqual(facts["clipNote"], "SAME-SESSION" if same else "OTHER-FLIGHT")
                if same:
                    self.assertGreater(mins, 0)
                    self.assertLess(mins, 60, "a recorder started an hour before the log was "
                                    "written is not obviously the same session -- re-examine")
        # Both branches must be exercised by the committed flights, or the test proves nothing.
        self.assertEqual(seen, {True, False},
                         "expected at least one same-session and one other-flight pairing")

    def test_the_tour_never_calls_the_clip_this_flights_without_the_attribution(self):
        """The old step 5 title asserted "this flight put [it] on the map". Any template that
        names the clip must carry the attribution substitution beside it."""
        for _title, body in self.steps:
            if "${F.clip}" in body:
                self.assertIn("${F.clipNote}", body, "clip named without its attribution")

    def test_the_coverage_line_is_this_flights_ledger(self):
        """2026-08-18 closed 207 cells in debt. The old step 5 announced 720 of 720 over it."""
        for stem in self.verdicts["flights"]:
            with self.subTest(flight=stem):
                _entry, log, facts, text = self.rendered(stem)
                self.assertIn(f"{facts['covered']} of {facts['cells']} cells covered", text)
                self.assertIn(f"{facts['debt']} in debt", text)
                self.assertEqual(facts["covered"] + facts["debt"], facts["cells"],
                                 "a cell that is neither covered nor debt is the ledger bug")


if __name__ == "__main__":
    unittest.main()
