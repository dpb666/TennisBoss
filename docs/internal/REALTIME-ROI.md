# Real-Time ROI Tracking System

## Overview

TennisBoss now has **instant ROI visibility** — you see settlement results and profits tick up **live** as matches complete, not 30 minutes later.

### What's New

- **Real-time settlement engine** (`bot/realtime.py`): async loop that polls for finished matches every 15 seconds
- **WebSocket endpoint** (`/api/v2/ws/settlement`): live stream of settlement events to connected browsers
- **Live ROI dashboard** (`/api/v2/dashboard`): browser-based view showing:
  - Running total ROI
  - Match count
  - Accuracy %
  - Live feed of last 20 settled matches with ROI delta
  - Auto-reconnecting WebSocket (survives browser tab suspend)

---

## Quick Start

### 1. Start the FastAPI server

```bash
cd /mnt/c/Users/donpa/TennisBoss
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

The server will:
- Load player profiles + ELO
- Initialize the real-time settlement engine
- Start polling for settled matches every 15 seconds
- Ready for WebSocket connections

### 2. Open the dashboard

Navigate to:
```
http://localhost:8001/api/v2/dashboard
```

Or from your phone (if on same network):
```
http://<your-laptop-ip>:8001/api/v2/dashboard
```

### 3. Watch settlements come in live

As matches end around the world:
1. API-Tennis reports the result
2. Settlement engine picks it up (within 15 seconds)
3. Model predicts (was our favorite right?)
4. ELO updates (continuous learning)
5. ROI calculates (did we have odds on this?)
6. Dashboard updates **in real-time** via WebSocket

---

## Architecture

### Settlement Loop (`bot/realtime.py`)

```python
RealtimeSettlementEngine
├─ start()              → launches async poll loop
├─ stop()               → graceful shutdown
├─ subscribe(callback)  → register listener
└─ _poll_loop()         → every 15 seconds:
   ├─ fetch_results()   → API-Tennis results
   ├─ for each result:
   │  ├─ resolve names
   │  ├─ predict (current model)
   │  ├─ record in DB
   │  ├─ update ELO (continuous learning)
   │  └─ emit settlement event
   └─ sleep(15s)
```

**Config**: Edit `poll_interval` in `app/main.py` lifespan to change polling frequency.

### WebSocket Endpoint (`/api/v2/ws/settlement`)

Emits JSON events:
```json
{
  "type": "settled",
  "data": {
    "player1": "Alexander Zverev",
    "player2": "Jannik Sinner",
    "winner": "Jannik Sinner",
    "pred_favorite": "Alexander Zverev",
    "pred_prob1": 52.3,
    "correct": 0,
    "roi_delta": -1.0,
    "timestamp": 1718000001.5
  },
  "ts": 1718000001.5
}
```

**ROI Delta**: profit/loss for this one match if we had odds.
- If favorite predicted, correct, and odds=2.5 → roi_delta = +1.5
- If favorite predicted, wrong → roi_delta = -1.0
- If no odds captured → roi_delta = 0.0

### Dashboard (`app/static/realtime-dashboard.html`)

Live browser UI:
- **Total ROI**: running sum of all roi_deltas
- **Match Count**: number of settlements seen
- **Accuracy %**: (wins / judged matches) * 100
- **Last Update**: when the most recent settlement arrived
- **Live Feed**: chronological list of last 20 matches with visual indicators

Colors:
- 🟢 Green: correct prediction, profit
- 🔴 Red: wrong prediction
- 🟡 Orange: neutral (no odds, or correct but no profit)

---

## API Endpoints

### GET `/api/v2/dashboard`
Returns the real-time ROI dashboard (HTML page).

### WebSocket `/api/v2/ws/settlement`
Live stream of settlement events. Expected usage:

```javascript
const ws = new WebSocket('ws://localhost:8001/api/v2/ws/settlement');
ws.onmessage = (e) => {
  const payload = JSON.parse(e.data);
  console.log('Settlement:', payload.data);
};
```

### GET `/api/v2/settlement-status`
Poll endpoint (HTTP) for settlement engine status:

```json
{
  "status": "running",
  "poll_interval": 15,
  "subscribers": 1,
  "active_ws_clients": 2,
  "recent_settlements": [
    {
      "player1": "...",
      "player2": "...",
      "winner": "...",
      "pred_favorite": "...",
      "correct": 1,
      "date": "..."
    }
  ]
}
```

---

## Continuous Learning

Real-time settlement also **updates ELO immediately**:
- When a match is settled, ELO is recalculated
- Next prediction uses the fresh ELO
- Dominance multiplier applied (dominant wins teach more)

This means your model improves with every settlement, live.

---

## Configuration

### Poll Interval

In `app/main.py`, change this line:
```python
engine = realtime.init(_MEM)
```

To customize:
```python
engine = realtime.RealtimeSettlementEngine(_MEM, poll_interval=10)  # 10 seconds instead of 15
```

### Dashboard URL

If running behind a proxy or on a different host:
- The dashboard auto-detects WebSocket URL from `window.location.hostname`
- For custom domains, edit `realtime-dashboard.html` line ~180:

```javascript
let wsUrl = `${wsProtocol}//${window.location.host}/api/v2/ws/settlement`;
// Change to:
let wsUrl = `${wsProtocol}//your-domain.com/api/v2/ws/settlement`;
```

---

## Troubleshooting

### "WebSocket connection refused"
- Check FastAPI server is running: `curl http://localhost:8001/api/v2/health`
- Check firewall allows port 8001
- On phone: use your laptop's LAN IP, not localhost

