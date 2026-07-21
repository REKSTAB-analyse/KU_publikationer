import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
from data.loader import get_cursor
from components.charts import fig_hbar_stacked, PLOTLY_CONFIG, _hls_gradient
from components.colors import build_faculty_colors
from components.export import render_table_export
from config import hier_cols, breakdown_label, doi_filter_sql, year_range_label, author_count_filter, show_ku_samlet

_TOP10_COL = {"OpenAlex": "Is_top_10_percent", "SciVal": "In_top_10_percent"}

TOP10_ORDER = ["Top 10%", "Øvrige"]
TOP10_COLORS = {"Top 10%": "#901a1e", "Øvrige": "#122947"}

IMMATURE_YEARS_DEFAULT = 3


def _org_where(filters, alias="", include_year_range=True):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'], alias=alias)
    year_clause = f"AND {alias}Year BETWEEN ? AND ?" if include_year_range else f"AND {alias}Year IS NOT NULL"

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
          {year_clause}
          AND ({ac_sql})
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access']
    )
    if include_year_range:
        params = params + [filters['aar_fra'], filters['aar_til']]
    params = params + ac_params
    return where_sql, params

@st.cache_data
def _query_fwci_by_org(filters, mode):
    """Gennemsnitlig FWCI pr. organisatorisk enhed - tæller DISTINKTE
    publikationer, ikke rå rækker, så en publikation med flere forfattere
    på samme enhed ikke vægtes tungere end en solo-publikation."""
    dims = hier_cols(mode)
    if not dims:
        return {}, {}
    n_dims = len(dims)
    dims_sql = ", ".join(dims)
    where_sql, params = _org_where(filters)

    sql = f"""
        WITH distinct_pubs AS (
            SELECT DISTINCT PURE_ID, {dims_sql}, FWCI
            FROM pubs
            {where_sql}
            AND FWCI IS NOT NULL
        )
        SELECT {dims_sql}, AVG(FWCI) AS mean_fwci, COUNT(*) AS n_pubs
        FROM distinct_pubs
        GROUP BY {dims_sql}
        ORDER BY {dims_sql}
    """
    rows = get_cursor().execute(sql, params).fetchall()

    result, cluster_map = {}, {}
    for row in rows:
        dim_values = row[:n_dims]
        mean_fwci, n_pubs = row[n_dims], row[n_dims + 1]
        dim_label = " | ".join(str(v) for v in reversed(dim_values))
        clusters = tuple(dim_values[:-1]) if n_dims > 1 else None
        result[dim_label] = {"fwci": round(mean_fwci, 2), "n": n_pubs}
        cluster_map[dim_label] = clusters
    
    if mode == "F" and show_ku_samlet(filters):
        ku_sql = f"""
            WITH distinct_pubs AS (
                SELECT DISTINCT PURE_ID, FWCI
                FROM pubs
                {where_sql}
                AND FWCI IS NOT NULL
            )
            SELECT AVG(FWCI), COUNT(*) FROM distinct_pubs
        """
        ku_mean, ku_n = get_cursor().execute(ku_sql, params).fetchone()
        if ku_mean is not None:
            result = {"KU samlet": {"fwci": round(ku_mean, 2), "n": ku_n}, **result}
            cluster_map = {"KU samlet": None, **cluster_map}

    return result, cluster_map

@st.cache_data
def _query_top10_by_org(filters, mode):
    """Andel publikationer i top 10% globalt citerede, pr. enhed - samme
    distinkt-tælling som FWCI-forespørgslen."""
    data_source = filters.get("data_source", "OpenAlex")
    top10_col = _TOP10_COL.get(data_source)
    if not top10_col:
        return {}, {}

    dims = hier_cols(mode)
    if not dims:
        return {}, {}
    dims_sql = ", ".join(dims)
    where_sql, params = _org_where(filters)

    sql = f"""
        WITH distinct_pubs AS (
            SELECT DISTINCT PURE_ID, {dims_sql}, {top10_col} AS is_top10
            FROM pubs
            {where_sql}
            AND {top10_col} IS NOT NULL
        )
        SELECT {dims_sql},
               CASE WHEN is_top10 THEN 'Top 10%' ELSE 'Øvrige' END AS cat,
               COUNT(*) AS n
        FROM distinct_pubs
        GROUP BY {dims_sql}, is_top10
        ORDER BY {dims_sql}
    """
    rows = get_cursor().execute(sql, params).fetchall()

    result, cluster_map = {}, {}
    n_dims = len(dims)
    for row in rows:
        dim_values = row[:n_dims]
        cat = row[n_dims]
        n = row[n_dims + 1]
        dim_label = " | ".join(str(v) for v in reversed(dim_values))
        clusters = tuple(dim_values[:-1]) if n_dims > 1 else None
        result.setdefault(dim_label, {})
        cluster_map[dim_label] = clusters
        result[dim_label][cat] = n
    
    if mode == "F" and show_ku_samlet(filters):
        ku_total = {}
        for dim_data in result.values():
            for cat, n in dim_data.items():
                ku_total[cat] = ku_total.get(cat, 0) + n
        result = {"KU samlet": ku_total, **result}
        cluster_map = {"KU samlet": None, **cluster_map}


    return result, cluster_map

