import streamlit as st
import psutil, os

from data.loader import load_logo, logo_base64, _DEPLOY_DATE, load_org_volume
from data.loader import load_filter_options, set_active_data_source
from data.loader import _sync_parquet_from_erda
from components.sidepanel import render_sidepanel
from components.charts import fig_org_treemap, PLOTLY_CONFIG
from components.colors import build_faculty_colors, stillingsgruppe_colors
from config import TABS, hier_cols, FAC_ORDER, FAC_FULL, ERDA_ENABLED

import tabs.oversigt as tab_oversigt
import tabs.publikationsformer as tab_pubformer
import tabs.citationsimpact as tab_citationsimpact
import tabs.forskningsprofil as tab_forskningsprofil
import tabs.eksternt as tab_eksternt
import tabs.sampublicering as tab_sampublicering
import tabs.datagrundlag as tab_datagrundlag
import tabs.forfatterprofil as tab_forfatterprofil
from tabs import diversitet as tab_diversitet

def main():
    # --- Page config ---
    st.set_page_config(
        page_title="KU Publikationer",
        page_icon=load_logo(),
        layout="wide",
    )

    # --- Skriftstørrelse i widgets (undtagen sidepanelet) ---
    st.markdown(
        """
        <style>
        [data-testid="stWidgetLabel"] p {
            font-size: 1rem !important;
            font-weight: 600 !important;
        }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
            font-size: unset !important;
            font-weight: unset !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # --- Synkroniser data fra ERDA, før noget forsøger at læse dem ---
    if ERDA_ENABLED:
        _sync_parquet_from_erda()

    _mem_mb = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    print(f"[DEBUG] Hukommelse efter ERDA-sync: {_mem_mb:.0f} MB", flush=True)

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
    
    # --- Sidepanel med aktive filtre ---
    filters = render_sidepanel()
    set_active_data_source(filters.get("data_source", "CURIS"))

    def _faculty_legend_html(faculty_colors: dict) -> str:
        items = "".join(
            f'<span style="display:inline-flex; align-items:center; gap:5px; margin:2px 12px 2px 0;">'
            f'<span style="width:11px; height:11px; border-radius:2px; '
            f'background:{faculty_colors.get(fak, "#666666")}; flex-shrink:0;"></span>'
            f'<span style="font-size:0.85rem;">{FAC_FULL.get(fak, fak)} ({fak})</span>'
            f'</span>'
            for fak in FAC_ORDER
        )
        return (
            '<div style="font-weight:600; margin-top:8px; margin-bottom:4px;">Fakultetsfarver</div>'
            f'<div style="display:flex; flex-wrap:wrap;">{items}</div>'
        )

    with st.expander("Sådan læser du figuren"):
        st.markdown(
"""
Hver boks' **størrelse** viser antal publikationer - jo større boks, jo flere publikationer.
**Farven** markerer fakultet: institutboksenes lysere/mørkere nuancer inden for samme fakultet 
er udelukkende en visuel adskillelse og har ingen selvstændig betydning. 

Hold musen over hver boks for at se de præcise tal.
"""
        )
        st.markdown(_faculty_legend_html(build_faculty_colors()), unsafe_allow_html=True)

    #"""
    _mode = filters.get("mode", "F")

    # Tilføj Stillingsgruppe som ekstra treemap-niveau, hvis specifikke
    # fakulteter eller institutter er eksplicit valgt - kun til selve
    # treemap'et, IKKE til filters["mode"] selv (som resten af appens faner
    # også læser, og som ikke skal påvirkes af denne ændring).
    _treemap_mode = _mode
    if "I" in _mode:
        # Institut-niveauet er slået til (enten "I" eller "FI") - Stillingsgruppe
        # vises kun, hvis et SPECIFIKT institut er valgt, uanset om fakultet også er det.
        _show_stil_in_treemap = filters.get("institutter_explicit", False)
    else:
        # Kun fakultet-niveauet er slået til ("F") - Stillingsgruppe vises,
        # så snart et specifikt fakultet er valgt.
        _show_stil_in_treemap = filters.get("fakultet_explicit", False)

    if _show_stil_in_treemap and "G" not in _treemap_mode:
        _treemap_mode += "G"

    _dims = hier_cols(_treemap_mode)
    _org_rows = load_org_volume(filters, _treemap_mode)
    if _org_rows:
        _any_unit_selected = (
            filters.get("fakultet_explicit", False)
            or filters.get("institutter_explicit", False)
            or filters.get("stillingsgrupper_explicit", False)
        )
        fig = fig_org_treemap(
            _org_rows, _dims, build_faculty_colors(), stillingsgruppe_colors(),
            height=500, show_pct=not _any_unit_selected,
        )
        if fig is not None:
            st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    _mem_mb2 = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    print(f"[DEBUG] Hukommelse efter treemap: {_mem_mb2:.0f} MB", flush=True)
    #"""
    
    # --- Faner ---
    tab_labels = [t for t in TABS]
    tabs = st.tabs(tab_labels)
    tabs_dict = dict(zip(tab_labels, tabs))


    with tabs_dict["Oversigt"]:
        tab_oversigt.render(filters)
    
    with tabs_dict["Publikationsformer"]:
        tab_pubformer.render(filters)
 
    with tabs_dict["Forskningsprofil"]:
        tab_forskningsprofil.render(filters)
    
    with tabs_dict["Citationsimpact"]:
        tab_citationsimpact.render(filters)
 
    with tabs_dict["Eksternt samarbejde"]:
        tab_eksternt.render(filters)
 
    with tabs_dict["Sampublicering"]:
        tab_sampublicering.render(filters)
    
    with tabs_dict["Datagrundlag"]:
        tab_datagrundlag.render(filters)
    
    with tabs_dict["Forfatterprofil"]:
        tab_forfatterprofil.render(filters)

    with tabs_dict["Diversitet"]:
        tab_diversitet.render(filters)
    
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