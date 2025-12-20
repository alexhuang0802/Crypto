
import pandas as pd
from scanner.legacy_scanner import run_for_streamlit_tables

def run_scan():
    """
    給 app.py 呼叫：回傳四個表格 + meta/error
    """
    return run_for_streamlit_tables()
