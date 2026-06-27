package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.LiveResponse
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

sealed interface LiveUiState {
    data object Idle : LiveUiState
    data object Loading : LiveUiState
    data class Success(val data: LiveResponse, val refreshIn: Int = 30) : LiveUiState
    data class Error(val message: String) : LiveUiState
}

class LiveViewModel : ViewModel() {

    var state by mutableStateOf<LiveUiState>(LiveUiState.Idle)
        private set

    private var autoRefreshJob: kotlinx.coroutines.Job? = null

    fun startAutoRefresh() {
        if (autoRefreshJob?.isActive == true) return
        autoRefreshJob = viewModelScope.launch {
            while (isActive) {
                load()
                // Countdown 30s entre chaque refresh
                var countdown = 30
                while (isActive && countdown > 0) {
                    delay(1000)
                    countdown--
                    val current = state
                    if (current is LiveUiState.Success) {
                        state = current.copy(refreshIn = countdown)
                    }
                }
            }
        }
    }

    fun stopAutoRefresh() {
        autoRefreshJob?.cancel()
        autoRefreshJob = null
    }

    fun loadOnce() {
        viewModelScope.launch { load() }
    }

    private suspend fun load() {
        if (state !is LiveUiState.Success) state = LiveUiState.Loading
        try {
            val resp = ApiClient.create().live()
            state = LiveUiState.Success(resp, refreshIn = 30)
        } catch (e: Exception) {
            if (state !is LiveUiState.Success) {
                state = LiveUiState.Error(e.message ?: "Erreur réseau")
            }
        }
    }
}
