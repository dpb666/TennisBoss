# Annule la redirection Wi-Fi de wifi-forward.ps1.
# A lancer en PowerShell ADMINISTRATEUR.
$port = 8000
netsh interface portproxy delete v4tov4 listenport=$port listenaddress=0.0.0.0 2>$null | Out-Null
netsh advfirewall firewall delete rule name="TennisBoss $port" 2>$null | Out-Null
Write-Host "Redirection et regle pare-feu supprimees (port $port)."
