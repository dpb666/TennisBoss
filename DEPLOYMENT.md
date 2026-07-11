# Déploiement — accès public permanent (WSL2 + Cloudflare)

Comment l'API TennisBoss (`bot/api.py`, port 8000) est exposée en permanence sur
**https://api.tennisboss.online**, et comment tout redémarre automatiquement
après un reboot du PC. Procédure écrite pour être reproductible sur une
nouvelle machine.

> **`app/` (quant, port 8001) est désactivé (2026-07-11)** — c'était un second
> backend FastAPI (moteur de trading/risque : `auto_bet_engine`, `hedge_manager`,
> `portfolio_greeks`...), jamais relié à l'app Android, jamais testé, laissé
> tourner sans qu'on l'audite. Confirmé abandonné par l'utilisateur lors d'un
> audit senior-engineer du projet. `tennisboss-quant.service` a été stoppé et
> désactivé (`systemctl stop/disable`) — pas supprimé, le code reste dans `app/`
> si besoin de le reprendre un jour. `tennisboss-bot.service` n'en dépend pas
> réellement (son `After=tennisboss-quant.service` n'est qu'un ordre de
> démarrage, pas une dépendance dure) — vérifié fonctionnel sans lui.

## Vue d'ensemble

```
Windows boot → tâche planifiée → wsl.exe démarre Ubuntu
                                        │
                                        ▼
                                    systemd (PID 1)
                                        │
                        ┌───────────────┼───────────────┐
                        ▼               ▼               ▼
                  tennisboss-bot  tennisboss-supervisor  tennisboss-tunnel
                    (port 8000)     (apprentissage)     (cloudflared)
                                                              │
                                                              ▼
                                              Cloudflare (tunnel nommé "tennisboss")
                                                              │
                                                              ▼
                                          DNS api.tennisboss.online (zone Cloudflare)
                                                              │
                                                              ▼
                              tennisboss-api.walid-zahir89.workers.dev (Worker proxy, secret token)
                                                              │
                                                              ▼
                                                    App Android / Telegram / routine cloud
```

Deux façons d'atteindre l'API publiquement :
- **`https://api.tennisboss.online`** — directe, nécessite le header `X-API-Token`.
- **`https://tennisboss-api.walid-zahir89.workers.dev`** — via le Worker Cloudflare
  (`cloudflare/worker.js`), qui injecte le token automatiquement (utile pour des
  clients qui ne doivent pas connaître le secret, ex. le routine cloud CLV monitor).

## 1. Domaine (tennisboss.online, GoDaddy)

Le domaine est acheté chez GoDaddy mais son DNS est délégué à Cloudflare.

1. Dashboard Cloudflare → **Add a Site** → `tennisboss.online` → plan Free.
2. Cloudflare donne 2 nameservers (ex. `karsyn.ns.cloudflare.com`, `titan.ns.cloudflare.com`).
3. GoDaddy → domaine → **Serveurs de noms** → remplacer par ceux de Cloudflare.
4. Attendre l'activation de la zone (souvent quelques minutes à quelques heures ;
   vérifier via `GET https://api.cloudflare.com/client/v4/zones?name=tennisboss.online`,
   champ `status` doit passer à `active`).

> Piste abandonnée : un sous-domaine gratuit `tennisboss.ca.eu.org` avait été demandé
> chez eu.org (registrar bénévole) mais jamais approuvé après 1+ semaine — service
> hors de contrôle, ne pas réessayer sauf patience infinie.

## 2. Tunnel Cloudflare nommé

Le tunnel `tennisboss` (UUID `55d2d52b-aed9-4395-97af-9f732a1a82db`) a été créé une
fois via `cloudflared tunnel create tennisboss`. Ses credentials vivent dans
`~/.cloudflared/` (pas dans le repo — à recréer sur une nouvelle machine).

Config (`~/.cloudflared/config.yml`) :

```yaml
tunnel: 55d2d52b-aed9-4395-97af-9f732a1a82db
credentials-file: /home/alchemist/.cloudflared/55d2d52b-aed9-4395-97af-9f732a1a82db.json

ingress:
  - hostname: api.tennisboss.online
    service: http://localhost:8000
  - hostname: api.tennisboss.ca.eu.org
    service: http://localhost:8000
  - service: http_status:404
```

⚠️ Le `hostname:` doit matcher exactement le Host header de la requête entrante —
sinon Cloudflare tombe sur la règle catch-all `http_status:404` (piège rencontré :
un tunnel rapide `--url` charge quand même ce `config.yml` s'il existe, et renvoie
404 pour tout hostname non listé).

Enregistrement DNS créé dans la zone `tennisboss.online` (dashboard Cloudflare →
DNS → Add record) :

| Type | Name | Target | Proxy |
|---|---|---|---|
| CNAME | `api` | `55d2d52b-aed9-4395-97af-9f732a1a82db.cfargotunnel.com` | Proxied (nuage orange) |

## 3. Worker Cloudflare (proxy avec token caché)

