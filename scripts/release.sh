#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Emilien Klein
# scripts/release.sh — cut a GitHub Action release from origin/main, one
# deliberate step at a time (see CONTRIBUTING.md "Releasing new versions").
#
# Every step re-fetches and re-derives origin/main's tip itself rather than
# trusting local HEAD or a previous invocation's output — the rebase-merge
# flow this repo uses (scripts/ship.sh -> PR -> rebase-merge) means the SHA
# you have locally right after `git commit`, or even right after ship.sh
# pushes to `ship`, is *not* the SHA that ends up on main. Tagging that
# local SHA would tag a commit about to become unreachable once the ship
# branch is deleted post-merge.
#
# There's no --all: run the steps below in order, reading the output
# between them. In particular, --move-major force-pushes a tag every
# `@v1`-style consumer immediately picks up on their next run — deliberately
# not bundled into anything automatic; see CONTRIBUTING.md.
#
# Usage:
#   scripts/release.sh vX.Y.Z                 # dry run: show origin/main's tip, no changes
#   scripts/release.sh vX.Y.Z --tag           # create + push the vX.Y.Z tag
#   scripts/release.sh vX.Y.Z --move-major    # move (or create) the floating major tag
#   scripts/release.sh vX.Y.Z --publish       # gh release create vX.Y.Z --generate-notes
set -euo pipefail

VERSION="${1:-}"
STEP="${2:-}"

if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Usage: $0 vX.Y.Z [--tag|--move-major|--publish]" >&2
  exit 1
fi

MAJOR="${VERSION%%.*}" # e.g. v1.0.5 -> v1

git fetch origin --prune --tags
TARGET_SHA="$(git rev-parse origin/main)"

echo "origin/main is at ${TARGET_SHA}:"
git log --oneline -5 "${TARGET_SHA}"
echo

case "$STEP" in
  "")
    echo "Dry run — no changes made. Steps, in order:"
    echo "  $0 ${VERSION} --tag         # tag ${TARGET_SHA} as ${VERSION} and push it"
    echo "  $0 ${VERSION} --move-major  # move/create floating ${MAJOR} -> ${VERSION} and push"
    echo "  $0 ${VERSION} --publish     # gh release create ${VERSION} --generate-notes"
    ;;
  --tag)
    if git rev-parse "${VERSION}" >/dev/null 2>&1 ||
      git ls-remote --tags origin "refs/tags/${VERSION}" | grep -q .; then
      echo "Tag ${VERSION} already exists — aborting." >&2
      exit 1
    fi
    git tag -a "${VERSION}" "${TARGET_SHA}" -m "${VERSION}"
    git push origin "${VERSION}"
    echo "Tagged and pushed ${VERSION} -> ${TARGET_SHA}"
    ;;
  --move-major)
    if ! git rev-parse "${VERSION}" >/dev/null 2>&1; then
      echo "${VERSION} doesn't exist yet — run '$0 ${VERSION} --tag' first." >&2
      exit 1
    fi
    if git rev-parse "${MAJOR}" >/dev/null 2>&1; then
      echo "Moving existing floating tag ${MAJOR} -> ${VERSION}"
      git tag -f "${MAJOR}" "${VERSION}"
      git push origin "${MAJOR}" --force
    else
      echo "No existing ${MAJOR} tag — creating it fresh (first release of this major line)."
      git tag "${MAJOR}" "${VERSION}"
      git push origin "${MAJOR}"
    fi
    ;;
  --publish)
    gh release create "${VERSION}" --generate-notes
    ;;
  *)
    echo "Unknown step: $STEP (expected --tag, --move-major, or --publish)" >&2
    exit 1
    ;;
esac
