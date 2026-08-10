# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

import weblate_checks_to_sarif as wcs

# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Reused translation", "reused-translation"),
        ("XML markup", "xml-markup"),
        ("  Weird!! Name??  ", "weird-name"),
        ("", "unknown-check"),
    ],
)
def test_slugify(name, expected):
    assert wcs._slugify(name) == expected


@pytest.mark.parametrize(
    "location,expected",
    [
        ("", []),
        (
            "app/templates/foo.html:12",
            [("app/templates/foo.html", 12)],
        ),
        (
            "app/templates/foo.html:12, app/templates/bar.html:34",
            [("app/templates/foo.html", 12), ("app/templates/bar.html", 34)],
        ),
        ("app/templates/foo.html", [("app/templates/foo.html", None)]),
        (" , app/templates/foo.html:5, ", [("app/templates/foo.html", 5)]),
        # A token that's just ":5" rpartitions to an empty uri — must not
        # produce a location with an empty artifactLocation.uri; falls back
        # to treating the whole token as an opaque (unparsed) uri instead.
        (":5", [(":5", None)]),
        # '³' (superscript three, U+00B3) passes str.isdigit() but isn't
        # parseable by int() — found by fuzz/fuzz_parse_locations.py.
        ("foo.html:³", [("foo.html:³", None)]),
    ],
)
def test_parse_locations(location, expected):
    assert wcs._parse_locations(location) == expected


def test_clean_html_text_strips_tags_and_collapses_whitespace():
    fragment = '<svg>icon</svg>  Reused   translation <span class="x">3</span>'
    assert wcs._clean_html_text(fragment) == "icon Reused translation 3"


def test_scrape_checks_parses_things_to_check_panel():
    page = """
    <div class="list-group-item check check-item ">
      <h5>Reused translation</h5>
      <p class="list-group-item-text check-description">Other source string: "Record"</p>
    </div>
    <div class="list-group-item check check-item ">
      <h5>Unchanged translation</h5>
    </div>
    """
    with patch.object(wcs, "_fetch", return_value=page.encode("utf-8")):
        checks = wcs.scrape_checks("https://example.org/translate/1", None)
    assert checks == [
        ("Reused translation", 'Other source string: "Record"'),
        ("Unchanged translation", ""),
    ]


def test_scrape_checks_returns_empty_on_fetch_failure():
    with patch.object(wcs, "_fetch", side_effect=wcs.WeblateApiError("boom")):
        assert wcs.scrape_checks("https://example.org/translate/1", None) == []


# ---------------------------------------------------------------------------
# _fetch error handling (mocking urllib.request.urlopen directly)
# ---------------------------------------------------------------------------


def _http_error(code, headers=None):
    return urllib.error.HTTPError(
        "https://example.org/api/units/", code, "err", headers or {}, None
    )


def test_fetch_rejects_non_http_schemes():
    with (
        patch("urllib.request.urlopen") as mock_urlopen,
        pytest.raises(wcs.ToolError, match="non-http"),
    ):
        wcs._fetch("file:///etc/passwd", None)
    mock_urlopen.assert_not_called()


def test_fetch_raises_rate_limit_exceeded_on_429():
    with (
        patch("urllib.request.urlopen", side_effect=_http_error(429)),
        pytest.raises(wcs.RateLimitExceeded),
    ):
        wcs._fetch("https://example.org/api/units/", None)


def test_fetch_raises_weblate_api_error_on_403():
    with (
        patch("urllib.request.urlopen", side_effect=_http_error(403)),
        pytest.raises(wcs.WeblateApiError, match="rejected"),
    ):
        wcs._fetch("https://example.org/api/units/", "bad-token")


def test_fetch_raises_weblate_api_error_on_connection_failure():
    with (
        patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("no route to host"),
        ),
        pytest.raises(wcs.WeblateApiError, match="Could not reach"),
    ):
        wcs._fetch("https://example.org/api/units/", None)


def test_fetch_rate_limit_message_includes_reset_time():
    err = _http_error(429, headers={"X-RateLimit-Reset": "5400"})
    with (
        patch("urllib.request.urlopen", side_effect=err),
        pytest.raises(wcs.RateLimitExceeded, match=r"Resets in ~1h30m"),
    ):
        wcs._fetch("https://example.org/api/units/", None)


