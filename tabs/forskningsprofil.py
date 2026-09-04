from tracemalloc import Snapshot
import sys
from pathlib import Path
import re
import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
 
import streamlit as st
from data.loader import get_cursor, load_figur_svg
import plotly.graph_objects as go
from components.charts import fig_hbar_stacked, fig_year_trend, PLOTLY_CONFIG, domain_shaded_colors, _DOMAIN_COLORS, _hls_gradient
from components.export import render_table_export
from components.colors import ku_color_sequence, build_faculty_colors
from config import FAC_ORDER, REFERENCE_TABLE_PATHS
from config import hier_cols, breakdown_label, doi_filter_sql, year_range_label, author_count_filter, show_ku_samlet

_ASJC_FIELD_TO_DOMAIN = {
    "AGRI": "Life Sciences", "ARTS": "Social Sciences", "BIOC": "Life Sciences",
    "BUSI": "Social Sciences", "CENG": "Physical Sciences", "CHEM": "Physical Sciences",
    "COMP": "Physical Sciences", "DECI": "Social Sciences", "DENT": "Health Sciences",
    "EART": "Physical Sciences", "ECON": "Social Sciences", "ENER": "Physical Sciences",
    "ENGI": "Physical Sciences", "ENVI": "Physical Sciences", "HEAL": "Health Sciences",
    "IMMU": "Life Sciences", "MATE": "Physical Sciences", "MATH": "Physical Sciences",
    "MEDI": "Health Sciences", "NEUR": "Life Sciences", "NURS": "Health Sciences",
    "PHAR": "Life Sciences", "PHYS": "Physical Sciences", "PSYC": "Social Sciences",
    "SOCI": "Social Sciences", "VETE": "Health Sciences", "MULT": "Multidisciplinary",
}

_ASJC_FIELD_NAMES = {
    "AGRI": "Agricultural and Biological Sciences", "ARTS": "Arts and Humanities",
    "BIOC": "Biochemistry, Genetics and Molecular Biology", "BUSI": "Business, Management and Accounting",
    "CENG": "Chemical Engineering", "CHEM": "Chemistry", "COMP": "Computer Science",
    "DECI": "Decision Sciences", "DENT": "Dentistry", "EART": "Earth and Planetary Sciences",
    "ECON": "Economics, Econometrics and Finance", "ENER": "Energy", "ENGI": "Engineering",
    "ENVI": "Environmental Science", "HEAL": "Health Professions", "IMMU": "Immunology and Microbiology",
    "MATE": "Materials Science", "MATH": "Mathematics", "MEDI": "Medicine", "NEUR": "Neuroscience",
    "NURS": "Nursing", "PHAR": "Pharmacology, Toxicology and Pharmaceutics", "PHYS": "Physics and Astronomy",
    "PSYC": "Psychology", "SOCI": "Social Sciences", "VETE": "Veterinary", "MULT": "Multidisciplinary",
}

_ASJC_FIELD_NAME_TO_DOMAIN = {name: _ASJC_FIELD_TO_DOMAIN[abbr] for abbr, name in _ASJC_FIELD_NAMES.items()}

ANDET_LABEL = "Andet"

def _case_expr(col_expr: str, mapping: dict, default: str = "'Ukendt'") -> str:
    whens = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in mapping.items())
    return f"CASE {col_expr} {whens} ELSE {default} END"

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
        ku_sql = f"""
            SELECT ({category_sql}) AS cat, COUNT(DISTINCT PURE_ID) AS n
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
            GROUP BY 1
        """
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}
    
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

@st.cache_data
def _query_asjc_section(filters, level, restrict_domain=None, restrict_field_abbr=None):
    """
    ASJC er flerværdi pr. publikation - felter, koder og navne er alle
    PIPE-SEPAREREDE i SAMME rækkefølge (positionelt parrede). For at undgå
    at et felt/en kategori fra et HELT ANDET fagområde/felt "lækker" ind,
    når man er zoomet ind på ét bestemt niveau, EKSPLODERES asjc_felter og
    asjc_navne SAMMEN (positionelt, via to UNNEST i samme SELECT-liste -
    IKKE i FROM-delen, som ikke parrer korrekt i DuckDB), og selve
    restriktionen (restrict_domain/restrict_field_abbr) filtrerer på det
    EKSPLODEREDE par, ikke kun på om publikationen overhovedet matcher et
    sted i sin fulde liste.
    level: 'domain' | 'field' | 'category'
    """
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(filters.get("mode", "F"))
    n_dims = len(dims)
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    dim_select = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""

    base_where = f"""
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
          AND ASJC_felter IS NOT NULL AND ASJC_felter != ''
    """
    base_params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params
    )

    domain_case = _case_expr("felt_abbr", _ASJC_FIELD_TO_DOMAIN)
    field_case = _case_expr("felt_abbr", _ASJC_FIELD_NAMES)

    # --- Positionel eksplodering: felt og kategori-navn SAMMEN, i SELECT-listen ---
    exploded_sql = f"""
        SELECT {dim_select}PURE_ID,
               TRIM(UNNEST(STRING_SPLIT(ASJC_felter, '|'))) AS felt_abbr,
               TRIM(UNNEST(STRING_SPLIT(ASJC_navne, '|'))) AS kat_navn
        FROM pubs
        {base_where}
    """

    restrict_sql = ""
    restrict_params = []
    if restrict_domain:
        restrict_sql = f"AND {domain_case} = ?"
        restrict_params = [restrict_domain]
    elif restrict_field_abbr:
        restrict_sql = "AND felt_abbr = ?"
        restrict_params = [restrict_field_abbr]

    if level == "domain":
        value_expr = domain_case
    elif level == "field":
        value_expr = field_case
    else:  # category
        value_expr = "kat_navn"

    dim_names = ", ".join(f"dim_{i}" for i in range(n_dims))
    dim_select_outer = (dim_names + ", ") if dims else ""
    group_by = ", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"
    order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1)) if dims else "1"

    sql = f"""
        WITH exploded AS ({exploded_sql})
        SELECT {dim_select_outer}{value_expr} AS asjc_value, COUNT(DISTINCT PURE_ID) AS n
        FROM exploded
        WHERE 1=1 {restrict_sql}
        GROUP BY {group_by}
        ORDER BY {order_by_sql}
    """
    rows = get_cursor().execute(sql, base_params + restrict_params).fetchall()

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
        ku_sql = f"""
            WITH exploded AS ({exploded_sql})
            SELECT {value_expr} AS asjc_value, COUNT(DISTINCT PURE_ID) AS n
            FROM exploded
            WHERE 1=1 {restrict_sql}
            GROUP BY 1
        """
        ku_rows = get_cursor().execute(ku_sql, base_params + restrict_params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}

    return result, cluster_map

