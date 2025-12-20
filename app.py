# app.py
import streamlit as st

from scanner.ema_cross import run_ema_cross_scan
from scanner.http import BinanceHTTPError  # 用來 catch API 被擋/限流

st.set_page_config(page_title="Crypto Toolbox", layout="wide")

# -------------------------
# Session defaults
# -------------------------
if "market" not in st.session_state:
    st.session_state.market = "幣圈"
if "tool" not in st.session_state:
    st.session_state.tool = "EMA"
if "stop_scan" not in st.session_state:
    st.session_state.stop_scan = False
if "ema_tables" not in st.session_state:
    st.session_state.ema_tables = None
if "ema_last_error" not in st.session_state:
    st.session_state.ema_last_error = None  # 記錄上次錯誤（不影響舊結果顯示）

# -------------------------
# Sidebar: Market / Tool
# -------------------------
with st.sidebar:
    st.title("🧰 Toolbox")
    st.session_state.market = st.radio("市場", ["台股", "幣圈"], index=0 if st.session_state.market == "台股" else 1)

    if st.session_state.market == "幣圈":
        st.session_state.tool = st.radio("幣圈工具", ["EMA", "MACD", "其他"], index={"EMA": 0, "MACD": 1, "其他": 2}[st.session_state.tool])
    else:
        st.session_state.tool = "台股"

# -------------------------
# Header
# -------------------------
st.title("Crypto Toolbox")
st.caption("先有台股（後續補上）→ 再來是幣圈工具（EMA / MACD / 其他）")

# -------------------------
# Helpers: progress / stop
# -------------------------
progress = st.progress(0, text="尚未開始")
status = st.empty()

def stop_cb():
    return st.session_state.stop_scan

def progress_cb(i, total, sym):
    progress.progress(i / total, text=f"掃描中 {i}/{total} : {sym}")
    status.write(f"目前：{sym}")

# -------------------------
# Main content
# -------------------------
if st.session_state.market == "台股":
    st.subheader("🇹🇼 台股（Coming soon）")
    st.info("台股功能先放入口，後續補上：資料源/選股條件/掃描器。")

else:
    st.subheader("🪙 幣圈")

    # --- 幣圈下面三個入口 ---
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### ✅ EMA10 / EMA200 上穿掃描")
        st.caption("已上穿 / 即將上穿 / 準備上穿")
        if st.button("進入 EMA", use_container_width=True):
            st.session_state.tool = "EMA"

    with col2:
        st.markdown("### 🟡 MACD 背離掃描（後續補上）")
        st.caption("等資料源更穩定再做")
        if st.button("進入 MACD", use_container_width=True):
            st.session_state.tool = "MACD"

    with col3:
        st.markdown("### 🟡 其他工具（後續補上）")
        st.caption("持倉量異動 / 爆量 / 型態...")
        if st.button("進入其他工具", use_container_width=True):
            st.session_state.tool = "其他"

    st.divider()

    # -------------------------
    # Tool: EMA
    # -------------------------
    if st.session_state.tool == "EMA":
        st.markdown("## 📈 EMA10 上穿 EMA200 掃描")

        # 只留按鈕，不顯示參數
        b1, b2, b3 = st.columns([1, 1, 2])

        with b1:
            run_now = st.button("⚡ 立即掃描（直接跑出資料）", use_container_width=True)
        with b2:
            stop_now = st.button("🛑 Stop", use_container_width=True)
        with b3:
            clear_now = st.button("🧹 清除結果", use_container_width=True)

        if stop_now:
            st.session_state.stop_scan = True

        if clear_now:
            st.session_state.ema_tables = None
            st.session_state.ema_last_error = None
            st.session_state.stop_scan = False
            st.rerun()

        # 固定 endpoint（你不要給 user 選）
        base_candidates = ["https://data-api.binance.vision", "https://fapi.binance.com"]

        # 按下掃描：才會更新結果；否則保留舊結果不動
        if run_now:
            st.session_state.stop_scan = False
            st.session_state.ema_last_error = None
            progress.progress(0, text="開始掃描...")
            status.empty()

            try:
                with st.spinner("掃描中... 跑完會直接出表格"):
                    crossed_df, imminent_df, preparing_df, meta = run_ema_cross_scan(
                        base_candidates=base_candidates,
                        progress_cb=progress_cb,
                        stop_cb=stop_cb,
                        # ✅ 其餘參數全部寫死在 scanner/ema_cross.py 內
                    )

                st.session_state.ema_tables = {
                    "crossed": crossed_df,
                    "imminent": imminent_df,
                    "preparing": preparing_df,
                    "meta": meta,
                }

            except BinanceHTTPError as e:
                # ✅ 不炸站：顯示錯誤，但舊結果保留
                st.session_state.ema_last_error = str(e)

            except Exception as e:
                st.session_state.ema_last_error = f"Unexpected: {e}"

        # 顯示「上次錯誤」（如果有），但不清掉舊結果
        if st.session_state.ema_last_error:
            st.error(
                "本次掃描失敗（API 被擋/限流或網路問題）。\n\n"
                f"{st.session_state.ema_last_error}\n\n"
                "✅ 舊的結果仍保留在下方。"
            )

        # 顯示結果：一直留著直到下次掃描或你清除
        tables = st.session_state.ema_tables
        if not tables:
            st.info("目前還沒有結果。按「⚡ 立即掃描」後會產生結果並保留到下次查詢。")
        else:
            meta = tables.get("meta", {})
            st.success(f"結果已載入｜掃描幣數：{meta.get('scanned')}｜Ticker base：{meta.get('ticker_base')}")

            t1, t2, t3 = st.tabs([
                f"✅ 已上穿 ({len(tables['crossed'])})",
                f"🟡 即將上穿 ({len(tables['imminent'])})",
                f"🔵 準備上穿 ({len(tables['preparing'])})",
            ])

            with t1:
                st.dataframe(tables["crossed"], use_container_width=True, height=520)
                st.download_button("下載 CSV", tables["crossed"].to_csv(index=False).encode("utf-8-sig"), "ema_crossed.csv")

            with t2:
                st.dataframe(tables["imminent"], use_container_width=True, height=520)
                st.download_button("下載 CSV", tables["imminent"].to_csv(index=False).encode("utf-8-sig"), "ema_imminent.csv")

            with t3:
                st.dataframe(tables["preparing"], use_container_width=True, height=520)
                st.download_button("下載 CSV", tables["preparing"].to_csv(index=False).encode("utf-8-sig"), "ema_preparing.csv")

            st.caption("diff = EMA10 - EMA200；diff<0 且連續改善代表正在靠近上穿。")

    elif st.session_state.tool == "MACD":
        st.markdown("## 🟡 MACD 背離掃描（Coming soon）")
        st.info("等資料源穩定後再補。")

    else:
        st.markdown("## 🟡 其他工具（Coming soon）")
        st.info("持倉量異動 / 爆量 / 型態…之後在這裡加。")
