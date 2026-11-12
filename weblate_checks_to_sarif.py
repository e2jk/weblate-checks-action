#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
"""
Fetch strings flagged by Weblate quality checks and convert them to SARIF 2.1.0.

Weblate's public REST API only exposes a boolean `has_failing_check` per string —
it does not say *which* check(s) fired. Its search syntax can filter by check,
though ("check:reused"), so this tool:

  1. If --languages is omitted, auto-discovers every language configured for
     the component (via Weblate's own translations list) — otherwise uses the
     given comma-separated list as-is.
  2. Queries the Weblate API for translated strings with a failing check, once
     per language.
  3. Finds which check(s) fired on each by searching the same strings per check
     name (CHECKS) — warning-level ones first, then the most common — stopping
     once every flagged string is accounted for — or through every check with --all-checks. (It used to
     scrape each string's public translate page instead, but Weblate now
     guards those with a proof-of-work bot challenge: HTTP 403 "pow_required".)
  4. Emits one SARIF result per (string, check, source location) so GitHub Code
     Scanning can link every occurrence back to the file/line it came from,
     each rule linking to its check's section of Weblate's documentation.
     Code Scanning rejects the whole upload if any result has no location, so
     a string Weblate has no source location for (e.g. a .po entry added by
     hand, without its "#:" reference comment) is attached to the language's
     translation file instead; if Weblate has no file for that language
     either (the source language of a bilingual component), the result is
     left out with a warning annotation rather than given a made-up path.

No Weblate login is required for a public project, but an API token raises the
rate limit from 100 anonymous requests/day to 5000/hour — useful for scheduled
runs. Create one at <weblate-url>/accounts/profile/#api and pass it via
--token or the WEBLATE_API_TOKEN environment variable.

Usage:
    python3 weblate_checks_to_sarif.py --project myproj --component mycomp
    python3 weblate_checks_to_sarif.py --project myproj --component mycomp --languages en,fr,nl
    WEBLATE_API_TOKEN=wlu_xxx python3 weblate_checks_to_sarif.py --project myproj --component mycomp --languages fr

Severity mapping is deliberately conservative: checks that mean a translation
is actually malformed at render time (mismatched line breaks, printf/format
placeholders, XML markup) map to SARIF "warning"; everything else (reused
translation, unchanged translation, etc. — content-quality hints rather than
render-time breakage) maps to "note", the lowest SARIF level. This keeps
Weblate findings from ever outranking real security findings (CodeQL, Bandit,
...) in the same Code Scanning list. Override with --warning-checks.

Exit code is non-zero only on a real execution failure (bad token, rate
limit, network error) — a run that successfully finds flagged strings still
exits 0, since those are informational findings, not a build failure.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Collection
from typing import Any

USER_AGENT = (
    "weblate-checks-action/1.0 (+https://github.com/e2jk/weblate-checks-action)"
)

SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)

TOOL_NAME = "weblate-checks-action"
TOOL_INFO_URI = "https://github.com/e2jk/weblate-checks-action"
WEBLATE_CHECKS_DOCS_URL = "https://docs.weblate.org/en/latest/user/checks.html"

# Defensive bound on API pagination, at 100 results/page (100k records) far
# above any real Weblate component — not a real-world ceiling. Without it, a
# malicious/misconfigured server (or a MITM, since http:// is accepted) that
# never returns a falsy "next" hangs the run forever.
MAX_PAGINATION_PAGES = 1_000

# Checks that mean a translation is malformed at render time, not just a
# content-quality hint — these map to SARIF "warning" instead of "note".
DEFAULT_WARNING_CHECKS = [
    "Mismatching line breaks",
    "Python format",
    "Python brace format",
    "C format",
    "C# format",
    "JavaScript format",
    "Perl format",
    "PHP format",
    "XML markup",
    "XML tags",
    "XML syntax",
]

Unit = dict[str, Any]
Check = tuple[str, str]  # (name, description)

# A flagged string no check search matched — a check newer than CHECKS.
UNKNOWN_CHECK = "Unknown check"
UNKNOWN_CHECK_DESC = (
    "Weblate flags this string with a check this tool doesn't know yet — "
    "open the Edit link to see it."
)

# Weblate's quality checks: (search name, display name) — the name Weblate's
# search syntax filters by ("check:<name>") and the one it shows, from its own
# definitions (weblate/checks/*.py: check_id, name). The display name is what
# rule IDs are made from and what --warning-checks matches. Most common first
# (consistency, format and punctuation checks), so the default search, which
# stops once every flagged string has a check, rarely needs more than a few
# requests per language.
CHECKS: list[tuple[str, str]] = [
    ("reused", "Reused translation"),
    ("multiple_failures", "Multiple failing checks"),
    ("inconsistent", "Inconsistent"),
    ("same", "Unchanged translation"),
    ("same-plurals", "Same plurals"),
    ("translated", "Has been translated"),
    ("plurals", "Missing plurals"),
    ("python_format", "Python format"),
    ("python_brace_format", "Python brace format"),
    ("c_format", "C format"),
    ("percent_placeholders", "Percent placeholders"),
    ("placeholders", "Placeholders"),
    ("unnamed_format", "Multiple unnamed variables"),
    ("end_stop", "Mismatched full stop"),
    ("end_colon", "Mismatched colon"),
    ("end_question", "Mismatched question mark"),
    ("end_exclamation", "Mismatched exclamation mark"),
    ("end_ellipsis", "Mismatched ellipsis"),
    ("end_semicolon", "Mismatched semicolon"),
    ("end_space", "Trailing space"),
    ("begin_space", "Starting spaces"),
    ("double_space", "Double space"),
    ("punctuation_spacing", "Punctuation spacing"),
    ("escaped_newline", "Mismatched \\n"),
    ("newline-count", "Mismatching line breaks"),
    ("end_newline", "Trailing newline"),
    ("begin_newline", "Starting newline"),
    ("duplicate", "Consecutive duplicated words"),
    ("xml-tags", "XML markup"),
    ("xml-invalid", "XML syntax"),
    ("safe-html", "Unsafe HTML"),
    ("url", "URL"),
    ("ai_accuracy", "AI: Accuracy"),
    ("ai_fluency", "AI: Fluency"),
    ("ai_terminology", "AI: Terminology"),
    ("ai_style", "AI: Style"),
    ("ai_formatting", "AI: Formatting"),
    ("angularjs_format", "AngularJS interpolation string"),
    ("accelerator", "Accelerator key"),
    ("kabyle-characters", "Non-standard characters in Kabyle"),
    ("end_interrobang", "Mismatched interrobang"),
    ("zero-width-space", "Zero-width space"),
    ("max-length", "Maximum length of translation"),
    ("max-lines", "Maximum number of lines"),
    ("kashida", "Kashida letter used"),
    ("multiple_capital", "Multiple capitals"),
    ("php_format", "PHP format"),
    ("objc_format", "Objective-C format"),
    ("perl_brace_format", "Perl brace format"),
    ("perl_format", "Perl format"),
    ("javascript_format", "JavaScript format"),
    ("lua_format", "Lua format"),
    ("object_pascal_format", "Object Pascal format"),
    ("scheme_format", "Scheme format"),
    ("c_sharp_format", "C# format"),
    ("laravel_format", "Laravel format"),
    ("java_printf_format", "Java format"),
    ("java_format", "Java MessageFormat"),
    ("i18next_interpolation", "i18next interpolation"),
    ("es_format", "ECMAScript template literals"),
    ("vue_format", "Vue I18n formatting"),
    ("automattic_components_format", "Automattic components formatting"),
    ("check_glossary", "Does not follow glossary"),
    ("prohibited_initial_character", "Prohibited initial character"),
    ("icu_message_format_syntax", "ICU MessageFormat syntax"),
    ("icu_message_format", "ICU MessageFormat"),
    ("bbcode", "BBCode markup"),
    ("xml-chars-around-tags", "Chars around XML tags"),
    ("md-reflink", "Markdown references"),
    ("md-link", "Markdown links"),
    ("md-syntax", "Markdown syntax"),
    ("rst-references", "Inconsistent reStructuredText"),
    ("rst-syntax", "reStructuredText syntax error"),
    ("asciidoc-markup", "AsciiDoc markup"),
    ("safe-mdx", "Safe MDX"),
    ("regex", "Regular expression"),
    ("qt_format", "Qt format"),
    ("qt_plural_format", "Qt plural format"),
    ("max-size", "Maximum size of translation"),
    ("ruby_format", "Ruby format"),
    ("optional_plural", "Unpluralised"),
    ("ellipsis", "Ellipsis"),
    ("source-max-length", "Source string length"),
    ("long_untranslated", "Long untranslated"),
]
SLUG_RE = re.compile(r"[^a-z0-9]+")


class ToolError(RuntimeError):
    """A known failure mode worth a clean, actionable message instead of a
    raw traceback (bad token, rate limit, network error)."""


class WeblateApiError(ToolError):
    """A Weblate API request failed."""


class RateLimitExceeded(WeblateApiError):
    """Weblate returned HTTP 429 — retrying won't help within a single run."""


