# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版 - Binance Futures USDT Perp with fallback)
- 只做：Binance USDT 永續合約 1h K 線 MACD 線背離掃描
- 輸出：低檔背離 / 高檔背離，各自分「成交量前五大」「成交量前五小」，最多 20 筆
- 顯示：Symbol / Signal / Price / Vol + 分組欄位 Category / Bucket
- 解決：雲端可能遇到 451/403/429 => 多個 base endpoint 失敗自動切換 + 重試
"""

import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 固定參數（你說寫死就好） ======
INTERVAL      = "1h"
KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000   # 24h quoteVolume 門檻（USDT）
MAX_WORKERS   = 4           # Cloud 建議小一點，避免 429
EXCLUDED      = {"TUTUSDT", "USDCUSDT", "USDPUSDT"}  # 你原本黑名單
LOOKBACK      = 40
RECENT_BARS   = 5
TOP_N         = 5
BOT_N         = 5

# ✅ 期貨 endpoints（依序嘗試）
# 1) fapi.binance.com：官方
# 2) fapi.binance.vision：常見鏡像（如果可用會救命；不可用也不影響，會自動跳下一個）
BASE_CANDIDATES = [
    "https://fapi.binance.com",
    "https://fapi.binance.vision",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "scanner/1.0",
    "Accept": "application/json",
})


# --------------------------
# HTTP / JSON helper
# --------------------------
def _request_json(base: str, path: str, params=None, timeout=20):
    url = f"{base}{path}"
    r = session.get(url, params=params, timeout=timeout)
    if r.status_code >= 400:
        text = (r.text or "")[:300]
        raise requests.HTTPError(f"HTTP {r.status_code} for {url} params={params} body={text}")
    return r.json()


def get_json(path: str, params=None, timeout=20, retries=2, backoff=1.2):
    """
    依序嘗試 BASE_CANDIDATES；每個 base 會重試 retries 次
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
        # 這個 base 多次失敗 -> 換下一個
    raise last_err


# --------------------------
# MACD & divergence
# --------------------------
def get_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist


