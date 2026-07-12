package com.tennisboss.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.material3.Text

/**
 * Groupes de navigation — regroupent la bottom nav de 9 à 5 destinations
 * (guideline Material : 3-5). Chaque groupe garde les écrans existants
 * intacts, juste un TabRow de second niveau pour basculer entre les deux,
 * même pattern que celui déjà utilisé dans ValueScreen/PerformanceScreen.
 */

@Composable
fun PredictGroupScreen(predictVM: PredictViewModel, compareVM: PlayerCompareViewModel) {
    var subTab by remember { mutableIntStateOf(0) }
    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = subTab) {
            Tab(selected = subTab == 0, onClick = { subTab = 0 },
                text = { Text("Prédire", maxLines = 1, overflow = TextOverflow.Ellipsis) })
            Tab(selected = subTab == 1, onClick = { subTab = 1 },
                text = { Text("Joueurs", maxLines = 1, overflow = TextOverflow.Ellipsis) })
        }
        when (subTab) {
            0 -> PredictScreen(predictVM)
            else -> PlayersScreen(
                selectedP1 = predictVM.player1,
                selectedP2 = predictVM.player2,
                onPlayerClick = { name ->
                    val pairComplete = predictVM.pick(name)
                    if (pairComplete) subTab = 0
                },
                vm = compareVM,
            )
        }
    }
}

@Composable
fun MatchesGroupScreen(liveVM: LiveViewModel, onMatchClick: (String, String, String?) -> Unit) {
    var subTab by remember { mutableIntStateOf(0) }
    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = subTab) {
            Tab(selected = subTab == 0, onClick = { subTab = 0 },
                text = { Text("À venir", maxLines = 1, overflow = TextOverflow.Ellipsis) })
            Tab(selected = subTab == 1, onClick = { subTab = 1 },
                text = { Text("Live", maxLines = 1, overflow = TextOverflow.Ellipsis) })
        }
        when (subTab) {
            0 -> UpcomingScreen(onMatchClick = onMatchClick)
            else -> LiveScreen(onMatchClick = onMatchClick, vm = liveVM)
        }
    }
}

@Composable
fun ValueGroupScreen(onMatchClick: (String, String, String?) -> Unit) {
    var subTab by remember { mutableIntStateOf(0) }
    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = subTab) {
            Tab(selected = subTab == 0, onClick = { subTab = 0 },
                text = { Text("Value", maxLines = 1, overflow = TextOverflow.Ellipsis) })
            Tab(selected = subTab == 1, onClick = { subTab = 1 },
                text = { Text("Scanner", maxLines = 1, overflow = TextOverflow.Ellipsis) })
            Tab(selected = subTab == 2, onClick = { subTab = 2 },
                text = { Text("Stats", maxLines = 1, overflow = TextOverflow.Ellipsis) })
            Tab(selected = subTab == 3, onClick = { subTab = 3 },
                text = { Text("Edge", maxLines = 1, overflow = TextOverflow.Ellipsis) })
        }
        when (subTab) {
            0 -> ValueScreen(onMatchClick = onMatchClick)
            1 -> ScannerScreen()
            2 -> PerformanceScreen()
            else -> EdgeScreen()
        }
    }
}
