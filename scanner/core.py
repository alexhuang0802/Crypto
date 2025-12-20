
import pandas as pd
from .legacy_scanner import scan_macd_main  # 假設你原本主程式叫這個

def run_scan(timeframe="15m", limit=200):
    """
    Streamlit 專用入口
    """
    result = scan_macd_main(
        timeframe=timeframe,
        limit=limit
    )
    return pd.DataFrame(result)
