# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
"""Fuzz `fetch_flagged_units`'s handling of the Weblate API's JSON response
body: json.loads() plus dict indexing (`data["results"]`, `data["next"]`),
no schema validation beyond the function's own try/except that turns a
malformed/adversarial response into a clean WeblateApiError. This is the
function actually called once per language on every real run (unlike
fetch_component_languages, only invoked when --languages is omitted), so it
gets its own harness despite the similar shape. A malicious or misconfigured
Weblate instance (or a MITM, since http:// is accepted) fully controls these
bytes. Network I/O is stubbed via `_fetch` so this never makes a real
request; MAX_PAGINATION_PAGES is patched down so a self-referencing "next"
(see test_fetch_flagged_units_stops_on_pagination_that_never_ends in the
test suite, which covers the same cap at its real value) can't slow the
fuzzer down — only the per-response parsing is under test here."""

import sys
from pathlib import Path
from unittest.mock import patch

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with atheris.instrument_imports(include=["weblate_checks_to_sarif"]):
    import weblate_checks_to_sarif as wcs


@atheris.instrument_func
def TestOneInput(data: bytes) -> None:
    with (
        patch.object(wcs, "_fetch", return_value=data),
        patch.object(wcs, "MAX_PAGINATION_PAGES", 5),
    ):
        try:
            units = wcs.fetch_flagged_units(
                "https://example.invalid", "proj", "comp", "en", None
            )
        except wcs.WeblateApiError:
            return  # malformed/adversarial API response — the function's
            # own try/except already turned it into a clean, known error
        assert isinstance(units, list)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
