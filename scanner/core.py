from .legacy_scanner import run_for_streamlit

def run_scan():
    return run_for_streamlit()
# --- 相容別名，避免 core.py import 失敗 ---
def run_for_streamlit_tables():
    return run_for_streamlit()
