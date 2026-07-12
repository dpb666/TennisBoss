package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Diamond
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.ui.tooling.preview.Preview
import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.FollowedPlayersResponse
import com.tennisboss.app.data.Player
import com.tennisboss.app.data.UpcomingMatch
import com.tennisboss.app.data.ValueComparison
import com.tennisboss.app.ui.components.SurfaceBadge
import com.tennisboss.app.ui.components.ValueCard

private val AccentColor = Color(0xFF4F8CFF)
private val GoodColor = Color(0xFF00E5A0)
private val BadColor = Color(0xFFFF5C7A)
private val WarnColor = Color(0xFFFFB020)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onMatchClick: (String, String, String?) -> Unit,
    vm: DashboardViewModel = viewModel()
) {
    PullToRefreshBox(
        isRefreshing = vm.state is DashboardUiState.Loading,
        onRefresh = { vm.load() },
        modifier = Modifier.fillMaxSize()
    ) {
        when (val s = vm.state) {
            is DashboardUiState.Loading -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            }
            is DashboardUiState.Error -> {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(s.message, color = MaterialTheme.colorScheme.error)
                }
            }
            is DashboardUiState.Success -> {
                DashboardContent(s.upcoming.matches, s.value.comparisons, s.calibration, s.clv, s.followed, onMatchClick)
            }
        }
    }
}

@Composable
private fun DashboardContent(
    upcoming: List<UpcomingMatch>,
    values: List<ValueComparison>,
    calib: CalibrationResponse,
    clv: ClvResponse?,
    followed: FollowedPlayersResponse?,
    onMatchClick: (String, String, String?) -> Unit
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Text(
                "🎾 TennisBoss Dashboard",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold
            )
        }

        // --- État du Modèle ---
        item {
            ModelStatusCard(calib)
        }

        // --- CLV (preuve d'edge, visible sans changer d'écran — cf. onglet Edge) ---
        clv?.let { c ->
            if (c.global.n_clv > 0) {
                item {
                    ClvSummaryCard(c)
                }
            }
        }

        // --- Mes joueurs suivis ---
        followed?.players?.takeIf { it.isNotEmpty() }?.let { players ->
            item {
                SectionHeader("⭐ Mes joueurs suivis", Icons.Default.Star)
            }
            item {
                FollowedPlayersRow(players)
            }
        }

        // --- Meilleures Opportunités Value ---
        if (values.isNotEmpty()) {
            item {
                SectionHeader("💎 Meilleures opportunités", Icons.Default.Diamond)
            }
            items(values.take(3)) { valItem ->
                ValueCard(valItem, onClick = { onMatchClick(valItem.player1, valItem.player2, null) })
            }
        }

        // --- Matchs du jour ---
        if (upcoming.isNotEmpty()) {
            item {
                SectionHeader("📅 Matchs du jour", Icons.Default.Insights)
            }
            items(upcoming.take(5)) { match ->
                MatchSummaryCard(match, onClick = { onMatchClick(match.player1_raw, match.player2_raw, null) })
            }
        }
    }
}

@Composable
private fun SectionHeader(title: String, icon: androidx.compose.ui.graphics.vector.ImageVector) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun ModelStatusCard(calib: CalibrationResponse) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
    ) {
        Column(Modifier.padding(16.dp)) {
            Text("État du modèle", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                StatItem("Précision", String.format("%.0f%%", (calib.metrics.accuracy ?: 0.0) * 100))
                StatItem("Prédictions", "${calib.metrics.n}")
                StatItem("ROI Value", String.format("%+.1f%%", (calib.metrics.roi_value ?: 0.0) * 100))
            }
            // Platt (a,b) prime sur k dès qu'il est fitté (bot/api.py::_calib) — voir
            // la même logique dans PerformanceScreen.StatsContent.
            val plattActive = calib.platt_a != 1.0 || calib.platt_b != 0.0
            Spacer(Modifier.height(8.dp))
            Text(
                if (plattActive)
                    "Calibration Platt : a=${String.format("%.2f", calib.platt_a)} · b=${String.format("%.2f", calib.platt_b)}"
                else
                    "Calibration k : ${String.format("%.2f", calib.calibration_k)}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.7f),
            )
        }
    }
}

@Composable
private fun StatItem(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onPrimaryContainer)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.7f))
    }
}

private fun verdictColor(verdict: String): Color = when (verdict) {
    "edge_prouvé" -> GoodColor
    "prometteur" -> WarnColor
    "pas_d_edge" -> BadColor
    else -> AccentColor
}

/** Résumé CLV — teaser de l'onglet Edge, pour que le pari n'ait pas besoin de
 * changer d'écran pour voir si le modèle bat le marché (retour parieur). */
@Composable
private fun ClvSummaryCard(clv: ClvResponse) {
    val g = clv.global
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically) {
                Text("💰 CLV (bat-on le marché ?)", style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold)
                Text(
                    clv.verdict_label.ifBlank { clv.verdict },
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    color = verdictColor(clv.verdict),
                )
            }
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                StatItem("CLV moyen", String.format("%+.1f%%", g.avg_clv_pct ?: 0.0))
                StatItem("Bat la clôture", g.beat_closing_pct?.let { String.format("%.0f%%", it) } ?: "—")
                StatItem("Picks", "${g.n_clv}")
            }
        }
    }
}

/** Ligne horizontale des joueurs suivis (retour fanatique : les mettre en
 * avant sur le Dashboard plutôt que seulement dans l'onglet Joueurs). */
@Composable
private fun FollowedPlayersRow(players: List<Player>) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        items(players) { p ->
            Card(modifier = Modifier.width(150.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Text(p.name, fontWeight = FontWeight.Bold, maxLines = 1,
                        style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Forme : ${String.format("%.0f%%", p.recent * 100)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "Win vs moy. : ${String.format("%.0f%%", p.win_prob_vs_avg * 100)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (p.win_prob_vs_avg >= 0.5) GoodColor else BadColor,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
    }
}

@Composable
private fun MatchSummaryCard(m: UpcomingMatch, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable { onClick() },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Row(
            Modifier
                .padding(12.dp)
                .fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(m.tournament, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                    Spacer(Modifier.width(6.dp))
                    Text(combineDateTimeUtcToLocal(m.date, m.time), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                    m.prediction?.surface?.let { surf ->
                        Spacer(Modifier.width(6.dp))
                        SurfaceBadge(surf)
                    }
                }
                Text("${m.player1_raw} vs ${m.player2_raw}", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            }
            m.prediction?.let { pred ->
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(AccentColor.copy(alpha = 0.1f))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    Text(String.format("%.0f%%", pred.prob1), color = AccentColor, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                }
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun DashboardPreview() {
    MaterialTheme {
        DashboardContent(
            upcoming = emptyList(),
            values = emptyList(),
            calib = CalibrationResponse(),
            clv = null,
            followed = null,
            onMatchClick = { _, _, _ -> }
        )
    }
}
