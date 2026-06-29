package com.tennisboss.app.ui

import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

// Fuseau heure de l'Est (Québec/Ontario) — gère DST automatiquement
// Été : UTC-4 (EDT)  |  Hiver : UTC-5 (EST)
val TZ_EASTERN: ZoneId = ZoneId.of("America/Toronto")

private val ISO_PARSER = DateTimeFormatter.ISO_DATE_TIME
private val TIME_FMT   = DateTimeFormatter.ofPattern("HH:mm")

/**
 * Convertit une chaîne UTC ISO-8601 ("2026-06-29T15:00:00Z")
 * en heure locale Eastern et retourne "Auj. · 11:00" / "Dem. · 08:30" / "29 Juin · 14:00".
 */
fun utcToLocalLabel(utcRaw: String): String {
    if (utcRaw.isBlank()) return ""
    return try {
        val zdt = ZonedDateTime.parse(utcRaw, ISO_PARSER)
            .withZoneSameInstant(TZ_EASTERN)
        val today = LocalDate.now(TZ_EASTERN)
        val d     = zdt.toLocalDate()
        val time  = zdt.format(TIME_FMT)
        val day   = when (d) {
            today            -> "Auj."
            today.plusDays(1) -> "Dem."
            else -> {
                val month = d.month.getDisplayName(TextStyle.SHORT, Locale.FRENCH)
                    .replaceFirstChar { it.uppercase() }
                "${d.dayOfMonth} $month"
            }
        }
        "📅 $day · $time"
    } catch (_: Exception) {
        utcRaw.take(16).replace("T", " ").replace("Z", "")
    }
}

/**
 * Convertit une chaîne UTC ISO-8601 en heure locale Eastern simple : "HH:mm".
 */
fun utcToLocalTime(utcRaw: String): String {
    if (utcRaw.isBlank()) return ""
    return try {
        ZonedDateTime.parse(utcRaw, ISO_PARSER)
            .withZoneSameInstant(TZ_EASTERN)
            .format(TIME_FMT)
    } catch (_: Exception) {
        utcRaw.takeLast(8).take(5)
    }
}

/**
 * Combine une date "yyyy-MM-dd" (UTC) et une heure "HH:mm" (UTC)
 * → label Eastern.  Utilisé par UpcomingScreen où date et time arrivent séparément.
 */
fun combineDateTimeUtcToLocal(dateUtc: String, timeUtc: String): String {
    return try {
        val d   = LocalDate.parse(dateUtc)
        val t   = if (timeUtc.isNotBlank()) LocalTime.parse(timeUtc.take(5)) else LocalTime.MIDNIGHT
        val utc = ZonedDateTime.of(d, t, ZoneId.of("UTC"))
        val loc = utc.withZoneSameInstant(TZ_EASTERN)
        val today = LocalDate.now(TZ_EASTERN)
        val ld    = loc.toLocalDate()
        val time  = loc.format(TIME_FMT)
        val day   = when (ld) {
            today             -> "Auj."
            today.plusDays(1) -> "Dem."
            else -> {
                val month = ld.month.getDisplayName(TextStyle.SHORT, Locale.FRENCH)
                    .replaceFirstChar { it.uppercase() }
                "${ld.dayOfMonth} $month"
            }
        }
        if (timeUtc.isNotBlank()) "📅 $day · $time" else "📅 $day"
    } catch (_: Exception) {
        if (timeUtc.isNotBlank()) "⏰ $timeUtc" else dateUtc
    }
}
