package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.FollowedPlayersResponse
import com.tennisboss.app.data.UpcomingResponse
import com.tennisboss.app.data.ValueResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

sealed interface DashboardUiState {
    object Loading : DashboardUiState
    data class Success(
        val upcoming: UpcomingResponse,
        val value: ValueResponse,
        val calibration: CalibrationResponse,
        // Best-effort (voir load()) : un pépin sur ces 2 appels ne doit pas
        // empêcher le reste du Dashboard de s'afficher.
        val clv: ClvResponse? = null,
        val followed: FollowedPlayersResponse? = null,
    ) : DashboardUiState
    data class Error(val message: String) : DashboardUiState
}

class DashboardViewModel : ViewModel() {
    var state by mutableStateOf<DashboardUiState>(DashboardUiState.Loading)
        private set

    init {
        load()
    }

    fun load() {
        state = DashboardUiState.Loading
        viewModelScope.launch {
            // coroutineScope{} (pas juste le launch englobant) : si un des 3 appels
            // échoue, l'exception doit ressortir par un vrai `throw` au point d'appel
            // pour être interceptée par le catch ci-dessous. Avec des async{} lancés
            // directement sur le scope du launch, l'échec peut annuler le parent
            // avant que .await() ne soit atteint et court-circuiter le catch,
            // laissant l'écran bloqué en Loading au lieu d'afficher une erreur.
            state = try {
                coroutineScope {
                    val api = ApiClient.create()
                    val upcomingDeferred = async { api.upcoming(days = 1, limit = 5) }
                    val valueDeferred = async { api.value(limit = 5) }
                    val calibrationDeferred = async { api.calibration() }
                    // Best-effort : CLV a besoin de picks réglés pour être significatif,
                    // et les favoris peuvent être vides — ni l'un ni l'autre ne doit
                    // faire échouer tout le Dashboard (même pattern que h2h dans
                    // MatchDetailViewModel).
                    val clvDeferred = async { try { api.clv() } catch (e: Exception) { null } }
                    val followedDeferred = async { try { api.followedPlayers() } catch (e: Exception) { null } }

                    DashboardUiState.Success(
                        upcoming = upcomingDeferred.await(),
                        value = valueDeferred.await(),
                        calibration = calibrationDeferred.await(),
                        clv = clvDeferred.await(),
                        followed = followedDeferred.await(),
                    )
                }
            } catch (e: Exception) {
                DashboardUiState.Error(e.message ?: "Erreur de chargement")
            }
        }
    }
}
