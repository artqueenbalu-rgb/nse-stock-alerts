import os, json, requests, yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
WATCHLIST_FILE = "watchlist.json"
ALERTS_HISTORY_FILE = "alerts_history.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "nse-alerts-in-2076").strip()
NL = chr(10)

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def is_nse_market_open(now_ist):
    if now_ist.weekday() >= 5:
        return False
    mins = now_ist.hour * 60 + now_ist.minute
    return (9 * 60 + 15) <= mins <= (15 * 60 + 30)

def send_ntfy(title, lines, priority="high", tags="chart_with_upwards_trend"):
    if not NTFY_TOPIC:
        return
    try:
        clean_title = title.encode("ascii", "ignore").decode("ascii").strip() or "NSE Buy Alert"
        body = NL.join(lines)
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={"Title": clean_title, "Priority": priority, "Tags": tags},
            timeout=15
        )
    except Exception as e:
        print(f"ntfy push warning: {e}")

def run_scan():
    now_ist = datetime.now(IST)
    event_name = os.getenv("GITHUB_EVENT_NAME", "manual")
    if event_name == "schedule" and not is_nse_market_open(now_ist):
        print(f"Outside NSE Market Hours ({now_ist.strftime('%I:%M %p IST')}). Skipping scheduled scan.")
        return

    watchlist = load_json(WATCHLIST_FILE, {})
    alerts_history = load_json(ALERTS_HISTORY_FILE, [])
    if not isinstance(alerts_history, list):
        alerts_history = []
    now_str = now_ist.strftime("%d-%b-%Y %I:%M %p IST")
    triggered_count = 0
    scanned_count = 0

    for sym, cfg in watchlist.items():
        try:
            df = yf.download(sym, period="1y", interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty:
                print(f"No data returned for {sym}")
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            close_series = df["Close"].dropna()
            low_series = df["Low"].dropna()
            if close_series.empty:
                continue

            close = float(close_series.iloc[-1])
            low_52w = float(low_series.rolling(252, min_periods=1).min().iloc[-1])
            sma_200 = float(close_series.rolling(200, min_periods=1).mean().iloc[-1])
            sma_50 = float(close_series.rolling(50, min_periods=1).mean().iloc[-1])
            target = float(cfg.get("target_price", 0))
            scanned_count += 1

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

            cfg["current_price"] = round(close, 2)
            cfg["low_52w"] = round(low_52w, 2)
            cfg["sma_200"] = round(sma_200, 2) if not np.isnan(sma_200) else 0.0
            cfg["sma_50"] = round(sma_50, 2) if not np.isnan(sma_50) else 0.0
            cfg["last_scanned"] = now_str

            if reasons:
                triggered_count += 1
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
                msg_lines = [
                    f"Stock: {cfg.get('name', sym)} ({sym})",
                    f"Live NSE Price: Rs.{close:.2f} | Target: Rs.{target:.2f}",
                    f"52W Low: Rs.{low_52w:.2f} | 200-DMA: Rs.{sma_200:.2f}",
                    *reasons
                ]
                send_ntfy(
                    f"NSE Buy Alert: {sym.replace('.NS', '')} @ Rs.{close:.2f}",
                    msg_lines,
                    priority="high",
                    tags="rotating_light,chart_with_upwards_trend"
                )
        except Exception as e:
            print(f"Error scanning {sym}: {e}")

    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, indent=2)
    with open(ALERTS_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts_history[:50], f, indent=2)

    if event_name != "schedule" and triggered_count == 0 and scanned_count > 0:
        send_ntfy(
            f"NSE Scan Complete ({scanned_count} shares updated)",
            [
                f"GitHub Actions scanned {scanned_count} NSE shares at {now_str}.",
                "Live prices, 52W Lows, and 200-DMAs are now updated in your app.",
                "No shares were below your target alert price on this scan."
            ],
            priority="default",
            tags="white_check_mark"
        )

if __name__ == "__main__":
    run_scan()