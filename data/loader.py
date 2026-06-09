import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
 
import streamlit as st
import json
import csv
import base64
import os
import subprocess
import paramiko
from datetime import datetime
from collections import OrderedDict

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

def _get_last_deploy_date() -> str:
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        ts = subprocess.check_output(
            ["git", "log", "-1", "--format=%ci"],
            cwd=repo_dir,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        dt = datetime.fromisoformat(ts)
        return f"{dt.day}. {dt.strftime('%B').lower()} {dt.year}"
    except Exception:
        d = datetime.today()
        return f"{d.day}. {d.strftime('%B').lower()} {d.year}"

_DEPLOY_DATE = _get_last_deploy_date()
