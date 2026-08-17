import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from data.loader import get_cursor
from components.charts import fig_year_trend, PLOTLY_CONFIG
import plotly.graph_objects as go
from config import doi_filter_sql, author_count_filter, hier_cols, show_ku_samlet
from components.colors import build_faculty_colors, ku_color_sequence
from components.charts import fig_year_trend, PLOTLY_CONFIG, _hls_gradient
from components.export import render_table_export
 
def _base_where_and_params(filters, alias=""):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'], alias=alias)
    where_sql = f"""
        WHERE {alias}Intern      = 'Intern'
          AND {alias}Fak         IN ({ph(filters['fakultet'])})
          AND {alias}Inst        IN ({ph(filters['institutter'])})
          AND {alias}Stil        IN ({ph(filters['stillingsgrupper'])})
          AND {alias}Type        IN ({ph(filters['typer'])})
          AND {alias}Sprog       IN ({ph(filters['sprog'])})
          AND {alias}Peer_review IN ({ph(filters['peer'])})
          AND {alias}Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi']).replace('DOI', f'{alias}DOI')})
          AND COALESCE({alias}Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND {alias}Year        BETWEEN ? AND ?
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
def _query_kpis(filters):
    """Nøgletal for det aktuelt filtrerede udsnit - ingen organisatorisk
    nedbrydning, kun samlede tal. Bemærk: 'Andel Open Access' antager, at
    Open_Access-kolonnens 'ikke-åbne' værdier er 'Closed'/'Unknown' -
    værd at bekræfte mod det faktiske værdisæt i data."""
    where_sql, params = _base_where_and_params(filters)

    n_pubs = get_cursor().execute(f"SELECT COUNT(DISTINCT PURE_ID) FROM pubs {where_sql}", params).fetchone()[0]
    n_authors = get_cursor().execute(f"SELECT COUNT(DISTINCT ext_id) FROM pubs {where_sql}", params).fetchone()[0]

    pct_oa = get_cursor().execute(f"""
        SELECT ROUND(100.0 * COUNT(DISTINCT CASE WHEN Open_Access NOT IN ('Closed', 'Unknown') THEN PURE_ID END)
               / NULLIF(COUNT(DISTINCT PURE_ID), 0), 1)
        FROM pubs {where_sql}
    """, params).fetchone()[0]

    pct_peer = get_cursor().execute(f"""
        SELECT ROUND(100.0 * COUNT(DISTINCT CASE WHEN Peer_review = 'Ja' THEN PURE_ID END)
               / NULLIF(COUNT(DISTINCT PURE_ID), 0), 1)
        FROM pubs {where_sql}
    """, params).fetchone()[0]

    return {
        "n_pubs": n_pubs or 0,
        "n_authors": n_authors or 0,
        "pct_oa": pct_oa or 0,
        "pct_peer": pct_peer or 0,
    }


@st.cache_data
def _query_intl_kpis(filters):
    """Andel publikationer med mindst én ekstern medforfatter, og antal
    distinkte samarbejdslande - inden for det aktuelt filtrerede udsnit."""
    where_sql, params = _base_where_and_params(filters, alias="i.")

    total = get_cursor().execute(f"SELECT COUNT(DISTINCT i.PURE_ID) FROM pubs i {where_sql}", params).fetchone()[0]

    intl = get_cursor().execute(f"""
    SELECT COUNT(DISTINCT i.PURE_ID)
    FROM pubs i
    JOIN pubs e ON i.PURE_ID = e.PURE_ID
    {where_sql}
    AND e.Intern = 'Ekstern' AND e.Land != 'Denmark' AND e.Land != 'Danmark'