def _log(msg: str) -> None:
    """Progress feedback on stderr — printed unconditionally since a run
    makes several HTTP requests and can take a while; silence for that long
    reads as a hang."""
    print(msg, file=sys.stderr, flush=True)


def _fetch(url: str, token: str | None) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        # Both --weblate-url and the pagination "next" links (echoed back by
        # the Weblate API) end up here — reject anything but http(s) so a
        # misconfigured or malicious value can't make urlopen() read a local
        # file:// path.
        raise ToolError(f"Refusing to fetch a non-http(s) URL: {url!r}")
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Token {token}"
    req = urllib.request.Request(url, headers=headers)
    weblate_url = f"{parsed.scheme}://{parsed.netloc}"
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310  # scheme validated above
                return resp.read()  # type: ignore[no-any-return]
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Anonymous quota is 100/day, not a short burst window —
                # sleeping a few seconds and retrying is pointless.
                reset_header = (
                    exc.headers.get("X-RateLimit-Reset") if exc.headers else None
                )
                reset_note = ""
                if reset_header and reset_header.isdigit():
                    seconds = int(reset_header)
                    reset_note = (
                        f" Resets in ~{seconds // 3600}h{(seconds % 3600) // 60}m."
                    )
                token_hint = (
                    ""
                    if token
                    else " Set WEBLATE_API_TOKEN (5000 req/hour instead of "
                    "100 req/day anonymous) to avoid this."
                )
                raise RateLimitExceeded(
                    f"Weblate API rate limit hit (HTTP 429).{reset_note}{token_hint}"
                ) from exc
            if exc.code in (401, 403):
                reason = (
                    "token is invalid or lacks access. Check it at "
                    f"{weblate_url}/accounts/profile/#api."
                    if token
                    else "no token is set — the request needs one, or Weblate "
                    "refused it (e.g. a bot challenge)."
                )
                raise WeblateApiError(
                    f"Weblate rejected the request (HTTP {exc.code}) — {reason}"
                ) from exc
            if exc.code == 503 and attempt == 0:
                time.sleep(5)
                continue
            raise
        except urllib.error.URLError as exc:
            raise WeblateApiError(f"Could not reach {weblate_url}: {exc}") from exc
    raise AssertionError("unreachable")  # pragma: no cover


