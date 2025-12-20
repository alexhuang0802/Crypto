# app.py
import streamlit as st

st.set_page_config(page_title="Crypto Toolbox", layout="wide")

# =========================
# Header
# =========================
st.title("🧰 Crypto Toolbox")
st.caption("Binance USDT 永續合約工具箱（多功能擴充中）")

st.markdown("### 🚀 目前可用工具")

c1, c2, c3 = st.columns(3)

# =========================
# Tool Card: EMA Cross
# =========================
with c1:
    st.markdown("#### ✅ EMA10 / EMA200 上穿掃描")
    st.write("找出：已上穿 / 即將上穿 / 準備上穿")

    # ✅ 讓使用者可以直接點進下一頁
    # 優先用 page_link（較新 streamlit）
    try:
        st.page_link(
            "pages/1_EMA10_上穿EMA200.py",
            label="➡️ 進入 EMA10 / EMA200 上穿掃描",
            use_container_width=True,
        )
    except Exception:
        # fallback：用按鈕 + switch_page
        if st.button("➡️ 進入 EMA10 / EMA200 上穿掃描", use_container_width=True):
            try:
                st.switch_page("pages/1_EMA10_上穿EMA200.py")
            except Exception:
                st.info("你的 Streamlit 版本不支援自動切頁，請從左側 Pages 點進：EMA10_上穿EMA200")

# =========================
# Tool Card: MACD (coming soon)
# =========================
with c2:
    st.markdown("#### 🟡 MACD 背離掃描（規劃中）")
    st.write("等資料源更穩定後再做（或改走替代資料源）")
    st.caption("狀態：Coming soon")

# =========================
# Tool Card: Others (coming soon)
# =========================
with c3:
    st.markdown("#### 🟡 其他工具（規劃中）")
    st.write("持倉量異動、爆量、型態…")
    st.caption("狀態：Coming soon")

st.markdown("---")
st.markdown("### 📌 使用說明")
st.write(
    "這個首頁是工具入口。請點上方按鈕進入功能頁。\n\n"
    "之後你新增新功能，只要在 `pages/` 下面多放一支 `*.py`，左側就會自動多一個頁面。"
)
