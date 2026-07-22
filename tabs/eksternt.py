import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.loader import get_cursor, load_author_counts
from components.charts import fig_country_choropleth, fig_hbar_stacked, PLOTLY_CONFIG, land_label_da, fig_year_trend
from components.export import render_table_export
from components.colors import ku_color_sequence
from config import doi_filter_sql, year_range_label, hier_cols, breakdown_label, author_count_filter, show_ku_samlet
import re

import streamlit as st

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

EKST_ORDER = ["Ja", "Nej"]
EKST_COLORS = {"Ja": "#901a1e", "Nej": "#122947"}
EKST_LABELS = {"Ja": "Med ekstern samarbejdspartner", "Nej": "Uden ekstern samarbejdspartner"}

ANDET_LABEL = "Andet"

_EXT_EXISTS_SQL = """
    CASE WHEN EXISTS (
        SELECT 1 FROM pubs e WHERE e.PURE_ID = pubs.PURE_ID AND e.Intern = 'Ekstern'
          AND e.Land IS NOT NULL AND e.Land != ''
    ) THEN 'Ja' ELSE 'Nej' END
"""

@st.cache_data
def _query_section(filters, mode, category_sql):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(mode)
    n_dims = len(dims)

    if not dims: 
        select_dims, group_by, order_by_sql = "", "1", "1"
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
        # Selvstændig optælling, IKKE summen af fakultets-rækkerne - en
        # publikation med interne medforfattere fra flere fakulteter ville
        # ellers blive dobbelt-talt i "KU samlet", samme princip som
        # load_author_counts allerede håndterer korrekt for forfattere.
        ku_sql = f"""
            SELECT ({category_sql}) AS cat, COUNT(DISTINCT PURE_ID) AS n
            FROM pubs
            {where_sql}
            GROUP BY 1
        """
        ku_rows = get_cursor().execute(ku_sql, base_params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}
    
    return result, cluster_map

@st.cache_data
def _query_land_by_org(filters, mode):
    """Land pr. organisatorisk enhed - join mellem interne (dims) og eksterne (Land)"""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(mode)
    n_dims = len(dims)

    if not dims:
        return {}, {}
    
    select_dims = ", ".join(f"i.{col} AS dim_{i}" for i, col in enumerate(dims))
    group_by = ", ".join(str(i) for i in range(1, n_dims + 2))
    order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1))

    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'], alias="i.")

    where_sql = f"""
        WHERE i.Intern      = 'Intern'
          AND i.Fak         IN ({ph(filters['fakultet'])})
          AND i.Inst        IN ({ph(filters['institutter'])})
          AND i.Stil        IN ({ph(filters['stillingsgrupper'])})
          AND i.Type        IN ({ph(filters['typer'])})
          AND i.Sprog       IN ({ph(filters['sprog'])})
          AND i.Peer_review IN ({ph(filters['peer'])})
          AND i.Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi']).replace('DOI', 'i.DOI')})
          AND COALESCE(i.Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND i.Year        BETWEEN ? AND ?
          AND ({ac_sql})
          AND e.Intern = 'Ekstern' AND e.Land IS NOT NULL AND e.Land != ''
    """
    base_params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params
    )

    sql = f"""
        SELECT {select_dims},
               CASE WHEN e.Land = 'Unknown' THEN 'Ukendt' ELSE e.Land END AS cat,
               COUNT(DISTINCT i.PURE_ID) AS n
        FROM pubs i
        JOIN pubs e ON i.PURE_ID = e.PURE_ID
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
            SELECT CASE WHEN e.Land = 'Unknown' THEN 'Ukendt' ELSE e.Land END AS cat,
                   COUNT(DISTINCT i.PURE_ID) AS n
            FROM pubs i
            JOIN pubs e ON i.PURE_ID = e.PURE_ID
            {where_sql}
            GROUP BY 1
        """
        ku_rows = get_cursor().execute(ku_sql, base_params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}

    return result, cluster_map

@st.cache_data
def _query_org_totals(filters, mode):
    """Samlet antal INTERNE publikationer pr. organisatorisk enhed,
    uafhængigt af om de har eksterne medforfattere - bruges som nævner til
    Samarbejdslandes 'Andel (%)', så andelen regnes ud af ALLE publikationer
    for enheden, ikke kun dem med mindst én ekstern medforfatter."""
    data, _ = _query_section(filters, mode, "'Alle'")
    return {unit: sum(cats.values()) for unit, cats in data.items()}