def fetch_component_languages(
    weblate_url: str, project: str, component: str, token: str | None
) -> list[str]:
    """Auto-discover which languages are configured for a component, so
    callers don't have to hardcode or separately maintain a language list.
    Includes the source language: Weblate tracks a translation object for it
    too (checks run against it as well, e.g. "Reused translation" between two
    distinct source strings), even though it has no .po file of its own."""
    path = f"/api/components/{project}/{component}/translations/?page_size=100"
    codes: list[str] = []
    url: str | None = weblate_url + path
    pages = 0
    while url:
        pages += 1
        if pages > MAX_PAGINATION_PAGES:
            raise WeblateApiError(
                f"Exceeded {MAX_PAGINATION_PAGES} pagination pages listing "
                f"translations for {project}/{component} — the server's "
                '"next" link never became empty.'
            )
        try:
            data = json.loads(_fetch(url, token))
            for translation in data["results"]:
                code = (
                    translation.get("language_code") or translation["language"]["code"]
                )
                codes.append(code)
            url = data["next"]
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            KeyError,
            TypeError,
            AttributeError,
            RecursionError,
        ) as exc:
            # A malformed/adversarial response (bad JSON, non-UTF-8 bytes, an
            # unexpected shape, or pathologically deep nesting) from a
            # misconfigured server or a MITM (http:// is accepted) — a
            # known, actionable failure mode, not a raw traceback.
            raise WeblateApiError(
                f"Weblate returned an unexpected response from {url}: {exc}"
            ) from exc
    return codes


