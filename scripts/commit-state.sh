#!/usr/bin/env bash
# Commit changes in state/ from a GitHub Actions run and push them, retrying on races.
set -euo pipefail

msg="${1:-Zustand aktualisiert}"
git config user.name "techeroesuniverse-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add state/
if git diff --cached --quiet; then
  echo "Keine Änderungen am Zustand."
  exit 0
fi
git commit -m "${msg} [skip ci]"

for attempt in 1 2 3 4 5; do
  if git push; then
    exit 0
  fi
  echo "Push abgelehnt (Versuch ${attempt}), hole neuen Stand …"
  sleep $((attempt * 3))
  git pull --rebase
done
echo "::error::Zustand konnte nicht gespeichert werden"
exit 1
