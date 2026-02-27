# -*- coding: utf-8 -*-
from __future__ import annotations

import os, json, time
import requests
import pandas as pd
import matplotlib.pyplot as plt
from dataclasses import dataclass
from datetime import datetime, timezone

print("=== VERSION: BINGX | ONLY last 2 CLOSED 45m | SIGNAL only if ENGULFING | SIGNAL-ONLY OUTPUT | TG DEBUG ===")

# =========================================================
# Config
# =========================================================
BINGX_BASE = "https://open-api.bingx.com"
STATE_FILE = "last_seen_local.json"

SOURCE_INTERVAL = "15m"
TARGET_INTERVAL_MIN = 45
LIMIT_15M = 800
PLOT_BARS = 140

# 吞噬模式：
#   "body"  = 實體吞噬（最嚴格）
#   "range" = 範圍吞噬（較寬鬆）
ENGULF_MODE = "body"

# SL：針尖 +0.25%
CRYPTO_STOP_BUFFER = 0.0025

# body/range 門檻：0.0 = 關閉
MIN_BODY_TO_RANGE = 0.0

# API 剛更新緩衝（避免剛收線但 API 還沒同步）
GRACE_SECONDS = 10

# 吞噬K的實體 必須 >= 被吞K的幾倍
# 1.0 = 只要比他大就好
# 1.2 = 至少大20%
# 1.5 = 至少大50%
MIN_ENGULF_BODY_RATIO = 1.3

# 做多：上引線（壞）不得超過實體的幾倍；下引線（好）可放寬到幾倍
MAX_BAD_WICK_TO_BODY_LONG  = 1.0   # 上引線 <= 1x body
MAX_GOOD_WICK_TO_BODY_LONG = 3.0   # 下引線 <= 3x body（放寬）

# 做空：下引線（壞）不得超過實體的幾倍；上引線（好）可放寬到幾倍
MAX_BAD_WICK_TO_BODY_SHORT  = 1.0  # 下引線 <= 1x body
MAX_GOOD_WICK_TO_BODY_SHORT = 3.0  # 上引線 <= 3x body（放寬）
# =========================================================
# Output control
# =========================================================
SHOW_NO_SIGNAL_MSG = True
NO_SIGNAL_MSG_TEXT = "❌ No signals this run."

# 是否畫圖（預設關閉，比較穩）
PLOT_ON_SIGNAL = False

# =========================================================
# Telegram control
# =========================================================
ENABLE_TG = True

# ⚠️ 建議你之後重新換 token（你已經貼過在聊天室，風險很高）
TG_BOT_TOKEN = "8041061344:AAEaPljQwnvWI8QJnkt_q3VBz1RmU14KDB8"

# 你的群組/對話 chat_id（注意很多群是 -100xxxxxxxxxx）
TG_CHAT_IDS = [
     -5227897042 #莉莉老師 帶你賺錢
]

# ✅ TG 是否只送「NEW」訊號？
# 先設 False：只要有訊號就送，方便你驗證 TG 通不通
SEND_TG_ONLY_IF_NEW = False

# =========================================================
# Symbols
# =========================================================
BINGX_SWAP_SYMBOLS = {
    #"1000PEPEUSDT": "1000PEPE-USDT",
     "ETHUSDT": "ETH-USDT",
     "BTCUSDT": "BTC-USDT",
     #"UNIUSDT": "UNI-USDT",
     "BNBUSDT": "BNB-USDT",
     "XRPUSDT": "XRP-USDT",
     "SOLUSDT": "SOL-USDT",
    # "TRXUSDT": "TRX-USDT",
     #"DOGEUSDT": "DOGE-USDT",
}

# =========================================================
# Data model
# =========================================================
@dataclass
class Signal:
    symbol: str
    market: str
    candle_open_time_utc: str
    candle_close_time_utc: str
    direction: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    r: float
    reason: str

# =========================================================
# Utils
# =========================================================
def utc_now_ts() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")

def interval_to_ms(interval: str) -> int:
    if interval.endswith("m"):
        return int(interval[:-1]) * 60_000
    if interval.endswith("h"):
        return int(interval[:-1]) * 60 * 60_000
    raise ValueError(f"Unsupported interval: {interval}")

