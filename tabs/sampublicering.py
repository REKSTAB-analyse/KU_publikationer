from data.loader import get_pairs_cursor
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import plotly.graph_objects as go

import streamlit as st
from config import SAMPUBLICERING_URL, doi_filter_sql
from components.charts import fig_year_trend, PLOTLY_CONFIG
from components.export import render_table_export
from components.colors import build_faculty_colors, ku_color_sequence, stillingsgruppe_colors
from components.charts import _hls_gradient

_NIVEAU_EDGE_COL = {"fak": "Edge_type_fak", "inst": "Edge_type_inst", "stil": "Edge_type_stil"}
_NIVEAU_LABEL = {"fak": "fakultet", "inst": "institut", "stil": "stillingsgruppe"}

@st.cache_data
def _query_intra_inter_trend(filters, metric, niveau):
    """
    Intra/inter-fordeling år for år, på det angivne niveau (fak/inst/stil).
    metric: 'publikationer' eller 'forfatterpar'. Et par tælles med, hvis
    MINDST ÉN af de to personer matcher sidepanelets Fak/Inst/Stil-filtre,
    uafhængigt af hvilket niveau selve intra/inter-klassifikationen sker på.
    """
    edge_col = _NIVEAU_EDGE_COL[niveau]
    ph = lambda lst: ", ".join(["?" for _ in lst])
    where_sql = f"""
        WHERE Year IS NOT NULL
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND Antal_forfattere BETWEEN ? AND ?
          AND (
                (Fak_1 IN ({ph(filters['fakultet'])}) AND Inst_1 IN ({ph(filters['institutter'])}) AND Stil_1 IN ({ph(filters['stillingsgrupper'])}))
             OR (Fak_2 IN ({ph(filters['fakultet'])}) AND Inst_2 IN ({ph(filters['institutter'])}) AND Stil_2 IN ({ph(filters['stillingsgrupper'])}))
          )
    """
    params = (
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['min_forfattere'], filters['max_forfattere']] +
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper']
    )

    if metric == "forfatterpar":
        sql = f"""
            SELECT Year, {edge_col} AS klasse, COUNT(*) AS n
            FROM pairs
            {where_sql}
            GROUP BY 1, 2
            ORDER BY 1
        """
    else:  # publikationer
        sql = f"""
            WITH pub_class AS (
                SELECT PURE_ID, Year,
                       MAX(CASE WHEN {edge_col} = 'inter' THEN 1 ELSE 0 END) AS has_inter,
                       MAX(CASE WHEN {edge_col} = 'solo' THEN 1 ELSE 0 END) AS is_solo
                FROM pairs
                {where_sql}
                GROUP BY PURE_ID, Year
            )
            SELECT Year, CASE WHEN has_inter = 1 THEN 'inter' ELSE 'intra' END AS klasse, COUNT(*) AS n
            FROM pub_class
            WHERE is_solo = 0
            GROUP BY 1, 2
            ORDER BY 1
        """

    data_source = filters.get("data_source", "CURIS")
    rows = get_pairs_cursor(data_source).execute(sql, params).fetchall()
    result = {}
    for year, klasse, n in rows:
        result.setdefault(year, {})[klasse] = n
    return result

def _current_scope_label(filters):
    """Beskriver den aktuelle afgrænsning på tværs af ALLE tre niveauer, ikke
    kun det niveau der lige nu vises - bruges som label for 'ingen
    specifikke enheder valgt på DETTE niveau', så et allerede indsnævret
    fakultet/institut afspejles korrekt, i stedet for altid at vise 'KU
    samlet' uanset andre aktive filtre."""
    if filters.get('institutter_explicit', False):
        insts = filters['institutter']
        return insts[0] if len(insts) == 1 else f"{len(insts)} valgte institutter"
    if filters.get('fakultet_explicit', False):
        faks = filters['fakultet']
        return faks[0] if len(faks) == 1 else f"{len(faks)} valgte fakulteter"
    return "KU samlet"

