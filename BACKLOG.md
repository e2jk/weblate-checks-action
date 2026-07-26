# Backlog

Live "still to do" list for this repository — remove items once implemented,
don't leave completed work here.

## One-time repo settings (not automatable)

- **Register for an OpenSSF Best Practices badge** (optional, fixes the
  `CII-Best-Practices` Scorecard check, currently 0/10) at
  <https://www.bestpractices.dev/en/projects/new> — a one-time
  questionnaire tied to a personal/org account, not something to automate.
  `.bestpractices.json` pre-fills proposed answers for that questionnaire.
- **Once the project above is registered and the questionnaire saved**: add
  the resulting `[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/NUMBER/badge)](https://www.bestpractices.dev/projects/NUMBER)`
  badge to the README (same spot as the other badges, see OpenHangar's
  README for the pattern), and delete `.bestpractices.json` — the badge app
  only reads it live when triggering an automation pass, so it's not needed
  once the answers are saved.
