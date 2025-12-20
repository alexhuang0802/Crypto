# scanner/http.py
import time
import requests

BASE_CANDIDATES_DEFAULT = [
    "https://data-api.binance.vision",  # 通常較不容易被擋
    "https://fapi.binance.com",         # 官方
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (scanner/1.0)",
    "Accept": "application/json",
})

def request_json(
    path: str,
    params=None,
    timeout: int = 10,
    base_candidates=None,
    max_retries: int = 2,
    backoff_sec: float = 0.8,
):
    """
    依序嘗試多個 base；遇到 429/5xx 做簡單退避重試。
    回傳: (json_data, used_base)
    """
    if base_candidates is None:
        base_candidates = BASE_CANDIDATES_DEFAULT

    last_err = None

    for base in base_candidates:
        url = f"{base}{path}"

        for attempt in range(max_retries + 1):
            try:
                r = SESSION.get(url, params=params, timeout=timeout)

                # 429：退避重試
                if r.status_code == 429:
                    sleep_s = backoff_sec * (attempt + 1)
                    time.sleep(sleep_s)
                    continue

                r.raise_for_status()
                return r.json(), base

            except Exception as e:
                last_err = e
                # 5xx 或網路波動：退避一下再試
                if attempt < max_retries:
                    time.sleep(backoff_sec * (attempt + 1))
                else:
                    break

    raise last_err
