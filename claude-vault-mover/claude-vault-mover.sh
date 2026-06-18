#!/usr/bin/env bash
set -euo pipefail

# ============================ CONFIG ============================
# Where the browser drops downloads:
WATCH_DIR="$HOME/Downloads"

# Where Claude files should land. Pointing at an _inbox subfolder, NOT the
# vault root, so exports get a review step before they pollute your flat vault.
VAULT_INBOX="/Users/parashuram/Documents/Personal-Backup"

# Source-URL substrings that mark a file as "from Claude". Add the exact
# host if you find one (see the note in the chat on how to check).
MATCH=("claude.ai" "anthropic")

LOG="$HOME/Library/Logs/claude-vault-mover.log"
# ===============================================================

mkdir -p "$VAULT_INBOX"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG"; }

shopt -s nullglob
for f in "$WATCH_DIR"/*; do
  [ -f "$f" ] || continue
  base="$(basename "$f")"

  # Skip in-progress downloads and dotfiles.
  case "$base" in
    *.crdownload|*.download|*.part|*.partial|.*) continue ;;
  esac

  # Read the source URL the browser recorded (quarantine metadata).
  # Files with no WhereFroms (e.g. things you created locally) are skipped,
  # so we never move anything we can't positively identify as a download.
  src="$(mdls -raw -name kMDItemWhereFroms "$f" 2>/dev/null | tr -d '\0')"
  [ -z "$src" ] && continue
  [ "$src" = "(null)" ] && continue

  matched=false
  for m in "${MATCH[@]}"; do
    if printf '%s' "$src" | grep -qi "$m"; then matched=true; break; fi
  done
  $matched || continue

  # Make sure the file is fully written: size must be stable across 1s.
  s1=$(stat -f%z "$f"); sleep 1; s2=$(stat -f%z "$f")
  if [ "$s1" -ne "$s2" ]; then log "skip (still writing): $base"; continue; fi

  # If a file of the same name already exists in the vault, skip it and
  # leave the download in place rather than creating a duplicate.
  dest="$VAULT_INBOX/$base"
  if [ -e "$dest" ]; then
    log "skip (already exists): $base"
    continue
  fi

  mv "$f" "$dest"
  log "moved: $base -> $dest"
done