def test_fetch_reraises_unhandled_http_error():
    with (
        patch("urllib.request.urlopen", side_effect=_http_error(500)),
        pytest.raises(urllib.error.HTTPError) as exc_info,
    ):
        wcs._fetch("https://example.org/api/units/", None)
    assert exc_info.value.code == 500


def test_fetch_retries_once_on_503_then_succeeds():
    success_resp = MagicMock()
    success_resp.__enter__.return_value.read.return_value = b"ok"
    with (
        patch("urllib.request.urlopen", side_effect=[_http_error(503), success_resp]),
        patch("time.sleep") as mock_sleep,
    ):
        assert wcs._fetch("https://example.org/api/units/", None) == b"ok"
    mock_sleep.assert_called_once_with(5)


# ---------------------------------------------------------------------------
# fetch_flagged_units pagination
# ---------------------------------------------------------------------------


def test_fetch_flagged_units_follows_pagination():
    page1 = json.dumps(
        {"results": [{"id": 1}], "next": "https://example.org/api/units/?page=2"}
    ).encode()
    page2 = json.dumps({"results": [{"id": 2}], "next": None}).encode()

    with patch.object(wcs, "_fetch", side_effect=[page1, page2]):
        units = wcs.fetch_flagged_units(
            "https://example.org", "proj", "comp", "fr", None
        )
    assert [u["id"] for u in units] == [1, 2]


def test_fetch_flagged_units_stops_on_pagination_that_never_ends():
    # A malicious/misconfigured server (or a MITM, since http:// is
    # accepted) whose "next" link never becomes falsy must not hang the run
    # forever — it should degrade to a clean, catchable error instead.
    looping_page = json.dumps(
        {"results": [], "next": "https://example.org/api/units/?page=2"}
    ).encode()

    with (
        patch.object(wcs, "_fetch", return_value=looping_page),
        patch.object(wcs, "MAX_PAGINATION_PAGES", 3),
        pytest.raises(wcs.WeblateApiError, match="Exceeded 3 pagination pages"),
    ):
        wcs.fetch_flagged_units("https://example.org", "proj", "comp", "fr", None)


# A JSON object nested this deep blows Python's recursion limit inside
# json.loads() itself — deep enough to be reliable, still parses in ~10ms.
_DEEPLY_NESTED_JSON = ('{"a":' * 200_000 + "1" + "}" * 200_000).encode()


@pytest.mark.parametrize(
    "bad_response",
    [
        b"not json",
        b"\xff\xfe not valid utf-8",
        b'{"results": []}',  # missing "next"
        b'{"next": null}',  # missing "results"
        b'{"results": 5, "next": null}',  # "results" not iterable
        _DEEPLY_NESTED_JSON,
    ],
)
def test_fetch_flagged_units_raises_clean_error_on_malformed_response(bad_response):
    # A malicious/misconfigured server (or a MITM, since http:// is
    # accepted) fully controls this response body — a bad shape must not
    # crash with a raw traceback.
    with (
        patch.object(wcs, "_fetch", return_value=bad_response),
        pytest.raises(wcs.WeblateApiError, match="unexpected response"),
    ):
        wcs.fetch_flagged_units("https://example.org", "proj", "comp", "fr", None)


# ---------------------------------------------------------------------------
# fetch_component_languages (auto-discovery)
# ---------------------------------------------------------------------------


def test_fetch_component_languages_uses_top_level_language_code():
    page = json.dumps(
        {
            "results": [
                {"language_code": "en", "language": {"code": "should-not-be-used"}},
                {"language_code": "fr", "language": {"code": "should-not-be-used"}},
            ],
            "next": None,
        }
    ).encode()

    with patch.object(wcs, "_fetch", return_value=page):
        languages = wcs.fetch_component_languages(
            "https://example.org", "proj", "comp", None
        )
    assert languages == ["en", "fr"]


def test_fetch_component_languages_falls_back_to_nested_language_code():
    page = json.dumps(
        {"results": [{"language": {"code": "nl"}}], "next": None}
    ).encode()

    with patch.object(wcs, "_fetch", return_value=page):
        languages = wcs.fetch_component_languages(
            "https://example.org", "proj", "comp", None
        )
    assert languages == ["nl"]


