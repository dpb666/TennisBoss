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
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.ValuePickHistory
import com.tennisboss.app.ui.components.SkeletonList
import com.tennisboss.app.ui.components.SurfaceBadge
import com.tennisboss.app.ui.components.ValueCard
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.LocalDate

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
fun ValueScreen(
    onMatchClick: ((String, String, String?) -> Unit)? = null,
    vm: ValueViewModel = viewModel()
) {
    var selectedTab by remember { mutableIntStateOf(0) }

    DisposableEffect(Unit) {
        vm.startAutoRefresh()
        onDispose { vm.stopAutoRefresh() }
    }

    LaunchedEffect(selectedTab) {
        if (selectedTab == 1 && vm.historyState is ValueHistoryUiState.Idle) {
            vm.loadHistory()
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        // Header
        Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("💎 Value bets (IA)", style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold)
                    val sub = when (val s = vm.state) {
                        is ValueUiState.Success -> {
                            val m = s.refreshIn / 60
                            val sec = s.refreshIn % 60
                            "Màj dans ${m}m${sec.toString().padStart(2, '0')}s"
                        }
                        else -> "Détection d'anomalies par IA"
                    }
                    Text(sub, style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (selectedTab == 0) {
                    Button(
                        onClick = { vm.load() },
                        enabled = vm.state !is ValueUiState.Loading,
                    ) { Text("Rafraîchir") }
                }
            }
        }

        TabRow(selectedTabIndex = selectedTab) {
            Tab(selected = selectedTab == 0, onClick = { selectedTab = 0 },
                text = { Text("Aujourd'hui") })
            Tab(selected = selectedTab == 1, onClick = { selectedTab = 1 },
                text = { Text("Historique") })
        }

        when (selectedTab) {
            0 -> ValuePicksTab(onMatchClick, vm)
            1 -> ValueHistoryTab(vm)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ValuePicksTab(
    onMatchClick: ((String, String, String?) -> Unit)? = null,
    vm: ValueViewModel
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        FilterChip(
            selected = vm.highConfidenceOnly,
            onClick = { vm.highConfidenceOnly = !vm.highConfidenceOnly },
            label = {
                Text(if (vm.highConfidenceOnly) "🎯 Fiable (≥40%)" else "Tout afficher")
            },
            colors = FilterChipDefaults.filterChipColors(
                selectedContainerColor = MaterialTheme.colorScheme.tertiaryContainer,
                selectedLabelColor = MaterialTheme.colorScheme.onTertiaryContainer,
            ),
        )

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
                            Text("⏳ Limite API atteinte",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold, color = Color(0xFFFFB800))
                            Text(
                                s.rateLimitMessage.ifBlank {
                                    "Quota odds-api.io épuisé. " +
                                        s.retryInS?.let { "Réessayer dans ${it}s." }.orEmpty()
                                },
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    } else {
                        val filtered = if (vm.highConfidenceOnly)
                            s.comparisons.filter { it.confidence >= 0.4 }
                        else s.comparisons
                        val hidden = s.comparisons.size - filtered.size

                        if (filtered.isEmpty()) {
                            Text(
                                if (s.comparisons.isEmpty())
                                    "Aucune value pour le moment. Tire vers le bas pour réessayer."
                                else
                                    "Toutes les values ont une confiance < 40%. " +
                                    "Désactive le filtre pour les voir.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        } else {
                            LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                                if (hidden > 0) {
                                    item {
                                        Text(
                                            "$hidden masqué${if (hidden > 1) "s" else ""} (confiance < 40%)",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                                items(filtered) { ValueCard(it, onClick = { onMatchClick?.invoke(it.player1, it.player2, null) }) }
                            }
                        }
                    }
                }
                else -> {}
            }
        }
    }
}

@Composable
private fun ValueHistoryTab(vm: ValueViewModel) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        when (val s = vm.historyState) {
            is ValueHistoryUiState.Loading -> SkeletonList(count = 5)
            is ValueHistoryUiState.Error ->
                Text(s.message, color = MaterialTheme.colorScheme.error)
            is ValueHistoryUiState.Success -> {
                val stats = s.data.stats
                if (stats.n > 0) {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceEvenly,
                        ) {
                            StatPill("Picks", "${stats.n}")
                            StatPill("Gagnés", "${stats.wins}")
                            StatPill("Win %",
                                stats.win_rate?.let { "${(it * 100).toInt()}%" } ?: "–")
                            val roiColor = when {
                                (stats.roi ?: 0.0) > 0 -> GoodColor
                                (stats.roi ?: 0.0) < -0.05 -> BadColor
                                else -> Color(0xFFFFB800)
                            }
                            StatPill("ROI",
                                stats.roi?.let { String.format("%+.1f%%", it * 100) } ?: "–",
                                roiColor)
                        }
                    }
                }

                if (s.data.picks.isEmpty()) {
                    Text(
                        "Aucun pick réglé pour le moment.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(s.data.picks) { HistoryPickRow(it) }
                    }
                }
            }
            else -> {
                Button(onClick = { vm.loadHistory() }) { Text("Charger l'historique") }
            }
        }
    }
}

@Composable
private fun StatPill(label: String, value: String, valueColor: Color = GoodColor) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold, color = valueColor)
        Text(label, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun HistoryPickRow(p: ValuePickHistory) {
    val won = p.result == 1
    val lost = p.result == 0
    val pending = p.result == null
    val rowColor = when {
        won -> GoodColor.copy(alpha = 0.08f)
        lost -> BadColor.copy(alpha = 0.06f)
        else -> Color.Transparent
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(rowColor)
            .padding(horizontal = 10.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("${p.player1} vs ${p.player2}",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.SemiBold, maxLines = 1)
            Text("Pari : ${p.side} @ ${p.odds}  •  EV ${String.format("%+.1f%%", p.ev)}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(p.date, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline)
                SurfaceBadge(p.surface)
            }
        }
        Spacer(Modifier.size(8.dp))
        val (icon, pnlStr, color) = when {
            won  -> Triple("✅", p.pnl?.let { String.format("%+.2fu", it) } ?: "+?", GoodColor)
            lost -> Triple("❌", "-1.00u", BadColor)
            else -> Triple("⏳", "en attente", Color(0xFFFFB800))
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(icon, style = MaterialTheme.typography.bodyMedium)
            Text(pnlStr, style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold, color = color)
        }
    }
}

// ValueCard, ProbCompareRow, SideBox, EvBadge/EdgeIndicator, fmt/fmtSigned :
// extraits dans ui/components/ValueCard.kt et ui/components/EdgeIndicator.kt
// pour être réutilisables ailleurs (ex. DashboardScreen).
