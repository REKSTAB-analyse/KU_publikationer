import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from data.loader import get_cursor
from components.charts import fig_hbar_stacked, fig_year_trend, PLOTLY_CONFIG
from components.export import render_table_export
from components.colors import stillingsgruppe_colors
from config import hier_cols, breakdown_label, author_count_filter, show_ku_samlet, STIL_ORDER, year_range_label

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
def _query_stil_totals(filters, mode, count_col="PURE_ID"):
    """Samlet antal DISTINKTE enheder (publikationer eller forfattere) pr.
    organisatorisk enhed, UAFHÆNGIGT af stillingsgruppe - bruges som nævner
    til 'Andel (%)', så andelen regnes ud af enhedens egne distinkte
    publikationer/forfattere, ikke summen af stillingsgruppernes
    (potentielt overlappende) tal. Genbruger _query_authors med en konstant
    kategori, hvilket også giver en korrekt, selvstændig 'KU samlet'-værdi
    gratis, via dens eksisterende mekanisme."""
    data, _ = _query_authors(filters, mode, "'Alle'", count_col=count_col)
    return {unit: sum(cats.values()) for unit, cats in data.items()}

@st.cache_data
def _query_year_totals_by_count(filters, count_col="ext_id"):
    """Samlet antal DISTINKTE enheder pr. år, UAFHÆNGIGT af stillingsgruppe -
    bruges som nævner til trend-fanernes 'Andel (%)', af samme grund som
    _query_stil_totals: undgår at dobbelttælle, når samme person/publikation
    optræder under flere stillingsgrupper samme år. Ignorerer bevidst
    sidepanelets årsinterval, samme princip som selve trend-forespørgslerne."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT Year, COUNT(DISTINCT {count_col}) AS n
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
        GROUP BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    return {year: n for year, n in rows}

@st.cache_data
def _query_stil_trend(filters):
    """Antal publicerende forfattere år for år pr. stillingsgruppe."""
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

@st.cache_data
def _query_stil_pub_trend(filters):
    """Antal publikationer år for år pr. stillingsgruppe - samme princip som
    _query_stil_trend, men tæller PUBLIKATIONER (PURE_ID), ikke personer."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT Year, COALESCE(Stil, 'Ukendt') AS stil, COUNT(DISTINCT PURE_ID) AS n
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


@st.cache_data
def _query_stil_korr_trend(filters):
    """Antal forfatterskaber og heraf antal korresponderende, år for år pr.
    stillingsgruppe - tæller forfatterskaber (person-publikation-par), ikke
    personer eller publikationer, samme enhed som Korr-sektionen ovenfor."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT Year, COALESCE(Stil, 'Ukendt') AS stil,
               COUNT(*) AS total,
               SUM(CASE WHEN Korr = 'Ja' THEN 1 ELSE 0 END) AS korr_ja
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
    for year, stil, total, korr_ja in rows:
        result.setdefault(year, {})[stil] = {"total": total, "korr_ja": korr_ja}
    return result

def _render_stil_trend_generic(trend_data, hover_unit, yaxis_title, chart_title, key_suffix, pct_denominators=None):
    """Genbrugelig renderer til Forfattere- og Publikationer-fanerne - begge
    er simple {år: {stillingsgruppe: antal}}-strukturer, og Andel (%)
    beregnes på tværs af stillingsgrupper via fig_year_trends indbyggede
    logik (fx 'hvor stor en andel af alle publicerende forfattere var
    professorer det år')."""
    if not trend_data:
        st.error("Ingen data matcher de valgte filtre.")
        return

    trend_data = {
        year: {stil: n for stil, n in cats.items() if stil != "Ukendt"}
        for year, cats in trend_data.items()
    }
    stil_order = [s for s in STIL_ORDER if s != "Ukendt"]

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True,
        key=f"trend_mode_{key_suffix}",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=stil_order, colors=stillingsgruppe_colors(),
        title=f"{chart_title} over tid (hele perioden)",
        yaxis_title=yaxis_title, mode=chart_mode, hover_unit=hover_unit,
        pct_denominators=pct_denominators,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År",
        filename=f"{key_suffix}_udvikling_over_tid.xlsx",
        sheet_name=f"{key_suffix[:25]} trend",
        key=f"export_trend_{key_suffix}",
    )


