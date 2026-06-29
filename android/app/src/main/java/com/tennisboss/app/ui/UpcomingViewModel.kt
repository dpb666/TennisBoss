package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.UpcomingMatch
import kotlinx.coroutines.CoroutineDispatcher
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

/**
 * Trie les matchs pour la décision : les plus prédictibles d'abord (proba du
 * favori la plus haute), les matchs sans prédiction (joueur inconnu) à la fin.
 * Fonction pure -> testable sans Android.
 */
fun sortUpcoming(matches: List<UpcomingMatch>): List<UpcomingMatch> =
    matches.sortedWith(compareBy(
        { it.date },
        { it.time.ifBlank { "99:99" } },  // matchs sans heure → fin de journée
    ))

class UpcomingViewModel : ViewModel() {

    var days by mutableStateOf(3)
    var withOdds by mutableStateOf(true)
    var highConfidenceOnly by mutableStateOf(true)

    // Dispatcher IO injectable (pour des tests déterministes).
    internal var io: CoroutineDispatcher = Dispatchers.IO

    var state by mutableStateOf<UpcomingUiState>(UpcomingUiState.Idle)
        private set

    fun load() {
        state = UpcomingUiState.Loading
        viewModelScope.launch {
            state = try {
                val resp = withContext(io) {
                    ApiClient.create().upcoming(days = days, limit = 60, odds = withOdds)
                }
                UpcomingUiState.Success(sortUpcoming(resp.matches))
            } catch (e: HttpException) {
                when (e.code()) {
                    429 -> UpcomingUiState.Error("Cotes rate-limitées. Cache disponible si rechargement.")
                    else -> UpcomingUiState.Error("Erreur serveur (HTTP ${e.code()}).")
                }
            } catch (e: Exception) {
                UpcomingUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }
}
