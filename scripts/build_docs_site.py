#!/usr/bin/env python3
"""Render every Markdown doc in this repo to a styled static site under docs-site/.

Design: ADR-014, direction D "Heatmap Neutral" — warm-grey monochrome chrome, with the
NDVI ramp (canopy green -> neutral -> soil red) spent ONLY where colour carries meaning:
status markers, state rows, gate outcomes. Markdown sources are never touched; this is a
rendering layer, so the docs stay diffable on GitHub exactly as they are.

Usage:  python3 scripts/build_docs_site.py
"""
from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    import markdown
    from markdown.extensions import Extension
    from markdown.postprocessors import Postprocessor
    from markdown.treeprocessors import Treeprocessor
except ImportError:
    sys.exit("build_docs_site: needs python-markdown -> python3 -m pip install markdown")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs-site"

# --- source set + landing-page order (docs/README.md's own map) ----------------------
GROUPS: list[tuple[str, str, list[str]]] = [
    ("Start here", "The repo's front door, how to run it, and how the tiger team is run.",
     ["README.md", "SETUP.md", "TIGER_TEAM_GUIDE.md"]),
    ("Living", "Always current. If these disagree with anything else, these win.",
     ["docs/README.md", "docs/SPEC.md", "docs/ROADMAP.md", "docs/DECISIONS.md",
      "docs/BUILD_LOG.md"]),
    ("Runbooks", "Operational, executed in Docker sessions; named by function.",
     ["docs/runbooks/SIM_BRINGUP.md", "docs/runbooks/AVOIDANCE_DEMO.md",
      "docs/runbooks/AVOIDANCE_REAL_DETECTION.md", "docs/runbooks/NDVI_VALIDATION.md",
      "docs/runbooks/FULL_PIPELINE_DEMO.md", "docs/runbooks/SIM_CI.md"]),
    ("History", "Records, deliberately frozen. Kept because live docs cite them.",
     ["docs/SPIKE_ndvi_vs_rgb.md", "docs/archive/WEEK3_VALIDATION.md",
      "docs/archive/tiger_team_playbook.md"]),
]

# --- pattern vocabulary -------------------------------------------------------------
# One ramp, one meaning: ok -> canopy green, wait -> neutral, bad -> soil red.
STATE = {"✅": "ok", "\U0001f7e2": "ok", "☑": "ok",
         "⏳": "wait", "\U0001f7e1": "wait", "\U0001f504": "wait", "\U0001f6a7": "wait",
         "❌": "bad", "⚠": "bad", "\U0001f534": "bad"}
# `⚠️` in the corpus is U+26A0 + VS16; without swallowing the variation selector the leftover
# codepoint survives the strip and blocks the leading-label match behind it.
MARK = re.compile("[%s]️?" % "".join(STATE))
# Leading label token in a heading: ADR-NNN / a log date / Gate|Shell|Step|Phase|Week N.
TAG = re.compile(r"^(ADR-\d{3}|\d{4}-\d{2}-\d{2}(?: \([^)]{1,24}\))?"
                 r"|(?:Gate|Shell|Step|Phase|Week) [\dA-D][\w-]*)(?!\w)")
TASK = re.compile(r"^\[([ xX])\]\s+")
HEADS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# ADR schema field labels (DECISIONS.md declares this schema in its own header block).
FIELD = re.compile(r"(?m)(^|<p>)((?:Decision|Alternative\(s\) rejected|Alternative rejected|Why"
                   r"|Status|Amendment \d+|Deciding numbers|Implementation notes)[^:\n<]{0,40}:)")
