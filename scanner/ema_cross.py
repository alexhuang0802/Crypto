import streamlit as st
from scanner.ema_cross import run_ema_cross_scan

st.set_page_config(page_title="EMA10 上穿 EMA200", layout="wide")
st.title("📈 EMA10 上穿 EMA200 掃描（USDT 永續合約）")

# =========================
# Stop 控制
# =========================
if "stop_scan" not in st.session_state:
    st.session_state.stop_scan = False

def stop_cb():
    return st.session_state.stop_scan

progress = st.progress(0, text="尚未開始")
status = st.empty()

def progress_cb(i, total, sym):
    progress.progress(i / total, text=f"掃描中 {i}/{total} : {sym}")
    status.write(f"目前：{sym}")

# =========================
# 讀取 autorun（從首頁帶過來）
# =========================
autorun = str(st.query_params.get("autorun", "0")) == "1"

with st.sidebar:
    st.subheader("掃描參數")
    timeframe = st.selectbox("TIMEFRAME", ["1m","3m","5m","15m","30m","1h","2h","4h"], index=3)
    kline_limit = st.slider("KLINE_LIMIT", 220, 1500, 300, 10)

    min_qv = st.number_input("MIN_QUOTE_VOLUME_USDT", value=1_000_000.0, step=100_000.0)
    max_symbols = st.slider("MAX_SYMBOLS", 10, 800, 200, 10)  # 預設先 200，比較不容易被擋

    imminent_gap_pct = st.number_input("IMMINENT_GAP_PCT", value=0.001, step=0.0001, format="%.4f")
    prep_gap_pct = st.number_input("PREP_GAP_PCT", value=0.003, step=0.0001, format="%.4f")

    improve_bars_imminent = st.slider("IMPROVE_BARS_IMMINENT", 2, 10, 3, 1)
    improve_bars_prep = st.slider("IMPROVE_BARS_PREP", 3, 20, 6, 1)

    sleep_per_symbol = st.number_input("SLEEP_PER_SYMBOL", value=0.08, step=0.01, format="%.2f")
    timeout = st.number_input("TIMEOUT", value=10, step=1)

    # 你不要讓 user 選 endpoint，所以這裡固定候選
    base_candidates = ["https://data-api.binance.vision", "https://fapi.binance.com"]

    col1, col2 = st.columns(2)
    run_btn = col1.button("🚀 開始掃描", use_container_width=True)
    stop_btn = col2.button("🛑 Stop", use_container_width=True)

if stop_btn:
    st.session_state.stop_scan = True

# =========================
# 自動跑：如果 autorun=1，就把 run_btn 視為 True
# 並且跑完後把 autorun 清掉（避免重整一直跑）
# =========================
if autorun:
    run_btn = True
    # 清掉 query param，避免重新整理又跑一次
    try:
        st.query_params.pop("autorun")
    except Exception:
        st.query_params["autorun"] = "0"

# =========================
# 開始掃描
# =========================
if run_btn:
    st.session_state.stop_scan = False

    with st.spinner("掃描中...（跑完會直接出結果表）"):
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

    st.session_state["ema_tables"] = {
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

# =========================
# 顯示結果
# =========================
tables = st.session_state.get("ema_tables")
if not tables:
    st.info("你可以按左側「開始掃描」，或從首頁按「⚡ 立即掃描」讓它自動跑。")
else:
    p = tables.get("params", {})
    st.success(
        f"掃描完成（或中止）。掃描幣數：{tables['meta']['scanned']}｜"
        f"TIMEFRAME={p.get('timeframe')}｜MAX_SYMBOLS={p.get('max_symbols')}｜MIN_QV={p.get('min_qv')}"
    )

    tab1, tab2, tab3 = st.tabs([
        f"✅ 已上穿 ({len(tables['crossed'])})",
        f"🟡 即將上穿 ({len(tables['imminent'])})",
        f"🔵 準備上穿 ({len(tables['preparing'])})",
    ])

    with tab1:
        st.dataframe(tables["crossed"], use_container_width=True, height=520)
        st.download_button("下載 CSV", tables["crossed"].to_csv(index=False).encode("utf-8-sig"), "ema_crossed.csv")

    with tab2:
        st.dataframe(tables["imminent"], use_container_width=True, height=520)
        st.download_button("下載 CSV", tables["imminent"].to_csv(index=False).encode("utf-8-sig"), "ema_imminent.csv")

    with tab3:
        st.dataframe(tables["preparing"], use_container_width=True, height=520)
        st.download_button("下載 CSV", tables["preparing"].to_csv(index=False).encode("utf-8-sig"), "ema_preparing.csv")

    st.caption("diff = EMA10 - EMA200；diff<0 且連續改善代表正在靠近上穿。")