""", params).fetchone()[0]

    n_lande = get_cursor().execute(f"""
        SELECT COUNT(DISTINCT e.Land)
        FROM pubs i
        JOIN pubs e ON i.PURE_ID = e.PURE_ID
        {where_sql}
        AND e.Intern = 'Ekstern' AND e.Land IS NOT NULL AND e.Land NOT IN ('', 'Unknown')
    """, params).fetchone()[0]

    pct_intl = round(100 * intl / total, 1) if total else 0
    return {"pct_intl": pct_intl, "n_lande": n_lande or 0}

@st.cache_data
def _query_pub_trend(filters):
    """Antal publikationer år for år, brudt ned på PRÆCIS det organisatoriske
    niveau valgt i sidepanelet (Fak/Inst) - samme princip som Forskningsprofils
    historik-grafer. Er intet fakultet valgt, vises kun 'KU samlet' som én
    selvstændig, UDELT optælling (ikke en sum af enkelte fakultets-rækker,
    som ville dobbelttælle tværfakultære publikationer). Ignorerer bevidst
    sidepanelets årsinterval; øvrige filtre respekteres stadig."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(filters.get("mode", "F"))
    n_dims = len(dims)
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    dim_select = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""

    base_where = f"""
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
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )

    sql = f"""
        SELECT {dim_select}Year, COUNT(DISTINCT PURE_ID) AS n
        FROM pubs
        {base_where}
        GROUP BY {", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"}
        ORDER BY {n_dims + 1 if dims else 1}
    """
    rows = get_cursor().execute(sql, params).fetchall()

    by_year_unit = {}
    for row in rows:
        dim_values = row[:n_dims]
        year = row[n_dims]
        n = row[n_dims + 1]
        unit_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        by_year_unit.setdefault(year, {})[unit_label] = n

    if filters.get("mode", "F") == "F" and not filters.get("fakultet_explicit", False):
        ku_sql = f"SELECT Year, COUNT(DISTINCT PURE_ID) AS n FROM pubs {base_where} GROUP BY 1"
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        return {year: {"KU samlet": n} for year, n in ku_rows}

    return by_year_unit

@st.cache_data
def _query_author_trend(filters):
    """Samme princip som _query_pub_trend, men tæller unikke forfattere."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    dims = hier_cols(filters.get("mode", "F"))
    n_dims = len(dims)
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    dim_select = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""

    base_where = f"""
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
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )

    sql = f"""
        SELECT {dim_select}Year, COUNT(DISTINCT ext_id) AS n
        FROM pubs
        {base_where}
        GROUP BY {", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"}
        ORDER BY {n_dims + 1 if dims else 1}
    """
    rows = get_cursor().execute(sql, params).fetchall()

    by_year_unit = {}
    for row in rows:
        dim_values = row[:n_dims]
        year = row[n_dims]
        n = row[n_dims + 1]
        unit_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        by_year_unit.setdefault(year, {})[unit_label] = n

    if filters.get("mode", "F") == "F" and not filters.get("fakultet_explicit", False):
        ku_sql = f"SELECT Year, COUNT(DISTINCT ext_id) AS n FROM pubs {base_where} GROUP BY 1"
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        return {year: {"KU samlet": n} for year, n in ku_rows}

    return by_year_unit

def _render_org_trend(trend_data, title, key_suffix):
    """Linjegraf, én linje pr. organisatorisk enhed (eller 'KU samlet') -
    samme princip som Forskningsprofils historik-grafer: KU-rød for
    'KU samlet', faste fakultetsfarver for navngivne fakulteter, enhedens
    navn indgår i selve hover-teksten."""
    if not trend_data:
        st.error("Ingen data matcher de valgte filtre.")
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
        elif u in faculty_colors:
            colors[u] = faculty_colors[u]

    # Institut-niveau ("Institut | Fakultet"): knækkede nuancer af moderfakultetets
    # farve, samme opskrift som treemap'et og Forskningsprofils historik-grafer.
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
        y_vals = [trend_data.get(year, {}).get(unit, 0) for year in years_sorted]
        fig.add_trace(go.Scatter(
            x=years_sorted, y=y_vals, mode="lines+markers", name=unit,
            line=dict(color=colors.get(unit, "#666666"), width=3 if unit == "KU samlet" else 2),
            marker=dict(size=6),
            hovertemplate=f"<b>{unit}</b><br>%{{x}}<br>%{{y:,}}<extra></extra>",
        ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        xaxis=dict(title="Udgivelsesår", dtick=1),
        yaxis=dict(title="Antal"),
        plot_bgcolor="white", height=420,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(t=50, b=10, l=10, r=150),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"trend_chart_{key_suffix}")

    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År",
        filename=f"{key_suffix}_over_tid.xlsx",
        sheet_name="Udvikling over tid",
        key=f"export_oversigt_{key_suffix}",
    )

def _render_ratio_trend(pub_trend, author_trend, title, key_suffix):
    """Linjegraf: publikationer pr. forfatter, år for år, pr. organisatorisk
    enhed - samme farvelogik (KU-rød/fakultetsfarver/knækkede institutfarver)
    som _render_org_trend, men viser forholdet mellem to allerede hentede
    trend-datasæt i stedet for ét råt antal."""
    years_sorted = sorted(set(pub_trend.keys()) | set(author_trend.keys()))
    units = sorted(
        {u for cats in pub_trend.values() for u in cats} | {u for cats in author_trend.values() for u in cats},
        key=lambda u: (u != "KU samlet", u)
    )
    if not units:
        st.error("Ingen data matcher de valgte filtre.")
        return

    faculty_colors = build_faculty_colors()
    totals = {}
    for cats in pub_trend.values():
        for u, n in cats.items():
            totals[u] = totals.get(u, 0) + n

    colors = {}
    for u in units:
        if u == "KU samlet":
            colors[u] = "#666666"
        elif u in faculty_colors:
            colors[u] = faculty_colors[u]

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

    ratio_data = {}
    fig = go.Figure()
    for unit in units:
        y_vals = []
        for year in years_sorted:
            n_pub = pub_trend.get(year, {}).get(unit, 0)
            n_auth = author_trend.get(year, {}).get(unit, 0)
            ratio = round(n_pub / n_auth, 2) if n_auth else None
            y_vals.append(ratio)
            ratio_data.setdefault(year, {})[unit] = ratio
        fig.add_trace(go.Scatter(
            x=years_sorted, y=y_vals, mode="lines+markers", name=unit,
            line=dict(color=colors.get(unit, "#666666"), width=3 if unit == "KU samlet" else 2),
            marker=dict(size=6),
            hovertemplate=f"<b>{unit}</b><br>%{{x}}<br>%{{y:.2f}} publikationer pr. forfatter<extra></extra>",
        ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        xaxis=dict(title="Udgivelsesår", dtick=1),
        yaxis=dict(title="Publikationer pr. forfatter"),
        plot_bgcolor="white", height=420,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(t=50, b=10, l=10, r=150),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"trend_chart_{key_suffix}")

    render_table_export(
        data={str(year): cats for year, cats in sorted(ratio_data.items())},
        row_label="År",
        filename=f"{key_suffix}_over_tid.xlsx",
        sheet_name="Publikationer pr. forfatter",
        key=f"export_oversigt_{key_suffix}",
    )

def render(filters):
    st.markdown(
""" 
### Oversigt over KU's publikationer

