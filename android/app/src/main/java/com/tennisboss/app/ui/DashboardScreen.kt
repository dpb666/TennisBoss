package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
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
import com.tennisboss.app.data.CalibrationResponse
import com.tennisboss.app.data.UpcomingMatch
import com.tennisboss.app.data.ValueComparison
import com.tennisboss.app.ui.components.ConfidenceBadge
import com.tennisboss.app.ui.components.SurfaceBadge

private val GoodColor = Color(0xFF00E5A0)
private val AccentColor = Color(0xFF4F8CFF)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(vm: DashboardViewModel = viewModel()) {
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
                DashboardContent(s.upcoming.matches, s.value.comparisons, s.calibration)
            }
        }
    }
}

@Composable
private fun DashboardContent(
    upcoming: List<UpcomingMatch>,
    values: List<ValueComparison>,
    calib: CalibrationResponse
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

        // --- Meilleures Opportunités Value ---
        if (values.isNotEmpty()) {
            item {
                SectionHeader("💎 Meilleures opportunités", Icons.Default.Diamond)
            }
            items(values.take(3)) { valItem ->
                ValueOpportunityCard(valItem)
            }
        }

        // --- Matchs du jour ---
        if (upcoming.isNotEmpty()) {
            item {
                SectionHeader("📅 Matchs du jour", Icons.Default.Insights)
            }
            items(upcoming.take(5)) { match ->
                MatchSummaryCard(match)
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

@Composable
private fun ValueOpportunityCard(v: ValueComparison) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(2.dp)
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(v.league, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                ConfidenceBadge(v.confidence_label, v.confidence)
            }
            Spacer(Modifier.height(4.dp))
            Text("${v.player1} vs ${v.player2}", fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column {
                    Text("Pari conseillé", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                    Text(v.best_side ?: "Pas de pick", color = GoodColor, fontWeight = FontWeight.Bold)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("Edge %", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                    Text(String.format("%+.1f%%", v.best_ev), color = GoodColor, fontWeight = FontWeight.ExtraBold, fontSize = 18.sp)
                }
            }
        }
    }
}

@Composable
private fun MatchSummaryCard(m: UpcomingMatch) {
    Card(
        modifier = Modifier.fillMaxWidth(),
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
                Text(m.tournament, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
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
