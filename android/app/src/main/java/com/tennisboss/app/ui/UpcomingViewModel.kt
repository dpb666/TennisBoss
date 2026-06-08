package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.UpcomingMatch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.HttpException

/** État de l'écran des matchs à venir. */
sealed interface UpcomingUiState {
    data object Idle : UpcomingUiState
    data object Loading : UpcomingUiState
    data class Success(val matches: List<UpcomingMatch>) : UpcomingUiState
    data class Error(val message: String) : UpcomingUiState
}

class UpcomingViewModel : ViewModel() {

    var days by mutableStateOf(2)
    var withOdds by mutableStateOf(true)

    var state by mutableStateOf<UpcomingUiState>(UpcomingUiState.Idle)
        private set

    fun load() {
        state = UpcomingUiState.Loading
        viewModelScope.launch {
            state = try {
                val resp = withContext(Dispatchers.IO) {
                    ApiClient.create().upcoming(days = days, limit = 40, odds = withOdds)
                }
                UpcomingUiState.Success(resp.matches)
            } catch (e: HttpException) {
                UpcomingUiState.Error("Erreur serveur (HTTP ${e.code()}).")
            } catch (e: Exception) {
                UpcomingUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }
}