def _asjc_pct_denominators(filters):
    """Antal ALLE distinkte publikationer pr. enhed, uafhængigt af ASJC-status
    - bruges som nævner til 'Andel (%)' på alle tre niveauer (domæne, felt,
    kategori), så et tal direkte kan læses som 'X% af enhedens publikationer
    i alt'. Bemærk: publikationer uden nogen ASJC-klassifikation tæller
    stadig med i nævneren, men kan aldrig optræde i nogen tæller - lav
    ASJC-dækning trækker derfor alle procenttal nedad."""
    data, _ = _query_topic_section(filters, "'Alle'")
    return {unit: sum(cats.values()) for unit, cats in data.items()}

@st.cache_data
def _query_category_year_trend(filters, category_sql, category_value, extra_filter_sql="1=1", extra_filter_params=()):
    """
    Antal publikationer år for år for ÉN specifik, allerede klikket
    kategoriværdi - brudt ned på PRÆCIS det organisatoriske niveau, du har
    valgt i sidepanelet (Fak, Inst, eller begge) - samme princip som resten
    af fanens søjlediagrammer, ingen kunstig begrænsning til kun fakultet.
    Vælger du intet i sidepanelet, vises kun 'KU samlet'. Ignorerer bevidst
    sidepanelets årsinterval, samme princip som appens øvrige 'over
    tid'-sektioner.
    """
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(filters.get("mode", "F"))
    n_dims = len(dims)
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    dim_select = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""

    sql = f"""
        SELECT {dim_select}Year, COUNT(DISTINCT PURE_ID) AS n
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
          AND Year IS NOT NULL
          AND ({ac_sql})
          AND ({extra_filter_sql})
          AND ({category_sql}) = ?
        GROUP BY {", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"}
        ORDER BY {n_dims + 1 if dims else 1}
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        ac_params + list(extra_filter_params) + [category_value]
    )
    rows = get_cursor().execute(sql, params).fetchall()

    by_year_unit = {}
    for row in rows:
        dim_values = row[:n_dims]
        year = row[n_dims]
        n = row[n_dims + 1]
        unit_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        by_year_unit.setdefault(year, {})[unit_label] = n

    if filters.get("mode", "F") == "F" and not filters.get("fakultet_explicit", False):
        ku_sql = f"""
            SELECT Year, COUNT(DISTINCT PURE_ID) AS n
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
              AND Year IS NOT NULL
              AND ({ac_sql})
              AND ({extra_filter_sql})
              AND ({category_sql}) = ?
            GROUP BY 1
        """
        ku_params = (
            filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
            filters['typer'] + filters['sprog'] + filters['peer'] +
            filters['indholdstyper'] + filters['open_access'] +
            ac_params + list(extra_filter_params) + [category_value]
        )
        ku_rows = get_cursor().execute(ku_sql, ku_params).fetchall()
        merged = {year: {"KU samlet": n} for year, n in ku_rows}
        return merged

    return by_year_unit


@st.cache_data
def _query_asjc_category_year_trend(filters, level, category_value, restrict_domain=None, restrict_field_abbr=None):
    """Samme princip som _query_category_year_trend (respekterer sidepanelets
    reelle organisatoriske niveau, inkl. institut), men til ASJC's
    flerværdi-felter."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(filters.get("mode", "F"))
    n_dims = len(dims)
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    #dim_select = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""
    dim_select_inner = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""
    dim_select_outer = (", ".join(f"dim_{i}" for i in range(n_dims)) + ", ") if dims else ""

    base_where = f"""
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
          AND Year IS NOT NULL
          AND ({ac_sql})
          AND ASJC_felter IS NOT NULL AND ASJC_felter != ''
    """
    base_params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )

    domain_case = _case_expr("felt_abbr", _ASJC_FIELD_TO_DOMAIN)
    field_case = _case_expr("felt_abbr", _ASJC_FIELD_NAMES)
    value_expr = domain_case if level == "domain" else field_case

    restrict_sql, restrict_params = "", []
    if restrict_domain:
        restrict_sql = f"AND {domain_case} = ?"
        restrict_params = [restrict_domain]
    elif restrict_field_abbr:
        restrict_sql = "AND felt_abbr = ?"
        restrict_params = [restrict_field_abbr]

    sql = f"""
        WITH exploded AS (
            SELECT {dim_select_inner}Year, PURE_ID, TRIM(UNNEST(STRING_SPLIT(ASJC_felter, '|'))) AS felt_abbr
            FROM pubs
            {base_where}
        )
        SELECT {dim_select_outer}Year, COUNT(DISTINCT PURE_ID) AS n
        FROM exploded
        WHERE {value_expr} = ? {restrict_sql}
        GROUP BY {", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"}
        ORDER BY {n_dims + 1 if dims else 1}
    """
    params = base_params + [category_value] + restrict_params
    rows = get_cursor().execute(sql, params).fetchall()

    by_year_unit = {}
    for row in rows:
        dim_values = row[:n_dims]
        year = row[n_dims]
        n = row[n_dims + 1]
        unit_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        by_year_unit.setdefault(year, {})[unit_label] = n

    if filters.get("mode", "F") == "F" and not filters.get("fakultet_explicit", False):
        ku_sql = f"""
            WITH exploded AS (
                SELECT Year, PURE_ID, TRIM(UNNEST(STRING_SPLIT(ASJC_felter, '|'))) AS felt_abbr
                FROM pubs
                {base_where}
            )
            SELECT Year, COUNT(DISTINCT PURE_ID) AS n
            FROM exploded
            WHERE {value_expr} = ? {restrict_sql}
            GROUP BY 1
        """
        ku_params = base_params + [category_value] + restrict_params
        ku_rows = get_cursor().execute(ku_sql, ku_params).fetchall()
        merged = {year: {"KU samlet": n} for year, n in ku_rows}
        return merged

    return by_year_unit


