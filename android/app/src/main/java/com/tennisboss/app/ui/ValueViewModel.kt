package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ValueComparison
import com.tennisboss.app.data.ValueHistoryResponse
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.HttpException

sealed interface ValueUiState {
    data object Idle : ValueUiState
    data object Loading : ValueUiState
    data class Success(
        val comparisons: List<ValueComparison>,
        val rateLimited: Boolean = false,
        val retryInS: Int? = null,
        val rateLimitMessage: String = "",
        val refreshIn: Int = 300,
    ) : ValueUiState
    data class Error(val message: String) : ValueUiState
}

sealed interface ValueHistoryUiState {
    data object Idle : ValueHistoryUiState
    data object Loading : ValueHistoryUiState
    data class Success(val data: ValueHistoryResponse) : ValueHistoryUiState
    data class Error(val message: String) : ValueHistoryUiState
}

/** Charge les value bets (modèle vs marché + EV) via /api/value. */
class ValueViewModel : ViewModel() {

    var state by mutableStateOf<ValueUiState>(ValueUiState.Idle)
        private set

    var historyState by mutableStateOf<ValueHistoryUiState>(ValueHistoryUiState.Idle)
        private set

    var highConfidenceOnly by mutableStateOf(true)

    // Dispatcher IO injectable (pour des tests déterministes) — même pattern
    // que UpcomingViewModel.io.
    internal var io: CoroutineDispatcher = Dispatchers.IO

    private var autoRefreshJob: kotlinx.coroutines.Job? = null

    fun startAutoRefresh() {
        if (autoRefreshJob?.isActive == true) return
        autoRefreshJob = viewModelScope.launch {
            while (isActive) {
                load()
                var countdown = 300
                while (isActive && countdown > 0) {
                    delay(1000)
                    countdown--
                    val current = state
                    if (current is ValueUiState.Success) {
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

    fun load() {
        state = ValueUiState.Loading
        viewModelScope.launch {
            state = try {
                val resp = withContext(io) {
                    ApiClient.create().value(limit = 20)
                }
                ValueUiState.Success(
                    comparisons = resp.comparisons,
                    rateLimited = resp.rate_limited,
                    retryInS = resp.retry_in_s,
                    rateLimitMessage = resp.message,
                )
            } catch (e: HttpException) {
                when (e.code()) {
                    503 -> ValueUiState.Error("Cotes indisponibles : clé ODDS_API absente côté serveur.")
                    429 -> ValueUiState.Error("Service rate-limité. Cotes réessayées automatiquement.")
                    else -> ValueUiState.Error("Erreur serveur (HTTP ${e.code()}).")
                }
            } catch (e: Exception) {
                ValueUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }

    fun loadHistory() {
        if (historyState is ValueHistoryUiState.Loading) return
        historyState = ValueHistoryUiState.Loading
        viewModelScope.launch {
            historyState = try {
                val resp = withContext(io) {
                    ApiClient.create().valueHistory(limit = 50)
                }
                ValueHistoryUiState.Success(resp)
            } catch (e: Exception) {
                ValueHistoryUiState.Error("Historique indisponible : ${e.message}")
            }
        }
    }
}
