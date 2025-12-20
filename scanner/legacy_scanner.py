# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版 - Spot API with fallback endpoints)

功能：
- Spot 1h K 線：MACD 線背離（低檔/高檔）
- 顯示：Symbol / Price / Vol / Signal
- 輸出：最多 4 個表格（低檔 top/bot、高檔 top/bot），每表最多 5 筆 => 最多 20 筆

注意：
- Streamlit Cloud 可能遇到 Binance 451/403/429，會自動切換 endpoint
"""

import time
import requests
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 固定參數（照你原本寫死）======
KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000
MAX_WORKERS   = 4
EXCLUDED      = {"USDCUSDT", "USDPUSDT"}  # 你可加黑名單
LOOKBACK      = 40
RECENT_BARS   = 5

TOP_N = 5
BOT_N = 5

# ====== 多個 endpoint（自動 fallback）======
BASE_CANDIDATES = [
    "https://data-api.binance.vision",  # 建議優先
    "https://api.binance.com",          # 官方（可能 451）
]

session = requests.Session()
session.headers.update({
    "User-Agent": "scanner/1.0",
    "Accept": "application/json",
})

# ---------------- HTTP Helpers ----------------
def _request_json(base: str, path: str, params=None, timeout=20):
    url = f"{base}{path}"
    r = session.get(url, params=params, timeout=timeout)
    if r.status_code >= 400:
        text = (r.text or "")[:300]
        raise requests.HTTPError(f"HTTP {r.status_code} for {url} params={params} body={text}")
    return r.json()

def get_json(path: str, params=None, timeout=20, retries=2, backoff=1.2):
    last_err = None
    for base in BASE_CANDIDATES:
        for i in range(retries):
            try:
                return _request_json(base, path, params=params, timeout=timeout)
            except Exception as e:
                last_err = e
                time.sleep(backoff * (i + 1))
        # 換下一個 base
    raise last_err

# ---------------- Indicator ----------------
def get_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist

def has_bullish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    """
    低檔背離：價格創更低 Low，但 MACD 創更高（轉強）
    """
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
    """
    高檔背離：價格未破高 / 走弱，但 MACD 創更高（鈍化）
    """
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

# ---------------- Binance Spot Data ----------------
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
        # 用 24hr ticker 取：成交額 + 最新價
        t24 = get_json("/api/v3/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = float(t24.get("quoteVolume", 0.0))
        price = float(t24.get("lastPrice", 0.0))

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

        df["MACD"], df["SignalLine"], df["Hist"] = get_macd(df)

        bull = has_bullish_line_divergence(df)
        bear = has_bearish_line_divergence(df)

        hits = []
        if bull:
            hits.append({
                "Symbol": symbol,
                "Signal": "🟢 線背離(低檔)",
                "Type": "BULL",
                "Price": price,
                "Vol": quote_vol,
            })
        if bear:
            hits.append({
                "Symbol": symbol,
                "Signal": "🔴 線背離(高檔)",
                "Type": "BEAR",
                "Price": price,
                "Vol": quote_vol,
            })
        return hits or None

    except Exception:
        return None

# ---------------- Output helpers ----------------
def _pick_top_bottom(df: pd.DataFrame, top_n: int = 5, bot_n: int = 5):
    """
    回傳兩份 df：top_df, bot_df（都已經欄位整理好）
    """
    if df is None or df.empty:
        cols = ["Symbol", "Price", "Vol", "Signal"]
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=cols)

    d = df.copy()
    d["Vol"] = pd.to_numeric(d["Vol"], errors="coerce").fillna(0.0)
    d["Price"] = pd.to_numeric(d["Price"], errors="coerce").fillna(0.0)

    d_desc = d.sort_values("Vol", ascending=False).head(top_n)
    d_asc  = d.sort_values("Vol", ascending=True).head(bot_n)

    keep = ["Symbol", "Price", "Vol", "Signal"]
    return d_desc[keep].reset_index(drop=True), d_asc[keep].reset_index(drop=True)

def run_for_streamlit_tables():
    """
    回傳 dict：
    {
      meta: "...",
      bull_top: df,
      bull_bot: df,
      bear_top: df,
      bear_bot: df,
      error: "..."
    }
    """
    meta = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = {"meta": meta}

    try:
        symbols = fetch_spot_symbols_usdt()
        if not symbols:
            out["error"] = "沒抓到任何 USDT 交易對（exchangeInfo 可能仍被擋）"
            out["bull_top"] = pd.DataFrame()
            out["bull_bot"] = pd.DataFrame()
            out["bear_top"] = pd.DataFrame()
            out["bear_bot"] = pd.DataFrame()
            return out

        rows = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(process_symbol, sym): sym for sym in symbols}
            for fut in as_completed(futs):
                res = fut.result()
                if res:
                    rows.extend(res)
                time.sleep(0.01)

        if not rows:
            out["error"] = "沒有命中訊號（或成交量門檻過濾後為空）"
            out["bull_top"] = pd.DataFrame()
            out["bull_bot"] = pd.DataFrame()
            out["bear_top"] = pd.DataFrame()
            out["bear_bot"] = pd.DataFrame()
            return out

        df = pd.DataFrame(rows)

        bull_df = df[df["Type"] == "BULL"].copy()
        bear_df = df[df["Type"] == "BEAR"].copy()

        bull_top, bull_bot = _pick_top_bottom(bull_df, TOP_N, BOT_N)
        bear_top, bear_bot = _pick_top_bottom(bear_df, TOP_N, BOT_N)

        out["bull_top"] = bull_top
        out["bull_bot"] = bull_bot
        out["bear_top"] = bear_top
        out["bear_bot"] = bear_bot

        return out

    except Exception as e:
        out["error"] = str(e)
        out["bull_top"] = pd.DataFrame()
        out["bull_bot"] = pd.DataFrame()
        out["bear_top"] = pd.DataFrame()
        out["bear_bot"] = pd.DataFrame()
        return out
