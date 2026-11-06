#!/usr/bin/env python3
"""Render a swathkeeper-gates verdict's badge string as a flat SVG badge (stdlib only, byte-deterministic).

    python3 scripts/render_gates_badge.py examples/tarot_x4/verdict.json --label 'tarot_x4 · public log' \
        --out examples/tarot_x4/badge.svg            # write it
    python3 scripts/render_gates_badge.py examples/tarot_x4/verdict.json --label ... --check examples/tarot_x4/badge.svg
                                                     # exit 1 if the committed file differs from a fresh render

The message is the verdict's `badge` string VERBATIM (design §5: `gates: <word> · m/n measured[ · k declared …]
[ (post-hoc) | (unregistered)]`); nothing is summarised or recoloured beyond the word. The colour follows the
word only: pass green, fail red, "could not tell" and "refused" grey -- a fourth word is never a green (ADR-023).
No timestamp, no random id, so `regenerate + diff` is a gate (ci.yml, job gates-tool, via check_gates_examples.py).

Why an SVG in the tree rather than a shields.io endpoint: the README then depends on nothing but the repository
(the same no-network rule the dashboard keeps, ADR-018), it renders on any branch and in any fork, and the file is
regenerated and diffed by CI so it cannot drift from the verdict it depicts. Widths are approximate Verdana 11 px
metrics pinned with `textLength`, which is how shields.io itself makes its text fit.
"""
import argparse
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

COLOURS = {"pass": "#4c1", "fail": "#e05d44", "could not tell": "#9f9f9f", "refused": "#9f9f9f"}
LABEL_BG = "#555"
# Approximate advance widths at Verdana 11 px (shields.io measures the real font; textLength pins ours).
_NARROW = set("iljtfr .:,;'|!()[]·/")
_WIDE = set("mwMW%@")
_CAPS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def text_width_px(text: str) -> float:
    w = 0.0
    for ch in text:
        if ch in _NARROW:
            w += 3.6
        elif ch in _WIDE:
            w += 9.6
        elif ch in _CAPS or ch.isdigit():
            w += 7.2
        else:
            w += 6.5
    return round(w, 1)


def badge_word(badge: str) -> str:
    """The §5 word: everything between `gates: ` and the first ` ·` (or the end)."""
    body = badge.split("gates: ", 1)[1] if badge.startswith("gates: ") else badge
    return body.split(" ·", 1)[0].strip()


def render_svg(label: str, message: str) -> str:
    colour = COLOURS.get(badge_word(message), "#9f9f9f")
    lw = text_width_px(label) + 10          # 5 px padding each side
    mw = text_width_px(message) + 10
    width = lw + mw
    title = escape(f"{label}: {message}")
    lab, msg = escape(label), escape(message)
    # shields.io's "flat" template, values in tenths (transform scale(.1)) as shields writes them.
    lx, mx = (lw / 2) * 10, (lw + mw / 2) * 10
    ltl, mtl = (lw - 10) * 10, (mw - 10) * 10
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width:g}" '
        f'height="20" role="img" aria-label="{title}">'
        f'<title>{title}</title>'
        '<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        '<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{width:g}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)"><rect width="{lw:g}" height="20" fill="{LABEL_BG}"/>'
        f'<rect x="{lw:g}" width="{mw:g}" height="20" fill="{colour}"/>'
        f'<rect width="{width:g}" height="20" fill="url(#s)"/></g>'
        '<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" '
        'text-rendering="geometricPrecision" font-size="110">'
        f'<text aria-hidden="true" x="{lx:g}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" '
        f'textLength="{ltl:g}">{lab}</text>'
        f'<text x="{lx:g}" y="140" transform="scale(.1)" fill="#fff" textLength="{ltl:g}">{lab}</text>'
        f'<text aria-hidden="true" x="{mx:g}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" '
        f'textLength="{mtl:g}">{msg}</text>'
        f'<text x="{mx:g}" y="140" transform="scale(.1)" fill="#fff" textLength="{mtl:g}">{msg}</text>'
        '</g></svg>\n'
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("verdict", help="a swathkeeper-verdict/1.0 JSON file")
    ap.add_argument("--label", default="swathkeeper-gates", help="the badge's left-hand text")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out", help="write the SVG here")
    g.add_argument("--check", help="compare a fresh render against this committed SVG; exit 1 on any difference")
    a = ap.parse_args(argv)
    try:
        verdict = json.loads(Path(a.verdict).read_text())
        badge = verdict["badge"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"[render_gates_badge] REFUSED: cannot read a badge from {a.verdict}: {e}", file=sys.stderr)
        return 2
    if not isinstance(badge, str) or not badge.startswith("gates: "):
        print(f"[render_gates_badge] REFUSED: {a.verdict} has no 'gates: …' badge (got {badge!r})", file=sys.stderr)
        return 2
    svg = render_svg(a.label, badge)
    if a.out:
        Path(a.out).write_text(svg)
        print(f"[render_gates_badge] wrote {a.out}: '{a.label}' | '{badge}' ({len(svg)} bytes)")
        return 0
    committed = Path(a.check)
    if not committed.is_file():
        print(f"[render_gates_badge] FAIL: {a.check} is not committed; render it with --out", file=sys.stderr)
        return 1
    if committed.read_text() != svg:
        print(f"[render_gates_badge] FAIL: {a.check} differs from a fresh render of '{badge}' -- regenerate it "
              f"(and read why the verdict changed) rather than editing the SVG", file=sys.stderr)
        return 1
    print(f"[render_gates_badge] {a.check} is current: '{a.label}' | '{badge}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