def _render_stil_korr_trend(filters):
    """Korresponderende forfatterskaber over tid - Andel (%) beregnes HER
    bevidst anderledes end i den generiske renderer: som andel af hver
    stillingsgruppes EGNE forfatterskaber det år, ikke på tværs af grupper -
    fig_year_trends indbyggede pct-logik passer ikke til det spørgsmål."""
    trend_data = _query_stil_korr_trend(filters)
    if not trend_data:
        st.error("Ingen data matcher de valgte filtre.")
        return

    trend_data = {
        year: {stil: v for stil, v in cats.items() if stil != "Ukendt"}
        for year, cats in trend_data.items()
    }
    stil_order = [s for s in STIL_ORDER if s != "Ukendt"]

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True,
        key="trend_mode_stil_korr",
    )

    if visning == "Antal":
        plot_data = {
            year: {stil: v["korr_ja"] for stil, v in cats.items()}
            for year, cats in trend_data.items()
        }
        yaxis_title = "Antal korresponderende forfatterskaber"
        hover_unit = "korresponderende forfatterskaber"
        filename, sheet, key = "korr_forfatterskaber_antal_over_tid.xlsx", "Korr trend (antal)", "export_trend_korr_antal"
    else:
        plot_data = {
            year: {
                stil: round(100 * v["korr_ja"] / v["total"], 1) if v["total"] > 0 else 0
                for stil, v in cats.items()
            }
            for year, cats in trend_data.items()
        }
        yaxis_title = "Andel korresponderende (%)"
        hover_unit = "% korresponderende"
        filename, sheet, key = "korr_forfatterskaber_andel_over_tid.xlsx", "Korr trend (andel)", "export_trend_korr_pct"

    fig = fig_year_trend(
        plot_data, order=stil_order, colors=stillingsgruppe_colors(),
        title="Korresponderende forfatterskaber over tid (hele perioden)",
        yaxis_title=yaxis_title, mode="antal", hover_unit=hover_unit,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    render_table_export(
        data={str(year): cats for year, cats in sorted(plot_data.items())},
        row_label="År", filename=filename, sheet_name=sheet, key=key,
    )

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
        title="Stillingsgruppe over tid (hele perioden)", yaxis_title="Antal forfattere", mode=chart_mode, hover_unit="forfattere",
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
        title=f"Korresponderende forfatterskaber pr. stillingsgruppe, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal forfatterskaber", mode=chart_mode,
        group_keys=group_keys, legend_position="right",
        hover_unit="forfatterskaber",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    render_table_export(
        data=data, row_label="Enhed", col_labels=KORR_LABELS,
        filename=f"korr_stillingsgruppe_{mode}_{chart_mode}.xlsx",
        sheet_name="Korr pr. stillingsgruppe",
        key=f"export_korr_stillingsgruppe_{mode}_{chart_mode}",
    )

def _render_section(filters, mode, category_sql, title_prefix, order=None, colors=None, labels=None,
                     chart_mode="antal", legend_position="bottom", count_col="ext_id", xaxis_title="Antal forfattere",
                     pct_denominators=None):
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

    hover_unit = "forfattere" if count_col == "ext_id" else "publikationer"

    fig = fig_hbar_stacked(
        data=data,
        order=order,
        colors=colors,
        labels=labels,
        title=f"{title_prefix}, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title=xaxis_title,
        mode=chart_mode,
        group_keys=group_keys,
        legend_position=legend_position,
        hover_unit=hover_unit,
        pct_denominators=pct_denominators,
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
organisatoriske niveauer (fakultet/institut). Andelen (%) angiver, hvor stor en del af enhedens
**publicerende forfattere** der tilhører hver stillingsgruppe, f.eks. at professorer kan udgøre
40% af SUND's forfattere. 

""")

    _stil_forf_totals = _query_stil_totals(filters, _stil_mode, count_col="ext_id")
    _tab_stil_n, _tab_stil_p = st.tabs(["Antal", "Andel (%)"])
    with _tab_stil_n:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="antal", legend_position="right",
            pct_denominators=_stil_forf_totals,
        )
    with _tab_stil_p:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="pct", legend_position="right",
            pct_denominators=_stil_forf_totals,
        )
    
    st.markdown(
"""
---

#### Publikationer pr. stillingsgruppe

I modsætning til sektionen ovenfor tæller denne **publikationer**, ikke personer:
en publikation med forfattere fra flere stillingsgrupper (fx en professor og en
ph.d.-studerende som medforfattere) tælles med i hver af de involverede grupper -
samme princip som resten af appens organisatoriske nedbrydninger.

Andelen (%) angiver defor, hvor stor en del af enhedens publikationer der har **mindst én** forfatter
fra den pågældende stillingsgruppe, f.eks. at professorer er med på 40% af alle publikationer. 
Det betyder ikke, at professorer har skrevet de 40% alene; en publikation kan tælle med under flere
stillingsgrupper på én gang. 
""")

    _stil_pub_totals = _query_stil_totals(filters, _stil_mode, count_col="PURE_ID")
    _tab_stilpub_n, _tab_stilpub_p = st.tabs(["Antal", "Andel (%)"])
    with _tab_stilpub_n:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Publikationer pr. stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="antal", legend_position="right",
            count_col="PURE_ID", xaxis_title="Antal publikationer", pct_denominators=_stil_pub_totals,
        )
    with _tab_stilpub_p:
        _render_section(
            filters, _stil_mode, "COALESCE(Stil, 'Ukendt')", "Publikationer pr. stillingsgruppe",
            order=STIL_ORDER, colors=stillingsgruppe_colors(), chart_mode="pct", legend_position="right",
            count_col="PURE_ID", xaxis_title="Antal publikationer", pct_denominators=_stil_pub_totals,
        )
    
    st.markdown(
"""
---

#### Korresponderende forfatterskaber pr. stillingsgruppe

**Metrikken her er forfatterskaber, ikke forfattere eller publikationer**: hver optælling er
én persons rolle på én bestemt publikation. Hvis én person har bidraget til tre publikationer, 
tæller vedkommende med ét forfatterskab per publikation, så tre forfatterskaber. 

Andelen af forfatterskaber, hvor personen er registreret som korresponderende forfatter,
er en indikator for forskningsledelse, ikke kun medforfatterskab. Brydes ned på de
organisatoriske niveauer valgt i sidepanelet (fakultet/institut), med stillingsgruppe
som det fineste niveau.
""")
    _tab_korr_n, _tab_korr_p = st.tabs(["Antal", "Andel (%)"])
    with _tab_korr_n:
        _render_korr_section(filters, _stil_mode, chart_mode="antal")
    with _tab_korr_p:
        _render_korr_section(filters, _stil_mode, chart_mode="pct")
    


    st.markdown(
"""
---

#### Udvikling over tid

Hvordan har sammensætningen af KU's **publicerende** personale udviklet sig - målt på
antal forfattere, antal publikationer eller andelen af korresponderende forfatterskaber?
Bemærk: hvert år tæller kun det, der reelt er registreret i netop det år - et fald kan
derfor lige så vel skyldes lavere publiceringsaktivitet det år som en reel ændring i
antal ansatte. 

Graferne viser altid hele den tilgængelige periode, uanset sidepanelets
valgte årsinterval - øvrige filtre gælder stadig. Er intet valgt i sidepanelet, dækker 
graferne hele KU; er f.eks. kun HUM valgt, viser graferne udelukkende udviklingen for HUM. 
""")
    _tab_trend_forf, _tab_trend_pub, _tab_trend_korr = st.tabs(
        ["Forfattere", "Publikationer", "Korresponderende forfatterskaber"]
    )
    with _tab_trend_forf:
        _render_stil_trend_generic(
            _query_stil_trend(filters), hover_unit="forfattere",
            yaxis_title="Antal forfattere", chart_title="Forfattere pr. stillingsgruppe",
            key_suffix="stil_forfattere",
            pct_denominators=_query_year_totals_by_count(filters, count_col="ext_id"),
        )
    with _tab_trend_pub:
        _render_stil_trend_generic(
            _query_stil_pub_trend(filters), hover_unit="publikationer",
            yaxis_title="Antal publikationer", chart_title="Publikationer pr. stillingsgruppe",
            key_suffix="stil_publikationer",
            pct_denominators=_query_year_totals_by_count(filters, count_col="PURE_ID"),
        )
        st.caption(
"""
Andelen (%) angiver, hvor stor en del af årets publikationer der har mindst én forfatter i den
pågældende stillingsgruppe - en publikation kan altså tælle med under flere stillingsgrupper
samme år.
""")
    with _tab_trend_korr:
        _render_stil_korr_trend(filters)