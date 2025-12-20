# -*- coding: utf-8 -*-
"""
macd_scan_both_loop_tpe.py + 持倉變化排行（期貨版）+ BingX資金費率整合穩定版
（已加上 Streamlit 入口：run_for_streamlit）
"""

import time
import requests
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz

# ====== 設定區 ======
BOT_TOKEN = " "   # Streamlit 版不使用
CHAT_ID = []      # Streamlit 版不使用

KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000

# ✅ 雲端先求穩：降低併發，避免 429
MAX_WORKERS   = 3

EXCLUDED      = {"TUTUSDT", "USDCUSDT", "USDPUSDT"}  # 黑名單
LOOKBACK      = 40
RECENT_BARS   = 5
ALWAYS_SEND   = True
TZ            = pytz.timezone("Asia/Taipei")
KEEP_PER_BUCKET = 5
VOL_TOP_LABEL = "📊 成交量前五大"
VOL_BOT_LABEL = "📉 成交量前五小"

session = requests.Session()
session.headers.update({"User-Agent": "scanner/1.0"})


def get_json(url, params=None, timeout=20, retries=3, backoff=1.2):
    """
    - Streamlit Cloud 常遇到 Binance 限流/擋 IP
    - 這裡加入 retry 並把 status/body 簡化成可讀訊息
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


def tg_send(text: str):
    # Streamlit 版不會呼叫這個
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN / CHAT_ID 未設定，略過發送")
        return
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunk = 3800
    for chat_id in CHAT_ID:
        for i in range(0, len(text), chunk):
            try:
                requests.post(api, data={"chat_id": chat_id, "text": text[i:i + chunk]}, timeout=15)
            except Exception as e:
                print(f"發送 TG 失敗: {e}")


# ====== MACD ======
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


# ====== Binance OI 變化排行（保留，不給 Streamlit 用）=====
def fetch_open_interest_change(symbol):
    try:
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        res = session.get(url, params={"symbol": symbol, "period": "1h", "limit": 2}, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < 2:
            return None
        val_old = float(data[0]["sumOpenInterestValue"])
        val_new = float(data[1]["sumOpenInterestValue"])
        pct_change = ((val_new - val_old) / val_old) * 100 if val_old != 0 else 0
        return {"symbol": symbol, "old": round(val_old / 1_000_000, 2), "new": round(val_new / 1_000_000, 2), "pct": round(pct_change, 2)}
    except:
        return None


# ====== BingX 資費（保留，不給 Streamlit 用）=====
def _norm_symbol(s: str) -> str:
    return str(s).replace("-", "").replace("_", "").upper()


def _parse_bingx_payload(payload):
    out = []
    if not isinstance(payload, dict):
        return out
    data = payload.get("data")
    if data is None:
        return out
    rows = data if isinstance(data, list) else [data]
    for item in rows:
        if not isinstance(item, dict):
            continue
        sym = item.get("symbol")
        rate = item.get("fundingRate", item.get("lastFundingRate", None))
        if sym and rate:
            try:
                out.append({"symbol": _norm_symbol(sym), "fundingRate": float(rate)})
            except:
                pass
    return out


def fetch_bingx_funding_rates(max_workers=8, per_symbol_fallback=False):
    endpoints = [
        "https://open-api.bingx.com/openApi/swap/v2/market/fundingRate",
        "https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex",
    ]
    for url in endpoints:
        try:
            payload = get_json(url, timeout=15)
            rows = _parse_bingx_payload(payload)
            if rows:
                return rows
        except:
            continue
    return []


# ====== 掃描單一 symbol ======
def process_symbol(symbol):
    """用期貨 1h K 線做 MACD 與背離判斷"""
    try:
        t24 = get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": symbol}, timeout=15)
        quote_vol = float(t24.get("quoteVolume", 0.0))
        if quote_vol < QUOTE_VOL_MIN:
            return None

        k = get_json(
            "https://fapi.binance.com/fapi/v1/klines",
            {"symbol": symbol, "interval": "1h", "limit": KLINE_LIMIT},
            timeout=30,
        )
        if not isinstance(k, list) or len(k) < 100:
            return None

        df = pd.DataFrame(
            k,
            columns=[
                "Open Time", "Open", "High", "Low", "Close", "Volume",
                "Close Time", "Quote Asset Volume", "Number of Trades",
                "Taker Buy Base Vol", "Taker Buy Quote Vol", "Ignore",
            ],
        )
        df[["High", "Low", "Close"]] = df[["High", "Low", "Close"]].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["High", "Low", "Close"]).reset_index(drop=True)

        df["MACD"], df["Signal"], df["Hist"] = get_macd(df)
        bull = has_bullish_line_divergence(df)
        bear = has_bearish_line_divergence(df)

        hits = []
        if bull:
            hits.append({"Symbol": symbol, "訊號": "🟢 線背離(低段)", "vol": quote_vol})
        if bear:
            hits.append({"Symbol": symbol, "訊號": "🔴 線背離(高段)", "vol": quote_vol})

        return hits or None

    except Exception:
        return None


# ✅✅✅ Streamlit 專用入口（最重要）
def run_for_streamlit():
    """
    Streamlit 專用：單次掃描、回傳 DataFrame
    - 不排程
    - 不發 TG
    - API 失敗會回傳錯誤 DataFrame，而不是讓 app 掛掉
    """

    # 1) 優先 exchangeInfo
    symbols = []
    try:
        ex = get_json("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=30)
        sym_objs = [
            s for s in ex["symbols"]
            if s.get("quoteAsset") == "USDT"
            and s.get("contractType") == "PERPETUAL"
            and s.get("status") == "TRADING"
            and s["symbol"] not in EXCLUDED
        ]
        symbols = [s["symbol"] for s in sym_objs]

    except Exception as e1:
        # 2) fallback：ticker/24hr
        try:
            tickers = get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=30)
            for t in tickers:
                sym = t.get("symbol")
                if sym and sym.endswith("USDT") and sym not in EXCLUDED:
                    symbols.append(sym)
        except Exception as e2:
            return pd.DataFrame([{
                "Symbol": "",
                "Signal": "❌ Binance API 取得交易對失敗",
                "Type": f"{str(e1)[:120]} | {str(e2)[:120]}",
            }])

    # 3) 掃描
    bull_list, bear_list = [], []
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_symbol, sym) for sym in symbols]
            for fut in as_completed(futures):
                res = fut.result()
                if res:
                    for item in res:
                        if "低段" in item["訊號"]:
                            bull_list.append(item)
                        elif "高段" in item["訊號"]:
                            bear_list.append(item)

    except Exception as e:
        return pd.DataFrame([{
            "Symbol": "",
            "Signal": "❌ 掃描過程失敗（可能限流/被擋）",
            "Type": str(e)[:200],
        }])

    # 4) 組成 DataFrame
    rows = []
    for r in bull_list:
        rows.append({"Symbol": r["Symbol"], "Signal": r["訊號"], "Type": "Bullish"})
    for r in bear_list:
        rows.append({"Symbol": r["Symbol"], "Signal": r["訊號"], "Type": "Bearish"})

    df = pd.DataFrame(rows, columns=["Symbol", "Signal", "Type"])
    return df.sort_values(by=["Type", "Symbol"]).reset_index(drop=True)


# 保留原本排程/發訊版本（Streamlit 不會用到）
def run_once():
    ex = get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
    sym_objs = [s for s in ex["symbols"]
                if s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
                and s["symbol"] not in EXCLUDED]
    symbols = [s["symbol"] for s in sym_objs]

    total, done = len(symbols), 0
    print(f"開始掃描（USDT 永續），共 {total} 檔…")

    bull_list, bear_list = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_symbol, sym): sym for sym in symbols}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                for item in res:
                    if "低段" in item["訊號"]:
                        bull_list.append(item)
                    elif "高段" in item["訊號"]:
                        bear_list.append(item)
            done += 1
            if done % 25 == 0 or done == total:
                print(f"進度：{done}/{total} ({done * 100 // total}%)")
            time.sleep(0.02)

    msg = f"bull={len(bull_list)} bear={len(bear_list)}"
    print(msg)
    if ALWAYS_SEND:
        tg_send(msg)


def scheduler_loop():
    while True:
        now = datetime.now(TZ)
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S%z')}] 執行掃描…")
        run_once()
        hour = now.hour
        interval = 3 * 3600 if 0 <= hour < 6 else 2 * 3600
        print(f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S%z')}] 休息 {interval // 3600} 小時…\n")
        time.sleep(interval)
