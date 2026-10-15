#!/usr/bin/env python3
"""Build the documentation site's shared parts and its agent bundle.

    python scripts/build_docs.py          # rewrite nav, page links, and docs/bundle.md
    python scripts/build_docs.py --check  # exit 1 if any of them is out of date

Every page carries the same top navigation and previous/next links, written from
PAGES below, and docs/bundle.md is the pages' text converted to Markdown. Edit
the pages, then run this; never edit the bundle by hand.
"""

from __future__ import annotations

import argparse
import re
import sys
from html import escape
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SITE = "https://lavallee.github.io/spindle/"

# (file, nav label, title used in previous/next links), in reading order.
PAGES = [
    ("index.html", "Overview", "Overview"),
    ("rationale.html", "Why", "Why a small house"),
    ("house.html", "House", "The house"),
    ("catalog.html", "Catalog", "The catalog and on-demand skills"),
    ("lifecycle.html", "Lifecycle", "The vetting lifecycle"),
    ("how-it-works.html", "How it works", "How it works"),
    ("evaluation.html", "Evaluation", "Does the skill help?"),
    ("guide.html", "Guide", "Using Spindle"),
]

NAV = re.compile(r'(?:<!-- nav:begin -->.*?<!-- nav:end -->|<nav class="site-nav">.*?</nav>)', re.S)
PAGENAV = re.compile(r'<nav class="pagenav">.*?</nav>', re.S)


def nav_html(current: str) -> str:
    current_mark = ' aria-current="page"'
    links = "\n".join(
        f'    <a href="{name}"{current_mark if name == current else ""}>{label}</a>'
        for name, label, _title in PAGES
    )
    return (
        "<!-- nav:begin -->\n"
        '<nav class="site-nav">\n'
        '  <a class="brand" href="index.html"><span class="spin"></span>spindle</a>\n'
        '  <button class="nav-toggle" aria-label="Menu">menu</button>\n'
        '  <div class="nav-links">\n'
        f"{links}\n"
        '    <a href="https://github.com/lavallee/spindle">GitHub</a>\n'
        "  </div>\n"
        '  <button data-theme-toggle class="nav-toggle" style="display:block;margin-left:auto" '
        'aria-label="Toggle theme">theme</button>\n'
        "</nav>\n"
        "<!-- nav:end -->"
    )


def pagenav_html(index: int) -> str:
    def link(css: str, direction: str, target: int) -> str:
        name, _label, title = PAGES[target]
        return (f'    <a class="{css}" href="{name}">\n'
                f'      <span class="dir">{direction}</span>\n'
                f'      <span class="ttl">{escape(title)}</span>\n'
                "    </a>")
    if index == 0:
        prev = ('    <a class="prev" href="https://github.com/lavallee/spindle">\n'
                '      <span class="dir">Source</span>\n'
                '      <span class="ttl">github.com/lavallee/spindle</span>\n'
                "    </a>")
    else:
        prev = link("prev", "← Previous", index - 1)
    nxt = (link("next", "Next →", index + 1) if index + 1 < len(PAGES)
           else link("next", "Start over →", 0))
    return f'<nav class="pagenav">\n{prev}\n{nxt}\n  </nav>'


