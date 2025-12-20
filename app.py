import streamlit as st
import pandas as pd
from scanner.core import run_scan

st.set_page_config(page_title="Crypto Scanner", layout="wide")

st.title("🚀 Crypto — MACD 背離 + 資費套利 掃描工具")

if st.button("🚀 開始掃描"):
    with st.spinner("掃描中，請稍候..."):
        df = run_scan()

    st.success(f"完成，共 {len(df)} 筆")
    st.dataframe(df, use_container_width=True)
