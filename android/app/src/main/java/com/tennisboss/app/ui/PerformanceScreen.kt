package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
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
import com.tennisboss.app.data.CalibMetrics
import com.tennisboss.app.data.HistoryMatch
import com.tennisboss.app.data.HistoryResponse
import com.tennisboss.app.data.SettledRecent
import com.tennisboss.app.ui.components.SkeletonList

private val GoodColor  = Color(0xFF00E5A0)
private val BadColor   = Color(0xFFFF5C7A)
private val AccentColor = Color(0xFF4F8CFF)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PerformanceScreen(vm: PerformanceViewModel = viewModel()) {
    var selectedTab by remember { mutableIntStateOf(0) }

    LaunchedEffect(Unit) { vm.load() }

    Column(
        modifier = Modifier.fillMaxSize().padding(top = 16.dp, start = 16.dp, end = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("📊 Performance de l'IA", style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold)

        TabRow(selectedTabIndex = selectedTab) {
            Tab(selected = selectedTab == 0, onClick = { selectedTab = 0 },
                text = { Text("Stats") })
            Tab(selected = selectedTab == 1, onClick = {
                selectedTab = 1
                vm.loadHistoryDates()
            }, text = { Text("Calendrier") })
        }

        Spacer(Modifier.height(4.dp))

        when (selectedTab) {
            0 -> StatsTab(vm)
            1 -> CalendarTab(vm)
        }
    }
}

// ─── Onglet Stats ─────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun StatsTab(vm: PerformanceViewModel) {
    PullToRefreshBox(
        isRefreshing = vm.state is PerformanceUiState.Loading,
        onRefresh = { vm.load() },
        modifier = Modifier.fillMaxSize(),
    ) {
        when (val s = vm.state) {
            is PerformanceUiState.Loading -> SkeletonList(count = 3)
            is PerformanceUiState.Error -> Text(s.message, color = MaterialTheme.colorScheme.error)
            is PerformanceUiState.Success -> StatsContent(s.data.metrics, s.data.calibration_k, s.data.recent)
            else -> {}
        }
    }
}

@Composable
private fun StatsContent(m: CalibMetrics, k: Double, recent: List<SettledRecent>) {
    if (m.n == 0 && recent.isEmpty()) {
        Text("Pas encore de match réglé.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        return
    }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatCard("Précision", pct(m.accuracy), AccentColor, Modifier.weight(1f),
                    sub = "${m.n} matchs prédits")
                StatCard("Couverture", pct(
                    if (m.n > 0 && m.roi_n > 0) m.n.toDouble() / (m.n + 2331) else null
                ), AccentColor, Modifier.weight(1f), sub = "% matchs modélisés")
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatCard("ROI favori", roiPct(m.roi), roiColor(m.roi), Modifier.weight(1f),
                    sub = if (m.roi_n > 0) "${m.roi_n} paris" else "à venir")
                StatCard("ROI value", roiPct(m.roi_value), roiColor(m.roi_value), Modifier.weight(1f),
                    sub = if (m.roi_value_n > 0) "${m.roi_value_n} paris" else "à venir")
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatCard("Calibration k", String.format("%.2f", k), AccentColor,
                    Modifier.weight(1f), sub = kInterpretation(k))
                StatCard("Brier", m.brier?.let { String.format("%.3f", it) } ?: "—",
                    AccentColor, Modifier.weight(1f), sub = "plus bas = mieux")
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.fillMaxWidth().padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)) {
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

// ─── Onglet Calendrier ────────────────────────────────────────────────────────

@Composable
private fun CalendarTab(vm: PerformanceViewModel) {
    when (val s = vm.historyState) {
        is HistoryUiState.Loading -> SkeletonList(count = 4)
        is HistoryUiState.Error -> Text(s.message, color = MaterialTheme.colorScheme.error)

        is HistoryUiState.Dates -> DatePicker(s.dates, null, vm)

        is HistoryUiState.DayLoading -> {
            DatePicker(s.dates, s.selectedDate, vm)
            SkeletonList(count = 4)
        }

        is HistoryUiState.DaySuccess -> {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                DatePicker(s.dates, s.selectedDate, vm)
                DayView(s.history)
            }
        }

        else -> {}
    }
}

@Composable
private fun DatePicker(dates: List<String>, selected: String?, vm: PerformanceViewModel) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        dates.forEach { date ->
            val isSelected = date == selected
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(20.dp))
                    .background(
                        if (isSelected) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.surfaceVariant
                    )
                    .clickable { vm.selectDate(date) }
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            ) {
                Text(
                    date.substring(5), // MM-DD
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                    color = if (isSelected) MaterialTheme.colorScheme.onPrimary
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun DayView(h: HistoryResponse) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        item {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(h.date, style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold)
                Column(horizontalAlignment = Alignment.End) {
                    Text("${h.count} matchs · ${h.n_predicted} prédits",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    h.accuracy_day?.let {
                        Text("Précision du jour : ${pct(it)}",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (it >= 0.6) GoodColor else AccentColor,
                            fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
        }
        val singles = h.matches.filter { !it.is_doubles }
        items(singles) { HistoryMatchRow(it) }
        if (singles.isEmpty()) {
            item {
                Text("Aucun match simple ce jour-là.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun HistoryMatchRow(m: HistoryMatch) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            if (m.tournament.isNotBlank()) {
                Text(m.tournament, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary)
            }
            Text("${m.player1} vs ${m.player2}",
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Medium)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("🏆 ${m.winner}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (m.score.isNotBlank())
                    Text("(${m.score})", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline)
            }
            m.pred_favorite?.let {
                Text("prédit: $it", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline)
            }
        }
        Spacer(Modifier.width(8.dp))
        Text(
            when (m.correct) { 1 -> "✅"; 0 -> "❌"; else -> "—" },
            style = MaterialTheme.typography.titleMedium,
        )
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
}

// ─── Composants partagés ──────────────────────────────────────────────────────

@Composable
private fun StatCard(label: String, value: String, color: Color,
                     modifier: Modifier = Modifier, sub: String = "") {
    Card(modifier = modifier) {
        Column(modifier = Modifier.fillMaxWidth().padding(14.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold, color = color)
            if (sub.isNotBlank())
                Text(sub, style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline)
        }
    }
}

@Composable
private fun SegmentRow(label: String, acc: Double?) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Text(pct(acc), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun RecentRow(r: SettledRecent) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween) {
            Column(Modifier.weight(1f)) {
                if (r.date.isNotBlank())
                    Text(r.date.take(16).replace("T", " ").replace("Z", ""),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary)
                Text("${r.player1}  vs  ${r.player2}",
                    style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                Text("🏆 ${r.winner} ${if (r.score.isNotBlank()) "(${r.score})" else ""}" +
                    (r.pred_favorite?.let { "  · prédit : $it" } ?: ""),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(when (r.correct) { 1 -> "✅"; 0 -> "❌"; else -> "—" },
                style = MaterialTheme.typography.titleMedium)
        }
    }
}

private fun pct(v: Double?): String = v?.let { String.format("%.0f%%", it * 100) } ?: "—"
private fun roiPct(roi: Double?): String = roi?.let { String.format("%+.1f%%", it * 100) } ?: "—"
private fun roiColor(roi: Double?): Color = when {
    roi == null -> AccentColor; roi >= 0 -> GoodColor; else -> BadColor
}
private fun kInterpretation(k: Double): String = when {
    k < 0.95 -> "sur-confiant"; k > 1.05 -> "sous-confiant"; else -> "bien calibré"
}
