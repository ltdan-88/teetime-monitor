"""The README and the docs: every picture and every link to another file must exist, and the English and German
READMEs must show the same screenshots (a renamed picture once left a broken image on the front page)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", ROOT / "README.de.md", *sorted((ROOT / "docs").glob("*.md"))]


def _targets(text: str) -> list[str]:
    found = re.findall(r'(?:src|href)="([^"]+)"', text) + re.findall(r"\]\(([^)\s]+)\)", text)
    return [t.split("#")[0] for t in found if not t.startswith(("http", "#", "mailto:")) and t.split("#")[0]]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_local_link_and_picture_exists(doc):
    missing = [t for t in _targets(doc.read_text(encoding="utf-8")) if not (doc.parent / t).resolve().exists()]
    assert missing == []


def test_both_readmes_show_the_same_screenshots():
    def pictures(name, lang):
        return sorted(Path(t).name for t in _targets((ROOT / name).read_text(encoding="utf-8")) if t.startswith(f"assets/{lang}/"))

    assert pictures("README.md", "en") == pictures("README.de.md", "de")