def _full_unit_label(unit, niveau, filters):
    """Sammensat label, der viser den valgte enhed sammen med evt. samtidigt
    aktive andre niveauer - samme 'X | Y'-mønster konsekvent på tværs af
    Fakultet, Institut og Stillingsgruppe."""
    parts = [unit]
    if niveau == "fak":
        if filters.get('institutter_explicit', False):
            insts = filters['institutter']
            parts.append(insts[0] if len(insts) == 1 else f"{len(insts)} institutter")
    elif niveau == "inst":
        if filters.get('fakultet_explicit', False):
            faks = filters['fakultet']
            parts.append(faks[0] if len(faks) == 1 else f"{len(faks)} fakulteter")
    else:  # stil
        if filters.get('institutter_explicit', False):
            insts = filters['institutter']
            parts.append(insts[0] if len(insts) == 1 else f"{len(insts)} institutter")
        elif filters.get('fakultet_explicit', False):
            faks = filters['fakultet']
            parts.append(faks[0] if len(faks) == 1 else f"{len(faks)} fakulteter")
    return " | ".join(parts)


def _stil_shared_fak_inst_color(filters, faculty_colors, data_source):
    """Fælles farve for ALLE stillingsgruppe-enheder i samme kald, når
    institut/fakultet er eksplicit valgt samtidig med stillingsgruppe -
    institut/fakultet-farven har forrang over stillingsgruppens egen."""
    if filters.get('institutter_explicit', False) and len(filters['institutter']) == 1:
        inst = filters['institutter'][0]
        parent_fak = _institut_to_fak_lookup(data_source).get(inst, "")
        return faculty_colors.get(parent_fak, "#666666")
    if filters.get('fakultet_explicit', False) and len(filters['fakultet']) == 1:
        return faculty_colors.get(filters['fakultet'][0], "#666666")
    return None

def _compute_unit_colors(units, niveau, filters, faculty_colors, data_source):
    """Delt farvelogik for BÅDE _render_intra_inter_by_unit og
    _render_internt_samarbejde_by_unit - undgår at vedligeholde flere
    kopier, der kan komme ud af trit. 'base_name' (før evt. ' | '-sammen-
    sætning fra _full_unit_label) bruges konsekvent til opslag."""
    stil_colors = stillingsgruppe_colors()
    colors = {}

    if niveau == "stil":
        shared_color = _stil_shared_fak_inst_color(filters, faculty_colors, data_source)
        if shared_color is not None:
            for u in units:
                colors[u] = "#666666" if u == "KU samlet" else shared_color
            return colors

    for u in units:
        base_name = u.split(" | ")[0]
        if u == "KU samlet":
            colors[u] = "#666666"
        elif niveau == "stil" and base_name in stil_colors:
            colors[u] = stil_colors[base_name]
        elif base_name in faculty_colors:
            colors[u] = faculty_colors[base_name]

    inst_units = [u for u in units if u not in colors]
    if inst_units:
        inst_to_fak = _institut_to_fak_lookup(data_source)
        by_fak = {}
        for u in inst_units:
            base_name = u.split(" | ")[0]
            by_fak.setdefault(inst_to_fak.get(base_name, ""), []).append(u)
        for parent_fak, insts in by_fak.items():
            insts_sorted = sorted(insts)
            base = faculty_colors.get(parent_fak)
            if base:
                shades = _hls_gradient(base, len(insts_sorted))
                for i, u in enumerate(insts_sorted):
                    colors[u] = shades[i]
            else:
                fallback = ku_color_sequence(len(insts_sorted))
                for i, u in enumerate(insts_sorted):
                    colors[u] = fallback[i]
    return colors

