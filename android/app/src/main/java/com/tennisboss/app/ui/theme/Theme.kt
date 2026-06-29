package com.tennisboss.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Palette « hi-tech » dark-first (style fintech / sports-tech).
 * L'app est volontairement toujours en sombre pour un rendu cohérent.
 */
private val NeonDark = darkColorScheme(
    primary = Color(0xFF00E5A0),          // vert néon — signal / favori
    onPrimary = Color(0xFF00251A),
    primaryContainer = Color(0xFF003D2C),
    onPrimaryContainer = Color(0xFF7DFFD4),
    secondary = Color(0xFF4F8CFF),        // bleu électrique — accents
    onSecondary = Color(0xFF00184A),
    tertiary = Color(0xFF00C2A8),
    background = Color(0xFF0A0E14),        // presque noir bleuté
    onBackground = Color(0xFFE6EDF3),
    surface = Color(0xFF131A24),           // cartes
    onSurface = Color(0xFFE6EDF3),
    surfaceVariant = Color(0xFF1C2530),    // cartes élevées
    onSurfaceVariant = Color(0xFFB0BEC8),  // texte secondaire — plus lisible
    outline = Color(0xFF637585),           // labels, bordures — contraste suffisant
    error = Color(0xFFFF5C7A),             // rouge néon
    onError = Color(0xFF3A0010),
)

@Composable
fun TennisBossTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = NeonDark,
        typography = Typography,
        content = content,
    )
}