def _render_category_trend(trend_data, label, key_suffix, chart_mode="antal", year_totals=None):
    """
    Historik-graf under et klikket niveau - én linje pr. organisatorisk
    enhed, matchende sidepanelets aktuelle niveau. chart_mode styrer om
    y-aksen viser rå antal eller andel af enhedens samlede publikationer
    det år (kræver year_totals fra _query_org_year_totals).
    """
    if not trend_data:
        return
    years_sorted = sorted(trend_data.keys())
    units = sorted({u for cats in trend_data.values() for u in cats}, key=lambda u: (u != "KU samlet", u))

    faculty_colors = build_faculty_colors()

    totals = {}
    for cats in trend_data.values():
        for u, n in cats.items():
            totals[u] = totals.get(u, 0) + n

    colors = {}
    for u in units:
        if u == "KU samlet":
            colors[u] = "#666666"
        elif u in FAC_ORDER:
            colors[u] = faculty_colors.get(u, "#666666")

    # Institut-niveau ("Institut | Fakultet"): knækkede nuancer af moderfakultetets
    # farve, samme opskrift som treemap'et - grupperet pr. fakultet, størst institut
    # (efter samlet volumen) får den mørkeste/mest "rene" nuance.
    inst_units = [u for u in units if u not in colors]
    by_faculty = {}
    for u in inst_units:
        parts = u.split(" | ")
        parent_fak = parts[-1] if len(parts) > 1 else None
        by_faculty.setdefault(parent_fak, []).append(u)

    for parent_fak, insts in by_faculty.items():
        insts_sorted = sorted(insts, key=lambda u: -totals.get(u, 0))
        base = faculty_colors.get(parent_fak)
        if base:
            shades = _hls_gradient(base, len(insts_sorted))
            for i, u in enumerate(insts_sorted):
                colors[u] = shades[i]
        else:
            fallback = ku_color_sequence(len(insts_sorted))
            for i, u in enumerate(insts_sorted):
                colors[u] = fallback[i]

    fig = go.Figure()
    for unit in units:
        raw_vals = [trend_data.get(year, {}).get(unit, 0) for year in years_sorted]
        if chart_mode == "pct" and year_totals:
            y_vals = [
                round(100 * raw / year_totals.get(year, {}).get(unit, 1), 1) if year_totals.get(year, {}).get(unit, 0) > 0 else 0
                for raw, year in zip(raw_vals, years_sorted)
            ]
            hover_suffix = "%{customdata[0]:.1f}%<br>%{customdata[1]:,} publikationer"
            customdata = list(zip(y_vals, raw_vals))
        else:
            y_vals = raw_vals
            hover_suffix = "%{y:,} publikationer"
            customdata = None

        fig.add_trace(go.Scatter(
            x=years_sorted, y=y_vals, mode="lines+markers", name=unit,
            line=dict(color=colors.get(unit, "#666666"), width=3 if unit == "KU samlet" else 2),
            marker=dict(size=6),
            customdata=customdata,
            hovertemplate=f"<b>{unit}</b><br>%{{x}}<br>{hover_suffix}<extra></extra>",
        ))
    fig.update_layout(
        title=dict(text=f"{label} over tid (hele perioden)", font=dict(size=14)),
        xaxis=dict(title="Udgivelsesår", dtick=1),
        yaxis=dict(
            title="Andel af publikationer (%)" if chart_mode == "pct" else "Antal publikationer",
            range=[0, 100] if chart_mode == "pct" else None,
        ),
        plot_bgcolor="white", height=380,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(t=50, b=10, l=10, r=150),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"trend_chart_{key_suffix}")

    if units == ["KU samlet"]:
        st.caption(
            "Viser KU samlet, fordi intet fakultet/institut er valgt i sidepanelet - "
            "vælg et eller flere for at se udviklingen for specifikke organisatoriske niveauer."
        )


