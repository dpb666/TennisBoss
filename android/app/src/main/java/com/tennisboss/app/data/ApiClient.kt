package com.tennisboss.app.data

import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Fabrique le client Retrofit vers l'API TennisBoss.
 *
 * baseUrl :
 *   - Émulateur Android Studio : http://10.0.2.2:8000/  (= localhost du PC)
 *   - Téléphone réel (même Wi-Fi) : http://IP_DU_PC:8000/
 *
 * apiToken : à renseigner SEULEMENT si le serveur a défini TENNISBOSS_API_TOKEN
 * (l'en-tête X-API-Token est alors ajouté à chaque requête).
 */
object ApiClient {

    @Volatile
    var baseUrl: String = "http://192.168.0.94:8000/"
        set(value) {
            if (field != value) {
                field = value
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
