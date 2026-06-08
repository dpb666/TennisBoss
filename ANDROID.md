# 📱 TennisBoss — Brancher l'app Android sur l'API REST

Le « cerveau » TennisBoss tourne côté serveur ; l'app Android n'est qu'un client
HTTP qui appelle l'API JSON. Aucune logique de prédiction n'est dupliquée dans
l'app — elle affiche ce que renvoie l'API.

## 1. Lancer le backend

```bash
cd TennisBoss
pip install -r requirements.txt
python3 run.py train --years 2022 2023 2024 --tours atp wta   # une fois
python3 run.py serve --host 0.0.0.0 --port 8000               # API REST
```

- `--host 0.0.0.0` rend l'API accessible aux autres appareils du réseau local.
- Protéger l'accès (optionnel) : `export TENNISBOSS_API_TOKEN="mon-secret"` avant
  `serve` → chaque requête `/api/*` devra envoyer l'en-tête `X-API-Token`.

### Quelle adresse depuis le téléphone ?
| Contexte | URL de base |
|---|---|
| Émulateur Android Studio | `http://10.0.2.2:8000` (alias de la machine hôte) |
| Téléphone réel (même Wi-Fi) | `http://IP_DU_PC:8000` (ex. `192.168.1.20`) |
| Production | derrière HTTPS (reverse-proxy nginx/Caddy + `gunicorn`) |

## 2. Référence des endpoints

| Méthode | Endpoint | Paramètres | Retour |
|---|---|---|---|
| GET | `/health` | — | état du service |
| GET | `/api/status` | — | métriques modèle + base |
| GET | `/api/players` | `q`, `tour`, `limit` | recherche joueurs (autocomplete) + proba |
| GET | `/api/predict` | `p1`, `p2` | prédiction 1er set |
| GET | `/api/upcoming` | `days`, `limit`, `odds=true` | matchs à venir + prédictions (+cotes) |
| GET | `/api/value` | `limit` | modèle (1er set) vs marché (match) |

Exemple :
```
GET /api/predict?p1=Iga%20Swiatek&p2=Aryna%20Sabalenka
{
  "first_set": {"prob1": 53.13, "prob2": 46.87, "favorite": "Iga Swiatek", ...},
  "player1": {"name": "Iga Swiatek", "matches": 227, "win_prob_vs_avg": 0.69, ...},
  "player2": {...}
}
```

## 3. Côté Android (Kotlin + Retrofit)

`app/build.gradle` :
```gradle
implementation 'com.squareup.retrofit2:retrofit:2.11.0'
implementation 'com.squareup.retrofit2:converter-gson:2.11.0'
```

HTTP en clair en dev : `AndroidManifest.xml` →
`<application android:usesCleartextTraffic="true" ...>` + permission
`<uses-permission android:name="android.permission.INTERNET"/>`.

```kotlin
// Modèles
data class PredictResponse(val first_set: FirstSet, val player1: Player, val player2: Player)
data class FirstSet(val prob1: Double, val prob2: Double, val favorite: String?, val verdict: String)
data class Player(val name: String, val matches: Int, val win_prob_vs_avg: Double, val confident: Boolean)

// API
interface TennisBossApi {
    @GET("api/predict")
    suspend fun predict(@Query("p1") p1: String, @Query("p2") p2: String): PredictResponse

    @GET("api/players")
    suspend fun players(@Query("q") q: String, @Query("limit") limit: Int = 20): PlayersResponse
}

// Client
object Api {
    private const val BASE = "http://10.0.2.2:8000/"   // émulateur
    val service: TennisBossApi = Retrofit.Builder()
        .baseUrl(BASE)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(TennisBossApi::class.java)
}

// Usage (dans une coroutine / ViewModel)
val r = Api.service.predict("Iga Swiatek", "Aryna Sabalenka")
println("${r.first_set.favorite} — ${r.first_set.prob1}%")
```

Si `TENNISBOSS_API_TOKEN` est défini côté serveur, ajoutez un interceptor OkHttp
qui pose l'en-tête `X-API-Token` sur chaque requête.

## 4. Limites & honnêteté
- Précision modèle ~0,61 hors-échantillon : aide à la décision, pas une garantie.
- L'API `value`/`odds` compare des marchés **différents** (1er set vs match) — voir
  README. **Aucun pari n'est placé automatiquement.**
- Le serveur Flask intégré est pour le **dev** ; en production, passez par
  `gunicorn` + reverse-proxy HTTPS.
