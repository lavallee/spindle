"""Public documentation remains aligned with the implemented 0.2 lifecycle."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
PUBLIC_PAGES = (
    "index.html",
    "rationale.html",
    "lifecycle.html",
    "how-it-works.html",
    "evaluation.html",
    "guide.html",
)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "link", "script"}:
            return
        values = dict(attrs)
        target = values.get("href") or values.get("src")
        if target:
            self.targets.append(target)


def test_public_html_parses_links_locally_and_routes_through_lifecycle():
    for name in PUBLIC_PAGES:
        page = DOCS / name
        text = page.read_text(encoding="utf-8")
        parser = _Links()
        parser.feed(text)
        parser.close()

        assert 'href="lifecycle.html"' in text
        for target in parser.targets:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or target.startswith(("data:", "#")):
                continue
            assert (page.parent / parts.path).exists(), f"{name}: missing {target}"


def test_readme_and_agent_docs_lead_with_the_implemented_0_2_lifecycle():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    llms = (DOCS / "llms.txt").read_text(encoding="utf-8")
    bundle = (DOCS / "bundle.md").read_text(encoding="utf-8")
    artifact = (ROOT / "artifact.toml").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "evidence-bearing lifecycle and control plane" in readme
    assert "try before adopting" in readme.lower()
    assert "evolving into" not in readme
    assert "Spindle v0.2" in llms
    assert "inspect → try/borrow → compose → bootstrap" in llms
    assert "Describes Spindle v0.2" in bundle
    assert "The current product direction expands" not in bundle
    assert "evidence-bearing lifecycle and control plane" in artifact
    assert "Evidence-bearing lifecycle and control plane" in project


def test_operational_examples_keep_mutation_and_retirement_explicit():
    guide = (DOCS / "guide.html").read_text(encoding="utf-8")
    lifecycle = (DOCS / "lifecycle.html").read_text(encoding="utf-8")

    assert "bootstrap --harness codex --here --reconcile-owned --dry-run" not in guide
    assert "retire review --harness codex --reason obsolete" in guide
    assert "retire review --harness codex --reason obsolete" in lifecycle
    assert "eval matrix validate matrix.toml" in guide
