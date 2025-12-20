# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版)
- 只做：Binance USDT 永續 1h K 線 MACD 背離掃描
- 移除：BingX 資金費率 / OI 排行 / Telegram 發送 / 排程 loop
- 加強：Streamlit Cloud 上 Binance 被擋時，不讓 App 紅畫面
"""

import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 你原本的參數（保留） ======
KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000
MAX_WORKERS   = 3          # Cloud 上建議小一點
EXCLUDED      = {"TUTUSDT", "USDCUSDT", "USDPUSDT"}
LOOKBACK      = 40
RECENT_BARS   = 5

session = requests.Session()
session.headers.update({
    "User-Agent": "scanner/1.0",
    "Accept": "application/json",
})
print("### legacy_scanner VERSION = 2025-12-20 v2 ###")
def get_json(url, params=None, timeout=20, retries=2, backoff=1.5):
    """
    Cloud 上常遇到 403/429，這裡做 retry；
    但最重要：最後丟出去的錯會在 run_for_streamlit() 被接住，不會紅畫面。
    """
    last_err = None
    for i in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout)

            if r.status_code >= 400:
                text = (r.text or "")[:300]
                raise requests.HTTPError(
                    f"HTTP {r.status_code} for {url} params={params} body={text}"
                )
            return r.json()

        except Exception as e:
            last_err = e
            time.sleep(backoff * (i + 1))
    raise last_err

# ====== MACD 計算 ======
def get_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    return macd, signal_line, hist

def has_bullish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["Low"].idxmin()
        if df["Low"].iloc[i] < df["Low"].iloc[prior_idx] and df["MACD"].iloc[i] > df["MACD"].iloc[prior_idx]:
            if i >= len(df) - recent:
                return True
    return False

def has_bearish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["High"].idxmax()
        if df["MACD"].iloc[i] > df["MACD"].iloc[prior_idx] and df["High"].iloc[i] <= df["High"].iloc[prior_idx]:
            if i >= len(df) - recent:
                return True
    return False

def process_symbol(symbol: str):
    """
    取期貨 24hr ticker 做成交額過濾，然後抓 1h K 線算 MACD 背離
    """
    try:
        t24 = get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = float(t24.get("quoteVolume", 0.0))
        if quote_vol < QUOTE_VOL_MIN:
            return None

        k = get_json(
            "https://fapi.binance.com/fapi/v1/klines",
            {"symbol": symbol, "interval": "1h", "limit": KLINE_LIMIT},
            timeout=25
        )
        if not isinstance(k, list) or len(k) < 120:
            return None

        df = pd.DataFrame(k, columns=[
            "Open Time","Open","High","Low","Close","Volume",
            "Close Time","Quote Asset Volume","Number of Trades",
            "Taker Buy Base Vol","Taker Buy Quote Vol","Ignore"
        ])
        df[["High","Low","Close"]] = df[["High","Low","Close"]].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["High","Low","Close"]).reset_index(drop=True)

        df["MACD"], df["Signal"], df["Hist"] = get_macd(df)

        bull = has_bullish_line_divergence(df)
        bear = has_bearish_line_divergence(df)

        hits = []
        if bull:
            hits.append({"Symbol": symbol, "Signal": "🟢 線背離(低段)", "Type": "Bullish", "Vol": quote_vol})
        if bear:
            hits.append({"Symbol": symbol, "Signal": "🔴 線背離(高段)", "Type": "Bearish", "Vol": quote_vol})
        return hits or None

    except Exception:
        return None

def run_for_streamlit(scan_limit: int = 50):
    """
    Streamlit 呼叫這個：
    - 永遠回傳 DataFrame
    - Binance 被擋(403/429) 也不會讓 App 紅畫面
    """
    # 1) 先拿 symbols（最常被擋的點）
    try:
        ex = get_json("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=20, retries=2)

        symbols = [
            s["symbol"] for s in ex.get("symbols", [])
            if s.get("quoteAsset") == "USDT"
            and s.get("contractType") == "PERPETUAL"
            and s.get("status") == "TRADING"
            and s.get("symbol") not in EXCLUDED
        ]

        if not symbols:
            raise RuntimeError("symbols list is empty")

    except Exception as e:
        # ✅ 不紅畫面：回一張表告訴你「被擋了」
        return pd.DataFrame([{
            "Symbol": "",
            "Signal": "❌ Binance API 被限制（403/429 很常見）",
            "Type": str(e)[:220],
            "Vol": ""
        }])

    # 2) 掃描（Cloud 上請務必限量，不然很快 429）
    symbols = symbols[:scan_limit]

    bull_bear_rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_symbol, sym) for sym in symbols]
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                bull_bear_rows.extend(res)

    if not bull_bear_rows:
        return pd.DataFrame([{
            "Symbol": "",
            "Signal": "⚠️ 本次未掃到背離（或 API 回應不穩）",
            "Type": "OK",
            "Vol": ""
        }])

    df = pd.DataFrame(bull_bear_rows)
    # 顯示順序好看一點
    df = df.sort_values(by=["Type", "Vol"], ascending=[True, False]).reset_index(drop=True)
    return df
