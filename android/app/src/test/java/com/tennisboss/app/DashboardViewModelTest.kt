package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.CalibMetrics
import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.ClvAgg
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.FollowedPlayersResponse
import com.tennisboss.app.data.Player
import com.tennisboss.app.data.UpcomingResponse
import com.tennisboss.app.data.ValueResponse
import com.tennisboss.app.ui.DashboardUiState
import com.tennisboss.app.ui.DashboardViewModel
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
class DashboardViewModelTest {

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
    fun `load combine upcoming, value et calibration en Success`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            upcomingResponse = UpcomingResponse(0, emptyList()),
            valueResponse = ValueResponse(0, emptyList()),
            calibrationResponse = CalibrationResponse(metrics = CalibMetrics(n = 42, accuracy = 0.65)),
        )

        val vm = DashboardViewModel()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is DashboardUiState.Success)
        s as DashboardUiState.Success
        assertEquals(42, s.calibration.metrics.n)
    }

    @Test
    fun `load reste en Success meme si CLV et favoris echouent`() = runTest(dispatcher) {
        // CLV et favoris sont best-effort (voir DashboardViewModel.load()) : un
        // echec dessus ne doit pas faire basculer tout le Dashboard en Error.
        ApiClient.apiOverride = FakeApi(
            upcomingResponse = UpcomingResponse(0, emptyList()),
            valueResponse = ValueResponse(0, emptyList()),
            calibrationResponse = CalibrationResponse(),
            // clvResponse et followedPlayersResponse volontairement absents :
            // FakeApi les fait echouer avec RuntimeException (best-effort).
        )

        val vm = DashboardViewModel()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is DashboardUiState.Success)
        s as DashboardUiState.Success
        assertEquals(null, s.clv)
        assertEquals(null, s.followed)
    }

    @Test
    fun `load expose CLV et joueurs suivis quand disponibles`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            upcomingResponse = UpcomingResponse(0, emptyList()),
            valueResponse = ValueResponse(0, emptyList()),
            calibrationResponse = CalibrationResponse(),
            clvResponse = ClvResponse(global = ClvAgg(n_clv = 12, avg_clv_pct = 3.4)),
            followedPlayersResponse = FollowedPlayersResponse(
                count = 1, players = listOf(Player(name = "Jannik Sinner")),
            ),
        )

        val vm = DashboardViewModel()
        advanceUntilIdle()

        val s = vm.state
        assertTrue(s is DashboardUiState.Success)
        s as DashboardUiState.Success
        assertEquals(12, s.clv?.global?.n_clv)
        assertEquals("Jannik Sinner", s.followed?.players?.first()?.name)
    }

    @Test
    fun `load gere l'erreur reseau`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("boom"))

        val vm = DashboardViewModel()
        advanceUntilIdle()

        assertTrue(vm.state is DashboardUiState.Error)
    }
}
