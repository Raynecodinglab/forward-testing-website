from flask import Flask, request, jsonify, render_template
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
DB_PATH = "/home/Raynecodinglab/forward-testing-website/trades.db"

# ─── Database Setup ───────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT    NOT NULL,
            action      TEXT    NOT NULL,
            entry_price REAL    NOT NULL,
            exit_price  REAL,
            tp          REAL,
            sl          REAL,
            entry_time  TEXT    NOT NULL,
            exit_time   TEXT,
            pnl_pct     REAL    DEFAULT 0,
            status      TEXT    DEFAULT 'open'
        )
    """)
    conn.commit()
    conn.close()

# ─── Webhook Endpoint ─────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Expected TradingView alert JSON:
    {
        "ticker":  "SOLUSDT",
        "action":  "long" | "short" | "flat",
        "price":   132.45,
        "tp":      138.00,   (optional)
        "sl":      129.00    (optional)
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    ticker = data.get("ticker", "").upper().strip()
    action = data.get("action", "").lower().strip()
    price  = data.get("price")
    tp     = data.get("tp")
    sl     = data.get("sl")

    if not ticker or not action or price is None:
        return jsonify({"error": "Missing required fields: ticker, action, price"}), 400

if action not in ("long", "short", "flat", "tp1", "tp2"):
    return jsonify({"error": f"Unknown action '{action}'"}), 400

if action in ("tp1", "tp2"):
    conn.close()
    return jsonify({"ok": True, "message": f"Partial exit {action} ignored"}), 200
    
    conn = get_db()
    now  = datetime.utcnow().isoformat()

    # Find any open position for this ticker
    open_trade = conn.execute(
        "SELECT * FROM trades WHERE ticker = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (ticker,)
    ).fetchone()

    result_msg = ""

    # ── Close existing position if needed ───────────────────────────────────
    if open_trade:
        existing_action = open_trade["action"]
        should_close = (
            action == "flat" or
            (existing_action == "long"  and action == "short") or
            (existing_action == "short" and action == "long")
        )

        if should_close:
            entry = open_trade["entry_price"]
            if existing_action == "long":
                pnl_pct = ((price - entry) / entry) * 100
            else:
                pnl_pct = ((entry - price) / entry) * 100

            conn.execute("""
                UPDATE trades
                SET status='closed', exit_price=?, exit_time=?, pnl_pct=?
                WHERE id=?
            """, (price, now, round(pnl_pct, 4), open_trade["id"]))
            conn.commit()
            result_msg += f"Closed {existing_action.upper()} {ticker} @ {price} | PnL: {pnl_pct:.2f}%"

    # ── Open new position if action is directional ───────────────────────────
    if action in ("long", "short"):
        conn.execute("""
            INSERT INTO trades (ticker, action, entry_price, tp, sl, entry_time, status)
            VALUES (?, ?, ?, ?, ?, ?, 'open')
        """, (ticker, action, price, tp, sl, now))
        conn.commit()
        result_msg += f" | Opened {action.upper()} {ticker} @ {price}"

    conn.close()
    return jsonify({"ok": True, "message": result_msg.strip(" |")}), 200

# ─── API Routes ───────────────────────────────────────────────────────────────

@app.route("/api/trades")
def api_trades():
    conn  = get_db()
    rows  = conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/positions")
def api_positions():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats")
def api_stats():
    conn = get_db()

    closed = conn.execute(
        "SELECT pnl_pct, ticker FROM trades WHERE status = 'closed'"
    ).fetchall()

    total_closed  = len(closed)
    wins          = sum(1 for r in closed if r["pnl_pct"] > 0)
    losses        = sum(1 for r in closed if r["pnl_pct"] <= 0)
    win_rate      = (wins / total_closed * 100) if total_closed else 0

    gross_profit  = sum(r["pnl_pct"] for r in closed if r["pnl_pct"] > 0)
    gross_loss    = abs(sum(r["pnl_pct"] for r in closed if r["pnl_pct"] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit else 0)

    total_pnl     = sum(r["pnl_pct"] for r in closed)
    avg_win       = (gross_profit / wins)   if wins   else 0
    avg_loss      = (gross_loss   / losses) if losses else 0

    # Per-coin breakdown
    tickers = list(set(r["ticker"] for r in closed))
    per_coin = {}
    for t in tickers:
        coin_trades = [r for r in closed if r["ticker"] == t]
        coin_wins   = sum(1 for r in coin_trades if r["pnl_pct"] > 0)
        coin_pnl    = sum(r["pnl_pct"] for r in coin_trades)
        per_coin[t] = {
            "trades":   len(coin_trades),
            "wins":     coin_wins,
            "win_rate": round(coin_wins / len(coin_trades) * 100, 1) if coin_trades else 0,
            "pnl_pct":  round(coin_pnl, 2)
        }

    # Equity curve — cumulative PnL over closed trades in order
    equity_rows = conn.execute(
        "SELECT entry_time, pnl_pct FROM trades WHERE status='closed' ORDER BY id ASC"
    ).fetchall()
    cumulative, curve = 0.0, []
    for row in equity_rows:
        cumulative += row["pnl_pct"]
        curve.append({"time": row["entry_time"][:10], "value": round(cumulative, 2)})

    open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='open'").fetchone()[0]
    conn.close()

    return jsonify({
        "total_closed":   total_closed,
        "open_positions": open_count,
        "win_rate":       round(win_rate, 1),
        "profit_factor":  round(profit_factor, 2),
        "total_pnl_pct":  round(total_pnl, 2),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "per_coin":       per_coin,
        "equity_curve":   curve
    })


@app.route("/api/clear", methods=["POST"])
def api_clear():
    """Dev utility — wipe all trades."""
    conn = get_db()
    conn.execute("DELETE FROM trades")
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "All trades cleared."})


# ─── Frontend ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── Entry ────────────────────────────────────────────────────────────────────

init_db()  # ← moved outside, runs on every startup including WSGI

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
