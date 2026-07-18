# Off-site encrypted backup of TennisBoss state (Windows operator host).
#
# Usage (PowerShell):
#   $env:BACKUP_DEST = "D:\Backups\tennisboss"
#   $env:BACKUP_ENCRYPT_PASS = "..."   # optional — 7-Zip AES-256
#   .\scripts\backup_offsite.ps1
#
# Requires 7-Zip (7z.exe on PATH) when BACKUP_ENCRYPT_PASS is set.
# Never commit secrets.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Dest = $env:BACKUP_DEST
if (-not $Dest) {
    Write-Error "BACKUP_DEST requis (répertoire hors machine)"
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$Archive = Join-Path $Dest "tennisboss-state-$Stamp.zip"

$Candidates = @(
    "state\tennisboss.db",
    "state\memory.json",
    "state\backups"
)
$Existing = @($Candidates | Where-Object { Test-Path $_ })
if ($Existing.Count -eq 0) {
    Write-Error "Aucun fichier state à sauvegarder"
}

Compress-Archive -Path $Existing -DestinationPath $Archive -Force
Write-Host "Archive : $Archive"

$Pass = $env:BACKUP_ENCRYPT_PASS
if ($Pass) {
    $Enc = "$Archive.7z"
    $SevenZ = Get-Command 7z -ErrorAction SilentlyContinue
    if (-not $SevenZ) {
        Write-Error "7z.exe requis pour le chiffrement (installez 7-Zip)"
    }
    & 7z a -t7z -mhe=on -p"$Pass" -mx=9 $Enc $Archive | Out-Null
    Remove-Item $Archive -Force
    Write-Host "Chiffré : $Enc"
}

# Rétention : 14 dernières archives
Get-ChildItem $Dest -Filter "tennisboss-state-*" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 14 |
    Remove-Item -Force -ErrorAction SilentlyContinue
