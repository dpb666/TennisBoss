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
import com.tennisboss.app.data.ValueComparison
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.util.Locale

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

    /** Cote combinée bookmaker saisie par l'utilisateur (analytique EV). */
    var bookComboOdds by mutableStateOf("")
        private set

    /** Bandeau éducatif parlay — dismissible pour la session (alignement tipsters). */
    var parlayBannerDismissed by mutableStateOf(false)
        private set

    fun dismissParlayBanner() {
        parlayBannerDismissed = true
    }

    fun updateBookComboOdds(value: String) {
        bookComboOdds = value
    }

    /** EV% affichable : priorité au calcul local (saisie live), sinon réponse API. */
    fun displayedEvPct(result: ComboResult): Double? {
        parseBookComboOdds(bookComboOdds)?.let { return computeComboEvPct(result.combined_probability_pct, it) }
        return result.ev_pct
    }

    /** Edge affichable (proba − implicite marché), même logique que displayedEvPct. */
    fun displayedEdge(result: ComboResult): Double? {
        parseBookComboOdds(bookComboOdds)?.let { return computeComboEdge(result.combined_probability_pct, it) }
        return result.edge
    }

    /** Pré-remplit une leg depuis un pick Value EV+ (marché match, côté best_side). */
    fun addLegFromValuePick(pick: ValueComparison) {
        val newLeg = pick.toComboLegInput()
        val emptyIndex = legs.indexOfFirst { it.player1.isBlank() || it.player2.isBlank() }
        legs = when {
            emptyIndex >= 0 -> legs.toMutableList().also { it[emptyIndex] = newLeg }
            legs.size < 4 -> legs + newLeg
            else -> legs.toMutableList().also { it[0] = newLeg }
        }
        state = ComboUiState.Idle
    }

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
                    book_odds = parseBookComboOdds(bookComboOdds),
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

/** Parse une cote décimale (> 1) depuis la saisie utilisateur. */
fun parseBookComboOdds(text: String): Double? {
    val value = text.replace(',', '.').trim().toDoubleOrNull() ?: return null
    return if (value > 1.0) value else null
}

/** EV analytique combo : (proba × cote − 1) × 100 — aligné bot/api.py _bet_builder. */
fun computeComboEvPct(combinedProbabilityPct: Double, bookOdds: Double): Double =
    (combinedProbabilityPct / 100.0 * bookOdds - 1.0) * 100.0

/** Edge vs marché : proba modèle − probabilité implicite (1/cote). */
fun computeComboEdge(combinedProbabilityPct: Double, bookOdds: Double): Double =
    combinedProbabilityPct / 100.0 - 1.0 / bookOdds

fun formatComboEvPct(evPct: Double): String =
    String.format(Locale.US, "%+.1f", evPct)

fun formatComboEdgePct(edge: Double): String =
    String.format(Locale.US, "%+.1f", edge * 100.0)

/** Mapping Value pick → leg combo (marché match, côté EV+). */
fun ValueComparison.toComboLegInput(): ComboLegInput {
    val side = when (best_side) {
        player1 -> "player1"
        player2 -> "player2"
        else -> if (ev1 >= ev2) "player1" else "player2"
    }
    return ComboLegInput(
        player1 = player1,
        player2 = player2,
        side = side,
        market = "match",
    )
}
