package com.tennisboss.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
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
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.TokenManager
import com.tennisboss.app.ui.ChatScreen
import com.tennisboss.app.ui.ChatViewModel
import com.tennisboss.app.ui.PerformanceScreen
import com.tennisboss.app.ui.PlayersScreen
import com.tennisboss.app.ui.PredictScreen
import com.tennisboss.app.ui.PredictViewModel
import com.tennisboss.app.ui.UpcomingScreen
import com.tennisboss.app.ui.ValueScreen
import com.tennisboss.app.ui.theme.TennisBossTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
    val chatVM: ChatViewModel = viewModel()

    // URL publique par défaut pour fonctionner hors réseau local.
    // Le token est chargé depuis TokenManager (variables de build ou stockage chiffré).
    val context = LocalContext.current
    LaunchedEffect(Unit) {
        ApiClient.baseUrl = ApiClient.DEFAULT_BASE_URL
        TokenManager.initialize(context)
    }

    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = tab == 0,
                    onClick = { tab = 0 },
                    icon = { Text("🎯") },
                    label = { Text("Prédire") },
                )
                NavigationBarItem(
                    selected = tab == 1,
                    onClick = { tab = 1 },
                    icon = { Text("📅") },
                    label = { Text("Matchs") },
                )
                NavigationBarItem(
                    selected = tab == 2,
                    onClick = { tab = 2 },
                    icon = { Text("👤") },
                    label = { Text("Joueurs") },
                )
                NavigationBarItem(
                    selected = tab == 3,
                    onClick = { tab = 3 },
                    icon = { Text("💎") },
                    label = { Text("Value") },
                )
                NavigationBarItem(
                    selected = tab == 4,
                    onClick = { tab = 4 },
                    icon = { Text("📊") },
                    label = { Text("Perf") },
                )
                NavigationBarItem(
                    selected = tab == 5,
                    onClick = { tab = 5 },
                    icon = { Text("🤖") },
                    label = { Text("AI Chat") },
                )
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
                            if (pairComplete) tab = 0   // paire prête -> on bascule sur Prédire
                        },
                    )
                    3 -> ValueScreen()
                    4 -> PerformanceScreen()
                    else -> ChatScreen(chatVM)
                }
            }
        }
    }
}
