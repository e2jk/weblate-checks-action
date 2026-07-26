# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
"""Fuzz `_parse_locations`, which parses Weblate's comma-separated
`location` field ("file:line, file2:line2, ...") from arbitrary API
responses."""

import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with atheris.instrument_imports(include=["weblate_checks_to_sarif"]):
    import weblate_checks_to_sarif as wcs


@atheris.instrument_func
def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    location_field = fdp.ConsumeUnicodeNoSurrogates(512)

    locations = wcs._parse_locations(location_field)

    assert isinstance(locations, list)
    for uri, line in locations:
        # A blank artifactLocation.uri is never valid SARIF — caught a real
        # instance of this during harness development (a ":5"-style token),
        # fixed in _parse_locations itself.
        assert isinstance(uri, str)
        assert uri != ""
        assert line is None or (isinstance(line, int) and line >= 0)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