def has_bullish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    """
    低檔（做多留意）：
    價格 Low 創更低，但 MACD 卻更高（底背離）
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
    高檔（做空留意）：
    MACD 創更高，但價格 High 沒有更高（頂背離）
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


# --------------------------
# Futures symbols & per-symbol scan
# --------------------------
def fetch_futures_symbols_usdt_perp():
    """
    USDT 永續合約名單
    """
    ex = get_json("/fapi/v1/exchangeInfo", timeout=20)
    symbols = []
    for s in ex.get("symbols", []):
        if s.get("contractType") != "PERPETUAL":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        if s.get("status") != "TRADING":
            continue
        sym = s.get("symbol")
        if not sym or sym in EXCLUDED:
            continue
        symbols.append(sym)
    return symbols


def process_symbol(symbol: str, drop_last_open_candle: bool = True):
    """
    單一幣掃描：
    - 24h ticker 取 quoteVolume + lastPrice
    - 1h K 線算 MACD，判斷低檔/高檔背離
    """
    try:
        t24 = get_json("/fapi/v1/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = float(t24.get("quoteVolume", 0.0))
        price = float(t24.get("lastPrice", 0.0))

        if quote_vol < QUOTE_VOL_MIN:
            return None

        k = get_json(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": INTERVAL, "limit": KLINE_LIMIT},
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
        df["Open Time"] = pd.to_numeric(df["Open Time"], errors="coerce")
        df["Close Time"] = pd.to_numeric(df["Close Time"], errors="coerce")
        df = df.dropna(subset=["High","Low","Close","Open Time","Close Time"]).reset_index(drop=True)

        # ✅ 對齊很多本機策略：排除最後一根未收線
        if drop_last_open_candle and len(df) >= 2:
            now_ms = int(time.time() * 1000)
            if df["Close Time"].iloc[-1] > now_ms:
                df = df.iloc[:-1].reset_index(drop=True)

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
        # 這裡不回傳錯誤列，避免污染輸出（你要 debug 再改）
        return None


# --------------------------
# Output helpers (top/bottom by Vol)
# --------------------------
def _pick_top_bottom(df: pd.DataFrame, top_n: int, bot_n: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Bucket", "Signal", "Symbol", "Price", "Vol", "Type"])

    df = df.copy()
    df["Vol"] = pd.to_numeric(df["Vol"], errors="coerce").fillna(0.0)

    top = df.sort_values("Vol", ascending=False).head(top_n)
    bot = df.sort_values("Vol", ascending=True).head(bot_n)

    out = []
    if not top.empty:
        t = top.copy()
        t.insert(0, "Bucket", "📊 成交量前五大")
        out.append(t)
    if not bot.empty:
        b = bot.copy()
        b.insert(0, "Bucket", "📉 成交量前五小")
        out.append(b)

    if not out:
        return pd.DataFrame(columns=["Bucket", "Signal", "Symbol", "Price", "Vol", "Type"])

    return pd.concat(out, ignore_index=True)


# --------------------------
# Main function for Streamlit
# --------------------------
def run_for_streamlit() -> pd.DataFrame:
    """
    給 Streamlit 用：回傳已整理好的表格
    欄位：Category / Bucket / Signal / Symbol / Price / Vol
    會輸出最多 20 筆：BULL(10) + BEAR(10)
    """
    try:
        symbols = fetch_futures_symbols_usdt_perp()
        if not symbols:
            return pd.DataFrame([{
                "Category": "",
                "Bucket": "",
                "Signal": "⚠️ 沒抓到任何 USDT 永續合約（exchangeInfo 可能被擋）",
                "Symbol": "",
                "Price": 0,
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
                "Category": "",
                "Bucket": "",
                "Signal": "（無命中）",
                "Symbol": "",
                "Price": 0,
                "Vol": 0,
            }])

        df = pd.DataFrame(rows)

        bull_df = df[df["Type"] == "BULL"].copy()
        bear_df = df[df["Type"] == "BEAR"].copy()

        bull_out = _pick_top_bottom(bull_df, TOP_N, BOT_N)
        bear_out = _pick_top_bottom(bear_df, TOP_N, BOT_N)

        outs = []
        if not bull_out.empty:
            bull_out.insert(0, "Category", "📈 低檔背離（做多留意）")
            outs.append(bull_out)
        if not bear_out.empty:
            bear_out.insert(0, "Category", "📉 高檔背離（做空留意）")
            outs.append(bear_out)

        if not outs:
            return pd.DataFrame([{
                "Category": "",
                "Bucket": "",
                "Signal": "（無命中）",
                "Symbol": "",
                "Price": 0,
                "Vol": 0,
            }])

        out = pd.concat(outs, ignore_index=True)
        out = out[["Category", "Bucket", "Signal", "Symbol", "Price", "Vol"]].copy()

        out["Price"] = pd.to_numeric(out["Price"], errors="coerce").fillna(0.0)
        out["Vol"] = pd.to_numeric(out["Vol"], errors="coerce").fillna(0.0)

        # 讓表格更直覺：同類別內先顯示「前五大」再「前五小」
        bucket_order = {"📊 成交量前五大": 0, "📉 成交量前五小": 1}
        out["_bucket_sort"] = out["Bucket"].map(bucket_order).fillna(9)
        out = out.sort_values(by=["Category", "_bucket_sort", "Vol"], ascending=[True, True, False]).drop(columns=["_bucket_sort"])

        return out.reset_index(drop=True)

    except Exception as e:
        return pd.DataFrame([{
            "Category": "",
            "Bucket": "",
            "Signal": "❌ 掃描失敗（請看錯誤訊息）",
            "Symbol": "",
            "Price": 0,
            "Vol": 0,
        }]).assign(Error=str(e))
