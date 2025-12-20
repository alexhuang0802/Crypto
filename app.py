import streamlit as st
import pandas as pd
from scanner.core import run_scan

st.set_page_config(page_title="Crypto Futures Scanner", layout="wide")
st.title("🚀 Crypto — MACD 背離掃描工具（USDT 永續合約）")
st.write("點擊下方按鈕，直接執行掃描並在頁面上顯示結果（結果會保留到下一次你再按掃描）。")

# ✅ 初始化 session_state，讓資料不會一下就不見
if "last_df" not in st.session_state:
    st.session_state.last_df = None

if st.button("🚀 開始掃描"):
    with st.spinner("掃描中...（雲端可能較慢，請稍等）"):
        df = run_scan()
        st.session_state.last_df = df
    st.success(f"完成，共 {len(df)} 筆")

# ✅ 不管有沒有按按鈕，只要有上次結果就顯示
df = st.session_state.last_df
if isinstance(df, pd.DataFrame) and not df.empty:
    st.dataframe(df, use_container_width=True)
elif isinstance(df, pd.DataFrame) and df.empty:
    st.info("（無命中）")
