import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
 
import streamlit as st
 
 
def render(publications, filters):
    st.error("Indhold kommer her.")