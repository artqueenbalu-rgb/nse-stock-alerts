import os, json, requests, yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
WATCHLIST_FILE = "watchlist.json"
ALERTS_HISTORY_FILE = "alerts_history.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "nse-alerts-in-3915")

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def is_nse_market_open(now_ist):
    if now_ist.weekday() >= 5:
        return False
    mins = now_ist.hour * 60 + now_ist.minute
    return (9 * 60 + 15) <= mins <= (15 * 60 + 30)

def run_scan():
    now_ist = datetime.now(IST)
    event_name = os.getenv("GITHUB_EVENT_NAME", "manual")
    if event_name == "schedule" and not is_nse_market_open(now_ist):
        print(f"Outside NSE Market Hours ({now_ist.strftime('%I:%M %p IST')}). Skipping scheduled scan.")
        return

    watchlist = load_json(WATCHLIST_FILE, {})
    alerts_history = load_json(ALERTS_HISTORY_FILE, [])
    now_str = now_ist.strftime("%d-%b-%Y %I:%M %p IST")

    for sym, cfg in watchlist.items():
        df = yf.download(sym, period="1y", interval="1d", progress=False)
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        close = float(df["Close"].iloc[-1])
        low_52w = float(df["Low"].rolling(252, min_periods=15).min().iloc[-1])
        sma_200 = float(df["Close"].rolling(200, min_periods=20).mean().iloc[-1])
        sma_50 = float(df["Close"].rolling(50, min_periods=10).mean().iloc[-1])
        target = float(cfg.get("target_price", 0))

        reasons = []
        status_type = "ok"
        badge_label = "✅ Above Target"
        if target > 0 and close <= target:
            reasons.append(f"🎯 Target Hit: Rs.{close:.2f} <= Target Rs.{target:.2f}")
            status_type = "target"
            badge_label = "🚨 TARGET BUY HIT"
        if cfg.get("alert_below_52w_low", True) and close <= low_52w * 1.02:
            reasons.append(f"📉 Near 52W Low: Rs.{close:.2f} (52W Low: Rs.{low_52w:.2f})")
            if status_type == "ok":
                status_type = "low52"
                badge_label = "🔥 52W LOW BUY ZONE"
        if cfg.get("alert_below_200dma", True) and not np.isnan(sma_200) and close < sma_200:
            reasons.append(f"📊 Below 200-DMA: Rs.{close:.2f} < Rs.{sma_200:.2f}")
            if status_type == "ok":
                status_type = "dma"
                badge_label = "⚠️ BELOW 200-DMA"
        if cfg.get("alert_below_50dma", False) and not np.isnan(sma_50) and close < sma_50:
            reasons.append(f"📊 Below 50-DMA: Rs.{close:.2f} < Rs.{sma_50:.2f}")

        # Save live GitHub-fetched metrics into watchlist.json so the Web App reads them
        cfg["current_price"] = round(close, 2)
        cfg["low_52w"] = round(low_52w, 2)
        cfg["sma_200"] = round(sma_200, 2) if not np.isnan(sma_200) else 0.0
        cfg["sma_50"] = round(sma_50, 2) if not np.isnan(sma_50) else 0.0
        cfg["last_scanned"] = now_str

        if reasons:
            alerts_history.insert(0, {
                "symbol": sym,
                "name": cfg.get("name", sym),
                "curr": round(close, 2),
                "target": round(target, 2),
                "low52": round(low_52w, 2),
                "sma200": round(sma_200, 2) if not np.isnan(sma_200) else 0.0,
                "statusType": status_type,
                "badgeLabel": badge_label,
                "reasons": reasons,
                "time": now_str
            })
            if NTFY_TOPIC:
                msg = f"Stock: {cfg.get('name', sym)} ({sym})\nLive Price: Rs.{close:.2f} | Target: Rs.{target:.2f}\n52W Low: Rs.{low_52w:.2f} | 200-DMA: Rs.{sma_200:.2f}\n" + "\n".join(reasons)
                requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers={"Title": f"NSE Buy Alert: {sym.replace('.NS','')} @ Rs.{close:.2f}", "Priority": "high"})

    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)
    with open(ALERTS_HISTORY_FILE, "w") as f:
        json.dump(alerts_history[:50], f, indent=2)

if __name__ == "__main__":
    run_scan()