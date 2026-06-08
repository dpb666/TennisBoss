# TennisBoss — expose l'API (qui tourne dans WSL) sur le Wi-Fi, pour tester
# l'app SANS câble USB.
#
# >>> A LANCER DANS UN PowerShell EXECUTE EN ADMINISTRATEUR <<<
#   cd C:\Users\donpa\TennisBoss\android\scripts
#   powershell -ExecutionPolicy Bypass -File .\wifi-forward.ps1
#
# A relancer apres un redemarrage du PC ou de WSL (l'IP de WSL change).

$port = 8000

# IP de WSL (recalculee a chaque execution).
$wslIp = (wsl hostname -I).Trim().Split(" ")[0]
if (-not $wslIp) { Write-Error "IP WSL introuvable. WSL est-il demarre ?"; exit 1 }

# Redirection 0.0.0.0:port (cote Windows) -> WSL:port
netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
netsh interface portproxy add    v4tov4 listenport=$port listenaddress=0.0.0.0 connectport=$port connectaddress=$wslIp

# Regle pare-feu entrante (idempotente)
netsh advfirewall firewall delete rule name="TennisBoss $port" 2>$null | Out-Null
netsh advfirewall firewall add rule name="TennisBoss $port" dir=in action=allow protocol=TCP localport=$port | Out-Null

# IP LAN Wi-Fi du PC (a saisir dans l'app)
$lan = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -like '192.168.*' -or $_.IPAddress -like '10.*' } |
    Where-Object { $_.InterfaceAlias -match 'Wi-Fi|Wireless|Ethernet' } |
    Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "==================================================="
Write-Host " Redirection active : 0.0.0.0:$port -> $($wslIp):$port"
Write-Host " URL a mettre dans l'app : http://$($lan):$port/"
Write-Host " (telephone sur le MEME Wi-Fi ; serveur lance avec --host 0.0.0.0)"
Write-Host "==================================================="
netsh interface portproxy show v4tov4
