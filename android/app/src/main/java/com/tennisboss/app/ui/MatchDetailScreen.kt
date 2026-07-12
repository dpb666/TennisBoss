package com.tennisboss.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.ui.tooling.preview.Preview
import com.tennisboss.app.data.*

private val GoodColor = Color(0xFF00E5A0)
private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)
private val WarnColor = Color(0xFFFF5C7A)
private val AccentColor = Color(0xFF4F8CFF)

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
                title = { Text("Analyse Premium", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Retour")
                    }
                }
            )
        }
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            when (val s = vm.uiState) {
                is MatchDetailUiState.Loading -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                is MatchDetailUiState.Error -> Text(s.message, color = WarnColor, modifier = Modifier.padding(16.dp))
                is MatchDetailUiState.Success -> MatchDetailContent(s.player1, s.player2, s.insight, s.h2h)
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
    h2h: H2H?
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        ComparisonHeader(p1, p2)
        SurfaceEloComparison(p1, p2)
        PremiumSignalsSection(insight)
        FormSection(p1, p2, insight)
        h2h?.let { H2HSection(it) }
        Spacer(Modifier.height(32.dp))
    }
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
        insight.clutch_signals.forEach { c ->
            val desc = listOfNotNull(
                c.bp_save_rate?.let { "BP Saved: ${String.format("%.0f%%", it*100)}" },
                c.tb_win_rate?.let { "TB Win: ${String.format("%.0f%%", it*100)}" }
            ).joinToString(" · ")
            SignalCard(Icons.Default.Star, "Clutch : ${c.player}", desc, GoodColor)
        }
        insight.opponent_quality_signals.forEach { o ->
            SignalCard(Icons.Default.TrendingUp, "Qualité opposition : ${o.player}", o.direction, AccentColor)
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
        SectionTitle("📈 Forme & Momentum", Icons.Default.TrendingUp)
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
            p1 = PlayerDetail(name = "Jannik Sinner", rating = 2100.0),
            p2 = PlayerDetail(name = "Carlos Alcaraz", rating = 2080.0),
            insight = InsightResponse(player1 = "Jannik Sinner", player2 = "Carlos Alcaraz"),
            h2h = H2H(player1 = "Jannik Sinner", player2 = "Carlos Alcaraz", wins1 = 4, wins2 = 4, total = 8)
        )
    }
}
