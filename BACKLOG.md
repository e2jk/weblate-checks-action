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

- **Enable "Allow auto-merge"** (Settings → General) — required for
  `dependabot-automerge.yml`'s `gh pr merge --auto` to actually take effect;
  without it the command succeeds but auto-merge never triggers.
- **Branch protection on `main`** requiring the `lint-and-test` check, if/when
  this repo gets outside contributors — not urgent for a single-maintainer
  repo but worth doing before accepting external PRs.
