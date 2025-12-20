# scanner/core.py
from .legacy_scanner import run_for_streamlit_tables

def run_scan():
    """
    給 app.py 呼叫：回傳 dict，內含 4 個 DataFrame
    """
    return run_for_streamlit_tables()