def fetch_translation_filename(
    weblate_url: str, project: str, component: str, language: str, token: str | None
) -> str:
    """The repository path of *language*'s translation file, as Weblate knows
    it (e.g. "locale/fr/LC_MESSAGES/messages.po"), or "" when it has none —
    the source language of a bilingual (e.g. gettext) component."""
    url = (
        f"{weblate_url}/api/translations/"
        f"{urllib.parse.quote(project, safe='')}/"
        f"{urllib.parse.quote(component, safe='')}/"
        f"{urllib.parse.quote(language, safe='')}/"
    )
    try:
        filename = json.loads(_fetch(url, token)).get("filename") or ""
        if not isinstance(filename, str):
            raise TypeError(f"filename is {type(filename).__name__}, not str")
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        AttributeError,
        TypeError,
        RecursionError,
    ) as exc:
        raise WeblateApiError(
            f"Weblate returned an unexpected response from {url}: {exc}"
        ) from exc
    return filename


def fetch_flagged_units(
    weblate_url: str, project: str, component: str, language: str, token: str | None
) -> list[Unit]:
    query = (
        f"project:{project} AND component:{component} AND language:{language} "
        "AND has:check AND state:>=translated"
    )
    return _search_units(
        weblate_url,
        query,
        token,
        f"flagged units for {project}/{component} ({language})",
    )


def _search_units(
    weblate_url: str, query: str, token: str | None, what: str
) -> list[Unit]:
    """Every unit matching a Weblate search *query*, following pagination —
    capped at MAX_PAGINATION_PAGES, and a malformed or adversarial response
    turned into a clean WeblateApiError (*what* says what was being listed)."""
    path = "/api/units/?" + urllib.parse.urlencode({"q": query, "page_size": 100})
    units: list[Unit] = []
    url: str | None = weblate_url + path
    pages = 0
    while url:
        pages += 1
        if pages > MAX_PAGINATION_PAGES:
            raise WeblateApiError(
                f"Exceeded {MAX_PAGINATION_PAGES} pagination pages listing "
                f'{what} — the server\'s "next" link never became empty.'
            )
        try:
            data = json.loads(_fetch(url, token))
            units.extend(data["results"])
            url = data["next"]
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            KeyError,
            TypeError,
            RecursionError,
        ) as exc:
            # A malformed/adversarial response (bad JSON, non-UTF-8 bytes, an
            # unexpected shape, or pathologically deep nesting) shouldn't
            # crash with a raw traceback.
            raise WeblateApiError(
                f"Weblate returned an unexpected response from {url}: {exc}"
            ) from exc
    return units