### "No settlements appearing"
- Check API-Tennis key is set: `echo $AT_API_KEY`
- Check settled matches exist in DB: `python3 run.py db`
- Check poll interval: `/api/v2/settlement-status` → `poll_interval`
- Temporarily reduce interval: `poll_interval=5` to test faster

### Dashboard shows "Last Update: —"
- Likely no matches have settled yet today (timezone issue?)
- Wait 15 seconds for first poll
- Check logs: `python3 run.py` → look for "settlement_check" messages

### High CPU usage
- Increase `poll_interval` (15 → 30 seconds)
- Reduce number of dashboard tabs open
- Check if `fetch_results()` is slow: profile `live_api.py`

---

## Mobile Alerts (Telegram / Slack)

Get instant push notifications on your phone when matches settle and ROI updates.

### Telegram Setup

1. Create a Telegram bot:
   - Chat with `@BotFather` on Telegram
   - Create new bot → copy the API token
   - Start a chat with your bot

2. Get your chat ID:
   ```bash
   # Replace TOKEN with your bot token
   curl "https://api.telegram.org/botTOKEN/getUpdates" | grep '"id"'
   ```

3. Set environment variables:
   ```bash
   export TELEGRAM_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
   export TELEGRAM_CHAT_ID="987654321"
   ```

4. Restart FastAPI server → alerts enabled

Example alert:
```
🟢 Settlement Alert

Alexander Zverev vs Jannik Sinner
🏆 Winner: Jannik Sinner
📊 Model: Alexander Zverev (52.3%)
✗ Result: Wrong
💰 ROI: -1.00
```

### Slack Setup

1. Create a Slack incoming webhook:
   - Go to your workspace → Settings → App Management
   - Create new app → enable Incoming Webhooks
   - Add new webhook → copy the URL

2. Set environment variable:
   ```bash
   export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
   ```

3. Restart FastAPI server → alerts enabled

Example alert:
```
🔴 Settlement: Zverev vs Sinner
   Winner: Sinner
   Prediction: Zverev
   ROI: -1.00
   Result: ✗ Wrong
```

---

## Future Enhancements

- [x] Settlement alert on Telegram/Slack (custom callback)
- [ ] Graph of cumulative ROI over time
- [ ] Confidence calibration live (Brier score updating)
- [ ] Settlement details modal (odds, prediction confidence, etc.)
- [ ] Export ROI history as CSV
- [ ] A/B test dashboard (compare two models live)

---

## Testing Locally

If no live matches are settling, manually insert a test:

```python
from bot import db
db.insert_settled({
    "event_key": "test_12345",
    "date": "2024-06-09",
    "tour": "atp",
    "tournament": "Test",
    "player1": "Alexander Zverev",
    "player2": "Jannik Sinner",
    "winner": "Jannik Sinner",
    "final_score": "6-4 6-3",
    "sets": [],
    "pred_favorite": "Alexander Zverev",
    "pred_prob1": 52.0,
    "correct": 0,
})
```

The engine will emit this next poll cycle (within 15s).

---

## Performance Notes

- **Settlement check**: ~200ms (API call + DB query)
- **WebSocket broadcast**: ~10ms per client
- **Memory overhead**: ~2MB for engine + recent settlements
- **API quota impact**: 1 call per poll interval (1 call per 15s ≈ 240/day)

Safe to run 24/7 with 15-30 second polling intervals.
