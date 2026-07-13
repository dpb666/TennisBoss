package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.HistoryDatesResponse
import com.tennisboss.app.data.HistoryResponse
import com.tennisboss.app.ui.HistoryUiState
import com.tennisboss.app.ui.PerformanceUiState
import com.tennisboss.app.ui.PerformanceViewModel
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
class PerformanceViewModelTest {

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
    fun `load passe par Loading puis Success avec la calibration`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(calibrationResponse = CalibrationResponse(calibration_k = 1.05))
        val vm = PerformanceViewModel().apply { io = dispatcher }

        vm.load()
        assertEquals(PerformanceUiState.Loading, vm.state)

        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is PerformanceUiState.Success)
        assertEquals(1.05, (state as PerformanceUiState.Success).data.calibration_k, 0.0001)
    }

    @Test
    fun `load passe en Error si la calibration echoue`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("connexion perdue"))
        val vm = PerformanceViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is PerformanceUiState.Error)
        assertTrue((state as PerformanceUiState.Error).message.contains("connexion perdue"))
    }

    @Test
    fun `loadHistoryDates ne relance pas l'appel si deja charge`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            historyDatesResponse = HistoryDatesResponse(listOf("2026-07-12", "2026-07-11")),
        )
        val vm = PerformanceViewModel().apply { io = dispatcher }

        vm.loadHistoryDates()
        advanceUntilIdle()
        assertTrue(vm.historyState is HistoryUiState.Dates)

        // Un deuxieme appel avec une api qui plante confirmerait un re-fetch s'il avait lieu.
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("ne doit pas etre appele"))
        vm.loadHistoryDates()
        advanceUntilIdle()

        assertEquals(
            listOf("2026-07-12", "2026-07-11"),
            (vm.historyState as HistoryUiState.Dates).dates,
        )
    }

    @Test
    fun `selectDate charge l'historique du jour choisi`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            historyDatesResponse = HistoryDatesResponse(listOf("2026-07-12")),
            historyByDateResponse = HistoryResponse(date = "2026-07-12", count = 5, n_predicted = 5),
        )
        val vm = PerformanceViewModel().apply { io = dispatcher }
        vm.loadHistoryDates()
        advanceUntilIdle()

        vm.selectDate("2026-07-12")
        assertTrue(vm.historyState is HistoryUiState.DayLoading)
        advanceUntilIdle()

        val state = vm.historyState
        assertTrue(state is HistoryUiState.DaySuccess)
        assertEquals(5, (state as HistoryUiState.DaySuccess).history.count)
        assertEquals("2026-07-12", state.selectedDate)
    }
}