def fetch_unit_checks(
    weblate_url: str,
    project: str,
    component: str,
    language: str,
    units: list[Unit],
    token: str | None,
    delay: float = 0.0,
    all_checks: bool = False,
    warning_checks: Collection[str] = (),
) -> dict[Any, list[str]]:
    """{unit id: [check display names]} for the flagged *units*, found by
    searching them per check name (CHECKS). Stops once every unit has at
    least one check — unless *all_checks*, which searches every check (one
    request per check: best with an API token). A unit no search matched (a
    check this tool doesn't know yet) gets none — the caller reports it as
    "Unknown check".

    Without *all_checks*, a unit failing several checks shows under just
    one, so *warning_checks* (display names) are searched first: otherwise a
    string failing both a note-level check ("Reused translation") and a
    warning-level one ("Python format") would be filed under the more common
    note only. One grouped search ("check:a OR check:b …") finds the units
    failing any of them — usually none, so it costs a single request — and
    only if some do are those checks searched one by one."""
    found: dict[Any, list[str]] = {unit["id"]: [] for unit in units}
    if not found:
        return found  # nothing flagged: no search needed, even --all-checks

    def search(check_filter: str, what: str) -> set[Any]:
        """IDs of our units matching *check_filter*."""
        query = (
            f"project:{project} AND component:{component} AND language:{language} "
            f"AND {check_filter} AND state:>=translated"
        )
        matches = _search_units(
            weblate_url,
            query,
            token,
            f"{what} units for {project}/{component} ({language})",
        )
        time.sleep(delay)
        ids = set()
        for unit in matches:
            # Only a plain ID can be one of ours: a malformed response's
            # (a list, an object…) isn't even hashable.
            unit_id = unit.get("id") if isinstance(unit, dict) else None
            if isinstance(unit_id, (int, str)) and unit_id in found:
                ids.add(unit_id)
        return ids

    remaining = set(found)
    searched: set[str] = set()
    warning_ids = [cid for cid, name in CHECKS if name in warning_checks]
    if warning_ids and not all_checks:
        group = "(" + " OR ".join(f"check:{cid}" for cid in warning_ids) + ")"
        pending = search(group, "warning-level check")
        searched.update(warning_ids)  # a unit failing one is now in pending
        for check_id, name in CHECKS:
            if not pending:
                break
            if check_id in warning_ids:
                matched = search(f"check:{check_id}", check_id)
                for unit_id in matched:
                    found[unit_id].append(name)
                pending -= matched
                remaining -= matched
    for check_id, name in CHECKS:
        if not remaining and not all_checks:
            break
        if check_id in searched:
            continue
        matched = search(f"check:{check_id}", check_id)
        for unit_id in matched:
            found[unit_id].append(name)
        remaining -= matched
    return found


def check_docs_url(name: str) -> str:
    """Weblate's documentation for the check displayed as *name* — its own
    section when it's one of CHECKS, else the checks page."""
    for check_id, check_name in CHECKS:
        if check_name == name:
            return f"{WEBLATE_CHECKS_DOCS_URL}#check-{check_id.replace('_', '-')}"
    return WEBLATE_CHECKS_DOCS_URL


def _slugify(name: str) -> str:
    slug = SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "unknown-check"


