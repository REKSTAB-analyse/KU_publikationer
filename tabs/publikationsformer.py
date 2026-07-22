import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from data.loader import get_cursor, load_author_counts
from components.charts import fig_hbar_stacked, PLOTLY_CONFIG, fig_year_trend
from components.export import render_table_export
from components.colors import ku_color_sequence
from config import hier_cols, breakdown_label, doi_filter_sql, year_range_label, author_count_filter, show_ku_samlet

# --- Konstanter per sektion ---
INDHOLD_ORDER = ["Forskning", "Formidling", "Undervisning", "Rådgivning"]
INDHOLD_COLORS = {
    "Forskning": "#901a1e",
    "Formidling": "#122947",
    "Undervisning": "#425570",
    "Rådgivning": "#bac7d9",
}
INDHOLD_LABELS = {
    "Forskning": "Forskning",
    "Formidling": "Formidling",
    "Undervisning": "Undervisning",
    "Rådgivning": "Rådgivning",
}

PEER_ORDER = ["Ja", "Nej", "Ukendt"]
PEER_COLORS = {
    "Ja": "#901a1e",
    "Nej": "#122947",
    "Ukendt": "#666666",
}
PEER_LABELS = {
    "Ja": "Peer reviewed",
    "Nej": "Ikke peer reviewed",
    "Ukendt": "Ukendt",
}

OA_ORDER = ["Open", "Closed", "Restricted", "Embargoed", "Unknown"]
OA_COLORS = {
    "Open": "#901a1e",
    "Closed": "#122947",
    "Restricted": "#425570",
    "Embargoed": "#bac7d9",
    "Unknown": "#666666",
}
OA_LABELS = {
    "Open": "Open Access",
    "Closed": "Lukket adgang",
    "Restricted": "Begrænset adgang",
    "Embargoed": "Embargo",
    "Unknown": "Ukendt",
}

DOI_ORDER = ["Ja", "Nej"]
DOI_COLORS = {"Ja": "#901a1e", "Nej": "#122947"}
DOI_LABELS = {"Ja": "Har DOI", "Nej": "Har ikke DOI"}

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

@st.cache_data
def _query_section(filters, mode, category_sql):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(mode)
    n_dims = len(dims)

    if not dims:
        select_dims = ""
        group_by = "1"
        order_by_sql = "1"
    else:
        select_dims = ", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", "
        group_by = ", ".join(str(i) for i in range(1, n_dims + 2))
        order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1))
    
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    where_sql = f"""
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year        BETWEEN ? AND ?
          AND ({ac_sql})
    """
    base_params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params
    )

    sql = f"""
        SELECT {select_dims}({category_sql}) AS cat,
               COUNT(DISTINCT PURE_ID) AS n
        FROM pubs
        {where_sql}
        GROUP BY {group_by}
        ORDER BY {order_by_sql}
    """
    rows = get_cursor().execute(sql, base_params).fetchall()

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
    
    if mode == "F" and show_ku_samlet(filters):
        ku_sql = f"""
            SELECT ({category_sql}) AS cat, COUNT(DISTINCT PURE_ID) AS n
            FROM pubs
            {where_sql}
            GROUP BY 1
        """
        ku_rows = get_cursor().execute(ku_sql, base_params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}
    
    if mode == "I":
        result = dict(sorted(result.items(), key=lambda kv: -sum(kv[1].values())))

    return result, cluster_map

@st.cache_data
def _query_trend(filters, category_sql):

    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT Year, ({category_sql}) AS cat, COUNT(DISTINCT PURE_ID) AS n
        FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year IS NOT NULL
          AND ({ac_sql})
        GROUP BY 1, 2
        ORDER BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()

    result = {}
    for year, cat, n in rows:
        result.setdefault(year, {})[cat] = n
    
    return result

