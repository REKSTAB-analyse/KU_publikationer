import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from config import FAC_ORDER, STILLINGSGRUPPER, doi_filter_sql
from data.loader import load_sprog_options, load_filter_options, load_max_author_count, load_institut_options

def render_sidepanel() -> dict:
    """ Viser sdepanel og returnerer aktive filtre som dict"""

    filters = {}

    with st.sidebar:
        st.header("Filtre og visning")
        st.caption(
"""
Brug filtrene nedenfor til at zoome in på et bestemt fakultet, karrieretrin, år, 
publikationstype eller tilføje en diversitetsdimension.
""")
        with st.expander("**Datakilde**"):
            data_source = st.radio(
                "Vælg datakilde",
                options = ["CURIS", "OpenAlex", "SciVal"],
                index = 1,
                key = "data_source_radio",
                help = "Vælg datakilden, som skal ligge til grund for analyserne"
            )
            filters["data_source"] = data_source
            opts = load_filter_options(data_source)

            year_min = 2000
            year_max = 2026 #max(opts["year"])
            aar_range = st.slider(
                "Vælg udgivelsesår",
                min_value=year_min,
                max_value=year_max,
                value=(year_min, year_max),
                key="sp_aar",
            )
            filters["aar_fra"] = aar_range[0]
            filters["aar_til"] = aar_range[1]
        
        with st.expander("**Organisation**"):
            show_fac = st.checkbox(
                "**Fakulteter**", 
                key="cb_fac", value=True,
            )
            show_inst = st.checkbox(
                "**Institutter**",
                key="cb_inst", value=False,
            )
            show_grp = st.checkbox(
                "**Stillingsgrupper**",
                key="cb_grp", value=True, disabled=True,
            )

            mode = ("F" if show_fac else "") + ("I" if show_inst else "")
            filters["mode"] = mode or "G"

            if show_fac:
                valgte_fak = st.multiselect(
                    "Vælg fakulteter (tom = alle)",
                    options=FAC_ORDER, default=[], key="sp_fakultet",
                )
                filters["fakultet"] = valgte_fak or FAC_ORDER
            else:
                filters["fakultet"] = FAC_ORDER
            
            if show_inst:
                institut_opts = load_institut_options(data_source, filters["fakultet"])
                valgte_inst = st.multiselect(
                "Vælg institut (tom = alle)",
                options=institut_opts, default=[], key="sp_institut",
                )
                filters["institutter"] = valgte_inst or institut_opts
            else:
                institut_opts = load_institut_options(data_source, filters["fakultet"])
                filters["institutter"] = institut_opts

            if show_grp:
                valgte_still = st.multiselect(
                    "Vælg stillingsgruppe (tom = alle)",
                    options=STILLINGSGRUPPER, default=[], key="sp_stillingsgrupper",
                )
                filters["stillingsgrupper"] = valgte_still or STILLINGSGRUPPER
            else:
                filters["stillingsgrupper"] = STILLINGSGRUPPER

        with st.expander("**Diversitet**"):
            valgte_køn = st.multiselect(
                "Køn (tom=begge)",
                options=["Kvinder", "Mænd"], default=[], key="sp_køn"
            )
            filters["køn"] = valgte_køn or ["Kvinder", "Mænd"]
        
        with st.expander("**Publikationstype og adgang**"):
            st.caption(
                "Filtrene begrænser, hvilke publikationer der indgår i analyserne."
                )

            valgte_typer = st.multiselect(
                "Publikationstype (tom = alle)",
                options=opts["typer"], default=[], key="sp_type",
            )
            filters["typer"] = valgte_typer or opts["typer"]

            valgte_indholds = st.multiselect(
                "Indholdstype (tom = alle)",
                options=opts["indholds"], default=[], key="sp_indholds",
            )
            filters["indholdstyper"] = valgte_indholds or opts["indholds"]

            sprog_opts = load_sprog_options(filters["aar_fra"], filters["aar_til"])
            valgte_sprog = st.multiselect(
                "Sprog (tom = alle)",
                options=sprog_opts, default=[], key="sp_sprog",
            )
            filters["sprog"] = valgte_sprog or sprog_opts

            valgte_peer = st.multiselect(
                "Peer review (tom = alle)",
                options=["Peer reviewed", "Ikke peer reviewed", "Ukendt"],
                default=[], key="sp_peer",
            )
            peer_map = {"Peer reviewed": "Ja", "Ikke peer reviewed": "Nej", "Ukendt": "Ukendt"}
            filters["peer"] = [peer_map[v] for v in valgte_peer] if valgte_peer else ["Ja", "Nej", "Ukendt"]

            valgte_oa = st.multiselect(
                "Open access (tom = alle)",
                options=opts["open_access"], default=[], key="sp_oa",
            )
            filters["open_access"] = valgte_oa or opts["open_access"] + [""]

            valgte_doi = st.multiselect(
                "Har DOI (tom = alle)",
                options=["Ja", "Nej"], default=[], key="sp_har_doi",
            )
            filters["har_doi"] = valgte_doi or ["Ja", "Nej"]
        
        with st.expander("**Forfatterantal**"):
            st.caption(
                "Filtrer publikationer efter det samlede antal forfattere (interne "
                "og eksterne tilsammen) - f.eks. for at udelukke solopublikationer "
                "eller meget store forfatterkonsortier."
                "\n\n**Tip**: anvend piletasterne til at finjustere spændet."
            )
            MIN_FORFATTERE = 1  # publikationer med 0 forfattere giver ikke mening i analyserne

            max_forf_i_data = load_max_author_count(data_source, filters)
            max_forf_i_data = max(max_forf_i_data, MIN_FORFATTERE)  # undgår negativ/tom range

            if max_forf_i_data <= MIN_FORFATTERE:
                st.caption(
                    f"Alle publikationer, der matcher de øvrige filtre, har præcis "
                    f"{max_forf_i_data} forfatter - intet filter at vælge her."
                )
                filters["min_forfattere"] = MIN_FORFATTERE
                filters["max_forfattere"] = max_forf_i_data
            else:
                forf_range = st.slider(
                    "Antal forfattere",
                    min_value=MIN_FORFATTERE, max_value=max_forf_i_data,
                    value=(MIN_FORFATTERE, max_forf_i_data),
                    key="sp_forf_range",
                )
                filters["min_forfattere"] = forf_range[0]
                filters["max_forfattere"] = forf_range[1]
    return filters