def _samarbejde_base_where(filters):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    where_sql = f"""
        WHERE Year IS NOT NULL
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND Antal_forfattere BETWEEN ? AND ?
          AND (
                (Fak_1 IN ({ph(filters['fakultet'])}) AND Inst_1 IN ({ph(filters['institutter'])}) AND Stil_1 IN ({ph(filters['stillingsgrupper'])}))
             OR (Fak_2 IN ({ph(filters['fakultet'])}) AND Inst_2 IN ({ph(filters['institutter'])}) AND Stil_2 IN ({ph(filters['stillingsgrupper'])}))
          )
    """
    params = (
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['min_forfattere'], filters['max_forfattere']] +
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper']
    )
    return where_sql, params


@st.cache_data
def _query_internt_samarbejde_by_unit(filters):
    candidates = [
        (filters.get('stillingsgrupper_explicit', False), "stillingsgrupper"),
        (filters.get('institutter_explicit', False), "institutter"),
        (filters.get('fakultet_explicit', False), "fakultet"),
    ]
    units, filter_key = None, None
    for is_active, key in candidates:
        if is_active:
            units, filter_key = filters[key], key
            break

    data_source = filters.get("data_source", "CURIS")

    def _counts(f):
        where_sql, params = _samarbejde_base_where(f)
        sql = f"""
            WITH pub_flags AS (
                SELECT PURE_ID, Year,
                       MAX(CASE WHEN Edge_type_inst = 'solo' THEN 1 ELSE 0 END) AS is_solo
                FROM pairs
                {where_sql}
                GROUP BY PURE_ID, Year
            )
            SELECT Year, COUNT(*) AS total,
                   SUM(CASE WHEN is_solo = 0 THEN 1 ELSE 0 END) AS internt_n,
                   SUM(is_solo) AS solo_n
            FROM pub_flags
            GROUP BY Year
            ORDER BY Year
        """
        return get_pairs_cursor(data_source).execute(sql, params).fetchall()

    if units is None:
        rows = _counts(filters)
        result = {}
        for year, total, internt_n, solo_n in rows:
            result.setdefault(year, {})[_current_scope_label(filters)] = {"total": total, "internt": internt_n, "solo": solo_n}
        return result, "fak"

    _filter_key_to_niveau = {"stillingsgrupper": "stil", "institutter": "inst", "fakultet": "fak"}
    niveau_for_label = _filter_key_to_niveau[filter_key]

    result = {}
    for unit in units:
        unit_filters = dict(filters)
        unit_filters[filter_key] = [unit]
        rows = _counts(unit_filters)
        display_label = _full_unit_label(unit, niveau_for_label, filters)
        for year, total, internt_n, solo_n in rows:
            result.setdefault(year, {})[display_label] = {"total": total, "internt": internt_n, "solo": solo_n}
    return result, niveau_for_label

