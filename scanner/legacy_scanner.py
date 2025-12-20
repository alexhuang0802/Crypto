import pandas as pd
import requests
import concurrent.futures
from datetime import datetime

# 設定常量
QUOTE_VOL_MIN = 10000000  # 舉例：24h 成交額大於 1000 萬 USDT
KLINE_LIMIT = 200
MAX_WORKERS = 20  # 同時執行的線程數，Streamlit Cloud 建議 10-20

# 修改後的現貨 API 端點
URL_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"
URL_KLINES = "https://api.binance.com/api/v3/klines"

def get_json(url, params=None, timeout=10):
    try:
        res = requests.get(url, params=params, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        return None

def process_symbol(symbol: str):
    """
    保持原有名稱。
    注意：此處不再重複抓取 ticker，因為我們會在主程式先過濾好，
    這樣可以省下幾百次 API 請求。
    """
    try:
        # 直接抓取 K 線
        k = get_json(
            URL_KLINES,
            {"symbol": symbol, "interval": "1h", "limit": KLINE_LIMIT},
            timeout=10
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

        # 這裡假設你的 get_macd, has_bullish_line_divergence 等函式已定義在外部
        df["MACD"], df["Signal"], df["Hist"] = get_macd(df)

        bull = has_bullish_line_divergence(df)
        bear = has_bearish_line_divergence(df)

        hits = []
        if bull:
            hits.append({"Symbol": symbol, "Signal": "🟢 線背離(低段)", "Type": "Bullish"})
        if bear:
            hits.append({"Symbol": symbol, "Signal": "🔴 線背離(高段)", "Type": "Bearish"})
        
        return hits or None

    except Exception:
        return None

def run_scan():
    """
    主掃描邏輯：優化後的流程
    """
    # 1. 一次抓取所有現貨 Ticker 過濾成交量 (節省 90% 時間)
    all_tickers = get_json(URL_TICKER_24H)
    if not all_tickers:
        return []

    # 篩選出 USDT 交易對且成交額達標的幣種
    target_symbols = [
        t['symbol'] for t in all_tickers 
        if t['symbol'].endswith('USDT') and float(t.get('quoteVolume', 0)) >= QUOTE_VOL_MIN
    ]

    results = []
    
    # 2. 使用多執行緒並行處理 process_symbol
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 建立任務映射
        future_to_symbol = {executor.submit(process_symbol, s): s for s in target_symbols}
        
        for future in concurrent.futures.as_completed(future_to_symbol):
            hit = future.result()
            if hit:
                results.extend(hit)
                
    return results
