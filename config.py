import streamlit as st

""" vent til data er sat korrekt op
# --- ERDA / SFTP ---
_ERDA = st.secrets["erda"]
DATA_PATH = _ERDA["data_path"]
"""

# --- Fakulteter ---
FAC_ORDER = ["SAMF", "SCIENCE", "TEO", "SUND", "HUM", "JUR"]

FAC_ABBRS = {
    "Det Teologiske Fakultet": "TEO",
    "Det Juridiske Fakultet": "JUR",
    "Det Humanistiske Fakultet": "HUM",
    "Det Natur- og Biovidenskabelige Fakultet": "SCIENCE",
    "Det Samfundsvidenskabelige Fakultet": "SAMF",
    "Det Sundhedsvidenskabelige Fakultet": "SUND"
}

# --- Stillingsgrupper ---
STILLINGSGRUPPER = [
    "Professor",
    "Lektor",
    "Adjunkt",
    "Postdoc",
    "Ph.d.",
    "Øvrige VIP (DVIP)",
    "Stillinger u. adjunktniveau",
    "Særlig stilling"
]

# --- FANER ---

TABS = [
    "Oversigt",
    "Output",
    "Publikationsformer",
    "Forskningsprofil",
    "Internationalt",
    "Sampublicering"
]

# --- Sampubliceringsapp URL ---
SAMPUBLICERING_URL = "https://ku-sampublicering.streamlit.app/"