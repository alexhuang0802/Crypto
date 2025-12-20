
import pandas as pd
from .legacy_scanner import run_for_streamlit

def run_scan() -> pd.DataFrame:
    """
    Streamlit 呼叫的唯一入口
    """
    return run_for_streamlit()