@st.cache_data
def _query_fwci_trend(filters):
    """Gennemsnitlig FWCI år for år for KU samlet (eller det udsnit, der er
    filtreret frem i sidepanelet) - viser altid hele den tilgængelige
    periode, uafhængig af sidepanelets årsinterval. Bruger IKKE mode/dims
    til at bryde ned på enheder; for at se et specifikt fakultet/institut
    isoleret filtreres der i stedet i sidepanelet."""
    where_sql, params = _org_where(filters, include_year_range=False)
    sql = f"""
        WITH distinct_pubs AS (
            SELECT DISTINCT PURE_ID, Year, FWCI
            FROM pubs
            {where_sql}
            AND FWCI IS NOT NULL
        )
        SELECT Year, AVG(FWCI) AS mean_fwci, COUNT(*) AS n_pubs
        FROM distinct_pubs
        GROUP BY Year
        ORDER BY Year
    """
    rows = get_cursor().execute(sql, params).fetchall()
    return {year: {"fwci": round(mean_fwci, 2), "n": n_pubs} for year, mean_fwci, n_pubs in rows}

def _render_fwci_section(filters, mode):
    data, cluster_map = _query_fwci_by_org(filters, mode)
    if not data:
        st.error("Ingen publikationer med FWCI matcher de valgte filtre.")
        return

    wrapped = {unit: {"FWCI": v["fwci"]} for unit, v in data.items()}
    y_labels = list(wrapped.keys())
    if any(v is not None for v in cluster_map.values()):
        group_keys = [
            "__ku__" if lbl == "KU samlet"
            else cluster_map.get(lbl, "__single__")
            for lbl in y_labels
        ]
    else:
        group_keys = None
    
    fig = fig_hbar_stacked(
        data=wrapped, order=["FWCI"], colors={"FWCI": "#901a1e"}, labels={"FWCI": "Gennemsnitlig FWCI"},
        title=f"Gennemsnitlig FWCI, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="FWCI", mode="antal", legend_position="right",
        group_keys=group_keys,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    st.caption("Baseret på antal publikationer med registreret FWCI pr. enhed - se tabellen nedenfor for de præcise antal.")
    render_table_export(
        data={u: {"FWCI": v["fwci"], "Antal publikationer": v["n"]} for u, v in data.items()},
        row_label="Enhed", filename=f"fwci_{mode}.xlsx", sheet_name="FWCI pr. enhed",
        key=f"export_fwci_{mode}",
    )


def _render_top10_section(filters, mode, chart_mode="antal"):
    data, cluster_map = _query_top10_by_org(filters, mode)
    if not any(data.values()):
        st.error("Ingen publikationer med top-10%-data matcher de valgte filtre.")
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
        data=data, order=TOP10_ORDER, colors=TOP10_COLORS,
        title=f"Top 10% citerede publikationer, {breakdown_label(mode)}",
        xaxis_title="Antal publikationer", mode=chart_mode,
        group_keys=group_keys, legend_position="right",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    render_table_export(
        data=data, row_label="Enhed", filename=f"top10_{mode}_{chart_mode}.xlsx",
        sheet_name="Top 10%", key=f"export_top10_{mode}_{chart_mode}",
    )

def _unit_colors(units, mode, totals):
    """
    Farvelægger enheder, så de matcher treemap'ets fakultetsfarver:
    - 'KU samlet' får en fast, neutral farve (indgår ikke i treemap'et selv)
    - Ren F-mode: enhedens egen fakultetsfarve, samme som treemap'ets bokse
    - FI-mode: en nuance af moderfakultetets farve pr. institut, samme
      _hls_gradient-opskrift som treemap'ets institutbokse bruger.
    """
    faculty_colors = build_faculty_colors()
    colors = {}
    if "KU samlet" in units:
        colors["KU samlet"] = "#122947"

    real_units = [u for u in units if u != "KU samlet"]
    if not real_units:
        return colors

    if "I" not in mode:
        for u in real_units:
            colors[u] = faculty_colors.get(u, "#666666")
        return colors

    by_fak = {}
    for u in real_units:
        parts = u.split(" | ")
        fak = parts[-1] if len(parts) > 1 else u
        by_fak.setdefault(fak, []).append(u)

    for fak, insts in by_fak.items():
        base = faculty_colors.get(fak, "#666666")
        insts_sorted = sorted(insts, key=lambda u: -totals.get(u, 0))
        shades = _hls_gradient(base, len(insts_sorted))
        for i, u in enumerate(insts_sorted):
            colors[u] = shades[i]

    return colors


def _render_fwci_trend(filters):
    trend_data = _query_fwci_trend(filters)
    if not trend_data:
        st.error("Ingen publikationer med FWCI matcher de valgte filtre.")
        return

    years_sorted = sorted(trend_data.keys())
    current_year = max(years_sorted)
    cutoff = current_year - IMMATURE_YEARS_DEFAULT

    vis_seneste = st.checkbox(
        f"Vis også de seneste {IMMATURE_YEARS_DEFAULT} år (citationstal er sandsynligvis "
        "endnu ikke fuldt modnet, jf. advarslen ovenfor)",
        value=False, key="fwci_trend_vis_seneste",
    )

    shown_years = years_sorted if vis_seneste else [y for y in years_sorted if y <= cutoff]

    if not shown_years:
        st.warning(
            f"Ingen år tilbage at vise, når de seneste {IMMATURE_YEARS_DEFAULT} år udelades som "
            "standard - kryds boksen ovenfor af, eller udvid det valgte årsinterval i sidepanelet."
        )
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=shown_years,
        y=[trend_data[y]["fwci"] for y in shown_years],
        mode="lines+markers",
        line=dict(color="#901a1e", width=2.5),
        marker=dict(size=6),
        customdata=[trend_data[y]["n"] for y in shown_years],
        hovertemplate="<b>%{x}</b><br>Gennemsnitlig FWCI: %{y:.2f}<br>%{customdata:,} publikationer<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Gennemsnitlig FWCI over tid (hele perioden)", font=dict(size=14)),
        xaxis=dict(title="Udgivelsesår", dtick=1),
        yaxis=dict(title="Gennemsnitlig FWCI"),
        plot_bgcolor="white", height=420,
        margin=dict(t=50, b=50, l=10, r=10),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    render_table_export(
        data={str(y): {"FWCI": v["fwci"], "Antal publikationer": v["n"]} for y, v in trend_data.items()},
        row_label="År", filename="fwci_over_tid.xlsx", sheet_name="FWCI over tid",
        key="export_fwci_trend",
    )
 
