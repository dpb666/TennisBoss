package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.PlayerDetail
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

sealed interface PlayerDetailState {
    object Idle : PlayerDetailState
    object Loading : PlayerDetailState
    data class Success(val data: PlayerDetail) : PlayerDetailState
    data class Error(val message: String) : PlayerDetailState
}

/** Charge la fiche détaillée d'un joueur (/api/player). */
class PlayerDetailViewModel : ViewModel() {

    var state by mutableStateOf<PlayerDetailState>(PlayerDetailState.Idle)
        private set

    fun load(name: String) {
        state = PlayerDetailState.Loading
        viewModelScope.launch {
            try {
                val d = withContext(Dispatchers.IO) {
                    ApiClient.create().player(name = name)
                }
                state = PlayerDetailState.Success(d)
            } catch (e: Exception) {
                state = PlayerDetailState.Error("Fiche indisponible : ${e.message}")
            }
        }
    }

    fun clear() {
        state = PlayerDetailState.Idle
    }
}
