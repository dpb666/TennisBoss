package com.tennisboss.app.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.tennisboss.app.BuildConfig

/**
 * Gère le token API de manière sécurisée. Le token est lu depuis :
 *   1. Variables de build (BuildConfig.TENNISBOSS_API_TOKEN)
 *   2. Fichier de config chiffré (EncryptedSharedPreferences)
 *
 * Le token ne doit JAMAIS être exposé dans l'UI ou envoyé via des canaux non-sécurisés.
 */
object TokenManager {
    private var cachedToken: String? = null

    /**
     * Charge le token depuis la build config ou le stockage chiffré.
     * Appelé une seule fois au démarrage de l'app.
     */
    fun initialize(context: Context) {
        cachedToken = try {
            // Essayer de charger depuis BuildConfig (défini lors de la compilation)
            val buildToken = BuildConfig.TENNISBOSS_API_TOKEN
            if (buildToken.isNotEmpty()) {
                buildToken
            } else {
                // Sinon, charger depuis le stockage chiffré
                loadFromEncryptedStorage(context)
            }
        } catch (e: Exception) {
            null
        }

        // Appliquer au client HTTP
        if (!cachedToken.isNullOrEmpty()) {
            ApiClient.apiToken = cachedToken ?: ""
        }
    }

    private fun loadFromEncryptedStorage(context: Context): String? {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()

            val prefs = EncryptedSharedPreferences.create(
                context,
                "token_storage",
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )

            prefs.getString("api_token", null)
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Stocke le token de manière chiffée (uniquement pour les mises à jour manuelles).
     * À utiliser uniquement en contexte de développement/configuration.
     */
    fun saveToken(context: Context, token: String) {
        try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()

            val prefs = EncryptedSharedPreferences.create(
                context,
                "token_storage",
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )

            prefs.edit().putString("api_token", token).apply()
            cachedToken = token
            ApiClient.apiToken = token
        } catch (e: Exception) {
            // Silencieusement échouer si le chiffrage ne fonctionne pas
        }
    }

    fun getToken(): String = cachedToken ?: ""

    fun isConfigured(): Boolean = !cachedToken.isNullOrEmpty()
}
