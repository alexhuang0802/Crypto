from __future__ import annotations
import numpy as np
import pandas as pd

WINDOWS = {
    "Week (5D)": 5,
    "Month (20D)": 20,
    "Year (250D)": 250,
}

PRICE_TYPES = ["High", "Close", "Low"]

def rolling_ref_price(df: pd.DataFrame, n: int, price_type: str) -> pd.Series:
    """
    用「過去 n 個交易日（不含當日）」當參考區間：
      - High: 參考區間最高價
      - Low : 參考區間最低價
      - Close: 參考區間最後一日收盤（也可改平均/中位數）
    """
    s = df[price_type].astype(float)

    if price_type == "High":
        ref = s.shift(1).rolling(n, min_periods=n).max()
    elif price_type == "Low":
        ref = s.shift(1).rolling(n, min_periods=n).min()
    else:  # Close
        ref = s.shift(1).rolling(n, min_periods=n).apply(lambda x: x[-1], raw=True)

    return ref

def compute_return_matrix(
    df: pd.DataFrame,
    n: int,
    price_type: str,
) -> pd.DataFrame:
    """
    回傳每一天的 (ref_price, today_price, return)
    return = today_price / ref_price - 1
    """
    ref = rolling_ref_price(df, n, price_type)
    today = df[price_type].astype(float)
    ret = (today / ref) - 1.0
    out = pd.DataFrame({
        "Date": df["Date"],
        "ref_price": ref,
        "today_price": today,
        "ret": ret
    }).dropna()
    return out

def bin_returns(ret_series: pd.Series, bin_size: float = 0.10, lo: float = -0.5, hi: float = 0.5) -> pd.DataFrame:
    """
    10% 分箱（預設 -50% ~ +50%），回傳各 bin 的 count、占比
    """
    s = ret_series.dropna().astype(float).clip(lo, hi)
    bins = np.arange(lo, hi + bin_size, bin_size)
    labels = [f"{int(b*100):+d}%~{int((b+bin_size)*100):+d}%" for b in bins[:-1]]
    cat = pd.cut(s, bins=bins, labels=labels, include_lowest=True, right=False)
    counts = cat.value_counts().reindex(labels).fillna(0).astype(int)
    pct = (counts / max(counts.sum(), 1)).round(4)
    return pd.DataFrame({"bin": labels, "count": counts.values, "pct": pct.values})
