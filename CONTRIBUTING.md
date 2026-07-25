# Contributing

## Bugs and feature requests

Open an issue.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Read [`AGENTS.md`](AGENTS.md) for the architecture and conventions this
   repo follows.
3. Set up your environment and run the checks: see
   [README.md § Development](README.md#development).
4. Install the pre-push hook (`git config core.hooksPath .githooks`) so
   lint, type-check, security scan, workflow lint, dependency audit, and
   tests all run automatically before you push — the same checks CI runs.
5. Open a PR against `main` with a clear description of what and why.

Commit messages follow [Conventional
Commits](https://www.conventionalcommits.org/) (`type(scope): description`,
e.g. `fix(sarif): ...`, `feat(cli): ...`, `chore(deps): ...`).
