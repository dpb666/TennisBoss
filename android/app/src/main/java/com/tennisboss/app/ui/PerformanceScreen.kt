package com.tennisboss.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.CalibMetrics
import com.tennisboss.app.data.SettledRecent
import com.tennisboss.app.ui.components.SkeletonList

private val GoodColor = Color(0xFF00E5A0)
private val BadColor = Color(0xFFFF5C7A)
private val AccentColor = Color(0xFF4F8CFF)

/**
 * Onglet « Performance » : comment le modèle se comporte sur les matchs réels
 * (précision, ROI, calibration), alimenté par /api/calibration.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PerformanceScreen(vm: PerformanceViewModel = viewModel()) {
    LaunchedEffect(Unit) {
        if (vm.state is PerformanceUiState.Idle) vm.load()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("📊 Performance du modèle", style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold)
        Text(
            "Mesuré sur les matchs réellement terminés.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        PullToRefreshBox(
            isRefreshing = vm.state is PerformanceUiState.Loading,
            onRefresh = { vm.load() },
            modifier = Modifier.fillMaxSize(),
        ) {
            when (val s = vm.state) {
                is PerformanceUiState.Loading -> SkeletonList(count = 3)
                is PerformanceUiState.Error ->
                    Text(s.message, color = MaterialTheme.colorScheme.error)
                is PerformanceUiState.Success -> Content(s.data.metrics, s.data.calibration_k,
                    s.data.recent)
                else -> {}
            }
        }
    }
}

@Composable
private fun Content(m: CalibMetrics, k: Double, recent: List<SettledRecent>) {
    if (m.n == 0) {
        Text(
            "Pas encore de match réglé. La calibration se fera automatiquement " +
                "dès que des matchs suivis seront terminés.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                StatCard("Précision", pct(m.accuracy), AccentColor, Modifier.weight(1f),
                    sub = "${m.n} matchs")
                StatCard("ROI", roiPct(m.roi), roiColor(m.roi), Modifier.weight(1f),
                    sub = if (m.roi_n > 0) "${m.roi_n} paris" else "à venir")
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                StatCard("Calibration k", String.format("%.2f", k), AccentColor,
                    Modifier.weight(1f), sub = kInterpretation(k))
                StatCard("Brier", m.brier?.let { String.format("%.3f", it) } ?: "—",
                    AccentColor, Modifier.weight(1f), sub = "plus bas = mieux")
            }
        }
        item {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("Détail par segment", fontWeight = FontWeight.Bold)
                    SegmentRow("ATP", m.atp_acc)
                    SegmentRow("WTA", m.wta_acc)
                    SegmentRow("Favori clair", m.fav_acc)
                    SegmentRow("Matchs serrés", m.dog_acc)
                }
            }
        }
        if (recent.isNotEmpty()) {
            item {
                Text("Derniers matchs réglés", fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall)
            }
            items(recent) { RecentRow(it) }
        }
    }
}

@Composable
private fun StatCard(label: String, value: String, color: Color,
                     modifier: Modifier = Modifier, sub: String = "") {
    Card(modifier = modifier) {
        Column(modifier = Modifier.fillMaxWidth().padding(14.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold, color = color)
            if (sub.isNotBlank()) {
                Text(sub, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}

@Composable
private fun SegmentRow(label: String, acc: Double?) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Text(pct(acc), style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun RecentRow(r: SettledRecent) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(Modifier.weight(1f)) {
                Text("${r.player1}  vs  ${r.player2}",
                    style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                Text(
                    "🏆 ${r.winner} ${if (r.score.isNotBlank()) "(${r.score})" else ""}" +
                        (r.pred_favorite?.let { "  · prédit : $it" } ?: ""),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                when (r.correct) { 1 -> "✅"; 0 -> "❌"; else -> "—" },
                style = MaterialTheme.typography.titleMedium,
            )
        }
    }
}

private fun pct(v: Double?): String = v?.let { String.format("%.0f%%", it * 100) } ?: "—"

private fun roiPct(roi: Double?): String =
    roi?.let { String.format("%+.1f%%", it * 100) } ?: "—"

private fun roiColor(roi: Double?): Color = when {
    roi == null -> AccentColor
    roi >= 0 -> GoodColor
    else -> BadColor
}

private fun kInterpretation(k: Double): String = when {
    k < 0.95 -> "sur-confiant"
    k > 1.05 -> "sous-confiant"
    else -> "bien calibré"
}
