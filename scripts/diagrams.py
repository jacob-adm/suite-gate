#!/usr/bin/env python3
"""Render docs/diagrams/*.mmd to SVG images with Mermaid in headless Chrome.

The pages show the SVG files, so the diagrams read the same on GitHub, on PyPI and in any
Markdown viewer. Labels are plain SVG text (no HTML labels), which every image viewer draws,
and each image gets a white background so it stays readable on a dark page.

    python3 scripts/diagrams.py [NAME ...]

Needs Google Chrome (or CHROME=path) and network access to load MERMAID once per diagram.
"""

import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ROOT / "docs" / "diagrams"
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"
CONFIG = {
    "startOnLoad": False,
    "theme": "default",
    "securityLevel": "strict",
    "htmlLabels": False,
    "flowchart": {"htmlLabels": False},
    "fontFamily": "ui-sans-serif, system-ui, -apple-system, Segoe UI, Helvetica, Arial, sans-serif",
}

PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<pre id="out">PENDING</pre>
<script type="module">
import mermaid from {mermaid};
const out = document.getElementById("out");
try {{
  mermaid.initialize({config});
  const {{ svg }} = await mermaid.render("diagram", {source});
  out.textContent = svg;
}} catch (e) {{
  out.textContent = "ERROR " + e;
}}
</script></body></html>
"""


def render(source):
    """Return the SVG Mermaid draws for one diagram source."""
    page = PAGE.format(mermaid=json.dumps(MERMAID), config=json.dumps(CONFIG), source=json.dumps(source))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.html"
        path.write_text(page)
        dom = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=20000",
                              "--dump-dom", path.as_uri()],
                             check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    found = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    text = html.unescape(found.group(1)) if found else "ERROR no output"
    if not text.startswith("<svg"):
        raise SystemExit(f"Mermaid did not render: {text[:300]}")
    return with_background(text)


def with_background(svg):
    """Put a white rectangle behind the drawing, as the first element of the SVG."""
    end = svg.index(">") + 1
    return svg[:end] + '<rect x="-50%" y="-50%" width="200%" height="200%" fill="#ffffff"/>' + svg[end:] + "\n"


def main():
    names = sys.argv[1:] or sorted(p.stem for p in DIAGRAMS.glob("*.mmd"))
    for name in names:
        svg = render((DIAGRAMS / f"{name}.mmd").read_text())
        (DIAGRAMS / f"{name}.svg").write_text(svg)
        print(f"docs/diagrams/{name}.svg")


if __name__ == "__main__":
    main()
