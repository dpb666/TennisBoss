package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.ui.tooling.preview.Preview
import com.tennisboss.app.data.*
import kotlin.math.abs

private val GoodColor = Color(0xFF00E5A0)
private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)
private val WarnColor = Color(0xFFFF5C7A)
private val AccentColor = Color(0xFF4F8CFF)
private val WatchColor = Color(0xFFFFB800)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MatchDetailScreen(
    p1: String,
    p2: String,
    surface: String? = null,
    eventId: String? = null,
    onBack: () -> Unit,
    vm: MatchDetailViewModel = viewModel()
) {
    LaunchedEffect(p1, p2) {
        vm.loadMatchDetail(p1, p2, surface, eventId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Rapport Scout Pro", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack, modifier = Modifier.testTag("matchdetail_back")) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Retour")
                    }
                }
            )
        }
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding).testTag("matchdetail_screen")) {
            when (val s = vm.uiState) {
                is MatchDetailUiState.Loading -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                is MatchDetailUiState.Error -> Text(s.message, color = WarnColor, modifier = Modifier.padding(16.dp))
                is MatchDetailUiState.Success -> MatchDetailContent(
                    s.player1, s.player2, s.insight, s.intelligence, s.h2h, surface
                )
                else -> {}
            }
        }
    }
}

@Composable
private fun MatchDetailContent(
    p1: PlayerDetail,
    p2: PlayerDetail,
    insight: InsightResponse,
    intelligence: MatchIntelligence,
    h2h: H2H?,
    surface: String? = null,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        ComparisonHeader(p1, p2)
        ScoutReportSection(p1, p2, insight, intelligence, h2h, surface)
        SurfaceEloComparison(p1, p2)
        PremiumSignalsSection(insight)
        FormSection(p1, p2, insight)
        h2h?.let { H2HSection(it) }
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun ScoutReportSection(
    p1: PlayerDetail,
    p2: PlayerDetail,
    insight: InsightResponse,
    intelligence: MatchIntelligence,
    h2h: H2H?,
    surface: String?,
) {
    Card(
        modifier = Modifier.fillMaxWidth().testTag("scout_report"),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f)
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            SectionTitle("📋 Rapport Scout Analyste", Icons.Default.Analytics)

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text(
                        "TIS ${intelligence.tis.toInt()}/100",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.ExtraBold,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    if (intelligence.favorite.isNotBlank()) {
                        Text(
                            "Favori : ${intelligence.favorite}",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                BettingRecommendationBadge(intelligence.recommendation)
            }

            if (intelligence.ev_pct != 0.0 || intelligence.market_odds != null) {
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    intelligence.market_odds?.let { odds ->
                        Text(
                            "Cote marché : $odds",
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                    if (intelligence.ev_pct != 0.0) {
                        val evColor = if (intelligence.ev_pct > 0) GoodColor else WarnColor
                        Text(
                            "EV ${String.format("%+.1f", intelligence.ev_pct)}%",
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                            color = evColor,
                        )
                    }
                    intelligence.fair_odds?.let { fair ->
                        Text(
                            "Cote juste : $fair",
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                }
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))

            AnalysisRow(Icons.Default.Terrain, "Avantage surface", surfaceAdvantageText(surface, p1, p2, intelligence))
            AnalysisRow(Icons.AutoMirrored.Filled.TrendingUp, "Avantage forme", formAdvantageText(insight))
            AnalysisRow(Icons.Default.SportsTennis, "Analyse service", serveAnalysisText(p1, p2, insight))
            AnalysisRow(Icons.Default.Replay, "Analyse retour", returnAnalysisText(p1, p2, insight))
            AnalysisRow(Icons.Default.History, "Analyse H2H", h2hAnalysisText(h2h, insight, p1.name, p2.name))

            if (intelligence.why.isNotEmpty() || intelligence.risks.isNotEmpty()) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))
                if (intelligence.why.isNotEmpty()) {
                    Text("Pourquoi", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall, color = GoodColor)
                    intelligence.why.forEach { bullet ->
                        Text("• $bullet", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface)
                    }
                }
                if (intelligence.risks.isNotEmpty()) {
                    Spacer(Modifier.height(4.dp))
                    Text("Risques", fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall, color = WarnColor)
                    intelligence.risks.forEach { bullet ->
                        Text("• $bullet", style = MaterialTheme.typography.bodySmall, color = WarnColor.copy(alpha = 0.85f))
                    }
                }
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))

            Text(
                buildSynthesis(intelligence, p1.name, p2.name),
                style = MaterialTheme.typography.bodyMedium,
                fontStyle = FontStyle.Italic,
                color = MaterialTheme.colorScheme.onSurface,
                lineHeight = 22.sp,
            )
        }
    }
}

