# scanner/legacy_scanner.py
# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版 - USDT 永續合約 Futures)
- 只做：USDT 永續合約 1h K 線 MACD 背離掃描（BULL 低檔 / BEAR 高檔）
- 輸出：4 個表格（低檔/高檔 × 成交量前五大/前五小），最多 20 筆
- 追加：Price (最新價) / Vol (24h quoteVolume)
- 解決：Streamlit Cloud 直連 fapi.binance.com 可能被 451/403/429
- 做法：fapi mirror endpoints fallback + 重試 + backoff
"""

import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd


# ====== 固定參數（你原本寫死的） ======
KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000
MAX_WORKERS   = 6          # Cloud 建議不要太大
EXCLUDED      = {"TUTUSDT", "USDCUSDT", "USDPUSDT"}
LOOKBACK      = 40
RECENT_BARS   = 5

TOP_N = 5
BOT_N = 5


# ====== Endpoint fallback（期貨要用 fapi）======
# ✅ 注意：data-api.binance.vision 是 Spot 鏡像，不一定支援 /fapi
# ✅ 期貨常用鏡像：fapi.binance.vision
BASE_CANDIDATES = [
    "https://fapi.binance.vision",
    "https://fapi.binance.com",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (scanner/1.0)",
    "Accept": "application/json",
})


def _to_path(url_or_path: str) -> str:
    """
    支援：
    - '/fapi/v1/exchangeInfo'
    - 'https://fapi.binance.com/fapi/v1/exchangeInfo'
    轉成 path：'/fapi/v1/exchangeInfo'
    """
    s = (url_or_path or "").strip()
    if s.startswith("http://") or s.startswith("https://"):
        p = urlparse(s)
        return p.path or "/"
    return s if s.startswith("/") else ("/" + s)


def _request_json(base: str, url_or_path: str, params=None, timeout=20):
    path = _to_path(url_or_path)
    url = f"{base}{path}"
    r = session.get(url, params=params, timeout=timeout)
    if r.status_code >= 400:
        text = (r.text or "")[:300]
        raise requests.HTTPError(f"HTTP {r.status_code} for {url} params={params} body={text}")
    return r.json()


def get_json(url_or_path: str, params=None, timeout=20, retries=2, backoff=1.2):
    """
    依序嘗試 BASE_CANDIDATES；
    每個 base 失敗會重試 retries 次；
    全部失敗才 raise。
    """
    last_err = None
    for base in BASE_CANDIDATES:
        for i in range(retries):
            try:
                return _request_json(base, url_or_path, params=params, timeout=timeout)
            except Exception as e:
                last_err = e
                time.sleep(backoff * (i + 1))
    raise last_err


# ====== MACD ======
def get_macd(df: pd.DataFrame, fast=12, slow=26, signal=9):
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist


def has_bullish_line_divergence(df: pd.DataFrame, lookback=LOOKBACK, recent=RECENT_BARS) -> bool:
    """
    低檔背離（做多留意）：
    - 價格創更低 Low
    - MACD 同時比前低點更高（回升）
    - 訊號落在最近 recent 根
    """
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["Low"].idxmin()
        if df["Low"].iloc[i] < df["Low"].iloc[prior_idx] and df["MACD"].iloc[i] > df["MACD"].iloc[prior_idx]:
            if i >= len(df) - recent:
                return True
    return False


def has_bearish_line_divergence(df: pd.DataFrame, lookback=LOOKBACK, recent=RECENT_BARS) -> bool:
    """
    高檔背離（做空留意）：
    - 價格未創更高 High（或走平）
    - MACD 卻創更高（動能衰竭）
    - 訊號落在最近 recent 根
    """
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["High"].idxmax()
        if df["MACD"].iloc[i] > df["MACD"].iloc[prior_idx] and df["High"].iloc[i] <= df["High"].iloc[prior_idx]:
            if i >= len(df) - recent:
                return True
    return False


# ====== Futures symbols（USDT PERPETUAL）======
def fetch_futures_symbols_usdt() -> list[str]:
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


def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def process_symbol(symbol: str):
    """
    回傳 list[dict] or None
    dict: Symbol/Signal/Type/Vol/Price
    """
    try:
        # 24hr ticker（期貨）
        t24 = get_json("/fapi/v1/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = _safe_float(t24.get("quoteVolume", 0.0), 0.0)
        price = _safe_float(t24.get("lastPrice", 0.0), 0.0)

        if quote_vol < QUOTE_VOL_MIN:
            return None

        k = get_json("/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": KLINE_LIMIT}, timeout=25)
        if not isinstance(k, list) or len(k) < 120:
            return None

        df = pd.DataFrame(k, columns=[
            "Open Time","Open","High","Low","Close","Volume",
            "Close Time","Quote Asset Volume","Number of Trades",
            "Taker Buy Base Vol","Taker Buy Quote Vol","Ignore"
        ])
        df[["High","Low","Close"]] = df[["High","Low","Close"]].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["High","Low","Close"]).reset_index(drop=True)

        df["MACD"], df["SignalLine"], df["Hist"] = get_macd(df)

        bull = has_bullish_line_divergence(df)
        bear = has_bearish_line_divergence(df)

        hits = []
        if bull:
            hits.append({"Symbol": symbol, "Signal": "🟢 線背離(低段)", "Type": "BULL", "Vol": quote_vol, "Price": price})
        if bear:
            hits.append({"Symbol": symbol, "Signal": "🔴 線背離(高段)", "Type": "BEAR", "Vol": quote_vol, "Price": price})
        return hits or None

    except Exception:
        return None


def _pick_top_bottom(df: pd.DataFrame, top_n=TOP_N, bot_n=BOT_N) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    依成交量 Vol 取 Top N + Bottom N
    """
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df2 = df.copy()
    df2["Vol"] = pd.to_numeric(df2["Vol"], errors="coerce").fillna(0.0)
    df2 = df2.sort_values("Vol", ascending=False)

    top_df = df2.head(top_n).copy()
    bot_df = df2.tail(bot_n).copy().sort_values("Vol", ascending=True)

    return top_df, bot_df


