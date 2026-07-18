# TennisBoss — Off-site backup

Local backups (`state/backups/`, every 6h via scheduler) protect against same-host
corruption. For machine loss, copy encrypted archives off-site.

## Scripts

| Script | Host | Output |
|---|---|---|
| `scripts/backup_offsite.sh` | WSL/Linux prod | `tennisboss-state-*.tar.gz` (+ optional `.gpg`) |
| `scripts/backup_offsite.ps1` | Windows operator | `tennisboss-state-*.zip` (+ optional `.7z`) |

## Environment (never commit)

```bash
export BACKUP_DEST=/mnt/backups/tennisboss    # off-machine path or cloud sync folder
export BACKUP_ENCRYPT_PASS=...                # optional symmetric encryption
```

PowerShell equivalent: `$env:BACKUP_DEST`, `$env:BACKUP_ENCRYPT_PASS`.

## What is copied

- `state/tennisboss.db` — picks, CLV, bet_history, players
- `state/memory.json` — learned profiles
- `state/backups/` — recent local DB snapshots

## Restore (outline)

1. Stop services: `sudo systemctl stop tennisboss-bot tennisboss-scheduler`
2. Decrypt if needed: `gpg -d archive.gpg | tar -xzf -` (or 7z x archive.7z)
3. Replace `state/tennisboss.db` and `state/memory.json`
4. Restart services and verify `curl https://api.tennisboss.online/health`

## Retention

Both scripts keep the **14 most recent** off-site archives.

## Schedule suggestion

Weekly cron (Sunday 04:00 UTC, after local backup):

```bash
0 4 * * 0 BACKUP_DEST=/mnt/backups/tennisboss /path/to/TennisBoss/scripts/backup_offsite.sh
```
