import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from config import FAC_ORDER, STILLINGSGRUPPER

def render_sidepanel() -> dict:
    """ Viser sdepanel og returnerer aktive filtre som dict"""

    filters = {}

    with st.sidebar:
        st.header("Filtre")

        # Fakultet
        st.subheader("Organisation")
        valgte_fak = st.multiselect(
            "Fakultet (tom=alle)",
            options=FAC_ORDER,
            default=[],
            key="sp_fakultet",
        )
        filters["fakultet"] = valgte_fak or FAC_ORDER

        # Stillingsgruppe
        valgte_still = st.multiselect(
            "Stillingsgruppe (tom=alle)",
            options=STILLINGSGRUPPER,
            default=[],
            key="sp_stillingsgrupper",
        )
        filters["stillingsgrupper"] = valgte_still or STILLINGSGRUPPER

        # Køn
        st.subheader("Diversitet")
        valgte_køn = st.multiselect(
            "Køn (tom=begge)",
            options=["Kvinder", "Mænd"],
            default=[],
            key="sp_køn"
        )
        filters["køn"] = valgte_køn or ["Kvinder", "Mænd"]

    return filters

