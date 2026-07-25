# AGENTS.md — weblate-checks-action Agent Briefing

This file is for AI coding agents (Claude Code, Codex, Cursor, etc.). Read it
in full before making any change. It is the authoritative source on how to
work in this repository.

## What this is

A GitHub Action (composite action, no Docker/JS runtime) that fetches strings
flagged by Weblate's translation quality checks and converts them into a
SARIF file for GitHub Code Scanning. The entire implementation is a single
stdlib-only Python script:

- `action.yml` — the Action manifest (inputs/outputs, sets up Python 3.12,
  invokes the script with args built from `inputs.*`).
- `weblate_checks_to_sarif.py` — all the logic, single file, no third-party
  runtime dependencies (stdlib only — dev/lint/test tooling is separate, see
  `requirements-dev.txt`).
- `tests/test_weblate_checks_to_sarif.py` — mocks all network calls; no live
  Weblate instance is contacted.

This repo was split out of [OpenHangar](https://github.com/e2jk/OpenHangar),
which remains the real-world consumer (see its
`.github/workflows/weblate-i18n-scan.yml`). It has not yet been published to
the GitHub Marketplace (see `BACKLOG.md` for that and other pending
one-time/deferred items — check it for outstanding work before assuming a
task is novel).

**Working with the human:** implement, fix, test, and document — but you are
not expected to push code, run destructive git commands, or commit. Propose
a commit message (Conventional Commits format, see "Conventions" below) and
let the human run the commit themselves, even if a change is otherwise
complete and verified.

## Commands

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

.venv/bin/ruff check .                                     # lint
.venv/bin/ruff format --check .                             # formatting (drop --check to fix)
.venv/bin/mypy weblate_checks_to_sarif.py                   # type-check (strict mode)
.venv/bin/bandit -c pyproject.toml -r weblate_checks_to_sarif.py -ll -i  # security scan
.venv/bin/zizmor -q --persona=pedantic --offline .github/ action.yml     # workflow/action.yml lint
.venv/bin/pip-audit -r requirements-dev.txt                 # dependency audit

.venv/bin/python -m pytest tests/ --cov=. --cov-report=term-missing -q   # full suite w/ coverage
.venv/bin/python -m pytest tests/test_weblate_checks_to_sarif.py::test_slugify -q  # single test

# actionlint requires a separate binary download, see .github/workflows/ci.yml
```

CI (`.github/workflows/ci.yml`) runs all of the above on every push/PR — treat
that job as the authoritative check list; run the same commands locally
before considering a change done.

A `.githooks/pre-push` hook runs the same checks (lint, type-check, security
scan, workflow lint, dependency audit, tests) automatically before every
`git push`. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

Sync locally installed tool versions to what `requirements-dev.txt`/`ci.yml`
pin (no network calls otherwise) with `bash .githooks/pre-push --update`.

Run the script itself locally:

```bash
python3 weblate_checks_to_sarif.py --project P --component C --output /tmp/out.sarif
```

`--help` mirrors the action's inputs one-for-one.

## Architecture / data flow

The core problem this tool solves: Weblate's REST API only exposes a boolean
`has_failing_check` per string — it never says *which* check fired or why.
That detail is only rendered in HTML on the string's own public "translate"
page. So the script combines an API-driven crawl with HTML scraping:

1. **Language discovery** (`fetch_component_languages`) — if `--languages` is
   omitted, queries Weblate's translations list for the component to get
   every configured language, *including the source language* (Weblate runs
   checks against it too, e.g. two distinct source strings sharing a
   translation elsewhere trips "Reused translation" on the source unit
   itself).
2. **Flagged-unit query** (`fetch_flagged_units`) — one paginated REST API
   call per language: `has:check AND state:>=translated`.
3. **Check scraping** (`scrape_checks` + `CHECK_ITEM_RE`) — for each flagged
   unit, fetches its public `web_url` translate page (not the API — doesn't
   count against API quota) and regex-parses the "Things to check"
   `list-group-item` blocks for check name + description. A failed/unparsable
   fetch degrades to an empty list, not an exception — the caller then emits
   a placeholder "Unknown check" result rather than dropping the string.
4. **SARIF assembly** (`build_sarif` / `_sarif_result`) — one SARIF result per
   (unit, check, location) tuple; `unit["location"]` (comma-separated
   `file:line` entries) is parsed by `_parse_locations` into SARIF
   `physicalLocation`s, omitted entirely if empty rather than fabricated.
   Rule IDs are slugified check names (`_slugify`); rule metadata is
   deduplicated into a `rules` dict keyed by slug as results accumulate.

**Severity mapping is deliberate and load-bearing**: checks in
`DEFAULT_WARNING_CHECKS` (format-placeholder/markup checks — mean the
translation is malformed and will misrender or crash at runtime) map to SARIF
`warning`; everything else (e.g. "Reused translation", "Unchanged
translation" — content-quality hints, not render-time breakage) maps to
`note`, the lowest SARIF level. This is intentional so Weblate findings never
outrank real security findings (CodeQL, Bandit, ...) in the same Code
Scanning list. `security-severity` is never set, for the same reason. Keep
this hierarchy in mind before changing what counts as "warning" — it's a
policy decision, not an oversight, and is user-overridable via
`--warning-checks`.

**Error handling contract**: `ToolError` (and subclasses `WeblateApiError`,
`RateLimitExceeded`) represent known, actionable failure modes (bad token,
rate limit, network error) and are caught in `main()` to print a clean
message and exit 1. A run that successfully completes and finds flagged
strings still exits 0 — those are informational findings, not a build
failure. Don't let a transport-level scrape failure (`scrape_checks`) bubble
up as a `ToolError`; it's expected to degrade gracefully per-unit instead.

**`_fetch` is the sole network chokepoint** — both the Weblate API and the
scraped translate pages go through it. It validates the URL scheme is
http(s) before every request (defense against a malicious/misconfigured
`--weblate-url` or an API-echoed `web_url` reaching `file://`), and handles
429 (rate limit, no point retrying same-run), 401/403 (bad/missing token),
and 503 (single retry after a short sleep) distinctly.

## Conventions

- Strict mypy (`pyproject.toml`: `strict = true`) — new code must be fully
  typed.
- Ruff for both lint and formatting; run `ruff format` (no `--check`) to
  auto-fix before `ruff check`.
- Composite action, not JS/Docker — any new logic goes in the Python script,
  not inline `run:` shell beyond the existing arg-building in `action.yml`.
- Third-party Actions in workflows are pinned to a full commit SHA with a
  trailing `# vX.Y.Z` comment (see `action.yml` and `.github/workflows/*`) —
  match that pattern for any new `uses:` step.
- Commit messages follow Conventional Commits (`type(scope): description`,
  e.g. `fix(i18n): ...`, `feat(ci): ...`, `chore(deps): ...`,
  `docs(readme): ...`) — same convention as OpenHangar, this repo's parent
  project.

## Releasing new versions

Unlike a package published via `pip`/`npm`, a GitHub Action is versioned
purely by git tags — pushing to `main` alone never creates a release or
moves a tag, so `@v1`/`@vX.Y.Z` consumers see no change until a maintainer
does the steps below. Skip all of this for changes that don't affect a
consumer's observable behavior (docs, tests, CI config, this file) — only
cut a release when `action.yml` or `weblate_checks_to_sarif.py` actually
changed what a consumer would see.

1. Pick the version bump per [semver](https://semver.org), based on what
   actually changed:
   - **patch** (`vX.Y.Z+1`) — bug fix, no input/output/behavior change.
   - **minor** (`vX.Y+1.0`) — new input/output or new backward-compatible
     behavior.
   - **major** (`vX+1.0.0`) — breaking change: removed/renamed input,
     changed default behavior, dropped Python version support, etc.
2. Tag the released commit on `main` and push the tag:
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```
3. Move the floating major-version tag (`v1`, `v2`, ...) — the one
   `uses: e2jk/weblate-checks-action@v1`-style consumers actually pin to —
   so they pick up the new patch/minor automatically, same convention as
   `actions/checkout`, `actions/setup-python`, etc.:
   ```bash
   git tag -f v1 vX.Y.Z
   git push origin v1 --force
   ```
   Skip this step on a **major** bump — a new major version gets its own new
   floating tag (`v2`) instead of moving `v1`, so existing `@v1` consumers
   are unaffected until they explicitly opt in.
4. Create a GitHub Release from the `vX.Y.Z` tag (UI, or
   `gh release create vX.Y.Z --generate-notes`). Once this repo has been
   published to the Marketplace (see `BACKLOG.md` for the one-time
   first-publish steps), this is also what pushes the update to the
   Marketplace listing.

Force-pushing a moved tag is a rewrite of published history that every
`@v1` consumer immediately picks up — per "Working with the human" above,
propose these steps rather than running them unprompted.