def _render_internt_samarbejde_by_unit(filters):
    """Solid = Internt samarbejde, stiplet = Solo, farve = enhed - samme
    visuelle sprog som _render_intra_inter_by_unit."""
    data, niveau_for_label = _query_internt_samarbejde_by_unit(filters)
    if not data:
        st.error("Ingen data matcher de valgte filtre.")
        return

    years_sorted = sorted(data.keys())
    units = sorted({u for cats in data.values() for u in cats}, key=lambda u: (u != "KU samlet", u))

    faculty_colors = build_faculty_colors()
    colors = _compute_unit_colors(units, niveau_for_label, filters, faculty_colors, filters.get("data_source", "CURIS"))

    def _build_and_render(chart_mode):
        fig = go.Figure()
        for unit in units:
            for klasse, dash in [("internt", None), ("solo", "dash")]:
                y_vals, pct_vals, hover_n = [], [], []
                for year in years_sorted:
                    stats = data.get(year, {}).get(unit, {"total": 0, "internt": 0, "solo": 0})
                    n = stats.get(klasse, 0) or 0
                    total = stats.get("total", 0) or 1
                    pct = round(100 * n / total, 1)
                    y_vals.append(pct if chart_mode == "pct" else n)
                    pct_vals.append(pct)
                    hover_n.append(n)
                label = "internt samarbejde" if klasse == "internt" else "solo"
                fig.add_trace(go.Scatter(
                    x=years_sorted, y=y_vals, mode="lines+markers",
                    name=f"{unit} ({label})",
                    line=dict(color=colors.get(unit, "#666666"), dash=dash, width=2.5 if unit == "KU samlet" else 2),
                    marker=dict(size=5),
                    customdata=list(zip(pct_vals, hover_n)),
                    hovertemplate=(
                        f"<b>{unit} ({label})</b><br>%{{x}}<br>"
                        f"%{{customdata[0]:.1f}}%<br>%{{customdata[1]:,}} publikationer<extra></extra>"
                    ),
                ))
        fig.update_layout(
            title=dict(text="Internt samarbejde og solo, pr. enhed", font=dict(size=14)),
            xaxis=dict(title="Udgivelsesår", dtick=1),
            yaxis=dict(title="Andel (%)" if chart_mode == "pct" else "Antal", range=[0, 100] if chart_mode == "pct" else None),
            plot_bgcolor="white", height=460,
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
            margin=dict(t=50, b=10, l=10, r=150),
        )
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"internt_samarbejde_chart_{chart_mode}")
        render_table_export(
            data={
                str(year): {
                    f"{u} ({k})": data.get(year, {}).get(u, {}).get(k, 0)
                    for u in units for k in ["internt", "solo"]
                }
                for year in years_sorted
            },
            row_label="År",
            filename=f"sampub_internt_samarbejde_pr_enhed_{chart_mode}.xlsx",
            sheet_name="Internt samarbejde pr. enhed",
            key=f"export_internt_samarbejde_pr_enhed_{chart_mode}",
        )

    _tab_antal, _tab_pct = st.tabs(["Antal", "Andel (%)"])
    with _tab_antal:
        _build_and_render("antal")
    with _tab_pct:
        _build_and_render("pct")

@st.cache_data
def _institut_to_fak_lookup(data_source: str):
    """Majoritetsbaseret Institut -> Fakultet-opslag, udledt direkte af
    par-tabellen selv. Bruges til at farve HVERT institut med dets eget
    moderfakultets farve, uafhængigt af hvor mange/hvilke fakulteter der er
    valgt i sidepanelet - i modsætning til den tidligere logik, som kun
    virkede korrekt, når præcis ét fakultet var eksplicit valgt."""
    rows = get_pairs_cursor(data_source).execute("""
        WITH all_insts AS (
            SELECT Inst_1 AS inst, Fak_1 AS fak FROM pairs WHERE Inst_1 != ''
            UNION ALL
            SELECT Inst_2 AS inst, Fak_2 AS fak FROM pairs WHERE Inst_2 != ''
        ),
        counted AS (
            SELECT inst, fak, COUNT(*) AS n,
                   ROW_NUMBER() OVER (PARTITION BY inst ORDER BY COUNT(*) DESC) AS rn
            FROM all_insts
            GROUP BY inst, fak
        )
        SELECT inst, fak FROM counted WHERE rn = 1
    """).fetchall()
    return dict(rows)

@st.cache_data
def _query_intra_inter_by_unit(filters, metric, niveau):
    """
    Samme princip som _query_intra_inter_trend, men PR. ORGANISATORISK
    ENHED. Enheds-aksen falder tilbage til det næst-mest specifikke, AKTIVT
    valgte niveau, hvis dette niveaus eget filter ikke er eksplicit valgt -
    fx: er specifikke fakulteter valgt, men ingen specifikke
    stillingsgrupper, vises Stillingsgruppe-sektionen alligevel som én linje
    PR. VALGT FAKULTET (hver med sin egen intra/inter-fordeling), i stedet
    for én samlet, blandet linje.
    """
    if niveau == "fak":
        candidates = [(filters.get('fakultet_explicit', False), "fakultet")]
    elif niveau == "inst":
        candidates = [(filters.get('institutter_explicit', False), "institutter"), (filters.get('fakultet_explicit', False), "fakultet")]
    else:  # stil
        candidates = [
            (filters.get('stillingsgrupper_explicit', False), "stillingsgrupper"),
            (filters.get('institutter_explicit', False), "institutter"),
            (filters.get('fakultet_explicit', False), "fakultet"),
        ]

    units, filter_key = None, None
    for is_active, key in candidates:
        if is_active:
            units, filter_key = filters[key], key
            break

    if units is None:
        data = _query_intra_inter_trend(filters, metric, niveau)
        result = {}
        for year, cats in data.items():
            result.setdefault(year, {})[_current_scope_label(filters)] = cats
        return result

    result = {}
    for unit in units:
        unit_filters = dict(filters)
        unit_filters[filter_key] = [unit]
        data = _query_intra_inter_trend(unit_filters, metric, niveau)
        display_label = _full_unit_label(unit, niveau, filters)
        for year, cats in data.items():
            result.setdefault(year, {})[display_label] = cats
    return result

