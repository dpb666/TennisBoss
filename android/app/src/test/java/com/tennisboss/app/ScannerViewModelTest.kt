package com.tennisboss.app

import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.ScannerStatus
import com.tennisboss.app.ui.ScannerUiState
import com.tennisboss.app.ui.ScannerViewModel
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
class ScannerViewModelTest {

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
    fun `load passe par Loading puis Success avec le statut du scanner`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            scannerStatusResponse = ScannerStatus(running = true, checked = 42, next_cycle_ts = null),
        )
        val vm = ScannerViewModel().apply { io = dispatcher }

        vm.load()
        assertEquals(ScannerUiState.Loading, vm.state)
        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is ScannerUiState.Success)
        assertEquals(42, (state as ScannerUiState.Success).data.checked)
    }

    @Test
    fun `sans next_cycle_ts le compte a rebours reste null`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(
            scannerStatusResponse = ScannerStatus(running = true, next_cycle_ts = null),
        )
        val vm = ScannerViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        assertEquals(null, vm.secondsToNext)
    }

    @Test
    fun `un next_cycle_ts deja passe fait retomber le compte a rebours a 0`() = runTest(dispatcher) {
        // Timestamp dans le passe : startCountdown doit constater diff <= 0 des le
        // premier tick et sortir de la boucle sans jamais attendre en temps reel.
        ApiClient.apiOverride = FakeApi(
            scannerStatusResponse = ScannerStatus(running = true, next_cycle_ts = "2020-01-01T00:00:00Z"),
        )
        val vm = ScannerViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        assertEquals(0, vm.secondsToNext)
    }

    @Test
    fun `load passe en Error si l'appel echoue`() = runTest(dispatcher) {
        ApiClient.apiOverride = FakeApi(throwError = RuntimeException("scanner indisponible"))
        val vm = ScannerViewModel().apply { io = dispatcher }

        vm.load()
        advanceUntilIdle()

        val state = vm.state
        assertTrue(state is ScannerUiState.Error)
        assertTrue((state as ScannerUiState.Error).message.contains("scanner indisponible"))
    }
}
