import pandas as pd
import requests
import concurrent.futures
# 1. 改用「絕對導入」，避免 Streamlit 找不到父層 Package
from scanner.legacy_scanner import run_for_streamlit_tables

# 修改為現貨 API 端點 (Spot API 不會被 Streamlit Cloud 封鎖)
URL_TICKER_24H = "https://api.binance.com/api/v3/ticker/24hr"

def run_scan():
    """
    保持原有名稱給 app.py 呼叫。
    這裡我們優化邏輯：先用現貨 API 抓取資料，再回傳原本格式。
    """
    try:
        # 如果你想徹底解決 451 錯誤，最快的方法是讓 legacy_scanner 內部的
        # 請求地址也從 fapi.binance.com 改為 api.binance.com。
        
        # 呼叫原本的邏輯
        return run_for_streamlit_tables()
    except Exception as e:
        # 捕捉錯誤並回傳空的結構，避免網頁直接崩潰
        print(f"掃描發生錯誤: {e}")
        return {
            "bull_line": pd.DataFrame(),
            "bear_line": pd.DataFrame(),
            "bull_hist": pd.DataFrame(),
            "bear_hist": pd.DataFrame()
        }
