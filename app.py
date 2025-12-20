# app.py
import streamlit as st
from scanner.http import request_json, BASE_CANDIDATES_DEFAULT

st.set_page_config(page_title="Crypto Toolbox", layout="wide")

st.title("🧰 Crypto Toolbox")
st.caption("Binance USDT 永續合約工具箱（多功能擴充中）")

with st.sidebar:
    st.subheader("全站設定（之後各工具共用）")
    if "base_candidates" not in st.session_state:
        st.session_state.base_candidates = BASE_CANDIDATES_DEFAULT

    st.session_state.base_candidates = st.multiselect(
        "API Endpoint 優先順序",
        options=BASE_CANDIDATES_DEFAULT,
        default=st.session_state.base_candidates
    )

st.markdown("### 🚀 目前可用工具")
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("#### ✅ EMA10 / EMA200 上穿掃描")
    st.write("找出：已上穿 / 即將上穿 / 準備上穿")
    st.info("請從左側 Pages 點進：**EMA10_上穿EMA200**")

with c2:
    st.markdown("#### 🟡 MACD 背離掃描（規劃中）")
    st.write("等 API 穩定後再做（或改走替代資料源）")

with c3:
    st.markdown("#### 🟡 其他工具（規劃中）")
    st.write("持倉量異動、爆量、型態…")

st.markdown("---")
st.markdown("### 🩺 API 健康檢查（輕量）")

colA, colB = st.columns([1, 2])
with colA:
    if st.button("測試 Binance API", use_container_width=True):
        try:
            data, used_base = request_json(
                "/fapi/v1/ticker/24hr",
                timeout=8,
                base_candidates=st.session_state.base_candidates,
                max_retries=1,
            )
            st.success(f"OK ✅ 目前可用 endpoint：{used_base}（回傳筆數：{len(data)}）")
        except Exception as e:
            st.error(f"Fail ❌ 目前 endpoints 可能被擋或限流：{e}")

with colB:
    st.write("如果你在部署環境常遇到 451/403：通常是雲端機房/IP 風控。此專案已預設先走 data-api.binance.vision，再 fallback 官方。")
