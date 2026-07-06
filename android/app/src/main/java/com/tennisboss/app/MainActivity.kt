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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.TokenManager
import com.tennisboss.app.ui.ChatScreen
import com.tennisboss.app.ui.ChatViewModel
import com.tennisboss.app.ui.EdgeScreen
import com.tennisboss.app.ui.LiveScreen
import com.tennisboss.app.ui.LiveViewModel
import com.tennisboss.app.ui.PerformanceScreen
import com.tennisboss.app.ui.PlayerCompareViewModel
import com.tennisboss.app.ui.PlayersScreen
import com.tennisboss.app.ui.PredictScreen
import com.tennisboss.app.ui.PredictViewModel
import com.tennisboss.app.notifications.PickNotificationHelper
import com.tennisboss.app.notifications.ScannerPollWorker
import com.tennisboss.app.ui.ScannerScreen
import com.tennisboss.app.ui.UpcomingScreen
import com.tennisboss.app.ui.ValueScreen
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

        // Worker périodique : poll scanner toutes les 15min
        val pollRequest = PeriodicWorkRequestBuilder<ScannerPollWorker>(15, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            ScannerPollWorker.WORK_NAME,
            ExistingPeriodicWorkPolicy.KEEP,
            pollRequest,
        )

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
                val tabs = listOf(
                    Triple(0, "🎯", "Prédire"),
                    Triple(1, "📅", "Matchs"),
                    Triple(2, "👤", "Joueurs"),
                    Triple(3, "💎", "Value"),
                    Triple(4, "📊", "Perf"),
                    Triple(5, "🔴", "Live"),
                    Triple(6, "💰", "Edge"),
                    Triple(7, "🔍", "Scan"),
                    Triple(8, "🤖", "Chat"),
                )
                tabs.forEach { (idx, icon, label) ->
                    NavigationBarItem(
                        selected = tab == idx,
                        onClick = { tab = idx },
                        icon = { Text(icon, fontSize = 16.sp) },
                        label = { Text(label, fontSize = 9.sp, maxLines = 1) },
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
                    0 -> PredictScreen(predictVM)
                    1 -> UpcomingScreen()
                    2 -> PlayersScreen(
                        selectedP1 = predictVM.player1,
                        selectedP2 = predictVM.player2,
                        onPlayerClick = { name ->
                            val pairComplete = predictVM.pick(name)
                            if (pairComplete) tab = 0
                        },
                        vm = compareVM,
                    )
                    3 -> ValueScreen()
                    4 -> PerformanceScreen()
                    5 -> LiveScreen(liveVM)
                    6 -> EdgeScreen()
                    7 -> ScannerScreen()
                    else -> ChatScreen(chatVM)
                }
            }
        }
    }
}
