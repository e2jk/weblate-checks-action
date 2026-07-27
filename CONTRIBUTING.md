# Contributing

## Bugs and feature requests

Open an issue. For security vulnerabilities, follow [SECURITY.md](SECURITY.md).

## Development setup

The shipped script (`weblate_checks_to_sarif.py`) itself has no dependencies
beyond the Python standard library — but working on this repo (linting,
type-checking, security scanning, running tests) uses a handful of dev-only
tools, kept separate in `requirements-dev.txt`. That file is hash-pinned
(including transitive dependencies, via `pip-compile --generate-hashes` —
see the comment at its top to regenerate it) so `pip install --require-hashes`
verifies every package against a known-good hash — this is what satisfies
OpenSSF Scorecard's `Pinned-Dependencies` check; Dependabot bumps versions
and hashes in place, no separate `.in` source file to keep in sync:

```bash
python -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.txt

.venv/bin/ruff check .                                      # lint
.venv/bin/ruff format .                                      # auto-format
.venv/bin/mypy weblate_checks_to_sarif.py                    # type-check (strict mode)
.venv/bin/bandit -c pyproject.toml -r weblate_checks_to_sarif.py -ll -i  # security scan
.venv/bin/zizmor -q --persona=pedantic --offline .github/ action.yml     # workflow/action.yml lint
.venv/bin/pip-audit -r requirements-dev.txt                  # dependency audit

.venv/bin/python -m pytest tests/ --cov=. --cov-report=term-missing -q   # tests, with coverage
.venv/bin/python -m pytest tests/test_weblate_checks_to_sarif.py::test_slugify -q  # single test
```

`actionlint` requires a separate binary download — see
`.github/workflows/ci.yml`. Tests mock all network calls — no live Weblate
instance is contacted.

### Testing policy

New or changed functionality must come with tests that cover it — this
project enforces 100% statement coverage
(`pytest --cov-fail-under=100`) in both CI (`ci.yml`) and the pre-push
hook; a change that drops coverage below 100% fails both. Coverage isn't a
substitute for reviewing test quality — a change still needs tests that
actually exercise the new/changed behavior, not just execute the lines.

### Fuzzing

`fuzz/` has [Atheris](https://github.com/google/atheris) harnesses for the
functions that handle data from an external/untrusted source (HTML scraped
from Weblate, the `location` field from its API, a `--weblate-url`/`web_url`
that could point anywhere, the JSON body of API responses): `scrape_checks`'s
HTML parsing, `_parse_locations`, `_slugify`, `_fetch`'s URL-scheme
validation, and `fetch_component_languages`'s/`fetch_flagged_units`'s
handling of the Weblate API's JSON response (network calls are stubbed out
in the last three harnesses — they only exercise the scheme guard / the
response-parsing path, never make a real request). Same technique as
OpenHangar's `fuzz/`, adapted to this repo's single-module layout.

Atheris is Linux-only (no macOS/Windows wheels), so it's kept out of
`requirements-dev.txt` in a separate hash-pinned `requirements-fuzz.txt`:

```bash
.venv/bin/pip install --require-hashes -r requirements-fuzz.txt

.venv/bin/python fuzz/fuzz_slugify.py fuzz/corpus/fuzz_slugify -max_total_time=10
```

`.github/workflows/fuzzing.yml` runs all harnesses after every merge to
`main` (a light ~2min budget) plus a deeper ~20min weekly run, with the
corpus cached across runs. It's deliberately independent of `ci.yml` —
not a required status check, triggered by push to `main` rather than on the
PR itself, so a fuzz finding can never mechanically block a merge or
release. A crash surfaces as a job summary (traceback) and a SARIF upload
to the Security tab; every finding still needs human triage to confirm it's
a real, reachable bug before acting on it.

CI (`.github/workflows/ci.yml`) runs all of the above on every push/PR —
treat that job as the authoritative check list; run the same commands
locally before considering a change done.

### Pre-push hook

A `.githooks/pre-push` hook runs the same checks (lint, type-check, security
scan, workflow lint, dependency audit, tests) automatically before every
`git push`. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

Sync locally installed tool versions to what `requirements-dev.txt`/`ci.yml`
pin (no network calls otherwise) with `bash .githooks/pre-push --update`.

## Landing changes on main

