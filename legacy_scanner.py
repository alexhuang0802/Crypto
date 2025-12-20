# -*- coding: utf-8 -*-
"""
Created on Sat Oct 18 11:36:55 2025

@author: AlexHuang 
"""

# -*- coding: utf-8 -*-
"""
macd_scan_both_loop_tpe.py + 持倉變化排行（期貨版）+ BingX資金費率整合穩定版
"""

import time
import requests
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz

# ====== 設定區 ======
BOT_TOKEN = "8041061344:AAEaPljQwnvWI8QJnkt_q3VBz1RmU14KDB8"
CHAT_ID = [

]

KLINE_LIMIT   = 720
QUOTE_VOL_MIN = 5_000_000          
MAX_WORKERS   = 8
EXCLUDED      = {"TUTUSDT", "USDCUSDT", "USDPUSDT"} #tut黑名單
LOOKBACK      = 40
RECENT_BARS   = 5
ALWAYS_SEND   = True
TZ            = pytz.timezone("Asia/Taipei")
KEEP_PER_BUCKET = 5
VOL_TOP_LABEL = "📊 成交量前五大"
VOL_BOT_LABEL = "📉 成交量前五小"

session = requests.Session()
session.headers.update({"User-Agent": "scanner/1.0"})


def get_json(url, params=None, timeout=20):
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def tg_send(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("BOT_TOKEN / CHAT_ID 未設定，略過發送")
        return
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunk = 3800
    for chat_id in CHAT_ID:
        for i in range(0, len(text), chunk):
            try:
                requests.post(api, data={"chat_id": chat_id, "text": text[i:i+chunk]}, timeout=15)
            except Exception as e:
                print(f"發送 TG 失敗: {e}")

# ====== MACD背離 
def get_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    return macd, signal_line, hist

def has_bullish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window['Low'].idxmin()
        if df['Low'].iloc[i] < df['Low'].iloc[prior_idx] and df['MACD'].iloc[i] > df['MACD'].iloc[prior_idx]:
            if i >= len(df) - recent:
                return True
    return False

def has_bearish_line_divergence(df, lookback=LOOKBACK, recent=RECENT_BARS):
    for i in range(lookback, len(df)):
        window = df.iloc[i - lookback:i]
        prior_idx = window['High'].idxmax()
        if df['MACD'].iloc[i] > df['MACD'].iloc[prior_idx] and df['High'].iloc[i] <= df['High'].iloc[prior_idx]:
            if i >= len(df) - recent:
                return True
    return False

# ====== Binance OI 變化排行
def fetch_open_interest_change(symbol):
    """抓取 1h OI 金額變化（USDT 永續）"""
    try:
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        res = session.get(url, params={"symbol": symbol, "period": "1h", "limit": 2}, timeout=10)
        data = res.json()
        if not isinstance(data, list) or len(data) < 2:
            return None
        val_old = float(data[0]['sumOpenInterestValue'])
        val_new = float(data[1]['sumOpenInterestValue'])
        pct_change = ((val_new - val_old) / val_old) * 100 if val_old != 0 else 0
        return {
            "symbol": symbol,
            "old": round(val_old / 1_000_000, 2),
            "new": round(val_new / 1_000_000, 2),
            "pct": round(pct_change, 2)
        }
    except:
        return None

# ====== BingX資費
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
    """回傳 [{'symbol':'BTCUSDT','fundingRate':0.0001}, ...]"""
    endpoints = [
        "https://open-api.bingx.com/openApi/swap/v2/market/fundingRate",
        "https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex"
    ]
    for url in endpoints:
        try:
            payload = get_json(url, timeout=15)
            rows = _parse_bingx_payload(payload)
            if rows:
                return rows
        except:
            continue
    if per_symbol_fallback:
        try:
            c_payload = get_json("https://open-api.bingx.com/openApi/swap/v2/quote/contracts", timeout=15)
            contracts = [c["symbol"] for c in c_payload.get("data", []) if "symbol" in c]
            contracts = list({_norm_symbol(s) for s in contracts})
            results = []
            def _one(sym):
                query_sym = sym.replace("USDT", "-USDT")
                p = get_json("https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex", {"symbol": query_sym})
                rows = _parse_bingx_payload(p)
                return rows[0] if rows else None
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                for fut in as_completed([ex.submit(_one, s) for s in contracts]):
                    r = fut.result()
                    if r:
                        results.append(r)
            return results
        except:
            pass
    return []

# ====== OI + 1h 價格變化 + BingX資費
def get_top_open_interest_changes(top_n_each=5, min_usdt=10_000_000):
    """
    一小時內持倉量變化（增加前5名、減少前5名），附實際過去1小時漲跌幅(%)，
    並加上 BingX 資金費率極端前五名
    """
    try:
        # 1) 期貨交易對名單（USDT 永續）
        symbols_data = get_json("https://fapi.binance.com/fapi/v1/exchangeInfo")
        symbols = [
            s["symbol"] for s in symbols_data["symbols"]
            if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT"
        ]

        # 2) 抓 OI 變化 + 計算真 1h 價格漲跌
        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_open_interest_change, sym) for sym in symbols]
            for fut in as_completed(futures):
                res = fut.result()
                if res and max(res["old"], res["new"]) * 1_000_000 > min_usdt:
                    try:
                        k = get_json("https://fapi.binance.com/fapi/v1/klines",
                                     {"symbol": res["symbol"], "interval": "1h", "limit": 2})
                        if isinstance(k, list) and len(k) >= 2:
                            open_p = float(k[0][1])
                            close_p = float(k[1][4])
                            pct = ((close_p - open_p) / open_p) * 100
                        else:
                            pct = 0.0
                    except:
                        pct = 0.0
                    res["price_change"] = round(pct, 2)
                    results.append(res)

        df = pd.DataFrame(results)
        if df.empty:
            return "📊 一小時內持倉變化：\n（無符合條件）"

        df_inc = df[df["pct"] > 0].sort_values(by="pct", ascending=False).head(top_n_each)
        df_dec = df[df["pct"] < 0].sort_values(by="pct", ascending=True).head(top_n_each)

        lines = ["📊 一小時內持倉變化排行"]

        if not df_inc.empty:
            lines.append("\n🟢 持倉量增加前五名")
            for i, r in enumerate(df_inc.itertuples(), 1):
                lines.append(f"{i}. {r.symbol:10s} {r.old:>5.1f}M ➔ {r.new:>5.1f}M (+{r.pct:>4.1f}%)  💹{r.price_change:+.2f}%")

        if not df_dec.empty:
            lines.append("\n🔴 持倉量減少前五名")
            for i, r in enumerate(df_dec.itertuples(), 1):
                lines.append(f"{i}. {r.symbol:10s} {r.old:>5.1f}M ➔ {r.new:>5.1f}M ({r.pct:>5.1f}%)  💹{r.price_change:+.2f}%")

        # 3) BingX 資金費率極端排行
        try:
            rates = fetch_bingx_funding_rates(max_workers=10, per_symbol_fallback=False)
            if not rates:
                rates = fetch_bingx_funding_rates(max_workers=6, per_symbol_fallback=True)

            if not rates:
                lines.append("\n⚡ BingX 資金費率極端前五名：資料來源目前不可用")
            else:
                df_rate = pd.DataFrame(rates)
                df_rate = df_rate[pd.to_numeric(df_rate["fundingRate"], errors="coerce").notna()]
                if df_rate.empty:
                    lines.append("\n⚡ BingX 資金費率極端前五名：無有效資料")
                else:
                    df_pos = df_rate.sort_values(by="fundingRate", ascending=False).head(5)
                    df_neg = df_rate.sort_values(by="fundingRate", ascending=True).head(5)

                    lines.append("\n⚡ BingX 資金費率極端前五名")
                    lines.append("🟢 正資金費率最高前五")
                    for i, r in enumerate(df_pos.itertuples(), 1):
                        lines.append(f"{i}. {r.symbol:10s} {r.fundingRate*100:+.4f}%")

                    lines.append("\n🔴 負資金費率最低前五")
                    for i, r in enumerate(df_neg.itertuples(), 1):
                        lines.append(f"{i}. {r.symbol:10s} {r.fundingRate*100:+.4f}%")
        except Exception as e:
            lines.append(f"\n⚡ BingX 資金費率取得失敗：{e}")

        return "\n".join(lines)

    except Exception as e:
        return f"📊 一小時內持倉變化：\n（操作失敗: {e}）"


