package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ComboLegRequest
import com.tennisboss.app.data.ComboRequest
import com.tennisboss.app.data.ComboResult
import kotlinx.coroutines.launch
import retrofit2.HttpException

/** Une leg saisie par l'utilisateur dans le Combo Builder (avant envoi à l'API). */
data class ComboLegInput(
    val player1: String = "",
    val player2: String = "",
    val side: String = "player1",   // "player1" | "player2"
    val market: String = "match",   // "match" | "set2" | "total_sets" | "handicap"
)

sealed interface ComboUiState {
    data object Idle : ComboUiState
    data object Loading : ComboUiState
    data class Success(val result: ComboResult) : ComboUiState
    data class Error(val message: String) : ComboUiState
}

/** Combine 2-4 pronostics déjà calculés via /api/bet-builder/combo — ne modifie
 * aucune logique de prédiction, purement de la combinaison (voir bot/api.py). */
class ComboBuilderViewModel : ViewModel() {

    var legs by mutableStateOf(listOf(ComboLegInput(), ComboLegInput()))
        private set

    var state by mutableStateOf<ComboUiState>(ComboUiState.Idle)
        private set

    fun updateLeg(index: Int, leg: ComboLegInput) {
        if (index !in legs.indices) return
        legs = legs.toMutableList().also { it[index] = leg }
    }

    fun addLeg() {
        if (legs.size < 4) legs = legs + ComboLegInput()
    }

    fun removeLeg(index: Int) {
        if (legs.size > 2 && index in legs.indices) {
            legs = legs.filterIndexed { i, _ -> i != index }
        }
    }

    fun canCalculate(): Boolean =
        legs.size in 2..4 && legs.all { it.player1.isNotBlank() && it.player2.isNotBlank() }

    fun calculate() {
        if (!canCalculate()) {
            state = ComboUiState.Error("Renseigne les 2 joueurs de chaque leg.")
            return
        }
        state = ComboUiState.Loading
        viewModelScope.launch {
            state = try {
                val request = ComboRequest(
                    legs = legs.map {
                        ComboLegRequest(
                            player1 = it.player1.trim(), player2 = it.player2.trim(),
                            side = it.side, market = it.market,
                        )
                    },
                )
                val result = ApiClient.create().betBuilderCombo(request)
                ComboUiState.Success(result)
            } catch (e: HttpException) {
                ComboUiState.Error(
                    when (e.code()) {
                        400 -> "2 à 4 legs requis, avec joueurs et côté valides."
                        422 -> "Prédiction impossible pour un des matchs (joueur inconnu ?)."
                        else -> "Erreur serveur (${e.code()})."
                    },
                )
            } catch (e: Exception) {
                ComboUiState.Error(e.message ?: "Erreur réseau inconnue.")
            }
        }
    }

    fun reset() {
        state = ComboUiState.Idle
    }
}
