# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
"""Fuzz `fetch_component_languages`'s handling of the Weblate API's JSON
response body: json.loads() plus dict indexing/fallback
(`data["results"]`, `translation.get("language_code") or
translation["language"]["code"]`, `data["next"]`), no schema validation
beyond the function's own try/except that turns a malformed/adversarial
response into a clean WeblateApiError. A malicious or misconfigured Weblate
instance (or a MITM, since http:// is accepted) fully controls these bytes.
Network I/O is stubbed via `_fetch` so this never makes a real request;
MAX_PAGINATION_PAGES is patched down so a self-referencing "next" (see
test_fetch_component_languages_stops_on_pagination_that_never_ends in the
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
            languages = wcs.fetch_component_languages(
                "https://example.invalid", "proj", "comp", None
            )
        except wcs.WeblateApiError:
            return  # malformed/adversarial API response — the function's
            # own try/except already turned it into a clean, known error
        # Not asserting str-typed elements here: a "language_code" that's
        # present but non-string (e.g. an int) is accepted as-is and only
        # produces a nonsensical downstream query, not a crash — a data
        # quality issue, not the crash class this harness targets.
        assert isinstance(languages, list)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