def process_symbol(symbol):
    """用期貨 1h K 線做 MACD 與背離判斷"""
    try:
        # 用期貨 24hr ticker 取成交金額過濾
        t24 = get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": symbol})
        quote_vol = float(t24.get("quoteVolume", 0.0))
        if quote_vol < QUOTE_VOL_MIN:
            return None

        # 用期貨 K 線
        k = get_json("https://fapi.binance.com/fapi/v1/klines",
                     {"symbol": symbol, "interval": "1h", "limit": KLINE_LIMIT}, timeout=30)
        if not isinstance(k, list) or len(k) < 100:
            return None

        df = pd.DataFrame(k, columns=[
            "Open Time","Open","High","Low","Close","Volume",
            "Close Time","Quote Asset Volume","Number of Trades",
            "Taker Buy Base Vol","Taker Buy Quote Vol","Ignore"
        ])
        df[["High","Low","Close"]] = df[["High","Low","Close"]].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["High","Low","Close"]).reset_index(drop=True)

        df['MACD'], df['Signal'], df['Hist'] = get_macd(df)
        bull = has_bullish_line_divergence(df)
        bear = has_bearish_line_divergence(df)

        hits = []
        if bull: hits.append({"Symbol": symbol, "訊號": "🟢 線背離(低段)", "vol": quote_vol})
        if bear: hits.append({"Symbol": symbol, "訊號": "🔴 線背離(高段)", "vol": quote_vol})
        return hits or None
    except:
        return None

