#!/usr/bin/env bash
# Off-site encrypted backup of TennisBoss state (WSL/Linux prod host).
#
# Usage:
#   export BACKUP_DEST=/mnt/backups/tennisboss   # required
#   export BACKUP_ENCRYPT_PASS=...               # optional — gpg symmetric
#   scripts/backup_offsite.sh
#
# Never commit secrets. BACKUP_ENCRYPT_PASS lives in .env on the host only.

set -euo pipefail
cd "$(dirname "$0")/.."

DEST="${BACKUP_DEST:-}"
if [ -z "$DEST" ]; then
  echo "BACKUP_DEST requis (répertoire de destination hors machine)" >&2
  exit 2
fi

mkdir -p "$DEST"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE="$DEST/tennisboss-state-$STAMP.tar.gz"

FILES=(state/tennisboss.db state/memory.json state/backups)
EXISTING=()
for f in "${FILES[@]}"; do
  [ -e "$f" ] && EXISTING+=("$f")
done

if [ ${#EXISTING[@]} -eq 0 ]; then
  echo "Aucun fichier state à sauvegarder" >&2
  exit 1
fi

tar -czf "$ARCHIVE" "${EXISTING[@]}"
echo "Archive : $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

if [ -n "${BACKUP_ENCRYPT_PASS:-}" ]; then
  ENC="$ARCHIVE.gpg"
  gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase "$BACKUP_ENCRYPT_PASS" -o "$ENC" "$ARCHIVE"
  rm -f "$ARCHIVE"
  echo "Chiffré : $ENC"
fi

# Rétention : garder les 14 dernières archives (chiffrées ou non)
ls -1t "$DEST"/tennisboss-state-* 2>/dev/null | tail -n +15 | xargs -r rm -f
