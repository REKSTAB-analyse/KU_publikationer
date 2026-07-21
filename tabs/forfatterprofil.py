import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from data.loader import get_cursor
from components.charts import fig_hbar_stacked, fig_year_trend, PLOTLY_CONFIG
from components.export import render_table_export
from components.colors import stillingsgruppe_colors
from config import hier_cols, breakdown_label, author_count_filter, show_ku_samlet, STIL_ORDER

# --- Konstanter per sektion ---
KOEN_ORDER = ["Kvinder", "Mænd", "Ukendt"]
KOEN_COLORS = {
    "Kvinder": "#901a1e",
    "Mænd": "#122947",
    "Ukendt": "#666666",
}
KOEN_LABELS = {
    "Kvinder": "Kvinder",
    "Mænd": "Mænd",
    "Ukendt": "Ukendt",
}

NATIONALITET_ORDER = ["Dansk", "International", "Ukendt"]
NATIONALITET_COLORS = {
    "Dansk": "#122947",
    "International": "#901a1e",
    "Ukendt": "#666666",
}
NATIONALITET_LABELS = {
    "Dansk": "Dansk statsborgerskab",
    "International": "Internationalt statsborgerskab",
    "Ukendt": "Ukendt",
}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _base_where_and_params(filters):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    where_sql = f"""
        WHERE Intern       = 'Intern'
          AND Fak          IN ({ph(filters['fakultet'])})
          AND Inst         IN ({ph(filters['institutter'])})
          AND Stil         IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year        BETWEEN ? AND ?
          AND ({ac_sql})
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params
    )
    return where_sql, params

@st.cache_data
def _query_authors(filters, mode, category_sql, count_col="ext_id"):
    """count_col='ext_id' tæller unikke FORFATTERE (KU-ID'er) - en person
    tælles én gang, uanset hvor mange publikationer vedkommende har.
    count_col='PURE_ID' tæller unikke PUBLIKATIONER i stedet - en
    publikation med forfattere fra flere kategorier (fx stillingsgrupper)
    tælles med i hver af dem."""
    where_sql, params = _base_where_and_params(filters)
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

    sql = f"""
        SELECT {select_dims}({category_sql}) AS cat,
               COUNT(DISTINCT {count_col}) AS n
        FROM pubs
        {where_sql}
        GROUP BY {group_by}
        ORDER BY {order_by_sql}
    """
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

    if mode == "F" and show_ku_samlet(filters):
        ku_sql = f"SELECT ({category_sql}) AS cat, COUNT(DISTINCT {count_col}) AS n FROM pubs {where_sql} GROUP BY 1"
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}

    return result, cluster_map


def _total_unique_authors(filters) -> int:
    where_sql, params = _base_where_and_params(filters)
    sql = f"SELECT COUNT(DISTINCT ext_id) FROM pubs {where_sql}"
    return get_cursor().execute(sql, params).fetchone()[0]

@st.cache_data
def _query_stil_trend(filters):
    """Stillingsgruppe-sammensætning år for år, uafhængig af sidepanelets
    årsinterval - viser altid hele den tilgængelige periode. Tæller unikke
    KU-ID'er (personer), samme talstørrelse som Stillingsgruppe-sektionen."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT Year, COALESCE(Stil, 'Ukendt') AS stil, COUNT(DISTINCT ext_id) AS n
        FROM pubs
        WHERE Intern       = 'Intern'
          AND Fak          IN ({ph(filters['fakultet'])})
          AND Inst         IN ({ph(filters['institutter'])})
          AND Stil         IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year IS NOT NULL
          AND ({ac_sql})
        GROUP BY 1, 2
        ORDER BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()

    result = {}
    for year, stil, n in rows:
        result.setdefault(year, {})[stil] = n
    return result


def _render_stil_trend(filters):
    trend_data = _query_stil_trend(filters)
    if not trend_data:
        st.error("Ingen forfattere matcher de valgte filtre.")
        return

    trend_data = {
        year: {stil: n for stil, n in cats.items() if stil != "Ukendt"}
        for year, cats in trend_data.items()
    }
    stil_order = [s for s in STIL_ORDER if s != "Ukendt"]

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_stillingsgruppe",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=stil_order, colors=stillingsgruppe_colors(),
        title="Stillingsgruppe over tid (hele perioden)", mode=chart_mode,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År",
        filename="stillingsgruppe_udvikling_over_tid.xlsx",
        sheet_name="Stillingsgruppe trend",
        key="export_trend_stillingsgruppe",
    )