@Composable
private fun BettingRecommendationBadge(recommendation: String) {
    val (bg, fg, label) = when (recommendation) {
        "STRONG_BET" -> Triple(GoodColor, Color(0xFF00251A), "PARI FORT")
        "VALUE_BET" -> Triple(AccentColor, Color.White, "VALUE BET")
        "WATCH" -> Triple(WatchColor, Color(0xFF2A1F00), "À SURVEILLER")
        else -> Triple(WarnColor, Color.White, "PAS DE PARI")
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(bg)
            .padding(horizontal = 12.dp, vertical = 6.dp)
            .testTag("betting_badge_$recommendation"),
    ) {
        Text(label, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.ExtraBold, color = fg)
    }
}

@Composable
private fun AnalysisRow(icon: ImageVector, title: String, description: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.Top,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
        Column {
            Text(title, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
            Text(description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun lastName(name: String): String = name.split(" ").last()

private fun surfaceAdvantageText(
    surface: String?,
    p1: PlayerDetail,
    p2: PlayerDetail,
    intelligence: MatchIntelligence,
): String {
    val surf = surface ?: intelligence.surface
    if (surf != null) {
        val e1 = p1.elo?.by_surface?.get(surf) ?: 1500.0
        val e2 = p2.elo?.by_surface?.get(surf) ?: 1500.0
        val diff = e1 - e2
        val surfLabel = surf.replaceFirstChar { it.uppercase() }
        return when {
            diff > 20 -> "${lastName(p1.name)} avantagé sur $surfLabel (+${diff.toInt()} ELO, ${e1.toInt()} vs ${e2.toInt()})"
            diff < -20 -> "${lastName(p2.name)} avantagé sur $surfLabel (+${abs(diff).toInt()} ELO, ${e2.toInt()} vs ${e1.toInt()})"
            else -> "Équilibre sur $surfLabel (${e1.toInt()} vs ${e2.toInt()} ELO) — score TIS ${intelligence.categories.surface.toInt()}/25"
        }
    }
    return "Surface non spécifiée — score TIS surface ${intelligence.categories.surface.toInt()}/25"
}

private fun formAdvantageText(insight: InsightResponse): String {
    val sig = insight.form_signals.maxByOrNull { abs(it.diff_pts) }
    return if (sig != null) {
        "${lastName(sig.player)} en ${sig.direction} (${String.format("%+.1f", sig.diff_pts)} pts vs carrière, ${String.format("%.0f", sig.recent_form_pct)}% récent)"
    } else {
        "Forme récente équilibrée — pas de bascule significative détectée"
    }
}

private fun serveAnalysisText(p1: PlayerDetail, p2: PlayerDetail, insight: InsightResponse): String {
    val factor = insight.factors.find { it.key == "serve" }
    val s1 = p1.serve * 100
    val s2 = p2.serve * 100
    val leader = factor?.favors?.let { lastName(it) }
        ?: if (s1 > s2 + 1) lastName(p1.name)
        else if (s2 > s1 + 1) lastName(p2.name)
        else "équilibre"
    return "Hold ${String.format("%.0f", s1)}% vs ${String.format("%.0f", s2)}% — avantage $leader"
}

private fun returnAnalysisText(p1: PlayerDetail, p2: PlayerDetail, insight: InsightResponse): String {
    val r1 = insight.factors.find { it.key == "return1" }
    val r2 = insight.factors.find { it.key == "return2" }
    val ret1 = p1.return1 * 100
    val ret2 = p2.return1 * 100
    val ret1b = p1.return2 * 100
    val ret2b = p2.return2 * 100
    val leader = r1?.favors?.let { lastName(it) }
        ?: if (ret1 + ret1b > ret2 + ret2b + 2) lastName(p1.name)
        else if (ret2 + ret2b > ret1 + ret1b + 2) lastName(p2.name)
        else "équilibre"
    val r2note = r2?.let { " · 2e balle favorise ${it.favors?.let { n -> lastName(n) } ?: "—"}" } ?: ""
    return "Break 1re balle ${String.format("%.0f", ret1)}%/${String.format("%.0f", ret2)}% · 2e balle ${String.format("%.0f", ret1b)}%/${String.format("%.0f", ret2b)}% — $leader$r2note"
}

private fun h2hAnalysisText(h2h: H2H?, insight: InsightResponse, p1: String, p2: String): String {
    val h2hFactor = insight.factors.find { it.key == "h2h" }
    if (h2h != null && h2h.total > 0) {
        val leader = h2h.leader?.let { lastName(it) } ?: "équilibre"
        return "${h2h.wins1}-${h2h.wins2} (${h2h.total} matchs) — leader $leader"
    }
    h2hFactor?.let { f ->
        val fav = f.favors?.let { lastName(it) } ?: "équilibre"
        return "Historique limité — modèle favorise $fav (${String.format("%.0f", f.value1 * 100)}% vs ${String.format("%.0f", f.value2 * 100)}%)"
    }
    return "Pas de confrontations directes significatives en base"
}

private fun buildSynthesis(intelligence: MatchIntelligence, p1: String, p2: String): String {
    val fav = lastName(intelligence.favorite.ifBlank { p1 })
    val tierFr = when (intelligence.recommendation) {
        "STRONG_BET" -> "nous positionnons un pari fort"
        "VALUE_BET" -> "une value bet est identifiée"
        "WATCH" -> "le match mérite une surveillance active"
        else -> "nous déconseillons un engagement"
    }
    val tis = intelligence.tis.toInt()
    val prob = if (intelligence.model_prob > 0) {
        " avec ${String.format("%.0f", intelligence.model_prob * 100)}% de probabilité modèle"
    } else ""
    val ev = if (intelligence.ev_pct != 0.0) {
        " L'edge marché estimé est de ${String.format("%+.1f", intelligence.ev_pct)}%."
    } else ""
    val topWhy = intelligence.why.firstOrNull()?.let { " Signal clé : $it." } ?: ""
    val topRisk = intelligence.risks.firstOrNull()?.let { " Point de vigilance : $it." } ?: ""
    return "Synthèse analyste — $fav ressort comme favori (TIS $tis/100$prob) ; $tierFr.$ev$topWhy$topRisk"
}

@Composable
private fun ComparisonHeader(p1: PlayerDetail, p2: PlayerDetail) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(16.dp).fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            PlayerBrief(p1, P1Color, Alignment.Start)
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("VS", fontWeight = FontWeight.ExtraBold, fontSize = 20.sp, color = MaterialTheme.colorScheme.outline)
                Text("1er Set", style = MaterialTheme.typography.labelSmall)
            }
            PlayerBrief(p2, P2Color, Alignment.End)
        }
    }
}