@st.cache_data
def _query_country_count(filters, mode):
    """
    Antal distinkte samarbejdslande pr. organisatorisk enhed - tæller efter
    kanonisk (oversat) landenavn. Returnerer også en cluster_map, så
    resultatet kan vises med samme hierarkiske y-akse-opdeling som appens
    øvrige grafer.
    """
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(mode)
    n_dims = len(dims)
    if not dims:
        return {}, {}

    select_dims = ", ".join(f"i.{col} AS dim_{i}" for i, col in enumerate(dims)) + ", "
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'], alias="i.")

    sql = f"""
        SELECT DISTINCT {select_dims} e.Land AS raw_land
        FROM pubs i
        JOIN pubs e ON i.PURE_ID = e.PURE_ID
        WHERE i.Intern      = 'Intern'
          AND i.Fak         IN ({ph(filters['fakultet'])})
          AND i.Inst        IN ({ph(filters['institutter'])})
          AND i.Stil        IN ({ph(filters['stillingsgrupper'])})
          AND i.Type        IN ({ph(filters['typer'])})
          AND i.Sprog       IN ({ph(filters['sprog'])})
          AND i.Peer_review IN ({ph(filters['peer'])})
          AND i.Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi']).replace('DOI', 'i.DOI')})
          AND COALESCE(i.Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND i.Year        BETWEEN ? AND ?
          AND ({ac_sql})
          AND e.Intern = 'Ekstern' AND e.Land IS NOT NULL AND e.Land != '' AND e.Land != 'Unknown'
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()

    canonical_by_unit, cluster_map = {}, {}
    for row in rows:
        dim_values = row[:n_dims]
        raw_land = row[n_dims]
        dim_label = " | ".join(str(v) for v in reversed(dim_values))
        cluster_map[dim_label] = tuple(dim_values[:-1]) if n_dims > 1 else None
        canonical_by_unit.setdefault(dim_label, set()).add(land_label_da(raw_land))

    result = {unit: len(cset) for unit, cset in canonical_by_unit.items()}
    result = {unit: result[unit] for unit in sorted(result)}  # alfabetisk

    if mode == "F":
        all_canonical = set()
        for cset in canonical_by_unit.values():
            all_canonical |= cset
        result = {"KU samlet": len(all_canonical), **result}
        cluster_map["KU samlet"] = None

    return result, cluster_map


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
    
    palette = ku_color_sequence(len(keep))
    colors = {k: palette[i] for i, k in enumerate(keep)}
    colors[ANDET_LABEL] = "#cccccc"

    return out, keep + [ANDET_LABEL], colors

def _merge_land_categories(data: dict) -> dict:
    """
    Slår rå Land-kategorier sammen efter deres oversatte (kanoniske) navn -
    fx 'Netherlands' og 'Holland' er to forskellige rå strenge i CURIS, der
    begge oversættes til samme danske navn, og skal derfor ende som ÉT
    søjlesegment, ikke to.
    """
    merged = {}
    for unit, cats in data.items():
        new_cats = {}
        for raw_cat, n in cats.items():
            canonical = land_label_da(raw_cat)
            new_cats[canonical] = new_cats.get(canonical, 0) + n
        merged[unit] = new_cats
    return merged

@st.cache_data
def _query_countries(filters):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    sql = f"""
        WITH intern_match AS (
            SELECT DISTINCT PURE_ID
            FROM pubs
            WHERE Intern       = 'Intern'
              AND Fak          IN ({ph(filters['fakultet'])})
              AND Inst         IN ({ph(filters['institutter'])})
              AND Stil         IN ({ph(filters['stillingsgrupper'])})
              AND Type         IN ({ph(filters['typer'])})
              AND Sprog        IN ({ph(filters['sprog'])})
              AND Peer_review  IN ({ph(filters['peer'])})
              AND Indholdstype IN ({ph(filters['indholdstyper'])})
              AND ({doi_filter_sql(filters['har_doi'])})
              AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
              AND Year BETWEEN ? AND ?
              AND ({ac_sql})
        )
        SELECT CASE WHEN e.Land = 'Unknown' THEN 'Ukendt' ELSE e.Land END AS Land,
               COUNT(DISTINCT e.PURE_ID) AS n
        FROM pubs e
        WHERE e.Intern = 'Ekstern'
          AND e.Land IS NOT NULL AND e.Land != ''
          AND e.PURE_ID IN (SELECT PURE_ID FROM intern_match)
        GROUP BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    return {land: n for land, n in rows}

