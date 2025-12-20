# -*- coding: utf-8 -*-
"""
legacy_scanner.py (Streamlit 版 - Spot API with fallback endpoints)

- 只做：Spot 1h K 線（USDT）MACD 線背離掃描
- 同時支援：
  - 低檔背離（做多留意）  -> BULL
  - 高檔背離（做空留意）  -> BEAR
- 輸出限制（你指定）：
  - 低檔：成交量前五大 + 前五小（最多 10）
  - 高檔：成交量前五大 + 前五小（最多 10）
  => 全部最多 20 筆
- 額外顯示：目前價格 Price（從 /ticker/24hr 的 lastPrice 來）
- 解決：Streamlit Cloud 直連 Binance 常見 451/403/429
  -> 用多個 base endpoint 失敗自動切換
"""

import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ====== 固定參數（照你原本寫死） ======
KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000
MAX_WORKERS   = 4
EXCLUDED      = {"USDCUSDT", "USDPUSDT"}  # 你要 TWT 就不要排除它
LOOKBACK      = 40
RECENT_BARS   = 5

TOP_N = 5  # 成交量前五大
BOT_N = 5  # 成交量前五小

# ====== 多個 endpoint（會自動 fallback）=====
# 建議把 data-api.binance.vision 放第一個（雲端比較不容易 451）
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
    """
    低檔背離（做多留意）
    近 lookback 內：價格創更低 Low，但 MACD 沒創更低（MACD 變高）
    """
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["Low"].idxmin()

        if (
            df["Low"].iloc[i] < df["Low"].loc[prior_idx]
            and df["MACD"].iloc[i] > df["MACD"].loc[prior_idx]
        ):
            if i >= len(df) - recent:
                return True
    return False

def has_bearish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    """
    高檔背離（做空留意）
    近 lookback 內：MACD 創更高，但價格 High 沒創更高（或更低）
    """
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window["High"].idxmax()

        if (
            df["MACD"].iloc[i] > df["MACD"].loc[prior_idx]
            and df["High"].iloc[i] <= df["High"].loc[prior_idx]
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
    每個 dict 會包含：Symbol / Signal / Type / Vol / Price
    """
    try:
        # 24hr ticker 同時拿到成交量與 lastPrice（你要的目前價格）
        t24 = get_json("/api/v3/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = float(t24.get("quoteVolume", 0.0))
        last_price = float(t24.get("lastPrice", 0.0))

        if quote_vol < QUOTE_VOL_MIN:
            return None

        # K 線
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
            hits.append({
                "Symbol": symbol,
                "Signal": "🟢 線背離(低段)",
                "Type": "BULL",
                "Vol": quote_vol,
                "Price": last_price,
            })
        if bear:
            hits.append({
                "Symbol": symbol,
                "Signal": "🔴 線背離(高段)",
                "Type": "BEAR",
                "Vol": quote_vol,
                "Price": last_price,
            })

        return hits or None

    except Exception:
        return None


def _pick_top_bottom(df: pd.DataFrame, n_top=TOP_N, n_bot=BOT_N) -> pd.DataFrame:
    """
    針對同一類（BULL 或 BEAR）：
    - 取成交量前 n_top
    - 取成交量前 n_bot（最小）
    回傳最多 n_top + n_bot（且去重 Symbol）
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["Bucket", "Symbol", "Price", "Signal", "Type", "Vol"])

    df = df.sort_values("Vol", ascending=False).copy()

    top_df = df.head(n_top).copy()
    bot_df = df.sort_values("Vol", ascending=True).head(n_bot).copy()

    # 去重：如果 top/bot 有重複（例如資料太少），避免重複出現
    used = set()
    rows = []

    for _, r in top_df.iterrows():
        sym = r["Symbol"]
        if sym in used:
            continue
        used.add(sym)
        rows.append({**r.to_dict(), "Bucket": "📊 成交量前五大"})

    for _, r in bot_df.iterrows():
        sym = r["Symbol"]
        if sym in used:
            continue
        used.add(sym)
        rows.append({**r.to_dict(), "Bucket": "📉 成交量前五小"})

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["Bucket", "Symbol", "Price", "Signal", "Type", "Vol"])

    # 排序：先前五大再前五小；各自內部再依 Vol 排序
    bucket_order = {"📊 成交量前五大": 0, "📉 成交量前五小": 1}
    out["_bucket_order"] = out["Bucket"].map(bucket_order).fillna(9)
    out = out.sort_values(by=["_bucket_order", "Vol"], ascending=[True, False]).drop(columns=["_bucket_order"])
    return out


def run_for_streamlit() -> pd.DataFrame:
    """
    給 Streamlit 用：回傳已整理好的表格
    欄位：Category / Bucket / Signal / Symbol / Price / Vol
    """
    try:
        symbols = fetch_spot_symbols_usdt()
        if not symbols:
            return pd.DataFrame([{
                "Category": "",
                "Bucket": "",
                "Signal": "⚠️ 沒抓到任何 USDT 交易對（exchangeInfo 可能仍被擋）",
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

        # 分別處理 BULL / BEAR，並限制每類只輸出 10（5大+5小）
        bull_df = df[df["Type"] == "BULL"].copy()
        bear_df = df[df["Type"] == "BEAR"].copy()

        bull_out = _pick_top_bottom(bull_df, TOP_N, BOT_N)
        bear_out = _pick_top_bottom(bear_df, TOP_N, BOT_N)

        if not bull_out.empty:
            bull_out.insert(0, "Category", "📈 低段線背離（做多留意）")
        if not bear_out.empty:
            bear_out.insert(0, "Category", "📉 高段線背離（做空留意）")

        out = pd.concat([bull_out, bear_out], ignore_index=True)

        if out.empty:
            return pd.DataFrame([{
                "Category": "",
                "Bucket": "",
                "Signal": "（無命中）",
                "Symbol": "",
                "Price": 0,
                "Vol": 0,
            }])

        # 欄位排序（你要看起來像之前 console 那樣：先類別、再成交量多/少）
        out = out[["Category", "Bucket", "Signal", "Symbol", "Price", "Vol"]].copy()

        # 讓 Price / Vol 數字更好看（可選：不想格式化可刪）
        out["Price"] = pd.to_numeric(out["Price"], errors="coerce").fillna(0.0)
        out["Vol"] = pd.to_numeric(out["Vol"], errors="coerce").fillna(0.0)

        return out

    except Exception as e:
        return pd.DataFrame([{
            "Category": "",
            "Bucket": "",
            "Signal": "❌ 掃描失敗（請看錯誤訊息）",
            "Symbol": "",
            "Price": 0,
            "Vol": 0,
        }]).assign(Error=str(e))
