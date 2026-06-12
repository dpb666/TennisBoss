package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ValueComparison
import kotlinx.coroutines.Dispatchers
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
    ) : ValueUiState
    data class Error(val message: String) : ValueUiState
}

/** Charge les value bets (modèle vs marché + EV) via /api/value. */
class ValueViewModel : ViewModel() {

    var state by mutableStateOf<ValueUiState>(ValueUiState.Idle)
        private set

    fun load() {
        state = ValueUiState.Loading
        viewModelScope.launch {
            state = try {
                val resp = withContext(Dispatchers.IO) {
                    ApiClient.create().value(limit = 15)
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
}
