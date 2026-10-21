import os, json, requests, yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
WATCHLIST_FILE = "watchlist.json"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "nse-alerts-in-3915")

def run_scan():
    with open(WATCHLIST_FILE, "r") as f:
        watchlist = json.load(f)
    for sym, cfg in watchlist.items():
        df = yf.download(sym, period="1y", interval="1d", progress=False)
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        close = float(df["Close"].iloc[-1])
        low_52w = float(df["Low"].rolling(252, min_periods=20).min().iloc[-1])
        sma_200 = float(df["Close"].rolling(200, min_periods=30).mean().iloc[-1])
        sma_50 = float(df["Close"].rolling(50, min_periods=10).mean().iloc[-1])
        target = float(cfg.get("target_price", 0))
        reasons = []
        if target > 0 and close <= target:
            reasons.append(f"Target Hit: Rs.{close:.2f} <= Target Rs.{target:.2f}")
        if cfg.get("alert_below_52w_low", True) and close <= low_52w * 1.02:
            reasons.append(f"Near 52W Low: Rs.{close:.2f} (52W Low: Rs.{low_52w:.2f})")
        if cfg.get("alert_below_200dma", True) and close < sma_200:
            reasons.append(f"Below 200-DMA: Rs.{close:.2f} < Rs.{sma_200:.2f}")
        if cfg.get("alert_below_50dma", False) and close < sma_50:
            reasons.append(f"Below 50-DMA: Rs.{close:.2f} < Rs.{sma_50:.2f}")
        if reasons and NTFY_TOPIC:
            msg = f"Stock: {cfg.get('name', sym)} ({sym})
Price: Rs.{close:.2f} | Target: Rs.{target:.2f}
52W Low: Rs.{low_52w:.2f} | 200-DMA: Rs.{sma_200:.2f}
" + "
".join(reasons)
            requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers={"Title": f"NSE Buy Alert: {sym.replace('.NS','')} @ Rs.{close:.2f}", "Priority": "high"})

if __name__ == "__main__":
    run_scan()