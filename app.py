import streamlit as st
import pandas as pd
from scanner.core import run_scan

st.set_page_config(page_title="Crypto Scanner", layout="wide")

st.title("🚀 Crypto — MACD 背離掃描工具")
st.write("點擊下方按鈕執行掃描。結果會保留在頁面上，直到你下次再按一次「開始掃描」。")

# ---------- Session State: 保存上一次結果 ----------
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_meta" not in st.session_state:
    st.session_state.last_meta = None

col1, col2 = st.columns([1, 3])
with col1:
    run_btn = st.button("🚀 開始掃描", use_container_width=True)

with col2:
    if st.session_state.last_meta:
        st.info(f"上次更新：{st.session_state.last_meta}", icon="🕒")

# ---------- 觸發掃描 ----------
if run_btn:
    with st.spinner("掃描中…（可能需要 30~120 秒，視雲端狀況與幣安限制而定）"):
        result = run_scan()  # dict of dfs + meta
    st.session_state.last_result = result
    st.session_state.last_meta = result.get("meta", "（無時間資訊）")
    st.success("完成 ✅")

# ---------- 顯示結果（保留直到下次按） ----------
result = st.session_state.last_result

if not result:
    st.warning("尚未執行掃描，請按「開始掃描」。")
    st.stop()

# 一次最多四個表格：bull_top, bull_bot, bear_top, bear_bot
tables = [
    ("📈 低檔背離（做多留意）— 成交量前五大", "bull_top"),
    ("📈 低檔背離（做多留意）— 成交量前五小", "bull_bot"),
    ("📉 高檔背離（做空留意）— 成交量前五大", "bear_top"),
    ("📉 高檔背離（做空留意）— 成交量前五小", "bear_bot"),
]

# 兩欄排版比較好看
left, right = st.columns(2)

for idx, (title, key) in enumerate(tables):
    df = result.get(key)
    if df is None or df.empty:
        continue

    target_col = left if idx % 2 == 0 else right
    with target_col:
        st.subheader(title)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

# 如果四個都空，顯示原因
if all((result.get(k) is None or result.get(k).empty) for _, k in tables):
    err = result.get("error")
    if err:
        st.error(f"目前沒有可顯示的結果：{err}")
    else:
        st.info("沒有命中訊號（或成交量門檻過濾後為空）。")
