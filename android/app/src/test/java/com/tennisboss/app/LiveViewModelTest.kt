package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.LiveMatch
import com.tennisboss.app.data.LivePrediction
import com.tennisboss.app.data.LiveResponse
import com.tennisboss.app.ui.LiveUiState
import com.tennisboss.app.ui.LiveViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * `LiveViewModel.load()` est privé — on passe par [LiveViewModel.loadOnce] (utilisé
 * par l'écran) pour l'exercer. inplayBest/inplayMarkets/inplayPicks ne sont pas
 * fournis par [FakeApi] ici : LiveViewModel les avale individuellement en cas
 * d'erreur (design existant, voir load() — `catch (e: Exception) { null }`),
 * donc un FakeApi qui ne les implémente pas (NotImplementedError) est le cas
 * réaliste à tester, pas un cas dégradé artificiel.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LiveViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
        ApiClient.apiOverride = null
    }

    private fun match(eventId: Long, favorite: String?) = LiveMatch(
        event_id = eventId,
        player1 = "Djokovic",
        player2 = "Alcaraz",
        prediction = LivePrediction(player1 = "Djokovic", player2 = "Alcaraz", favorite = favorite),
    )

    @Test
    fun `loadOnce renvoie Success avec les matchs live et sans pick ni marches`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            liveResponse = LiveResponse(count = 1, matches = listOf(match(1L, "Djokovic"))),
        )
        val vm = LiveViewModel()

        vm.loadOnce()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is LiveUiState.Success)
        s as LiveUiState.Success
        assertEquals(1, s.data.matches.size)
        // inplayBest/Markets/Picks non fournis par FakeApi -> avalés individuellement.
        assertEquals(null, s.bestPick)
        assertTrue(s.swungEventIds.isEmpty())
    }

    @Test
    fun `un changement de favori entre deux chargements est detecte comme bascule`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            liveResponse = LiveResponse(count = 1, matches = listOf(match(1L, "Djokovic"))),
        )
        val vm = LiveViewModel()
        vm.loadOnce()
        advanceUntilIdle()
        assertTrue((vm.state as LiveUiState.Success).swungEventIds.isEmpty())

        // Le favori du même match (event_id=1) change entre les deux chargements.
        ApiClient.apiOverride = FakeApi(
            liveResponse = LiveResponse(count = 1, matches = listOf(match(1L, "Alcaraz"))),
        )
        vm.loadOnce()
        advanceUntilIdle()

        val s = vm.state as LiveUiState.Success
        assertEquals(setOf(1L), s.swungEventIds)
    }
}