def build_table(df: pd.DataFrame, title: str) -> str:
    if df is None or df.empty:
        df = pd.DataFrame([{"訊號": "—", "Symbol": "（無命中）"}])
    signal_width = 14
    symbol_width = 14
    df["訊號"] = df["訊號"].astype(str).str.ljust(signal_width)
    df["Symbol"] = df["Symbol"].astype(str).str.ljust(symbol_width)
    lines = [title]
    for _, row in df.iterrows():
        lines.append(f"{row['訊號']}{row['Symbol']}")
    return "\n".join(lines)

def select_rows_by_volume(items, keep_each=KEEP_PER_BUCKET):
    if not items:
        return []
    sorted_desc = sorted(items, key=lambda x: (x.get("vol") or 0.0), reverse=True)
    sorted_asc = list(reversed(sorted_desc))
    used = set()
    top_pick, bot_pick = [], []
    for it in sorted_desc:
        sym = it["Symbol"]
        if sym in used:
            continue
        top_pick.append(it)
        used.add(sym)
        if len(top_pick) >= keep_each:
            break
    for it in sorted_asc:
        sym = it["Symbol"]
        if sym in used:
            continue
        bot_pick.append(it)
        used.add(sym)
        if len(bot_pick) >= keep_each:
            break
    rows = []
    if top_pick:
        rows.append({"訊號": VOL_TOP_LABEL, "Symbol": ""})
        for r in top_pick:
            rows.append({"訊號": r["訊號"], "Symbol": r["Symbol"]})
    if bot_pick:
        rows.append({"訊號": VOL_BOT_LABEL, "Symbol": ""})
        for r in bot_pick:
            rows.append({"訊號": r["訊號"], "Symbol": r["Symbol"]})
    return rows[:keep_each*2 + 2]

def run_once():
    # 期貨名單（USDT 永續）
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
                print(f"進度：{done}/{total} ({done*100//total}%)")
            time.sleep(0.02)

    bull_rows = select_rows_by_volume(bull_list)
    bear_rows = select_rows_by_volume(bear_list)

    bull_df = pd.DataFrame(bull_rows)[["訊號","Symbol"]] if bull_rows else pd.DataFrame()
    bear_df = pd.DataFrame(bear_rows)[["訊號","Symbol"]] if bear_rows else pd.DataFrame()

    msg = "\n\n".join([
        build_table(bull_df, "📈 低段線背離（做多留意）"),
        build_table(bear_df, "📉 高段線背離（做空留意）"),
        get_top_open_interest_changes(),
        "(策略筆記，非投資建議)"
    ])
    print(msg)
    if (not bull_df.empty) or (not bear_df.empty) or ALWAYS_SEND:
        tg_send(msg)

def scheduler_loop():
    while True:
        now = datetime.now(TZ)
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S%z')}] 執行掃描…")
        run_once()
        hour = now.hour
        interval = 3*3600 if 0 <= hour < 6 else 2*3600
        print(f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S%z')}] 休息 {interval//3600} 小時…\n")
        time.sleep(interval)

if __name__ == "__main__":

    run_once()
    # scheduler_loop()