def render(filters):
    st.markdown(
f"""
### Citationsimpact

Fanen viser, hvor meget KU's publikationer citeres sammenlignet med det globale
gennemsnit for tilsvarende publikationer - både som gennemsnitlig FWCI pr. enhed
og som andelen af publikationer blandt verdens mest citerede 10%.

Der er dog to vigtige forbehold før FWCI-værdierne anvendes:
- **Kun en delmænde af KU's publikationer indgår**. For at optræde her skal en publikation både
have et **DOI registreret i CURIS** og være **fundet ved opslag** i OpenAlex/Scopus - publikationer
uden DOI (f.eks. mange bogkapitler og ældre værker) er - for nu - strukturelt udelukkede, uanset
deres faktiske citationsgennemslag. 
- **FWCI-niveauer afhænger systematisk af datakilden**. OpenAlex giver konsekvent højere FWCI-værdier
end SciVal/Scopus for samme publikationer (se studiet i 'Hvad er FWCI?' nedenfor). Sammenlign
derfor kun tal fra **samme datakilde** - f.eks. to enheder i samme år eller en enhed på tværs af år - 
aldrig på tværs af datakildeskift i sidepanelet. 
""")

    with st.expander("Hvad er FWCI?"):
        st.markdown(
"""
**Field Weighted Citation Impact (FWCI)** er et mål for, hvor meget en publikation citeres
sammenlignet med det globale gennemsnit for publikationer inden for samme fagfelt, publiceringsår
og publikationstype. 

$$
FWCI = \\frac{\\text{Antal citationer modtaget}}{\\text{Forventet antal citationer}}
$$

- **FWCI = 1.0** betyder, at publikationen citeres præcis som forventet
- **FWVI > 1.0** betyder, at publikationen citeres mere end forventet
- **FWCI < 1.0** betyder, at publikationen citeres mindre end forventet

Citationer akkumuleres over tid, så FWCI er typisk beregnet over en **fast tidsramme** - ofte
**tre år efter publikationsåret**. Det betyder, at nyere publikationer naturligt vil have en 
lavere FWCI, da de endnu ikke har nået deres fulde *citationspotentiale*.

FWCI beregnes af Scopus/SciVal og OpenAlex, men de to kilder kan give forskellige værdier, da
de bygger på forskellige publikations- og citationsdatabaser. Se fanen **Datagrundlag** for
en sammenligning af datakilderne.

**Sammenligning mellem OpenAlex, Scopus, Dimensions og Web of Science**
Et nyere studie af Scheidsteger, Haunschild og Bornmann (2025), der sammenligner 
feltnormaliserede citationsscorer for 48 tyske universiteter på tværs af dire databaser, fandt
en **konsekvent** rækkefølge uden undtagelser: OpenAlex gav den højeste score for samtlige 48 universiteter, 
foran Dimensions, Scopus og Web of Science i den rækkefølge. 

Årsagen er ikke en fejl i OpenAlex, men databasens grovere emne- og dokumenttypeklassifikation: 
omkring 40% af OpenAlex' poster mandler en dokumenttypeangivelse - og typer, som WoS/Scopus
holder adskilt (f.eks. 'Letter', 'Editorial') lægges i OpenAlex sammen med tidsskriftartikler.
Da den slags sjældent citerede tekster trækker referencesættets gennemsnit ned, bliver den 
forventede citationsrate lavere - og dermed FWCI-værdien dystematisk højere, selv for
identiske publikationer. ([Scheidsteger et al., 2025, *Scientometrics*](https://doi.org/10.1007/s11192-025-05338-7))
""")

    data_source = filters.get("data_source", "OpenAlex")
    if data_source not in ("OpenAlex", "SciVal"):
        st.error(
"""Citationsmetrikker registreres ikke i CURIS. Vælg OpenAlex eller SciVal som datakilde
i sidepanelet for at se fanens indhold.
""")
        return
    
    mode = filters.get("mode", "F")
    mode = mode.replace("G", "") or "F"

    st.markdown("---\n#### Gennemsnitlig FWCI pr. enhed")
    _render_fwci_section(filters, mode)

    st.markdown(
"""
---

#### Top 10% citerede publikationer

Andelen af KU's publikationer, der ligger blandt de 10% mest citerede globalt inden for
samme fagfelt, publiceringsår og publikationstype - en indikator for, hvor meget af KU's
output der placerer sig i den absolutte top, snarere end blot over gennemsnittet.
"""
    )
    _tab_top10_n, _tab_top10_p = st.tabs(["Antal", "Andel (%)"])
    with _tab_top10_n:
        _render_top10_section(filters, mode, chart_mode="antal")
    with _tab_top10_p:
        _render_top10_section(filters, mode, chart_mode="pct")

    st.markdown(
f"""
---

#### FWCI over tid

Citationer akkumuleres over tid, så de seneste år vil systematisk fremstå med kunstigt lav FWCI - 
ikke fordi forskningskvaliteten er faldet, men fordi de nyeste publikationer endnu ikke har 
nået deres fulde citationspotentiale (jf. forklaringen øverst på fanen). Grafen udelader derfor 
som **standard** de seneste {IMMATURE_YEARS_DEFAULT} år - kryds boksen under grafen af, hvis
du vil se dem alligevel.

Graferne dækker altid hele den tilgængelige periode, uanset sidepanelets valgte årsinterval - 
øvrige filtre gælder stadig.
"""
    )
    _render_fwci_trend(filters)