class _Markdown(HTMLParser):
    """Convert one page's <main> into plain Markdown for the agent bundle."""

    SKIP = {"pagenav", "toc", "terminal-bar", "colophon", "site-nav", "n", "meta-row"}
    TITLES = {"callout-title"}
    BLOCKS = {"p", "li", "dt", "dd", "h1", "h2", "h3", "h4", "tr", "aside", "div"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.buf: list[str] = []
        self.in_main = False
        self.skip_depth = 0
        self.stack: list[tuple[str, bool, bool]] = []
        self.pre = False
        self.cells: list[str] = []
        self.header_row = False
        self.rows = 0
        self.lists: list[str] = []
        self.counters: list[int] = []

    def flush(self, prefix: str = "") -> None:
        text = " ".join("".join(self.buf).split())
        self.buf = []
        if text:
            self.out.append(prefix + text)

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "main":
            self.in_main = True
        skipped = bool(classes & self.SKIP) or tag in {"script", "style", "nav"} and "toc" not in classes
        self.stack.append((tag, skipped, bool(classes & ({"term"} | self.TITLES))))
        if skipped:
            self.skip_depth += 1
        if not self.in_main or self.skip_depth:
            return
        if tag == "pre":
            self.flush()
            self.pre = True
            self.buf.append("```text\n")
        elif tag in {"ul", "ol"}:
            self.flush()
            self.lists.append(tag)
            self.counters.append(0)
        elif tag == "table":
            self.flush()
            self.rows = 0
        elif tag in {"td", "th"}:
            self.cells.append("")
            self.header_row = tag == "th"
        elif tag == "code" and not self.pre:
            self.buf.append("`")
        elif tag in {"strong", "b"} or classes & ({"term"} | self.TITLES):
            self.buf.append("**")
        elif tag == "em":
            self.buf.append("*")
        elif tag in self.BLOCKS:
            self.flush()

    def handle_endtag(self, tag):
        if not self.stack:
            return
        open_tag, skipped, term = self.stack.pop()
        while open_tag != tag and self.stack:
            open_tag, skipped, term = self.stack.pop()
        if skipped:
            self.skip_depth -= 1
            return
        if tag == "main":
            self.flush()
            self.in_main = False
        if not self.in_main or self.skip_depth:
            return
        if tag == "pre":
            self.out.append("".join(self.buf).rstrip() + "\n```")
            self.buf, self.pre = [], False
        elif tag == "code" and not self.pre:
            self.buf.append("`")
        elif tag in {"strong", "b"}:
            self.buf.append("**")
        elif term:
            self.buf.append(":** ")
        elif tag == "em":
            self.buf.append("*")
        elif tag in {"td", "th"}:
            self.cells[-1] = " ".join("".join(self.buf).split())
            self.buf = []
        elif tag == "tr":
            self.out.append("| " + " | ".join(self.cells) + " |")
            if self.rows == 0:
                self.out.append("|" + " --- |" * len(self.cells))
            self.rows += 1
            self.cells = []
        elif tag == "li":
            if self.lists[-1] == "ol":
                self.counters[-1] += 1
                self.flush(f"{self.counters[-1]}. ")
            else:
                self.flush("- ")
        elif tag in {"ul", "ol"}:
            self.lists.pop()
            self.counters.pop()
            self.out.append("")
        elif tag in {"h1", "h2", "h3", "h4"}:
            self.flush("#" * (int(tag[1]) + 1) + " ")
        elif tag == "dt":
            self.flush("**")
            self.out[-1] += "**"
        elif tag in self.BLOCKS:
            self.flush()

    def handle_data(self, data):
        if self.in_main and not self.skip_depth:
            self.buf.append(data)


def page_markdown(name: str) -> str:
    parser = _Markdown()
    parser.feed((DOCS / name).read_text(encoding="utf-8"))
    lines, previous = [], None
    for line in parser.out:
        if line == "" and previous == "":
            continue
        lines.append(line)
        previous = line
    body = "\n\n".join(line for line in lines if line != "").replace("\n\n|", "\n|")
    return f"<!-- {SITE}{name} -->\n\n{body}\n"


def bundle() -> str:
    head = (
        "# Spindle — complete documentation bundle\n\n"
        "> Generated by scripts/build_docs.py from the pages of " + SITE + ".\n"
        "> One file for an agent's context. Source: https://github.com/lavallee/spindle"
        " · MIT licensed.\n\n"
    )
    return head + "\n---\n\n".join(page_markdown(name) for name, _label, _title in PAGES)


def built_pages() -> dict[Path, str]:
    result = {}
    for index, (name, _label, _title) in enumerate(PAGES):
        path = DOCS / name
        text = path.read_text(encoding="utf-8")
        if not NAV.search(text) or not PAGENAV.search(text):
            raise SystemExit(f"{name}: missing site nav or page nav")
        text = NAV.sub(lambda _m: nav_html(name), text, count=1)
        text = PAGENAV.sub(lambda _m: pagenav_html(index), text, count=1)
        result[path] = text
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    pages = built_pages()
    if args.check:
        stale = [p.name for p, text in pages.items() if p.read_text(encoding="utf-8") != text]
        if (DOCS / "bundle.md").read_text(encoding="utf-8") != bundle():
            stale.append("bundle.md")
        if stale:
            print("out of date: " + ", ".join(stale) + " (run scripts/build_docs.py)")
            return 1
        print("docs are current")
        return 0
    for path, text in pages.items():
        path.write_text(text, encoding="utf-8")
    (DOCS / "bundle.md").write_text(bundle(), encoding="utf-8")
    print(f"wrote nav for {len(PAGES)} pages and docs/bundle.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
