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

    @Volatile
    var apiToken: String = ""

    /** Implémentation injectable pour les tests (court-circuite Retrofit). */
    @Volatile
    var apiOverride: TennisBossApi? = null

    fun create(): TennisBossApi {
        apiOverride?.let { return it }

        val client = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)   // LLM local peut être lent
            .writeTimeout(30, TimeUnit.SECONDS)
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
    }
}