def _render_trend_tab(filters, category_sql, title_prefix, order=None, colors=None, labels=None, top_x=None, always_keep=None):
    
    trend_data = _query_trend(filters, category_sql)
    if not trend_data:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return
    
    full_trend_data = trend_data

    if top_x:
        trend_data, _order, _colors = _apply_top_x(trend_data, top_x, always_keep=always_keep)
        if _order is not None:
            order, colors = _order, _colors

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True,
        key=f"trend_mode_{_slugify(title_prefix)}",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=order, colors=colors, labels=labels,
        title=f"{title_prefix} over tid (hele perioden)",
        mode=chart_mode,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    render_table_export(
        data={str(year): cats for year, cats in sorted(full_trend_data.items())},
        row_label="År",
        col_labels=labels,
        filename=f"{_slugify(title_prefix)}_udvikling_over_tid.xlsx",
        sheet_name=title_prefix[:31],
        key=f"export_trend_{_slugify(title_prefix)}",
    )



ANDET_LABEL = "Andet"

def _apply_top_x(data, top_x, always_keep=None):
    """behold de top_x-værdier (efter samlet antal) - resten samles i Andet"""
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
    palette = ku_color_sequence(len(keep))
    colors = {k: palette[i] for i, k in enumerate(keep)}
    colors[ANDET_LABEL] = "#cccccc"
    return out, keep + [ANDET_LABEL], colors

def _render_section(filters, mode, category_sql, title_prefix, order=None, colors=None, labels=None, chart_mode="antal", legend_position="right", top_x=None, always_keep=None):
    
    data, cluster_map = _query_section(filters, mode, category_sql)
    if not any(data.values()):
        st.error("Ingen publikationer matcher de valgte filtre.")
        return
    
    full_data = data

    if top_x:
        data, _order, _colors = _apply_top_x(data, top_x, always_keep=always_keep)
        if _order is not None:
            order = _order
            colors = _colors

    if chart_mode == "rate":
        author_counts = load_author_counts(filters, mode)
        data = {
            unit: {cat: n / author_counts.get(unit, 1) for cat, n in cats.items()}
            for unit, cats in data.items()
            if author_counts.get(unit, 0) > 0
        }
        full_data = {
            unit: {cat: n / author_counts.get(unit, 1) for cat, n in cats.items()}
            for unit, cats in full_data.items() 
            if author_counts.get(unit, 0) > 0
        }
        if not data:
            st.error("Ingen forfattere matcher de valgte filtre.")
            return

    y_labels = list(data.keys())

    if any(v is not None for v in cluster_map.values()):
        group_keys = [
            "__ku__" if lbl == "KU samlet"
            else cluster_map.get(lbl, "__single__")
            for lbl in y_labels
        ]
    else:
        group_keys = None
    
    fig = fig_hbar_stacked(
        data=data,
        order=order,
        colors=colors,
        labels=labels,
        title=f"{title_prefix}, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal publikationer",
        mode=chart_mode,
        group_keys=group_keys,
        legend_position=legend_position,
    )
    
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    
    render_table_export(
        data=full_data,
        row_label="Enhed",
        col_labels=labels,
        filename=f"{_slugify(title_prefix)}_{mode}_{chart_mode}.xlsx",
        sheet_name=title_prefix[:31],
        key=f"export_{_slugify(title_prefix)}_{mode}_{chart_mode}",
    )


