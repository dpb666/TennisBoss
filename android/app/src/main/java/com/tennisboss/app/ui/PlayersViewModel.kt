package com.tennisboss.app.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.Player
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Recherche de joueurs avec autocomplete (appel débouncé à /api/players). */
class PlayersViewModel : ViewModel() {

    var query by mutableStateOf("")
        private set
    var players by mutableStateOf<List<Player>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    private var searchJob: Job? = null

    fun onQueryChange(q: String) {
        query = q
        searchJob?.cancel()
        if (q.isBlank()) {
            players = emptyList()
            error = null
            loading = false
            return
        }
        searchJob = viewModelScope.launch {
            delay(300)              // debounce : on attend une pause de frappe
            loading = true
            error = null
            try {
                val resp = withContext(Dispatchers.IO) {
                    ApiClient.create().players(q = q.trim(), limit = 30)
                }
                players = resp.players
            } catch (e: Exception) {
                error = "Recherche impossible : ${e.message}"
                players = emptyList()
            } finally {
                loading = false
            }
        }
    }
}
