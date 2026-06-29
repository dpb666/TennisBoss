"""Telegram + Slack alerts for settlement events (optional add-on).

If TELEGRAM_TOKEN + TELEGRAM_CHAT_ID are set, send instant notifications
when matches settle with ROI results.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("tennisboss.alerts")


class SettlementAlertSender:
    """Send settlement notifications to Telegram / Slack."""

    def __init__(self):
        self.telegram_token = os.environ.get("TELEGRAM_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        self.slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")

    def is_enabled(self) -> bool:
        """Return True if at least one alert service is configured."""
        return bool(self.telegram_token or self.slack_webhook)

    def on_value_pick(self, pick: Dict[str, Any]) -> None:
        """Send alert when a high-confidence value pick is detected."""
        if not self.is_enabled():
            return
        p1 = pick.get("player1", "?")
        p2 = pick.get("player2", "?")
        side = pick.get("best_side", "?")
        ev = pick.get("best_ev", 0.0)
        odds = pick.get("odds", {})
        pick_odds = odds.get("home") if side == p1 else odds.get("away")
        kelly = pick.get("kelly_u", 0.0)
        conf = pick.get("confidence_label", "")
        league = pick.get("league", "")
        terrain = " 🌟 terrain favorable" if pick.get("terrain_favorable") else ""
        book = pick.get("best_book", "")
        msg = (
            f"🎾 *VALUE PICK*{terrain}\n\n"
            f"*{p1}* vs *{p2}*\n"
            f"📍 {league}\n\n"
            f"✅ Miser sur: *{side}*\n"
            f"💹 Cote: `{pick_odds}` chez {book or '?'}\n"
            f"📈 EV: `+{ev:.1f}%`\n"
            f"🎯 Kelly 1/4: `{kelly:.1f}% bankroll`\n"
            f"🔒 Confiance: {conf}\n"
        )
        if self.telegram_token:
            self._send_telegram(msg)

    def on_settlement(self, event: Dict[str, Any]) -> None:
        """Send alert for a settled match."""
        if not self.is_enabled():
            return

        data = event.get("data", {})
        msg = self._format_message(data)

        if self.telegram_token:
            self._send_telegram(msg)
        if self.slack_webhook:
            self._send_slack(data)

    def _format_message(self, data: Dict[str, Any]) -> str:
        """Format settlement into a readable alert message."""
        player1 = data.get("player1", "?")
        player2 = data.get("player2", "?")
        winner = data.get("winner", "?")
        pred_fav = data.get("pred_favorite", "?")
        correct = data.get("correct")
        roi = data.get("roi_delta", 0.0)

        correct_emoji = "✓" if correct == 1 else "✗" if correct == 0 else "?"
        roi_emoji = "🟢" if roi > 0 else "🔴" if roi < 0 else "⚪"

        return (
            f"{roi_emoji} *Settlement Alert*\n\n"
            f"{player1} vs {player2}\n"
            f"🏆 Winner: {winner}\n"
            f"📊 Model: {pred_fav} ({data.get('pred_prob1', '?')}%)\n"
            f"{correct_emoji} Result: {'Correct' if correct == 1 else 'Wrong' if correct == 0 else 'Unpredicted'}\n"
            f"💰 ROI: {roi:+.2f}\n"
        )

    def _send_telegram(self, msg: str) -> None:
        """Send message to Telegram."""
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(
                url,
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": msg,
                    "parse_mode": "Markdown",
                },
                timeout=5,
            )
            logger.debug("Telegram alert sent.")
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)

    def _send_slack(self, data: Dict[str, Any]) -> None:
        """Send message to Slack."""
        try:
            import requests

            player1 = data.get("player1", "?")
            player2 = data.get("player2", "?")
            winner = data.get("winner", "?")
            roi = data.get("roi_delta", 0.0)

            color = "#36a64f" if roi > 0 else "#ff0000" if roi < 0 else "#ffa500"

            payload = {
                "attachments": [
                    {
                        "color": color,
                        "title": f"{player1} vs {player2}",
                        "fields": [
                            {"title": "Winner", "value": winner, "short": True},
                            {
                                "title": "Prediction",
                                "value": data.get("pred_favorite", "?"),
                                "short": True,
                            },
                            {"title": "ROI", "value": f"{roi:+.2f}", "short": True},
                            {
                                "title": "Result",
                                "value": "✓ Correct"
                                if data.get("correct") == 1
                                else "✗ Wrong",
                                "short": True,
                            },
                        ],
                    }
                ]
            }
            requests.post(self.slack_webhook, json=payload, timeout=5)
            logger.debug("Slack alert sent.")
        except Exception as e:
            logger.warning("Slack send failed: %s", e)


# Global singleton
_ALERTER: Optional[SettlementAlertSender] = None


def init() -> SettlementAlertSender:
    """Initialize the alert sender."""
    global _ALERTER
    _ALERTER = SettlementAlertSender()
    if _ALERTER.is_enabled():
        logger.info("Settlement alerts enabled (Telegram and/or Slack).")
    return _ALERTER


def get() -> Optional[SettlementAlertSender]:
    """Get the global alert sender."""
    return _ALERTER
