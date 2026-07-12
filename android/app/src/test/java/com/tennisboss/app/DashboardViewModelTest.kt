package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.CalibMetrics
import com.tennisboss.app.data.CalibrationResponse
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
    fun `load gere l'erreur reseau`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("boom"))

        val vm = DashboardViewModel()
        advanceUntilIdle()

        assertTrue(vm.state is DashboardUiState.Error)
    }
}
