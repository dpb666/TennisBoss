package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.IntelligenceStats
import com.tennisboss.app.data.LearnerStats
import com.tennisboss.app.ui.EdgeUiState
import com.tennisboss.app.ui.EdgeViewModel
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
class EdgeViewModelTest {

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
    fun `load combine clv, intelligence et learner en un seul etat Success`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            clvResponse = ClvResponse(verdict = "positif"),
            intelligenceStatsResponse = IntelligenceStats(accuracy_drift_pts = 2.5),
            learnerStatsResponse = LearnerStats(n_zones = 3),
        )
        val vm = EdgeViewModel().apply { io = dispatcher }

        vm.load()
        assertEquals(EdgeUiState.Loading, vm.state)
        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is EdgeUiState.Success)
        val data = (state as EdgeUiState.Success).data
        assertEquals("positif", data.clv.verdict)
        assertEquals(2.5, data.intelligence.accuracy_drift_pts, 0.0001)
        assertEquals(3, data.learner.n_zones)
    }

    @Test
    fun `intelligence et learner en echec retombent sur des valeurs par defaut sans faire echouer l'ecran`() =
        runTest(dispatcher) {
            // intelligenceStatsResponse / learnerStatsResponse non fournis -> FakeApi leve
            // RuntimeException, rattrapee en interne par EdgeViewModel (best-effort).
            ApiClient.apiOverride = FakeApi(clvResponse = ClvResponse(verdict = "insuffisant"))
            val vm = EdgeViewModel().apply { io = dispatcher }

            vm.load()
            advanceUntilIdle()

            val state = vm.state
            assertTrue(state is EdgeUiState.Success)
            val data = (state as EdgeUiState.Success).data
            assertEquals("insuffisant", data.clv.verdict)
            assertEquals(IntelligenceStats(), data.intelligence)
            assertEquals(LearnerStats(), data.learner)
        }

    @Test
    fun `un echec du CLV fait passer l'ecran entier en Error`() = runTest(dispatcher) {
        // clvResponse non fourni -> FakeApi.clv() leve RuntimeException("non utilisé"),
        // qui n'est PAS rattrapee par EdgeViewModel (contrairement a intelligence/learner).
        ApiClient.apiOverride = FakeApi()
        val vm = EdgeViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is EdgeUiState.Error)
        assertTrue((state as EdgeUiState.Error).message.contains("non utilisé"))
    }
}
