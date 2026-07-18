package com.tennisboss.app.ui

import androidx.compose.foundation.background
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
import androidx.compose.material.icons.filled.Info
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ComboLeg
import java.util.Locale

private val MARKET_LABELS = mapOf(
    "match" to "Vainqueur du match",
    "set2" to "Vainqueur 2e set",
    "total_sets" to "Total sets (+/- 2.5)",
    "handicap" to "Handicap -1.5 sets",
)

private const val TOTAL_SETS_OVER = "Plus de 2.5 sets"
private const val TOTAL_SETS_UNDER = "Moins de 2.5 sets"

/** Labels des chips côté — pour total_sets, player1/player2 = Over/Under, pas les joueurs. */
private fun sideChipLabels(leg: ComboLegInput): Pair<String, String> = when (leg.market) {
    "total_sets" -> TOTAL_SETS_OVER to TOTAL_SETS_UNDER
    else -> (leg.player1.ifBlank { "Joueur 1" }) to (leg.player2.ifBlank { "Joueur 2" })
}

private fun legSideDisplayName(leg: ComboLeg): String = when (leg.market) {
    "total_sets" -> if (leg.side == "player1") TOTAL_SETS_OVER else TOTAL_SETS_UNDER
    else -> if (leg.side == "player1") leg.player1 else leg.player2
}

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

        if (!vm.parlayBannerDismissed) {
            ParlayEducationalBanner(onDismiss = { vm.dismissParlayBanner() })
        }

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
                result = s.result,
                bookComboOdds = vm.bookComboOdds,
                onBookComboOddsChange = { vm.updateBookComboOdds(it) },
                evPct = vm.displayedEvPct(s.result),
                edge = vm.displayedEdge(s.result),
            )
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
    val (side1Label, side2Label) = sideChipLabels(leg)

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
                    label = { Text(side1Label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.primaryContainer),
                    modifier = Modifier.testTag("combo_side1_$index"),
                )
                FilterChip(
                    selected = leg.side == "player2",
                    onClick = { onChange(leg.copy(side = "player2")) },
                    label = { Text(side2Label) },
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
private fun ComboResultCard(
    result: com.tennisboss.app.data.ComboResult,
    bookComboOdds: String,
    onBookComboOddsChange: (String) -> Unit,
    evPct: Double?,
    edge: Double?,
) {
    val AccentColor = Color(0xFF00E5A0)
    val GoodColor = Color(0xFF00E5A0)
    val BadColor = Color(0xFFFF6B6B)
    Card(modifier = Modifier.fillMaxWidth().testTag("combo_result")) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Résultat du combiné", style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold)
            result.legs.forEach { leg ->
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("${legSideDisplayName(leg)} — ${MARKET_LABELS[leg.market] ?: leg.market}",
                        style = MaterialTheme.typography.bodySmall)
                    Text("${leg.prob_pct}% · cote ${leg.fair_odds}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            HorizontalDivider()
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Proba combinée", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Text("${result.combined_probability_pct}%",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold, color = AccentColor)
            }
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Cote juste combo", style = MaterialTheme.typography.bodySmall)
                Text(String.format(Locale.US, "%.2f", result.combined_fair_odds),
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.SemiBold, color = AccentColor)
            }
            OutlinedTextField(
                value = bookComboOdds,
                onValueChange = onBookComboOddsChange,
                label = { Text("Cote combo bookmaker") },
                placeholder = { Text("ex. 4.50") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("combo_book_odds"),
            )
            if (evPct != null) {
                val evColor = if (evPct >= 0.0) GoodColor else BadColor
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("EV vs cote saisie", style = MaterialTheme.typography.bodySmall)
                    Text(formatComboEvPct(evPct) + "%",
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.Bold, color = evColor,
                        modifier = Modifier.testTag("combo_ev_pct"))
                }
                if (edge != null) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("Edge vs marché", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(formatComboEdgePct(edge) + " pts",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            Text(result.note, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Rappel éducatif : les parieurs pros évitent les parlays (variance, pas de CLV combo). */
@Composable
private fun ParlayEducationalBanner(onDismiss: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.45f))
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .testTag("combo_parlay_banner"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(
            Icons.Filled.Info, contentDescription = null,
            tint = MaterialTheme.colorScheme.onErrorContainer,
        )
        Column(Modifier.weight(1f)) {
            Text(
                "Parlays : variance élevée",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            Text(
                "Les parieurs pros privilégient les singles (CLV, flat stake). " +
                    "Ce combiné est un outil éducatif — probabilités théoriques, " +
                    "EV analytique si vous saisissez la cote bookmaker du parlay.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
        IconButton(onClick = onDismiss, modifier = Modifier.testTag("combo_parlay_banner_dismiss")) {
            Icon(
                Icons.Filled.Close, contentDescription = "Ignorer",
                tint = MaterialTheme.colorScheme.onErrorContainer,
            )
        }
    }
}