@st.cache_data
def _query_alle_pub_by_unit(filters, niveau):
    """Samlet antal ALLE publikationer (inkl. solo) år for år, PR.
    ORGANISATORISK ENHED - matcher samme enheds-fallback-kæde som
    _query_intra_inter_by_unit. Bruges UDELUKKENDE som alternativ nævner
    til Andel (%), når 'alle publikationer'-toggle'en er slået til - ændrer
    intet ved selve linjerne (intra/inter), kun hvad de sammenlignes med."""
    if niveau == "fak":
        candidates = [(filters.get('fakultet_explicit', False), "fakultet")]
    elif niveau == "inst":
        candidates = [(filters.get('institutter_explicit', False), "institutter"), (filters.get('fakultet_explicit', False), "fakultet")]
    else:  # stil
        candidates = [
            (filters.get('stillingsgrupper_explicit', False), "stillingsgrupper"),
            (filters.get('institutter_explicit', False), "institutter"),
            (filters.get('fakultet_explicit', False), "fakultet"),
        ]

    units, filter_key = None, None
    for is_active, key in candidates:
        if is_active:
            units, filter_key = filters[key], key
            break

    data_source = filters.get("data_source", "CURIS")

    def _count(f):
        where_sql, params = _samarbejde_base_where(f)
        sql = f"SELECT Year, COUNT(DISTINCT PURE_ID) AS n FROM pairs {where_sql} GROUP BY Year"
        return dict(get_pairs_cursor(data_source).execute(sql, params).fetchall())

    if units is None:
        counts = _count(filters)
        return {year: {_current_scope_label(filters): n} for year, n in counts.items()}

    result = {}
    for unit in units:
        unit_filters = dict(filters)
        unit_filters[filter_key] = [unit]
        counts = _count(unit_filters)
        display_label = _full_unit_label(unit, niveau, filters)
        for year, n in counts.items():
            result.setdefault(year, {})[display_label] = n
    return result

