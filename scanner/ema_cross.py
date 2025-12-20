# scanner/ema_cross.py
# -*- coding: utf-8 -*-

import time
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from .http import request_json  # 你前面那支 http.py
from .http import BinanceHTTPError  # 讓 app.py 可以 catch


# ===== 你原本回測/驗證過的參數（保留一致）=====
TIMEFRAME = "15m"
KLINE_LIMIT = 300

MIN_QUOTE_VOLUME_USDT = 1_000_000
MAX_SYMBOLS = 400

IMMINENT_GAP_PCT = 0.001   # 0.10% 以內：即將上穿
PREP_GAP_PCT     = 0.003   # 0.30% 以內：準備上穿

IMPROVE_BARS_IMMINENT = 3
IMPROVE_BARS_PREP     = 6

SLEEP_PER_SYMBOL = 0.08
TIMEOUT = 10
# ============================================


ProgressCB = Callable[[int, int, str], None]
StopCB = Callable[[], bool]


def get_symbols_by_volume(
    min_quote_volume_usdt: float,
    max_symbols: int,
    timeout: int,
    base_candidates: List[str],
) -> Tuple[List[str], str]:
    """
    取 24h ticker，依 quoteVolume 排序，挑出 USDT 永續合約（symbol 結尾 USDT）
    回傳：symbols, used_base
    """
    data, used_base = request_json(
        "/fapi/v1/ticker/24hr",
        params=None,
        timeout=timeout,
        base_candidates=base_candidates,
    )

    rows: List[Tuple[str, float]] = []
    for x in data:
        sym = x.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            qv = float(x.get("quoteVolume", 0.0))
        except Exception:
            continue
        if qv >= float(min_quote_volume_usdt):
            rows.append((sym, qv))

    rows.sort(key=lambda t: t[1], reverse=True)
    symbols = [s for s, _ in rows[: int(max_symbols)]]
    return symbols, used_base


def fetch_klines(
    symbol: str,
    interval: str,
    limit: int,
    timeout: int,
    base_candidates: List[str],
) -> Optional[pd.DataFrame]:
    params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
    k, _used_base = request_json(
        "/fapi/v1/klines",
        params=params,
        timeout=timeout,
        base_candidates=base_candidates,
    )
    if not k:
        return None

    df = pd.DataFrame(k, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "num_trades",
        "taker_base_vol", "taker_quote_vol", "ignore"
    ])
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df


def classify(df: pd.DataFrame) -> Tuple[bool, bool, bool, float, float, float, float]:
    """
    回傳：
    crossed_up, imminent, preparing, score, ema10_last, ema200_last, last_close
    """
    close = df["close"]
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    diff = ema10 - ema200  # >0 代表 EMA10 在上方
    last_close = float(close.iloc[-1])

    imminent_gap = last_close * IMMINENT_GAP_PCT
    prep_gap = last_close * PREP_GAP_PCT

    def improving(n: int) -> bool:
        if len(diff) < n + 1:
            return False
        d = diff.iloc[-(n + 1):].values
        return all(d[i] > d[i - 1] for i in range(1, len(d)))

    crossed_up = (diff.iloc[-2] <= 0) and (diff.iloc[-1] > 0)

    imminent = (
        (diff.iloc[-1] < 0)
        and (abs(diff.iloc[-1]) <= imminent_gap)
        and improving(IMPROVE_BARS_IMMINENT)
    )

    preparing = (
        (diff.iloc[-1] < 0)
        and (abs(diff.iloc[-1]) <= prep_gap)
        and improving(IMPROVE_BARS_PREP)
    )

    score = float(diff.iloc[-1])

    return (
        crossed_up,
        imminent,
        preparing,
        score,
        float(ema10.iloc[-1]),
        float(ema200.iloc[-1]),
        float(last_close),
    )


def run_ema_cross_scan(
    base_candidates: List[str],
    progress_cb: Optional[ProgressCB] = None,
    stop_cb: Optional[StopCB] = None,
):
    """
    給 Streamlit 用的入口：
    - 參數沿用本檔案常數（你回測過的）
    - 只要傳 base_candidates + progress/stop callback 即可
    回傳：crossed_df, imminent_df, preparing_df, meta
    """
    symbols, ticker_base = get_symbols_by_volume(
        min_quote_volume_usdt=MIN_QUOTE_VOLUME_USDT,
        max_symbols=MAX_SYMBOLS,
        timeout=TIMEOUT,
        base_candidates=base_candidates,
    )

    crossed: List[Dict] = []
    imminent: List[Dict] = []
    preparing: List[Dict] = []

    total = len(symbols)

    for i, sym in enumerate(symbols, 1):
        if stop_cb and stop_cb():
            break

        if progress_cb:
            progress_cb(i, total, sym)

        try:
            df = fetch_klines(sym, TIMEFRAME, KLINE_LIMIT, TIMEOUT, base_candidates)
            if df is None or len(df) < 220:
                continue

            c_up, im, prep, _score, e10, e200, last = classify(df)

            item = {
                "symbol": sym,
                "last": last,
                "ema10": e10,
                "ema200": e200,
                "diff": e10 - e200,
                "diff_pct": (e10 - e200) / last * 100.0
            }

            if c_up:
                crossed.append(item)
            elif im:
                imminent.append(item)
            elif prep:
                preparing.append(item)

        except BinanceHTTPError:
            # 這種錯誤要往上丟，讓 UI 顯示「被擋/限流」訊息
            raise
        except Exception:
            # 單一幣錯誤不影響全局
            pass

        if SLEEP_PER_SYMBOL and SLEEP_PER_SYMBOL > 0:
            time.sleep(float(SLEEP_PER_SYMBOL))

    def to_df(arr: List[Dict]) -> pd.DataFrame:
        if not arr:
            return pd.DataFrame(columns=["symbol", "last", "ema10", "ema200", "diff", "diff_pct"])
        return pd.DataFrame(arr).sort_values("diff", ascending=False).reset_index(drop=True)

    meta = {
        "ticker_base": ticker_base,
        "scanned": total,
        "timeframe": TIMEFRAME,
        "kline_limit": KLINE_LIMIT,
        "min_quote_volume_usdt": MIN_QUOTE_VOLUME_USDT,
        "max_symbols": MAX_SYMBOLS,
        "imminent_gap_pct": IMMINENT_GAP_PCT,
        "prep_gap_pct": PREP_GAP_PCT,
        "improve_bars_imminent": IMPROVE_BARS_IMMINENT,
        "improve_bars_prep": IMPROVE_BARS_PREP,
        "sleep_per_symbol": SLEEP_PER_SYMBOL,
        "timeout": TIMEOUT,
    }

    return to_df(crossed), to_df(imminent), to_df(preparing), meta
