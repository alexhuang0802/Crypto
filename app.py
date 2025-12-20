import streamlit as st
from scanner.core import run_scan

st.title("🚀 Crypto — MACD 背離掃描工具（USDT 永續合約）")
st.write("點擊開始掃描，結果會保留到下一次你再按掃描。")

if "tables" not in st.session_state:
    st.session_state.tables = None

if st.button("🚀 開始掃描"):
    st.session_state.tables = run_scan()
    st.success("完成！")

tables = st.session_state.tables
if tables:
    if not tables["bull_top"].empty:
        st.subheader("📈 低段線背離（做多留意）— 成交量前五大")
        st.dataframe(tables["bull_top"], use_container_width=True)
    if not tables["bull_bot"].empty:
        st.subheader("📈 低段線背離（做多留意）— 成交量前五小")
        st.dataframe(tables["bull_bot"], use_container_width=True)

    if not tables["bear_top"].empty:
        st.subheader("📉 高段線背離（做空留意）— 成交量前五大")
        st.dataframe(tables["bear_top"], use_container_width=True)
    if not tables["bear_bot"].empty:
        st.subheader("📉 高段線背離（做空留意）— 成交量前五小")
        st.dataframe(tables["bear_bot"], use_container_width=True)
