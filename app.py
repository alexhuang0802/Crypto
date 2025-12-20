import streamlit as st
import pandas as pd
from scanner.core import run_scan

st.set_page_config(page_title="Crypto Scanner", layout="wide")

st.title("🚀 Crypto — MACD 背離 + 資費套利 掃描工具")
st.write("點擊下方按鈕，直接執行掃描並在頁面上顯示結果。")

# ===== 開始按鈕 =====
if st.button("🚀 開始掃描"):
    with st.spinner("掃描中，請稍候..."):
        df = run_scan()   # 👈 不傳任何參數

    # 保護一下，避免 scanner 回傳怪東西
    if not isinstance(df, pd.DataFrame):
        st.error("run_scan() 沒有回傳 pandas.DataFrame，請檢查 scanner/core.py")
        st.stop()

    st.success(f"✅ 掃描完成，共 {len(df)} 筆結果")

    # ===== 直接在網頁呈現 =====
    st.dataframe(df, use_container_width=True, height=600)

else:
    st.info("請點擊「開始掃描」執行策略")
