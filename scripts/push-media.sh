#!/usr/bin/env bash
# Upload the media files of one week to the branch media/<week>.
#
#   scripts/push-media.sh 2026-W49 build/2026-W49
#
# The branch contains only that week's files (no history from main). Every file is
# committed and pushed on its own so each push stays small. Re-running replaces
# changed files and adds missing ones.
set -euo pipefail

week="${1:?Woche fehlt, z. B. 2026-W49}"
src="$(cd "${2:?Ordner mit den Dateien fehlt}" && pwd)"
[[ "$week" =~ ^[0-9]{4}-W[0-9]{2}$ ]] || { echo "Ungültige Woche: $week" >&2; exit 1; }

repo="$(git rev-parse --show-toplevel)"
branch="media/${week}"
work="$(mktemp -d)"
trap 'git -C "$repo" worktree remove --force "$work" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

max_bytes=$(python3 -c "import yaml;print(yaml.safe_load(open('$repo/config.yaml'))['limits']['max_media_bytes'])")

if git -C "$repo" ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
  git -C "$repo" fetch --depth=1 origin "+refs/heads/${branch}:refs/remotes/origin/${branch}"
  git -C "$repo" worktree add --detach "$work" "origin/${branch}" >/dev/null
else
  git -C "$repo" worktree add --detach "$work" >/dev/null
  git -C "$work" checkout --orphan "tmp-${week}" >/dev/null
  git -C "$work" rm -rf --quiet . >/dev/null 2>&1 || true
  git -C "$work" clean -fdxq
fi

shopt -s nullglob
files=("$src"/*.mp4 "$src"/*.mov "$src"/*.jpg "$src"/*.jpeg)
[[ ${#files[@]} -gt 0 ]] || { echo "Keine Mediendateien in $src" >&2; exit 1; }

for f in "${files[@]}"; do
  name="$(basename "$f")"
  size=$(stat -c %s "$f")
  if (( size > max_bytes )); then
    echo "$name ist zu groß ($size Bytes) – erst mit 'python -m igpost prepare' umwandeln" >&2
    exit 1
  fi
  cp "$f" "$work/$name"
  git -C "$work" add -- "$name"
  if git -C "$work" diff --cached --quiet; then
    echo "unverändert: $name"
    continue
  fi
  git -C "$work" -c user.name="techeroesuniverse-bot" -c user.email="noreply@anthropic.com" \
    commit -q -m "Medien ${week}: ${name}"
  for attempt in 1 2 3; do
    if git -C "$work" -c push.negotiate=true push -q origin "HEAD:refs/heads/${branch}"; then
      echo "hochgeladen: $name ($(( size / 1000000 )) MB)"
      break
    fi
    [[ $attempt -eq 3 ]] && { echo "Upload von $name fehlgeschlagen" >&2; exit 1; }
    sleep $((attempt * 5))
  done
done
echo "Fertig: ${branch}"
