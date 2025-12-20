# scanner/http.py
import time
import requests

BASE_CANDIDATES_DEFAULT = [
    "https://data-api.binance.vision",
    "https://fapi.binance.com",
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (scanner/1.0)",
    "Accept": "application/json",
})


class BinanceHTTPError(RuntimeError):
    def __init__(self, status_code: int, url: str, body_snippet: str = ""):
        super().__init__(f"HTTP {status_code} for {url} | {body_snippet}")
        self.status_code = status_code
        self.url = url
        self.body_snippet = body_snippet


def request_json(
    path: str,
    params=None,
    timeout: int = 10,
    base_candidates=None,
    max_retries: int = 3,
    backoff_sec: float = 1.0,
):
    """
    依序嘗試多個 base；遇到 429/403/451/418/5xx 做退避重試。
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

                # 這些狀態常見於風控/限流/維護：先退避重試
                if r.status_code in (429, 403, 451, 418, 500, 502, 503, 504):
                    sleep_s = backoff_sec * (attempt + 1)
                    time.sleep(sleep_s)
                    # 最後一次仍失敗就丟出自訂錯誤
                    if attempt == max_retries:
                        snippet = (r.text or "")[:200]
                        raise BinanceHTTPError(r.status_code, url, snippet)
                    continue

                # 其他非 200：直接丟出
                if not (200 <= r.status_code < 300):
                    snippet = (r.text or "")[:200]
                    raise BinanceHTTPError(r.status_code, url, snippet)

                return r.json(), base

            except BinanceHTTPError as e:
                last_err = e
            except Exception as e:
                last_err = e
                # 網路波動也退避一下
                if attempt < max_retries:
                    time.sleep(backoff_sec * (attempt + 1))

        # 換下一個 base

    raise last_err if last_err else RuntimeError("Unknown error")
