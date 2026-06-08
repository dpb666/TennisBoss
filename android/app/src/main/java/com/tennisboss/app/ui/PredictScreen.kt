package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.PredictResponse
import com.tennisboss.app.data.SettingsStore
import com.tennisboss.app.ui.components.BetBuilderView
import com.tennisboss.app.ui.components.ExplainView
import com.tennisboss.app.ui.components.H2HView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

@Composable
fun PredictScreen(
    vm: PredictViewModel = viewModel(),
    store: SettingsStore? = null,
    scope: CoroutineScope? = null,
) {
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

        if (store != null && scope != null) {
            ServerSettings(store, scope)
        }

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

            d.explain?.let { ex ->
                HorizontalDivider(Modifier.padding(vertical = 4.dp))
                ExplainView(
                    name1 = d.player1.name,
                    name2 = d.player2.name,
                    explain = ex,
                )
            }

            d.h2h?.let { h ->
                HorizontalDivider(Modifier.padding(vertical = 4.dp))
                H2HView(h2h = h)
            }

            d.bet_builder?.let { bb ->
                HorizontalDivider(Modifier.padding(vertical = 4.dp))
                BetBuilderView(
                    name1 = d.player1.name,
                    name2 = d.player2.name,
                    bb = bb,
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

/** Réglages serveur persistants (URL + token), repliables. */
@Composable
private fun ServerSettings(store: SettingsStore, scope: CoroutineScope) {
    var expanded by remember { mutableStateOf(false) }

    // Valeurs persistées (source de vérité). Les champs locaux sont seedés dessus.
    val savedUrl by store.baseUrlFlow.collectAsState(initial = ApiClient.baseUrl)
    val savedToken by store.tokenFlow.collectAsState(initial = ApiClient.apiToken)
    var urlEdit by remember { mutableStateOf<String?>(null) }
    var tokenEdit by remember { mutableStateOf<String?>(null) }
    val url = urlEdit ?: savedUrl
    val token = tokenEdit ?: savedToken

    // Applique la valeur persistée au client réseau.
    LaunchedEffect(savedUrl) { ApiClient.baseUrl = savedUrl }
    LaunchedEffect(savedToken) { ApiClient.apiToken = savedToken }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            if (expanded) "⚙️ Réglages serveur  ▲" else "⚙️ Réglages serveur  ▼",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded },
        )
        if (!expanded) {
            Text(
                url,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            OutlinedTextField(
                value = url,
                onValueChange = {
                    urlEdit = it
                    ApiClient.baseUrl = it
                    scope.launch { store.setBaseUrl(it) }
                },
                label = { Text("URL du serveur") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = token,
                onValueChange = {
                    tokenEdit = it
                    ApiClient.apiToken = it
                    scope.launch { store.setToken(it) }
                },
                label = { Text("Token API (optionnel)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "Sauvegardé automatiquement. Émulateur : http://10.0.2.2:8000/ · " +
                    "téléphone : http://IP_DU_PC:8000/",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}
