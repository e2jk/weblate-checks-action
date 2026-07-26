# Governance

This project uses a **solo-maintainer** model: one person (currently Emilien
Klein, [@e2jk](https://github.com/e2jk)) holds every role — design decisions,
code review of external contributions, releases, security response, and
Code of Conduct enforcement — and has final say on all of them.

## Roles and responsibilities

There is currently no separate triage, review, or release team; the
maintainer is that team. In practice:

- **Design and code decisions**: the maintainer's own commits land without a
  second reviewer (see [`CONTRIBUTING.md`](CONTRIBUTING.md#landing-changes-on-main)
  for why); external contributions go through a normal reviewed pull
  request.
- **Security reports**: handled per [`SECURITY.md`](SECURITY.md).
- **Code of Conduct enforcement**: handled per
  [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
- **Releases**: cut by the maintainer per
  [`CONTRIBUTING.md`](CONTRIBUTING.md#releasing-new-versions).

## Decision-making

For a project this size, decisions are made unilaterally by the maintainer,
informed by discussion on issues/pull requests where a change originates
from someone else. There's no voting process or steering committee — that
overhead isn't justified at the current scale, and would mostly be
theater for a project with one active contributor.

## Continuity

There is currently no designated backup maintainer with repository admin
access. If that changes, this document will be updated to name who has that
access and how it was granted.
