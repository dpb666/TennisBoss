package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ValueComparison
import com.tennisboss.app.ui.components.ConfidenceBadge
import com.tennisboss.app.ui.components.SkeletonList

private val GoodColor = Color(0xFF00E5A0)   // EV+
private val BadColor = Color(0xFFFF5C7A)    // EV-
private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)

/**
 * Onglet « Value » : matchs où le modèle voit une espérance de gain (EV) positive
 * par rapport aux cotes du marché. Trié des meilleures values aux pires.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ValueScreen(vm: ValueViewModel = viewModel()) {
    LaunchedEffect(Unit) {
        if (vm.state is ValueUiState.Idle) vm.load()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("💎 Value bets (IA)", style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold)
                Text(
                    "Détection d'anomalies par IA",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Button(
                onClick = { vm.load() },
                enabled = vm.state !is ValueUiState.Loading,
            ) { Text("Rafraîchir") }
        }

        PullToRefreshBox(
            isRefreshing = vm.state is ValueUiState.Loading,
            onRefresh = { vm.load() },
            modifier = Modifier.fillMaxSize(),
        ) {
            when (val s = vm.state) {
                is ValueUiState.Loading -> SkeletonList(count = 4)
                is ValueUiState.Error ->
                    Text(s.message, color = MaterialTheme.colorScheme.error)
                is ValueUiState.Success -> {
                    if (s.rateLimited) {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(
                                "⏳ Limite API atteinte",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold,
                                color = Color(0xFFFFB800),
                            )
                            Text(
                                s.rateLimitMessage.ifBlank {
                                    "Quota odds-api.io épuisé. " +
                                        s.retryInS?.let { "Réessayer dans ${it}s." }.orEmpty()
                                },
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    } else if (s.comparisons.isEmpty()) {
                        Text(
                            "Aucune value pour le moment (cotes momentanément indisponibles " +
                                "ou aucun match coté). Tire vers le bas pour réessayer.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            items(s.comparisons) { ValueCard(it) }
                        }
                    }
                }
                else -> {}
            }
        }
    }
}

@Composable
private fun ValueCard(c: ValueComparison) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    c.league.ifBlank { "—" },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.weight(1f),
                )
                if (c.confidence_label.isNotBlank()) {
                    ConfidenceBadge(c.confidence_label, c.confidence)
                    Spacer(Modifier.size(6.dp))
                }
                EvBadge(c.best_ev, c.value)
            }

            Text("${c.player1}  vs  ${c.player2}", fontWeight = FontWeight.SemiBold)

            // Modèle vs marché (proba match), par joueur.
            ProbCompareRow(c.player1, c.model_match_prob1, c.market_match_prob1, P1Color)
            ProbCompareRow(c.player2, c.model_match_prob2, c.market_match_prob2, P2Color)

            // Cotes + EV par côté.
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                SideBox(Modifier.weight(1f), c.player1, c.odds.home, c.ev1,
                    highlight = c.best_side == c.player1)
                SideBox(Modifier.weight(1f), c.player2, c.odds.away, c.ev2,
                    highlight = c.best_side == c.player2)
            }

            if (c.value && c.best_side != null) {
                val odd = if (c.best_side == c.player1) c.odds.home else c.odds.away
                Text(
                    "✅ Pari conseillé : ${c.best_side} @ $odd  (EV ${fmtSigned(c.best_ev)})",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Bold,
                    color = GoodColor,
                )
            }

            if (c.odds.books.isNotEmpty()) {
                Text(
                    "Bookmakers : ${c.odds.books.joinToString(", ")}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
        }
    }
}

@Composable
private fun ProbCompareRow(name: String, model: Double, market: Double, color: Color) {
    val edge = model - market
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(name, style = MaterialTheme.typography.bodySmall, color = color,
            fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
        Text(
            "modèle ${fmt(model)} · marché ${fmt(market)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "  ${fmtSigned(edge)}",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Bold,
            color = if (edge >= 0) GoodColor else BadColor,
        )
    }
}

@Composable
private fun SideBox(
    modifier: Modifier,
    name: String,
    odd: Double,
    ev: Double,
    highlight: Boolean,
) {
    val border = if (highlight) GoodColor.copy(alpha = 0.18f) else Color.Transparent
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .background(border)
            .padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(name, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        Text("cote $odd", style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold)
        Text(
            "EV ${fmtSigned(ev)}",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Bold,
            color = if (ev >= 0) GoodColor else BadColor,
        )
    }
}

@Composable
private fun EvBadge(bestEv: Double, value: Boolean) {
    val bg = if (value) GoodColor else MaterialTheme.colorScheme.surfaceVariant
    val fg = if (value) Color(0xFF00251A) else MaterialTheme.colorScheme.onSurfaceVariant
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(bg)
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) {
        Text(
            if (value) "🟢 VALUE ${fmtSigned(bestEv)}" else "Pas de value",
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
            color = fg,
        )
    }
}

private fun fmt(v: Double): String = String.format("%.0f%%", v)
private fun fmtSigned(v: Double): String = String.format("%+.1f%%", v)