@st.cache_data
def _query_ekst_trend(filters):
    """Andel/antal publikationer med ekstern samarbejdspartner, år for år -
    ignorerer bevidst sidepanelets årsinterval og viser altid hele den
    tilgængelige periode, samme princip som appens øvrige 'over tid'-sektioner."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT Year, ({_EXT_EXISTS_SQL}) AS cat, COUNT(DISTINCT PURE_ID) AS n
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

@st.cache_data
def _query_land_trend(filters):
    """Samarbejdslande år for år, uafhængig af sidepanelets årsinterval -
    viser altid hele den tilgængelige periode. Samme forfatter-tælling som
    _query_land_by_org, men grupperet på Year i stedet for organisatorisk enhed."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'], alias="i.")

    sql = f"""
        SELECT i.Year,
               CASE WHEN e.Land = 'Unknown' THEN 'Ukendt' ELSE e.Land END AS raw_land,
               COUNT(DISTINCT i.PURE_ID) AS n
        FROM pubs i
        JOIN pubs e ON i.PURE_ID = e.PURE_ID
        WHERE i.Intern      = 'Intern'
          AND i.Fak         IN ({ph(filters['fakultet'])})
          AND i.Inst        IN ({ph(filters['institutter'])})
          AND i.Stil        IN ({ph(filters['stillingsgrupper'])})
          AND i.Type        IN ({ph(filters['typer'])})
          AND i.Sprog       IN ({ph(filters['sprog'])})
          AND i.Peer_review IN ({ph(filters['peer'])})
          AND i.Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi']).replace('DOI', 'i.DOI')})
          AND COALESCE(i.Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND i.Year IS NOT NULL
          AND ({ac_sql})
          AND e.Intern = 'Ekstern' AND e.Land IS NOT NULL AND e.Land != ''
        GROUP BY i.Year, raw_land
        ORDER BY i.Year
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()

    result = {}
    for year, raw_land, n in rows:
        result.setdefault(year, {})[raw_land] = n
    return result

@st.cache_data
def _query_year_totals(filters):
    """Samlet antal INTERNE publikationer pr. år, uafhængigt af om de har
    eksterne medforfattere - bruges som nævner til Samarbejdslande over
    tids 'Andel (%)'. Ignorerer bevidst sidepanelets årsinterval, samme
    princip som appens øvrige trend-forespørgsler."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT Year, COUNT(DISTINCT PURE_ID) AS n
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
        GROUP BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    return {year: n for year, n in rows}

