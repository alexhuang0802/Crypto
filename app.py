import streamlit as st
from scanner.core import run_scan

st.set_page_config(page_title="Crypto Scanner", layout="wide")

st.title("🚀 Crypto — MACD 背離 掃描工具")
st.write("點擊下方按鈕，直接執行掃描並在頁面上顯示結果。")

if st.button("🚀 開始掃描"):
    with st.spinner("掃描中，請稍候（雲端可能會被 Binance 限流，若失敗會顯示 HTTP 錯誤）..."):
        df = run_scan()

    if df is None:
        st.error("run_scan() 回傳 None")
        st.stop()

    st.success(f"完成，共 {len(df)} 筆")
    st.dataframe(df, use_container_width=True)