@Composable
private fun PlayerBrief(p: PlayerDetail, color: Color, align: Alignment.Horizontal) {
    Column(horizontalAlignment = align) {
        Text(p.name, fontWeight = FontWeight.Bold, color = color, style = MaterialTheme.typography.titleMedium)
        Text("ELO: ${p.rating.toInt()}", style = MaterialTheme.typography.bodySmall)
        Text("Rank: #${p.elo?.rank ?: "?"}", style = MaterialTheme.typography.bodySmall)
        Text("Service : ${String.format("%.0f%%", p.serve * 100)}", style = MaterialTheme.typography.labelSmall)
        Text("Retour 1re/2e : ${String.format("%.0f%%", p.return1 * 100)}/${String.format("%.0f%%", p.return2 * 100)}", style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
private fun SurfaceEloComparison(p1: PlayerDetail, p2: PlayerDetail) {
    val surfaces = listOf("clay", "hard", "grass")
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionTitle("📊 ELO par Surface", Icons.Default.History)
        surfaces.forEach { surf ->
            val e1 = p1.elo?.by_surface?.get(surf) ?: 1500.0
            val e2 = p2.elo?.by_surface?.get(surf) ?: 1500.0
            SurfaceEloRow(surf.replaceFirstChar { it.uppercase() }, e1, e2)
        }
    }
}

@Composable
private fun SurfaceEloRow(label: String, e1: Double, e2: Double) {
    val ratio = (e1 / (e1 + e2)).toFloat()
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(label, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            Text("${e1.toInt()} vs ${e2.toInt()}", style = MaterialTheme.typography.labelSmall)
        }
        Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(MaterialTheme.colorScheme.surfaceVariant)) {
            Box(Modifier.fillMaxWidth(ratio).fillMaxSize().background(P1Color))
        }
    }
}

