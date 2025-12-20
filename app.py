# app.py
import streamlit as st

st.set_page_config(page_title="Crypto Toolbox", layout="wide")

st.title("🧰 Crypto Toolbox")
st.caption("Binance USDT 永續合約工具箱（多功能擴充中）")

st.markdown("### 🚀 目前可用工具")
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("#### ✅ EMA10 / EMA200 上穿掃描")
    st.write("找出：已上穿 / 即將上穿 / 準備上穿")

    # 方案：用 query params 讓 EMA 頁自動 autorun
    # Streamlit 的 multipage URL 一般是 /?page=<page_name> 或 /<page>，不同版本略有差異
    # 最穩的方式：用 st.page_link（若可用）直接 link 到 pages 檔案，並帶 query param
    try:
        st.page_link(
            "pages/1_EMA10_上穿EMA200.py?autorun=1",
            label="⚡ 立即掃描（進入後自動跑）",
            use_container_width=True,
        )
        st.page_link(
            "pages/1_EMA10_上穿EMA200.py",
            label="➡️ 只進入頁面（不自動跑）",
            use_container_width=True,
        )
    except Exception:
        # 若 page_link 不支援帶 query string，就用按鈕 + set_query_params 導頁
        if st.button("⚡ 立即掃描（進入後自動跑）", use_container_width=True):
            st.query_params["page"] = "1_EMA10_上穿EMA200"
            st.query_params["autorun"] = "1"
            st.rerun()

        if st.button("➡️ 只進入頁面（不自動跑）", use_container_width=True):
            st.query_params["page"] = "1_EMA10_上穿EMA200"
            st.rerun()

with c2:
    st.markdown("#### 🟡 MACD 背離掃描（規劃中）")
    st.write("等資料源更穩定後再做（或改走替代資料源）")
    st.caption("狀態：Coming soon")

with c3:
    st.markdown("#### 🟡 其他工具（規劃中）")
    st.write("持倉量異動、爆量、型態…")
    st.caption("狀態：Coming soon")

st.markdown("---")
st.markdown("### 📌 使用說明")
st.write("首頁是入口。建議直接按「⚡ 立即掃描」，會跳到 EMA 頁並自動開始掃描，跑完直接出表格。")
