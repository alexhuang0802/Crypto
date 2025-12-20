# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版 - Spot API with fallback endpoints)
- 只做：Spot 1h K 線 MACD 背離掃描（USDT）
- 解決：Streamlit Cloud 直連 api.binance.com 可能被 451/403/429 擋
- 做法：多個 base endpoint 失敗自動切換
- 輸出：只顯示「有命中」後的成交量 Top5 + Bottom5（最多 10 筆）
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

# 你要的名額
TOP_N = 5
BOTTOM_N = 5

# ====== 多個 endpoint（會自動 fallback） ======
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
    """
    低檔背離（做多留意）：
    價格創更低 Low，但 MACD 創更高（背離）
    且訊號發生在最近 recent 根內
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
    高檔背離（做空留意）：
    價格沒有創更高 High（<= 前高），但 MACD 創更高（背離）
    且訊號發生在最近 recent 根內
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
    """
    回傳 list[dict] 或 None
    dict: {Symbol, Signal, Type, Vol}
    Type: BULL / BEAR
    """
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
            hits.append({"Symbol": symbol, "Signal": "🟢 低檔背離(做多留意)", "Type": "BULL", "Vol": quote_vol})
        if bear:
            hits.append({"Symbol": symbol, "Signal": "🔴 高檔背離(做空留意)", "Type": "BEAR", "Vol": quote_vol})

        return hits or None

    except Exception:
        return None

def _merge_same_symbol(rows: list[dict]) -> pd.DataFrame:
    """
    同一個 Symbol 若同時 bull/bear，合併成一筆，Signal 串起來
    """
    if not rows:
        return pd.DataFrame(columns=["Symbol", "Signal", "Type", "Vol"])

    df = pd.DataFrame(rows)
    # 合併 Signal / Type
    agg = df.groupby("Symbol", as_index=False).agg({
        "Signal": lambda s: " / ".join(sorted(set(map(str, s)))),
        "Type":   lambda s: ",".join(sorted(set(map(str, s)))),
        "Vol":    "max",
    })
    return agg[["Symbol", "Signal", "Type", "Vol"]]

def _pick_top_bottom(df: pd.DataFrame, top_n=TOP_N, bottom_n=BOTTOM_N) -> pd.DataFrame:
    """
    只保留成交量 Top N + Bottom N
    """
    if df.empty:
        return df

    df2 = df.sort_values(by="Vol", ascending=False).reset_index(drop=True)

    top_df = df2.head(top_n)

    # bottom 從小到大
    bot_df = df2.sort_values(by="Vol", ascending=True).head(bottom_n)

    # 合併後去重（避免 top/bottom 重覆）
    out = pd.concat([top_df, bot_df], ignore_index=True)
    out = out.drop_duplicates(subset=["Symbol"]).reset_index(drop=True)

    # 最後再按 Vol 大到小看起來更直觀
    out = out.sort_values(by="Vol", ascending=False).reset_index(drop=True)
    return out

def run_for_streamlit() -> pd.DataFrame:
    """
    給 Streamlit 呼叫：回傳一個 DataFrame
    """
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

        # 只顯示命中，沒命中就給提示
        if not rows:
            return pd.DataFrame([{
                "Symbol": "",
                "Signal": "（本次無命中背離訊號）",
                "Type": "",
                "Vol": 0,
            }])

        df = _merge_same_symbol(rows)
        df = _pick_top_bottom(df, top_n=TOP_N, bottom_n=BOTTOM_N)
        return df[["Symbol", "Signal", "Type", "Vol"]]

    except Exception as e:
        return pd.DataFrame([{
            "Symbol": "",
            "Signal": "❌ 掃描失敗（請看 Type 欄位錯誤）",
            "Type": str(e),
            "Vol": 0,
        }])