@st.cache_data
def _query_korr_by_stil(filters, mode):
    """Andel forfatterskaber med korresponderende forfatter, brudt ned på
    stillingsgruppe OG de organisatoriske niveauer valgt i sidepanelet
    (Fak/Inst) - stillingsgruppe er altid det fineste niveau, tilføjet
    efter de øvrige valgte dimensioner."""
    where_sql, params = _base_where_and_params(filters)
    dims = hier_cols(mode) + ["Stil"]
    n_dims = len(dims)

    select_dims = ", ".join(
        f"COALESCE({col}, 'Ukendt') AS dim_{i}" if col == "Stil" else f"{col} AS dim_{i}"
        for i, col in enumerate(dims)
    ) + ", "
    group_by = ", ".join(str(i) for i in range(1, n_dims + 2))
    order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1))

    sql = f"""
        SELECT {select_dims}COALESCE(Korr, 'Ukendt') AS korr, COUNT(*) AS n
        FROM pubs
        {where_sql}
        GROUP BY {group_by}
        ORDER BY {order_by_sql}
    """
    rows = get_cursor().execute(sql, params).fetchall()

    result, cluster_map = {}, {}
    for row in rows:
        dim_values = row[:n_dims]
        cat = row[n_dims]
        n = row[n_dims + 1]
        dim_label = " | ".join(str(v) for v in reversed(dim_values))
        clusters = tuple(dim_values[:-1]) if n_dims > 1 else None
        if dim_label not in result:
            result[dim_label] = {}
            cluster_map[dim_label] = clusters
        result[dim_label][cat] = result[dim_label].get(cat, 0) + n

    return result, cluster_map


KORR_ORDER = ["Ja", "Nej", "Ukendt"]
KORR_COLORS = {"Ja": "#901a1e", "Nej": "#122947", "Ukendt": "#666666"}
KORR_LABELS = {"Ja": "Korresponderende forfatter", "Nej": "Ikke korresponderende", "Ukendt": "Ukendt"}


