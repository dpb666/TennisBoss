package com.tennisboss.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.UpcomingMatch

@Composable
fun UpcomingScreen(vm: UpcomingViewModel = viewModel()) {
    // Charge automatiquement au premier affichage.
    LaunchedEffect(Unit) {
        if (vm.state is UpcomingUiState.Idle) vm.load()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            "Matchs à venir",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Cotes")
                Switch(
                    checked = vm.withOdds,
                    onCheckedChange = { vm.withOdds = it },
                )
            }
            Button(
                onClick = { vm.load() },
                enabled = vm.state !is UpcomingUiState.Loading,
            ) {
                Text("Rafraîchir")
            }
        }

        when (val s = vm.state) {
            is UpcomingUiState.Loading -> CircularProgressIndicator()
            is UpcomingUiState.Error -> Text(
                s.message,
                color = MaterialTheme.colorScheme.error,
            )
            is UpcomingUiState.Success -> {
                if (s.matches.isEmpty()) {
                    Text("Aucun match à venir trouvé.")
                } else {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        items(s.matches) { m -> MatchCard(m) }
                    }
                }
            }
            else -> {}
        }
    }
}

@Composable
private fun MatchCard(m: UpcomingMatch) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    m.tournament.ifBlank { "—" },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
                if (m.live) {
                    Text("🔴 LIVE", color = Color(0xFFD32F2F),
                        fontWeight = FontWeight.Bold)
                } else {
                    Text("${m.date} ${m.time}",
                        style = MaterialTheme.typography.labelSmall)
                }
            }

            Text(
                "${m.player1_raw}  vs  ${m.player2_raw}",
                fontWeight = FontWeight.SemiBold,
            )

            val pred = m.prediction
            if (pred != null) {
                Text(
                    "1er set : ${pred.player1} ${fmt(pred.prob1)} / " +
                        "${pred.player2} ${fmt(pred.prob2)}",
                )
                pred.favorite?.let {
                    Text("🏆 Favori : $it", style = MaterialTheme.typography.bodySmall)
                }
            } else {
                Text(
                    "Joueur inconnu en base — pas de prédiction.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFF8A6D00),
                )
            }

            val odds = m.odds
            if (odds != null) {
                Text(
                    "Marché (match) : favori dom. ${fmt(odds.market_match_prob_home)} · " +
                        "cotes ${odds.home_odds}/${odds.away_odds}",
                    style = MaterialTheme.typography.bodySmall,
                )
                if (odds.books.isNotEmpty()) {
                    Text(
                        "Bookmakers : ${odds.books.joinToString(", ")}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
        }
    }
}

private fun fmt(v: Double): String = String.format("%.1f%%", v)
