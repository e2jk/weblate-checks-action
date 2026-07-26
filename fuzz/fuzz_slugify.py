"""Fuzz `_slugify`, which turns a Weblate check name into a SARIF rule ID."""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with atheris.instrument_imports(include=["weblate_checks_to_sarif"]):
    import weblate_checks_to_sarif as wcs

_SLUG_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


@atheris.instrument_func
def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    name = fdp.ConsumeUnicodeNoSurrogates(256)

    slug = wcs._slugify(name)

    assert isinstance(slug, str)
    assert slug != ""  # falls back to "unknown-check", never empty
    assert not slug.startswith("-")
    assert not slug.endswith("-")
    assert all(c in _SLUG_CHARS for c in slug)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