@st.cache_data
def _query_country_count_trend(filters):
    """Antal DISTINKTE samarbejdslande år for år - uafhængig af sidepanelets
    årsinterval, viser altid hele den tilgængelige periode."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'], alias="i.")

    sql = f"""
        SELECT DISTINCT i.Year, e.Land AS raw_land
        FROM pubs i
        JOIN pubs e ON i.PURE_ID = e.PURE_ID
        WHERE i.Intern      = 'Intern'
          AND i.Fak         IN ({ph(filters['fakultet'])})
          AND i.Inst        IN ({ph(filters['institutter'])})
          AND i.Stil        IN ({ph(filters['stillingsgrupper'])})
          AND i.Type        IN ({ph(filters['typer'])})
          AND i.Sprog       IN ({ph(filters['sprog'])})
          AND i.Peer_review IN ({ph(filters['peer'])})
          AND i.Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi']).replace('DOI', 'i.DOI')})
          AND COALESCE(i.Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND i.Year IS NOT NULL
          AND ({ac_sql})
          AND e.Intern = 'Ekstern' AND e.Land IS NOT NULL AND e.Land != '' AND e.Land != 'Unknown'
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()

    canonical_by_year = {}
    for year, raw_land in rows:
        canonical_by_year.setdefault(year, set()).add(land_label_da(raw_land))

    return {year: len(cset) for year, cset in canonical_by_year.items()}


def _render_section(filters, mode, data, cluster_map, title_prefix, order=None, colors=None, labels=None,
                     chart_mode="antal", legend_position="right", top_x=None, always_keep=None,
                     xaxis_title="Antal publikationer", pct_denominators=None):
    
    if not any(data.values()):
        st.error("Ingen publikationer matcher de valgte filtre.")
        return 
    
    full_data = data

    if top_x:
        data, _order, _colors = _apply_top_x(data, top_x, always_keep=always_keep)
        if _order is not None:
            order, colors = _order, _colors
    
    if chart_mode == "rate":
        author_counts = load_author_counts(filters, mode)
        data = {u: {c: n / author_counts.get(u, 1) for c, n in cs.items()} for u, cs in data.items() if author_counts.get(u, 0) > 0}
        full_data = {u: {c: n / author_counts.get(u, 1) for c, n in cs.items()} for u, cs in full_data.items() if author_counts.get(u, 0) > 0}

        if not data: 
            st.error("Ingen forfattere matcher de valgte filtre.")
    
    y_labels = list(data.keys())

    if any(v is not None for v in cluster_map.values()):
        group_keys = ["__ku__" if lbl == "KU samlet" else cluster_map.get(lbl, "__single__") for lbl in y_labels]
    else:
        group_keys = None
    
    fig = fig_hbar_stacked(
        data=data, order=order, colors=colors, labels=labels,
        title=f"{title_prefix}, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal publikationer", mode=chart_mode,
        group_keys=group_keys, legend_position=legend_position,
        pct_denominators=pct_denominators,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    
    render_table_export(
        data=full_data, row_label="Enhed", col_labels=labels,
        filename=f"eksternt_{_slugify(title_prefix)}_{mode}_{chart_mode}.xlsx",
        sheet_name=title_prefix[:31],
        key=f"export_eksternt_{_slugify(title_prefix)}_{mode}_{chart_mode}",
    )

def _render_ekst_trend(filters):
    trend_data = _query_ekst_trend(filters)
    if not trend_data:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_eksternt",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=EKST_ORDER, colors=EKST_COLORS, labels=EKST_LABELS,
        title="Eksternt samarbejde over tid (hele perioden)", mode=chart_mode,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År", col_labels=EKST_LABELS,
        filename="eksternt_udvikling_over_tid.xlsx", sheet_name="Eksternt over tid",
        key="export_trend_eksternt",
    )

def _render_land_trend(filters):
    trend_data = _query_land_trend(filters)
    if not trend_data:
        st.error("Ingen eksterne samarbejder matcher de valgte filtre.")
        return

    trend_data = _merge_land_categories(trend_data)
    full_trend_data = trend_data
    year_totals = _query_year_totals(filters)
    total_land = len({cat for cats in trend_data.values() for cat in cats}) or 1
    topx = st.number_input(
        "Vis top-X lande (resten samles i 'Andet')",
        min_value=1, max_value=total_land, value=min(10, total_land), step=1, key="topx_land_trend",
    )

    order, colors = None, None
    if topx:
        trend_data, order, colors = _apply_top_x(trend_data, topx, always_keep=["Ukendt"])

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_land",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=order, colors=colors,
        title="Samarbejdslande over tid (hele perioden)", mode=chart_mode,
        pct_denominators=year_totals
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    render_table_export(
        data={str(year): cats for year, cats in sorted(full_trend_data.items())},
        row_label="År",
        filename="samarbejdslande_udvikling_over_tid.xlsx", sheet_name="Lande over tid",
        key="export_trend_land",
    )


def _render_country_count_trend(filters):
    trend_data = _query_country_count_trend(filters)
    if not trend_data:
        st.error("Ingen eksterne samarbejder matcher de valgte filtre.")
        return

    wrapped = {year: {"Lande": n} for year, n in trend_data.items()}

    fig = fig_year_trend(
        wrapped, order=["Lande"], colors={"Lande": "#901a1e"},
        title="Antal samarbejdslande over tid (hele perioden)", yaxis_title="Antal lande", mode="antal",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    render_table_export(
        data={str(year): {"Antal lande": n} for year, n in sorted(trend_data.items())},
        row_label="År",
        filename="antal_samarbejdslande_over_tid.xlsx", sheet_name="Antal lande over tid",
        key="export_trend_country_count",
    )

def render(filters):
    st.markdown(
"""
### Eksternt samarbejde

Fanen belyser KU's samarbejde med eksterne institutioner - både danske universiteter og internationale partnere -
opgjort på publikationer med mindst én ekstern medforfatter. Eksternt samarbejde er en indikator
for forskningens rækkevidde og kan indgå i strategiske vurderinger af, hvor godt et fakultet
eller institut er forankret i det internationale forskningslandskab. 

Oversigten viser de vigtigste samarbejdslande og den organisatotiske fordeling af KU's eksterne netværk. 
Fanen bygger for nu udelukkende på CURIS' registrering af medforfatteres landetilknytning; at 
koble samarbejdet til specifikke institutiner via OpenAlex og SciVal er under udvikling. 
""")

    st.markdown(
"""
---

#### Geografisk fordeling

Kortet viser, hvor mange af KU's publikationer der har mindst én ekstern medforfatter fra det pågældende land - 
dvs. en medforfatter, der **ikke** er ansat på KU - baseret på CURIS' registrering af medforfatters landetilknytning. 
'Danmark' på kortet dækker altså samarbejde med danske institutioner uden for KU (f.eks. andre universiteter
eller hospitaler), ikke internt samarbejde på tværs af KU's egne fakulteter og institutter. 

En publikation tælles kun med, hvis mindst én af dens **interne** KU-forfattere matcher de valgte filtre
i sidepanelet. 
"""
    )

    country_data = _query_countries(filters)
    if not country_data:
        st.error("Ingen eksterne samarbejder matcher de valgte filtre.")
        return

    fig, unmatched, unknown_count = fig_country_choropleth(
        country_data,
        title=f"Eksternt samarbejde efter land, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    if unmatched:
        st.caption(
            f"{len(unmatched)} landenavne kunne ikke genkendes og er udeladt af kortet: "
            + ", ".join(sorted(unmatched))
        )

    mode = filters.get("mode", "F")

    st.markdown(
"""
Figurene nedenfor viser, hvilke lande KU's eksterne medforfattere kommer fra, fordelt på de valgte organisatoriske
enheder - samme opgørelse som kortet ovenfor, bare brudt ned per enhed. 
""")

    _land_data, _land_cm = _query_land_by_org(filters, mode)
    _land_data = _merge_land_categories(_land_data)
    _land_totals = _query_org_totals(filters, mode)
    _total_land = len({cat for cats in _land_data.values() for cat in cats}) or 1
    _topx_land = st.number_input(
        "Vis top-X lande (resten samles i 'Andet')",
        min_value=1, max_value=_total_land, value=min(10, _total_land), step=1, key="topx_land",
    )

    _tab_land_n, _tab_land_p, _tab_land_r = st.tabs(["Antal", "Andel (%)", "Rate (pr. forfatter)"])

    with _tab_land_n:
        _render_section(filters, mode, _land_data, _land_cm, "Samarbejdslande",
                         chart_mode="antal", top_x=_topx_land, pct_denominators=_land_totals)
    with _tab_land_p:
        _render_section(filters, mode, _land_data, _land_cm, "Samarbejdslande",
                         chart_mode="pct", top_x=_topx_land, pct_denominators=_land_totals)
    with _tab_land_r:
        _render_section(filters, mode, _land_data, _land_cm, "Samarbejdslande",
                         chart_mode="rate", top_x=_topx_land, pct_denominators=_land_totals)

    st.markdown(
"""
---

#### Eksternt samarbejde pr. enhed

Sektionen viser, hvor mange af KU's publikationer der har mindst én ekstern
medforfatter, fordelt på de valgte organisatoriske niveauer - samt, i den sidste fane,
hvor mange forskellige lande hver enhed samarbejder med.
""")

    _tab_ekst_n, _tab_ekst_p, _tab_ekst_r, _tab_ekst_lande = st.tabs(
        ["Antal", "Andel (%)", "Rate (pr. forfatter)", "Antal samarbejdslande"]
    )
    _ekst_data, _ekst_cm = _query_section(filters, mode, _EXT_EXISTS_SQL)

    with _tab_ekst_n:
        _render_section(filters, mode, _ekst_data, _ekst_cm, "Eksternt samarbejde",
                         order=EKST_ORDER, colors=EKST_COLORS, labels=EKST_LABELS, chart_mode="antal")
    with _tab_ekst_p:
        _render_section(filters, mode, _ekst_data, _ekst_cm, "Eksternt samarbejde",
                         order=EKST_ORDER, colors=EKST_COLORS, labels=EKST_LABELS, chart_mode="pct")
    with _tab_ekst_r:
        _render_section(filters, mode, _ekst_data, _ekst_cm, "Eksternt samarbejde",
                         order=EKST_ORDER, colors=EKST_COLORS, labels=EKST_LABELS, chart_mode="rate")
    with _tab_ekst_lande:
        _country_data, _country_cm = _query_country_count(filters, mode)
        _country_wrapped = {u: {"Lande": n} for u, n in _country_data.items()}
        _render_section(
            filters, mode, _country_wrapped, _country_cm, "Antal samarbejdslande",
            order=["Lande"], colors={"Lande": "#901a1e"}, labels={"Lande": "Antal lande"},
            chart_mode="antal", xaxis_title="Antal lande",
        )
    
    st.markdown(
"""
---

#### Udvikling over tid

Graferne nedenfor dækker altid hele den tilgængelige periode, uanset sidepanelets
valgte årsinterval - øvrige filtre gælder stadig.
"""
    )
    _tab_trend_land, _tab_trend_ekst, _tab_trend_antal_land = st.tabs(
        ["Samarbejdslande", "Med/uden ekstern samarbejdspartner", "Antal samarbejdslande"]
    )
    with _tab_trend_land:
        _render_land_trend(filters)
    with _tab_trend_ekst:
        _render_ekst_trend(filters)
    with _tab_trend_antal_land:
        _render_country_count_trend(filters)