def render(filters: dict):
    # UÆNDRET herfra og ned
    st.markdown(
"""
### Publikationsformer

Fanen kortlægger formen på KU's publikationer: fordelingen af publikations- og
indholdstyper, hvilke sprog der publiceres på, samt i hvilken grad outputtet er peer
reviewed, frit tilgængeligt og DOI-registreret.

Alle metrikker i fanen bygger på CURIS' egen registrering, uanset hvilken datakilde 
der er valgt i sidepanelet - et valg af OpenAlex eller SciVal ændrer kun, hvilken
delmængde af publikationer der indgår, ikke hvoer selve type-/sprog-/peer review-data
kommer fra. 

Hver figur kan ses på tre måder: 
- **Antal** viser det rå antal publikationer. 
- **Andel (%)** viser den procentvise fordeling inden for hver enhed. 
- **Rate (pr. forfatter)** viser antal publikationer divideret med antal unikke forfattere i
i den organisatoriske enhed - et produktivitetsmål, der gør det muligt at sammenligne enheder af 
meget forskellig størrelse. 

**Eksempel**: et institut har 30 forfattere og 100 publikationer. Raten er da 100 / 40 = 2.5. 
Et andet institut med 10 forfattere og 30 publikationer har en højere rate på 3.0, selvom
det samlede antal publikationer er lavere. 

Hvor der er mange kategorier (f.eks. publikationstype eller sprog), kan du selv vælge, hvor
mange der skal vises ved brug af **top-x**-feltet ovenfor figuren - resten samles i kategorien 'Andet'.
'Ukendt' vises altid særskilt, uanset hvor mange kategorier der er blevet valgt. 

---
""")

    mode = filters.get("mode", "F")

    st.markdown(
"""
#### Publikationstype

KU's publikationer fordeler sig på en række forskellige typer - fra tidsskriftartikler
og bøger til konferencebidrag og rapporter. Fordelingen herunder er opgjort på tværs af
de valgte organisatoriske niveauer og bygger på CURIS' egen registrering af
publikationstype.

**Eksempel**: en artikel i et internationalt tidsskrift registreres som 'Tidsskriftartikel', mens
den samme forskning præsenteret på en konference i stedet registreres som 'Konferencebidrag' - selv om
det er samme underliggende resultat. 

""")

    _type_category_sql = "COALESCE(Type, 'Ukendt')"
    _type_data_preview, _ = _query_section(filters, mode, _type_category_sql)
    _total_type = len({cat for cats in _type_data_preview.values() for cat in cats}) or 1
    
    _topx_type = st.number_input(
        "Vip top-x publikationstyper (resten samles i Andet-kategorien)",
        min_value=1, max_value=_total_type, value=min(5, _total_type), step=1, key="topx_type"
    )

    _tab_type_n, _tab_type_p, _tab_type_r = st.tabs(["Antal", "Andel (%)", "Rate (pr. forfatter)"])

    with _tab_type_n:
        _render_section(
            filters, 
            mode, 
            category_sql=_type_category_sql, 
            title_prefix="Publikationstype", 
            chart_mode="antal", 
            legend_position="right",
            top_x=_topx_type,
            always_keep=["Ukendt"])
    
    with _tab_type_p:
        _render_section(
            filters, 
            mode, 
            category_sql=_type_category_sql, 
            title_prefix="Publikationstype", 
            chart_mode="pct", 
            legend_position="right",
            top_x=_topx_type,
            always_keep=["Ukendt"])

    with _tab_type_r:
        _render_section(
            filters, 
            mode, 
            category_sql=_type_category_sql, 
            title_prefix="Publikationstype", 
            chart_mode="rate", 
            legend_position="right",
            top_x=_topx_type,
            always_keep=["Ukendt"])


    st.markdown(
"""
---

#### Indholdstype

Ud over selve publikationstypen registrerer CURIS også **indholdstypen**: hvilket formål en 
publikation tjener - forskning, formidling, undervisning eller rådgivning. Indholdstypen er
uafhængig af publikationstypen - en konferenceartikel kan f.eks. være registreret som
enten forskning eller formidling, afhængigt af den bagvedliggende aktivitet.
""")

    _tab_indhold_n, _tab_indhold_p, _tab_indhold_r = st.tabs(["Antal", "Andel (%)", "Rate (pr. forfatter)"])

    with _tab_indhold_n:
        _render_section(
            filters, mode,
            category_sql="Indholdstype",
            title_prefix="Indholdstype",
            order=INDHOLD_ORDER, colors=INDHOLD_COLORS, labels=INDHOLD_LABELS,
            chart_mode="antal",
        )

    with _tab_indhold_p:
        _render_section(
            filters, mode,
            category_sql="Indholdstype",
            title_prefix="Indholdstype",
            order=INDHOLD_ORDER, colors=INDHOLD_COLORS, labels=INDHOLD_LABELS,
            chart_mode="pct",
        )

    with _tab_indhold_r:
        _render_section(
            filters, mode,
            category_sql="Indholdstype",
            title_prefix="Indholdstype",
            order=INDHOLD_ORDER, colors=INDHOLD_COLORS, labels=INDHOLD_LABELS,
            chart_mode="rate",
        )

    
    st.markdown(
"""
---

#### Sprog

Hvilke sprog publicerer KU's forskere på? Fordelingen nedenfor viser publikationssprog
på tværs af de valgte organisatoriske niveauer. **'Ukendt'** dækker publikationer, hvor
sprog ikke er registreret i CURIS, samt CURIS-kategorien 'Andet sprog'. 
""")

    _sprog_category_sql = """
        CASE
            WHEN Sprog IS NULL OR Sprog = '' OR Sprog IN ('Udefineret/Ukendt', 'Andet sprog', 'Ukendt') THEN 'Ukendt'
            ELSE Sprog
        END
    """
    
    _sprog_data_preview, _ = _query_section(filters, mode, _sprog_category_sql)
    _total_sprog = len({cat for cats in _sprog_data_preview.values() for cat in cats}) or 1


    _topx_sprog = st.number_input(
        "Vis top-X sprog (resten samles i 'Andet')",
        min_value=1, max_value=_total_sprog, value=min(5, _total_sprog), step=1, key="topx_sprog",
    )

    _tab_sprog_n, _tab_sprog_p, _tab_sprog_r = st.tabs(["Antal", "Andel (%)", "Rate (pr. forfatter)"])

    with _tab_sprog_n:
        _render_section(
            filters, mode,
            category_sql=_sprog_category_sql,
            title_prefix="Sprog",
            chart_mode="antal",
            legend_position="right",
            top_x=_topx_sprog,
            always_keep=["Ukendt"]
        )

    with _tab_sprog_p:
        _render_section(
            filters, mode,
            category_sql=_sprog_category_sql,
            title_prefix="Sprog",
            chart_mode="pct",
            legend_position="right",
            top_x=_topx_sprog,
            always_keep=["Ukendt"]
        )

    with _tab_sprog_r:
        _render_section(
            filters, mode,
            category_sql=_sprog_category_sql,
            title_prefix="Sprog",
            chart_mode="rate",
            legend_position="right",
            top_x=_topx_sprog,
            always_keep=["Ukendt"]
        )


    st.markdown(
"""
---

#### Peer review

Peer review-status angiver, om en publikation har gennemgået fagfællebedømmelse.
Nedenfor er den fordelt på tværs af de valgte organisatoriske niveauer, baseret på
CURIS' registrering. **'Ukendt'** dækker publikationer, hvor status ikke er registreret.
""")

    _tab_peer_n, _tab_peer_p, _tab_peer_r = st.tabs(["Antal", "Andel (%)", "Rate (pr. forfatter)"])

    with _tab_peer_n:
        _render_section(
            filters, mode,
            category_sql="COALESCE(Peer_review, 'Ukendt')",
            title_prefix="Peer review-status",
            order=PEER_ORDER, colors=PEER_COLORS, labels=PEER_LABELS,
            chart_mode="antal",
        )

    with _tab_peer_p:
        _render_section(
            filters, mode,
            category_sql="COALESCE(Peer_review, 'Ukendt')",
            title_prefix="Peer review-status",
            order=PEER_ORDER, colors=PEER_COLORS, labels=PEER_LABELS,
            chart_mode="pct",
        )

    with _tab_peer_r:
        _render_section(
            filters, mode,
            category_sql="COALESCE(Peer_review, 'Ukendt')",
            title_prefix="Peer review-status",
            order=PEER_ORDER, colors=PEER_COLORS, labels=PEER_LABELS,
            chart_mode="rate",
        )

    st.markdown("""
--- 

#### Open Access

Open Access-status beskriver, i hvilken grad KU's publikationer er frit tilgængelige.
Fordelingen herunder bygger på CURIS' registrering og er opgjort på tværs af de valgte
organisatoriske niveauer. **'Ukendt'** dækker publikationer, hvor Open Access-status endnu 
ikke er registreret.

**Eksempel**: en artikel, der er frit tilgængelig fra udgivelsesdatoen, registreres som 'Open'. 
En artikel med et forlagspålagt embargo på f.eks. 12 måneder registreres i stedet som 'Embargoed',
indtil embargoperioden udløber. 
""")

    _tab_oa_n, _tab_oa_p, _tab_oa_r = st.tabs(["Antal", "Andel (%)", "Rate (pr. forfatter)"])

    with _tab_oa_n:
        _render_section(
            filters, mode,
            category_sql="COALESCE(Open_Access, 'Unknown')",
            title_prefix="Open Access-status",
            order=OA_ORDER, colors=OA_COLORS, labels=OA_LABELS,
            chart_mode="antal",
        )

    with _tab_oa_p:
        _render_section(
            filters, mode,
            category_sql="COALESCE(Open_Access, 'Unknown')",
            title_prefix="Open Access-status",
            order=OA_ORDER, colors=OA_COLORS, labels=OA_LABELS,
            chart_mode="pct",
        )

    with _tab_oa_r:
        _render_section(
            filters, mode,
            category_sql="COALESCE(Open_Access, 'Unknown')",
            title_prefix="Open Access-status",
            order=OA_ORDER, colors=OA_COLORS, labels=OA_LABELS,
            chart_mode="rate",
        )
    
    st.markdown(
"""
---

#### DOI

Sektionen viser, hvor stor en andel af publikationerne der har et registreret 
[DOI](https://www.doi.org/) (Digital Object Identifier), på tværs af de 
valgte organisatoriske niveauer.
""")

    _tab_doi_n, _tab_doi_p, _tab_doi_r = st.tabs(["Antal", "Andel (%)", "Rate (pr. forfatter)"])

    _doi_category_sql = "CASE WHEN DOI IS NULL OR DOI = '' THEN 'Nej' ELSE 'Ja' END"

    with _tab_doi_n:
        _render_section(
            filters, mode,
            category_sql=_doi_category_sql,
            title_prefix="DOI-status",
            order=DOI_ORDER, colors=DOI_COLORS, labels=DOI_LABELS,
            chart_mode="antal",
        )

    with _tab_doi_p:
        _render_section(
            filters, mode,
            category_sql=_doi_category_sql,
            title_prefix="DOI-status",
            order=DOI_ORDER, colors=DOI_COLORS, labels=DOI_LABELS,
            chart_mode="pct",
        )

    with _tab_doi_r:
        _render_section(
            filters, mode,
            category_sql=_doi_category_sql,
            title_prefix="DOI-status",
            order=DOI_ORDER, colors=DOI_COLORS, labels=DOI_LABELS,
            chart_mode="rate",
        )

    st.markdown(
"""
---

### Udvikling over tid 

Fanerne nedenfor viser, hvordan sammensætningen inden for hver dimension har udviklet sig
over tid. Graferne dækker altid **hele den tilgængelige periode**, uanset det valgte årsinterval - 
sidepanelets øvrige filtre gælder stadig. Er intet valgt i sidepanelet, dækker graferne hele 
KU; er f.eks. kun HUM valgt, viser graferne udelukkende udviklingen for HUM. 
""")


    _tab_trend_type, _tab_trend_indhold, _tab_trend_sprog, _tab_trend_peer, _tab_trend_oa, _tab_trend_doi = st.tabs(
        ["Publikationstype", "Indholdstype", "Sprog", "Peer review", "Open Access", "DOI"]
    )

    with _tab_trend_type:
        _render_trend_tab(filters, _type_category_sql, "Publikationstype",
                           top_x=_topx_type, always_keep=["Ukendt"])

    with _tab_trend_indhold:
        _render_trend_tab(filters, "Indholdstype", "Indholdstype",
                           order=INDHOLD_ORDER, colors=INDHOLD_COLORS, labels=INDHOLD_LABELS)

    with _tab_trend_sprog:
        _render_trend_tab(filters, _sprog_category_sql, "Sprog",
                           top_x=_topx_sprog, always_keep=["Ukendt"])

    with _tab_trend_peer:
        _render_trend_tab(filters, "COALESCE(Peer_review, 'Ukendt')", "Peer review-status",
                           order=PEER_ORDER, colors=PEER_COLORS, labels=PEER_LABELS)

    with _tab_trend_oa:
        _render_trend_tab(filters, "COALESCE(Open_Access, 'Unknown')", "Open Access-status",
                           order=OA_ORDER, colors=OA_COLORS, labels=OA_LABELS)

    with _tab_trend_doi:
        _render_trend_tab(filters, _doi_category_sql, "DOI-status",
                           order=DOI_ORDER, colors=DOI_COLORS, labels=DOI_LABELS)