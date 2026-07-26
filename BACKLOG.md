# Backlog

Live "still to do" list for this repository — remove items once implemented,
don't leave completed work here.

## Publish to GitHub Marketplace

Deliberately deferred at the time this repo was split out of OpenHangar
(2026-07-25): the plan is to use this action for real for a while first
(starting with OpenHangar's own `weblate-i18n-scan.yml`), then publish once
comfortable with the public listing step.

To publish: cut a GitHub Release from a `vX.Y.Z` tag, tick "Publish this
Action to the GitHub Marketplace" in the release UI, pick up to 2 categories,
and accept the Marketplace Developer Agreement (one-time, for the account's
first published action). Requirements are already met: public repo,
`action.yml` at the repo root, and a `branding` block (`check-circle` /
`blue`).

## One-time repo settings (not automatable)

- **Create the `SCORECARD_TOKEN` secret** — since branch protection on
  `main` was enabled (2026-07-25), the OpenSSF Scorecard workflow's default
  `GITHUB_TOKEN` can no longer read it (a documented Scorecard/GitHub API
  limitation, not a bug here), so the `Branch-Protection` check now errors
  instead of scoring. Fix: create a fine-grained PAT at
  <https://github.com/settings/personal-access-tokens/new> scoped to just
  this repo, with `Administration: Read-only` permission (`Metadata:
  Read-only` gets added automatically), then add it as a repo secret named
  `SCORECARD_TOKEN`
  (`https://github.com/e2jk/weblate-checks-action/settings/secrets/actions/new`).
  `.github/workflows/scorecard.yml` already reads it (falls back to
  `GITHUB_TOKEN` — every check except `Branch-Protection` works without
  this). Full instructions:
  <https://github.com/ossf/scorecard-action/blob/main/docs/authentication/fine-grained-auth-token.md>.
- **Register for an OpenSSF Best Practices badge** (optional, fixes the
  `CII-Best-Practices` Scorecard check, currently 0/10) at
  <https://www.bestpractices.dev/en/projects/new> — a one-time
  questionnaire tied to a personal/org account, not something to automate.
