# app.py
import streamlit as st
from scanner.ema_cross import run_ema_cross_scan

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

# -------------------------
# Sidebar: Market / Tool 선택
# -------------------------
with st.sidebar:
    st.title("🧰 Toolbox")
    st.session_state.market = st.radio(
        "市場",
        ["台股", "幣圈"],
        index=0 if st.session_state.market == "台股" else 1
    )

    if st.session_state.market == "幣圈":
        st.session_state.tool = st.radio(
            "幣圈工具",
            ["EMA", "MACD", "其他"],
            index={"EMA": 0, "MACD": 1, "其他": 2}[st.session_state.tool]
        )
    else:
        st.session_state.tool = "台股"

# -------------------------
# Header
# -------------------------
st.title("Crypto Toolbox")
st.caption("先做台股（後續補上）→ 再做幣圈工具（EMA / MACD / 其他）")

# -------------------------
# Helper: Progress callbacks
# -------------------------
progress = st.progress(0, text="尚未開始")
status = st.empty()

def stop_cb():
    return st.session_state.stop_scan

def progress_cb(i, total, sym):
    progress.progress(i / total, text=f"掃描中 {i}/{total} : {sym}")
    status.write(f"目前：{sym}")

# -------------------------
# Main layout
# -------------------------
if st.session_state.market == "台股":
    st.subheader("🇹🇼 台股（Coming soon）")
    st.info("台股版本先放入口，後續會補上：資料源、EMA/MACD/型態掃描、選股條件等。")
    st.markdown("你之後想先做台股的哪個功能？我建議順序：**EMA 上穿 → MACD 背離 → 量價異常**。")

else:
    st.subheader("🪙 幣圈（USDT 永續合約）")

    # --- 三個工具入口（同頁面切換，不跳頁） ---
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### ✅ EMA10 / EMA200 上穿掃描")
        st.caption("已上穿 / 即將上穿 / 準備上穿")
        if st.button("進入 EMA 工具", use_container_width=True):
            st.session_state.tool = "EMA"

    with col2:
        st.markdown("### 🟡 MACD 背離掃描（後續補上）")
        st.caption("API 風控問題，等資料源穩定再做")
        if st.button("進入 MACD（Coming soon）", use_container_width=True):
            st.session_state.tool = "MACD"

    with col3:
        st.markdown("### 🟡 其他工具（後續補上）")
        st.caption("持倉量異動 / 爆量 / 型態...")
        if st.button("進入其他工具（Coming soon）", use_container_width=True):
            st.session_state.tool = "其他"

    st.divider()

    # -------------------------
    # Tool: EMA
    # -------------------------
    if st.session_state.tool == "EMA":
        st.markdown("## 📈 EMA10 上穿 EMA200 掃描")

        # 參數區（放在 expander，畫面乾淨）
        with st.expander("⚙️ 掃描參數（可調整）", expanded=True):
            cA, cB, cC = st.columns(3)
            with cA:
                timeframe = st.selectbox("TIMEFRAME", ["1m","3m","5m","15m","30m","1h","2h","4h"], index=3)
                kline_limit = st.slider("KLINE_LIMIT", 220, 1500, 300, 10)
            with cB:
                min_qv = st.number_input("MIN_QUOTE_VOLUME_USDT", value=1_000_000.0, step=100_000.0)
                # 預設先保守（避免被擋），你要再往上調
                max_symbols = st.slider("MAX_SYMBOLS", 10, 800, 200, 10)
            with cC:
                sleep_per_symbol = st.number_input("SLEEP_PER_SYMBOL", value=0.08, step=0.01, format="%.2f")
                timeout = st.number_input("TIMEOUT", value=10, step=1)

            cD, cE, cF = st.columns(3)
            with cD:
                imminent_gap_pct = st.number_input("IMMINENT_GAP_PCT", value=0.001, step=0.0001, format="%.4f")
            with cE:
                prep_gap_pct = st.number_input("PREP_GAP_PCT", value=0.003, step=0.0001, format="%.4f")
            with cF:
                improve_bars_imminent = st.slider("IMPROVE_BARS_IMMINENT", 2, 10, 3, 1)
                improve_bars_prep = st.slider("IMPROVE_BARS_PREP", 3, 20, 6, 1)

        # 控制按鈕
        b1, b2, b3 = st.columns([1, 1, 2])
        with b1:
            run_now = st.button("⚡ 立即掃描（直接跑出資料）", use_container_width=True)
        with b2:
            stop_now = st.button("🛑 Stop", use_container_width=True)
        with b3:
            if st.button("🧹 清除結果", use_container_width=True):
                st.session_state.ema_tables = None
                st.session_state.stop_scan = False
                st.rerun()

        if stop_now:
            st.session_state.stop_scan = True

        # 固定 endpoint（你說不要給 user 選）
        base_candidates = ["https://data-api.binance.vision", "https://fapi.binance.com"]

        # 掃描
        if run_now:
            st.session_state.stop_scan = False
            progress.progress(0, text="開始掃描...")
            status.empty()

            with st.spinner("掃描中... 跑完會直接出表格"):
                crossed_df, imminent_df, preparing_df, meta = run_ema_cross_scan(
                    timeframe=timeframe,
                    kline_limit=kline_limit,
                    min_quote_volume_usdt=min_qv,
                    max_symbols=max_symbols,
                    imminent_gap_pct=imminent_gap_pct,
                    prep_gap_pct=prep_gap_pct,
                    improve_bars_imminent=improve_bars_imminent,
                    improve_bars_prep=improve_bars_prep,
                    sleep_per_symbol=sleep_per_symbol,
                    timeout=timeout,
                    base_candidates=base_candidates,
                    progress_cb=progress_cb,
                    stop_cb=stop_cb,
                )

            st.session_state.ema_tables = {
                "crossed": crossed_df,
                "imminent": imminent_df,
                "preparing": preparing_df,
                "meta": meta,
                "params": {
                    "timeframe": timeframe,
                    "max_symbols": max_symbols,
                    "min_qv": min_qv,
                }
            }

        # 顯示結果
        tables = st.session_state.ema_tables
        if not tables:
            st.info("按「⚡ 立即掃描」後，這裡會直接顯示三個結果表。")
        else:
            p = tables.get("params", {})
            st.success(
                f"完成（或中止）。掃描幣數：{tables['meta']['scanned']}｜"
                f"TIMEFRAME={p.get('timeframe')}｜MAX_SYMBOLS={p.get('max_symbols')}｜MIN_QV={p.get('min_qv')}"
            )

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
        st.info("先把資料源問題解掉再做：雲端 IP 常被 Binance Futures 擋。之後可以改走替代資料源或做快取。")

    else:
        st.markdown("## 🟡 其他工具（Coming soon）")
        st.info("持倉量異動 / 爆量 / 型態… 之後在這裡加。")