OWNER = re.compile(r"(?m)(^|<p>)(Owner ?/ ?roles[^\n<]*)")
PRE = re.compile(r"(<pre\b.*?</pre>)", re.S)
# `#` starts a narration comment; `##` inside a fence is a Markdown heading form, not a comment.
COMMENT = re.compile(r"(?m)(^|\s)(#(?!#)[^\n]*)")
# GitHub (CommonMark) requires whitespace after the hashes; python-markdown's legacy regex does
# not. A wrapped body line that happens to start with a `#N` cross-reference — DECISIONS.md:165
# `#5→#8), no restart at #1.` and SPIKE_ndvi_vs_rgb.md:27 `#1). Picking (b)...` — therefore became
# a page-title <h1> mid-paragraph here while rendering as prose on GitHub. The site must never
# invent a heading the source does not have, so match GitHub.
HASH_HEADER = re.compile(r"(?:^|\n)(?P<level>#{1,6})[ \t]+(?P<header>(?:\\.|[^\\])*?)#*(?:\n|$)")
# Same rule, applied to the source to count what the author actually declared. Blockquote markers
# are stripped first (WEEK3_VALIDATION.md's verdict is a `> ## ✅ RESULT` inside a callout); 4+
# spaces of indent is an indented code block, so headings get at most 3.
SRC_HEAD = re.compile(r"^ {0,3}#{1,6}[ \t]+\S")
QUOTE = re.compile(r"^ {0,3}(?:> ?)+")
FENCE = re.compile(r"^ {0,3}(```|~~~)")


def state_of(text: str, anchored: bool = False) -> str | None:
    m = MARK.match(text.lstrip()) if anchored else MARK.search(text)
    return STATE[m.group()[0]] if m else None       # [0] drops a trailing variation selector


def add_class(el: ET.Element, cls: str) -> None:
    el.set("class", (el.get("class", "") + " " + cls).strip())


class Ctx:
    """Per-file conversion context (one Markdown instance is reused for speed)."""
    src = Path()      # repo-relative path of the file being converted
    up = ""           # from this page's dir back to docs-site/ (stylesheet, index, sibling pages)
    out = ""          # from this page's dir back to the REPO root — one level further than `up`,
                      # because docs-site/ is itself a directory inside the repo


class Heatmap(Treeprocessor):
    def run(self, root: ET.Element) -> None:
        parents = list(root.iter())
        for el in parents:
            for i, child in enumerate(list(el)):
                if child.tag == "table":            # wide content scrolls in its own box
                    box = ET.Element("div", {"class": "tw", "tabindex": "0"})
                    box.append(child)
                    el[i] = box
        for el in root.iter():
            if el.tag in HEADS:
                self.heading(el)
            elif el.tag == "tr":
                self.row(el)
            elif el.tag == "blockquote":
                self.callout(el)
            elif el.tag == "p":
                self.evidence(el)
            elif el.tag == "li":
                self.item(el)
            elif el.tag == "a":
                self.link(el)

    # (2)(5)(6)(8) headings: state marker -> ramp dot; leading label token -> mono tag
    def heading(self, el: ET.Element) -> None:
        text = "".join(el.itertext())
        st = state_of(text, anchored=True)
        if st:
            add_class(el, "st-" + st)
        head = (el.text or "").lstrip()
        if st:                                      # keep the emoji, skip past it
            head = MARK.sub("", head, count=1).lstrip()
        m = TAG.match(head) if el.tag in ("h2", "h3") else None
        if not m:                                   # an h1 is a page title, never a label + title
            return
        span = ET.Element("span", {"class": "tag"})
        tail = head[m.end():]
        span.text = m.group(1) + (":" if tail.startswith(":") else "")
        span.tail = tail[1:] if tail.startswith(":") else tail
        el.text = (el.text or "")[:len(el.text or "") - len(head)]
        el.insert(0, span)
        add_class(el, "titled")
        if el.tag == "h3" and "amendment" in text.lower():
            add_class(el, "amend")

    # (1) status tables: the row's state paints a tick on its first cell
    def row(self, el: ET.Element) -> None:
        st = state_of("".join(el.itertext()))
        if st:
            add_class(el, "st-" + st)

    # (3) blockquote callouts: bold lead phrase + state edge
    def callout(self, el: ET.Element) -> None:
        st = state_of("".join(el.itertext()))
        if st:
            add_class(el, "st-" + st)

    # (4) *Look for:* evidence lines after a fence
    def evidence(self, el: ET.Element) -> None:
        kid = el.find("em")
        if kid is not None and list(el)[0] is kid and not (el.text or "").strip():
            label = "".join(kid.itertext()).strip()
            if label.endswith(":") and len(label) <= 40:
                add_class(el, "ev")

    # (5) checklists + marked list items
    def item(self, el: ET.Element) -> None:
        m = TASK.match((el.text or "").lstrip())
        if m:
            box = ET.Element("span", {"class": "box on" if m.group(1) != " " else "box"})
            box.tail = (el.text or "").lstrip()[m.end():]
            el.text = ""
            el.insert(0, box)
            add_class(el, "task")
            return
        st = state_of((el.text or ""), anchored=True)
        if st:
            add_class(el, "st-" + st)

    # intra-repo links -> generated pages; other repo paths -> back out to the tree
    def link(self, el: ET.Element) -> None:
        href = el.get("href", "")
        if not href or href.startswith(("#", "mailto:", "//")) or "://" in href:
            return
        path, _, frag = href.partition("#")
        if not path:
            return
        anchor = "#" + frag if frag else ""
        target = (ROOT / Ctx.src.parent / path).resolve()
        try:
            rel = target.relative_to(ROOT)
        except ValueError:
            BROKEN.append((Ctx.src, href, "escapes the repo"))
            return
        if rel in SOURCES:
            el.set("href", path[:-3] + ".html" + anchor)
        elif target.exists():
            # A repo file that is not a rendered doc: point back out of docs-site/ at the real tree.
            el.set("href", Ctx.out + rel.as_posix() + anchor)
        else:
            BROKEN.append((Ctx.src, href, "no such file in the repo"))


