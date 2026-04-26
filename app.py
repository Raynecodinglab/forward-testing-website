from flask import Flask, request, jsonify, render_template
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
DB_PATH = "/home/Raynecodinglab/forward-testing-website/trades.db"

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
            strategy    TEXT    DEFAULT 'AlgoX',
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
    try:
        conn.execute("ALTER TABLE trades ADD COLUMN strategy TEXT DEFAULT 'AlgoX'")
    except:
        pass
    conn.commit()
    conn.close()

init_db()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    ticker   = data.get("ticker", "").upper().strip()
    action   = data.get("action", "").lower().strip()
    price    = data.get("price")
    tp       = data.get("tp")
    sl       = data.get("sl")
    strategy = data.get("strategy", "AlgoX").strip()
    if not ticker or not action or price is None:
        return jsonify({"error": "Missing required fields: ticker, action, price"}), 400
    if action not in ("long", "short", "flat", "tp1", "tp2"):
        return jsonify({"error": f"Unknown action '{action}'"}), 400
    if action in ("tp1", "tp2"):
        return jsonify({"ok": True, "message": f"Partial exit {action} ignored"}), 200
    conn = get_db()
    now  = datetime.utcnow().isoformat()
    open_trade = conn.execute(
        "SELECT * FROM trades WHERE ticker = ? AND strategy = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (ticker, strategy)
    ).fetchone()
    result_msg = ""
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
    if action in ("long", "short"):
        conn.execute("""
            INSERT INTO trades (ticker, strategy, action, entry_price, tp, sl, entry_time, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
        """, (ticker, strategy, action, price, tp, sl, now))
        conn.commit()
        result_msg += f" | Opened {action.upper()} {ticker} @ {price}"
    conn.close()
    return jsonify({"ok": True, "message": result_msg.strip(" |")}), 200

@app.route("/api/trades")
def api_trades():
    strategy = request.args.get("strategy", None)
    conn = get_db()
    if strategy:
        rows = conn.execute("SELECT * FROM trades WHERE strategy = ? ORDER BY id DESC LIMIT 200", (strategy,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/positions")
def api_positions():
    strategy = request.args.get("strategy", None)
    conn = get_db()
    if strategy:
        rows = conn.execute("SELECT * FROM trades WHERE strategy = ? AND status = 'open' ORDER BY entry_time DESC", (strategy,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/stats")
def api_stats():
    strategy = request.args.get("strategy", None)
    conn = get_db()
    if strategy:
        closed = conn.execute("SELECT pnl_pct, ticker FROM trades WHERE strategy = ? AND status = 'closed'", (strategy,)).fetchall()
        open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE strategy = ? AND status='open'", (strategy,)).fetchone()[0]
        equity_rows = conn.execute("SELECT entry_time, pnl_pct FROM trades WHERE strategy = ? AND status='closed' ORDER BY id ASC", (strategy,)).fetchall()
    else:
        closed = conn.execute("SELECT pnl_pct, ticker FROM trades WHERE status = 'closed'").fetchall()
        open_count = conn.execute("SELECT COUNT(*) FROM trades WHERE status='open'").fetchone()[0]
        equity_rows = conn.execute("SELECT entry_time, pnl_pct FROM trades WHERE status='closed' ORDER BY id ASC").fetchall()
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
    cumulative, curve = 0.0, []
    for row in equity_rows:
        cumulative += row["pnl_pct"]
        curve.append({"time": row["entry_time"][:10], "value": round(cumulative, 2)})
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
    strategy = request.args.get("strategy", None)
    conn = get_db()
    if strategy:
        conn.execute("DELETE FROM trades WHERE strategy = ?", (strategy,))
    else:
        conn.execute("DELETE FROM trades")
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": f"Trades cleared{' for ' + strategy if strategy else ''}."})

@app.route("/")
def index():
    return render_template("landing.html")

@app.route("/algox")
def algox():
    return render_template("index.html")

@app.route("/superflow")
def superflow():
    return render_template("superflow.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