def test_fetch_component_languages_follows_pagination():
    page1 = json.dumps(
        {
            "results": [{"language_code": "en"}],
            "next": "https://example.org/api/components/proj/comp/translations/?page=2",
        }
    ).encode()
    page2 = json.dumps({"results": [{"language_code": "fr"}], "next": None}).encode()

    with patch.object(wcs, "_fetch", side_effect=[page1, page2]):
        languages = wcs.fetch_component_languages(
            "https://example.org", "proj", "comp", None
        )
    assert languages == ["en", "fr"]


def test_fetch_component_languages_stops_on_pagination_that_never_ends():
    looping_page = json.dumps(
        {
            "results": [],
            "next": "https://example.org/api/components/proj/comp/translations/?page=2",
        }
    ).encode()

    with (
        patch.object(wcs, "_fetch", return_value=looping_page),
        patch.object(wcs, "MAX_PAGINATION_PAGES", 3),
        pytest.raises(wcs.WeblateApiError, match="Exceeded 3 pagination pages"),
    ):
        wcs.fetch_component_languages("https://example.org", "proj", "comp", None)


@pytest.mark.parametrize(
    "bad_response",
    [
        b"not json",
        b"\xff\xfe not valid utf-8",
        b'{"results": []}',  # missing "next"
        b'{"next": null}',  # missing "results"
        b'{"results": 5, "next": null}',  # "results" not iterable
        b'{"results": ["not-a-dict"], "next": null}',  # no .get()
        b'{"results": [{}], "next": null}',  # no "language_code"/"language"
        _DEEPLY_NESTED_JSON,
    ],
)
def test_fetch_component_languages_raises_clean_error_on_malformed_response(
    bad_response,
):
    with (
        patch.object(wcs, "_fetch", return_value=bad_response),
        pytest.raises(wcs.WeblateApiError, match="unexpected response"),
    ):
        wcs.fetch_component_languages("https://example.org", "proj", "comp", None)


# ---------------------------------------------------------------------------
# build_sarif end-to-end (mocking the two network-facing functions)
# ---------------------------------------------------------------------------


def _unit(uid, source, target, location):
    return {
        "id": uid,
        "source": [source],
        "target": [target],
        "location": location,
        "web_url": f"https://example.org/translate/{uid}",
    }


def test_build_sarif_maps_severity_and_deduplicates_rules():
    units_by_lang = {
        "fr": [_unit(1, "Hello", "Bonjour", "app/templates/a.html:10")],
        "en": [_unit(2, "Hello", "Hi", "")],
    }
    checks_by_unit = {
        1: [("Reused translation", "Other source string")],
        2: [("Python format", "Mismatched %(name)s"), ("Reused translation", "")],
    }

    def fake_fetch(_weblate_url, _project, _component, language, _token):
        return units_by_lang[language]

    def fake_scrape(translate_url, _token):
        uid = int(translate_url.rsplit("/", 1)[-1])
        return checks_by_unit[uid]

    with (
        patch.object(wcs, "fetch_flagged_units", side_effect=fake_fetch),
        patch.object(wcs, "scrape_checks", side_effect=fake_scrape),
        patch("time.sleep"),
    ):
        sarif, flagged_count = wcs.build_sarif(
            "https://example.org",
            "proj",
            "comp",
            ["fr", "en"],
            None,
            0.0,
            set(wcs.DEFAULT_WARNING_CHECKS),
        )

    assert flagged_count == 2
    run = sarif["runs"][0]
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert rule_ids == {"reused-translation", "python-format"}

    levels = {r["ruleId"]: r["level"] for r in run["results"]}
    assert levels["python-format"] == "warning"
    assert levels["reused-translation"] == "note"

    # The fr unit has a parseable location; the en unit's empty location
    # field must not fabricate a fake one.
    fr_result = next(r for r in run["results"] if "Bonjour" in r["message"]["text"])
    assert fr_result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == (
        "app/templates/a.html"
    )
    en_results = [r for r in run["results"] if '"Hi"' in r["message"]["text"]]
    assert all("locations" not in r for r in en_results)


