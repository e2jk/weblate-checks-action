# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
"""Fuzz `_fetch`'s URL-scheme validation — the only thing standing between
a malicious/misconfigured `--weblate-url` (or an API-echoed `web_url`) and
urlopen() reading a local file:// path or similar. Network I/O is stubbed
out so this never makes a real request, however the fuzzer twists the URL —
only the scheme-validation logic itself is under test."""

import sys
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with atheris.instrument_imports(include=["weblate_checks_to_sarif"]):
    import weblate_checks_to_sarif as wcs


class _NoNetwork(Exception):
    """Raised by the stubbed urlopen — proves _fetch got past scheme
    validation and would have made a real request."""


def _stub_urlopen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN201
    raise _NoNetwork


@atheris.instrument_func
def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    url = fdp.ConsumeUnicodeNoSurrogates(512)

    with patch("urllib.request.urlopen", side_effect=_stub_urlopen):
        try:
            wcs._fetch(url, None)
        except wcs.ToolError as exc:
            if "non-http" in str(exc):
                return  # correctly rejected
            raise  # some other ToolError — not the scheme guard, unexpected
        except _NoNetwork:
            # Got past scheme validation to the real urlopen call — only
            # acceptable if the scheme really was http(s).
            scheme = urllib.parse.urlparse(url).scheme
            assert scheme in ("http", "https"), (
                f"non-http(s) URL {url!r} (scheme {scheme!r}) reached urlopen()"
            )
        except (urllib.error.URLError, UnicodeError, ValueError):
            return  # urlparse/Request's own input validation rejected it


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
