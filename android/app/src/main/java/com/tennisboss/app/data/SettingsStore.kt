package com.tennisboss.app.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

// Un seul DataStore par appli (déclaré sur le Context applicatif).
private val Context.dataStore by preferencesDataStore(name = "tennisboss_settings")

/**
 * Stocke et restaure les réglages (URL du serveur) entre les lancements.
 * Les valeurs sont aussi appliquées à [ApiClient] au démarrage.
 *
 * Le token API est geré séparément via TokenManager (variables de build ou
 * fichier de config sécurisé) et ne doit pas être exposé dans l'UI.
 */
class SettingsStore(private val context: Context) {

    private object Keys {
        val BASE_URL = stringPreferencesKey("base_url")
    }

    val baseUrlFlow: Flow<String> = context.dataStore.data
        .map { it[Keys.BASE_URL] ?: ApiClient.baseUrl }

    suspend fun setBaseUrl(value: String) {
        context.dataStore.edit { it[Keys.BASE_URL] = value }
    }
}
