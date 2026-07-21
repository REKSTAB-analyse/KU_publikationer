from tracemalloc import Snapshot
import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).parent.parent))
 
import streamlit as st
from data.loader import get_cursor
from components.charts import fig_hbar_stacked, PLOTLY_CONFIG, domain_shaded_colors, _DOMAIN_COLORS
from components.export import render_table_export
from components.colors import ku_color_sequence
from config import hier_cols, breakdown_label, doi_filter_sql, year_range_label, author_count_filter, show_ku_samlet


ANDET_LABEL = "Andet"

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _apply_top_x(data, top_x, always_keep=None):
    totals = {}
    for cats in data.values():
        for k, n in cats.items():
            totals[k] = totals.get(k, 0) + n
    always_keep = [k for k in (always_keep or []) if k in totals]

    if len(totals) <= top_x:
        return data, None, None

    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    keep = [k for k, _ in ranked[:top_x]]
    for k in always_keep:
        if k not in keep:
            keep.append(k)
    keep = sorted(keep, key=lambda k: -totals[k])
    keep_set = set(keep)

    out = {}
    for unit, cats in data.items():
        newc = {}
        for k, n in cats.items():
            key = k if k in keep_set else ANDET_LABEL
            newc[key] = newc.get(key, 0) + n
        out[unit] = newc

    return out, keep + [ANDET_LABEL], None

def _count_categories(filters, category_sql, extra_filter_sql="1=1", extra_filter_params=()):
    """Tæller distinkte kategorier i den aktuelle kontekst - bruges som max_value
    til Top-X-feltet, så det aldrig tilbyder flere end der reelt findes."""
    data, _ = _query_topic_section(filters, category_sql, extra_filter_sql, extra_filter_params)
    cats = {c for cats in data.values() for c in cats}
    return len(cats) or 1

@st.cache_data
def _query_topic_section(filters, category_sql, extra_filter_sql="1=1", extra_filter_params=()):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(filters.get("mode", "F"))
    n_dims = len(dims)
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    if not dims:
        select_dims, group_by, order_by_sql = "", "1", "1"
    else:
        select_dims = ", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", "
        group_by = ", ".join(str(i) for i in range(1, n_dims + 2))
        order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1))
    
    sql = f"""
        SELECT {select_dims}({category_sql}) AS cat,
               COUNT(DISTINCT PURE_ID) AS n
        FROM pubs
        WHERE Intern       = 'Intern'
          AND Fak          IN ({ph(filters['fakultet'])})
          AND Inst         IN ({ph(filters['institutter'])})
          AND Stil         IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year        BETWEEN ? AND ?
          AND ({ac_sql})
          AND ({extra_filter_sql})
        GROUP BY {group_by}
        ORDER BY {order_by_sql}
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params + list(extra_filter_params)
    )
    rows = get_cursor().execute(sql, params).fetchall()

    result, cluster_map = {}, {}
    for row in rows:
        dim_values = row[:n_dims]
        cat = row[n_dims]
        n = row[n_dims + 1]
        dim_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        clusters = tuple(dim_values[:-1]) if n_dims > 1 else None
        if dim_label not in result:
            result[dim_label] = {}
            cluster_map[dim_label] = clusters
        result[dim_label][cat] = result[dim_label].get(cat, 0) + n
    
    if filters.get("mode", "F") == "F" and show_ku_samlet(filters):
        ku_total = {}
        for dim_data in result.values():
            for cat, n in dim_data.items():
                ku_total[cat] = ku_total.get(cat, 0) + n
        result = {"KU samlet": ku_total, **result}
    
    return result, cluster_map

@st.cache_data
def _query_dim_domain_map(filters, dim_col, extra_filter_sql="1=1", extra_filter_params=()):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    sql = f"""
        SELECT DISTINCT COALESCE({dim_col}, 'Ukendt') AS cat, COALESCE(Domain, 'Ukendt') AS dom
        FROM pubs
        WHERE Intern       = 'Intern'
          AND Fak          IN ({ph(filters['fakultet'])})
          AND Inst         IN ({ph(filters['institutter'])})
          AND Stil         IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year        BETWEEN ? AND ?
          AND ({ac_sql})
          AND ({extra_filter_sql})
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params + list(extra_filter_params)
    )
    rows = get_cursor().execute(sql, params).fetchall()
    return {cat: dom for cat, dom in rows}

