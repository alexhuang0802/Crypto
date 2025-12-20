# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版 - Spot API)
- 只做：Binance Spot 1h K 線 MACD 背離掃描（USDT 交易對）
- 參數固定：KLINE_LIMIT=720, interval=1h, lookback=40, recent_bars=5
- 移除：BingX 資金費率 / OI 排行 / Telegram 發送 / scheduler loop
- 目的：讓 Streamlit Cloud 上能穩定跑並在頁面顯示結果
"""

import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 固定參數（照你原本寫死） ======
KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000          # 24h quoteVolume 過濾
MAX_WORKERS   = 6                  # Cloud 建議不要太大
EXCLUDED      = {"USDCUSDT", "USDPUSDT"}  # 可自行加黑名單
LOOKBACK      = 40
RECENT_BARS   = 5

# ====== Binance Spot Base URL ======
SPOT_BASE = "https://api.binance.com"

session = requests.Session()
session.headers.update({
    "User-Agent": "scanner/1.0",
    "Accept": "application/json",
})

def get_json(url, params=None, timeout=20, retries=3, backoff=1.2):
    """
    帶 retry + 回傳更好 debug 的錯誤訊息
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
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist

def has_bullish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    """
    低段線背離：價格破低、MACD 不破低（且發生在最近 RECENT_BARS 根內）
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
    高段線背離：價格不創高（或創高幅度弱）、MACD 創高（且發生在最近 RECENT_BARS 根內）
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

# ====== 取 Spot 交易對清單（USDT） ======
def fetch_spot_symbols_usdt():
    """
    回傳：["BTCUSDT", "ETHUSDT", ...]
    """
    ex = get_json(f"{SPOT_BASE}/api/v3/exchangeInfo", timeout=20)
    symbols = []
    for s in ex.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        # Spot 沒有 contractType，這邊就是現貨交易對
        sym = s.get("symbol")
        if not sym:
            continue
        if sym in EXCLUDED:
            continue
        symbols.append(sym)
    return symbols

# ====== 單一幣種掃描（Spot 1h） ======
def process_symbol(symbol: str):
    try:
        # 1) 24hr ticker 取成交金額過濾（quoteVolume）
        t24 = get_json(f"{SPOT_BASE}/api/v3/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = float(t24.get("quoteVolume", 0.0))
        if quote_vol < QUOTE_VOL_MIN:
            return None

        # 2) K 線
        k = get_json(
            f"{SPOT_BASE}/api/v3/klines",
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

# ====== Streamlit 用的主入口：回傳 DataFrame ======
def run_for_streamlit() -> pd.DataFrame:
    """
    給 app.py 呼叫用：回傳 DataFrame
    欄位：Symbol, Signal, Type, Vol
    """
    try:
        symbols = fetch_spot_symbols_usdt()

        if not symbols:
            return pd.DataFrame([{
                "Symbol": "",
                "Signal": "⚠️ 沒抓到任何 USDT 交易對",
                "Type": "",
                "Vol": 0,
            }])

        rows = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(process_symbol, sym): sym for sym in symbols}
            for fut in as_completed(futs):
                res = fut.result()
                if res:
                    rows.extend(res)
                time.sleep(0.01)  # 稍微放慢，避免被 API 拒絕

        if not rows:
            return pd.DataFrame([{
                "Symbol": "",
                "Signal": "（無命中）",
                "Type": "",
                "Vol": 0,
            }])

        df = pd.DataFrame(rows)

        # 依成交額排序（大的在前）
        if "Vol" in df.columns:
            df = df.sort_values(by="Vol", ascending=False).reset_index(drop=True)

        return df[["Symbol", "Signal", "Type", "Vol"]]

    except Exception as e:
        # 不要讓 Streamlit 整頁紅，改成回傳一列錯誤資訊
        return pd.DataFrame([{
            "Symbol": "",
            "Signal": "❌ 掃描失敗（請看 Type 欄位錯誤）",
            "Type": str(e),
            "Vol": 0,
        }])
