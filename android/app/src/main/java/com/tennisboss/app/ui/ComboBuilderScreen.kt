package com.tennisboss.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ComboLeg

private val MARKET_LABELS = mapOf(
    "match" to "Vainqueur du match",
    "set2" to "Vainqueur 2e set",
    "total_sets" to "Total sets (+/- 2.5)",
    "handicap" to "Handicap -1.5 sets",
)

@Composable
fun ComboBuilderScreen(vm: ComboBuilderViewModel = viewModel()) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("🧩 Combo Builder", style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold)
        Text(
            "Combine 2 à 4 pronostics déjà calculés — probabilité combinée = " +
                "produit des probas individuelles (hypothèse d'indépendance entre " +
                "matchs différents). Cote juste théorique, pas une cote de bookmaker " +
                "réelle hors marché \"Vainqueur du match\".",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        vm.legs.forEachIndexed { index, leg ->
            LegEditor(
                index = index,
                leg = leg,
                canRemove = vm.legs.size > 2,
                onChange = { vm.updateLeg(index, it) },
                onRemove = { vm.removeLeg(index) },
            )
        }

        if (vm.legs.size < 4) {
            OutlinedButton(
                onClick = { vm.addLeg() },
                modifier = Modifier.fillMaxWidth().testTag("combo_add_leg"),
            ) { Text("+ Ajouter un match") }
        }

        Button(
            onClick = { vm.calculate() },
            enabled = vm.canCalculate() && vm.state !is ComboUiState.Loading,
            modifier = Modifier.fillMaxWidth().testTag("combo_calculate"),
        ) { Text("Calculer le combiné") }

        when (val s = vm.state) {
            is ComboUiState.Loading -> CircularProgressIndicator()
            is ComboUiState.Error -> Text(s.message, color = MaterialTheme.colorScheme.error)
            is ComboUiState.Success -> ComboResultCard(
                s.result.legs, s.result.combined_probability_pct, s.result.combined_fair_odds, s.result.note)
            ComboUiState.Idle -> {}
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LegEditor(
    index: Int,
    leg: ComboLegInput,
    canRemove: Boolean,
    onChange: (ComboLegInput) -> Unit,
    onRemove: () -> Unit,
) {
    var marketExpanded by remember { mutableStateOf(false) }

    Card(modifier = Modifier.fillMaxWidth().testTag("combo_leg_$index")) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Match ${index + 1}", style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold)
                if (canRemove) {
                    IconButton(onClick = onRemove, modifier = Modifier.testTag("combo_remove_$index")) {
                        Icon(Icons.Filled.Close, contentDescription = "Retirer ce match")
                    }
                }
            }
            OutlinedTextField(
                value = leg.player1,
                onValueChange = { onChange(leg.copy(player1 = it)) },
                label = { Text("Joueur 1") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("combo_p1_$index"),
            )
            OutlinedTextField(
                value = leg.player2,
                onValueChange = { onChange(leg.copy(player2 = it)) },
                label = { Text("Joueur 2") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("combo_p2_$index"),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = leg.side == "player1",
                    onClick = { onChange(leg.copy(side = "player1")) },
                    label = { Text(leg.player1.ifBlank { "Joueur 1" }) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.primaryContainer),
                    modifier = Modifier.testTag("combo_side1_$index"),
                )
                FilterChip(
                    selected = leg.side == "player2",
                    onClick = { onChange(leg.copy(side = "player2")) },
                    label = { Text(leg.player2.ifBlank { "Joueur 2" }) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.primaryContainer),
                    modifier = Modifier.testTag("combo_side2_$index"),
                )
            }
            Box(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = MARKET_LABELS[leg.market] ?: leg.market,
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("Marché") },
                    trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { marketExpanded = true }
                        .testTag("combo_market_$index"),
                )
                DropdownMenu(
                    expanded = marketExpanded,
                    onDismissRequest = { marketExpanded = false },
                ) {
                    MARKET_LABELS.forEach { (key, label) ->
                        DropdownMenuItem(
                            text = { Text(label) },
                            onClick = {
                                onChange(leg.copy(market = key))
                                marketExpanded = false
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ComboResultCard(legs: List<ComboLeg>, combinedProb: Double, combinedOdds: Double, note: String) {
    val AccentColor = Color(0xFF00E5A0)
    Card(modifier = Modifier.fillMaxWidth().testTag("combo_result")) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Résultat du combiné", style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold)
            legs.forEach { leg ->
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    val side = if (leg.side == "player1") leg.player1 else leg.player2
                    Text("$side — ${MARKET_LABELS[leg.market] ?: leg.market}",
                        style = MaterialTheme.typography.bodySmall)
                    Text("${leg.prob_pct}% · cote ${leg.fair_odds}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            HorizontalDivider()
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Combiné", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Text("${combinedProb}% · cote $combinedOdds",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold, color = AccentColor)
            }
            Text(note, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