@st.cache_data
def _query_org_year_totals(filters):
    """Totalt antal publikationer år for år, pr. organisatorisk enhed
    (matchende sidepanelets niveau) - INGEN kategori-restriktion. Bruges
    som nævner til historik-plottets Andel (%)-tilstand."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(filters.get("mode", "F"))
    n_dims = len(dims)
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    dim_select = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""

    sql = f"""
        SELECT {dim_select}Year, COUNT(DISTINCT PURE_ID) AS n
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
          AND Year IS NOT NULL
          AND ({ac_sql})
        GROUP BY {", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"}
        ORDER BY {n_dims + 1 if dims else 1}
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()

    by_year_unit = {}
    for row in rows:
        dim_values = row[:n_dims]
        year = row[n_dims]
        n = row[n_dims + 1]
        unit_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        by_year_unit.setdefault(year, {})[unit_label] = n

    if filters.get("mode", "F") == "F" and not filters.get("fakultet_explicit", False):
        ku_sql = f"""
            SELECT Year, COUNT(DISTINCT PURE_ID) AS n
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
              AND Year IS NOT NULL
              AND ({ac_sql})
            GROUP BY 1
        """
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        merged = {year: {"KU samlet": n} for year, n in ku_rows}
        return merged

    return by_year_unit

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
    "topic_cluster": ["sv_topic"],
    "asjc_domain": ["asjc_field"],
    "asjc_field": ["asjc_category"],
}
_LEVEL_WIDGET_SUFFIXES = {
    "field": ["field_antal", "field_pct"],
    "subfield": ["subfield_antal", "subfield_pct"],
    "topic": ["topic_antal", "topic_pct"],
    "sv_topic": ["sv_topic_antal", "sv_topic_pct"],
    "asjc_field": ["asjc_field"],
    "asjc_category": ["asjc_category"],
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

@st.cache_data
def _load_scival_reference_table(kind: str):
    """Indlæser de lokalt byggede opslagstabeller (build_scival_reference_tables.py)
    direkte via DuckDB, som en PyArrow-tabel - IKKE pandas, og IKKE noget
    SciVal selv stiller til rådighed, men afledt af KU's egne, allerede
    indsamlede publikationer. Returnerer None, hvis filen ikke findes endnu."""
    key = "scival_topics" if kind == "topics" else "scival_asjc"
    path = REFERENCE_TABLE_PATHS[key]
    if not Path(path).exists():
        return None
    return duckdb.connect().execute(f"SELECT * FROM read_parquet('{path}')").fetch_arrow_table()


def _render_topic_section(filters, dim_col, category_sql, title_prefix, chart_mode="antal", top_x=None,
                           clickable=False, key_suffix="", level_key="", extra_filter_sql="1=1", extra_filter_params=(),
                           use_domain_colors=True, base_color=None):
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

    pct_denominators = {unit: sum(cats.values()) for unit, cats in org_data.items()}

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
    if base_color:
        # Bruges til fx SciVal Topics under en Topic Cluster: knækkede
        # nuancer af MODERENS egen (allerede tildelte) farve, i stedet for
        # en fast domænefarve, som SciVal ikke selv har.
        real_keys = [k for k in order if k != ANDET_LABEL]
        shades = _hls_gradient(base_color, len(real_keys))
        colors = {k: shades[i] for i, k in enumerate(real_keys)}
        if ANDET_LABEL in order:
            colors[ANDET_LABEL] = "#cccccc"
    elif not use_domain_colors:
        real_keys = [k for k in order if k != ANDET_LABEL]
        palette = ku_color_sequence(len(real_keys))
        colors = {k: palette[i] for i, k in enumerate(real_keys)}
        if ANDET_LABEL in order:
            colors[ANDET_LABEL] = "#cccccc"
    elif dim_col == "Domain":
        colors = {k: _DOMAIN_COLORS.get(k, "#666666") for k in order}
    else:
        dim_domain_map = _query_dim_domain_map(filters, dim_col, extra_filter_sql, extra_filter_params)
        real_keys = [k for k in order if k != ANDET_LABEL]
        colors = domain_shaded_colors(real_keys, dim_domain_map, totals)
        if ANDET_LABEL in order:
            colors[ANDET_LABEL] = "#cccccc"

    st.session_state[f"_colors_{key_suffix}"] = colors  # gemmes så et barneniveaus base_color kan slå moderens farve op

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
        pct_denominators=pct_denominators,
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

def _render_asjc_section(filters, level, title_prefix, top_x=None, clickable=False, key_suffix="",
                          level_key="", restrict_domain=None, restrict_field_abbr=None):
    data, cluster_map = _query_asjc_section(filters, level, restrict_domain=restrict_domain, restrict_field_abbr=restrict_field_abbr)
    if not any(data.values()):
        st.error("Ingen publikationer matcher de valgte filtre.")
        return None

    pct_denominators = _asjc_pct_denominators(filters)

    full_data = data
    totals = {}
    for cats in data.values():
        for k, n in cats.items():
            totals[k] = totals.get(k, 0) + n

    order = None
    if top_x:
        data, order, _ = _apply_top_x(data, top_x, always_keep=["Ukendt"])
    if order is None:
        order = sorted(totals, key=lambda k: -totals[k])

    real_keys = [k for k in order if k != ANDET_LABEL]
    if level == "domain":
        colors = {k: _DOMAIN_COLORS.get(k, "#666666") for k in order}
    elif level == "field":
        dim_domain_map = {k: _ASJC_FIELD_NAME_TO_DOMAIN.get(k, "Ukendt") for k in real_keys}
        colors = domain_shaded_colors(real_keys, dim_domain_map, totals)
    else:  # category - alt under det klikkede felt hører til SAMME domæne
        dom = restrict_field_abbr and _ASJC_FIELD_TO_DOMAIN.get(restrict_field_abbr, "Ukendt") or "Ukendt"
        dim_domain_map = {k: dom for k in real_keys}
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
        xaxis_title="Andel (%)", mode="pct",
        group_keys=group_keys, legend_position="right",
        pct_denominators=pct_denominators,
    )

    if clickable:
        widget_key = f"asjc_chart_{key_suffix}"
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
        filename=f"{_slugify(title_prefix)}_asjc.xlsx",
        sheet_name=title_prefix[:31],
        key=f"export_asjc_{_slugify(title_prefix)}_{key_suffix}",
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

Fanen kortlægger KU's faglige profil på baggrund af publikationernes emneområder. Klassifikationen
afhænger af den valgte datakilde i sidepanelet: OpenAlex og SciVal tilbyder begge et hierarki
(fra brede domæner til specifikke emner), men CURIS' egen klassifikation ('Hovedområde') er langt
grovere - kun fire kategorier, inden underinddeling - men til gengæld dækker den alle publikationer, 
uafhængigt af DOI-matchning.
""")

    data_source = filters.get("data_source", "CURIS")

    if data_source == "CURIS":
        
        with st.expander("Sådan klassificerer CURIS hovedområder"):
            st.markdown(
"""
CURIS' fire hovedområder blev fastlagt, da CURIS blev sat op: hvert fakultet fik dengang 
tildelt **ét** af de fire områder - og alle underliggende enheder arvede det samme 
hovedområde. 

De fire hovedområder er: 

- Humanities (HUM og TEO)
- Social sciences (SAMF og JUR)
- Health sciences (SUND)
- Technical/neutral sciences (SCIENCE)

**En metodisk svaghed, som er værd at bemærke, inden tallene bruges**: en publikation
tildeles sit hovedområde ud fra **førsteforfatterens** organisatoriske tilknytning - ikke 
ud fra publikationens faktiske emne, og ikke ud fra en samlet vurdering af alle medforfattere.