Fanen giver et samlet overblik over publikationsaktiviteten på Københavns Universitet, 
opgjort på tværs af fakulteter, institutter og stillingsgrupper. 

Oversigten beskriver **omfang og fordeling** af KU's publicering, herunder hvor mange
publikationer, der udgives, og hvordan outputtet fordeler sig på organisatoriske enheder.
"""
)

    kpis = _query_kpis(filters)
    intl = _query_intl_kpis(filters)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Publikationer", f"{kpis['n_pubs']:,}")
    c2.metric("Forfattere", f"{kpis['n_authors']:,}", help="Antallet af unikke, udgivne forfattere på KU")
    c3.metric("Åben adgang", f"{kpis['pct_oa']:.1f}%", help="Andelen af publikationer, der er Open Access")
    c4.metric("Internationalt samarbejde", f"{intl['pct_intl']:.1f}%", help="Andelen af publikationer med internationale forfattere")
    c5.metric("Samarbejdslande", f"{intl['n_lande']:,}")

    st.markdown(
"""
**Forfattere** tæller unikke KU-ID'er blandt dem, der har mindst én publikation i den valgte periode - se 
Forfatterprofil for detaljer. **Internationalt samarbejde** angiver andelen af publikationer med mindst én ekstern 
medforfatter fra et andet land end Danmark; danske eksterne samarbejdspartnere (f.eks. andre universiteter eller 
hospitaler) tæller ikke med i dette tal. 

**Eksempel**: er 'Internationalt samarbejde' 35 % betyder det, at 30 % af publikationer har mindst én medforfatter
fra et andet land end Danmark - ikke at 35 % af alle medforfattere er udenlandske. 

---

#### Udvikling over tid

Graferne nedenfor dækker altid hele den tilgængelige periode, uanset sidepanelets valgte årsinterval - 
øvrige filtre gælder stadig, inklusiv valg af fakultet/institut. Er intet valgt i sidepanelet, dækker graferne 
hele KU; er f.eks. kun HUM valgt, viser graferne udelukkende udviklingen for HUM. 
"""
    )

    pub_trend = _query_pub_trend(filters)
    author_trend = _query_author_trend(filters)

    _tab_pub, _tab_auth, _tab_ratio = st.tabs(["Publikationer", "Forfattere", "Publikationer pr. forfatter"])
    with _tab_pub:
        _render_org_trend(pub_trend, "Antal publikationer over tid (hele perioden)", key_suffix="pub")
    with _tab_auth:
        _render_org_trend(author_trend, "Antal forfattere over tid (hele perioden)", key_suffix="auth")
    with _tab_ratio:
        _render_ratio_trend(pub_trend, author_trend, "Publikationer pr. forfatter over tid (hele perioden)", key_suffix="ratio")
    
    st.markdown(
"""
---

#### Se mere i de øvrige faner

Denne fane giver det samlede overblik - vil du grave dybere, kan du gå til:

- **Publikationsformer** - hvordan fordeler outputtet sig på type, sprog, peer review og Open Access?
- **Forfatterprofil** - hvem står bag publikationerne, fordelt på stillingsgruppe og korresponderende
forfatterskab?
- **Diversitet** - hvordan er KU's publicerende forfattere sammensat på tværs af køn og statsborgerskab?
- **Forskningsprofil** - hvad handler KU's forskning om?
- **Citationsimpact** - hvor meget citeres KU's forskning, sammenlignet med resten af verden?
- **Eksternt samarbejde** - hvilke lande samarbejder KU med, og hvor udbredt er det?
- **Sampublicering** - hvor meget samarbejder KU's forskere internt, på tværs af enheder?
- **Datagrundlag** - hvordan hænger datakilderne sammen, og hvor godt dækker de hinanden?

"""
    )
