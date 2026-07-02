package com.tennisboss.app.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
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
import com.tennisboss.app.data.NearMiss
import com.tennisboss.app.data.ScannerStatus
import com.tennisboss.app.ui.components.SkeletonList

private val GreenColor = Color(0xFF00E5A0)
private val RedColor   = Color(0xFFFF5C7A)
private val BlueColor  = Color(0xFF4F8CFF)
private val OrangeColor = Color(0xFFFFB020)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScannerScreen(vm: ScannerViewModel = viewModel()) {
    LaunchedEffect(Unit) { vm.load() }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("🔍 Scanner", style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold)
        Text("Détection value picks en temps réel (toutes les 90s)",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)

        PullToRefreshBox(
            isRefreshing = vm.state is ScannerUiState.Loading,
            onRefresh = { vm.load() },
            modifier = Modifier.fillMaxSize(),
        ) {
            when (val s = vm.state) {
                is ScannerUiState.Loading -> SkeletonList(count = 4)
                is ScannerUiState.Error ->
                    Text(s.message, color = MaterialTheme.colorScheme.error)
                is ScannerUiState.Success ->
                    ScannerContent(s.data, vm.secondsToNext)
                else -> {}
            }
        }
    }
}

@Composable
private fun ScannerContent(data: ScannerStatus, secondsToNext: Int?) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {

        // ── Status + Countdown ──────────────────────────────────────────
        item { StatusCard(data, secondsToNext) }

        // ── Couverture cycle ────────────────────────────────────────────
        item { CoverageCard(data) }

        // ── Breakdown des rejets ────────────────────────────────────────
        item { RejectionsCard(data) }

        // ── Near-misses ─────────────────────────────────────────────────
        if (data.near_misses.isNotEmpty()) {
            item {
                Text("⚡ Proches du seuil (EV 2-8%)",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold)
            }
            items(data.near_misses) { NearMissRow(it) }
        } else {
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        "Aucun near-miss ce cycle",
                        modifier = Modifier.padding(14.dp),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        item { Spacer(Modifier.height(16.dp)) }
    }
}

@Composable
private fun StatusCard(data: ScannerStatus, secondsToNext: Int?) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (data.running) GreenColor.copy(0.10f)
            else RedColor.copy(0.10f)
        ),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(
                    modifier = Modifier
                        .size(10.dp).clip(CircleShape)
                        .background(if (data.running) GreenColor else RedColor)
                )
                Column {
                    Text(
                        if (data.running) "Scanner actif" else "Scanner arrêté",
                        fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.titleSmall,
                        color = if (data.running) GreenColor else RedColor,
                    )
                    if (data.last_cycle_ts != null) {
                        Text(
                            "Dernier cycle : ${data.last_cycle_ts.take(16).replace("T", " ")} UTC",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            Column(horizontalAlignment = Alignment.End) {
                val secs = secondsToNext
                if (secs != null && secs > 0) {
                    Text("${secs}s", style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold, color = BlueColor)
                    Text("prochain cycle", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (data.active_picks > 0) {
                    Spacer(Modifier.height(4.dp))
                    Text("${data.active_picks} pick(s) actif(s)",
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.SemiBold, color = GreenColor)
                }
            }
        }
    }
}

@Composable
private fun CoverageCard(data: ScannerStatus) {
    val progress = if (data.cap > 0) data.checked.toFloat() / data.cap else 0f
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Couverture cycle", fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall)
                Text("${data.checked}/${data.cap} vérifiés sur ${data.total_events} events",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier.fillMaxWidth(),
                color = BlueColor,
            )
            Text(
                "Cap atteint : " + if (data.checked >= data.cap) "oui (${data.total_events - data.checked} events non vérifiés)"
                else "non — ${data.total_events - data.checked} events restants",
                style = MaterialTheme.typography.labelSmall,
                color = if (data.checked >= data.cap) OrangeColor
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun RejectionsCard(data: ScannerStatus) {
    val r = data.rejections
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.fillMaxWidth().padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Filtres ce cycle", fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.titleSmall)
            HorizontalDivider()
            RejectRow("Hors fenêtre (>6h)", r["fenetre"] ?: 0, BlueColor.copy(0.5f))
            RejectRow("Déjà évalués (cache)", r["cache"] ?: 0, BlueColor.copy(0.5f))
            RejectRow("Sans cotes (no_odds)", r["no_odds"] ?: 0, OrangeColor)
            RejectRow("Confiance insuffisante", r["conf"] ?: 0, OrangeColor)
            RejectRow("Modèle ≤ marché", r["mkt"] ?: 0, OrangeColor)
            RejectRow("EV trop faible (<8%)", r["ev"] ?: 0, RedColor)
            RejectRow("Zone dangereuse (IA)", r["zone"] ?: 0, RedColor)
            RejectRow("Joueur blacklisté (IA)", r["bl"] ?: 0, RedColor)
            RejectRow("Surface dangereuse (IA)", r["surf"] ?: 0, RedColor)
        }
    }
}

@Composable
private fun RejectRow(label: String, count: Int, color: Color) {
    Row(modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f))
        Spacer(Modifier.width(8.dp))
        Text(
            if (count == 0) "—" else "$count",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = if (count > 0) FontWeight.Bold else FontWeight.Normal,
            color = if (count > 0) color else MaterialTheme.colorScheme.outline,
        )
    }
}

@Composable
private fun NearMissRow(nm: NearMiss) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = OrangeColor.copy(0.08f)),
    ) {
        Row(modifier = Modifier.fillMaxWidth().padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("${nm.player1}  vs  ${nm.player2}",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium)
                Text("▸ ${nm.side}  @ ${String.format("%.2f", nm.odds)}" +
                    (nm.hours?.let { "  ·  ${String.format("%.1f", it)}h" } ?: ""),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (nm.league.isNotBlank()) {
                    Text(nm.league, style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline)
                }
            }
            Column(horizontalAlignment = Alignment.End) {
                Text("+${String.format("%.1f", nm.ev)}%",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold, color = OrangeColor)
                Text("EV", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}