def _render_intra_inter_by_unit(filters, metric, niveau, alle_publikationer=False):
    """
    To linjer pr. enhed (intra=stiplet, inter=optrukket) - farven
    identificerer enheden. Enheds-aksen falder tilbage til det næst-mest
    specifikke, aktivt valgte niveau, hvis dette niveau ikke selv er
    eksplicit valgt.
    """
    data = _query_intra_inter_by_unit(filters, metric, niveau)
    alle_pub_totals = _query_alle_pub_by_unit(filters, niveau) if alle_publikationer else None
    if not data:
        st.error("Ingen data matcher de valgte filtre.")
        return

    years_sorted = sorted(data.keys())
    units = sorted({u for cats in data.values() for u in cats}, key=lambda u: (u != "KU samlet", u))

    faculty_colors = build_faculty_colors()
    colors = {}

    colors = _compute_unit_colors(units, niveau, filters, faculty_colors, filters.get("data_source", "CURIS"))
    

    def _build_and_render(chart_mode):
        fig = go.Figure()
        for unit in units:
            for klasse, dash in [("inter", None), ("intra", "dash")]:
                y_vals, pct_vals, hover_n = [], [], []
                for year in years_sorted:
                    cats = data.get(year, {}).get(unit, {})
                    n = cats.get(klasse, 0)
                    if alle_pub_totals is not None:
                        total = alle_pub_totals.get(year, {}).get(unit, 0) or 1
                    else:
                        total = sum(cats.values()) or 1
                    pct = round(100 * n / total, 1)
                    y_vals.append(pct if chart_mode == "pct" else n)
                    pct_vals.append(pct)
                    hover_n.append(n)
                fig.add_trace(go.Scatter(
                    x=years_sorted, y=y_vals, mode="lines+markers",
                    name=f"{unit} ({'intra' if klasse == 'intra' else 'inter'})",
                    line=dict(color=colors.get(unit, "#666666"), dash=dash, width=2.5 if unit == "KU samlet" else 2),
                    marker=dict(size=5),
                    customdata=list(zip(pct_vals, hover_n)),
                    hovertemplate=(
                        f"<b>{unit} ({'intra' if klasse=='intra' else 'inter'})</b><br>%{{x}}<br>"
                        f"%{{customdata[0]:.1f}}%<br>%{{customdata[1]:,}} {metric}<extra></extra>"
                    ),
                ))
        fig.update_layout(
            title=dict(text=f"Intra vs. inter, pr. enhed ({metric})", font=dict(size=14)),
            xaxis=dict(title="Udgivelsesår", dtick=1),
            yaxis=dict(title="Andel (%)" if chart_mode == "pct" else "Antal", range=[0, 100] if chart_mode == "pct" else None),
            plot_bgcolor="white", height=460,
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
            margin=dict(t=50, b=10, l=10, r=150), # 220
        )
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"sampub_chart_{niveau}_{metric}_{chart_mode}")
        render_table_export(
            data={
                str(year): {
                    f"{u} ({k})": data.get(year, {}).get(u, {}).get(k, 0)
                    for u in units for k in _KLASSE_ORDER
                }
                for year in years_sorted
            },
            row_label="År",
            filename=f"sampub_intra_inter_{niveau}_{metric}_pr_enhed_{chart_mode}.xlsx",
            sheet_name=f"Pr. enhed ({niveau})",
            key=f"export_sampub_{niveau}_{metric}_pr_enhed_{chart_mode}",
        )

    _tab_antal, _tab_pct = st.tabs(["Antal", "Andel (%)"])
    with _tab_antal:
        _build_and_render("antal")
    with _tab_pct:
        _build_and_render("pct")

_KLASSE_ORDER = ["intra", "inter"]
_KLASSE_COLORS = {"intra": "#122947", "inter": "#901a1e"}
_KLASSE_LABELS = {"intra": "Intra", "inter": "Inter"}

def _render_intra_inter_trend(filters, metric, niveau):
    trend_data = _query_intra_inter_trend(filters, metric, niveau)
    if not trend_data:
        st.error("Ingen data matcher de valgte filtre.")
        return

    niveau_navn = _NIVEAU_LABEL[niveau]
    _tab_antal, _tab_pct = st.tabs(["Antal", "Andel (%)"])

    with _tab_antal:
        fig = fig_year_trend(
            trend_data, order=_KLASSE_ORDER, colors=_KLASSE_COLORS, labels=_KLASSE_LABELS,
            title=f"Intra vs. inter af {niveau_navn} over tid ({metric})",
            mode="antal", hover_unit=metric,
        )
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
        render_table_export(
            data={str(year): cats for year, cats in sorted(trend_data.items())},
            row_label="År",
            filename=f"sampub_intra_inter_{niveau}_{metric}_antal.xlsx",
            sheet_name=f"Intra-inter {niveau_navn}",
            key=f"export_sampub_{niveau}_{metric}_antal",
        )

    with _tab_pct:
        fig = fig_year_trend(
            trend_data, order=_KLASSE_ORDER, colors=_KLASSE_COLORS, labels=_KLASSE_LABELS,
            title=f"Intra vs. inter af {niveau_navn} over tid ({metric})",
            mode="pct", hover_unit=metric,
        )
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
        render_table_export(
            data={str(year): cats for year, cats in sorted(trend_data.items())},
            row_label="År",
            filename=f"sampub_intra_inter_{niveau}_{metric}_pct.xlsx",
            sheet_name=f"Intra-inter {niveau_navn}",
            key=f"export_sampub_{niveau}_{metric}_pct",
        )

