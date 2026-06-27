package com.tennisboss.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Surface
import androidx.compose.material3.VerticalDivider
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.foundation.clickable
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import com.tennisboss.app.ui.components.SkeletonList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tennisboss.app.data.UpcomingMatch
import com.tennisboss.app.data.Prediction
import com.tennisboss.app.data.WeatherAnalysis
import com.tennisboss.app.ui.components.BetBuilderView
import com.tennisboss.app.ui.components.ConfidenceBadge
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UpcomingScreen(vm: UpcomingViewModel = viewModel()) {
    // Charge automatiquement au premier affichage.
    LaunchedEffect(Unit) {
        if (vm.state is UpcomingUiState.Idle) vm.load()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            "Matchs à venir (Analyse IA)",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Cotes")
                Switch(
                    checked = vm.withOdds,
                    onCheckedChange = { vm.withOdds = it },
                )
            }
            Button(
                onClick = { vm.load() },
                enabled = vm.state !is UpcomingUiState.Loading,
            ) {
                Text("Rafraîchir")
            }
        }

        PullToRefreshBox(
            isRefreshing = vm.state is UpcomingUiState.Loading,
            onRefresh = { vm.load() },
            modifier = Modifier.fillMaxSize(),
        ) {
            when (val s = vm.state) {
                is UpcomingUiState.Loading -> SkeletonList(count = 5)
                is UpcomingUiState.Error -> Text(
                    s.message,
                    color = MaterialTheme.colorScheme.error,
                )
                is UpcomingUiState.Success -> {
                    if (s.matches.isEmpty()) {
                        Text("Aucun match à venir trouvé. Tire vers le bas pour réessayer.")
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

@Composable
private fun MatchCard(m: UpcomingMatch) {
    var expanded by remember { mutableStateOf(false) }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            // ── Ligne 1 : tournoi + date/surface ─────────────────────────────
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    m.tournament.ifBlank { "—" },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.weight(1f),
                )
                if (m.live) {
                    Text("🔴 LIVE", color = Color(0xFFD32F2F), fontWeight = FontWeight.Bold)
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        val surface = m.prediction?.surface?.takeIf { it.isNotBlank() }
                        if (surface != null) { SurfaceBadge(surface); Spacer(Modifier.size(8.dp)) }
                        Text("${m.date} ${m.time}", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }

            // ── Joueurs ───────────────────────────────────────────────────────
            Text("${m.player1_raw}  vs  ${m.player2_raw}", fontWeight = FontWeight.SemiBold)

            // ── Résultat (live/terminé) ───────────────────────────────────────
            m.result?.let { res ->
                Surface(color = MaterialTheme.colorScheme.surfaceVariant,
                    shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Row(modifier = Modifier.padding(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center) {
                        Text("SCORE : ${res.score}", style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.ExtraBold,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        if (res.winner.isNotBlank())
                            Text(" • WINNER: ${res.winner}",
                                style = MaterialTheme.typography.labelSmall,
                                color = Color(0xFF2E7D32))
                    }
                }
            }

            // ── Prédiction résumée (toujours visible) ────────────────────────
            val pred = m.prediction
            if (pred != null) {
                Row(modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically) {
                    Text("1er set : ${pred.player1} ${fmt(pred.prob1)} / ${pred.player2} ${fmt(pred.prob2)}",
                        modifier = Modifier.weight(1f),
                        style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
                    if (pred.confidence_label.isNotBlank())
                        ConfidenceBadge(pred.confidence_label, pred.confidence)
                }
                pred.favorite?.let {
                    Text("🏆 Favori : $it", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (pred.target_160 && pred.fair_odds != null) {
                    Text("🎯 1er set jouable : ${pred.favorite} @ cote juste ${pred.fair_odds} (≥1.60)",
                        style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Bold,
                        color = Color(0xFF00E5A0))
                }
            } else {
                Text("Joueur inconnu en base — pas de prédiction.",
                    style = MaterialTheme.typography.bodySmall, color = Color(0xFF8A6D00))
            }

            // ── Chevron expand/collapse ───────────────────────────────────────
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                Text(
                    if (expanded) "▲ Fermer détail" else "▼ Détail · météo · cotes",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // ── Section détail (dépliable) ────────────────────────────────────
            AnimatedVisibility(
                visible = expanded,
                enter = expandVertically(),
                exit = shrinkVertically(),
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    HorizontalDivider(thickness = 0.5.dp,
                        color = MaterialTheme.colorScheme.outlineVariant,
                        modifier = Modifier.padding(vertical = 2.dp))

                    if (pred != null) {
                        pred.surface?.let { surf ->
                            if (surf.isNotBlank()) Text("🏟 Surface : $surf",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                        }
                        Spacer(Modifier.height(2.dp))
                        BossStatsComparison(pred)
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

                    // Météo — seulement dans le détail
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
                            val windStr = w.wind_mph?.let { " · Vent ${it.toInt()} mph" } ?: ""
                            val rainStr = w.rain_mm?.takeIf { it > 0 }?.let { " · Pluie ${it}mm" } ?: ""
                            val humStr = w.humidity_pct?.let { " · Hum. ${it.toInt()}%" } ?: ""
                            val tempStr = w.temp_c?.let { "${it.toInt()}°C" } ?: ""
                            Text("$icon $tempStr ${w.conditions}$windStr$rainStr$humStr",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                        }
                    }

                    // Analyse conditions : style joueurs + météo + foule + honeypot
                    m.weather_analysis?.let { wa ->
                        HorizontalDivider(thickness = 0.5.dp,
                            color = MaterialTheme.colorScheme.outlineVariant,
                            modifier = Modifier.padding(vertical = 4.dp))
                        WeatherAnalysisCard(wa, m.player1_raw, m.player2_raw)
                    }

                    // Cotes marché
                    m.odds?.let { odds ->
                        HorizontalDivider(thickness = 0.5.dp,
                            color = MaterialTheme.colorScheme.outlineVariant,
                            modifier = Modifier.padding(vertical = 4.dp))
                        Text("Marché (match) : favori dom. ${fmt(odds.market_match_prob_home)} · cotes ${odds.home_odds}/${odds.away_odds}",
                            style = MaterialTheme.typography.bodySmall)
                        if (odds.books.isNotEmpty())
                            Text("Bookmakers : ${odds.books.joinToString(", ")}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline)
                    }

                    // Contexte pari : modèle vs marché
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
                        Text(ctx.label,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                            color = tagColor)
                        val edgeSign = if (ctx.edge_pct >= 0) "+" else ""
                        Text(
                            "Edge ${edgeSign}${String.format("%.1f", ctx.edge_pct)}% · " +
                            "Modèle: ${ctx.model_fav?.substringAfterLast(" ") ?: "?"} ${fmt(ctx.model_fav_prob)} · " +
                            "Marché: ${ctx.market_fav?.substringAfterLast(" ") ?: "?"} ${fmt(ctx.market_fav_prob)}",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

private fun fmt(v: Double): String = String.format(Locale.US, "%.1f%%", v)

@Composable
fun WeatherAnalysisCard(wa: WeatherAnalysis, p1Name: String, p2Name: String) {
    val p1Short = p1Name.substringAfterLast(" ")
    val p2Short = p2Name.substringAfterLast(" ")

    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
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
            val benefName = when (wi.beneficiary) {
                "p1" -> p1Short; "p2" -> p2Short; else -> ""
            }
            val wiColor = when (wi.impact_level) {
                "fort"   -> Color(0xFFFFD600)
                "modéré" -> Color(0xFF80CBC4)
                else     -> MaterialTheme.colorScheme.onSurfaceVariant
            }
            Text("🌤 Météo → $benefName avantagé · ${wi.label}",
                style = MaterialTheme.typography.labelSmall,
                color = wiColor)
        }

        // Avantage surface
        val sa = wa.surface_advantage
        if (sa != null && sa.label.isNotBlank()) {
            Text("🏟 ${sa.label}",
                style = MaterialTheme.typography.labelSmall,
                color = Color(0xFF80CBC4))
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
            val hpBenef = when (hp.beneficiary) {
                "p1" -> p1Short; "p2" -> p2Short; else -> hp.player.substringAfterLast(" ")
            }
            Surface(
                color = Color(0xFFFFD600).copy(alpha = 0.12f),
                shape = MaterialTheme.shapes.small,
            ) {
                Text(
                    "⚠️ HONEYPOT +${String.format("%.1f", hp.edge_pct)}% → $hpBenef (conditions non pricées)",
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    color = Color(0xFFFFD600),
                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                )
            }
        }
    }
}

@Composable
fun SurfaceBadge(tour: String) {
    val color = when {
        tour.contains("Clay", ignoreCase = true) -> Color(0xFFD84315) // Terre battue
        tour.contains("Grass", ignoreCase = true) -> Color(0xFF2E7D32) // Gazon
        else -> Color(0xFF1565C0) // Dur / Autre
    }
    Surface(
        color = color.copy(alpha = 0.1f),
        shape = CircleShape,
        modifier = Modifier.clip(CircleShape)
    ) {
        Text(
            text = if (tour.length > 10) tour.take(10) + "..." else tour,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
            style = MaterialTheme.typography.labelSmall,
            color = color,
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
fun BossStatsComparison(p: Prediction) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("Power Matchup", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            Text("Service vs Return", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        }
        
        // Un indicateur visuel de balance entre les deux joueurs
        val ratio = (p.prob1 / (p.prob1 + p.prob2)).toFloat()
        
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(p.player1.take(3).uppercase(), style = MaterialTheme.typography.labelSmall)
            LinearProgressIndicator(
                progress = { ratio },
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 8.dp)
                    .height(6.dp)
                    .clip(CircleShape),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.secondary.copy(alpha = 0.3f)
            )
            Text(p.player2.take(3).uppercase(), style = MaterialTheme.typography.labelSmall)
        }
    }
}
