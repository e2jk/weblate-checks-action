"""Fuzz the HTML "Things to check" panel parser used to extract Weblate
check names/descriptions from a scraped translate page."""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with atheris.instrument_imports(include=["weblate_checks_to_sarif"]):
    import weblate_checks_to_sarif as wcs


@atheris.instrument_func
def TestOneInput(data: bytes) -> None:
    # Mirrors scrape_checks's own decode: bytes fetched over the network,
    # decoded permissively since Weblate's encoding isn't guaranteed.
    page = data.decode("utf-8", errors="replace")

    checks = []
    for m in wcs.CHECK_ITEM_RE.finditer(page):
        name = wcs._clean_html_text(m.group("name"))
        desc = wcs._clean_html_text(m.group("desc") or "")
        checks.append((name, desc))

    for name, desc in checks:
        assert isinstance(name, str)
        assert isinstance(desc, str)
        # _clean_html_text collapses whitespace and strips ends — a
        # leftover leading/trailing space would mean the collapse regex
        # missed a case.
        assert name == name.strip()
        assert desc == desc.strip()


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
