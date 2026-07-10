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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.HorizontalDivider
import com.tennisboss.app.data.ClvAgg
import com.tennisboss.app.data.ClvRecent
import com.tennisboss.app.data.ClvResponse
import com.tennisboss.app.data.IntelligenceStats
import com.tennisboss.app.data.LearnerStats
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
                is EdgeUiState.Success -> Content(s.data.clv, s.data.intelligence, s.data.learner)
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
private fun Content(d: ClvResponse, intel: IntelligenceStats, learner: LearnerStats) {
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
            IntelligenceCard(intel, learner)
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
        // ── Scanner post-filtre (signal propre, sans historique contaminé) ──
        if ((d.scanner.n_settled ?: 0) > 0) {
            item { ScannerStatsCard(d.scanner) }
        }

        item {
            Text(d.note, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline)
        }

        // ── Intelligence autonome ─────────────────────────────────────
        item { IntelligenceCard(intel, learner) }

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
                r.honeypot?.let { hp ->
                    if (hp.flag) {
                        val b = hp.player.substringAfterLast(" ")
                        SignalChip("⚠️ HONEYPOT $b +${String.format("%.1f", hp.edge_pct)}%",
                            Color(0xFFFFD600), bold = true)
                    }
                }
            }
            Column(horizontalAlignment = androidx.compose.ui.Alignment.End) {
                Text(signedPct(r.clv_pct), fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.bodyMedium, color = clvColor(r.clv_pct))
                Text(
                    when (r.result) { 1 -> "✅ gagné"; 0 -> "❌ perdu"; else -> "⏳" },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
                r.pnl_flat?.let { pnl ->
                    Text(
                        "${if (pnl >= 0) "+" else ""}${"%.1f".format(pnl)}u",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (pnl >= 0) GoodColor else BadColor,
                    )
                }
            }
        }
    }
}

@Composable
private fun IntelligenceCard(intel: IntelligenceStats, learner: LearnerStats) {
    val driftColor = when {
        intel.accuracy_drift_pts > 5.0 -> GoodColor
        intel.accuracy_drift_pts < -5.0 -> BadColor
        else -> WarnColor
    }
    val driftSign = if (intel.accuracy_drift_pts >= 0) "+" else ""

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("🧠 Intelligence autonome", fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall)
                Text(
                    "${driftSign}${String.format("%.1f", intel.accuracy_drift_pts)} pts",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    color = driftColor,
                )
            }
            Text(
                "Drift modèle : précision récente vs all-time",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            HorizontalDivider()

            // Zones dangereuses
            if (learner.zones.isNotEmpty()) {
                Text("Zones bloquées (ROI systématiquement négatif)",
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = BadColor)
                learner.zones.forEach { zone ->
                    val label = buildString {
                        append("EV ${zone.ev_bucket}%")
                        zone.odds_bucket?.let { append(" · cotes $it") }
                        zone.surface?.let { if (it != "unknown" && it.isNotBlank()) append(" · $it") }
                        append("  →  ROI ${String.format("%.0f%%", zone.roi * 100)}  (n=${zone.n})")
                    }
                    Text("🚫 $label", style = MaterialTheme.typography.bodySmall, color = BadColor)
                }
            } else {
                Text("Aucune zone dangereuse détectée",
                    style = MaterialTheme.typography.bodySmall,
                    color = GoodColor)
            }

            // Surfaces en danger
            if (intel.surface_danger.isNotEmpty()) {
                Text("⚠️ Surfaces en danger : ${intel.surface_danger.joinToString(", ")}",
                    style = MaterialTheme.typography.bodySmall, color = WarnColor)
            }

            // Joueurs blacklistés
            if (intel.blacklist.isNotEmpty()) {
                HorizontalDivider()
                Text("Joueurs sur-évalués (bloqués par l'IA)",
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                // Chips pour les 6 premiers
                val shown = intel.blacklist.take(6)
                val overflow = intel.blacklist.size - shown.size
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    shown.take(3).forEach { name ->
                        AssistChip(
                            onClick = {},
                            label = { Text(name.take(12), style = MaterialTheme.typography.labelSmall) },
                            colors = AssistChipDefaults.assistChipColors(
                                containerColor = BadColor.copy(alpha = 0.12f)
                            ),
                        )
                    }
                }
                if (shown.size > 3) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        shown.drop(3).forEach { name ->
                            AssistChip(
                                onClick = {},
                                label = { Text(name.take(12), style = MaterialTheme.typography.labelSmall) },
                                colors = AssistChipDefaults.assistChipColors(
                                    containerColor = BadColor.copy(alpha = 0.12f)
                                ),
                            )
                        }
                    }
                }
                if (overflow > 0) {
                    Text("+ $overflow autres", style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline)
                }
            }
        }
    }
}


@Composable
private fun ScannerStatsCard(s: com.tennisboss.app.data.ClvAgg) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = GoodColor.copy(alpha = 0.08f)),
    ) {
        Column(modifier = Modifier.fillMaxWidth().padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text("🎯 Scanner (post-filtre)", fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.titleSmall)
                Text("depuis 03/07", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline)
            }
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                StatCard("ROI", signedPct(s.roi_flat_pct), roiColor(s.roi_flat_pct),
                    Modifier.weight(1f), sub = "${s.n_settled} réglés")
                StatCard("Win rate", pct(s.win_rate_pct), roiColor((s.win_rate_pct ?: 0.0) - 50.0),
                    Modifier.weight(1f), sub = "${s.n_picks} picks")
            }
            Text("Picks avec filtres actifs : dead zone, Bet365, confiance ITF 0.65",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
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