def is_green(o, c): return c > o
def is_red(o, c): return c < o
def wick_ok_by_direction(o, h, l, c, direction: str) -> bool:
    """
    direction = "LONG" or "SHORT"
    LONG:  上引線(壞)限制嚴格；下引線(好)放寬
    SHORT: 下引線(壞)限制嚴格；上引線(好)放寬
    """
    o = float(o); h = float(h); l = float(l); c = float(c)

    body = abs(c - o)
    if body <= 1e-12:  # 幾乎沒實體(十字/極小K) 直接不合格
        return False

    upper_wick = max(0.0, h - max(o, c))
    lower_wick = max(0.0, min(o, c) - l)

    if direction == "LONG":
        # 壞：上引線；好：下引線
        return (upper_wick <= body * MAX_BAD_WICK_TO_BODY_LONG) and \
               (lower_wick <= body * MAX_GOOD_WICK_TO_BODY_LONG)

    if direction == "SHORT":
        # 壞：下引線；好：上引線
        return (lower_wick <= body * MAX_BAD_WICK_TO_BODY_SHORT) and \
               (upper_wick <= body * MAX_GOOD_WICK_TO_BODY_SHORT)

    return False
def body_to_range_ratio(o, h, l, c) -> float:
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    return body / rng

def load_state():
    try:
        if not os.path.exists(STATE_FILE):
            return {}
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def should_show(symbol, candle_close_time_utc, direction, state):
    key = symbol
    cur = f"{candle_close_time_utc}|{direction}"
    if state.get(key) == cur:
        return False
    state[key] = cur
    return True

# =========================================================
# Telegram (prints ONLY on failure)
# =========================================================
def tg_send(text: str):
    if not ENABLE_TG:
        return
    if not TG_BOT_TOKEN or not TG_CHAT_IDS:
        print("⚠️ TG config empty (TG_BOT_TOKEN / TG_CHAT_IDS).")
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"

    for chat_id in TG_CHAT_IDS:
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True
                },
                timeout=15
            )
            if resp.status_code != 200:
                print(f"❌ TG failed chat_id={chat_id} status={resp.status_code} resp={resp.text}")
        except Exception as e:
            print(f"❌ TG exception chat_id={chat_id}: {e}")

# =========================================================
# Output format (your red-box block)
# =========================================================
def format_signal_block(sig: Signal) -> str:
    return (
        f"✅ SIGNAL: {sig.symbol} {sig.direction} | entry={sig.entry:.6g} stop={sig.stop:.6g}\n"
        f"tp1={sig.tp1:.6g} tp2={sig.tp2:.6g}"
    )

def format_signal_text_for_tg(sig: Signal) -> str:
    emoji = "🟢" if sig.direction == "LONG" else "🔴"

    return (
        f"{emoji}【45M 進場訊號】{sig.symbol}\n\n"
        f"方向：{sig.direction}\n"
        f"進場價：{sig.entry:.6g}\n"
        f"停損價：{sig.stop:.6g}\n\n"
        f"🎯 目標一：{sig.tp1:.6g}\n"
        f"🎯 目標二：{sig.tp2:.6g}\n\n"
        f"📊 型態：45分K戰法\n"
     #   f"⏰ 收線時間：{sig.candle_close_time_utc}\n"
        f"⚙️ 系統：Crypto Robert Auto Trader"
    )