def _render_korr_section(filters, mode, chart_mode="antal"):
    data, cluster_map = _query_korr_by_stil(filters, mode)
    if not any(data.values()):
        st.error("Ingen forfattere matcher de valgte filtre.")
        return

    y_labels = list(data.keys())
    if any(v is not None for v in cluster_map.values()):
        group_keys = [cluster_map.get(lbl, "__single__") for lbl in y_labels]
    else:
        group_keys = None

    fig = fig_hbar_stacked(
        data=data, order=KORR_ORDER, colors=KORR_COLORS, labels=KORR_LABELS,
        title=f"Korresponderende forfatter pr. stillingsgruppe, {breakdown_label(mode)}",
        xaxis_title="Antal forfatterskaber", mode=chart_mode,
        group_keys=group_keys, legend_position="right",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    render_table_export(
        data=data, row_label="Enhed", col_labels=KORR_LABELS,
        filename=f"korr_stillingsgruppe_{mode}_{chart_mode}.xlsx",
        sheet_name="Korr pr. stillingsgruppe",
        key=f"export_korr_stillingsgruppe_{mode}_{chart_mode}",
    )

def _render_section(filters, mode, category_sql, title_prefix, order=None, colors=None, labels=None,
                     chart_mode="antal", legend_position="bottom", count_col="ext_id", xaxis_title="Antal forfattere"):
    data, cluster_map = _query_authors(filters, mode, category_sql, count_col=count_col)
    if not any(data.values()):
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
        title=f"{title_prefix}, {breakdown_label(mode)}",
        xaxis_title=xaxis_title,
        mode=chart_mode,
        group_keys=group_keys,
        legend_position=legend_position,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    render_table_export(
        data=data,
        row_label="Enhed",
        col_labels=labels,
        filename=f"{_slugify(title_prefix)}_{mode}_{chart_mode}.xlsx",
        sheet_name=title_prefix[:31],
        key=f"export_forfatter_{_slugify(title_prefix)}_{mode}_{chart_mode}",
    )

def render(filters: dict):
    st.markdown(
"""
### Forfatterprofil

Hvor Publikationsformer og Forskningsprofil ser på selve outputtet, ser denne fane på
**personerne** bag det: hvor mange forfattere står bag KU's publikationer, hvordan
de fordeler sig på stillingsgruppe og deres rolle i publiceringerne.

Generelt tælles **unikke KU-ID'er blandt dem, der har mindst én publikation** i 
den valgte periode: en forsker tæller med præcis én gang, uanset hvor mange publikationer de har i den 
perioden. Det er altså et mål for, hvor mange **publicerende personer** der findes
i hvert stillingsgruppe, ikke hvor mange KU reelt har ansat - en forsker, der ikke har publiceret
i perioden, indgår ikke i tallet, uanset ansættelsesforhold. 

---
""")

    mode = filters.get("mode", "F")
    _stil_mode = mode.replace("G", "")

    st.markdown(
"""
#### Stillingsgruppe

Fordelingen af KU's forfattere på tværs af stillingsgrupper, fordelt på de valgte
organisatoriske niveauer (fakultet/institut).

""")

    _tab_stil_n, _tab_stil_p = st.tabs(["Antal", "Andel (%)"])
    with _tab_stil_n:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="antal", legend_position="right",
        )
    with _tab_stil_p:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="pct", legend_position="right",
        )
    
    st.markdown(
"""
---

#### Publikationer pr. stillingsgruppe

I modsætning til sektionen ovenfor tæller denne **publikationer**, ikke personer:
en publikation med forfattere fra flere stillingsgrupper (fx en professor og en
ph.d.-studerende som medforfattere) tælles med i hver af de involverede grupper -
samme princip som resten af appens organisatoriske nedbrydninger.
""")

    _tab_stilpub_n, _tab_stilpub_p = st.tabs(["Antal", "Andel (%)"])
    with _tab_stilpub_n:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Publikationer pr. stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="antal", legend_position="right",
            count_col="PURE_ID", xaxis_title="Antal publikationer",
        )
    with _tab_stilpub_p:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Publikationer pr. stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="pct", legend_position="right",
            count_col="PURE_ID", xaxis_title="Antal publikationer",
        )
    
    st.markdown(
"""
---

#### Korresponderende forfatter pr. stillingsgruppe

Andelen af forfatterskaber, hvor personen er registreret som korresponderende forfatter -
en indikator for forskningsledelse, ikke kun medforfatterskab. Vises for KU samlet,
uafhængigt af organisatorisk niveau i sidepanelet.
""")
    _tab_korr_n, _tab_korr_p = st.tabs(["Antal", "Andel (%)"])
    with _tab_korr_n:
        _render_korr_section(filters, _stil_mode, chart_mode="antal")
    with _tab_korr_p:
        _render_korr_section(filters, _stil_mode, chart_mode="pct")
    
    st.markdown(
"""
---

#### Stillingsgruppe over tid

Hvordan har sammensætningen af KU's **publicerende** personale udviklet sig? Bemærk: 
hvert år tæller kun de personer, der har mindst én publikation registreret i netop
det år - et fald i en stillingsgruppe kan derfor lige så vel skyldes en lavere 
publiceringsaktivitet det år som en reel ændring i antal ansatte. Grafen viser
altid hele den tilgængelige periode, uanset sidepanelets valgte årsinterval - øvrige
filtre gælder stadig. 
""")
    _render_stil_trend(filters)