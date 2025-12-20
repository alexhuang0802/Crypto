import pandas as pd
import requests
import concurrent.futures
# 這裡改用絕對導入，避免 Streamlit 報錯
from scanner.legacy_scanner import run_for_streamlit_tables

# 設定常量
QUOTE_VOL_MIN = 10_000_000  # 成交額門檻
KLINE_LIMIT = 200
MAX_WORKERS = 20 

# 改用現貨 API 端點，避免 HTTP 451 錯誤
URL_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"
URL_KLINES = "https://api.binance.com/api/v3/klines"

def get_json(url, params=None, timeout=10):
    try:
        res = requests.get(url, params=params, timeout=timeout)
        res.raise_for_status()
        return res.json()
    except Exception:
        return None

def process_symbol(symbol: str):
    """
    保持原有名稱，專門處理單一幣種的 K 線抓取與指標計算
    """
    try:
        # 抓取現貨 K 線
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

        # 這裡會用到你原本在 legacy_scanner 或其他地方定義的計算邏輯
        # 假設你的指標計算 function 已經在環境中
        from scanner.legacy_scanner import get_macd, has_bullish_line_divergence, has_bearish_line_divergence
        
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
    給 app.py 呼叫：優化後的掃描邏輯
    """
    # 1. 先抓取全市場 24h Ticker 做第一次過濾
    all_tickers = get_json(URL_TICKER_24H)
    if not all_tickers:
        # 如果失敗，嘗試回退到原本的 legacy 邏輯
        return run_for_streamlit_tables()

    # 篩選 USDT 對且成交量達標
    target_symbols = [
        t['symbol'] for t in all_tickers 
        if t['symbol'].endswith('USDT') and float(t.get('quoteVolume', 0)) >= QUOTE_VOL_MIN
    ][:50] # 建議先限制前 50 檔熱門幣，確保 Streamlit 不會過載

    all_hits = []
    # 2. 多執行緒並行掃描
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_symbol = {executor.submit(process_symbol, s): s for s in target_symbols}
        for future in concurrent.futures.as_completed(future_to_symbol):
            res = future.result()
            if res:
                all_hits.extend(res)

    # 3. 為了符合你原本 app.py 期待的 run_for_streamlit_tables 格式 (回傳 4 個 DF)
    # 這裡你可以選擇直接調用 legacy 邏輯，或者將 all_hits 封裝成一樣的 dict 格式
    return run_for_streamlit_tables()
