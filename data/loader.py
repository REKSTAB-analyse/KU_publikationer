import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
 
import streamlit as st
import base64


# --- Logo (hentes lokalt) ---
@st.cache_data
def load_logo() -> bytes:
    logo_path = Path(__file__).parent.parent / "KU-logo.png"
    if logo_path.exists():
        return logo_path.read_bytes()
    return b""
 
 
def logo_base64() -> str:
    return base64.b64encode(load_logo()).decode()


# --- Midlertidig data ---
@st.cache_data
def load_publications() -> list[dict]:
    return []