class Ink(Postprocessor):
    """(6) ADR field labels outside fences; (7) muted # comments inside them."""

    def run(self, text: str) -> str:
        parts = PRE.split(text)
        for i, seg in enumerate(parts):
            if i % 2:
                parts[i] = COMMENT.sub(r'\1<span class="c">\2</span>', seg)
            else:
                seg = FIELD.sub(r'\1<span class="fld">\2</span>', seg)
                parts[i] = OWNER.sub(r'\1<span class="own">\2</span>', seg)
        return "".join(parts)


class HeatmapNeutral(Extension):
    def extendMarkdown(self, md: markdown.Markdown) -> None:
        md.parser.blockprocessors["hashheader"].RE = HASH_HEADER  # GitHub's rule, not Markdown.pl's
        md.treeprocessors.register(Heatmap(md), "heatmap", 5)
        md.postprocessors.register(Ink(md), "heatmap_ink", 5)


def source_headings(text: str) -> int:
    """How many ATX headings the Markdown declares, ignoring fenced blocks."""
    n, fenced = 0, False
    for line in text.splitlines():
        line = QUOTE.sub("", line)
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and SRC_HEAD.match(line):
            n += 1
    return n


# --- page shell ----------------------------------------------------------------------
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{up}docs-site-style.css">
<script src="{up}docs-site.js"></script>
</head>
<body>
<header class="bar">
  <a class="home" href="{up}index.html">SwathKeeper docs</a>
  <span class="path">{path}</span>{badge}
  <div class="tsw" role="group" aria-label="Theme">
    <button type="button" data-t="auto">Auto</button\
><button type="button" data-t="light">Light</button\
><button type="button" data-t="dark">Dark</button>
  </div>
