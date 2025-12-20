import streamlit as st
from scanner.core import run_scan

st.set_page_config(
    page_title="Crypto — MACD 背離 掃描工具",
    layout="wide"
)

st.title("🚀 Crypto — MACD 背離 掃描工具")
st.write("點擊下方按鈕，直接執行掃描並在頁面上顯示結果。")

# ====== 初始化 session_state ======
if "scan_df" not in st.session_state:
    st.session_state.scan_df = None

# ====== 按鈕 ======
if st.button("🚀 開始掃描"):
    with st.spinner("掃描中，請稍候…"):
        df = run_scan()                     # 呼叫你的 scanner
        st.session_state.scan_df = df       # ⭐ 存起來
    st.success(f"完成，共 {len(df)} 筆")

# ====== 顯示結果（只要有資料就顯示）=====
if st.session_state.scan_df is not None:
    st.dataframe(
        st.session_state.scan_df,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("尚未執行掃描")
