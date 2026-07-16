package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.BuildConfig
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.AppVersionInfo
import kotlinx.coroutines.launch

/** Bandeau "nouvelle version disponible" — avant publication Play Store
 * (qui gère ça nativement une fois publié). Compare BuildConfig.VERSION_CODE
 * (build installée) au version_code publié côté backend (voir
 * GET /api/app/version, run.py set-app-version). Ne fait AUCUNE
 * installation automatique — juste un bandeau informatif dismissible.
 */
class UpdateBannerViewModel : ViewModel() {

    var updateInfo by mutableStateOf<AppVersionInfo?>(null)
        private set

    var dismissed by mutableStateOf(false)
        private set

    val isUpdateAvailable: Boolean
        get() {
            val info = updateInfo ?: return false
            return !dismissed && info.available &&
                (info.version_code ?: 0) > BuildConfig.VERSION_CODE
        }

    fun checkForUpdate() {
        viewModelScope.launch {
            try {
                updateInfo = ApiClient.create().appVersion()
            } catch (e: Exception) {
                // Silencieux : l'app doit fonctionner même si le check échoue
                // (pas de connectivité, endpoint absent sur une vieille build backend...).
                updateInfo = null
            }
        }
    }

    fun dismiss() {
        dismissed = true
    }
}