</header>
<main>
{body}
</main>
</body>
</html>
"""
BADGE = '<span class="frozen">frozen historical record</span>'

JS = """(function(){var K='swk-theme',d=document.documentElement;
function set(t){if(t&&t!=='auto'){d.setAttribute('data-theme',t)}else{d.removeAttribute('data-theme')}
try{localStorage.setItem(K,t)}catch(e){}}
try{var s=localStorage.getItem(K);if(s&&s!=='auto'){d.setAttribute('data-theme',s)}}catch(e){}
document.addEventListener('DOMContentLoaded',function(){
var cur='auto';try{cur=localStorage.getItem(K)||'auto'}catch(e){}
var b=[].slice.call(document.querySelectorAll('.tsw button'));
function paint(t){b.forEach(function(x){x.setAttribute('aria-pressed',String(x.dataset.t===t))})}
b.forEach(function(x){x.addEventListener('click',function(){set(x.dataset.t);paint(x.dataset.t)})});
paint(cur)});})();
"""

CSS = """/* SwathKeeper docs — D · Heatmap Neutral (ADR-014). Generated by scripts/build_docs_site.py */
:root{
  --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
  --serif:ui-serif,"New York",Georgia,"Times New Roman",serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  --bg:#F6F4F1; --surface:#FCFBF9; --text:#1E1B18; --muted:#6F6862;
  --green:#4A7A3E; --soil:#A04E33; --line:#E4E0DA; --code:#EFECE7; --rule:#CEC7BE;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#14120F; --surface:#1C1916; --text:#EAE6E1; --muted:#97908A;
  --green:#86BE72; --soil:#E08163; --line:#2A2621; --code:#221E1A; --rule:#4B443C;
}}
:root[data-theme="dark"]{
  --bg:#14120F; --surface:#1C1916; --text:#EAE6E1; --muted:#97908A;
  --green:#86BE72; --soil:#E08163; --line:#2A2621; --code:#221E1A; --rule:#4B443C;
}

*{box-sizing:border-box}
html{scroll-padding-top:64px}
/* break-word, not anywhere: only a token that cannot fit is broken. These docs are full of
   unbreakable single tokens — `eval/results/testflight_gate_20260818T222031Z.json` measures 422px,
   wider than a phone's 339px text column — and one of them widened the whole document at 375px,
   dragging the fixed bar sideways with it. Fences opt out via `white-space:pre` in their scroll box. */
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--serif);
  font-size:16px;line-height:1.65;-webkit-font-smoothing:antialiased;overflow-wrap:break-word}
:focus-visible{outline:2px solid var(--muted);outline-offset:3px;border-radius:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}

/* ---- fixed chrome: monochrome by rule ---- */
.bar{position:fixed;top:0;left:0;right:0;z-index:9;display:flex;align-items:center;gap:14px;
  height:44px;padding:0 22px;background:var(--bg);border-bottom:1px solid var(--line);
  font-family:var(--sans);font-size:12px}
.bar .home{font-weight:600;font-size:12.5px;letter-spacing:-.005em;text-decoration:none;
  white-space:nowrap;color:var(--text)}
.bar .path{font-family:var(--mono);font-size:11.5px;color:var(--muted);letter-spacing:.01em;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.frozen{flex:none;font-size:9.5px;font-weight:640;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);border:1px solid var(--line);border-radius:3px;padding:3px 7px;white-space:nowrap}
.tsw{margin-left:auto;display:inline-flex;border:1px solid var(--line);border-radius:5px;
  background:var(--surface);flex:none}
.tsw button{appearance:none;border:0;border-left:1px solid var(--line);background:transparent;
  color:var(--muted);font-family:var(--sans);font-size:11px;font-weight:530;padding:5px 10px;cursor:pointer}
.tsw button:first-child{border-left:0}
.tsw button:hover{color:var(--text)}
.tsw button[aria-pressed="true"]{color:var(--text);background:var(--code)}

main{max-width:94ch;margin:0 auto;padding:74px 26px 140px}
main>*{max-width:72ch}
main>.tw,main>pre,main>hr{max-width:100%}

/* ---- type ---- */
h1{font-family:var(--serif);font-size:clamp(30px,4.6vw,42px);font-weight:500;line-height:1.1;
  letter-spacing:-.018em;margin:6px 0 24px;text-wrap:balance}
h2{font-family:var(--sans);font-size:13px;font-weight:640;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);margin:54px 0 18px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-family:var(--sans);font-size:16.5px;font-weight:620;letter-spacing:-.006em;margin:34px 0 12px}
h4,h5,h6{font-family:var(--sans);font-size:13.5px;font-weight:640;letter-spacing:.02em;
  color:var(--muted);margin:26px 0 8px}
