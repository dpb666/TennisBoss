package com.tennisboss.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.PredictResponse
import com.tennisboss.app.ui.PredictUiState
import com.tennisboss.app.ui.PredictViewModel
import com.tennisboss.app.ui.UpcomingScreen
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
            }
        },
    ) { padding ->
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            when (tab) {
                0 -> PredictScreen()
                else -> UpcomingScreen()
            }
        }
    }
}

@Composable
fun PredictScreen(vm: PredictViewModel = viewModel()) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            "🎾 TennisBoss",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "Prédiction du 1er set",
            style = MaterialTheme.typography.titleMedium,
        )

        ServerField()

        OutlinedTextField(
            value = vm.player1,
            onValueChange = { vm.player1 = it },
            label = { Text("Joueur 1") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = vm.player2,
            onValueChange = { vm.player2 = it },
            label = { Text("Joueur 2") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        Button(
            onClick = { vm.predict() },
            modifier = Modifier.fillMaxWidth(),
            enabled = vm.state !is PredictUiState.Loading,
        ) {
            Text("Prédire")
        }

        when (val s = vm.state) {
            is PredictUiState.Loading -> CircularProgressIndicator()
            is PredictUiState.Error -> Text(
                s.message,
                color = MaterialTheme.colorScheme.error,
            )
            is PredictUiState.Success -> ResultCard(s.data)
            else -> {}
        }
    }
}

/** Permet de changer l'URL du backend à chaud (émulateur vs téléphone réel). */
@Composable
private fun ServerField() {
    var url by remember { mutableStateOf(ApiClient.baseUrl) }
    OutlinedTextField(
        value = url,
        onValueChange = {
            url = it
            ApiClient.baseUrl = it
        },
        label = { Text("URL du serveur") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun ResultCard(d: PredictResponse) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            ProbabilityRow(d.player1.name, d.first_set.prob1, d.player1.matches)
            ProbabilityRow(d.player2.name, d.first_set.prob2, d.player2.matches)

            Spacer(Modifier.height(4.dp))
            Text(
                d.first_set.verdict,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            if (!d.player1.confident || !d.player2.confident) {
                Text(
                    "⚠️ Confiance faible (joueur peu/pas connu).",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFFB26A00),
                )
            }
        }
    }
}

@Composable
private fun ProbabilityRow(name: String, prob: Double, matches: Int) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(name, fontWeight = FontWeight.SemiBold)
            Text(String.format("%.1f%%", prob))
        }
        LinearProgressIndicator(
            progress = { (prob / 100.0).toFloat() },
            modifier = Modifier
                .fillMaxWidth()
                .height(8.dp),
        )
        Text(
            "matchs vus : $matches",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
