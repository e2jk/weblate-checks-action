# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
"""Fuzz `fetch_unit_checks`'s handling of the Weblate API's JSON response
bodies — one search per check name ("check:<name>"), whose results it
matches against the flagged units' IDs. A malicious or misconfigured
Weblate instance (or a MITM, since http:// is accepted) fully controls these
bytes: any shape must end in a clean WeblateApiError or a well-formed
{unit id: [check names]} map, never a crash. Network I/O is stubbed via
`_fetch` (every search gets the same fuzzed body) and MAX_PAGINATION_PAGES is
patched down so a self-referencing "next" can't slow the fuzzer down."""

import sys
from pathlib import Path
from unittest.mock import patch

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with atheris.instrument_imports(include=["weblate_checks_to_sarif"]):
    import weblate_checks_to_sarif as wcs


UNITS = [{"id": 1}, {"id": 2}]


@atheris.instrument_func
def TestOneInput(data: bytes) -> None:
    with (
        patch.object(wcs, "_fetch", return_value=data),
        patch.object(wcs, "MAX_PAGINATION_PAGES", 5),
        patch.object(wcs, "CHECKS", wcs.CHECKS[:3]),
    ):
        try:
            found = wcs.fetch_unit_checks(
                "https://example.invalid", "proj", "comp", "en", UNITS, None
            )
        except wcs.WeblateApiError:
            return  # malformed/adversarial API response — turned into a
            # clean, known error by the shared search's own try/except
        assert set(found) == {1, 2}
        assert all(isinstance(names, list) for names in found.values())


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
