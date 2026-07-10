package com.tennisboss.app

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Diamond
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.outlined.Diamond
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.sp
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.TokenManager
import com.tennisboss.app.ui.ChatScreen
import com.tennisboss.app.ui.ChatViewModel
import com.tennisboss.app.ui.LiveViewModel
import com.tennisboss.app.ui.MatchesGroupScreen
import com.tennisboss.app.ui.PerfGroupScreen
import com.tennisboss.app.ui.PlayerCompareViewModel
import com.tennisboss.app.ui.PredictGroupScreen
import com.tennisboss.app.ui.PredictViewModel
import com.tennisboss.app.ui.ValueGroupScreen
import com.tennisboss.app.notifications.PickNotificationHelper
import com.tennisboss.app.notifications.LiveProbPollWorker
import com.tennisboss.app.notifications.ScannerPollWorker
import com.tennisboss.app.ui.theme.TennisBossTheme

class MainActivity : ComponentActivity() {

    private val requestNotifPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* accordée ou refusée — silencieux */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Notification channel (Android 8+)
        PickNotificationHelper.createChannel(this)

        // Demande permission POST_NOTIFICATIONS (Android 13+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestNotifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        // Worker périodique : poll scanner toutes les 15min. enqueueUniquePeriodicWork
        // écrit dans la DB Room de WorkManager (I/O disque) — hors thread principal pour
        // éviter un ANR au lancement à froid (constaté : "No response to onStartJob").
        lifecycleScope.launch(Dispatchers.Default) {
            val pollRequest = PeriodicWorkRequestBuilder<ScannerPollWorker>(15, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(this@MainActivity).enqueueUniquePeriodicWork(
                ScannerPollWorker.WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                pollRequest,
            )
            val liveProbRequest = PeriodicWorkRequestBuilder<LiveProbPollWorker>(15, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(this@MainActivity).enqueueUniquePeriodicWork(
                LiveProbPollWorker.WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                liveProbRequest,
            )
        }

        setContent {
            TennisBossTheme {
                AppRoot()
            }
        }
    }
}

@Composable
fun AppRoot() {
    var tab by remember { mutableIntStateOf(0) }
    // ViewModel de prédiction partagé : la recherche joueurs peut le pré-remplir.
    val predictVM: PredictViewModel = viewModel()
    val compareVM: PlayerCompareViewModel = viewModel()
    val chatVM: ChatViewModel = viewModel()
    val liveVM: LiveViewModel = viewModel()

    // Le token est chargé depuis TokenManager (variables de build ou stockage chiffré).
    // baseUrl est déjà auto-détecté (localhost:8000 émulateur, ngrok sinon).
    val context = LocalContext.current
    LaunchedEffect(Unit) {
        TokenManager.initialize(context)
    }

    Scaffold(
        bottomBar = {
            NavigationBar {
                data class NavTab(val index: Int, val label: String, val filled: ImageVector, val outlined: ImageVector)
                val tabs = listOf(
                    NavTab(0, "Prédire", Icons.Filled.Insights, Icons.Outlined.Insights),
                    NavTab(1, "Matchs", Icons.Filled.CalendarMonth, Icons.Outlined.CalendarMonth),
                    NavTab(2, "Value", Icons.Filled.Diamond, Icons.Outlined.Diamond),
                    NavTab(3, "Perf", Icons.Filled.BarChart, Icons.Outlined.BarChart),
                    NavTab(4, "Chat", Icons.Filled.SmartToy, Icons.Outlined.SmartToy),
                )
                tabs.forEach { t ->
                    val selected = tab == t.index
                    NavigationBarItem(
                        selected = selected,
                        onClick = { tab = t.index },
                        icon = {
                            Icon(
                                imageVector = if (selected) t.filled else t.outlined,
                                contentDescription = t.label,
                            )
                        },
                        label = { Text(t.label, fontSize = 9.sp, maxLines = 1) },
                    )
                }
            }
        },
    ) { padding ->
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            AnimatedContent(
                targetState = tab,
                transitionSpec = {
                    (fadeIn(tween(260)) +
                        slideInVertically(tween(260)) { it / 16 }) togetherWith
                        fadeOut(tween(180))
                },
                label = "tabs",
            ) { current ->
                when (current) {
                    0 -> PredictGroupScreen(predictVM, compareVM)
                    1 -> MatchesGroupScreen(liveVM)
                    2 -> ValueGroupScreen()
                    3 -> PerfGroupScreen()
                    else -> ChatScreen(chatVM)
                }
            }
        }
    }
}