# =========================================================
# Fetch BingX swap klines
# =========================================================
def fetch_bingx_swap_klines(symbol: str, interval: str = "15m", limit: int = 800) -> pd.DataFrame:
    url = f"{BINGX_BASE}/openApi/swap/v3/quote/klines"

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    int_ms = interval_to_ms(interval)
    start_ms = now_ms - (limit * int_ms)

    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": str(start_ms),
        "endTime": str(now_ms),
        "limit": str(limit),
    }

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    j = r.json()

    data = j.get("data") if isinstance(j, dict) else None
    if not data:
        raise RuntimeError(f"No data from BingX for {symbol}. Raw={j}")

    rows = []
    for item in data:
        if isinstance(item, dict):
            t = item.get("time") or item.get("openTime") or item.get("t")
            if t is None:
                continue
            t = int(t)
            o = float(item.get("open")  or item.get("o"))
            h = float(item.get("high")  or item.get("h"))
            l = float(item.get("low")   or item.get("l"))
            c = float(item.get("close") or item.get("c"))
            v = float(item.get("volume") or item.get("v") or 0.0)
            rows.append((t, o, h, l, c, v))
        elif isinstance(item, (list, tuple)) and len(item) >= 6:
            t = int(item[0])
            o = float(item[1]); h = float(item[2]); l = float(item[3]); c = float(item[4]); v = float(item[5])
            rows.append((t, o, h, l, c, v))

    df = pd.DataFrame(rows, columns=["open_time_ms","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    df["close_time"] = df["time"] + pd.Timedelta(milliseconds=int_ms)

    return df[["time","close_time","open","high","low","close","volume"]]

# =========================================================
# Resample 15m -> 45m aligned by close_time
# =========================================================
def resample_to_45m(df15: pd.DataFrame) -> pd.DataFrame:
    d = df15.copy().set_index("close_time")
    rule = f"{TARGET_INTERVAL_MIN}min"
    rs = dict(rule=rule, label="right", closed="right")

    df45 = pd.DataFrame({
        "open":   d["open"].resample(**rs).first(),
        "high":   d["high"].resample(**rs).max(),
        "low":    d["low"].resample(**rs).min(),
        "close":  d["close"].resample(**rs).last(),
        "volume": d["volume"].resample(**rs).sum(),
    }).dropna()

    df45 = df45.reset_index()  # close_time
    df45["time"] = df45["close_time"] - pd.Timedelta(minutes=TARGET_INTERVAL_MIN)
    return df45[["time","close_time","open","high","low","close","volume"]]

def drop_unclosed_45m(df45: pd.DataFrame) -> pd.DataFrame:
    now = utc_now_ts() - pd.Timedelta(seconds=GRACE_SECONDS)
    return df45[df45["close_time"] <= now].copy()

# =========================================================
# Engulfing (ONLY last 2 closed bars)
# =========================================================
def is_bearish_engulf(prev, cur, mode: str) -> bool:
    prev_o, prev_h, prev_l, prev_c = map(float, [prev["open"], prev["high"], prev["low"], prev["close"]])
    cur_o,  cur_h,  cur_l,  cur_c  = map(float, [cur["open"],  cur["high"],  cur["low"],  cur["close"]])

    if not (is_green(prev_o, prev_c) and is_red(cur_o, cur_c)):
        return False

    if mode == "range":
        return (cur_h >= prev_h) and (cur_l <= prev_l)

    # body
    return (cur_o >= prev_c) and (cur_c <= prev_o)

def is_bullish_engulf(prev, cur, mode: str) -> bool:
    prev_o, prev_h, prev_l, prev_c = map(float, [prev["open"], prev["high"], prev["low"], prev["close"]])
    cur_o,  cur_h,  cur_l,  cur_c  = map(float, [cur["open"],  cur["high"],  cur["low"],  cur["close"]])

    if not (is_red(prev_o, prev_c) and is_green(cur_o, cur_c)):
        return False

    if mode == "range":
        return (cur_h >= prev_h) and (cur_l <= prev_l)

    # body
    return (cur_o <= prev_c) and (cur_c >= prev_o)

def wick_body_ok(o, h, l, c, max_wick_to_body: float = 1.0) -> bool:
    """
    回傳 True 表示這根K棒的上下引線都不會超過實體。
    規則：upper_wick <= body*max_ratio 且 lower_wick <= body*max_ratio
    """
    o = float(o); h = float(h); l = float(l); c = float(c)

    body = abs(c - o)
    if body <= 1e-12:  # doji 或近乎沒實體：直接視為不合格
        return False

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    # 避免資料異常造成負值
    upper_wick = max(0.0, upper_wick)
    lower_wick = max(0.0, lower_wick)

    return (upper_wick <= body * max_wick_to_body) and (lower_wick <= body * max_wick_to_body)

def compute_signal_only_if_last2_engulf(df45_closed: pd.DataFrame, symbol: str) -> Signal | None:
    """
    只看最後兩根 45m：
    - 必須吞噬
    - 吞噬K實體必須明顯大於被吞K（避免差不多長的假吞噬）
    """

    if len(df45_closed) < 2:
        return None

    prev = df45_closed.iloc[-2]
    cur  = df45_closed.iloc[-1]

    prev_o, prev_h, prev_l, prev_c = map(float, [prev["open"], prev["high"], prev["low"], prev["close"]])
    cur_o,  cur_h,  cur_l,  cur_c  = map(float, [cur["open"],  cur["high"],  cur["low"],  cur["close"]])

    prev_body = abs(prev_c - prev_o)
    cur_body  = abs(cur_c - cur_o)

    # ❌ 排除：實體太小
    if cur_body <= 1e-12 or prev_body <= 1e-12:
        return None

    # ❌ 排除：吞噬強度不足（你現在要的重點）
    if cur_body < prev_body * MIN_ENGULF_BODY_RATIO:
        return None

    # 原本實體比例濾網
    ratio = body_to_range_ratio(cur_o, cur_h, cur_l, cur_c)
    if ratio < MIN_BODY_TO_RANGE:
        return None

    bear = is_bearish_engulf(prev, cur, ENGULF_MODE)
    bull = is_bullish_engulf(prev, cur, ENGULF_MODE)

    if not (bear or bull):
        return None

    cur_t  = pd.Timestamp(cur["time"]).tz_convert("UTC")
    cur_ct = pd.Timestamp(cur["close_time"]).tz_convert("UTC")

    entry = cur_c

    if bear:
        direction = "SHORT"
        stop = cur_h * (1 + CRYPTO_STOP_BUFFER)
        r = stop - entry
        if r <= 0:
            return None
        tp1 = entry - r
        tp2 = entry - 2 * r
        reason = f"bearish engulfing | strong body x{MIN_ENGULF_BODY_RATIO}"
    else:
        direction = "LONG"
        stop = cur_l * (1 - CRYPTO_STOP_BUFFER)
        r = entry - stop
        if r <= 0:
            return None
        tp1 = entry + r
        tp2 = entry + 2 * r
        reason = f"bullish engulfing | strong body x{MIN_ENGULF_BODY_RATIO}"

    return Signal(
        symbol=symbol,
        market="bingx_swap",
        candle_open_time_utc=cur_t.isoformat(),
        candle_close_time_utc=cur_ct.isoformat(),
        direction=direction,
        entry=entry,
        stop=stop,
        tp1=tp1,
        tp2=tp2,
        r=abs(r),
        reason=reason,
    )
# =========================================================
# Plot (optional)
# =========================================================
def plot(df45_closed: pd.DataFrame, sig: Signal, bars: int = 140):
    d = df45_closed.tail(bars).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title(f"{sig.symbol} 45m | {sig.direction} | {sig.reason} | close={sig.candle_close_time_utc}")
    ax.set_xlabel("Bars")
    ax.set_ylabel("Price")

    for i, row in d.iterrows():
        o,h,l,c = row["open"], row["high"], row["low"], row["close"]
        ax.plot([i,i], [l,h], linewidth=1)
        bottom=min(o,c); height=abs(c-o) if abs(c-o)>0 else 1e-9
        ax.add_patch(plt.Rectangle((i-0.3, bottom), 0.6, height))

    ax.axhline(sig.entry, linestyle="--", linewidth=1)
    ax.axhline(sig.stop,  linestyle="--", linewidth=1)
    ax.axhline(sig.tp1,   linestyle="--", linewidth=1)
    ax.axhline(sig.tp2,   linestyle="--", linewidth=1)

    ax.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.show()

# =========================================================
# Scan loop
# =========================================================
def scan_once(state: dict):
    any_sig = False

    for sym, bingx_symbol in BINGX_SWAP_SYMBOLS.items():
        try:
            df15 = fetch_bingx_swap_klines(bingx_symbol, interval=SOURCE_INTERVAL, limit=LIMIT_15M)
            df45_all = resample_to_45m(df15)
            df45_closed = drop_unclosed_45m(df45_all)

            sig = compute_signal_only_if_last2_engulf(df45_closed, sym)

            if sig:
                any_sig = True
                # ✅ console 只印紅框那坨
                print(format_signal_block(sig))

                # ✅ TG：預設「只要有訊號就送」(方便驗證)
                if ENABLE_TG:
                    if SEND_TG_ONLY_IF_NEW:
                        if should_show(sym, sig.candle_close_time_utc, sig.direction, state):
                            tg_send(format_signal_text_for_tg(sig))
                    else:
                        tg_send(format_signal_text_for_tg(sig))

                # plot（預設關）
                if PLOT_ON_SIGNAL:
                    plot(df45_closed, sig, bars=PLOT_BARS)

        except Exception as e:
            # 只印一行錯誤，避免爆 LOG
            print(f"❌ scan error for {sym}: {e}")

    if (not any_sig) and SHOW_NO_SIGNAL_MSG:
        print(NO_SIGNAL_MSG_TEXT)

def run_every_45m():
    state = load_state()
    while True:
        scan_once(state)
        save_state(state)
        time.sleep(45 * 60)

#if __name__ == "__main__":
    # ✅ 開機先測試 TG，讓你立刻知道 token/chat_id/權限有沒有問題

  #  run_every_45m()
    
if __name__ == "__main__":
    state = load_state()
    scan_once(state)
    save_state(state)
