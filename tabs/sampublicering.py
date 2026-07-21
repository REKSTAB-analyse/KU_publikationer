import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
 
import streamlit as st
from config import SAMPUBLICERING_URL

def render(filters: dict) -> None:
    st.subheader("Sampublicering")

    st.markdown(
"""
Her vises nøgletal om sampublicering på tværs af KU. For en dybdegående netværksanalyse, gå til
sampubliceringsappen.
""")

    st.markdown(f"[Åbn sampubliceringsappen]({SAMPUBLICERING_URL})")