:is(h1,h2,h3,h4,h5,h6){position:relative;scroll-margin-top:8px}
p,ul,ol{margin:0 0 18px}
li{margin:0 0 6px}
li>ul,li>ol{margin:6px 0 0}
strong{font-weight:640}
hr{border:0;border-top:1px solid var(--line);margin:44px 0}
a{color:inherit;text-decoration:underline;text-decoration-color:var(--rule);
  text-decoration-thickness:1px;text-underline-offset:2px}
a:hover{text-decoration-color:var(--text)}

/* (6)(8)(5) a leading ADR-NNN / date / Gate token turns the heading into a titled block */
h2.titled{text-transform:none;letter-spacing:-.008em;font-size:19px;font-weight:620;line-height:1.35;
  color:var(--text)}
.tag{font-family:var(--mono);font-size:.72em;font-weight:520;letter-spacing:.04em;
  font-variant-numeric:tabular-nums;color:var(--muted);margin-right:.45em;white-space:nowrap}
h3.amend{padding-left:15px;border-left:2px solid var(--line);font-size:15px;color:var(--muted);
  font-weight:600}
h3.amend .tag{font-size:.78em}

/* (2) state markers: the only colour the chrome ever gets */
:is(h1,h2,h3,h4,h5,h6,li)[class*="st-"]::before{content:"";position:absolute;left:-15px;top:.66em;
  width:5px;height:5px;border-radius:50%}
li[class*="st-"]{position:relative}
:is(h1,h2,h3,h4,h5,h6,li).st-ok::before{background:var(--green)}
:is(h1,h2,h3,h4,h5,h6,li).st-wait::before{background:var(--muted)}
:is(h1,h2,h3,h4,h5,h6,li).st-bad::before{background:var(--soil)}
h2.st-ok{border-bottom-color:var(--green)}
h2.st-bad{border-bottom-color:var(--soil)}

/* (1) status tables */
.tw{overflow-x:auto;margin:0 0 26px}
table{border-collapse:collapse;width:100%;min-width:520px;font-family:var(--sans);font-size:14px;
  line-height:1.5}
th{text-align:left;font-size:10.5px;font-weight:640;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);padding:0 16px 8px 0;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:11px 16px 11px 0;border-bottom:1px solid var(--line);vertical-align:top;
  font-variant-numeric:tabular-nums}
th:last-child,td:last-child{padding-right:0}
tr:last-child td{border-bottom:0}
tr[class*="st-"] td:first-child{position:relative;padding-left:14px}
tr[class*="st-"] td:first-child::before{content:"";position:absolute;left:0;top:17px;
  width:4px;height:4px;border-radius:50%}
tr.st-ok td:first-child::before{background:var(--green)}
tr.st-wait td:first-child::before{background:var(--muted)}
tr.st-bad td:first-child::before{background:var(--soil)}

/* (7) fences — narration muted, command legible */
code{font-family:var(--mono);font-size:.855em;background:var(--code);border-radius:3px;padding:.1em .36em}
pre{margin:0 0 20px;padding:15px 18px;background:var(--code);border:1px solid var(--line);
  border-radius:5px;overflow-x:auto;font-family:var(--mono);font-size:12.5px;line-height:1.7}
pre code{background:none;padding:0;font-size:inherit;white-space:pre}
pre .c{color:var(--muted)}

/* (3) callouts */
blockquote{margin:0 0 22px;padding:14px 18px;background:var(--surface);border:1px solid var(--line);
  border-radius:3px;font-family:var(--sans);font-size:14.5px;line-height:1.6}
blockquote>:first-child{margin-top:0}
blockquote>:last-child{margin-bottom:0}
blockquote>p:first-child>strong:first-child,blockquote>p:first-child>em:first-child{color:var(--soil)}
blockquote.st-ok{border-left:3px solid var(--green)}
blockquote.st-bad{border-left:3px solid var(--soil)}
blockquote.st-wait{border-left:3px solid var(--muted)}
blockquote.st-ok>p:first-child>strong:first-child{color:var(--green)}
blockquote :is(h1,h2,h3,h4){font-family:var(--sans);font-size:15px;font-weight:640;
  letter-spacing:0;text-transform:none;color:var(--text);border:0;padding:0;margin:0 0 10px}
