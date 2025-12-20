# scanner/ema_cross.py
import time
import pandas as pd

from .http import request_json  # ✅ 用相對匯入，避免路徑問題


def get_symbols_by_volume(
    min_quote_volume_usdt: float,
    max_symbols: int,
    timeout: int,
    base_candidates,
):
    data, used_base = request_json(
        "/fapi/v1/ticker/24hr",
        timeout=timeout,
        base_candidates=base_candidates,
    )

    rows = []
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


def fetch_klines(symbol: str, interval: str, limit: int, timeout: int, base_candidates):
    params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
    k, used_base = request_json(
        "/fapi/v1/klines",
        params=params,
        timeout=timeout,
        base_candidates=base_candidates,
    )
    if not k:
        return None, used_base

    df = pd.DataFrame(k, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_volume","num_trades",
        "taker_base_vol","taker_quote_vol","ignore"
    ])
    for col in ["open","high","low","close","volume","quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df, used_base


def classify(
    df: pd.DataFrame,
    imminent_gap_pct: float,
    prep_gap_pct: float,
    improve_bars_imminent: int,
    improve_bars_prep: int,
):
    close = df["close"]
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    diff = ema10 - ema200
    last_close = float(close.iloc[-1])

    imminent_gap = last_close * float(imminent_gap_pct)
    prep_gap = last_close * float(prep_gap_pct)

    def improving(n: int) -> bool:
        if len(diff) < n + 1:
            return False
        d = diff.iloc[-(n + 1):].values
        return all(d[i] > d[i - 1] for i in range(1, len(d)))

    crossed_up = (diff.iloc[-2] <= 0) and (diff.iloc[-1] > 0)
    imminent = (diff.iloc[-1] < 0) and (abs(diff.iloc[-1]) <= imminent_gap) and improving(int(improve_bars_imminent))
    preparing = (diff.iloc[-1] < 0) and (abs(diff.iloc[-1]) <= prep_gap) and improving(int(improve_bars_prep))

    return crossed_up, imminent, preparing, float(ema10.iloc[-1]), float(ema200.iloc[-1]), float(last_close)


def run_ema_cross_scan(
    timeframe: str,
    kline_limit: int,
    min_quote_volume_usdt: float,
    max_symbols: int,
    imminent_gap_pct: float,
    prep_gap_pct: float,
    improve_bars_imminent: int,
    improve_bars_prep: int,
    sleep_per_symbol: float,
    timeout: int,
    base_candidates,
    progress_cb=None,
    stop_cb=None,
):
    symbols, ticker_base = get_symbols_by_volume(
        min_quote_volume_usdt=min_quote_volume_usdt,
        max_symbols=max_symbols,
        timeout=timeout,
        base_candidates=base_candidates,
    )

    crossed, imminent, preparing = [], [], []

    for i, sym in enumerate(symbols, 1):
        if stop_cb and stop_cb():
            break

        if progress_cb:
            progress_cb(i, len(symbols), sym)

        try:
            df, _ = fetch_klines(sym, timeframe, kline_limit, timeout, base_candidates)
            if df is None or len(df) < 220:
                continue

            c_up, im, prep, e10, e200, last = classify(
                df,
                imminent_gap_pct=imminent_gap_pct,
                prep_gap_pct=prep_gap_pct,
                improve_bars_imminent=improve_bars_imminent,
                improve_bars_prep=improve_bars_prep,
            )

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

        except Exception:
            pass

        if sleep_per_symbol and sleep_per_symbol > 0:
            time.sleep(float(sleep_per_symbol))

    def to_df(arr):
        if not arr:
            return pd.DataFrame(columns=["symbol","last","ema10","ema200","diff","diff_pct"])
        return pd.DataFrame(arr).sort_values("diff", ascending=False).reset_index(drop=True)

    meta = {"ticker_base": ticker_base, "scanned": len(symbols)}
    return to_df(crossed), to_df(imminent), to_df(preparing), meta