def _format_bucket(df: pd.DataFrame, bucket_label: str, category_label: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    out.insert(0, "Category", category_label)
    out.insert(1, "Bucket", bucket_label)
    # 欄位順序
    out = out[["Category", "Bucket", "Signal", "Symbol", "Price", "Vol"]]
    out["Price"] = pd.to_numeric(out["Price"], errors="coerce").fillna(0.0)
    out["Vol"] = pd.to_numeric(out["Vol"], errors="coerce").fillna(0.0)
    return out


def run_for_streamlit_tables() -> dict:
    """
    回傳 4 個表格（DataFrame）
    keys:
      - bull_top, bull_bot, bear_top, bear_bot
    """
    try:
        symbols = fetch_futures_symbols_usdt()
        if not symbols:
            err = pd.DataFrame([{
                "Category": "",
                "Bucket": "",
                "Signal": "⚠️ 沒抓到任何 USDT 永續合約（exchangeInfo 可能被擋）",
                "Symbol": "",
                "Price": 0,
                "Vol": 0,
            }])
            return {"bull_top": err, "bull_bot": pd.DataFrame(), "bear_top": pd.DataFrame(), "bear_bot": pd.DataFrame()}

        rows = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = [ex.submit(process_symbol, sym) for sym in symbols]
            for fut in as_completed(futs):
                res = fut.result()
                if res:
                    rows.extend(res)
                time.sleep(0.005)

        if not rows:
            empty = pd.DataFrame([{
                "Category": "",
                "Bucket": "",
                "Signal": "（無命中）",
                "Symbol": "",
                "Price": 0,
                "Vol": 0,
            }])
            return {"bull_top": empty, "bull_bot": pd.DataFrame(), "bear_top": pd.DataFrame(), "bear_bot": pd.DataFrame()}

        df = pd.DataFrame(rows)

        bull_df = df[df["Type"] == "BULL"].copy()
        bear_df = df[df["Type"] == "BEAR"].copy()

        bull_top, bull_bot = _pick_top_bottom(bull_df, TOP_N, BOT_N)
        bear_top, bear_bot = _pick_top_bottom(bear_df, TOP_N, BOT_N)

        bull_top = _format_bucket(bull_top, "📊 成交量前五大", "📈 低段線背離（做多留意）")
        bull_bot = _format_bucket(bull_bot, "📉 成交量前五小", "📈 低段線背離（做多留意）")
        bear_top = _format_bucket(bear_top, "📊 成交量前五大", "📉 高段線背離（做空留意）")
        bear_bot = _format_bucket(bear_bot, "📉 成交量前五小", "📉 高段線背離（做空留意）")

        return {
            "bull_top": bull_top,
            "bull_bot": bull_bot,
            "bear_top": bear_top,
            "bear_bot": bear_bot,
        }

    except Exception as e:
        err = pd.DataFrame([{
            "Category": "",
            "Bucket": "",
            "Signal": "❌ 掃描失敗（請看錯誤訊息）",
            "Symbol": "",
            "Price": 0,
            "Vol": 0,
            "Error": str(e),
        }])
        return {"bull_top": err, "bull_bot": pd.DataFrame(), "bear_top": pd.DataFrame(), "bear_bot": pd.DataFrame()}


# 相容：若你 app.py / core.py 還有人在叫舊名字
def run_for_streamlit():
    """
    舊版相容：回傳單一表格（把 4 表 concat 起來）
    """
    tables = run_for_streamlit_tables()
    frames = [tables.get("bull_top"), tables.get("bull_bot"), tables.get("bear_top"), tables.get("bear_bot")]
    frames = [f for f in frames if isinstance(f, pd.DataFrame) and not f.empty]
    if not frames:
        return pd.DataFrame([{"Category":"","Bucket":"","Signal":"（無命中）","Symbol":"","Price":0,"Vol":0}])
    return pd.concat(frames, ignore_index=True)