def test_build_sarif_verbose_logs_each_string(capsys):
    with (
        patch.object(
            wcs,
            "fetch_flagged_units",
            return_value=[_unit(1, "Hello world", "Bonjour", "")],
        ),
        patch.object(wcs, "scrape_checks", return_value=[("Reused translation", "")]),
        patch("time.sleep"),
    ):
        wcs.build_sarif(
            "https://example.org",
            "proj",
            "comp",
            ["fr"],
            None,
            0.0,
            set(),
            verbose=True,
        )
    captured = capsys.readouterr()
    assert "Hello world" in captured.err
    assert "Reused translation" in captured.err


def test_build_sarif_falls_back_to_unknown_check_when_scrape_finds_nothing():
    with (
        patch.object(
            wcs,
            "fetch_flagged_units",
            return_value=[_unit(1, "Hi", "Salut", "")],
        ),
        patch.object(wcs, "scrape_checks", return_value=[]),
        patch("time.sleep"),
    ):
        sarif, flagged_count = wcs.build_sarif(
            "https://example.org", "proj", "comp", ["fr"], None, 0.0, set()
        )

    assert flagged_count == 1
    [result] = sarif["runs"][0]["results"]
    assert result["ruleId"] == "unknown-check-could-not-parse-open-link"
    assert result["level"] == "note"


def test_write_github_output_appends_key_value_pairs(tmp_path, monkeypatch):
    out_file = tmp_path / "gh_output"
    out_file.write_text("existing=1\n")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))

    wcs._write_github_output(
        {"sarif-file": "weblate-checks.sarif", "flagged-count": "3"}
    )

    content = out_file.read_text()
    assert "existing=1" in content
    assert "sarif-file=weblate-checks.sarif" in content
    assert "flagged-count=3" in content


def test_write_github_output_is_a_noop_without_the_env_var(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    wcs._write_github_output({"a": "b"})  # must not raise


# ---------------------------------------------------------------------------
# main() CLI entrypoint
# ---------------------------------------------------------------------------


def test_main_uses_explicit_languages_and_writes_sarif_output(
    monkeypatch, tmp_path, capsys
):
    output = tmp_path / "out.sarif"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--project",
            "proj",
            "--component",
            "comp",
            "--languages",
            "fr,en",
            "--token",
            "tok123",
            "--output",
            str(output),
        ],
    )
    fake_sarif = {"runs": [{"results": [{"a": 1}, {"b": 2}]}]}
    with (
        patch.object(wcs, "build_sarif", return_value=(fake_sarif, 2)) as mock_build,
        patch.object(wcs, "fetch_component_languages") as mock_discover,
    ):
        rc = wcs.main()

    assert rc == 0
    mock_discover.assert_not_called()
    assert mock_build.call_args.args[3] == ["fr", "en"]
    assert mock_build.call_args.args[4] == "tok123"
    assert json.loads(output.read_text()) == fake_sarif
    captured = capsys.readouterr()
    assert "Using Weblate API token" in captured.err
    assert "Wrote 2 result(s)" in captured.err


def test_main_auto_discovers_languages_when_omitted(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("WEBLATE_API_TOKEN", raising=False)
    output = tmp_path / "out.sarif"
    monkeypatch.setattr(
        "sys.argv",
        [
            "prog",
            "--project",
            "proj",
            "--component",
            "comp",
            "--output",
            str(output),
        ],
    )
    with (
        patch.object(
            wcs, "fetch_component_languages", return_value=["en", "fr"]
        ) as mock_discover,
        patch.object(
            wcs, "build_sarif", return_value=({"runs": [{"results": []}]}, 0)
        ) as mock_build,
    ):
        rc = wcs.main()

    assert rc == 0
    mock_discover.assert_called_once()
    assert mock_build.call_args.args[3] == ["en", "fr"]
    captured = capsys.readouterr()
    assert "No Weblate API token set" in captured.err
    assert "Discovered 2 language(s): en, fr" in captured.err


def test_main_returns_1_on_tool_error(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--project", "p", "--component", "c", "--languages", "fr"],
    )
    with patch.object(wcs, "build_sarif", side_effect=wcs.ToolError("boom")):
        rc = wcs.main()

    assert rc == 1
    assert "Error: boom" in capsys.readouterr().err


def test_main_returns_130_on_keyboard_interrupt(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--project", "p", "--component", "c", "--languages", "fr"],
    )
    with patch.object(wcs, "build_sarif", side_effect=KeyboardInterrupt()):
        rc = wcs.main()

    assert rc == 130
    assert "Interrupted" in capsys.readouterr().err
