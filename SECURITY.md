# Security Policy

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report vulnerabilities privately using GitHub's built-in security advisory feature:

**[Report a vulnerability](https://github.com/e2jk/weblate-checks-action/security/advisories/new)**

Alternatively, reach the maintainer by email at wick-geology-woven@duck.com.

## What to Include

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Affected versions (if known)
- Any suggested mitigations

## Disclosure Policy

- We will acknowledge receipt within **5 business days**.
- We aim to release a fix within **90 days** of the initial report.
- We will coordinate public disclosure with the reporter and publish a GitHub Security Advisory once a fix is available.
- If a fix cannot be delivered within 90 days, we will notify the reporter and agree on an extended timeline.

## Scope

This project is a single Python script (`weblate_checks_to_sarif.py`) that
runs as a step in consumers' GitHub Actions workflows. In scope:

- Anything that lets a malicious/misconfigured `--weblate-url`, or a
  `web_url` echoed back by the Weblate API, be fetched outside http(s) or
  reach an unintended host (see `_fetch`'s scheme validation) —
  SSRF-adjacent issues.
- Handling of the Weblate API token (`--token` / `WEBLATE_API_TOKEN`) —
  leakage into logs, the generated SARIF file, or Action outputs.
- Issues in the HTML scraping (`scrape_checks`, `CHECK_ITEM_RE`) or SARIF
  assembly that could corrupt or exploit a downstream SARIF consumer (e.g.
  GitHub Code Scanning).
- Supply-chain issues in this repo's own GitHub Actions workflows
  (`.github/workflows/`, `action.yml`).

Out of scope:

- Vulnerabilities in Weblate itself — report those to the
  [Weblate project](https://github.com/WeblateOrg/weblate/security).
- Vulnerabilities arising purely from a consumer's own workflow
  configuration (e.g. an overly permissive `GITHUB_TOKEN` on their side).