**Eksempel**: Skriver en kemiker ('Tecnical/natural sciences') en artikel sammen med to 
forfattere fra Biomedicinsk Institut ('Health sciences'), bliver hele publikationen 
tildelt **'Technical/natural sciences'**, selvom det faglige indhold måske ligger tættere 
på 'Health sciences' - udelukkende fordi kemikeren er førsteforfatter. Havde forfatterrækkefølgen
væres anderledes, ville samme publikation være blevet tildelt 'Health sciences' i stedet.

Denne begrænsning gælder **alle** tværfaglige publikationer - og bør derfor snarere læses som
*hvilket område førsteforfatteren organisatorisk hører under*, ikke som en pålidelig
indikator for selve forskningsemnet. 
"""
            )


        st.markdown(
"""
##### Hovedområder 

Fordelingen er opgjort på tværs af de valgte organisatoriske niveauer. Da hver publikation
kun har ét Hovedområde, summerer andelene her altid til 100%.

**Eksempel**: 70 % 'Health sciences' for SUND betyder, at 70 % af SUND's publikationer i alt
er klassificeret under det hovedområde.
"""
        )

        _tab_ho_n, _tab_ho_p = st.tabs(["Antal", "Andel (%)"])
        with _tab_ho_n:
            _render_topic_section(
                filters, "Hovedomraade_en", "COALESCE(Hovedomraade_en, 'Ukendt')", "Hovedområde",
                chart_mode="antal", clickable=True, key_suffix="hovedomraade_antal",
                level_key="hovedomraade", use_domain_colors=False,
            )
            _clicked_hovedomraade_n = st.session_state.get("_resolved_hovedomraade")
            if _clicked_hovedomraade_n:
                _trend = _query_category_year_trend(filters, "COALESCE(Hovedomraade_en, 'Ukendt')", _clicked_hovedomraade_n)
                _render_category_trend(_trend, _clicked_hovedomraade_n, key_suffix="hovedomraade_trend_antal", chart_mode="antal")
        with _tab_ho_p:
            _render_topic_section(
                filters, "Hovedomraade_en", "COALESCE(Hovedomraade_en, 'Ukendt')", "Hovedområde",
                chart_mode="pct", clickable=True, key_suffix="hovedomraade_pct",
                level_key="hovedomraade", use_domain_colors=False,
            )
            _clicked_hovedomraade_p = st.session_state.get("_resolved_hovedomraade")
            if _clicked_hovedomraade_p:
                _trend = _query_category_year_trend(filters, "COALESCE(Hovedomraade_en, 'Ukendt')", _clicked_hovedomraade_p)
                _trend_totals = _query_org_year_totals(filters)
                _render_category_trend(_trend, _clicked_hovedomraade_p, key_suffix="hovedomraade_trend_pct", chart_mode="pct", year_totals=_trend_totals)

        return
    
    if data_source == "OpenAlex":
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

**Eksempel**: Emnet *International Maritime Law Issues* hører under underfeltet
*Management, Monitoring, Policy, and Law*, feltet *Environmental Science* og 
domænet *Physical Sciences*. ([CNRS' OpenAlex-brugerguide](https://www.science-ouverte.cnrs.fr/wp-content/uploads/2026/02/20260209_OpenAlex_Discovery-User-Guide_CNRS_2026.pdf))

**Sådan bygges og tildeles emnerne**

Selve emnetaksonomien (de 4500 kategorier) er bygget ud fra 71 millioner
OpenAlex-publikationer udgivet 2000-2023 og forbundet af 1.7 milliarder citationslinks. 
Klyngedannelsen bygger udelukkende på disse citationsforbindelser - ikke på 
abstracts eller en sprogmodel. Senere har hver klynge fået et navn ved
brug af en sprogmodel, som kun så titlerne på de 250 mest citerede publikationer
i hver klynge. ([Analyse af navngivningstrinnet](https://arxiv.org/pdf/2510.14303))

Publikationernes abstract kommer først i spil i det næste trin: når en konkret
publikation skal have tildelt sit emne, bruger en trænet klassifikationsmodel titel, 
abstract og citationer som input - så selv publikationer
uden citationer kan klassificeres. ([Analyse af klassifikationsmodellen](https://arxiv.org/pdf/2408.04163))
"""
            )

            #st.markdown(
               # f'<div style="max-width:700px; margin:auto;">{load_figur_svg("fig_OpenAlex_topics.svg")}</div>',
                   # unsafe_allow_html=True,
            #)
        
        with st.expander("Se opslagstabel"):
            st.markdown(
"""
Denne tabel stilles **til rådighed af OpenAlex selv**, i modsætning til de tilsvarende
SciVal/ASJC-tabeller andetsteds i denne fane, som er bygget lokalt ud fra KU's egne data.
Det betyder også, at den er **udtømmende**: hele taksonomien - alle domæner, felter,
underfelter og emner, der findes i OpenAlex globalt, ikke kun dem der forekommer i KU's
publikationer - med tilhørende nøgleord, en kort beskrivelse og et Wikipedia-link per emne,
kan slås op i
[OpenAlex' fulde emne-opslagstabel](https://docs.google.com/spreadsheets/d/1v-MAq64x4YjhO7RWcB-yrKV5D_2vOOsxl4u6GBKEXY8/edit?gid=983250122#gid=983250122).
"""
            )

        st.markdown(
"""
---

##### Domæner

Figuren nedenfor viser den bredeste inddeling; klik på en søjle for at zoome ind på dens felter, 
og videre ned gennem underfelter til specifikke emner. Hvert niveau kan brydes ned på de organisatoriske 
niveauer, du har valgt i sidepanelet - f.eks. to fakulteter samtidig, så du direkte kan sammenligne
deres faglige profil. 

**Eksempel**: 60 % Health Sciences for SUND betyder, at 60 % af SUND's publikationer er klassificeret under 
det domæne. 
""")

        _TOPX_DEFAULT = 10

        # --- Domæne ---
        _tab_dom_n, _tab_dom_p = st.tabs(["Antal", "Andel (%)"])
        with _tab_dom_n:
            _render_topic_section(
                filters, "Domain", "COALESCE(Domain, 'Ukendt')", "Domæne",
                chart_mode="antal", clickable=True, key_suffix="domain_antal", level_key="domain",
            )
            _clicked_domain_n = st.session_state.get("_resolved_domain")
            if _clicked_domain_n:
                _trend = _query_category_year_trend(filters, "COALESCE(Domain, 'Ukendt')", _clicked_domain_n)
                _render_category_trend(_trend, _clicked_domain_n, key_suffix="domain_trend_antal", chart_mode="antal")
        with _tab_dom_p:
            _render_topic_section(
                filters, "Domain", "COALESCE(Domain, 'Ukendt')", "Domæne",
                chart_mode="pct", clickable=True, key_suffix="domain_pct", level_key="domain",
            )
            _clicked_domain_p = st.session_state.get("_resolved_domain")
            if _clicked_domain_p:
                _trend = _query_category_year_trend(filters, "COALESCE(Domain, 'Ukendt')", _clicked_domain_p)
                _trend_totals = _query_org_year_totals(filters)
                _render_category_trend(_trend, _clicked_domain_p, key_suffix="domain_trend_pct", chart_mode="pct", year_totals=_trend_totals)
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
                _clicked_field_n = st.session_state.get("_resolved_field")
                if _clicked_field_n:
                    _trend = _query_category_year_trend(filters, "COALESCE(Field, 'Ukendt')", _clicked_field_n, extra_filter_sql=_field_extra_sql, extra_filter_params=_field_extra_params)
                    _render_category_trend(_trend, _clicked_field_n, key_suffix="field_trend_antal", chart_mode="antal")
            with _tab_field_p:
                _render_topic_section(
                    filters, "Field", "COALESCE(Field, 'Ukendt')", f"Felt under {_clicked_domain}",
                    chart_mode="pct", clickable=True, key_suffix="field_pct", level_key="field",
                    extra_filter_sql=_field_extra_sql, extra_filter_params=_field_extra_params,
                )
                _clicked_field_p = st.session_state.get("_resolved_field")
                if _clicked_field_p:
                    _trend = _query_category_year_trend(filters, "COALESCE(Field, 'Ukendt')", _clicked_field_p, extra_filter_sql=_field_extra_sql, extra_filter_params=_field_extra_params)
                    _trend_totals = _query_org_year_totals(filters)
                    _render_category_trend(_trend, _clicked_field_p, key_suffix="field_trend_pct", chart_mode="pct", year_totals=_trend_totals)
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
                    _clicked_subfield_n = st.session_state.get("_resolved_subfield")
                    if _clicked_subfield_n:
                        _trend = _query_category_year_trend(filters, "COALESCE(Subfield, 'Ukendt')", _clicked_subfield_n, extra_filter_sql=_subfield_extra_sql, extra_filter_params=_subfield_extra_params)
                        _render_category_trend(_trend, _clicked_subfield_n, key_suffix="subfield_trend_antal", chart_mode="antal")
                with _tab_sub_p:
                    _render_topic_section(
                        filters, "Subfield", "COALESCE(Subfield, 'Ukendt')", f"Underfelt under {_clicked_field}",
                        chart_mode="pct", top_x=_topx_subfield, clickable=True, key_suffix="subfield_pct", level_key="subfield",
                        extra_filter_sql=_subfield_extra_sql, extra_filter_params=_subfield_extra_params,
                    )
                    _clicked_subfield_p = st.session_state.get("_resolved_subfield")
                    if _clicked_subfield_p:
                        _trend = _query_category_year_trend(filters, "COALESCE(Subfield, 'Ukendt')", _clicked_subfield_p, extra_filter_sql=_subfield_extra_sql, extra_filter_params=_subfield_extra_params)
                        _trend_totals = _query_org_year_totals(filters)
                        _render_category_trend(_trend, _clicked_subfield_p, key_suffix="subfield_trend_pct", chart_mode="pct", year_totals=_trend_totals)
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
                            chart_mode="antal", top_x=_topx_topic, clickable=True, key_suffix="topic_antal", level_key="topic",
                            extra_filter_sql=_topic_extra_sql, extra_filter_params=_topic_extra_params,
                        )
                        _clicked_topic_n = st.session_state.get("_resolved_topic")
                        if _clicked_topic_n:
                            _trend = _query_category_year_trend(filters, "COALESCE(Topic, 'Ukendt')", _clicked_topic_n, extra_filter_sql=_topic_extra_sql, extra_filter_params=_topic_extra_params)
                            _render_category_trend(_trend, _clicked_topic_n, key_suffix="topic_trend_antal", chart_mode="antal")
                    with _tab_topic_p:
                        _render_topic_section(
                            filters, "Topic", "COALESCE(Topic, 'Ukendt')", f"Emne under {_clicked_subfield}",
                            chart_mode="pct", top_x=_topx_topic, clickable=True, key_suffix="topic_pct", level_key="topic",
                            extra_filter_sql=_topic_extra_sql, extra_filter_params=_topic_extra_params,
                        )
                        _clicked_topic_p = st.session_state.get("_resolved_topic")
                        if _clicked_topic_p:
                            _trend = _query_category_year_trend(filters, "COALESCE(Topic, 'Ukendt')", _clicked_topic_p, extra_filter_sql=_topic_extra_sql, extra_filter_params=_topic_extra_params)
                            _trend_totals = _query_org_year_totals(filters)
                            _render_category_trend(_trend, _clicked_topic_p, key_suffix="topic_trend_pct", chart_mode="pct", year_totals=_trend_totals)


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
Prominence for hvert topic kan ses i opslagstabellen.

