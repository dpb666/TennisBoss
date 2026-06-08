package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.Prediction
import com.tennisboss.app.data.UpcomingMatch
import com.tennisboss.app.data.UpcomingResponse
import com.tennisboss.app.ui.UpcomingUiState
import com.tennisboss.app.ui.UpcomingViewModel
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

@OptIn(ExperimentalCoroutinesApi::class)
class UpcomingViewModelTest {

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

    private fun match(tag: String, p1: Double) = UpcomingMatch(
        player1_raw = "a", player2_raw = "b", tournament = tag, round = "",
        date = "", time = "", live = false, tour = "atp", predictable = true,
        prediction = Prediction("a", "b", p1, 100.0 - p1, "a"),
    )

    @Test
    fun `load renvoie Success trie par favori`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            upcomingResponse = UpcomingResponse(2, listOf(match("Faible", 55.0), match("Fort", 82.0))),
        )
        val vm = UpcomingViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is UpcomingUiState.Success)
        s as UpcomingUiState.Success
        assertEquals("Fort", s.matches.first().tournament)
    }

    @Test
    fun `load gere l'erreur reseau`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("boom"))
        val vm = UpcomingViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        assertTrue(vm.state is UpcomingUiState.Error)
    }
}
