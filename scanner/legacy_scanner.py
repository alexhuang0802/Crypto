# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版 - Spot API with fallback endpoints)
- 只做：Spot 1h K 線 MACD 背離掃描（USDT）
- 解決：Streamlit Cloud 直連 api.binance.com 可能被 451/403/429 擋
- 做法：多個 base endpoint 失敗自動切換
"""

import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 固定參數（照你原本寫死） ======
KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000
MAX_WORKERS   = 4
EXCLUDED      = {"USDCUSDT", "USDPUSDT"}
LOOKBACK      = 40
RECENT_BARS   = 5

# ====== 多個 endpoint（會自動 fallback） ======
# 1) data-api.binance.vision：常見可用的 Binance data mirror（雲端較不容易被 451）
# 2) api.binance.com：官方（你現在會 451，留著當備援）
BASE_CANDIDATES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "scanner/1.0",
    "Accept": "application/json",
})

def _request_json(base: str, path: str, params=None, timeout=20):
    url = f"{base}{path}"
    r = session.get(url, params=params, timeout=timeout)
    if r.status_code >= 400:
        text = (r.text or "")[:300]
        raise requests.HTTPError(f"HTTP {r.status_code} for {url} params={params} body={text}")
    return r.json()

def get_json(path: str, params=None, timeout=20, retries=2, backoff=1.2):
    """
    會依序嘗試 BASE_CANDIDATES，成功就回傳
    全部失敗才 raise
    """
    last_err = None
    for base in BASE_CANDIDATES:
        for i in range(retries):
            try:
                return _request_json(base, path, params=params, timeout=timeout)
            except Exception as e:
                last_err = e
                time.sleep(backoff * (i + 1))
                continue
        # 這個 base 多次失敗 -> 換下一個
    raise last_err

# ====== MACD ======
def get_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist

def has_bullish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["Low"].idxmin()
        if (
            df["Low"].iloc[i] < df["Low"].iloc[prior_idx]
            and df["MACD"].iloc[i] > df["MACD"].iloc[prior_idx]
        ):
            if i >= len(df) - recent:
                return True
    return False

def has_bearish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["High"].idxmax()
        if (
            df["MACD"].iloc[i] > df["MACD"].iloc[prior_idx]
            and df["High"].iloc[i] <= df["High"].iloc[prior_idx]
        ):
            if i >= len(df) - recent:
                return True
    return False

# ====== Spot symbols ======
def fetch_spot_symbols_usdt():
    ex = get_json("/api/v3/exchangeInfo", timeout=20)
    symbols = []
    for s in ex.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        sym = s.get("symbol")
        if not sym:
            continue
        if sym in EXCLUDED:
            continue
        symbols.append(sym)
    return symbols

def process_symbol(symbol: str):
    try:
        t24 = get_json("/api/v3/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = float(t24.get("quoteVolume", 0.0))
        if quote_vol < QUOTE_VOL_MIN:
            return None

        k = get_json(
            "/api/v3/klines",
            {"symbol": symbol, "interval": "1h", "limit": KLINE_LIMIT},
            timeout=25,
        )
        if not isinstance(k, list) or len(k) < 120:
            return None

        df = pd.DataFrame(
            k,
            columns=[
                "Open Time","Open","High","Low","Close","Volume",
                "Close Time","Quote Asset Volume","Number of Trades",
                "Taker Buy Base Vol","Taker Buy Quote Vol","Ignore"
            ],
        )
        df[["High","Low","Close"]] = df[["High","Low","Close"]].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["High","Low","Close"]).reset_index(drop=True)

        df["MACD"], df["Signal"], df["Hist"] = get_macd(df)

        bull = has_bullish_line_divergence(df)
        bear = has_bearish_line_divergence(df)

        hits = []
        if bull:
            hits.append({"Symbol": symbol, "Signal": "🟢 線背離(低段)", "Type": "BULL", "Vol": quote_vol})
        if bear:
            hits.append({"Symbol": symbol, "Signal": "🔴 線背離(高段)", "Type": "BEAR", "Vol": quote_vol})
        return hits or None
    except Exception:
        return None

def run_for_streamlit() -> pd.DataFrame:
    try:
        symbols = fetch_spot_symbols_usdt()
        if not symbols:
            return pd.DataFrame([{
                "Symbol": "",
                "Signal": "⚠️ 沒抓到任何 USDT 交易對（exchangeInfo 可能仍被擋）",
                "Type": "NO_SYMBOLS",
                "Vol": 0,
            }])

        rows = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(process_symbol, sym): sym for sym in symbols}
            for fut in as_completed(futs):
                res = fut.result()
                if res:
                    rows.extend(res)
                time.sleep(0.01)

        if not rows:
            return pd.DataFrame([{
                "Symbol": "",
                "Signal": "（無命中）",
                "Type": "",
                "Vol": 0,
            }])

        df = pd.DataFrame(rows)
        df = df.sort_values(by="Vol", ascending=False).reset_index(drop=True)
        return df[["Symbol", "Signal", "Type", "Vol"]]

    except Exception as e:
        return pd.DataFrame([{
            "Symbol": "",
            "Signal": "❌ 掃描失敗（請看 Type 欄位錯誤）",
            "Type": str(e),
            "Vol": 0,
        }])
