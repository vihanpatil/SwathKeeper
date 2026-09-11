"""Every URL `dashboard/app.js` fetches resolves — in BOTH layouts the page is ever served from.

THE FAILURE THIS PREVENTS. Since 2026-09-10 the page no longer carries its own copy of the flight
logs: they are committed once, at `eval/results/`, and read in place through the `EVIDENCE` root in
`app.js` (`../eval/results/`). That buys back 140,942 lines of duplicated JSON and removes a copy
of evidence that could disagree with the evidence — at the cost of a relative path that has to be
correct in two different directory layouts:

  * LOCAL — `python3 -m http.server` at the REPOSITORY ROOT, the command the page's own boot error
    and `dashboard/README.md` print. `dashboard/index.html` sits at `/dashboard/`, so
    `../eval/results/x` is `/eval/results/x`.
  * PAGES — the site assembled by `.github/workflows/pages.yml`, which lays `eval/results/` down
    beside `dashboard/` for exactly this reason.

A path that is right in one and wrong in the other is a 404 that the author never sees and every
visitor does. So this test resolves every fetched URL against both — and it does not TRUST the
workflow's description of the site: it extracts that workflow's `Assemble the published site`
shell block and RUNS it into a temp tree (the pattern `tests/test_ci_evidence_gate.py` uses on
ci.yml), then checks the files in what it produced.

It also pins the page's fetch SITES, so a sixth `getJSON(...)` cannot be added without this model
of what the page loads being updated with it. A path checker that checks a stale list of paths is
worse than none.

Lives in tests/ (not tests/fieldguard_planning/) like its siblings: it tests host-side artifacts —
a static page, a workflow file and a directory layout — not the planning package.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "dashboard" / "app.js"
PAGES_YML = REPO_ROOT / ".github" / "workflows" / "pages.yml"
DATA = REPO_ROOT / "dashboard" / "data"
ASSEMBLE_STEP = "Assemble the published site"

# The page's load path, expression by expression (dashboard/app.js `boot()`). Each line here is a
# fetch this file MODELS below; if app.js grows another one, `test_the_pages_it_fetches_are_the_
# pages_this_test_models` goes red and this list — and the model — must be updated together.
FETCH_SITES = (
    "[DATA + 'manifest.json', DATA + 'field.json', DATA + 'verdicts.json', "
    "DATA + 'clips/index.json'].map(getJSON)",
    "await getJSON(EVIDENCE + v.log)",
    "await getText(EVIDENCE + v.marker)",
    "await getJSON(DATA + 'truth/' + stem + '.json')",
    "[c.heatmap, c.meta, c.tree_check].map(p => getJSON(DATA + p))",
)


def _js_const(name: str) -> str:
    """The value of a top-level `const <name> = '<value>';` in app.js — read, never assumed."""
    for line in APP_JS.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(f"const {name} = '"):
            return stripped.split("'")[1]
    raise AssertionError(f"dashboard/app.js has no `const {name} = '...'` — the page's data roots "
                         f"are what this test resolves; if they were renamed, rename them here.")


def _step_run_block(yml: Path, name_fragment: str) -> str:
    """The shell body of the workflow step whose `name:` contains `name_fragment`.

    The same ~20-line indentation walk `tests/test_ci_evidence_gate.py` uses, for the same reason:
    a PyYAML dependency so a test can read two lines of YAML shape is a worse trade.
    """
    lines = yml.read_text().splitlines()
    for i, line in enumerate(lines):
        if not (line.lstrip().startswith("- name:") and name_fragment in line):
            continue
        for j in range(i + 1, len(lines)):
            if lines[j].lstrip().startswith("- name:") or lines[j].lstrip().startswith("- uses:"):
                break
            if lines[j].strip() != "run: |":
                continue
            indent = len(lines[j]) - len(lines[j].lstrip()) + 2
            body = []
            for k in range(j + 1, len(lines)):
                ln = lines[k]
                if ln.strip() and (len(ln) - len(ln.lstrip())) < indent:
                    break
                body.append(ln[indent:] if len(ln) >= indent else ln)
            return "\n".join(body)
    raise AssertionError(f"no step named ~{name_fragment!r} with a 'run: |' block in {yml.name}")


def fetched_urls():
    """Every URL `boot()` asks for, as the page would spell it, in load order.

    Derived from the SAME files the page reads (verdicts.json, clips/index.json), so adding a
    flight or a clip extends this automatically — the list cannot go stale behind a reviewed diff.
    """
    data, evidence = _js_const("DATA"), _js_const("EVIDENCE")
    urls = [data + name for name in
            ("manifest.json", "field.json", "verdicts.json", "clips/index.json")]
    verdicts = json.loads((DATA / "verdicts.json").read_text())["flights"]
    for stem, v in sorted(verdicts.items()):
        urls.append(evidence + v["log"])
        if v.get("marker"):
            urls.append(evidence + v["marker"])
        if (v.get("schema_version") or 0) >= 2:
            urls.append(f"{data}truth/{stem}.json")
    clips = json.loads((DATA / "clips" / "index.json").read_text())["clips"]
    for _name, c in sorted(clips.items()):
        urls += [data + c["heatmap"], data + c["meta"], data + c["tree_check"]]
    return urls


def resolve(served_root: Path, url: str) -> Path:
    """Where `url` lands when `served_root` is the web root and the page is at /dashboard/."""
    return Path(os.path.normpath(served_root / "dashboard" / url))


class TestTheModelMatchesThePage(unittest.TestCase):

    def test_the_pages_it_fetches_are_the_pages_this_test_models(self):
        source = APP_JS.read_text()
        for site in FETCH_SITES:
            self.assertIn(site, source,
                          "dashboard/app.js no longer contains this fetch site, so the URL model "
                          "below is describing a page that does not exist:\n    " + site)
        # ...and there are no OTHERS. Two fetch() call sites, both inside the loader helpers.
        self.assertEqual(source.count("await fetch("), 2,
                         "app.js has a fetch() outside getJSON/getText -- add it to FETCH_SITES "
                         "and to fetched_urls(), or this test stops covering the page")
        self.assertEqual(source.count("getJSON") + source.count("getText"), 7,
                         "a loader call site was added or removed (2 definitions + 5 uses). "
                         "Update FETCH_SITES and fetched_urls() with it.")

    def test_the_page_carries_no_second_copy_of_the_flight_logs(self):
        self.assertFalse((DATA / "flights").exists(),
                         "dashboard/data/flights/ exists again -- the logs are committed twice and "
                         "the EVIDENCE root has nothing to prove")
        self.assertEqual(_js_const("EVIDENCE"), "../eval/results/",
                         "the evidence root moved; both layouts below assume this exact value")


class TestLocalLayout(unittest.TestCase):
    """`python3 -m http.server` at the repository root — the command the page itself prints."""

    def test_every_fetched_url_exists_under_the_repository_root(self):
        urls = fetched_urls()
        self.assertGreaterEqual(len(urls), 10, "the model found almost nothing to check")
        for url in urls:
            target = resolve(REPO_ROOT, url)
            self.assertTrue(target.is_file(), f"{url} -> {target} does not exist")

    def test_no_fetched_url_escapes_the_served_root(self):
        """`../` is one level too many away from a 404 on a server that refuses to serve above its
        root. Every URL must stay inside the directory the reader is told to serve."""
        for url in fetched_urls():
            target = resolve(REPO_ROOT, url)
            self.assertTrue(str(target).startswith(str(REPO_ROOT) + os.sep),
                            f"{url} resolves to {target}, outside the served root {REPO_ROOT}")


class TestPagesLayout(unittest.TestCase):
    """The GitHub Pages site — built by running the workflow's own assembly block."""

    site = None
    assemble_output = ""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        # A stand-in for scripts/build_docs_site.py's output: this test is about the LAYOUT, and
        # rendering 51 documents to prove a `cp -R` would be a minute of someone else's gate.
        docs = tmp / "docs-site"
        (docs / "runbooks").mkdir(parents=True)
        (docs / "index.html").write_text("<!doctype html><title>stand-in</title>")
        proc = subprocess.run(["bash", "-c", _step_run_block(PAGES_YML, ASSEMBLE_STEP)],
                              cwd=str(REPO_ROOT), capture_output=True, text=True,
                              env=dict(os.environ, SITE=str(tmp / "_site"), DOCS_SITE=str(docs)))
        cls.assemble_output = proc.stdout + proc.stderr
        cls.returncode = proc.returncode
        cls.site = tmp / "_site"
        cls.addClassCleanup(cls._tmp.cleanup)

    def test_the_workflow_block_assembles_a_site(self):
        self.assertEqual(self.returncode, 0,
                         f"the pages.yml '{ASSEMBLE_STEP}' block failed:\n{self.assemble_output}")
        self.assertTrue((self.site / "index.html").is_file(), "no landing page")
        self.assertTrue((self.site / "dashboard" / "index.html").is_file(), "no dashboard")
        self.assertTrue((self.site / "docs" / "index.html").is_file(), "docs were not published")

    def test_every_fetched_url_exists_in_the_published_site(self):
        for url in fetched_urls():
            target = resolve(self.site, url)
            self.assertTrue(target.is_file(),
                            f"{url} -> {target} is missing from the Pages site. The page would "
                            f"404 on it in the browser while working locally.\n"
                            f"{self.assemble_output}")

    def test_the_published_evidence_is_byte_identical_to_the_repository_evidence(self):
        """A copy made by the site build is still a copy: if it can differ from eval/results/, the
        published verdict can differ from the gate's."""
        published = sorted((self.site / "eval" / "results").glob("live_flight_log_*"))
        self.assertTrue(published, "the site published no flight evidence at all")
        for path in published:
            source = REPO_ROOT / "eval" / "results" / path.name
            self.assertEqual(path.read_bytes(), source.read_bytes(), path.name)

    def test_the_site_carries_the_markers_beside_the_logs(self):
        """The INVALID take's written finding travels WITH it. The page fetches the marker and
        renders it; a site with the log and not the finding publishes the flight without the
        reason it is not evidence of a safe one."""
        logs = {p.name for p in (self.site / "eval" / "results").glob("live_flight_log_*.json")}
        markers = {p.name for p in
                   (self.site / "eval" / "results").glob("live_flight_log_*.SAFETY_FINDING.md")}
        self.assertTrue(logs, "no logs published")
        for stem in (n[: -len(".json")] for n in logs):
            if (REPO_ROOT / "eval" / "results" / f"{stem}.SAFETY_FINDING.md").exists():
                self.assertIn(f"{stem}.SAFETY_FINDING.md", markers, stem)

    def test_the_landing_page_reaches_both_halves_and_leaves_the_machine_alone(self):
        html = (self.site / "index.html").read_text()
        self.assertIn('href="dashboard/"', html)
        self.assertIn('href="docs/"', html)
        for token in ("http://", "https://", "//cdn", "integrity="):
            self.assertNotIn(token, html,
                             f"the landing page references {token} -- the site is offline-clean "
                             f"by ADR-018 and the front door is part of the site")


if __name__ == "__main__":
    unittest.main()