def _detect_fresh_click(widget_key: str) -> int | None:
    """
    Returnerer curve_number, HVIS widgettens gemte valg er nyt siden sidste
    kørsel (dvs. brugeren klikkede på DENNE specifikke widget lige nu) -
    ellers None. Bruges til at afgøre, hvilken af to faner (Antal/Andel) der
    senest blev klikket, når begge kan udløse samme niveaus drilldown.
    """
    state = st.session_state.get(widget_key)
    points = (state or {}).get("selection", {}).get("points", [])
    current_sig = points[0].get("curve_number") if points else None

    snapshot_key = f"_click_snapshot_{widget_key}"
    last_sig = st.session_state.get(snapshot_key)
    st.session_state[snapshot_key] = current_sig

    if current_sig is not None and current_sig != last_sig:
        return current_sig
    return None

_LEVEL_CHILDREN = {
    "domain": ["field"],
    "field": ["subfield"],
    "subfield": ["topic"],
}
_LEVEL_WIDGET_SUFFIXES = {
    "field": ["field_antal", "field_pct"],
    "subfield": ["subfield_antal", "subfield_pct"],
    "topic": ["topic_antal", "topic_pct"],
}

def _clear_descendants(level_key: str) -> None:
    """
    Rydder gemte klik-valg for alle niveauer UNDER det angivne niveau, når
    det selv skifter - ellers kan et forældet valg (fx et feltnavn fra det
    forrige domæne) overleve og ende med at matche INGEN søjler i den nye
    kontekst, hvilket dæmper samtlige søjler i stedet for at markere den
    korrekte.
    """
    for child in _LEVEL_CHILDREN.get(level_key, []):
        st.session_state.pop(f"_resolved_{child}", None)
        for suffix in _LEVEL_WIDGET_SUFFIXES.get(child, []):
            widget_key = f"topic_chart_{suffix}"
            st.session_state.pop(widget_key, None)
            st.session_state.pop(f"_click_snapshot_{widget_key}", None)
        _clear_descendants(child)

def _render_topic_section(filters, dim_col, category_sql, title_prefix, chart_mode="antal", top_x=None,
                           clickable=False, key_suffix="", level_key="", extra_filter_sql="1=1", extra_filter_params=()):
    data, cluster_map = _query_topic_section(filters, category_sql, extra_filter_sql, extra_filter_params)
    if not any(data.values()):
        st.error("Ingen publikationer matcher de valgte filtre.")
        return None

    org_data, org_cluster_map = _query_topic_section(filters, "'Alle'")
    for unit in org_data:
        data.setdefault(unit, {})
        cluster_map.setdefault(unit, org_cluster_map.get(unit))
    ordered_units = [u for u in org_data if u in data] + [u for u in data if u not in org_data]
    data = {u: data[u] for u in ordered_units}
    cluster_map = {u: cluster_map[u] for u in ordered_units}

    full_data = data  # ureduceret - bruges til eksport, uanset Top-X

    totals = {}
    for cats in data.values():
        for k, n in cats.items():
            totals[k] = totals.get(k, 0) + n

    order = None
    if top_x:
        data, order, _ = _apply_top_x(data, top_x, always_keep=["Ukendt"])
    if order is None:
        order = sorted(totals, key=lambda k: -totals[k])
    
    # --- Farver ---
    if dim_col == "Domain":
        colors = {k: _DOMAIN_COLORS.get(k, "#666666") for k in order}
    else:
        dim_domain_map = _query_dim_domain_map(filters, dim_col, extra_filter_sql, extra_filter_params)
        real_keys = [k for k in order if k != ANDET_LABEL]
        colors = domain_shaded_colors(real_keys, dim_domain_map, totals)
        if ANDET_LABEL in order:
            colors[ANDET_LABEL] = "#cccccc"
    
    y_labels = list(data.keys())
    group_keys = None
    if any(v is not None for v in cluster_map.values()):
        group_keys = ["__ku__" if lbl == "KU samlet" else cluster_map.get(lbl, "__single__") for lbl in y_labels]
    
    mode = filters.get("mode", "F")
    fig = fig_hbar_stacked(
        data=data, order=order, colors=colors,
        title=f"{title_prefix}, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal publikationer", mode=chart_mode,
        group_keys=group_keys, legend_position="right",
    )

    prev_state = st.session_state.get(f"topic_chart_{key_suffix}") if clickable else None

    if clickable:
        widget_key = f"topic_chart_{key_suffix}"

        if level_key:
            resolved = st.session_state.get(f"_resolved_{level_key}")
            if resolved:
                for trace in fig.data:
                    trace.marker.opacity = 1.0 if trace.name == resolved else 0.25

        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, on_select="rerun", key=widget_key)
    else:
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    render_table_export(
        data=full_data, row_label="Enhed",
        filename=f"{_slugify(title_prefix)}_{chart_mode}.xlsx",
        sheet_name=title_prefix[:31],
        key=f"export_forskningsprofil_{_slugify(title_prefix)}_{chart_mode}_{key_suffix}",
    )

    if not clickable:
        return None

    fresh_curve = _detect_fresh_click(widget_key)
    if fresh_curve is not None and fresh_curve < len(fig.data):
        clicked_name = fig.data[fresh_curve].name
        if level_key and st.session_state.get(f"_resolved_{level_key}") != clicked_name:
            st.session_state[f"_resolved_{level_key}"] = clicked_name
            _clear_descendants(level_key)
            st.rerun()
        return clicked_name

    if level_key:
        return st.session_state.get(f"_resolved_{level_key}")
    return None

