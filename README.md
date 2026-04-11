# AlgoX Forward Test Platform

## Setup

```bash
pip install -r requirements.txt
python app.py
# → running on http://localhost:5000
```

## Deploy to Railway / Render

1. Push this folder to a GitHub repo
2. Connect repo on Railway or Render
3. Set start command: `gunicorn app:app`
4. Copy the public URL

---

## TradingView Alert Setup

In TradingView, set your alert **Message** to this JSON:

```json
{
  "ticker":  "{{ticker}}",
  "action":  "long",
  "price":   {{close}},
  "tp":      0,
  "sl":      0
}
```

- Change `"action"` to `"long"`, `"short"`, or `"flat"` per alert
- Set `"tp"` and `"sl"` to actual values or `0` if not used
- Set Webhook URL to: `https://your-domain.com/webhook`

### Three alerts needed per strategy signal:

**Long Entry alert:**
```json
{"ticker":"{{ticker}}","action":"long","price":{{close}},"tp":0,"sl":0}
```

**Short Entry alert:**
```json
{"ticker":"{{ticker}}","action":"short","price":{{close}},"tp":0,"sl":0}
```

**Exit / Flat alert (close any open position):**
```json
{"ticker":"{{ticker}}","action":"flat","price":{{close}},"tp":0,"sl":0}
```

---

## How Trade Matching Works

- `long` or `short` → opens a new position for that ticker
- `flat` → closes any open position for that ticker
- `long` when short is open → closes the short, opens a long (and vice versa)
- Duplicate same-direction signals are ignored (no double entries)

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/webhook` | Receive TradingView signal |
| GET  | `/api/stats` | Metrics, equity curve, per-coin |
| GET  | `/api/trades` | Full trade log |
| GET  | `/api/positions` | Open positions only |
| POST | `/api/clear` | Wipe all trades (dev use) |

---

## Notes

- Database: `trades.db` (SQLite, auto-created on first run)
- All PnL is in **percentage** terms per trade
- Dashboard auto-refreshes every 5 seconds
- Click "POST /webhook" in the header to copy your webhook URL
