package com.tennisboss.app.data

import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Fabrique le client Retrofit vers l'API TennisBoss.
 *
 * L'app mobile utilise l'API publique Cloudflare pour fonctionner hors du
 * réseau local. Le serveur local reste possible en tests via [apiOverride].
 *
 * apiToken : à renseigner SEULEMENT si le serveur a défini TENNISBOSS_API_TOKEN
 * (l'en-tête X-API-Token est alors ajouté à chaque requête).
 */
object ApiClient {
    // 10.0.2.2 = loopback de la machine hôte vue depuis l'émulateur Android
    // (localhost dans l'émulateur = l'émulateur lui-même, pas ton PC).
    const val EMULATOR_BASE_URL = "http://10.0.2.2:8000/"
    // Worker Cloudflare (pas api.tennisboss.online directement) : le Worker injecte
    // X-API-Token côté serveur, donc les vrais appareils n'ont jamais besoin de connaître
    // le secret. Un token compilé dans BuildConfig serait extractible de l'APK public
    // (décompilation triviale) — voir TokenManager, gardé pour les tests locaux uniquement.
    const val DEFAULT_BASE_URL = "https://tennisboss-api.walid-zahir89.workers.dev/"

    private fun defaultUrl(): String {
        val fp = android.os.Build.FINGERPRINT
        val product = android.os.Build.PRODUCT
        val model = android.os.Build.MODEL
        val isEmulator = fp.startsWith("generic") || fp.startsWith("unknown") ||
            model.contains("Emulator") || model.contains("Android SDK") ||
            android.os.Build.MANUFACTURER == "Genymotion" ||
            product.startsWith("sdk") || product.contains("gphone") ||
            product.contains("emulator", ignoreCase = true)
        return if (isEmulator) EMULATOR_BASE_URL else DEFAULT_BASE_URL
    }

    // Calculé à la PREMIÈRE LECTURE, pas au chargement de la classe : un `object`
    // Kotlin exécute tous ses initialisateurs de champs dès qu'un membre est
    // touché (ex. ApiClient.apiOverride = ...), donc un `= defaultUrl()` ici
    // forcerait android.os.Build.* à chaque fois — y compris dans les tests
    // unitaires JVM (sans device ni Robolectric), où Build.FINGERPRINT est
    // null → NullPointerException avant même que le test n'ait pu s'exécuter.
    @Volatile
    private var _baseUrl: String? = null

    var baseUrl: String
        get() = _baseUrl ?: defaultUrl().also { _baseUrl = it }
        set(value) {
            if (_baseUrl != value) {
                _baseUrl = value
                _cached = null  // invalide le cache si l'URL change
            }
        }

    @Volatile
    var apiToken: String = ""
        set(value) {
            if (field != value) {
                field = value
                _cached = null  // invalide le cache si le token change
            }
        }

    /** Implémentation injectable pour les tests (court-circuite Retrofit). */
    @Volatile
    var apiOverride: TennisBossApi? = null

    @Volatile
    private var _cached: TennisBossApi? = null

    fun create(): TennisBossApi {
        apiOverride?.let { return it }
        _cached?.let { return it }

        val client = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(300, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val builder = chain.request().newBuilder()
                if (apiToken.isNotBlank()) {
                    builder.addHeader("X-API-Token", apiToken)
                }
                chain.proceed(builder.build())
            }
            .build()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(TennisBossApi::class.java)
            .also { _cached = it }
    }
}
