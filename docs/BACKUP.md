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
0 4 * * 0 cd /mnt/c/Users/donpa/TennisBoss && BACKUP_DEST=/mnt/backups/tennisboss ./scripts/backup_offsite.sh >> /var/log/tennisboss-backup.log 2>&1
```

Set `BACKUP_DEST` to a cloud-sync folder (OneDrive, Google Drive, NAS mount, etc.).
Optional `BACKUP_ENCRYPT_PASS` in host `.env` only — never commit.

### Windows Task Scheduler

1. Open **Task Scheduler** → **Create Task**
2. **Triggers:** Weekly, Sunday, 04:00 (local or UTC — pick one and stay consistent)
3. **Actions:** Start a program
   - Program: `powershell.exe`
   - Arguments: `-NoProfile -ExecutionPolicy Bypass -File "C:\Users\donpa\TennisBoss\scripts\backup_offsite.ps1"`
4. **Environment:** add user variables on the task (or in your PowerShell profile):
   - `BACKUP_DEST` = e.g. `D:\Backups\tennisboss-sync` (folder synced to cloud)
   - `BACKUP_ENCRYPT_PASS` = optional encryption passphrase (host only)
5. Run with highest privileges if the script must read `state/` while services are stopped;
   on a live host, locked DB files in `state/backups/` may be skipped (expected).

Dry-run from PowerShell:

```powershell
$env:BACKUP_DEST = "D:\Backups\tennisboss"
.\scripts\backup_offsite.ps1
```
