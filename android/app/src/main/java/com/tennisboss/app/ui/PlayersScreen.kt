package com.tennisboss.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.Player
import com.tennisboss.app.ui.components.PlayerDetailSheet

@Composable
fun PlayersScreen(
    selectedP1: String,
    selectedP2: String,
    onPlayerClick: (String) -> Unit,
    vm: PlayersViewModel = viewModel(),
    detailVM: PlayerDetailViewModel = viewModel(),
) {
    var detailOpen by remember { mutableStateOf(false) }
    if (detailOpen) {
        PlayerDetailSheet(
            state = detailVM.state,
            onDismiss = { detailOpen = false; detailVM.clear() },
        )
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            "Recherche joueurs",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "Touchez un joueur pour le placer dans la prédiction (J1 puis J2).",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.outline,
        )
        Text(
            "Sélection →  J1 : ${selectedP1.ifBlank { "—" }}   ·   J2 : ${selectedP2.ifBlank { "—" }}",
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
        )
        OutlinedTextField(
            value = vm.query,
            onValueChange = { vm.onQueryChange(it) },
            label = { Text("Nom du joueur") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        if (vm.loading) CircularProgressIndicator()
        vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        if (!vm.loading && vm.error == null && vm.query.isNotBlank() && vm.players.isEmpty()) {
            Text("Aucun joueur trouvé.")
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(vm.players) { p ->
                PlayerRow(
                    p = p,
                    onClick = { onPlayerClick(p.name) },
                    onInfo = { detailVM.load(p.name); detailOpen = true },
                )
            }
        }
    }
}

@Composable
private fun PlayerRow(p: Player, onClick: () -> Unit, onInfo: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(14.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(p.name, fontWeight = FontWeight.SemiBold)
                Text(
                    buildString {
                        if (p.tour.isNotBlank()) append(p.tour.uppercase()).append(" · ")
                        append("${p.matches} matchs")
                        if (!p.confident) append(" · ⚠️ peu de données")
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    String.format("%.0f%%", p.win_prob_vs_avg * 100),
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    "force",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
            // Bouton info -> ouvre la fiche détaillée (consomme son propre clic).
            Text(
                "ℹ️",
                fontSize = 20.sp,
                modifier = Modifier
                    .padding(start = 12.dp)
                    .clickable(onClick = onInfo),
            )
        }
    }
}