blockquote :is(h1,h2,h3,h4)::before{display:none}  /* the callout edge already carries the state */

/* (4) evidence lines */
p.ev{font-family:var(--sans);font-size:13.5px;color:var(--muted);margin:0 0 22px}
pre+p.ev{margin-top:-8px}
p.ev em{font-style:italic;font-weight:600;color:var(--green)}
p.ev code{font-size:.9em}

/* (6) ADR schema fields */
.fld{font-family:var(--sans);font-size:.86em;font-weight:640;letter-spacing:.01em}
.own{font-family:var(--sans);font-size:.84em;color:var(--muted)}

/* (5) checklists */
li.task{list-style:none;margin-left:-1.15em}
.box{display:inline-block;width:11px;height:11px;margin-right:9px;position:relative;top:1px;
  border:1px solid var(--rule);border-radius:2px}
.box.on{background:var(--green);border-color:var(--green)}

/* ---- landing page ---- */
.lede{font-size:18px;color:var(--muted);max-width:64ch;margin:0 0 8px}
.grp{margin-top:56px}
.grp h2{margin-top:0}
.grp>p{font-size:14px;color:var(--muted);margin:-8px 0 18px;font-family:var(--sans)}
.cards{display:grid;gap:1px;background:var(--line);border:1px solid var(--line);border-radius:6px;
  overflow:hidden;max-width:100%}
.card{background:var(--surface);padding:15px 18px;display:flex;align-items:baseline;gap:14px;
  flex-wrap:wrap;text-decoration:none}
.card:hover{background:var(--code)}
.card b{font-family:var(--sans);font-size:15px;font-weight:600;letter-spacing:-.006em}
.card .path{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-left:auto}
main>footer{margin-top:64px;padding-top:22px;border-top:1px solid var(--line);
  font-family:var(--sans);font-size:12.5px;color:var(--muted)}

@media (max-width:640px){
  main{padding:66px 18px 90px}
  .bar .path{display:none}
  :is(h1,h2,h3,h4,h5,h6,li)[class*="st-"]::before{left:-11px}
}