def render(filters: dict) -> None:
    st.subheader("Sampublicering")

    st.markdown(
"""
Fanen viser KU's interne sampubliceringsmønstre - hvor meget forskere fra forskellige
organisatoriske enheder skriver sammen, og hvor meget samarbejdet foregår inden for egen
enhed (*intra*) versus på tværs af enheder (*inter*). Kun **interne** medforfattere indgår; 
eksternt samarbejde med ikke-KU-parter dækkes i stedet af fanen **Eksternt samarbejde**. 

Vælges OpenAlex eller SciVal som datakilde i sidepanelet, indgår kun de publikationer, der
er fundet i den pågældende datakilde - samme afgrænsning som resten af appens faner.
""" 
    )

    _metrik = st.radio(
        "Vis som:",
        options=["Publikationer", "Forfatterpar"],
        index=0, horizontal=True, key="sampub_metrik",
    )

    if _metrik == "Forfatterpar":
        st.markdown(
"""
**Forfatterpar** tæller hver unik kombination af to interne medforfattere på samme
publikation. En publikation med *n* interne forfattere bidrager med n(n-1)/2 par -
en artikel med mange forfattere vejer derfor tungere i denne metrik end en med få. 
Publikationer med kun én intern forfatter bidrager per definition med **0** par, og indgår
derfor ikke i denne metrik. 

**Eksempel**: En publikation med 5 interne medforfattere fra forskellige institutter
bidrager med 10 forfatterpar til netværket - langt mere end en 2-forfatter-artikel, selvom
begge kun er **én** publikation. Forfatterpar er derfor det rette valg, hvis spørgsmålet er
*"hvor meget parvis samarbejdsaktivitet foregår der?"*
"""
        )
    else:
        st.markdown(
"""
**Publikationer** tæller hver publikation præcis én gang, uanset hvor mange interne
medforfattere den har. En publikation klassificeres som **inter**, hvis den
har **mindst ét** forfatterpar, der krydser den valgte organisatoriske grænse (f.eks. 
fakultet) - ellers som **intra**. Publikationer med kun én intern forfatter kan hverken være intra
eller intra - se **Internt samarbejde nedenfor** for hvordan de indgår. 

**Eksempel**: En publikation med 5 interne medforfattere, hvoraf blot to kommer fra
forskellige fakulteter, tæller som **én** tværgående publikation - uanset at de øvrige
8 forfatterpar er interne. Publikationer er derfor det rette valg, hvis spørgsmålet er
*"hvor mange konkrete publikationer involverer tværgående samarbejde?"*, uden at store
konsortium-artikler vejer tungere end små.
"""
        )

    st.markdown("---")
    _metric_arg = "forfatterpar" if _metrik == "Forfatterpar" else "publikationer"

    _alle_pub = False
    if _metrik == "Publikationer":
        st.markdown(
"""
##### Internt samarbejde

Internt samarbejde dækker over publikationer med mindst to interne forfattere - uanset organisatorisk
tilknytning. Modstykket er 'solo', som er publikationer med kun én intern forfatter. Det implicerer altså, 
at publikationer med én KU-forfatter og desuden eksterne forfattere indgår i solo publikationerne. 

Er specifikke enheder valgt i sidepanelet, vises ét linjepar pr. valgt enhed. 

**Eksempel**: Vælges 'SAMF' i sidepanelet, viser linjeparret, hvor stor en andel af SAMF's publikationer
der har **mindst to** KU-forfattere (uanset om de begge er fra SAMF), versus
hvor stor en del der har SAMF-forfatteren som eneste interne forfatter. 
"""
        )
        _render_internt_samarbejde_by_unit(filters)

        _alle_pub = st.toggle(
            "Andel af alle publikationer",
            value=True, 
            key="sampub_alle_pub_toggle",
        )
        if _alle_pub:
            st.caption(
                "Andel (%) i de tre sektioner nedenfor viser nu andelen af **alle** publikationer (inkl. solo) - ikke kun "
                "andelen af publikationer med internt samarbejde."
            )
        else:
            st.caption(
                "Andel (%) viser nu kun andelen af publikationer med internt samarbejde."
            )
        
        st.markdown("---")


    st.markdown(
"""
##### Fakultet

I det her afsnit fokuserer figuren på samarbejde, der krydser fakultetsgrænserne. 
**Intra** er her samarbejde inden for samme fakultet, mens **inter** er samarbejde på tværs af to
fakulteter.  

Er specifikke fakulteter valgt i sidepanelet, vises ét linjepar pr. valgt fakultet. Er der
i stedet kun valgt specifikke institutter valgt (uden noget fakultet), vises ét linjepar pr.
valgt institut - men stadig med fakultet-niveauets intra/inter-opdeling, altså hvor stor
en andel af det pågældende instituts samarbejde der krydser fakultetsgrænser. Er hverken
fakultet eller institut valgt, vises i stedet ét linjepar for 'KU samlet'.

"""
    )
    _render_intra_inter_by_unit(filters, _metric_arg, "fak", alle_publikationer=_alle_pub)


    st.markdown("---")
    st.markdown(
"""##### Institut

Figuren nedenfor viser samarbejde på tværs af institutgrænserne. **Intra** er samarbejde inden for samme
institut, mens **inter** er samarbejde på tværs af institutter. 

Er specifikke institutter valgt i sidepanelet, vises ét linjepar pr. institut. Er
ingen institutter valgt, falder figuren i stedet tilbage til at vise fakulteter - men 
stadig med institutniveauets intra/inter-opdeling. 

**Eksempel**: Vælger du 'SAMF', viser linjeparret dermed, hvor stor en andel af **hele SAMF's**
samarbejde der foregår inden for samme institut, versus på tværs af institutter. 
"""
    )
    _render_intra_inter_by_unit(filters, _metric_arg, "inst", alle_publikationer=_alle_pub)

    st.markdown("---")
    st.markdown(
"""##### Stillingsgruppe

Figuren nedenfor viser samarbejde på tværs af stillingsgrupper. **Intra** viser samarbejde inden for samme
stillingsgruppe, mens **inter** viser samarbejde på tværs af stillingsgrupper. 

Er specifikke stillingsgrupper valgt i sidepanelet, vises ét linjepar pr. valgt stillingsgruppe. 
Er ingen valgt, falder figuren tilbage til institut eller fakultet - og til 'KU samlet',
hvis intet af det heller er valgt. 

**Bemærk**: uanset hvilken enhed, der vises, er selve intra/inter her altid baseret på 
**stillingsgruppe**, ikke organisatorisk tilhørsforhold - det ændrer sig ikke, selvom 
enheden skifter. 

**Eksempel**: Er 'Professor' valgt i sidepanelet, viser linjeparret, hvor stor en andel af 
professors samarbejde der er med **andre professorer** (intra), versus med forskere
i **andre stillingsgrupper**, f.eks. en adjunkt eller postdoc (inter). 

**Eksempel**: Er 'SAMF' valgt (ingen specifik stillingsgruppe), viser figuren, hvor stor en andel af 
SAMF's samlede samarbejde, der foregår **inden for samme stillingsgruppe** (intra) versus 
**på tværs af stillingsgrupper** (inter).  

Begge eksempler ovenfor kan selvfølgelig kombineres. 
"""
        )

    _render_intra_inter_by_unit(filters, _metric_arg, "stil", alle_publikationer=_alle_pub)