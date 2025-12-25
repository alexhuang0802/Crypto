from __future__ import annotations
import streamlit as st
import pandas as pd

from data_sources import fetch_ohlcv_yf
from analytics import WINDOWS, PRICE_TYPES, compute_return_matrix, bin_returns
from charts import bar_bins

st.set_page_config(page_title="TW Stock Monitor (Streamlit)", layout="wide")

st.title("台股 Rolling 分箱報酬監控（Streamlit 版）")
st.caption("互動版：週/月/年 × 高/收/低 → 9 張 10% 分箱圖（概念對齊 taiwan-stock-monitor）")

with st.sidebar:
    st.header("設定")
    ticker = st.text_input("股票代號", value="2330")
    period = st.selectbox("抓取區間", ["2y", "5y", "10y"], index=1)
    bin_size = st.select_slider("分箱大小", options=[0.05, 0.10, 0.20], value=0.10)
    lo, hi = st.slider("分箱上下限（超出會被 clip）", min_value=-1.0, max_value=1.0, value=(-0.5, 0.5), step=0.05)

@st.cache_data(ttl=3600, show_spinner=False)
def load_data(ticker: str, period: str) -> pd.DataFrame:
    return fetch_ohlcv_yf(ticker, period=period)

df = load_data(ticker, period)

if df.empty:
    st.error("抓不到資料：請確認代號（例如 2330 / 2330.TW / 6488.TWO）或稍後再試")
    st.stop()

st.subheader(f"{ticker} | 資料筆數：{len(df)}")
st.dataframe(df.tail(20), use_container_width=True)

# 產出 9 個矩陣結果（其實是 9 個分箱分佈）
results = []
charts = {}

with st.spinner("計算 Rolling return 與分箱…"):
    for win_name, n in WINDOWS.items():
        for price_type in PRICE_TYPES:
            mat = compute_return_matrix(df, n=n, price_type=price_type)
            b = bin_returns(mat["ret"], bin_size=bin_size, lo=lo, hi=hi)
            key = f"{win_name} × {price_type}"
            charts[key] = bar_bins(b, title=key)
            # 留一份表格可下載
            tmp = b.copy()
            tmp["window"] = win_name
            tmp["price_type"] = price_type
            results.append(tmp)

out_df = pd.concat(results, ignore_index=True)

st.divider()
st.subheader("9 張分箱圖（週/月/年 × 高/收/低）")

# 3 欄排版
cols = st.columns(3)
order = []
for win_name in WINDOWS.keys():
    for pt in PRICE_TYPES:
        order.append(f"{win_name} × {pt}")

for i, k in enumerate(order):
    cols[i % 3].plotly_chart(charts[k], use_container_width=True)

st.divider()
st.subheader("下載分箱統計")
csv = out_df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "下載 CSV",
    data=csv,
    file_name=f"{ticker}_rolling_bins.csv",
    mime="text/csv",
)

with st.expander("我想要更像原專案：3×3 Rolling Distribution Matrix（市場寬度/動能）怎麼做？"):
    st.markdown(
        """
原 repo 的重點還包含「3×3 Rolling Distribution Matrix」用來看市場寬度/動能（偏向跨股票池）。  
你接下來只要補兩件事就能做到：

1) **Universe（全市場股票池）**：例如上市+上櫃+興櫃+ETF 清單  
2) **Cross-sectional 計算**：每天對所有股票算 ret 後，統計各 bin 的佔比，最後做成 3×3（W/M/Y × High/Close/Low）

我可以把「多股票池批次處理 + cache + 進度條 + 失敗重試（jitter）」也一起補上。
"""
    )
