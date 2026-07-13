package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.Player
import com.tennisboss.app.data.PlayerDetail
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class CompareState(
    val p1: PlayerDetail? = null,
    val p2: PlayerDetail? = null,
    val h2h: H2H? = null,
    val loading: Boolean = false,
    val error: String? = null,
)

class PlayerCompareViewModel : ViewModel() {

    // Overridable en test pour piloter le dispatcher IO avec le TestDispatcher,
    // comme UpcomingViewModel.io / ValueViewModel.io.
    internal var io: CoroutineDispatcher = Dispatchers.IO

    // ── Recherche A ───────────────────────────────────────────────────────────
    var queryA by mutableStateOf("")
        private set
    var resultsA by mutableStateOf<List<Player>>(emptyList())
        private set
    var loadingA by mutableStateOf(false)
        private set
    var selectedA by mutableStateOf<String?>(null)
        private set

    // ── Recherche B ───────────────────────────────────────────────────────────
    var queryB by mutableStateOf("")
        private set
    var resultsB by mutableStateOf<List<Player>>(emptyList())
        private set
    var loadingB by mutableStateOf(false)
        private set
    var selectedB by mutableStateOf<String?>(null)
        private set

    // ── Comparaison ───────────────────────────────────────────────────────────
    var compare by mutableStateOf(CompareState())
        private set

    private var jobA: Job? = null
    private var jobB: Job? = null

    fun onQueryA(q: String) {
        queryA = q
        if (q.isBlank()) { resultsA = emptyList(); return }
        jobA?.cancel()
        jobA = viewModelScope.launch {
            delay(280)
            loadingA = true
            try {
                resultsA = withContext(io) {
                    ApiClient.create().players(q = q.trim(), limit = 20).players
                }
            } catch (_: Exception) { resultsA = emptyList() }
            loadingA = false
        }
    }

    fun onQueryB(q: String) {
        queryB = q
        if (q.isBlank()) { resultsB = emptyList(); return }
        jobB?.cancel()
        jobB = viewModelScope.launch {
            delay(280)
            loadingB = true
            try {
                resultsB = withContext(io) {
                    ApiClient.create().players(q = q.trim(), limit = 20).players
                }
            } catch (_: Exception) { resultsB = emptyList() }
            loadingB = false
        }
    }

    fun selectA(name: String) {
        selectedA = name
        queryA = name
        resultsA = emptyList()
        loadCompare()
    }

    fun selectB(name: String) {
        selectedB = name
        queryB = name
        resultsB = emptyList()
        loadCompare()
    }

    fun clearA() { selectedA = null; queryA = ""; resultsA = emptyList(); compare = CompareState() }
    fun clearB() { selectedB = null; queryB = ""; resultsB = emptyList(); compare = compare.copy(p2 = null, h2h = null) }

    private fun loadCompare() {
        val a = selectedA ?: return
        val b = selectedB
        compare = compare.copy(loading = true, error = null)
        viewModelScope.launch {
            try {
                val api = ApiClient.create()
                val p1 = withContext(io) { api.player(name = a) }
                compare = compare.copy(p1 = p1)
                if (b != null) {
                    val p2 = withContext(io) { api.player(name = b) }
                    val h2h = try { withContext(io) { api.h2h(p1 = a, p2 = b) } }
                              catch (_: Exception) { null }
                    compare = compare.copy(p2 = p2, h2h = h2h)
                }
            } catch (e: Exception) {
                compare = compare.copy(error = "Erreur : ${e.message}")
            } finally {
                compare = compare.copy(loading = false)
            }
        }
    }
}
