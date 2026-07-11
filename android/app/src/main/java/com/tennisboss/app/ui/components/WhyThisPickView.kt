package com.tennisboss.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.tennisboss.app.data.ApiClient
import com.tennisboss.app.data.InsightFactor
import com.tennisboss.app.data.InsightResponse
import com.tennisboss.app.data.ModelHealth
import java.util.Locale

/**
 * Section repliable "Pourquoi ce pick ?", alimentée par /api/insight (Sport
 * Intelligence Layer Phase 1). Chargement paresseux : l'appel réseau n'a lieu
 * qu'à la première expansion, pas à l'affichage de la liste des matchs.
 *
 * Volontairement absente de PredictScreen : ce dernier a déjà [ExplainView]
 * + [H2HView] issus de /api/predict (même décomposition de logit que
 * /api/insight réutilise en interne côté backend) — les dupliquer ici serait
 * redondant. Ce composant cible les écrans qui n'ont pas encore cette
 * profondeur d'explication (Live, in-play).
 */
@Composable
fun WhyThisPickSection(
    player1: String,
    player2: String,
    surface: String? = null,
    eventId: String? = null,
    modifier: Modifier = Modifier,
) {
    var expanded by remember(player1, player2) { mutableStateOf(false) }
    var insight by remember(player1, player2) { mutableStateOf<InsightResponse?>(null) }
    var loading by remember(player1, player2) { mutableStateOf(false) }
    var error by remember(player1, player2) { mutableStateOf<String?>(null) }

    LaunchedEffect(expanded) {
        if (expanded && insight == null && !loading) {
            loading = true
            error = null
            try {
                insight = ApiClient.create().insight(player1, player2, surface, eventId)
            } catch (e: Exception) {
                error = "Analyse indisponible : ${e.message}"
            } finally {
                loading = false
            }
        }
    }

    Column(modifier = modifier.fillMaxWidth()) {
        TextButton(onClick = { expanded = !expanded }) {
            Text(
                if (expanded) "▲ Pourquoi ce pick ?" else "▼ Pourquoi ce pick ?",
                style = MaterialTheme.typography.labelLarge,
            )
        }
        if (expanded) {
            when {
                loading -> CircularProgressIndicator(modifier = Modifier.size(20.dp))
                error != null -> Text(
                    error!!,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                insight != null -> InsightContent(insight!!)
            }
        }
    }
}

private val P1Color = Color(0xFF4F8CFF)
private val P2Color = Color(0xFF00C2A8)
private val WarnColor = Color(0xFFB26A00)

@Composable
private fun InsightContent(d: InsightResponse) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 6.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val decisive = d.factors.firstOrNull { it.key == d.decisive_factor }
        if (decisive != null && decisive.favors != null) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(Color(0x1A4F8CFF))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    "🎯 Facteur décisif : ${decisive.label} — avantage ${decisive.favors} " +
                        "(confiance ${d.confidence_label})",
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }

        d.factors.forEach { f -> InsightFactorRow(f, d.player1, d.player2) }

        d.form_signals.forEach { sig ->
            val emoji = if (sig.direction == "surperformance") "📈" else "📉"
            Text(
                "$emoji ${sig.player} en ${sig.direction} : forme récente ${sig.recent_form_pct.toInt()}% " +
                    "vs bilan carrière ${sig.career_baseline_pct.toInt()}%",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }

        modelHealthWarnings(d).forEach { warning ->
            Text(
                "⚠️ $warning",
                style = MaterialTheme.typography.bodySmall,
                color = WarnColor,
            )
        }

        d.market?.let { m ->
            if (m.n_snapshots >= 2) {
                Text(
                    "📈 Mouvement de cote : ${d.player1} ${pctSigned(m.move_home_pct)} · " +
                        "${d.player2} ${pctSigned(m.move_away_pct)} (${m.n_snapshots} relevés)",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
        }
    }
}

private fun modelHealthWarnings(d: InsightResponse): List<String> {
    val h: ModelHealth = d.model_health
    val warnings = mutableListOf<String>()
    if (h.player1_blacklisted) warnings.add("${d.player1} sur-évalué par le modèle (mis-prédictions répétées).")
    if (h.player2_blacklisted) warnings.add("${d.player2} sur-évalué par le modèle (mis-prédictions répétées).")
    if (h.surface_danger) warnings.add("Précision du modèle en baisse sur cette surface.")
    if (h.accuracy_drift_pts <= -5.0) {
        warnings.add("Dérive de précision détectée (${String.format(Locale.FRANCE, "%.1f", h.accuracy_drift_pts)} pts).")
    }
    return warnings
}

@Composable
private fun InsightFactorRow(f: InsightFactor, name1: String, name2: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(f.label, style = MaterialTheme.typography.bodySmall)
        val favorColor = when (f.favors) {
            name1 -> P1Color
            name2 -> P2Color
            else -> MaterialTheme.colorScheme.outline
        }
        Text(
            f.favors ?: "égal",
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Medium,
            color = favorColor,
        )
    }
}

private fun pctSigned(v: Double): String {
    val sign = if (v > 0) "+" else ""
    return String.format(Locale.FRANCE, "%s%.1f%%", sign, v)
}

@Preview(showBackground = true)
@Composable
private fun WhyThisPickPreview() {
    Column {
        InsightContent(
            InsightResponse(
                player1 = "Jannik Sinner",
                player2 = "Carlos Alcaraz",
                confidence = 0.79,
                confidence_label = "bonne",
                decisive_factor = "recent",
                factors = listOf(
                    InsightFactor("recent", "Forme récente", 0.99, 0.75, favors = "Jannik Sinner"),
                    InsightFactor("elo", "Niveau ELO (historique)", 0.66, 0.34, favors = "Jannik Sinner"),
                    InsightFactor("h2h", "Confrontations directes", 7.0, 9.0, favors = "Carlos Alcaraz"),
                ),
                market = com.tennisboss.app.data.MarketMovement(
                    n_snapshots = 4, move_home_pct = -8.2, move_away_pct = 6.1,
                ),
                model_health = ModelHealth(surface_danger = true, accuracy_drift_pts = -6.0),
            ),
        )
    }
}
