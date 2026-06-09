import streamlit as st

from data.loader import load_logo, logo_base64, load_publications, _DEPLOY_DATE
from components.sidepanel import render_sidepanel
from config import TABS

import tabs.oversigt as tab_oversigt
import tabs.output as tab_output
import tabs.publikationsformer as tab_pubformer
import tabs.forskningsprofil as tab_forskningsprofil
import tabs.eksternt as tab_eksternt
import tabs.sampublicering as tab_sampublicering
import tabs.datagrundlag as tab_datagrundlag

def main():
    # --- Page config ---

    st.set_page_config(
        page_title="KU Publikationer",
        page_icon=load_logo(),
        layout="wide",
    )

    # --- Header: logo + titel ---
    col_logo, col_title = st.columns([1, 4])
    with col_logo:
        st.markdown(
            f'<img src="data:image/png;base64,{logo_base64()}" '
            f'style="max-width:180px; width:100%;">',
            unsafe_allow_html=True
        )
    
    with col_title:
        st.title("Publikationer på Københavns Universitet")
    
    # --- Data ---
    publications = load_publications()

    # --- Sidepanel med aktive filtre ---
    filters = render_sidepanel()

    # --- Faner ---
    tabs = st.tabs(TABS)
    tabs_dict = dict(zip(TABS, tabs))

    with tabs_dict["Oversigt"]:
        tab_oversigt.render(publications, filters)
    
    with tabs_dict["Output"]:
        tab_output.render(publications, filters)
    
    with tabs_dict["Publikationsformer"]:
        tab_pubformer.render(publications, filters)
 
    with tabs_dict["Forskningsprofil"]:
        tab_forskningsprofil.render(publications, filters)
 
    with tabs_dict["Eksternt samarbejde"]:
        tab_eksternt.render(publications, filters)
 
    with tabs_dict["Sampublicering"]:
        tab_sampublicering.render(publications, filters)
    
    with tabs_dict["Datagrundlag"]:
        tab_datagrundlag.render(publications, filters)
    
    # Footer
    st.markdown(f"""
<hr style="margin-top: 50px;">
<div style="text-align:center; color:#666; font-size: 0.9em;">
  REKSTAB Analyse · Amanda Schramm Petersen · <a href="mailto:ascp@adm.ku.dk">ascp@adm.ku.dk</a>
  · opdateret {_DEPLOY_DATE}
</div>
""", unsafe_allow_html=True)

if __name__ == "__main__":
    main()