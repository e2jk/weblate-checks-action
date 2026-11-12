#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
# .github/scripts/auto-rebase-stale-bot-prs.sh
#
# Finds open Dependabot PRs against main that have fallen behind (or hit a
# conflict, or sit on a CI run from before main advanced) and asks
# Dependabot to rebase them — see
# .github/workflows/auto-rebase-stale-bot-prs.yml for the full "why". Ported
# from OpenHangar's script of the same name, minus its Renovate label
# trigger and its stuck-CI-run recovery (a workaround for a CI concurrency
# lane this repo doesn't have).
#
# How the rebase is triggered: an "@dependabot rebase" comment posted with
# GH_COMMENT_TOKEN, a PAT for the repo owner. It can't be GITHUB_TOKEN —
# tested on PR #91: Dependabot answers a github-actions[bot] comment with
# "Sorry, only users with push access can use that command." From the
# owner's account it's accepted (👍 reaction), after which Dependabot either
# rebases the PR in place or, for a group update, closes it and opens a
# fresh one built on the current main (#91 -> #95). Either way the PR stops
# sitting stale, and dependabot-automerge.yml re-enables auto-merge on the
# new push/PR.
#
# The comment body is exactly "@dependabot rebase" — nothing else, since
# that's the form verified to work. Attempts are therefore counted as
# comments whose body starts with that command, whoever posted them (a
# manual one counts too, which is fine: it was a rebase attempt either way).
#
# Every PR this script looks at is logged — number, author login, and
# mergeStateStatus — even the ones skipped, so a mismatch (e.g. gh >= 2.98
# reporting the bot as "app/dependabot" instead of "dependabot[bot]", which
# once made OpenHangar's version silently match nothing) shows up in the
# log instead of as quiet inaction.
#
# Treats mergeStateStatus UNKNOWN and BLOCKED like BEHIND/DIRTY (worth a
# nudge):
#
# - UNKNOWN is GitHub's "still computing" placeholder, returned while it
#   recomputes mergeability after a push to main — exactly when this
#   workflow's push:main trigger fires, so treating it as "not stale" would
#   skip the very PRs that push just made stale.
# - BLOCKED is what a PR settles into when its merge preview is clean
#   against the current main but its last CI run predates that main and
#   was never re-triggered.
#
# A false-positive nudge (a PR that didn't need it, or that's failing for
# an unrelated reason) costs at most MAX_ATTEMPTS comments, after which the
# PR is left for a human.
#
# A PR labelled `no-auto-rebase` is skipped entirely — for a bot PR that's
# blocked on something a rebase can't fix (e.g. a bump that conflicts with
# another package's pin until that package releases). Remove the label once
# the blocking condition is resolved.
#
# Requires GH_TOKEN (read access is enough), GH_COMMENT_TOKEN (posts the
# comment) and GH_REPO in the environment — safe to run locally with
# personal tokens to debug.
#
# Env vars (optional, defaults match the workflow):
#   MAX_ATTEMPTS  max rebase nudges per PR before leaving it for a human (default 3)

set -uo pipefail

MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
COMMAND="@dependabot rebase"

: "${GH_COMMENT_TOKEN:?GH_COMMENT_TOKEN must be set (PAT for an account with push access)}"

# gh CLI >= 2.98 reports GitHub App PR authors as "app/<slug>" instead of
# the classic "<slug>[bot]" — match both.
is_dependabot() {
  [ "$1" = "dependabot[bot]" ] || [ "$1" = "app/dependabot" ]
}

echo "Listing open PRs against main..."
prs_json=$(gh pr list --state open --base main --limit 100 --json number,author,mergeStateStatus,labels)
pr_count=$(echo "$prs_json" | jq 'length')
echo "Found $pr_count open PR(s) targeting main."
echo

# Nudges at most one PR per run. Rebasing several at once makes them all
# re-run CI together; whichever merges first leaves the others behind main
# again, wasting their attempt. The push:main trigger re-invokes this
# script as soon as that one PR lands, pacing nudges to the merge cadence.
#
# `shuf` picks that one PR at random, so a PR that's stale for a real
# reason can't monopolize every run (until it burns its attempts) while a
# PR that would merge cleanly waits behind it.
echo "$prs_json" | jq -c '.[]' | shuf | while read -r pr; do
  number=$(echo "$pr" | jq -r '.number')
  login=$(echo "$pr" | jq -r '.author.login')
  status=$(echo "$pr" | jq -r '.mergeStateStatus')
  has_skip_label=$(echo "$pr" | jq -r '[.labels[].name] | any(. == "no-auto-rebase")')

  if ! is_dependabot "$login"; then
    echo "PR #$number: author '$login' is not Dependabot — skipping."
    continue
  fi

  if [ "$has_skip_label" = "true" ]; then
    echo "PR #$number (author '$login'): labelled 'no-auto-rebase' — skipping."
    continue
  fi

  case "$status" in
    BEHIND | DIRTY | UNKNOWN | BLOCKED) ;;
    *)
      echo "PR #$number (author '$login'): mergeStateStatus=$status — not stale, skipping."
      continue
      ;;
  esac

  attempts=$(gh pr view "$number" --json comments \
    --jq "[.comments[] | select(.body | startswith(\"$COMMAND\"))] | length")

  if [ "$attempts" -ge "$MAX_ATTEMPTS" ]; then
    echo "PR #$number: mergeStateStatus=$status, already asked $attempts/$MAX_ATTEMPTS times — leaving for a human."
    continue
  fi

  echo "PR #$number: mergeStateStatus=$status, asking Dependabot to rebase, attempt $((attempts + 1))/$MAX_ATTEMPTS"
  if ! GH_TOKEN="$GH_COMMENT_TOKEN" gh pr comment "$number" --body "$COMMAND"; then
    echo "::warning::Failed to comment on PR #$number"
    continue
  fi

  echo "Nudged PR #$number this run — leaving any other stale PR for next time."
  break
done

echo
echo "Done — checked $pr_count PR(s)."