`main` is protected by a repository ruleset (not classic branch
protection — the default `GITHUB_TOKEN` can't read classic protection
settings, which broke OpenSSF Scorecard's own `Branch-Protection` check the
first time this repo tried that route; a ruleset avoids the problem and is
what OpenHangar, this repo's parent project, already uses): no direct
pushes, not even for the repo owner (`bypass_actors: []`), rebase-only
merges (`allowed_merge_methods: ["rebase"]`, so no merge commits ever land),
and the `Lint, type-check, and test` status check must pass on an
up-to-date branch before anything merges. There are two ways a change
reaches `main`, and they're deliberately asymmetric:

- **The repo owner's own commits**: `scripts/ship.sh` rebases the current
  branch onto `origin/main` and force-pushes it to a `ship` branch.
  `.github/workflows/auto-pr-merge.yml` reacts to that push by opening (or
  reusing) a PR from `ship` into `main` and enabling GitHub auto-merge with
  `--rebase`; it lands on its own once the status check passes, with **no
  human approval** — by design, since the author already reviewed it by
  writing it. Requires the `PAT_AUTO_PR_MERGE` repo secret (a fine-grained
  PAT scoped to this repo, `Contents: read/write` + `Pull requests:
  read/write`) — the default `GITHUB_TOKEN` can't be used because a PR it
  opens would need manual workflow-run approval before its own triggered
  CI run, defeating the point.
- **External contributors**: fork the repo, branch, and open a PR straight
  into `main` the normal GitHub way (see "Pull requests" below) — `ship.sh`
  and `auto-pr-merge.yml` have no part in this path; `ci.yml`'s existing
  `pull_request:` trigger already covers it. These get an actual human
  review; merge with "Rebase and merge" once satisfied, rather than turning
  on auto-merge.

This asymmetry is intentional and known to keep Scorecard's `Code-Review`
check at 0 for solo commits (same as OpenHangar) — full auto-merge on your
own PRs and required reviews are mutually exclusive, and solo review is a
theater, not a safeguard.

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
2. Ship it and wait for the PR to actually merge (watch it land, e.g. `gh pr
   checks` / `gh pr view --json state`, or just check on GitHub) — **only
   after** it's landed on `origin/main`, run `scripts/release.sh`, one step
   at a time:
   ```bash
   scripts/release.sh vX.Y.Z               # dry run: prints origin/main's tip, no changes
   scripts/release.sh vX.Y.Z --tag         # tags *that* SHA and pushes it
   scripts/release.sh vX.Y.Z --move-major  # moves (or creates) the floating vX tag
   scripts/release.sh vX.Y.Z --publish     # gh release create vX.Y.Z --generate-notes
   ```
   Each step re-fetches and re-derives `origin/main`'s tip itself rather
   than trusting local state — landing here always goes through
   `scripts/ship.sh` -> a PR -> a rebase-merge (see "Landing changes on
   main" above), and a rebase-merge *rewrites every commit it merges* (new
   parent, so a new SHA) — the SHA you have locally right after `git
   commit`, or even right after `scripts/ship.sh` pushes to `ship`, is
   **not** the SHA that ends up on `main`. Tagging too early tags a commit
   that's about to become unreachable once the ship branch is deleted
   post-merge; the script sidesteps this entirely by always reading
   `origin/main` fresh, never local `HEAD`.

   `--move-major` moves the floating major-version tag (`v1`, `v2`, ...) —
   the one `uses: e2jk/weblate-checks-action@v1`-style consumers actually
   pin to — so they pick up the new patch/minor automatically, same
   convention as `actions/checkout`, `actions/setup-python`, etc. On a
   **major** bump there's no existing `vX` tag yet, so the script creates it
   fresh instead of force-moving anything — existing `@v1` consumers stay
   put until they explicitly opt in to `@v2`.

   There's no `--all`: run the steps in order, reading the output between
   them. `--move-major` in particular force-pushes a tag every `@v1`-style
   consumer immediately picks up on their next run — deliberately not
   bundled into anything automatic; this remains repo-owner-only territory
   (see `scripts/ship.sh` above), a script to remove typos, not a reason to
   stop paying attention.

Publishing the release (`--publish`, or the GitHub UI) automatically
triggers `.github/workflows/release-sign.yml`, which generates an SBOM,
signs it with `cosign` (keyless — no key material to manage; see the
workflow's own comments), attests SLSA provenance, and attaches all three as
release assets. Nothing further to do — this is what satisfies OpenSSF
Scorecard's `Signed-Releases` check. To backfill signing on a release that
predates this workflow (or to re-run it), trigger it manually:
`gh workflow run "Sign release artifacts" -f tag=vX.Y.Z`.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Read [`AGENTS.md`](AGENTS.md) for the architecture and code conventions
   this repo follows.
3. Set up your environment and run the checks above (or rely on the
   pre-push hook).
4. Open a PR against `main` with a clear description of what and why.

Commit messages follow [Conventional
Commits](https://www.conventionalcommits.org/) (`type(scope): description`,
e.g. `fix(sarif): ...`, `feat(cli): ...`, `chore(deps): ...`).