@Composable
private fun PremiumSignalsSection(insight: InsightResponse) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionTitle("🧠 Intelligence Sportive", Icons.Default.ElectricBolt)
        insight.fatigue_signals.forEach { f ->
            SignalCard(Icons.Default.FitnessCenter, "Fatigue : ${f.player}", "${f.matches_recent} matchs en ${f.window_days}j", WarnColor)
        }
        insight.rest_days_signals.forEach { r ->
            val label = if (r.flag == "enchainement_rapide") "Enchaînement rapide" else "Retour après coupure"
            SignalCard(Icons.Default.Bedtime, "Repos : ${r.player}", "$label — ${r.rest_days}j depuis le dernier match", WarnColor)
        }
        insight.clutch_signals.forEach { c ->
            val desc = listOfNotNull(
                c.bp_save_rate?.let { "BP Saved: ${String.format("%.0f%%", it*100)}" },
                c.tb_win_rate?.let { "TB Win: ${String.format("%.0f%%", it*100)}" }
            ).joinToString(" · ")
            SignalCard(Icons.Default.Star, "Clutch : ${c.player}", desc, GoodColor)
        }
        insight.opponent_quality_signals.forEach { o ->
            SignalCard(Icons.AutoMirrored.Filled.TrendingUp, "Qualité opposition : ${o.player}", o.direction, AccentColor)
        }
    }
}

@Composable
private fun SignalCard(icon: ImageVector, title: String, desc: String, color: Color) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.1f))
    ) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(24.dp))
            Spacer(Modifier.width(12.dp))
            Column {
                Text(title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium, color = color)
                Text(desc, style = MaterialTheme.typography.labelSmall, color = color.copy(alpha = 0.8f))
            }
        }
    }
}

@Composable
private fun FormSection(p1: PlayerDetail, p2: PlayerDetail, insight: InsightResponse) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionTitle("📈 Forme & Momentum", Icons.AutoMirrored.Filled.TrendingUp)
        insight.form_signals.forEach { sig ->
            val color = if (sig.direction == "surperformance") GoodColor else WarnColor
            Text(
                "• ${sig.player} : ${sig.direction} (${String.format("%+.1f", sig.diff_pts)} pts vs carrière)",
                style = MaterialTheme.typography.bodySmall,
                color = color,
                fontWeight = FontWeight.SemiBold
            )
        }
    }
}

@Composable
private fun H2HSection(h: H2H) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SectionTitle("⚔️ Historique H2H", Icons.Default.History)
        Text("${h.player1} ${h.wins1} - ${h.wins2} ${h.player2}", fontWeight = FontWeight.Bold)
        h.meetings.take(5).forEach { m ->
            Text("• ${m.date.take(10)} : ${m.winner} gagne (${m.tour})", style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun SectionTitle(title: String, icon: ImageVector) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(8.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
    }
}

@Preview(showBackground = true)
@Composable
private fun MatchDetailPreview() {
    MaterialTheme {
        MatchDetailContent(
            p1 = PlayerDetail(name = "Jannik Sinner", rating = 2100.0, serve = 0.72, return1 = 0.55, return2 = 0.58),
            p2 = PlayerDetail(name = "Carlos Alcaraz", rating = 2080.0, serve = 0.70, return1 = 0.53, return2 = 0.56),
            insight = InsightResponse(
                player1 = "Jannik Sinner",
                player2 = "Carlos Alcaraz",
                factors = listOf(
                    InsightFactor(key = "serve", label = "Service", value1 = 0.72, value2 = 0.70, favors = "Jannik Sinner"),
                    InsightFactor(key = "return1", label = "Retour 1re balle", value1 = 0.55, value2 = 0.53, favors = "Jannik Sinner"),
                ),
                form_signals = listOf(
                    FormSignal(player = "Jannik Sinner", direction = "surperformance", diff_pts = 8.5, recent_form_pct = 85.0, career_baseline_pct = 76.5),
                ),
            ),
            intelligence = MatchIntelligence(
                tis = 82.0,
                recommendation = "VALUE_BET",
                favorite = "Jannik Sinner",
                model_prob = 0.62,
                ev_pct = 4.5,
                market_odds = 1.85,
                fair_odds = 1.61,
                categories = MatchIntelligenceCategories(player = 32.0, surface = 18.0, market = 32.0),
                why = listOf("Écart ELO en faveur de Sinner", "Value modérée +4.5% (cote 1.85)"),
                risks = listOf("Alcaraz monte en puissance récemment"),
                player1 = "Jannik Sinner",
                player2 = "Carlos Alcaraz",
                surface = "hard",
            ),
            h2h = H2H(player1 = "Jannik Sinner", player2 = "Carlos Alcaraz", wins1 = 4, wins2 = 4, total = 8, leader = "équilibre"),
            surface = "hard",
        )
    }
}