def _escape_command_data(text: str) -> str:
    """Escape *text* for the message part of a GitHub workflow command
    (``::warning::<message>``). Unescaped, a newline in it — e.g. from a
    multi-line source string — would end the command early and leave the
    rest on its own line, where the runner would read a leading "::" as a
    new workflow command."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _parse_locations(location_field: str) -> list[tuple[str, int | None]]:
    """Weblate's `location` field is a comma-separated "file:line" list (or
    empty). Returns [] if nothing usable was found — the caller then falls
    back to the translation file rather than a fabricated location."""
    if not location_field:
        return []
    locations: list[tuple[str, int | None]] = []
    for token in location_field.split(","):
        token = token.strip()
        if not token:
            continue
        uri, sep, line_str = token.rpartition(":")
        # isdecimal(), not isdigit(): isdigit() accepts Unicode digit
        # variants like '³' (superscript three) that int() can't actually
        # parse, raising ValueError instead of falling back gracefully —
        # isdecimal() is the strict "int() will accept this" check.
        if uri and sep and line_str.isdecimal():
            locations.append((uri, int(line_str)))
        else:
            locations.append((token, None))
    return locations


def _sarif_result(
    lang: str,
    unit: Unit,
    check_name: str,
    check_desc: str,
    level: str,
    fallback_uri: str = "",
) -> dict[str, Any]:
    """One SARIF result for *unit* failing *check_name*. Located at the
    unit's own source location(s); when Weblate has none, at *fallback_uri*
    (the language's translation file) instead — and with neither, the result
    has no "locations", which the caller must not upload as-is."""
    source = " / ".join(unit["source"])
    target = " / ".join(unit["target"])
    text = f'[{lang}] Source: "{source}"\nTarget: "{target}"'
    if check_desc:
        text += f"\n{check_desc}"
    parsed = _parse_locations(unit.get("location", ""))
    if not parsed and fallback_uri:
        text += (
            "\nWeblate has no source location for this string, so it is shown "
            "on the translation file."
        )
        parsed = [(fallback_uri, None)]
    text += f"\nEdit: {unit['web_url']}"

    result: dict[str, Any] = {
        "ruleId": _slugify(check_name),
        "level": level,
        "message": {"text": text},
    }

    locations = [
        {
            "physicalLocation": {
                "artifactLocation": {"uri": uri, "uriBaseId": "%SRCROOT%"},
                **({"region": {"startLine": line}} if line else {}),
            }
        }
        for uri, line in parsed
    ]
    if locations:
        result["locations"] = locations
    return result


def build_sarif(
    weblate_url: str,
    project: str,
    component: str,
    languages: list[str],
    token: str | None,
    delay: float,
    warning_checks: set[str],
    verbose: bool = False,
    all_checks: bool = False,
) -> tuple[dict[str, Any], int]:
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    flagged_unit_ids: set[int] = set()

    for lang in languages:
        _log(f"[{lang}] querying Weblate for flagged strings...")
        units = fetch_flagged_units(weblate_url, project, component, lang, token)
        plural = "" if len(units) == 1 else "s"
        _log(f"[{lang}] {len(units)} flagged string{plural} — finding their checks...")
        unit_checks = fetch_unit_checks(
            weblate_url,
            project,
            component,
            lang,
            units,
            token,
            delay,
            all_checks=all_checks,
            warning_checks=warning_checks,
        )

        # Fetched at most once per language, and only if a unit needs it.
        fallback_uri: str | None = None

        for i, unit in enumerate(units, start=1):
            checks: list[Check] = [
                (name, "") for name in unit_checks.get(unit["id"], [])
            ] or [(UNKNOWN_CHECK, UNKNOWN_CHECK_DESC)]
            if verbose:
                source_preview = " / ".join(unit["source"])[:60]
                check_names = ", ".join(name for name, _desc in checks)
                _log(f"[{lang}] {i}/{len(units)}: {source_preview!r} — {check_names}")

            flagged_unit_ids.add(unit["id"])
            if fallback_uri is None and not _parse_locations(unit.get("location", "")):
                fallback_uri = fetch_translation_filename(
                    weblate_url, project, component, lang, token
                )
            for name, desc in checks:
                slug = _slugify(name)
                if slug not in rules:
                    rules[slug] = {
                        "id": slug,
                        "name": re.sub(r"[^A-Za-z0-9]", "", name.title())
                        or "UnknownCheck",
                        "shortDescription": {"text": name},
                        "helpUri": check_docs_url(name),
                        "properties": {"tags": ["i18n", "translation"]},
                    }
                level = "warning" if name in warning_checks else "note"
                result = _sarif_result(
                    lang, unit, name, desc, level, fallback_uri or ""
                )
                if "locations" not in result:
                    # GitHub Code Scanning rejects the whole upload over a
                    # single result without a location, so leave this one
                    # out — loudly, as a workflow annotation, not silently.
                    print(
                        "::warning title=Weblate finding not uploaded::"
                        + _escape_command_data(
                            f"[{lang}] "
                            f'"{" / ".join(unit["source"])[:60]}" fails "{name}", '
                            "but Weblate has no source location or translation "
                            f"file for it to point at. See {unit['web_url']}"
                        )
                    )
                    continue
                results.append(result)

    sarif = {
        "version": "2.1.0",
        "$schema": SARIF_SCHEMA,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "informationUri": TOOL_INFO_URI,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return sarif, len(flagged_unit_ids)


def _write_github_output(pairs: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.writelines(f"{key}={value}\n" for key, value in pairs.items())


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--weblate-url",
        default="https://hosted.weblate.org",
        help="Base URL of the Weblate instance (default: %(default)s)",
    )
    parser.add_argument("--project", required=True, help="Weblate project slug")
    parser.add_argument("--component", required=True, help="Weblate component slug")
    parser.add_argument(
        "--languages",
        default=None,
        help="Comma-separated language codes to check, e.g. 'en,fr,nl' "
        "(include the source language too — Weblate flags checks against "
        "it as well). If omitted, auto-discovers every language configured "
        "for the component from Weblate itself.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("WEBLATE_API_TOKEN"),
        help="Weblate API token (default: $WEBLATE_API_TOKEN)",
    )
    parser.add_argument(
        "--output",
        default="weblate-checks.sarif",
        help="Path to write the SARIF file to (default: %(default)s)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="Seconds to sleep between Weblate check searches (default: %(default)s)",
    )
    parser.add_argument(
        "--all-checks",
        action="store_true",
        help="Search every Weblate check, not just until each flagged string has "
        "one — finds all the checks a string fails, at one API request per "
        "check and language (best with an API token)",
    )
    parser.add_argument(
        "--warning-checks",
        default=",".join(DEFAULT_WARNING_CHECKS),
        help="Comma-separated Weblate check names that map to SARIF 'warning' "
        "instead of 'note' (default: format/markup checks that mean a "
        "translation is malformed at render time)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also log each string's source text and detected check name(s) as they're fetched",
    )
    args = parser.parse_args()

    warning_checks = {c.strip() for c in args.warning_checks.split(",") if c.strip()}

    if args.token:
        _log("Using Weblate API token (rate limit: 5000 requests/hour).")
    else:
        _log(
            "No Weblate API token set — using anonymous access (rate limit: "
            "100 requests/day). Set --token or $WEBLATE_API_TOKEN for frequent runs."
        )

    try:
        if args.languages:
            languages = [
                lang.strip() for lang in args.languages.split(",") if lang.strip()
            ]
        else:
            _log(
                "No --languages given — auto-discovering configured languages "
                "from Weblate..."
            )
            languages = fetch_component_languages(
                args.weblate_url, args.project, args.component, args.token
            )
            _log(f"Discovered {len(languages)} language(s): {', '.join(languages)}")

        sarif, flagged_count = build_sarif(
            args.weblate_url,
            args.project,
            args.component,
            languages,
            args.token,
            args.delay,
            warning_checks,
            verbose=args.verbose,
            all_checks=args.all_checks,
        )
    except ToolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted — no SARIF file written.", file=sys.stderr)
        return 130

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(sarif, fh, indent=2)

    result_count = len(sarif["runs"][0]["results"])
    _log(
        f"Wrote {result_count} result(s) across {flagged_count} flagged string(s) "
        f"to {args.output}"
    )
    _write_github_output(
        {"sarif-file": args.output, "flagged-count": str(flagged_count)}
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