@media print{
  /* `:root:root` on purpose. The dark rule above is `:root:not([data-theme="light"])` — (0,2,0),
     because :not() carries its argument's specificity — and it still matches while printing, since
     prefers-color-scheme is a user setting print does not clear. A plain `:root` here is (0,1,0)
     and loses to it, so Auto + dark OS (the default state for a dark-mode reader) printed a black
     page. Doubling :root ties at (0,2,0) and wins on source order, in every theme state. */
  :root:root{--bg:#fff;--surface:#fff;--code:#F4F2EF;--text:#111;--muted:#555;
    --line:#DCDCDC;--rule:#BBB;--green:#2F6B25;--soil:#8A3D24}
  .bar,.tsw{position:static;border:0;padding:0}
  .tsw,.bar .home{display:none}
  main{max-width:none;padding:0}
  pre,blockquote,table{break-inside:avoid}
  a{text-decoration:none}
}
"""


def title_of(text: str, fallback: str) -> str:
    m = re.search(r"^# (.+)$", text, re.M)
    if not m:
        return fallback
    t = re.sub(r"\s*\*\(.*?\)\*\s*$", "", m.group(1)).strip()
    return re.sub(r"^SwathKeeper\s*[—-]\s*", "", t) or fallback


def tab_title(title: str) -> str:
    """Browser-tab name. The site suffix is what tells you which repo a stray tab belongs to —
    but a doc that already says SwathKeeper doesn't need to say it twice."""
    return title if "SwathKeeper" in title else title + " — SwathKeeper"


def main() -> int:
    t0 = time.perf_counter()
    listed = [Path(p) for grp in GROUPS for p in grp[2]]
    found = [Path("README.md"), Path("SETUP.md"), Path("TIGER_TEAM_GUIDE.md")]
    found += [p.relative_to(ROOT) for p in sorted((ROOT / "docs").rglob("*.md"))]
    missing = [p for p in listed if p not in found]
    if missing:
        print("build_docs_site: listed but not on disk: %s" % ", ".join(map(str, missing)),
              file=sys.stderr)
        return 1
    extra = [p for p in found if p not in listed]
    groups = list(GROUPS) + ([("Other documents", "Not yet placed in the docs map.",
                               [p.as_posix() for p in extra])] if extra else [])

    global SOURCES
    SOURCES = set(found)
    md = markdown.Markdown(extensions=["extra", "toc", HeatmapNeutral()],
                           extension_configs={"toc": {"permalink": False}})

    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "docs").mkdir(parents=True, exist_ok=True)
    (OUT / "docs-site-style.css").write_text(CSS, "utf-8")
    (OUT / "docs-site.js").write_text(JS, "utf-8")

    titles: dict[Path, str] = {}
    drift: list[str] = []
    for src in found:
        try:
            text = (ROOT / src).read_text("utf-8")
            Ctx.src = src
            Ctx.up = "../" * len(src.parent.parts)
            Ctx.out = "../" * (len(src.parent.parts) + 1)   # + docs-site/ itself
            md.reset()
            body = md.convert(text)
        except Exception as exc:                    # unreadable or unconvertible -> fail loud
            print("build_docs_site: %s: %s" % (src, exc), file=sys.stderr)
            return 1
        # The site must render the headings the source declares — no more, no fewer. (A silent
        # extra <h1> is how `#5→#8),` mid-paragraph became a page title before this gate existed.)
        want, got = source_headings(text), len(re.findall(r"<h[1-6][ >]", body))
        if want != got:
            drift.append("%s: source declares %d headings, render produced %d" % (src, want, got))
        titles[src] = title_of(text, src.stem)
        dest = OUT / src.with_suffix(".html")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(PAGE.format(
            title=tab_title(titles[src]), up=Ctx.up, path=src.as_posix(),
            badge=BADGE if src.parent.name == "archive" else "", body=body), "utf-8")

    cards = []
    for name, blurb, paths in groups:
        rows = "".join(
            '<a class="card" href="%s"><b>%s</b>%s<span class="path">%s</span></a>' % (
                Path(p).with_suffix(".html").as_posix(), titles[Path(p)],
                BADGE if Path(p).parent.name == "archive" else "", p)
            for p in paths)
        cards.append('<section class="grp"><h2>%s</h2><p>%s</p><div class="cards">%s</div></section>'
                     % (name, blurb, rows))
    index = ('<h1>SwathKeeper docs</h1>\n<p class="lede">Autonomous drone survey in simulation — '
             'live reactive obstacle avoidance and NDVI crop-health mapping on ArduPilot + Gazebo '
             '+ ROS 2. Every page here is generated from the Markdown in the repo; the Markdown is '
             'the source of truth.</p>\n' + "\n".join(cards) +
             '\n<footer>%d documents · rendered by <code>scripts/build_docs_site.py</code> · '
             'style: D · Heatmap Neutral (ADR-014)</footer>' % len(found))
    (OUT / "index.html").write_text(PAGE.format(
        title="SwathKeeper docs", up="", path="docs-site/index.html", badge="", body=index), "utf-8")

    # Both gates run against the finished render, and both fail the build. A docs site that
    # ships a dead link or an invented heading is worse than one that refuses to ship.
    for line in drift:
        print("build_docs_site: heading drift: %s" % line, file=sys.stderr)
    for src, href, why in BROKEN:
        print("build_docs_site: broken link: %s -> %s (%s)" % (src, href, why), file=sys.stderr)
    if drift or BROKEN:
        print("build_docs_site: %d heading drift(s), %d broken link(s) — not shipping"
              % (len(drift), len(BROKEN)), file=sys.stderr)
        return 1

    print("built %d pages in %.2fs -> %s" % (len(found) + 1, time.perf_counter() - t0,
                                             OUT.relative_to(ROOT)))
    print("open docs-site/index.html")
    return 0


SOURCES: set[Path] = set()
BROKEN: list[tuple[Path, str, str]] = []

if __name__ == "__main__":
    sys.exit(main())
