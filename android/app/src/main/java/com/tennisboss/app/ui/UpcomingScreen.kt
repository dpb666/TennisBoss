package com.tennisboss.app.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.H2HSummary
import com.tennisboss.app.data.Prediction
import com.tennisboss.app.data.UpcomingMatch
import com.tennisboss.app.data.WeatherAnalysis
import com.tennisboss.app.ui.components.BetBuilderView
import com.tennisboss.app.ui.components.ConfidenceBadge
import com.tennisboss.app.ui.components.SkeletonList
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UpcomingScreen(vm: UpcomingViewModel = viewModel()) {
    LaunchedEffect(Unit) { if (vm.state is UpcomingUiState.Idle) vm.load() }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Matchs à venir", style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold)

        Row(modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Cotes")
                Switch(checked = vm.withOdds, onCheckedChange = { vm.withOdds = it })
            }
            Button(onClick = { vm.load() },
                enabled = vm.state !is UpcomingUiState.Loading) { Text("Rafraîchir") }
        }

        PullToRefreshBox(isRefreshing = vm.state is UpcomingUiState.Loading,
            onRefresh = { vm.load() }, modifier = Modifier.fillMaxSize()) {
            when (val s = vm.state) {
                is UpcomingUiState.Loading -> SkeletonList(count = 5)
                is UpcomingUiState.Error -> Text(s.message, color = MaterialTheme.colorScheme.error)
                is UpcomingUiState.Success -> {
                    if (s.matches.isEmpty()) {
                        Text("Aucun match à venir. Tire vers le bas pour réessayer.")
                    } else {
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            items(s.matches) { m -> MatchCard(m) }
                        }
                    }
                }
                else -> {}
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MatchCard(m: UpcomingMatch) {
    var expanded by remember { mutableStateOf(false) }
    val pred = m.prediction

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // ── Header : tournoi · round · surface · heure ────────────────────
            Row(modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically) {
                Row(verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(5.dp),
                    modifier = Modifier.weight(1f)) {
                    Text(m.tournament.ifBlank { "—" },
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary)
                    if (m.round.isNotBlank()) {
                        Text("·", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline)
                        Text(m.round, style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                if (m.live) {
                    Text("🔴 LIVE", color = Color(0xFFD32F2F), fontWeight = FontWeight.Bold)
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        val surface = pred?.surface?.takeIf { it.isNotBlank() }
                        if (surface != null) SurfaceBadge(surface)
                        Text("${m.date} ${m.time}", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline)
                    }
                }
            }

            // ── Résultat (live / terminé) ─────────────────────────────────────
            m.result?.let { res ->
                Surface(color = MaterialTheme.colorScheme.surfaceVariant,
                    shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Row(modifier = Modifier.padding(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center) {
                        Text("SCORE : ${res.score}", style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.ExtraBold)
                        if (res.winner.isNotBlank())
                            Text(" · ${res.winner}", style = MaterialTheme.typography.labelSmall,
                                color = Color(0xFF2E7D32))
                    }
                }
            }

            // ── Joueurs + rankings ────────────────────────────────────────────
            Row(modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically) {
                // Joueur 1
                Column(modifier = Modifier.weight(1f)) {
                    Text(m.player1_raw, fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.bodyMedium)
                    m.rank1?.let {
                        Text("Rang #$it", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline)
                    }
                }
                Text("vs", style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(horizontal = 10.dp))
                // Joueur 2
                Column(modifier = Modifier.weight(1f),
                    horizontalAlignment = Alignment.End) {
                    Text(m.player2_raw, fontWeight = FontWeight.Bold,
                        style = MaterialTheme.typography.bodyMedium)
                    m.rank2?.let {
                        Text("Rang #$it", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.outline)
                    }
                }
            }

            // ── Barres de probabilités ────────────────────────────────────────
            if (pred != null) {
                ProbBar(
                    label = "1er set",
                    name1 = pred.player1, prob1 = pred.prob1,
                    name2 = pred.player2, prob2 = pred.prob2,
                    barColor = MaterialTheme.colorScheme.primary,
                )
                if (pred.ml_prob1 != null && pred.ml_prob2 != null) {
                    ProbBar(
                        label = "Match",
                        name1 = pred.player1, prob1 = pred.ml_prob1,
                        name2 = pred.player2, prob2 = pred.ml_prob2,
                        barColor = Color(0xFF00E5A0),
                    )
                }
                if (pred.target_160 && pred.fair_odds != null) {
                    Text(
                        "🎯 1er set jouable : ${pred.favorite} @ cote juste ${pred.fair_odds} (≥1.60)",
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.Bold,
                        color = Color(0xFF00E5A0),
                    )
                }
            } else {
                Text("Joueur non analysé — données insuffisantes.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline)
            }

            // ── Chips : signaux rapides (toujours visibles) ───────────────────
            if (pred != null) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    // Niveau de confiance
                    ConfidenceBadge(pred.confidence_label, pred.confidence)

                    // Tag pari
                    m.bet_context?.let { ctx ->
                        val (chipColor, chipText) = when (ctx.tag) {
                            "good_bet"       -> Color(0xFF00C853) to "✅ Bon pari"
                            "value_underdog" -> Color(0xFFFFD600) to "💎 Value"
                            "bad_bet"        -> Color(0xFFFF5252) to "⚠️ Éviter"
                            else             -> MaterialTheme.colorScheme.outline to "Neutre"
                        }
                        SignalChip(chipText, chipColor)
                    }

                    // H2H
                    m.h2h?.let { h ->
                        if (h.total > 0) {
                            val s1 = m.player1_raw.substringAfterLast(" ")
                            val s2 = m.player2_raw.substringAfterLast(" ")
                            val chipText = when {
                                h.wins1 > h.wins2 -> "H2H $s1 ${h.wins1}-${h.wins2}"
                                h.wins2 > h.wins1 -> "H2H $s2 ${h.wins2}-${h.wins1}"
                                else              -> "H2H ${h.wins1}-${h.wins2}"
                            }
                            SignalChip(chipText, MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }

                    // Alerte météo
                    m.weather_analysis?.weather_impact?.let { wi ->
                        if (wi.beneficiary != "neutre") {
                            val b = when (wi.beneficiary) {
                                "p1" -> m.player1_raw.substringAfterLast(" ")
                                "p2" -> m.player2_raw.substringAfterLast(" ")
                                else -> ""
                            }
                            val icon = if (wi.impact_level == "fort") "⛅" else "🌤"
                            SignalChip("$icon → $b", Color(0xFF80CBC4))
                        }
                    }

                    // Honeypot
                    m.weather_analysis?.honeypot?.let { hp ->
                        if (hp.flag) {
                            val b = when (hp.beneficiary) {
                                "p1" -> m.player1_raw.substringAfterLast(" ")
                                "p2" -> m.player2_raw.substringAfterLast(" ")
                                else -> hp.player.substringAfterLast(" ")
                            }
                            SignalChip("⚠️ HONEYPOT $b +${String.format("%.1f", hp.edge_pct)}%",
                                Color(0xFFFFD600), bold = true)
                        }
                    }
                }
            }

            // ── Chevron ───────────────────────────────────────────────────────
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                Text(if (expanded) "▲ Fermer" else "▼ Analyse détaillée",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }

            // ── Section détail dépliable ──────────────────────────────────────
            AnimatedVisibility(visible = expanded,
                enter = expandVertically(), exit = shrinkVertically()) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    HorizontalDivider(thickness = 0.5.dp,
                        color = MaterialTheme.colorScheme.outlineVariant,
                        modifier = Modifier.padding(vertical = 2.dp))

                    if (pred != null) {
                        // Surface
                        pred.surface?.takeIf { it.isNotBlank() }?.let { surf ->
                            Text("🏟 Surface : $surf",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                        }
                        Spacer(Modifier.height(2.dp))

                        // Matchup bar
                        BossStatsComparison(pred)

                        // Scénarios score correct
                        pred.correct_score_probs?.let { scores ->
                            val top = scores.entries.sortedByDescending { it.value }.take(3)
                            if (top.isNotEmpty()) {
                                HorizontalDivider(thickness = 0.5.dp,
                                    color = MaterialTheme.colorScheme.outlineVariant,
                                    modifier = Modifier.padding(vertical = 4.dp))
                                SectionLabel("Scénarios les plus probables")
                                top.forEachIndexed { i, (scenario, pct) ->
                                    val alpha = if (i == 0) 1f else 0.7f
                                    Text(
                                        "• $scenario — ${String.format("%.1f", pct)}%",
                                        style = MaterialTheme.typography.bodySmall,
                                        fontWeight = if (i == 0) FontWeight.Bold else FontWeight.Normal,
                                        color = if (i == 0) Color(0xFF00E5A0)
                                            else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = alpha),
                                    )
                                }
                            }
                        }

                        HorizontalDivider(thickness = 0.5.dp,
                            color = MaterialTheme.colorScheme.outlineVariant,
                            modifier = Modifier.padding(vertical = 4.dp))
                        BetBuilderView(
                            name1 = pred.player1, name2 = pred.player2,
                            mlProb1 = pred.ml_prob1, mlProb2 = pred.ml_prob2,
                            set2Prob1 = pred.set2_prob1, set2Prob2 = pred.set2_prob2,
                            thirdSetProb = pred.total_sets_over,
                            correctScore = pred.correct_score_probs,
                            totalPointsOver = pred.total_points_over,
                            totalAcesAvg = pred.total_aces_avg,
                        )
                    }

                    // Météo brute
                    m.weather?.let { w ->
                        if (w.conditions.isNotBlank() || w.temp_c != null) {
                            HorizontalDivider(thickness = 0.5.dp,
                                color = MaterialTheme.colorScheme.outlineVariant,
                                modifier = Modifier.padding(vertical = 4.dp))
                            val icon = when {
                                w.conditions.contains("pluie") || w.conditions.contains("bruine") -> "🌧"
                                w.conditions.contains("orage") -> "⛈"
                                w.conditions.contains("nuag") -> "☁️"
                                w.conditions.contains("vent") -> "💨"
                                else -> "☀️"
                            }
                            val parts = listOfNotNull(
                                w.temp_c?.let { "${it.toInt()}°C" },
                                w.conditions.takeIf { it.isNotBlank() },
                                w.wind_mph?.let { "Vent ${it.toInt()} mph" },
                                w.rain_mm?.takeIf { it > 0 }?.let { "Pluie ${it}mm" },
                                w.humidity_pct?.let { "Hum. ${it.toInt()}%" },
                            )
                            Text("$icon ${parts.joinToString(" · ")}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                        }
                    }

                    // Analyse conditions + styles + honeypot
                    m.weather_analysis?.let { wa ->
                        HorizontalDivider(thickness = 0.5.dp,
                            color = MaterialTheme.colorScheme.outlineVariant,
                            modifier = Modifier.padding(vertical = 4.dp))
                        SectionLabel("Conditions de jeu")
                        WeatherAnalysisCard(wa, m.player1_raw, m.player2_raw)
                    }

                    // Cotes marché
                    m.odds?.let { odds ->
                        HorizontalDivider(thickness = 0.5.dp,
                            color = MaterialTheme.colorScheme.outlineVariant,
                            modifier = Modifier.padding(vertical = 4.dp))
                        SectionLabel("Marché")
                        Text(
                            "Favori marché ${fmt(odds.market_match_prob_home)} · " +
                            "Cotes ${odds.home_odds} / ${odds.away_odds}",
                            style = MaterialTheme.typography.bodySmall,
                        )
                        if (odds.books.isNotEmpty())
                            Text(odds.books.joinToString(", "),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                    }

                    // Contexte pari détail
                    m.bet_context?.let { ctx ->
                        HorizontalDivider(thickness = 0.5.dp,
                            color = MaterialTheme.colorScheme.outlineVariant,
                            modifier = Modifier.padding(vertical = 4.dp))
                        val tagColor = when (ctx.tag) {
                            "good_bet"       -> Color(0xFF00C853)
                            "value_underdog" -> Color(0xFFFFD600)
                            "bad_bet"        -> Color(0xFFFF5252)
                            else             -> MaterialTheme.colorScheme.onSurfaceVariant
                        }
                        Text(ctx.label, style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold, color = tagColor)
                        val sign = if (ctx.edge_pct >= 0) "+" else ""
                        Text(
                            "Edge ${sign}${String.format("%.1f", ctx.edge_pct)}% · " +
                            "Modèle : ${ctx.model_fav?.substringAfterLast(" ") ?: "?"} ${fmt(ctx.model_fav_prob)} · " +
                            "Marché : ${ctx.market_fav?.substringAfterLast(" ") ?: "?"} ${fmt(ctx.market_fav_prob)}",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    // H2H détail
                    m.h2h?.let { h ->
                        if (h.total > 0) {
                            HorizontalDivider(thickness = 0.5.dp,
                                color = MaterialTheme.colorScheme.outlineVariant,
                                modifier = Modifier.padding(vertical = 4.dp))
                            SectionLabel("Face-à-face")
                            val s1 = m.player1_raw.substringAfterLast(" ")
                            val s2 = m.player2_raw.substringAfterLast(" ")
                            Text("$s1 ${h.wins1} – ${h.wins2} $s2 (${h.total} matchs)",
                                style = MaterialTheme.typography.bodySmall,
                                fontWeight = FontWeight.SemiBold)
                            h.last_winner?.let { lw ->
                                Text("Dernier vainqueur : ${lw.substringAfterLast(" ")}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.outline)
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── Composables utilitaires ───────────────────────────────────────────────────

@Composable
private fun ProbBar(
    label: String,
    name1: String, prob1: Double,
    name2: String, prob2: Double,
    barColor: Color,
) {
    val ratio = (prob1 / (prob1 + prob2)).toFloat()
    val fav1 = prob1 >= prob2
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${name1.substringAfterLast(" ").take(10)} ${String.format("%.1f", prob1)}%",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = if (fav1) FontWeight.Bold else FontWeight.Normal,
                color = if (fav1) barColor else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(label, style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline)
            Text(
                "${String.format("%.1f", prob2)}% ${name2.substringAfterLast(" ").take(10)}",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = if (!fav1) FontWeight.Bold else FontWeight.Normal,
                color = if (!fav1) barColor else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        LinearProgressIndicator(
            progress = { ratio },
            modifier = Modifier.fillMaxWidth().height(5.dp).clip(CircleShape),
            color = barColor,
            trackColor = barColor.copy(alpha = 0.18f),
        )
    }
}

@Composable
private fun SignalChip(text: String, color: Color, bold: Boolean = false) {
    Surface(color = color.copy(alpha = 0.12f), shape = RoundedCornerShape(16.dp)) {
        Text(text,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal,
            color = color)
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text, style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.Bold,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(bottom = 2.dp))
}

private fun fmt(v: Double): String = String.format(Locale.US, "%.1f%%", v)

@Composable
fun WeatherAnalysisCard(wa: WeatherAnalysis, p1Name: String, p2Name: String) {
    val p1Short = p1Name.substringAfterLast(" ")
    val p2Short = p2Name.substringAfterLast(" ")

    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        // Styles joueurs
        val pr1 = wa.player1
        val pr2 = wa.player2
        if (pr1 != null || pr2 != null) {
            val s1 = pr1?.style_label ?: "?"
            val s2 = pr2?.style_label ?: "?"
            val icon1 = if (s1.contains("Serveur")) "🎯" else if (s1.contains("Baseliner")) "🔄" else "⚡"
            val icon2 = if (s2.contains("Serveur")) "🎯" else if (s2.contains("Baseliner")) "🔄" else "⚡"
            Text("$icon1 $p1Short: $s1  ·  $icon2 $p2Short: $s2",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        // Impact météo
        val wi = wa.weather_impact
        if (wi != null && wi.label.isNotBlank() && wi.beneficiary != "neutre") {
            val b = when (wi.beneficiary) { "p1" -> p1Short; "p2" -> p2Short; else -> "" }
            val wiColor = when (wi.impact_level) {
                "fort"   -> Color(0xFFFFD600)
                "modéré" -> Color(0xFF80CBC4)
                else     -> MaterialTheme.colorScheme.onSurfaceVariant
            }
            Text("🌤 Météo favorise $b · ${wi.label}",
                style = MaterialTheme.typography.labelSmall, color = wiColor)
        }

        // Avantage surface
        val sa = wa.surface_advantage
        if (sa != null && sa.label.isNotBlank()) {
            Text("🏟 ${sa.label}",
                style = MaterialTheme.typography.labelSmall, color = Color(0xFF80CBC4))
        }

        // Foule
        val crowd = wa.crowd
        if (crowd != null && crowd.beneficiary != "neutre" && crowd.label.isNotBlank()) {
            Text("👥 ${crowd.label}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        // Honeypot
        val hp = wa.honeypot
        if (hp != null && hp.flag) {
            val b = when (hp.beneficiary) {
                "p1" -> p1Short; "p2" -> p2Short; else -> hp.player.substringAfterLast(" ")
            }
            Surface(color = Color(0xFFFFD600).copy(alpha = 0.12f),
                shape = MaterialTheme.shapes.small) {
                Text(
                    "⚠️ HONEYPOT +${String.format("%.1f", hp.edge_pct)}% → $b (conditions non pricées)",
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold, color = Color(0xFFFFD600),
                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                )
            }
        }
    }
}

@Composable
fun SurfaceBadge(tour: String) {
    val color = when {
        tour.contains("Clay", ignoreCase = true)  -> Color(0xFFD84315)
        tour.contains("Grass", ignoreCase = true) -> Color(0xFF2E7D32)
        else                                       -> Color(0xFF1565C0)
    }
    Surface(color = color.copy(alpha = 0.1f), shape = CircleShape,
        modifier = Modifier.clip(CircleShape)) {
        Text(
            text = if (tour.length > 10) tour.take(10) + "…" else tour,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
            style = MaterialTheme.typography.labelSmall,
            color = color, fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
fun BossStatsComparison(p: Prediction) {
    val ratio = (p.prob1 / (p.prob1 + p.prob2)).toFloat()
    Column(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Power Matchup", style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            Text("1er set dominance", style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline)
        }
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(p.player1.take(3).uppercase(), style = MaterialTheme.typography.labelSmall)
            LinearProgressIndicator(
                progress = { ratio },
                modifier = Modifier.weight(1f).padding(horizontal = 8.dp).height(6.dp).clip(CircleShape),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.secondary.copy(alpha = 0.3f),
            )
            Text(p.player2.take(3).uppercase(), style = MaterialTheme.typography.labelSmall)
        }
    }
}