**Alternativ: ASJC-klassifikation**

Som et alternativ til Topic/Topic Clusters kan fordelingen også vises efter
tidsskrifternes emneklassifikation: Scopus' All Science Journal Classification
(ASJC). Det er et hierarki - fire brede fagområder (*Life Science*, 
*Physical Science*, *Health Science* og *Social Sciences and Humanities*), opdelt i 27 hovedfelter og
videre ud i 334 kategorier - som Elsevier-eksperter manuelt tildeler det enkelte
tidsskrift ud fra dets formål og indhold, når det optaget i Scopus. 
([Scopus subject area categories and ASJC codes](https://service.elsevier.com/app/answers/detail/a_id/12007/supporthub/scopus/))

Den afgørende forskel til Topics: ASJC klassificerer hele tidsskriftet, ikke den 
enkelte artikel. Alle artikler i samme tidsskrift får dermed samme ASJC-kode(r), 
uanset hvad den konkrete artikel faktisk handler om - modsat Topics, der er 
publikationsspecifikke og opdateres dynamisk ud fra artiklens egne referencer. 
Et tidsskrift kan desuden have flere ASJC-koder, hvis det dækker flere
fagområder. 
([SciVal LibGuide](https://elsevier.libguides.com/c.php?g=1328583&p=9781974))
"""
            )

        _sv_visning = st.radio(
            "Vis emnefordeling efter:",
            options=["Topics og Topic Clusters", "ASJC-klassifikation"],
            index=0, horizontal=True, key="scival_emnevisning",
        )

        if _sv_visning == "Topics og Topic Clusters":
            _topics_ref = _load_scival_reference_table("topics")
            if _topics_ref is not None:
                with st.expander("Se opslagstabel"):
                    st.markdown(
"""
Denne tabel stilles **ikke til rådighed af SciVal selv** - den er bygget lokalt ud fra
KU's egne, allerede indsamlede publikationer, og viser derfor kun de værdier, der faktisk
forekommer i data, ikke en global, udtømmende liste. 
"""
                    )
                    st.dataframe(_topics_ref, width="stretch", hide_index=True)
                    st.caption("Prominence måler aktuel opmærksomhed, **ikke** kvalitet eller vigtighed.")

            st.markdown(
"""
---

##### Topic Clusters

Topic Cluster-figuren nedenfor viser den bredeste inddeling: klik på en søjle for at 
zoome ind på dens Topics. Hver niveau brydes ned på de organisatoriske niveauer, du 
har valgt i sidepanelet.

**Eksempel**: 45 % 'Cancer Biology' for Sund betyder, at 45 % af SUND's publikationer hører under det
Topic Cluster. Da hver publikation kun hører til ét Topic (og dermed ét Topic Cluster), summerer andelene her
altid til 100 %. 
"""
            )

            _max_tc = _count_categories(filters, "COALESCE(Topic_cluster, 'Ukendt')")
            _topx_tc = st.number_input(
                "Vis top-X Topic Clusters (resten samles i 'Andet')",
                min_value=1, max_value=_max_tc, value=min(10, _max_tc), step=1, key="topx_topic_cluster",
            )

            _tab_tc_n, _tab_tc_p = st.tabs(["Antal", "Andel (%)"])
            with _tab_tc_n:
                _render_topic_section(
                    filters, "Topic_cluster", "COALESCE(Topic_cluster, 'Ukendt')", "Topic Cluster",
                    chart_mode="antal", top_x=_topx_tc, clickable=True, key_suffix="tc_antal", level_key="topic_cluster",
                    use_domain_colors=False,
                )
                _clicked_tc_n = st.session_state.get("_resolved_topic_cluster")
                if _clicked_tc_n:
                    _trend = _query_category_year_trend(filters, "COALESCE(Topic_cluster, 'Ukendt')", _clicked_tc_n)
                    _render_category_trend(_trend, _clicked_tc_n, key_suffix="tc_trend_antal", chart_mode="antal")
            with _tab_tc_p:
                _render_topic_section(
                    filters, "Topic_cluster", "COALESCE(Topic_cluster, 'Ukendt')", "Topic Cluster",
                    chart_mode="pct", top_x=_topx_tc, clickable=True, key_suffix="tc_pct", level_key="topic_cluster",
                    use_domain_colors=False,
                )
                _clicked_tc_p = st.session_state.get("_resolved_topic_cluster")
                if _clicked_tc_p:
                    _trend = _query_category_year_trend(filters, "COALESCE(Topic_cluster, 'Ukendt')", _clicked_tc_p)
                    _trend_totals = _query_org_year_totals(filters)
                    _render_category_trend(_trend, _clicked_tc_p, key_suffix="tc_trend_pct", chart_mode="pct", year_totals=_trend_totals)
            _clicked_tc = st.session_state.get("_resolved_topic_cluster")

            if not _clicked_tc:
                st.caption("Klik på en Topic Cluster i figuren ovenfor for at zoome ind på dens Topics.")
            else:
                st.markdown(f"---\n##### Topics under *{_clicked_tc}*")
                _tc_color = st.session_state.get("_colors_tc_antal", {}).get(_clicked_tc, "#666666")

                _sv_topic_extra_sql = "Topic_cluster = ?"
                _sv_topic_extra_params = (_clicked_tc,)

                _max_sv_topic = _count_categories(filters, "COALESCE(Topic, 'Ukendt')", _sv_topic_extra_sql, _sv_topic_extra_params)
                _topx_sv_topic = st.number_input(
                    "Vis top-X Topics (resten samles i 'Andet')",
                    min_value=1, max_value=_max_sv_topic, value=min(10, _max_sv_topic), step=1, key="topx_scival_topic",
                )

                _tab_svt_n, _tab_svt_p = st.tabs(["Antal", "Andel (%)"])
                with _tab_svt_n:
                    _render_topic_section(
                        filters, "Topic", "COALESCE(Topic, 'Ukendt')", f"Topic under {_clicked_tc}",
                        chart_mode="antal", top_x=_topx_sv_topic, clickable=True, key_suffix="sv_topic_antal", level_key="sv_topic",
                        extra_filter_sql=_sv_topic_extra_sql, extra_filter_params=_sv_topic_extra_params,
                        base_color=_tc_color,
                    )
                    _clicked_sv_topic_n = st.session_state.get("_resolved_sv_topic")
                    if _clicked_sv_topic_n:
                        _trend = _query_category_year_trend(filters, "COALESCE(Topic, 'Ukendt')", _clicked_sv_topic_n, extra_filter_sql=_sv_topic_extra_sql, extra_filter_params=_sv_topic_extra_params)
                        _render_category_trend(_trend, _clicked_sv_topic_n, key_suffix="sv_topic_trend_antal", chart_mode="antal")
                with _tab_svt_p:
                    _render_topic_section(
                        filters, "Topic", "COALESCE(Topic, 'Ukendt')", f"Topic under {_clicked_tc}",
                        chart_mode="pct", top_x=_topx_sv_topic, clickable=True, key_suffix="sv_topic_pct", level_key="sv_topic",
                        extra_filter_sql=_sv_topic_extra_sql, extra_filter_params=_sv_topic_extra_params,
                        base_color=_tc_color,
                    )
                    _clicked_sv_topic_p = st.session_state.get("_resolved_sv_topic")
                    if _clicked_sv_topic_p:
                        _trend = _query_category_year_trend(filters, "COALESCE(Topic, 'Ukendt')", _clicked_sv_topic_p, extra_filter_sql=_sv_topic_extra_sql, extra_filter_params=_sv_topic_extra_params)
                        _trend_totals = _query_org_year_totals(filters)
                        _render_category_trend(_trend, _clicked_sv_topic_p, key_suffix="sv_topic_trend_pct", chart_mode="pct", year_totals=_trend_totals)

        else:
            
            _asjc_ref = _load_scival_reference_table("asjc")
            if _asjc_ref is not None:
                with st.expander("Se opslagstabel"):
                    st.markdown(
"""
Denne tabel stilles **ikke til rådighed af SciVal selv** - den er bygget lokalt ud fra
KU's egne, allerede indsamlede publikationer, og viser derfor kun de værdier, der faktisk
forekommer i data, ikke en global, udtømmende liste. 
"""
                    )
                    st.dataframe(_asjc_ref, width="stretch", hide_index=True)

            st.markdown(
"""
---

##### Fagområder

Figuren nedenfor viser andelen af publikationer klassificeret under hvert fagområde - klik på en søjle
for at zoome ind på dens hovedfelter, og videre ned til specifikke kategorier. En publikation kan tælle
med under **flere** fagområder/felter/kategorier samtidig, hvis dens tidsskrift dækker mere end ét område -
andelene på hvert niveau summerer derfor ikke nødvendigvis til 100%.

**Eksempel**: Har et tidsskrift ASJC-koder i både Health Sciences og Life Sciences, tæller en publikation heri
med i **begge** kategoriers andel - summen af Health Science (60 %) og Life Sciences (55 %) kan derfor sagtens
overstige 100 %. 
"""
            )

            _render_asjc_section(
                filters, "domain", "Fagområde",
                clickable=True, key_suffix="domain", level_key="asjc_domain",
            )
            _clicked_asjc_domain = st.session_state.get("_resolved_asjc_domain")
            if _clicked_asjc_domain:
                _trend = _query_asjc_category_year_trend(filters, "domain", _clicked_asjc_domain)
                _trend_totals = _query_org_year_totals(filters)
                _render_category_trend(_trend, _clicked_asjc_domain, key_suffix="asjc_domain_trend", chart_mode="pct", year_totals=_trend_totals)

            if not _clicked_asjc_domain:
                st.caption("Klik på et fagområde i figuren ovenfor for at se dets hovedfelter.")
            else:
                st.markdown(f"---\n##### Hovedfelter under *{_clicked_asjc_domain}*")

                _topx_asjc_field = st.number_input(
                    "Vis top-X hovedfelter (resten samles i 'Andet')",
                    min_value=1, max_value=27, value=10, step=1, key="topx_asjc_field",
                )
                _render_asjc_section(
                    filters, "field", f"Hovedfelt under {_clicked_asjc_domain}", top_x=_topx_asjc_field,
                    clickable=True, key_suffix="field", level_key="asjc_field",
                    restrict_domain=_clicked_asjc_domain,
                )
                _clicked_asjc_field = st.session_state.get("_resolved_asjc_field")
                if _clicked_asjc_field:
                    _trend = _query_asjc_category_year_trend(filters, "field", _clicked_asjc_field, restrict_domain=_clicked_asjc_domain)
                    _trend_totals = _query_org_year_totals(filters)
                    _render_category_trend(_trend, _clicked_asjc_field, key_suffix="asjc_field_trend", chart_mode="pct", year_totals=_trend_totals)

                if not _clicked_asjc_field:
                    st.caption("Klik på et hovedfelt i figuren ovenfor for at se dets kategorier.")
                else:
                    st.markdown(f"---\n##### Kategorier under *{_clicked_asjc_field}*")
                    _clicked_field_abbr = next(
                        (a for a, n in _ASJC_FIELD_NAMES.items() if n == _clicked_asjc_field), None
                    )

                    _topx_asjc_cat = st.number_input(
                        "Vis top-X kategorier (resten samles i 'Andet')",
                        min_value=1, max_value=50, value=10, step=1, key="topx_asjc_category",
                    )
                    _render_asjc_section(
                        filters, "category", f"Kategori under {_clicked_asjc_field}", top_x=_topx_asjc_cat,
                        clickable=True, key_suffix="category", level_key="asjc_category", restrict_field_abbr=_clicked_field_abbr,
                    )
                    _clicked_asjc_category = st.session_state.get("_resolved_asjc_category")
                    if _clicked_asjc_category:
                        _trend = _query_asjc_category_year_trend(filters, "category", _clicked_asjc_category, restrict_field_abbr=_clicked_field_abbr)
                        _trend_totals = _query_org_year_totals(filters)
                        _render_category_trend(_trend, _clicked_asjc_category, key_suffix="asjc_category_trend", chart_mode="pct", year_totals=_trend_totals)


