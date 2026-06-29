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
import androidx.compose.material3.CardDefaults
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
import com.tennisboss.app.data.ClvAgg
import com.tennisboss.app.data.ClvRecent
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.ui.components.SkeletonList

private val GoodColor = Color(0xFF00E5A0)
private val BadColor = Color(0xFFFF5C7A)
private val AccentColor = Color(0xFF4F8CFF)
private val WarnColor = Color(0xFFFFB020)

/**
 * Onglet « Edge » : le CLV (Closing Line Value) — la preuve qu'on bat le marché.
 * Indicateur AVANCÉ de profitabilité, fiable bien avant le ROI. Source /api/clv.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EdgeScreen(vm: EdgeViewModel = viewModel()) {
    LaunchedEffect(Unit) { vm.load() }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("💰 Edge — Closing Line Value", style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold)
        Text(
            "Est-ce qu'on bat le marché ? Le CLV se voit avant le ROI.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        PullToRefreshBox(
            isRefreshing = vm.state is EdgeUiState.Loading,
            onRefresh = { vm.load() },
            modifier = Modifier.fillMaxSize(),
        ) {
            when (val s = vm.state) {
                is EdgeUiState.Loading -> SkeletonList(count = 3)
                is EdgeUiState.Error ->
                    Text(s.message, color = MaterialTheme.colorScheme.error)
                is EdgeUiState.Success -> Content(s.data)
                else -> {}
            }
        }
    }
}

private fun verdictColor(verdict: String): Color = when (verdict) {
    "edge_prouvé" -> GoodColor
    "prometteur" -> WarnColor
    "pas_d_edge" -> BadColor
    else -> AccentColor
}

@Composable
private fun Content(d: ClvResponse) {
    val g = d.global
    if (g.n_clv == 0 && g.n_settled == 0) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            VerdictBanner(d.verdict, d.verdict_label)
            Text(
                "Aucun pick value encore réglé. Ouvre l'onglet Value pour générer " +
                    "des picks : leur cote sera comparée à la clôture, puis au résultat.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        return
    }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { VerdictBanner(d.verdict, d.verdict_label) }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                StatCard("CLV moyen", signedPct(g.avg_clv_pct), clvColor(g.avg_clv_pct),
                    Modifier.weight(1f), sub = "${g.n_clv} picks")
                StatCard("Bat la clôture", pct(g.beat_closing_pct),
                    beatColor(g.beat_closing_pct, g.beat_closing_ci95), Modifier.weight(1f),
                    sub = ci95(g.beat_closing_pct, g.beat_closing_ci95))
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                StatCard("ROI flat", signedPct(g.roi_flat_pct), roiColor(g.roi_flat_pct),
                    Modifier.weight(1f), sub = "${g.n_settled} réglés")
                StatCard("P&L Kelly", units(g.pnl_kelly_units), roiColor(g.pnl_kelly_units),
                    Modifier.weight(1f), sub = "unités bankroll")
            }
        }
        item {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("CLV par palier de confiance", fontWeight = FontWeight.Bold)
                    ConfRow("Élevée (≥75%)", d.by_confidence.high)
                    ConfRow("Modérée (60-75%)", d.by_confidence.medium)
                    ConfRow("Faible (<60%)", d.by_confidence.low)
                }
            }
        }
        item {
            Text(d.note, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline)
        }
        if (d.recent.isNotEmpty()) {
            item {
                Text("Derniers picks", fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall)
            }
            items(d.recent) { RecentRow(it) }
        }
    }
}

@Composable
private fun VerdictBanner(verdict: String, label: String) {
    val c = verdictColor(verdict)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = c.copy(alpha = 0.12f)),
    ) {
        Text(
            label.ifBlank { "—" },
            modifier = Modifier.padding(14.dp),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
            color = c,
        )
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
private fun ConfRow(label: String, a: ClvAgg) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Text(
            if (a.n_clv > 0) "${signedPct(a.avg_clv_pct)}  ·  ${a.n_clv}p"
            else "—",
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = if (a.n_clv > 0) clvColor(a.avg_clv_pct)
            else MaterialTheme.colorScheme.outline,
        )
    }
}

@Composable
private fun RecentRow(r: ClvRecent) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(Modifier.weight(1f)) {
                if (r.date.isNotBlank()) {
                    Text(utcToLocalLabel(r.date),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary)
                }
                Text("${r.player1}  vs  ${r.player2}",
                    style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                Text(
                    "▸ ${r.side}  @ ${odds(r.pick_odds)} → clôt. ${odds(r.closing_odds)}" +
                        (r.closing_src?.let { if (it == "last_seen") "  (approx.)" else "" } ?: ""),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = androidx.compose.ui.Alignment.End) {
                Text(signedPct(r.clv_pct), fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.bodyMedium, color = clvColor(r.clv_pct))
                Text(
                    when (r.result) { 1 -> "✅ gagné"; 0 -> "❌ perdu"; else -> "⏳" },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
        }
    }
}

private fun pct(v: Double?): String = v?.let { String.format("%.0f%%", it) } ?: "—"
private fun signedPct(v: Double?): String = v?.let { String.format("%+.1f%%", it) } ?: "—"
private fun units(v: Double?): String = v?.let { String.format("%+.2f", it) } ?: "—"
private fun odds(v: Double?): String = v?.let { String.format("%.2f", it) } ?: "—"
private fun ci95(beat: Double?, ci: Double?): String =
    if (beat != null && ci != null) "±${String.format("%.0f", ci)} pts (IC95)" else "à venir"

private fun clvColor(v: Double?): Color = when {
    v == null -> AccentColor
    v > 0 -> GoodColor
    v < 0 -> BadColor
    else -> AccentColor
}

private fun roiColor(v: Double?): Color = when {
    v == null -> AccentColor
    v >= 0 -> GoodColor
    else -> BadColor
}

private fun beatColor(beat: Double?, ci: Double?): Color = when {
    beat == null -> AccentColor
    ci != null && beat - ci > 50.0 -> GoodColor   // significativement > 50%
    beat > 50.0 -> WarnColor
    else -> BadColor
}
