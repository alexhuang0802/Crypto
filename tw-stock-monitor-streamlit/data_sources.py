from __future__ import annotations
import pandas as pd
import yfinance as yf

def normalize_tw_ticker(ticker: str) -> str:
    """
    支援輸入:
      2330 -> 2330.TW (預設)
      2330.TW / 2330.TWO -> 그대로
    你也可以做更完整判斷：上市=.TW，上櫃=.TWO
    """
    t = ticker.strip().upper()
    if t.endswith(".TW") or t.endswith(".TWO"):
        return t
    if t.isdigit():
        return f"{t}.TW"
    return t

def fetch_ohlcv_yf(ticker: str, period: str = "5y") -> pd.DataFrame:
    """
    回傳欄位: Date index + Open High Low Close Volume
    """
    t = normalize_tw_ticker(ticker)
    df = yf.download(t, period=period, auto_adjust=False, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename_axis("Date").reset_index()
    # 統一欄位
    keep = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df = df[keep].dropna()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date")
    return df