`cloudflare/wrangler.toml` + `cloudflare/worker.js` déploient un Worker qui relaie
vers `TUNNEL_URL` (= `https://api.tennisboss.online`) en injectant `X-API-Token`
côté serveur — les clients du Worker n'ont pas besoin de connaître le secret.

Déploiement (nécessite `CLOUDFLARE_API_TOKEN` dans `.env`, permissions Workers) :

```bash
cd cloudflare
CLOUDFLARE_API_TOKEN="$(grep -E '^CLOUDFLARE_API_TOKEN=' ../.env | cut -d= -f2)" npx wrangler@latest deploy
echo "<TENNISBOSS_API_TOKEN>" | npx wrangler@latest secret put API_TOKEN
```

⚠️ Ne jamais remettre `API_TOKEN` dans `[vars]` de `wrangler.toml` — il serait
commité en clair dans git (c'est arrivé une fois, corrigé par la suite). Toujours
`wrangler secret put`, jamais une variable texte.

## 4. Services systemd (WSL2)

WSL2 doit avoir systemd actif (`/etc/wsl.conf` → `[boot]` → `systemd=true`, puis
`wsl --shutdown` depuis Windows pour appliquer).

Units actifs dans `systemd/*.service` (chemins/utilisateur à adapter si la
machine change — actuellement `User=alchemist`,
`WorkingDirectory=/mnt/c/Users/donpa/TennisBoss`) :

| Service | Rôle | Dépend de |
|---|---|---|
| `tennisboss-bot` | API Flask (port 8000, backend Android) | réseau |
| `tennisboss-supervisor` | apprentissage continu / self-healing (`run.py start`) | bot |
| `tennisboss-tunnel` | `cloudflared tunnel run` (expose bot en public) | réseau |
| `tennisboss-scheduler` | tâches planifiées (`bot.scheduler`) | réseau |

`tennisboss-quant` (port 8001, `app/`) existe toujours dans `systemd/` mais est
**stoppé et désactivé** (`systemctl disable`) — voir note en haut de ce document.

Installation (sur une nouvelle machine, en remplaçant `User=`/`WorkingDirectory=`
dans les fichiers si besoin) :

```bash
sudo cp systemd/tennisboss-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tennisboss-bot tennisboss-supervisor tennisboss-tunnel tennisboss-scheduler
```

Vérification :

```bash
systemctl status tennisboss-bot tennisboss-supervisor tennisboss-tunnel tennisboss-scheduler --no-pager
curl -s http://localhost:8000/health
curl -s https://api.tennisboss.online/health
```

Chaque unit a `Restart=always` — un crash relance le process sans intervention.
`EnvironmentFile=/mnt/c/Users/donpa/TennisBoss/.env` charge les clés API (remplace
le `source .env` de `scripts/start_servers.sh`, qui reste utilisable pour un
lancement ponctuel manuel mais n'est plus nécessaire au quotidien).

## 5. Démarrage automatique de WSL au boot Windows

systemd ne se lance que **quand l'instance WSL démarre** — et WSL ne démarre pas
tout seul au boot de Windows sans configuration additionnelle. Une tâche planifiée
Windows comble ce trou :

```powershell
schtasks.exe /create /tn "TennisBoss-WSL-AutoStart" `
  /tr "wsl.exe -d Ubuntu -u alchemist -- true" `
  /sc onlogon /rl limited /f
```

Puis désactiver la restriction batterie par défaut (importante sur un laptop) :

```powershell
$task = Get-ScheduledTask -TaskName 'TennisBoss-WSL-AutoStart'
$settings = $task.Settings
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries = $false
Set-ScheduledTask -TaskName 'TennisBoss-WSL-AutoStart' -Settings $settings
```

Déclenchement : à l'ouverture de session Windows (`onlogon`), pas au boot
matériel brut (`onstart`) — plus simple, pas besoin de droits admin, suffisant
pour un usage personnel où l'utilisateur se reconnecte après un redémarrage.

Test manuel : `schtasks.exe /run /tn "TennisBoss-WSL-AutoStart"`, puis
`schtasks.exe /query /tn "TennisBoss-WSL-AutoStart" /fo list` → `Dernier résultat: 0`
= succès.

## Limites connues

- **Bug réseau miroir WSL2** (constaté 2026-06-11 et pendant cette mise en place) :
  des connexions QUIC/UDP du tunnel peuvent échouer par intermittence
  (`network is unreachable`) sans cause apparente. `systemctl restart
  tennisboss-tunnel` résout généralement ; en dernier recours `wsl --shutdown`
  depuis Windows puis relancer.
- Si le PC reste éteint plusieurs jours, rien ne se passe (logique) — tout revient
  seul dès la prochaine ouverture de session.
- Le token `TENNISBOSS_API_TOKEN` (`.env`) doit rester synchronisé avec le secret
  Wrangler du Worker (`wrangler secret put API_TOKEN`) si jamais il est régénéré.
