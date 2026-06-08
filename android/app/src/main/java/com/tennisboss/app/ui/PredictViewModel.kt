package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.PredictResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.HttpException

/** État de l'écran de prédiction. */
sealed interface PredictUiState {
    data object Idle : PredictUiState
    data object Loading : PredictUiState
    data class Success(val data: PredictResponse) : PredictUiState
    data class Error(val message: String) : PredictUiState
}

class PredictViewModel : ViewModel() {

    var player1 by mutableStateOf("Iga Swiatek")
    var player2 by mutableStateOf("Aryna Sabalenka")

    var state by mutableStateOf<PredictUiState>(PredictUiState.Idle)
        private set

    fun predict() {
        if (player1.isBlank() || player2.isBlank()) {
            state = PredictUiState.Error("Entrez deux joueurs.")
            return
        }
        state = PredictUiState.Loading
        viewModelScope.launch {
            state = try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient.create().predict(player1.trim(), player2.trim())
                }
                PredictUiState.Success(response)
            } catch (e: HttpException) {
                PredictUiState.Error(
                    when (e.code()) {
                        404 -> "Joueur inconnu en base."
                        401 -> "Token API requis ou invalide."
                        else -> "Erreur serveur (HTTP ${e.code()})."
                    }
                )
            } catch (e: Exception) {
                PredictUiState.Error("Connexion impossible : ${e.message}")
            }
        }
    }
}
