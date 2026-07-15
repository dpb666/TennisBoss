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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.sp
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.TokenManager
import com.tennisboss.app.ui.DashboardScreen
import com.tennisboss.app.ui.DashboardViewModel
import com.tennisboss.app.ui.MatchDetailScreen
import com.tennisboss.app.ui.MatchDetailViewModel
import com.tennisboss.app.ui.ChatScreen
import com.tennisboss.app.ui.ChatViewModel
import com.tennisboss.app.ui.LiveViewModel
import com.tennisboss.app.ui.MatchesGroupScreen
import com.tennisboss.app.ui.PlayerCompareViewModel
import com.tennisboss.app.ui.PredictGroupScreen
import com.tennisboss.app.ui.PredictViewModel
import com.tennisboss.app.ui.ValueGroupScreen
import com.tennisboss.app.notifications.PickNotificationHelper
import com.tennisboss.app.notifications.LiveProbPollWorker
import com.tennisboss.app.notifications.ScannerPollWorker
import com.tennisboss.app.ui.theme.TennisBossTheme
import com.google.firebase.messaging.FirebaseMessaging
import com.tennisboss.app.data.DeviceRegisterRequest
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.outlined.Home

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

        // Doit s'exécuter avant setContent{} : TokenManager.initialize() est synchrone
        // (pas de suspend), donc appelé ici ApiClient.apiToken est déjà renseigné avant
        // la toute première composition — et donc avant que les ViewModel (dont
        // DashboardViewModel, qui lance son 1er appel API dans son init{}) ne soient
        // construits. Un appel équivalent dans un LaunchedEffect(Unit) de AppRoot()
        // arrive trop tard : la coroutine du LaunchedEffect ne démarre qu'après la
        // composition initiale, donc après DashboardViewModel.init{} — le tout premier
        // appel API partait avec un token vide -> 401 (constaté sur émulateur).
        TokenManager.initialize(this)

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
    var selectedMatch by remember { mutableStateOf<Triple<String, String, String?>?>(null) }
    
    val dashboardVM: DashboardViewModel = viewModel()
    val predictVM: PredictViewModel = viewModel()
    val compareVM: PlayerCompareViewModel = viewModel()
    val detailVM: MatchDetailViewModel = viewModel()
    val chatVM: ChatViewModel = viewModel()
    val liveVM: LiveViewModel = viewModel()

    // Le token est chargé dans MainActivity.onCreate() (avant setContent{}), pour être
    // déjà en place lorsque les ViewModel se construisent — voir le commentaire là-bas.
    // baseUrl est déjà auto-détecté (10.0.2.2:8000 émulateur, Worker sinon).
    LaunchedEffect(Unit) {
        // Ré-enregistre le token FCM à chaque démarrage : couvre le cas où le
        // token existait déjà avant l'ajout de cette fonctionnalité (onNewToken
        // ne se redéclenche pas pour un token inchangé), et rattrape un échec
        // silencieux de TennisBossMessagingService.onNewToken.
        FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
            android.util.Log.d("TennisBossFCM", "Token obtenu: $token")
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    ApiClient.create().registerDevice(DeviceRegisterRequest(token = token))
                    android.util.Log.d("TennisBossFCM", "Enregistré côté backend OK")
                } catch (e: Exception) {
                    android.util.Log.e("TennisBossFCM", "Échec enregistrement backend", e)
                }
            }
        }.addOnFailureListener { e ->
            android.util.Log.e("TennisBossFCM", "Échec obtention token FCM", e)
        }
    }

    Scaffold(
        bottomBar = {
            NavigationBar {
                data class NavTab(
                    val index: Int,
                    val label: String,
                    val filled: ImageVector,
                    val outlined: ImageVector,
                    val tag: String,
                )
                val tabs = listOf(
                    NavTab(0, "Accueil", Icons.Filled.Home, Icons.Outlined.Home, "nav_dashboard"),
                    NavTab(1, "Prédire", Icons.Filled.Insights, Icons.Outlined.Insights, "nav_predict"),
                    NavTab(2, "Matchs", Icons.Filled.CalendarMonth, Icons.Outlined.CalendarMonth, "nav_matches"),
                    NavTab(3, "Value", Icons.Filled.Diamond, Icons.Outlined.Diamond, "nav_value"),
                    NavTab(4, "Chat", Icons.Filled.SmartToy, Icons.Outlined.SmartToy, "nav_chat"),
                )
                tabs.forEach { t ->
                    val selected = tab == t.index
                    NavigationBarItem(
                        selected = selected,
                        onClick = { tab = t.index },
                        modifier = Modifier.testTag(t.tag),
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
            val match = selectedMatch
            if (match != null) {
                MatchDetailScreen(
                    p1 = match.first,
                    p2 = match.second,
                    eventId = match.third,
                    onBack = { selectedMatch = null },
                    vm = detailVM
                )
            } else {
                AnimatedContent(
                    targetState = tab,
                    transitionSpec = {
                        (fadeIn(tween(260)) +
                            slideInVertically(tween(260)) { it / 16 }) togetherWith
                            fadeOut(tween(180))
                    },
                    label = "tabs",
                ) { current ->
                    val onMatchClick: (String, String, String?) -> Unit = { p1, p2, eid ->
                        selectedMatch = Triple(p1, p2, eid)
                    }
                    when (current) {
                        0 -> DashboardScreen(onMatchClick, dashboardVM)
                        1 -> PredictGroupScreen(predictVM, compareVM)
                        2 -> MatchesGroupScreen(liveVM, onMatchClick)
                        3 -> ValueGroupScreen(onMatchClick)
                        else -> ChatScreen(chatVM)
                    }
                }
            }
        }
    }
}