def render(filters):
    st.markdown(
"""
### Forskningsprofil

Fanen kortlægger KU's faglige profil på baggrund af publikationernes emneområder, baseret på OpenAlex' 
eller SciVals emneklassifikation - CURIS indeholder ikke selv en (XX pålidelig - spørg Svend, om hvordan klassifikation sker) emneklassifikation af 
publikationer. 
""")

    data_source = filters.get("data_source", "CURIS")

    if data_source == "CURIS":
        st.error("CURIS indeholder ikke en emneklassifikation af publikationer. "
        " Vælg OpenAlex eller SciVal som datakilde i sidepanelet for at se fanens indhold.")
        return 
    
    if data_source == "OpenAlex":
        st.markdown(
"""
Domæne-figuren nedenfor viser den bredeste inddeling; klik på en søjle for at zoome ind på dens felter, 
og videre ned gennem underfelter til specifikke emner. Hvert niveau kan brydes ned på de organisatoriske 
niveauer, du har valgt i sidepanelet - f.eks. to fakulteter samtidig, så du direkte kan sammenligne
deres faglige profil. 
""")
        with st.expander("Sådan klassificerer OpenAlex emneområder"):
            st.markdown(
"""
**Hierarki**

OpenAlex placerer hver publikation i et firelaget hierarki, fra bredest 
til mest specifikt: **domæne → felt → underfelt → emne**. ([OpenAlex' dokumentation](https://help.openalex.org/hc/en-us/articles/24736129405719-Topics))

- **Domæner (4)**: de bredeste videnskabsområder, *Life Sciences*, 
*Physical Sciences*, *Social Sciences* og *Health Sciences*
- **Felter (26)**: fagområder inden for hvert domæne
- **Underfelter (254)**: mere specifikke faggrene inden for hvert felt
- **Emner (4500)**: de mest specifikke kategorier, tildelt automatisk ud fra 
publikationens titel, abstract og citationsmønstre

Hvert emne hører entydigt til ét underfelt, ét felt og ét domæne, så hierarkiet
er altid strengt uden overlap. En publikation kan få tildelt flere topics med hver
sin score; det højest scorende bliver publikationens primære emne. 

**Eksempel**: emnet *International Maritime Law Issues* hører under underfeltet
*Management, Monitoring, Policy, and Law*, feltet *Environmental Science* og 
domænet *Physical Sciences*. ([CNRS' OpenAlex-brugerguide](https://www.science-ouverte.cnrs.fr/wp-content/uploads/2026/02/20260209_OpenAlex_Discovery-User-Guide_CNRS_2026.pdf))

Hele taksonomien - alle domæner, felter, underfelter og emner, med tilhørende nøgleord, en kort
beskrivelse og et Wikipedia-link per emne - kan slås op i 
[OpenAlex' fulde emne-opslagstabel](https://docs.google.com/spreadsheets/d/1v-MAq64x4YjhO7RWcB-yrKV5D_2vOOsxl4u6GBKEXY8/edit?gid=983250122#gid=983250122).

**Sådan bygges og tildeles emnerne**

Selve emnetaksonomien (de 4500 kategorier) er bygget ud fra 71 millioner
OpenAlex-publikationer udgivet 2000-2023, forbundet af 1.7 milliarder citationslinks. 
Klyngedannelsen bygger udelukkende på disse citationsforbindelser - ikke på 
abstracts eller en sprogmodel. Først bagefter fik hver klynge et navn ved
brug af en sprogmodel, som kun så titlerne på de 250 mest citerede publikationer
i hver klynge. ([Analyse af navngivningstrinnet](https://arxiv.org/pdf/2510.14303))

Publikationernes abstract kommer først i spil i det næste trin: når en konkret
publikation skal have tildelt sit emne, bruger en trænet klassifikationsmodel titel, 
abstract og citationer som input - så selv publikationer
uden citationer kan klassificeres. ([Analyse af klassifikationsmodellen](https://arxiv.org/pdf/2408.04163))
"""
            )

        _TOPX_DEFAULT = 10

        # --- Domæne ---
        _tab_dom_n, _tab_dom_p = st.tabs(["Antal", "Andel (%)"])
        with _tab_dom_n:
            _render_topic_section(
                filters, "Domain", "COALESCE(Domain, 'Ukendt')", "Domæne",
                chart_mode="antal", clickable=True, key_suffix="domain_antal", level_key="domain",
            )
        with _tab_dom_p:
            _render_topic_section(
                filters, "Domain", "COALESCE(Domain, 'Ukendt')", "Domæne",
                chart_mode="pct", clickable=True, key_suffix="domain_pct", level_key="domain",
            )
        _clicked_domain = st.session_state.get("_resolved_domain")
    
        if not _clicked_domain:
            st.caption("Klik på et domæne i figuren ovenfor for at se dets felter.")
        else:
            st.markdown(f"---\n##### Felter under *{_clicked_domain}*")
            _field_extra_sql = "Domain = ?"
            _field_extra_params = (_clicked_domain,)

            _tab_field_n, _tab_field_p = st.tabs(["Antal", "Andel (%)"])
            with _tab_field_n:
                _render_topic_section(
                    filters, "Field", "COALESCE(Field, 'Ukendt')", f"Felt under {_clicked_domain}",
                    chart_mode="antal", clickable=True, key_suffix="field_antal", level_key="field",
                    extra_filter_sql=_field_extra_sql, extra_filter_params=_field_extra_params,
                )
            with _tab_field_p:
                _render_topic_section(
                    filters, "Field", "COALESCE(Field, 'Ukendt')", f"Felt under {_clicked_domain}",
                    chart_mode="pct", clickable=True, key_suffix="field_pct", level_key="field",
                    extra_filter_sql=_field_extra_sql, extra_filter_params=_field_extra_params,
                )
            _clicked_field = st.session_state.get("_resolved_field")

            if not _clicked_field:
                st.caption("Klik på et felt i figuren ovenfor for at se dets underfelter.")
            else:
                st.markdown(f"---\n##### Underfelter under *{_clicked_field}*")
                _subfield_extra_sql = "Domain = ? AND Field = ?"
                _subfield_extra_params = (_clicked_domain, _clicked_field)

                _max_subfield = _count_categories(filters, "COALESCE(Subfield, 'Ukendt')", _subfield_extra_sql, _subfield_extra_params)
                _topx_subfield = st.number_input(
                    "Vis top-X underfelter (resten samles i 'Andet')",
                    min_value=1, max_value=_max_subfield, value=min(10, _max_subfield), step=1, key="topx_subfield",
                )

                _tab_sub_n, _tab_sub_p = st.tabs(["Antal", "Andel (%)"])
                with _tab_sub_n:
                    _clicked_subfield = _render_topic_section(
                        filters, "Subfield", "COALESCE(Subfield, 'Ukendt')", f"Underfelt under {_clicked_field}",
                        chart_mode="antal", top_x=_topx_subfield, clickable=True, key_suffix="subfield_antal", level_key="subfield",
                        extra_filter_sql=_subfield_extra_sql, extra_filter_params=_subfield_extra_params,
                    )
                with _tab_sub_p:
                    _render_topic_section(
                        filters, "Subfield", "COALESCE(Subfield, 'Ukendt')", f"Underfelt under {_clicked_field}",
                        chart_mode="pct", top_x=_topx_subfield, clickable=True, key_suffix="subfield_pct", level_key="subfield",
                        extra_filter_sql=_subfield_extra_sql, extra_filter_params=_subfield_extra_params,
                    )
                _clicked_subfield = st.session_state.get("_resolved_subfield")

                if not _clicked_subfield:
                    st.caption("Klik på et underfelt i figuren ovenfor for at se dets emner.")
                else:
                    st.markdown(f"---\n##### Emner under *{_clicked_subfield}*")
                    _topic_extra_sql = "Domain = ? AND Field = ? AND Subfield = ?"
                    _topic_extra_params = (_clicked_domain, _clicked_field, _clicked_subfield)

                    _max_topic = _count_categories(filters, "COALESCE(Topic, 'Ukendt')", _topic_extra_sql, _topic_extra_params)
                    _topx_topic = st.number_input(
                        "Vis top-X emner (resten samles i 'Andet')",
                        min_value=1, max_value=_max_topic, value=min(10, _max_topic), step=1, key="topx_topic",
                    )

                    _tab_topic_n, _tab_topic_p = st.tabs(["Antal", "Andel (%)"])
                    with _tab_topic_n:
                        _render_topic_section(
                            filters, "Topic", "COALESCE(Topic, 'Ukendt')", f"Emne under {_clicked_subfield}",
                            chart_mode="antal", top_x=_topx_topic, key_suffix="topic_antal",
                            extra_filter_sql=_topic_extra_sql, extra_filter_params=_topic_extra_params,
                        )
                    with _tab_topic_p:
                        _render_topic_section(
                            filters, "Topic", "COALESCE(Topic, 'Ukendt')", f"Emne under {_clicked_subfield}",
                            chart_mode="pct", top_x=_topx_topic, key_suffix="topic_pct",
                            extra_filter_sql=_topic_extra_sql, extra_filter_params=_topic_extra_params,
                        )



    if data_source == "SciVal":
        with st.expander("Sådan klassificerer SciVal emneområder"):
            st.markdown(
"""
**Topics og Topic Clusters**

SciVal klynger publikationer efter deres indbyrdes citationsmønstre til et sæt 
af **Topics**. Klyngedannelsen bygger på citationsnetværket for Scopus-indhold
udgivet fra 1996 og frem. Omkring 95% af dette indhold har nok citationsdata til at
blive placeret i et Topic; resten mangler formentlig tilstrækkkelige referencer
til at kunne klynges. Det resulterer i omkring 94000 Topics. Når citationsforbindelserne
mellem flere topics er stærke nok, samles de i en bredere **Topic Cluster**; der er
cirka 1500 Topic Clusters. ([SciVal Topics | Elsevier](https://www.elsevier.com/products/scival/overview/topics))

Hver publikation hører til præcis ét Topic og dermed én Topic Cluster.
([SciVal Topics FAQ](https://service.elsevier.com/app/answers/detail/a_id/28428/supporthub/evolve/))

Når en ny publikation udkommer, bliver den tilføjet til et Topic ud fra sin egen
**referenceliste** - altså, hvilke andre publikationer den citerer - og ikke
ud fra titel eller abstract. Det gør Topics dynamiske - de fleste vokser
løbende, efterhånden som nye publikationer citerer ind i dem. 
([What are Topics? – Elsevier](https://service.elsevier.com/app/answers/detail/a_id/27947/supporthub/scopus/))

I maj 2024 lancerede Elsevier en opdateret metode ("next generation Topics"), der giver
en tættere sammenhæng mellem publikationer og deres Topic end den oprindelige model
fra 2016. 
([Next Generation SciVal Topics](https://service.elsevier.com/app/answers/detail/a_id/37167/supporthub/evolve/))

**Prominence**

Topics rangeres efter **Prominence**: et mål for et emnes aktuelle momentum, 
sammensat af citationstal, Scopus-visninger og gennemsnitlig CiteScore for de 
seneste to år. Prominence er bevidst ikke et kvalitets- eller vigtighedsmål, 
kun et udtryk for, hvor meget opmærksomhed et emne får lige nu.
([SciVal Metrics and Indicators](https://elsevier.libguides.com/c.php?g=1328583&p=9781971))

**Alternativ: ASJC-klassifikation**

Som et alternativ til Topic/Topic Clusters kan fordelingen også vises efter
tidsskrifternes emneklassifikation: Scopus' All Science Journal Classification
(ASJC). Det er et hierarki - fire brede fagområder (*Life Science*, 
*Physical Science*, *Health Science* og *Social Sciences and Humanities*), opdelt i 27 hovedfelter og
videre ud i 334 kategorier - som Elsevier-eksperter manuelt tildeler det enkelte
tidsskrift ud fra dets formål og indhold, når det optaget i Scopus. 
([Scopus subject area categories and ASJC codes](https://service.elsevier.com/app/answers/detail/a_id/12007/supporthub/scopus/))

Den afgørende forskel til Topics: ASJC klassificerer hele tidsskriftet, ikke den 
enkelte artikle. Alle artikler i samme tidsskrift får dermed samme ASJC-kode(r), 
uanset hvad den konkrete artikel faktisk handler om - modsat Topics, der er 
publikationsspecifikke og opdateres dynamisk ud fra artiklens egne referencer. 
Et tidsskrift kan desuden have flere ASJC-koder, hvis det dækker flere
fagområder. 
([SciVal LibGuide](https://elsevier.libguides.com/c.php?g=1328583&p=9781974))
"""
            )



