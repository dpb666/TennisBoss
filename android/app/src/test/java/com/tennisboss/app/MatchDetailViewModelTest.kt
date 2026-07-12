package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.H2H
import com.tennisboss.app.data.InsightResponse
import com.tennisboss.app.data.PlayerDetail
import com.tennisboss.app.ui.MatchDetailUiState
import com.tennisboss.app.ui.MatchDetailViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class MatchDetailViewModelTest {

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

    @Test
    fun `loadMatchDetail combine joueurs, insight et h2h en Success`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf(
                "Sinner" to PlayerDetail(name = "Sinner", rating = 2100.0),
                "Alcaraz" to PlayerDetail(name = "Alcaraz", rating = 2080.0),
            ),
            insightResponse = InsightResponse(player1 = "Sinner", player2 = "Alcaraz"),
            h2hResponse = H2H(player1 = "Sinner", player2 = "Alcaraz", wins1 = 3, wins2 = 2, total = 5),
        )

        val vm = MatchDetailViewModel()
        vm.loadMatchDetail("Sinner", "Alcaraz")
        advanceUntilIdle()

        val s = vm.uiState
        assertTrue(s is MatchDetailUiState.Success)
        s as MatchDetailUiState.Success
        assertEquals("Sinner", s.player1.name)
        assertEquals("Alcaraz", s.player2.name)
        assertEquals(5, s.h2h?.total)
    }

    @Test
    fun `loadMatchDetail reste en Success meme si le H2H echoue`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            playerResponses = mapOf(
                "Sinner" to PlayerDetail(name = "Sinner", rating = 2100.0),
                "Alcaraz" to PlayerDetail(name = "Alcaraz", rating = 2080.0),
            ),
            insightResponse = InsightResponse(player1 = "Sinner", player2 = "Alcaraz"),
            // h2hResponse absent : FakeApi.h2h() lève, capturé en best-effort par le VM.
        )

        val vm = MatchDetailViewModel()
        vm.loadMatchDetail("Sinner", "Alcaraz")
        advanceUntilIdle()

        val s = vm.uiState
        assertTrue(s is MatchDetailUiState.Success)
        s as MatchDetailUiState.Success
        assertNull(s.h2h)
    }

    @Test
    fun `loadMatchDetail gere l'erreur reseau`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("boom"))

        val vm = MatchDetailViewModel()
        vm.loadMatchDetail("Sinner", "Alcaraz")
        advanceUntilIdle()

        assertTrue(vm.uiState is MatchDetailUiState.Error)
    }
}
