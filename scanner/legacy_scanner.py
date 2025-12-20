import time
import requests
from urllib.parse import urlparse

BASE_CANDIDATES = [
    "https://data-api.binance.vision",  # ✅ 先用雲端鏡像（通常不會 451）
    "https://fapi.binance.com",         # ✅ 官方（可能 451/403/429）
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (scanner/1.0)",
    "Accept": "application/json",
})

def _to_path(url_or_path: str) -> str:
    """
    支援：
    - '/fapi/v1/exchangeInfo'
    - 'https://fapi.binance.com/fapi/v1/exchangeInfo'
    會一律轉成 path：'/fapi/v1/exchangeInfo'
    """
    s = (url_or_path or "").strip()
    if s.startswith("http://") or s.startswith("https://"):
        p = urlparse(s)
        return p.path or "/"
    return s if s.startswith("/") else ("/" + s)

def _request_json(base: str, url_or_path: str, params=None, timeout=20):
    path = _to_path(url_or_path)
    url = f"{base}{path}"
    r = session.get(url, params=params, timeout=timeout)
    if r.status_code >= 400:
        text = (r.text or "")[:300]
        raise requests.HTTPError(
            f"HTTP {r.status_code} for {url} params={params} body={text}"
        )
    return r.json()

def get_json(url_or_path: str, params=None, timeout=20, retries=2, backoff=1.2):
    """
    會依序嘗試 BASE_CANDIDATES；
    每個 base 失敗會重試 retries 次；
    全部失敗才 raise。
    """
    last_err = None
    for base in BASE_CANDIDATES:
        for i in range(retries):
            try:
                return _request_json(base, url_or_path, params=params, timeout=timeout)
            except Exception as e:
                last_err = e
                time.sleep(backoff * (i + 1))
    raise last_err
