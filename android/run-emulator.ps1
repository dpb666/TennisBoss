# TennisBoss — lancer émulateur + installer l'app debug
# Usage: .\run-emulator.ps1

$ErrorActionPreference = "Stop"
$Sdk = "C:\Users\donpa\AppData\Local\Android\Sdk"
$env:ANDROID_HOME = $Sdk
$env:ANDROID_SDK_ROOT = $Sdk
$env:PATH = "$Sdk\platform-tools;$Sdk\emulator;$Sdk\cmdline-tools\latest\bin;$env:PATH"

Write-Host "=== SDK ===" -ForegroundColor Cyan
& adb version
Write-Host "`n=== AVDs ===" -ForegroundColor Cyan
& emulator -list-avds

$devices = & adb devices | Select-String "device$"
if (-not $devices) {
    Write-Host "`nDemarrage AVD TennisBoss..." -ForegroundColor Yellow
    Start-Process -FilePath "$Sdk\emulator\emulator.exe" -ArgumentList "-avd","TennisBoss","-no-snapshot-load","-gpu","auto" -WindowStyle Normal
    Write-Host "Attente boot (60s)..."
    Start-Sleep -Seconds 60
    & adb wait-for-device
    & adb shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 2; done; input keyevent 82'
}

Write-Host "`n=== Backend (doit tourner sur le PC) ===" -ForegroundColor Cyan
Write-Host "Dans un autre terminal: cd C:\Users\donpa\TennisBoss && python run.py serve --host 0.0.0.0 --port 8000"
Write-Host "Test: curl http://127.0.0.1:8000/health"
Write-Host "Emulateur utilise: http://10.0.2.2:8000/ (ApiClient.kt)"

Write-Host "`n=== Build + install ===" -ForegroundColor Cyan
Set-Location $PSScriptRoot
& .\gradlew installDebug --no-daemon

Write-Host "`n=== Lancement app ===" -ForegroundColor Cyan
& adb shell am start -n com.tennisboss.app/.MainActivity
Write-Host "OK" -ForegroundColor Green
