# Backlog

Live "still to do" list for this repository — remove items once implemented,
don't leave completed work here.

## One-time repo settings (not automatable)

- **Delete the classic branch protection rule on `main`** (superseded
  2026-07-25 by a repository ruleset — see `CONTRIBUTING.md` § Landing
  changes on main) and **delete the now-unneeded `SCORECARD_TOKEN` repo
  secret**, then revoke the corresponding fine-grained PAT at
  <https://github.com/settings/personal-access-tokens>. Classic branch
  protection is unreadable by the default `GITHUB_TOKEN` (which is why
  OpenSSF Scorecard's `Branch-Protection` check errored instead of scoring
  once it was enabled); a ruleset gives the same enforcement and the
  default token can read it fine, so the PAT/secret are no longer needed.
  Both actions require repo-admin access this session's sandboxing doesn't
  allow it to use — deletions of live GitHub settings are blocked by the
  auto-mode safety classifier.
- **Register for an OpenSSF Best Practices badge** (optional, fixes the
  `CII-Best-Practices` Scorecard check, currently 0/10) at
  <https://www.bestpractices.dev/en/projects/new> — a one-time
  questionnaire tied to a personal/org account, not something to automate.
