import sys
from pathlib import Path
import re
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
from data.loader import get_cursor
from components.charts import fig_hbar_stacked, fig_year_trend, PLOTLY_CONFIG, _build_y_positions, _BAR_WIDTH, _INTRA_GAP, grouped_bar_offsets
from components.export import render_table_export
from components.colors import build_faculty_colors, stillingsgruppe_colors
from config import hier_cols, doi_filter_sql, author_count_filter, show_ku_samlet, year_range_label, breakdown_label, STIL_ORDER, COUNTRY_LOOKUP
from config import _COUNTRY_NAMES_DA

KOEN_ORDER = ["Kvinder", "Mænd", "Ukendt"]
KOEN_COLORS = {"Kvinder": "#901a1e", "Mænd": "#122947", "Ukendt": "#666666"}
KOEN_LABELS = {"Kvinder": "Kvinder", "Mænd": "Mænd", "Ukendt": "Ukendt"}
_KOEN_ORDER_TREND = ["Kvinder", "Mænd"]

_KOEN_CATEGORY_SQL = "CASE Koen WHEN 'K' THEN 'Kvinder' WHEN 'M' THEN 'Mænd' ELSE 'Ukendt' END"

STATSBG_ORDER = ["Danmark", "Europa", "Asien", "Amerika", "Afrika", "Oceanien", "Ukendt"]
STATSBG_COLORS = {
    "Danmark": "#901a1e", "Europa": "#122947", "Asien": "#39641c",
    "Amerika": "#0a5963", "Afrika": "#c0392b", "Oceanien": "#8e6b23", "Ukendt": "#666666",
}
STATSBG_LABELS = {k: k for k in STATSBG_ORDER}


_STATSBG_REGION_OVERRIDE = {
    "USA": "Amerika", "Holland": "Europa", "Australien": "Oceanien",
    "Etiopien": "Afrika", "Colombia": "Amerika", "Mozambique": "Afrika",
    "Usbekistan": "Asien", "Bahrain": "Asien", "Kasakhstan": "Asien",
    "Nordmakedonien": "Europa", "Madagaskar": "Afrika",
}

# Navn -> region, udledt af COUNTRY_LOOKUP selv (bruges som fallback,
# før override-listen konsulteres)
_LAND_TIL_REGION = {info["land"]: info["region"] for info in COUNTRY_LOOKUP.values()}


def _statsbg_region_da(code: str) -> str:
    """Grupperer KU's gamle CPR-stil Statsbg-kode (fx 'S' for Sverige) efter
    region. Bro-forbinder to eksisterende opslag: _COUNTRY_NAMES_DA
    (CPR-kode -> dansk navn) og COUNTRY_LOOKUP (navn -> region), med en
    manuel override-liste for de ~11 lande, hvis navne ikke matcher ordret
    mellem de to kilder (se _STATSBG_REGION_OVERRIDE)."""
    if not code:
        return "Ukendt"
    navn = _COUNTRY_NAMES_DA.get(code, _COUNTRY_NAMES_DA.get(code.upper()))
    if navn is None or navn == "Ukendt":
        return "Ukendt"
    if navn == "Danmark":
        return "Danmark"
    if navn in _STATSBG_REGION_OVERRIDE:
        return _STATSBG_REGION_OVERRIDE[navn]
    return _LAND_TIL_REGION.get(navn, "Ukendt")

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _filter_suppressed_units(data, min_celle):
    """Fjerner HELE enheder, hvor mindst ét af Kvinder/Mænd (ikke Ukendt) er
    under min_celle - bruges FØR selve figuren bygges, så en lille gruppe
    hverken vises i søjlehøjde, hover-tekst eller eksport."""
    result = {}
    for unit, cats in data.items():
        real = {k: v for k, v in cats.items() if k in ("Kvinder", "Mænd")}
        if real and any(v < min_celle for v in real.values()):
            continue
        result[unit] = cats
    return result


def _filter_suppressed_trend(trend_data, min_celle):
    """Samme suppressionsprincip, for trend-data (år -> 'enhed (køn)' ->
    antal). Suppression sker PR. ÅR: er ét køn under grænsen for en given
    enhed i et givet år, skjules BEGGE køns punkter for netop det år."""
    all_series = {s for cats in trend_data.values() for s in cats}
    base_units = {}
    for s in all_series:
        base = s.rsplit(" (", 1)[0]
        base_units.setdefault(base, []).append(s)

    result = {}
    for year, cats in trend_data.items():
        result[year] = {}
        for base, series_list in base_units.items():
            values = {s: cats.get(s) for s in series_list if cats.get(s) is not None}
            if values and any(v < min_celle for v in values.values()):
                continue
            for s in series_list:
                if s in cats:
                    result[year][s] = cats[s]
    return result


def _base_where(filters, alias=""):
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    where_sql = f"""
        WHERE {alias}Intern       = 'Intern'
          AND {alias}Fak          IN ({ph(filters['fakultet'])})
          AND {alias}Inst         IN ({ph(filters['institutter'])})
          AND {alias}Stil         IN ({ph(filters['stillingsgrupper'])})
          AND {alias}Type        IN ({ph(filters['typer'])})
          AND {alias}Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF({alias}Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
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

def _current_unit_label(filters):
    """Beskriver den aktuelt fokuserede enhed ud fra sidepanelets
    fakultet/institut-valg - 'KU samlet', hvis intet er eksplicit valgt."""
    if filters.get('institutter_explicit', False):
        insts = filters['institutter']
        return insts[0] if len(insts) == 1 else f"{len(insts)} valgte institutter"
    if filters.get('fakultet_explicit', False):
        faks = filters['fakultet']
        return faks[0] if len(faks) == 1 else f"{len(faks)} valgte fakulteter"
    return "KU samlet"

# --- Kønsfordeling / Publikationer pr. køn: direkte klon af forfatterprofil.py's
# _query_authors/_render_section, blot med kategorien hardcodet til køn ---

@st.cache_data(show_spinner="Henter data...")
def _query_koen(filters, mode, count_col="ext_id"):
    where_sql, params = _base_where(filters)
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
        SELECT {select_dims}({_KOEN_CATEGORY_SQL}) AS cat,
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
        ku_sql = f"SELECT ({_KOEN_CATEGORY_SQL}) AS cat, COUNT(DISTINCT {count_col}) AS n FROM pubs {where_sql} GROUP BY 1"
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}

    return result, cluster_map


@st.cache_data(show_spinner="Henter data...")
def _query_koen_totals(filters, mode, count_col="PURE_ID"):
    """Selvstændig, udelt nævner til Andel (%) - samme princip som
    forfatterprofil.py's _query_stil_totals."""
    where_sql, params = _base_where(filters)
    dims = hier_cols(mode)
    n_dims = len(dims)
    select_dims = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""
    group_by = ", ".join(str(i) for i in range(1, n_dims + 1)) if dims else "1"

    sql = f"SELECT {select_dims}COUNT(DISTINCT {count_col}) AS n FROM pubs {where_sql} GROUP BY {group_by}"
    rows = get_cursor().execute(sql, params).fetchall()

    result = {}
    for row in rows:
        dim_values = row[:n_dims]
        n = row[n_dims]
        dim_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        result[dim_label] = n

    if mode == "F" and show_ku_samlet(filters):
        ku_total = get_cursor().execute(f"SELECT COUNT(DISTINCT {count_col}) FROM pubs {where_sql}", params).fetchone()[0]
        result = {"KU samlet": ku_total, **result}
    return result

@st.cache_data(show_spinner="Henter data...")
def _query_statsbg(filters, mode, count_col="ext_id"):
    """Statsborgerskabsfordeling, grupperet via _statsbg_region_da.
    count_col='ext_id': aggregeres trygt i SQL pr. rå landekode og summeres
    i Python - en person har netop ÉT statsborgerskab, ingen risiko for
    dobbelttælling. count_col='PURE_ID': aggregeres IKKE i SQL - en
    publikation kan have medforfattere fra FLERE forskellige lande i SAMME
    region (fx svensk + tysk), så SQL-optælling pr. rå kode + Python-
    summering ville tælle publikationen flere gange under regionen. Rå
    (dims, Statsbg, PURE_ID)-rækker hentes i stedet, og PURE_ID deduplikeres
    pr. REGION i Python via set()."""
    where_sql, params = _base_where(filters)
    dims = hier_cols(mode)
    n_dims = len(dims)
    select_dims = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""

    if count_col == "ext_id":
        group_by = ", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"
        order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1)) if dims else "1"
        sql = f"SELECT {select_dims}Statsbg, COUNT(DISTINCT ext_id) AS n FROM pubs {where_sql} GROUP BY {group_by} ORDER BY {order_by_sql}"
        rows = get_cursor().execute(sql, params).fetchall()

        result, cluster_map = {}, {}
        for row in rows:
            dim_values = row[:n_dims]
            raw_code, n = row[n_dims], row[n_dims + 1]
            dim_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
            clusters = tuple(dim_values[:-1]) if n_dims > 1 else None
            gruppe = _statsbg_region_da(raw_code)
            if dim_label not in result:
                result[dim_label] = {}
                cluster_map[dim_label] = clusters
            result[dim_label][gruppe] = result[dim_label].get(gruppe, 0) + n

        if mode == "F" and show_ku_samlet(filters):
            ku_sql = f"SELECT Statsbg, COUNT(DISTINCT ext_id) AS n FROM pubs {where_sql} GROUP BY 1"
            ku_rows = get_cursor().execute(ku_sql, params).fetchall()
            ku_result = {}
            for raw_code, n in ku_rows:
                gruppe = _statsbg_region_da(raw_code)
                ku_result[gruppe] = ku_result.get(gruppe, 0) + n
            result = {"KU samlet": ku_result, **result}
            cluster_map = {"KU samlet": None, **cluster_map}
        return result, cluster_map

    else:  # count_col == "PURE_ID"
        order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1)) if dims else "1"
        sql = f"SELECT {select_dims}Statsbg, PURE_ID FROM pubs {where_sql} ORDER BY {order_by_sql}"
        rows = get_cursor().execute(sql, params).fetchall()

        pub_sets, cluster_map = {}, {}
        for row in rows:
            dim_values = row[:n_dims]
            raw_code, pure_id = row[n_dims], row[n_dims + 1]
            dim_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
            clusters = tuple(dim_values[:-1]) if n_dims > 1 else None
            gruppe = _statsbg_region_da(raw_code)
            if dim_label not in pub_sets:
                pub_sets[dim_label] = {}
                cluster_map[dim_label] = clusters
            pub_sets[dim_label].setdefault(gruppe, set()).add(pure_id)

        result = {dl: {g: len(s) for g, s in groups.items()} for dl, groups in pub_sets.items()}

        if mode == "F" and show_ku_samlet(filters):
            ku_sql = f"SELECT Statsbg, PURE_ID FROM pubs {where_sql}"
            ku_rows = get_cursor().execute(ku_sql, params).fetchall()
            ku_sets = {}
            for raw_code, pure_id in ku_rows:
                gruppe = _statsbg_region_da(raw_code)
                ku_sets.setdefault(gruppe, set()).add(pure_id)
            result = {"KU samlet": {g: len(s) for g, s in ku_sets.items()}, **result}
            cluster_map = {"KU samlet": None, **cluster_map}
        return result, cluster_map

@st.cache_data(show_spinner="Henter data...")
def _query_statsbg_pr_stil(filters):
    """Statsborgerskabsfordeling KRYDSET med stillingsgruppe - samme princip
    som _query_koen_pr_stil, grupperet via _statsbg_region_da."""
    where_sql, params = _base_where(filters)
    sql = f"SELECT Stil, Statsbg, COUNT(DISTINCT ext_id) AS n FROM pubs {where_sql} GROUP BY Stil, Statsbg"
    rows = get_cursor().execute(sql, params).fetchall()
    result = {}
    for stil, raw_code, n in rows:
        gruppe = _statsbg_region_da(raw_code)
        stil_dict = result.setdefault(stil, {})
        stil_dict[gruppe] = stil_dict.get(gruppe, 0) + n
    return result

@st.cache_data(show_spinner="Henter data...")
def _query_statsbg_forfatterskaber(filters, mode):
    """Antal FORFATTERSKABER pr. statsborgerskabsregion - samme princip som
    _query_koen_forfatterskaber."""
    where_sql, params = _base_where(filters)
    dims = hier_cols(mode)
    n_dims = len(dims)
    select_dims = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""
    group_by = ", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"
    order_by_sql = ", ".join(str(i) for i in range(1, n_dims + 1)) if dims else "1"
    sql = f"SELECT {select_dims}Statsbg, COUNT(*) AS n FROM pubs {where_sql} GROUP BY {group_by} ORDER BY {order_by_sql}"
    rows = get_cursor().execute(sql, params).fetchall()

    result = {}
    for row in rows:
        dim_values = row[:n_dims]
        raw_code, n = row[n_dims], row[n_dims + 1]
        dim_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        gruppe = _statsbg_region_da(raw_code)
        dim_dict = result.setdefault(dim_label, {})
        dim_dict[gruppe] = dim_dict.get(gruppe, 0) + n

    if mode == "F" and show_ku_samlet(filters):
        ku_sql = f"SELECT Statsbg, COUNT(*) AS n FROM pubs {where_sql} GROUP BY 1"
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        ku_result = {}
        for raw_code, n in ku_rows:
            gruppe = _statsbg_region_da(raw_code)
            ku_result[gruppe] = ku_result.get(gruppe, 0) + n
        result = {"KU samlet": ku_result, **result}

    return result


_STATSBG_RATE_KATEGORIER = [k for k in STATSBG_ORDER if k != "Ukendt"]


@st.cache_data(show_spinner="Henter data...")
def _query_statsbg_rate(filters, mode, taeller="forfatterskaber"):
    """Rate pr. forfatter, pr. statsborgerskabsregion - samme princip som
    _query_koen_rate, generaliseret til alle regioner (minus Ukendt)."""
    if taeller == "forfatterskaber":
        tæller_data = _query_statsbg_forfatterskaber(filters, mode)
    else:
        tæller_data, _ = _query_statsbg(filters, mode, count_col="PURE_ID")

    author_data, cluster_map = _query_statsbg(filters, mode, count_col="ext_id")

    rate_data = {}
    for unit in tæller_data:
        rate_data[unit] = {}
        for gruppe in _STATSBG_RATE_KATEGORIER:
            n_taeller = tæller_data.get(unit, {}).get(gruppe, 0)
            n_forf = author_data.get(unit, {}).get(gruppe, 0)
            rate_data[unit][gruppe] = round(n_taeller / n_forf, 2) if n_forf > 0 else None

    return rate_data, author_data, cluster_map


def _render_statsbg_rate(filters, mode, taeller="forfatterskaber", min_celle=4):
    rate_data, author_data, cluster_map = _query_statsbg_rate(filters, mode, taeller=taeller)
    taeller_navn = "forfatterskaber" if taeller == "forfatterskaber" else "publikationer"
    if not rate_data:
        st.error("Ingen forfattere matcher de valgte filtre.")
        return

    rate_data = {
        u: cats for u, cats in rate_data.items()
        if not any(v < min_celle for k, v in author_data.get(u, {}).items() if k in _STATSBG_RATE_KATEGORIER)
    }
    if not rate_data:
        st.error(f"Alle enheder er skjult, da mindst én region har færre end {min_celle} repræsenterede overalt i det valgte udsnit.")
        return

    y_labels = list(rate_data.keys())
    group_keys = None
    if any(v is not None for v in cluster_map.values()):
        group_keys = ["__ku__" if lbl == "KU samlet" else cluster_map.get(lbl, "__single__") for lbl in y_labels]

    n_kat = len(_STATSBG_RATE_KATEGORIER)
    row_scale = max(1.0, n_kat / 3)  # flere klyngede søjler pr. række => højere rækker

    if group_keys is not None:
        y_pos, tick_pos, tick_labels = _build_y_positions(y_labels, group_keys)
    else:
        y_pos = list(range(len(y_labels)))
        tick_pos, tick_labels = y_pos, y_labels
    y_pos = [y * row_scale for y in y_pos]
    tick_pos = [y * row_scale for y in tick_pos]

    total_span = (y_pos[-1] - y_pos[0]) if len(y_pos) > 1 else 0
    height = max(200, int(total_span * 55 + 150))
    yaxis_kwargs = dict(
        tickmode="array", tickvals=tick_pos, ticktext=tick_labels,
        autorange="reversed", showgrid=False, zeroline=False,
    )
    offsets, bar_width = grouped_bar_offsets(n_kat, span=_INTRA_GAP * row_scale)

    fig = go.Figure()
    for i, gruppe in enumerate(_STATSBG_RATE_KATEGORIER):
        y_vals = [y + offsets[i] for y in y_pos]
        x_vals = [rate_data[u].get(gruppe) for u in y_labels]
        fig.add_trace(go.Bar(
            x=x_vals, y=y_vals, orientation="h", name=gruppe,
            marker=dict(color=STATSBG_COLORS[gruppe], line=dict(color="white", width=1)),
            width=bar_width,
            text=[f"{v:.2f}" if v is not None else "" for v in x_vals],
            textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=9),
            hovertemplate=f"<b>{gruppe}</b><br>%{{y}}<br>%{{x:.2f}} {taeller_navn} pr. forfatter<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text=f"{taeller_navn.capitalize()} pr. forfatter, pr. statsborgerskabsregion, {breakdown_label(mode)}", font=dict(size=14)),
        xaxis=dict(title=f"{taeller_navn.capitalize()} pr. forfatter"),
        yaxis=dict(**yaxis_kwargs),
        barmode="overlay",
        plot_bgcolor="white", height=height,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(t=50, b=10, l=10, r=150),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"diversitet_statsbg_rate_{taeller}")
    render_table_export(
        data=rate_data, row_label="Enhed",
        filename=f"{taeller}_pr_forfatter_statsbg.xlsx", sheet_name=f"{taeller_navn.capitalize()} pr. statsbg",
        key=f"export_diversitet_statsbg_rate_{taeller}",
    )

@st.cache_data(show_spinner="Henter data...")
def _query_koen_rate(filters, mode, taeller="forfatterskaber"):
    """Rate pr. forfatter, pr. køn. taeller='forfatterskaber' tæller hver
    persons rolle fuldt ud (kan udvandes af medforfattere ikke); 
    taeller='publikationer' tæller distinkte publikationer (en publikation
    med flere forfattere af samme køn tælles kun én gang)."""
    if taeller == "forfatterskaber":
        tæller_data = _query_koen_forfatterskaber(filters, mode)
    else:
        tæller_data, _ = _query_koen(filters, mode, count_col="PURE_ID")

    author_data, cluster_map = _query_koen(filters, mode, count_col="ext_id")

    rate_data = {}
    for unit in tæller_data:
        rate_data[unit] = {}
        for koen in ("Kvinder", "Mænd"):
            n_taeller = tæller_data.get(unit, {}).get(koen, 0)
            n_forf = author_data.get(unit, {}).get(koen, 0)
            rate_data[unit][koen] = round(n_taeller / n_forf, 2) if n_forf > 0 else None

    return rate_data, author_data, cluster_map

def _render_koen_rate(filters, mode, taeller="forfatterskaber", min_celle=4):
    rate_data, author_data, cluster_map = _query_koen_rate(filters, mode, taeller=taeller)
    taeller_navn = "forfatterskaber" if taeller == "forfatterskaber" else "publikationer"
    if not rate_data:
        st.error("Ingen forfattere matcher de valgte filtre.")
        return

    rate_data = {
        u: cats for u, cats in rate_data.items()
        if not any(
            v < min_celle for k, v in author_data.get(u, {}).items()
            if k in ("Kvinder", "Mænd")
        )
    }
    if not rate_data:
        st.error(f"Alle enheder er skjult, da mindst ét køn har færre end {min_celle} repræsenterede overalt i det valgte udsnit.")
        return

    y_labels = list(rate_data.keys())
    group_keys = None
    if any(v is not None for v in cluster_map.values()):
        group_keys = [
            "__ku__" if lbl == "KU samlet" else cluster_map.get(lbl, "__single__")
            for lbl in y_labels
        ]

    n_kat = 2  # Kvinder, Mænd
    row_scale = max(1.0, n_kat / 3)

    if group_keys is not None:
        y_pos, tick_pos, tick_labels = _build_y_positions(y_labels, group_keys)
    else:
        y_pos = list(range(len(y_labels)))
        tick_pos, tick_labels = y_pos, y_labels
    y_pos = [y * row_scale for y in y_pos]
    tick_pos = [y * row_scale for y in tick_pos]

    total_span = (y_pos[-1] - y_pos[0]) if len(y_pos) > 1 else 0
    height = max(200, int(total_span * 55 + 150))
    yaxis_kwargs = dict(
        tickmode="array", tickvals=tick_pos, ticktext=tick_labels,
        autorange="reversed", showgrid=False, zeroline=False,
    )
    offsets, bar_width = grouped_bar_offsets(n_kat, span=_INTRA_GAP * row_scale)

    fig = go.Figure()
    for i, koen in enumerate(("Kvinder", "Mænd")):
        y_vals = [y + offsets[i] for y in y_pos]
        x_vals = [rate_data[u].get(koen) for u in y_labels]
        fig.add_trace(go.Bar(
            x=x_vals, y=y_vals, orientation="h", name=koen,
            marker=dict(color=KOEN_COLORS[koen], line=dict(color="white", width=1)),
            width=bar_width,
            text=[f"{v:.2f}" if v is not None else "" for v in x_vals],
            textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white"),
            hovertemplate=f"<b>{koen}</b><br>%{{y}}<br>%{{x:.2f}} publikationer pr. forfatter<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text=f"Publikationer pr. forfatter, pr. køn, {breakdown_label(mode)}", font=dict(size=14)),
        xaxis=dict(title="Publikationer pr. forfatter"),
        yaxis=dict(**yaxis_kwargs),
        barmode="overlay",
        plot_bgcolor="white", height=height,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(t=50, b=10, l=10, r=150),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"diversitet_koen_rate_{taeller}")
    render_table_export(
        data=rate_data, row_label="Enhed",
        filename=f"{taeller}_pr_forfatter_koen.xlsx", sheet_name=f"{taeller_navn.capitalize()} pr. køn",
        key=f"export_diversitet_koen_rate_{taeller}",
    )

def _render_koen_section(filters, mode, title_prefix, chart_mode="antal", count_col="ext_id",
                          xaxis_title="Antal forfattere", pct_denominators=None, min_celle=4):
    data, cluster_map = _query_koen(filters, mode, count_col=count_col)
    if not any(data.values()):
        st.error("Ingen forfattere matcher de valgte filtre.")
        return

    data = _filter_suppressed_units(data, min_celle)
    if pct_denominators is not None:
        pct_denominators = {u: v for u, v in pct_denominators.items() if u in data}
    if not data:
        st.error(f"Alle enheder er skjult, da mindst ét køn har færre end {min_celle} repræsenterede overalt i det valgte udsnit.")
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
        data=data, order=KOEN_ORDER, colors=KOEN_COLORS, labels=KOEN_LABELS,
        title=f"{title_prefix}, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title=xaxis_title, mode=chart_mode,
        group_keys=group_keys, legend_position="right",
        hover_unit=hover_unit, pct_denominators=pct_denominators,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"diversitet_{_slugify(title_prefix)}_{chart_mode}")
    render_table_export(
        data=data, row_label="Enhed", col_labels=KOEN_LABELS,
        filename=f"{_slugify(title_prefix)}_{chart_mode}.xlsx",
        sheet_name=title_prefix[:31],
        key=f"export_diversitet_{_slugify(title_prefix)}_{chart_mode}",
    )

def _render_statsbg_section(filters, mode, chart_mode="antal", count_col="ext_id",
                             xaxis_title="Antal forfattere", min_celle=4):
    """MIN_CELLE-suppression her er simplere end for Køn: kun ÉN kategori
    (ikke to gensidigt udelukkende) skal være under grænsen, for at hele
    enheden skjules - undgår komplementær afsløring på samme måde, siden
    syv kategorier gør det langt sværere at udlede et enkelt tal ved
    subtraktion end med kun to."""
    data, cluster_map = _query_statsbg(filters, mode, count_col=count_col)
    if not any(data.values()):
        st.error("Ingen forfattere matcher de valgte filtre.")
        return

    data = {
        u: cats for u, cats in data.items()
        if not any(v < min_celle for k, v in cats.items() if k != "Ukendt")
    }
    if not data:
        st.error(f"Alle enheder er skjult, da mindst én region har færre end {min_celle} repræsenterede overalt i det valgte udsnit.")
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
        data=data, order=STATSBG_ORDER, colors=STATSBG_COLORS, labels=STATSBG_LABELS,
        title=f"Statsborgerskabsfordeling, {breakdown_label(mode)}, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title=xaxis_title, mode=chart_mode,
        group_keys=group_keys, legend_position="right", hover_unit=hover_unit,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"diversitet_statsbg_{count_col}_{chart_mode}")
    render_table_export(
        data=data, row_label="Enhed", col_labels=STATSBG_LABELS,
        filename=f"statsborgerskabsfordeling_{count_col}_{chart_mode}.xlsx",
        sheet_name="Statsborgerskabsfordeling",
        key=f"export_diversitet_statsbg_{count_col}_{chart_mode}",
    )

@st.cache_data(show_spinner="Henter data...")
def _query_koen_pr_stil(filters):
    """Kønsfordeling KRYDSET med stillingsgruppe - Stillingsgruppe som
    x-akse, køn som stakkede kategorier. Viser hele det aktuelt valgte
    fakultet/institut-udsnit samlet, ikke yderligere opdelt pr. enhed."""
    where_sql, params = _base_where(filters)
    sql = f"""
        SELECT Stil, ({_KOEN_CATEGORY_SQL}) AS koen, COUNT(DISTINCT ext_id) AS n
        FROM pubs
        {where_sql}
        GROUP BY Stil, koen
    """
    rows = get_cursor().execute(sql, params).fetchall()
    result = {}
    for stil, koen, n in rows:
        result.setdefault(stil, {})[koen] = n
    return result

@st.cache_data(show_spinner="Henter data...")
def _query_koen_forfatterskaber(filters, mode):
    """Antal FORFATTERSKABER (ikke distinkte publikationer) pr. køn - hver
    række i pubs er én persons rolle på én publikation, matcher samme
    'forfatterskab'-definition som Forfatterprofils Korr-sektion."""
    where_sql, params = _base_where(filters)
    dims = hier_cols(mode)
    n_dims = len(dims)
    select_dims = (", ".join(f"{col} AS dim_{i}" for i, col in enumerate(dims)) + ", ") if dims else ""
    group_by = ", ".join(str(i) for i in range(1, n_dims + 2)) if dims else "1"

    sql = f"""
        SELECT {select_dims}({_KOEN_CATEGORY_SQL}) AS cat, COUNT(*) AS n
        FROM pubs
        {where_sql}
        GROUP BY {group_by}
    """
    rows = get_cursor().execute(sql, params).fetchall()

    result = {}
    for row in rows:
        dim_values = row[:n_dims]
        cat, n = row[n_dims], row[n_dims + 1]
        dim_label = " | ".join(str(v) for v in reversed(dim_values)) if dim_values else "KU samlet"
        result.setdefault(dim_label, {})[cat] = n

    if mode == "F" and show_ku_samlet(filters):
        ku_sql = f"SELECT ({_KOEN_CATEGORY_SQL}) AS cat, COUNT(*) AS n FROM pubs {where_sql} GROUP BY 1"
        ku_rows = get_cursor().execute(ku_sql, params).fetchall()
        result = {"KU samlet": dict(ku_rows), **result}

    return result

@st.cache_data(show_spinner="Henter data...")
def _query_koensfordeling_trend(filters):
    """Antal personer pr. køn, år for år - KU samlet, eller ét linjepar pr.
    valgt fakultet, hvis specifikke fakulteter er eksplicit valgt. Ignorerer
    bevidst sidepanelets årsinterval; øvrige filtre gælder stadig."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    base_where = f"""
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
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

    if not filters.get('fakultet_explicit', False):
        sql = f"SELECT Year, ({_KOEN_CATEGORY_SQL}) AS koen, COUNT(DISTINCT ext_id) AS n FROM pubs {base_where} GROUP BY 1, 2"
        rows = get_cursor().execute(sql, params).fetchall()
        result = {}
        for year, koen, n in rows:
            result.setdefault(year, {})[f"KU samlet ({koen})"] = n
        return result

    result = {}
    for fak in filters['fakultet']:
        fak_where = base_where + " AND Fak = ?"
        rows = get_cursor().execute(
            f"SELECT Year, ({_KOEN_CATEGORY_SQL}) AS koen, COUNT(DISTINCT ext_id) AS n FROM pubs {fak_where} GROUP BY 1, 2",
            params + [fak],
        ).fetchall()
        for year, koen, n in rows:
            result.setdefault(year, {})[f"{fak} ({koen})"] = n
    return result

@st.cache_data(show_spinner="Henter data...")
def _query_koen_trend_generic(filters, count_expr):
    """Delt forespørgsel til ALLE fem trend-grafer - count_expr styrer om
    der tælles forfattere, publikationer eller forfatterskaber. 'Ukendt'
    køn ekskluderes altid i selve SQL'en her, aldrig kun bagefter."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    sql = f"""
        SELECT Year, ({_KOEN_CATEGORY_SQL}) AS koen, {count_expr} AS n
        FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year IS NOT NULL
          AND ({ac_sql})
          AND Koen IN ('K', 'M')
        GROUP BY 1, 2
        ORDER BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    result = {}
    for year, koen, n in rows:
        result.setdefault(year, {})[koen] = n
    return result


@st.cache_data(show_spinner="Henter data...")
def _query_koen_trend(filters):
    return _query_koen_trend_generic(filters, "COUNT(DISTINCT ext_id)")


@st.cache_data(show_spinner="Henter data...")
def _query_pub_koen_trend(filters):
    return _query_koen_trend_generic(filters, "COUNT(DISTINCT PURE_ID)")


@st.cache_data(show_spinner="Henter data...")
def _query_pub_total_trend(filters):
    """Samlet antal ALLE publikationer år for år - selvstændig, udelt nævner
    til 'Publikationer pr. køn over tid's Andel (%), samme princip som
    _query_koen_totals bruger til søjlediagrammet."""
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
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year IS NOT NULL
          AND ({ac_sql})
        GROUP BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    return dict(rows)


@st.cache_data(show_spinner="Henter data...")
def _query_koen_stil_trend(filters):
    """Kønsfordeling KRYDSET med stillingsgruppe, år for år - én serie pr.
    (stillingsgruppe, køn). Ekskluderer 'Ukendt' stillingsgruppe, samme
    konvention som Forfatterprofils tilsvarende trend-sektion."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    sql = f"""
        SELECT Year, Stil, ({_KOEN_CATEGORY_SQL}) AS koen, COUNT(DISTINCT ext_id) AS n
        FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year IS NOT NULL
          AND ({ac_sql})
          AND COALESCE(Stil, 'Ukendt') != 'Ukendt'
          AND Koen IN ('K', 'M')
        GROUP BY 1, 2, 3
        ORDER BY 1
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    result = {}
    for year, stil, koen, n in rows:
        result.setdefault(year, {})[f"{stil} ({koen})"] = n
    return result


@st.cache_data(show_spinner="Henter data...")
def _query_koen_rate_trend(filters, taeller="forfatterskaber"):
    """Rate pr. forfatter, år for år - samme tæller/nævner-princip som
    _query_koen_rate, bare pr. år i stedet for pr. organisatorisk enhed."""
    if taeller == "forfatterskaber":
        taeller_data = _query_koen_trend_generic(filters, "COUNT(*)")
    else:
        taeller_data = _query_pub_koen_trend(filters)
    forfatter_data = _query_koen_trend(filters)

    rate_data = {}
    for year in taeller_data:
        rate_data[year] = {}
        for koen in ("Kvinder", "Mænd"):
            n_taeller = taeller_data.get(year, {}).get(koen, 0)
            n_forf = forfatter_data.get(year, {}).get(koen, 0)
            rate_data[year][koen] = round(n_taeller / n_forf, 2) if n_forf > 0 else None
    return rate_data, forfatter_data


def _render_koen_trend_tab(filters, min_celle=4):
    trend_data_raw = _query_koen_trend(filters)
    if not trend_data_raw:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    trend_data = {}
    for year, cats in trend_data_raw.items():
        if any(v < min_celle for v in cats.values()):
            continue
        trend_data[year] = cats

    if not trend_data:
        st.error(f"Alle år er skjult, da mindst ét køn har færre end {min_celle} repræsenterede i hele perioden.")
        return

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_koen",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=_KOEN_ORDER_TREND, colors=KOEN_COLORS, labels=KOEN_LABELS,
        title="Kønsfordeling over tid (hele perioden)",
        mode=chart_mode, hover_unit="forfattere",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_koen_trend")
    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År", col_labels=KOEN_LABELS,
        filename="koensfordeling_udvikling_over_tid.xlsx",
        sheet_name="Kønsfordeling trend",
        key="export_diversitet_koen_trend",
    )

@st.cache_data(show_spinner="Henter data...")
def _query_statsbg_trend(filters):
    """Statsborgerskabsfordeling år for år - respekterer sidepanelets
    Fak/Inst/Stil-filtre, viser ét linjesæt (én linje pr. region), ikke
    opdelt pr. enhed, samme princip som _query_koen_trend."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    sql = f"""
        SELECT Year, Statsbg, COUNT(DISTINCT ext_id) AS n
        FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
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
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    result = {}
    for year, raw_code, n in rows:
        gruppe = _statsbg_region_da(raw_code)
        year_dict = result.setdefault(year, {})
        year_dict[gruppe] = year_dict.get(gruppe, 0) + n
    return result

@st.cache_data(show_spinner="Henter data...")
def _query_statsbg_pub_trend(filters):
    """Se _query_statsbg's PURE_ID-gren for forklaring af, hvorfor
    deduplikering sker i Python pr. region, ikke i SQL pr. rå landekode."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    sql = f"""
        SELECT Year, Statsbg, PURE_ID
        FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
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
    rows = get_cursor().execute(sql, params).fetchall()

    pub_sets = {}
    for year, raw_code, pure_id in rows:
        gruppe = _statsbg_region_da(raw_code)
        pub_sets.setdefault(year, {}).setdefault(gruppe, set()).add(pure_id)

    return {year: {g: len(s) for g, s in groups.items()} for year, groups in pub_sets.items()}


@st.cache_data(show_spinner="Henter data...")
def _query_statsbg_forfatterskaber_trend(filters):
    """Antal FORFATTERSKABER pr. statsborgerskabsregion, år for år - samme
    princip som _query_koen_trend_generic med COUNT(*)."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])
    sql = f"""
        SELECT Year, Statsbg, COUNT(*) AS n
        FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt') IN ({ph(filters['peer'])})
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
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    result = {}
    for year, raw_code, n in rows:
        gruppe = _statsbg_region_da(raw_code)
        year_dict = result.setdefault(year, {})
        year_dict[gruppe] = year_dict.get(gruppe, 0) + n
    return result

@st.cache_data(show_spinner="Henter data...")
def _query_statsbg_rate_trend(filters, taeller="forfatterskaber"):
    """Rate pr. forfatter, år for år, pr. statsborgerskabsregion - samme
    princip som _query_koen_rate_trend, generaliseret til alle regioner."""
    if taeller == "forfatterskaber":
        taeller_data = _query_statsbg_forfatterskaber_trend(filters)
    else:
        taeller_data = _query_statsbg_pub_trend(filters)
    forfatter_data = _query_statsbg_trend(filters)

    rate_data = {}
    for year in taeller_data:
        rate_data[year] = {}
        for gruppe in _STATSBG_RATE_KATEGORIER:
            n_taeller = taeller_data.get(year, {}).get(gruppe, 0)
            n_forf = forfatter_data.get(year, {}).get(gruppe, 0)
            rate_data[year][gruppe] = round(n_taeller / n_forf, 2) if n_forf > 0 else None
    return rate_data, forfatter_data


def _render_statsbg_pub_trend_tab(filters, min_celle=4):
    trend_data_raw = _query_statsbg_pub_trend(filters)
    author_data_raw = _query_statsbg_trend(filters)
    pub_totals = _query_pub_total_trend(filters)
    if not trend_data_raw:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    trend_data, denom = {}, {}
    for year, cats in trend_data_raw.items():
        real = author_data_raw.get(year, {})
        if any(v < min_celle for k, v in real.items() if k != "Ukendt"):
            continue
        trend_data[year] = cats
        denom[year] = pub_totals.get(year, 0)

    if not trend_data:
        st.error(f"Alle år er skjult, da mindst én region har færre end {min_celle} repræsenterede i hele perioden.")
        return

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_statsbg_pub",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=STATSBG_ORDER, colors=STATSBG_COLORS, labels=STATSBG_LABELS,
        title="Publikationer pr. statsborgerskabsregion over tid (hele perioden)",
        mode=chart_mode, hover_unit="publikationer",
        pct_denominators=denom,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_statsbg_pub_trend")
    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År", col_labels=STATSBG_LABELS,
        filename="publikationer_pr_statsbg_udvikling_over_tid.xlsx",
        sheet_name="Publikationer pr. statsbg trend",
        key="export_diversitet_statsbg_pub_trend",
    )


def _render_statsbg_rate_trend(filters, taeller="forfatterskaber", min_celle=4):
    rate_data, forfatter_data = _query_statsbg_rate_trend(filters, taeller=taeller)
    if not rate_data:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    suppressed = {}
    for year, cats in rate_data.items():
        real = forfatter_data.get(year, {})
        if any(v < min_celle for k, v in real.items() if k != "Ukendt"):
            continue
        suppressed[year] = cats
    rate_data = suppressed

    if not rate_data:
        st.error(f"Alle år er skjult, da mindst én region har færre end {min_celle} repræsenterede i hele perioden.")
        return

    taeller_navn = "forfatterskaber" if taeller == "forfatterskaber" else "publikationer"
    years_sorted = sorted(rate_data.keys())

    fig = go.Figure()
    for gruppe in _STATSBG_RATE_KATEGORIER:
        y_vals = [rate_data[y].get(gruppe) for y in years_sorted]
        fig.add_trace(go.Scatter(
            x=years_sorted, y=y_vals, mode="lines+markers", name=gruppe,
            line=dict(color=STATSBG_COLORS[gruppe], width=2.5),
            hovertemplate=f"<b>{gruppe}</b><br>%{{x}}<br>%{{y:.2f}} {taeller_navn} pr. forfatter<extra></extra>",
        ))
    fig.update_layout(
        title=dict(text=f"{taeller_navn.capitalize()} pr. forfatter, pr. statsborgerskabsregion, over tid (hele perioden)", font=dict(size=14)),
        xaxis=dict(title="Udgivelsesår", dtick=1),
        yaxis=dict(title=f"{taeller_navn.capitalize()} pr. forfatter"),
        plot_bgcolor="white", height=420,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(t=50, b=10, l=10, r=150),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"diversitet_statsbg_rate_trend_{taeller}")
    render_table_export(
        data={str(y): cats for y, cats in rate_data.items()},
        row_label="År",
        filename=f"{taeller}_pr_forfatter_statsbg_over_tid.xlsx", sheet_name=f"{taeller_navn.capitalize()} trend",
        key=f"export_diversitet_statsbg_rate_trend_{taeller}",
    )

def _render_statsbg_trend_tab(filters, min_celle=4):
    trend_data_raw = _query_statsbg_trend(filters)
    if not trend_data_raw:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    trend_data = {}
    for year, cats in trend_data_raw.items():
        if any(v < min_celle for k, v in cats.items() if k != "Ukendt"):
            continue
        trend_data[year] = cats

    if not trend_data:
        st.error(f"Alle år er skjult, da mindst én region har færre end {min_celle} repræsenterede i hele perioden.")
        return

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_statsbg",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=STATSBG_ORDER, colors=STATSBG_COLORS, labels=STATSBG_LABELS,
        title="Statsborgerskabsfordeling over tid (hele perioden)",
        mode=chart_mode, hover_unit="forfattere",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_statsbg_trend")
    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År", col_labels=STATSBG_LABELS,
        filename="statsborgerskab_udvikling_over_tid.xlsx",
        sheet_name="Statsborgerskab trend",
        key="export_diversitet_statsbg_trend",
    )

def _render_pub_koen_trend_tab(filters, min_celle=4):
    trend_data_raw = _query_pub_koen_trend(filters)
    forfatter_data = _query_koen_trend(filters)
    pub_totals = _query_pub_total_trend(filters)
    if not trend_data_raw:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    trend_data, denom = {}, {}
    for year, cats in trend_data_raw.items():
        real = forfatter_data.get(year, {})
        if any(v < min_celle for v in real.values()):
            continue
        trend_data[year] = cats
        denom[year] = pub_totals.get(year, 0)

    if not trend_data:
        st.error(f"Alle år er skjult, da mindst ét køn har færre end {min_celle} repræsenterede i hele perioden.")
        return

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_pub_koen",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    fig = fig_year_trend(
        trend_data, order=_KOEN_ORDER_TREND, colors=KOEN_COLORS, labels=KOEN_LABELS,
        title="Publikationer pr. køn over tid (hele perioden)",
        mode=chart_mode, hover_unit="publikationer",
        pct_denominators=denom,
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_pub_koen_trend")
    render_table_export(
        data={str(year): cats for year, cats in sorted(trend_data.items())},
        row_label="År", col_labels=KOEN_LABELS,
        filename="publikationer_pr_koen_udvikling_over_tid.xlsx",
        sheet_name="Publikationer pr. køn trend",
        key="export_diversitet_pub_koen_trend",
    )


def _render_koen_stil_trend(filters, min_celle=4):
    trend_data_raw = _query_koen_stil_trend(filters)
    if not trend_data_raw:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    all_series = {s for cats in trend_data_raw.values() for s in cats}
    base_stils = {}
    for s in all_series:
        base = s.rsplit(" (", 1)[0]
        base_stils.setdefault(base, []).append(s)

    trend_data = {}
    for year, cats in trend_data_raw.items():
        trend_data[year] = {}
        for stil, series_list in base_stils.items():
            values = {s: cats.get(s) for s in series_list if cats.get(s) is not None}
            if values and any(v < min_celle for v in values.values()):
                continue
            for s in series_list:
                if s in cats:
                    trend_data[year][s] = cats[s]

    if not any(trend_data.values()):
        st.error(f"Alle stillingsgrupper er skjult, da mindst ét køn har færre end {min_celle} repræsenterede i hele perioden.")
        return

    visning = st.radio(
        "Vis som", options=["Antal", "Andel (%)"],
        index=0, horizontal=True, key="trend_mode_koen_stil",
    )
    chart_mode = "pct" if visning == "Andel (%)" else "antal"

    years_sorted = sorted(trend_data.keys())
    series = sorted({s for cats in trend_data.values() for s in cats})
    stil_colors = stillingsgruppe_colors()

    fig = go.Figure()
    for s in series:
        stil = s.rsplit(" (", 1)[0]
        koen = s.rsplit("(", 1)[-1].rstrip(")")
        color = stil_colors.get(stil, "#666666")
        y_vals, hover_n = [], []
        for year in years_sorted:
            n = trend_data.get(year, {}).get(s, 0)
            total = sum(trend_data.get(year, {}).values()) or 1
            pct = round(100 * n / total, 1)
            y_vals.append(pct if chart_mode == "pct" else n)
            hover_n.append(n)
        fig.add_trace(go.Scatter(
            x=years_sorted, y=y_vals, mode="lines+markers", name=s,
            line=dict(color=color, dash="dash" if koen == "Mænd" else None, width=2.5),
            customdata=hover_n,
            hovertemplate=f"<b>{s}</b><br>%{{x}}<br>%{{y}}{'%' if chart_mode == 'pct' else ''}<br>%{{customdata:,}} forfattere<extra></extra>",
        ))
    fig.update_layout(
        title=dict(text="Kønsfordeling pr. stillingsgruppe over tid (hele perioden)", font=dict(size=14)),
        xaxis=dict(title="År", dtick=1),
        yaxis=dict(
            title="Andel (%)" if chart_mode == "pct" else "Antal forfattere",
            range=[0, 100] if chart_mode == "pct" else None,
        ),
        plot_bgcolor="white", height=420,
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02, traceorder="normal"),
        margin=dict(t=50, b=60, l=10, r=220),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_koen_stil_trend")
    render_table_export(
        data={str(y): cats for y, cats in trend_data.items()},
        row_label="År", filename="koen_stil_udvikling_over_tid.xlsx", sheet_name="Køn x Stil trend",
        key="export_diversitet_koen_stil_trend",
    )


def _render_koen_rate_trend(filters, taeller="forfatterskaber", min_celle=4):
    rate_data, forfatter_data = _query_koen_rate_trend(filters, taeller=taeller)
    if not rate_data:
        st.error("Ingen publikationer matcher de valgte filtre.")
        return

    suppressed = {}
    for year, cats in rate_data.items():
        real = forfatter_data.get(year, {})
        if any(v < min_celle for v in real.values()):
            continue
        suppressed[year] = cats
    rate_data = suppressed

    if not rate_data:
        st.error(f"Alle år er skjult, da mindst ét køn har færre end {min_celle} repræsenterede i hele perioden.")
        return

    taeller_navn = "forfatterskaber" if taeller == "forfatterskaber" else "publikationer"
    years_sorted = sorted(rate_data.keys())

    fig = go.Figure()
    for koen in ("Kvinder", "Mænd"):
        y_vals = [rate_data[y].get(koen) for y in years_sorted]
        fig.add_trace(go.Scatter(
            x=years_sorted, y=y_vals, mode="lines+markers", name=koen,
            line=dict(color=KOEN_COLORS[koen], width=2.5),
            hovertemplate=f"<b>{koen}</b><br>%{{x}}<br>%{{y:.2f}} {taeller_navn} pr. forfatter<extra></extra>",
        ))
    fig.update_layout(
        title=dict(text=f"{taeller_navn.capitalize()} pr. forfatter, pr. køn, over tid (hele perioden)", font=dict(size=14)),
        xaxis=dict(title="Udgivelsesår", dtick=1),
        yaxis=dict(title=f"{taeller_navn.capitalize()} pr. forfatter"),
        plot_bgcolor="white", height=420,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        margin=dict(t=50, b=10, l=10, r=150),
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=f"diversitet_koen_rate_trend_{taeller}")
    render_table_export(
        data={str(y): cats for y, cats in rate_data.items()},
        row_label="År",
        filename=f"{taeller}_pr_forfatter_koen_over_tid.xlsx", sheet_name=f"{taeller_navn.capitalize()} trend",
        key=f"export_diversitet_koen_rate_trend_{taeller}",
    )


def render(filters: dict) -> None:
    st.subheader("Diversitet")

    MIN_CELLE = 0  # hardcodet, ikke justerbar - en brugerstyret tærskel ville underminere selve beskyttelsen

    st.markdown(
f"""
Fanen belyser den demografiske sammensætning af KU's publicerende forfattere, opdelt i 
to selvstændige sektioner, som vælges nedenfor: 

- **Køn** - bestemt ud fra CPR-nummer, se metodenote nedenfor
- **Statsborgerskab** - grupperet i regioner, dog med Danmark som sin egen kategori

Begge sektioner følger samme opbygning: en fordeling, en krydsning med stillingsgruppe, 
en publikationsbaseret variant og udvikling over tid. 

Enheder, hvor mindst én kategori har **færre end {MIN_CELLE}** repræsenterede, vises ikke - hverken
i graferne eller i eksport-tabellerne.
"""
    )

    _mode = filters.get("mode", "F")

    _kategori = st.radio(
        "Vælg mellem", options=["Køn", "Statsborgerskab"],
        index=0, horizontal=True, key="diversitet-kategori" 
    )

    if _kategori == "Køn":
        # --- Kønsfordeling (personer) ---
        st.markdown(

"""
---

### Køn

Køn er bestemt ud fra det sidste ciffer i forfatterens CPR-nummer: et **ulige** ciffer
klassificeres som mand, et **lige** ciffer som kvinde. 

##### Kønsfordeling

Fordelingen af KU's publicerende forfattere på køn, opgjort på tværs af de valgte
organisatoriske niveauer. Andelen (%) angiver, hvor stor en del af enhedens **publicerende
forfattere** der er af hvert køn.
"""
    )
        _koen_totals = _query_koen_totals(filters, _mode, count_col="ext_id")
        _tab_kf_n, _tab_kf_p = st.tabs(["Antal", "Andel (%)"])
        with _tab_kf_n:
            _render_koen_section(filters, _mode, "Kønsfordeling", chart_mode="antal",
                                pct_denominators=_koen_totals, min_celle=MIN_CELLE)
        with _tab_kf_p:
            _render_koen_section(filters, _mode, "Kønsfordeling", chart_mode="pct",
                                pct_denominators=_koen_totals, min_celle=MIN_CELLE)


        # --- Kønsfordeling pr. stillingsgruppe ---
        _koen_stil_unit_label = _current_unit_label(filters)
        _koen_stil_ku_note = (
            " Ingen specifikke enheder er valgt i sidepanelet - og figuren nedenfor viser kønsfordelingen pr. stillingsgruppe på tværs af **hele KU**."
            if _koen_stil_unit_label == "KU samlet" else ""
        )

        st.markdown("---")
        st.markdown(
f"""
##### Kønsfordeling pr. stillingsgruppe

Her krydser vi kønsfordelingen med stillingsgruppe - gør det muligt at se, om kønsbalancen ændrer
sig hen over karrieretrin (f.eks. fra ph.d. til professor), i stedet for kun et samlet
KU-gennemsnit, der kan skjule den slags mønstre. Viser altid det aktuelt valgte
fakultet/institut-udsnit samlet, ikke yderligere opdelt pr. enhed. 

{_koen_stil_ku_note}
"""
        )
        _koen_stil_data_raw = _query_koen_pr_stil(filters)
        _koen_stil_data = _filter_suppressed_units(_koen_stil_data_raw, MIN_CELLE)
        if not any(_koen_stil_data_raw.values()):
            st.error("Ingen publikationer matcher de valgte filtre.")
        elif not _koen_stil_data:
            st.error(f"Alle stillingsgrupper er skjult, da mindst ét køn har færre end {MIN_CELLE} repræsenterede overalt.")
        else:
            _tab_ks_n, _tab_ks_p = st.tabs(["Antal", "Andel (%)"])
            _unit_label = _current_unit_label(filters)
            with _tab_ks_n:
                fig = fig_hbar_stacked(
                    data=_koen_stil_data, order=KOEN_ORDER, colors=KOEN_COLORS, labels=KOEN_LABELS,
                    title=f"Kønsfordeling pr. stillingsgruppe, {_unit_label}", xaxis_title="Antal forfattere",
                    mode="antal", legend_position="right", hover_unit="forfattere",
                )
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_koen_stil_antal")
            with _tab_ks_p:
                fig = fig_hbar_stacked(
                    data=_koen_stil_data, order=KOEN_ORDER, colors=KOEN_COLORS, labels=KOEN_LABELS,
                    title=f"Kønsfordeling pr. stillingsgruppe, {_unit_label}", xaxis_title="Andel (%)",
                    mode="pct", legend_position="right", hover_unit="forfattere",
                )
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_koen_stil_pct")
            render_table_export(
                data=_koen_stil_data, row_label="Stillingsgruppe", col_labels=KOEN_LABELS,
                filename="koen_pr_stillingsgruppe.xlsx", sheet_name="Køn pr. stillingsgruppe",
                key="export_diversitet_koen_stil",
            )

        # --- Publikationer pr. køn ---
        st.markdown("---")
        st.markdown(
"""
##### Publikationer pr. køn

I modsætning til sektionerne ovenfor tælles her **publikationer**, ikke personer: en
publikation med forfattere af begge køn tælles med under **begge**.

**Eksempel**: Er kvinder med på 40 % af alle publikationer, betyder det ikke, at kvinder har
skrevet de 40 % alene - en publikation kan tælle med under begge køn på én gang.

**Gabet mellem de to sidste faner** ('Publikationer pr. forfatter' og 'Forfatterskaber
pr. forfatter') er en indikator for, hvor meget forfattere af samme køn skriver sammen med
hinanden - begge tal kan afspejle kønnets produktivitet:

- **Publikationer pr. forfatter** er forholdet mellem kønnets samlede pulje af distinkte
publikationer og antal forfattere af det køn. 
- **Forfatterskaber pr. forfatter** er det reelle gennemsnit af, hvor mange publikationer
hver enkelt person selv har bidraget til. 

Ligger de to tal tæt på hinanden, har kønnet sjældent en anden forfatter af **samme**
som medforfatter på samme artikel. Er gabet stort, sker det oftere. 
"""
        )
        _pub_koen_totals = _query_koen_totals(filters, _mode, count_col="PURE_ID")
        _tab_pk_n, _tab_pk_p, _tab_pk_r_pub, _tab_pk_r_fs = st.tabs(
            ["Antal", "Andel (%)", "Publikationer pr. forfatter", "Forfatterskaber pr. forfatter"]
        )
        with _tab_pk_n:
            _render_koen_section(filters, _mode, "Publikationer pr. køn", chart_mode="antal",
                                count_col="PURE_ID", xaxis_title="Antal publikationer",
                                pct_denominators=_pub_koen_totals, min_celle=MIN_CELLE)
        with _tab_pk_p:
            _render_koen_section(filters, _mode, "Publikationer pr. køn", chart_mode="pct",
                                count_col="PURE_ID", xaxis_title="Antal publikationer",
                                pct_denominators=_pub_koen_totals, min_celle=MIN_CELLE)
        with _tab_pk_r_pub:
            st.markdown(
"""
Antal **distinkte publikationer** med mindst én forfatter af det pågældende køn, divideret med
antal forfattere af det køn. En publikation med flere forfattere af samme køn tælles kun 
**én** gang - raten undervuderer derfor grupper, der ofte publicerer sammen med eget køn. 
"""
            )
            _render_koen_rate(filters, _mode, taeller="publikationer", min_celle=MIN_CELLE)
        with _tab_pk_r_fs:
            st.markdown(
"""
Antal **forfatterskaber** for det pågældende køn, divideret med antal forfattere af det køn. 
"""
            )
            _render_koen_rate(filters, _mode, taeller="forfatterskaber", min_celle=MIN_CELLE)

        # --- Kønsfordeling over tid ---
        _koen_rate_unit_label = _current_unit_label(filters)
        _koen_rate_ku_note = (
            "Siden ingen enheder er valgt i sidepanelet, dækker graferne nedenfor **hele KU**."
            if _koen_rate_unit_label == "KU samlet" else "" 
        )

        st.markdown("---")
        st.markdown(
f"""
#### Udvikling i køn over tid

Graferne dækker altid **hele den tilgængelige periode**, uanset det valgte årsinterval -
sidepanelets øvrige filtre gælder stadig. Er intet valgt i sidepanelet, dækker graferne hele
KU; er f.eks. kun HUM valgt, viser graferne udelukkende udviklingen for HUM. 

**Bemærk:** Enkelte år kan mangle i en linje, hvis mindst ét køn det år havde færre end
{MIN_CELLE} repræsenterede - resten af perioden vises stadig. Brug derfor linjernes overordnede 
tendens, ikke enkeltårs absolutte tal, til at vurdere udviklingen. 

{_koen_rate_ku_note}
"""
        )
        (_tab_trend_kf, _tab_trend_ks, _tab_trend_pk,
        _tab_trend_pr_pub, _tab_trend_pr_fs) = st.tabs([
            "Kønsfordeling", "Kønsfordeling pr. stillingsgruppe", "Publikationer pr. køn",
            "Publikationer pr. forfatter", "Forfatterskaber pr. forfatter",
        ])
        with _tab_trend_kf:
            _render_koen_trend_tab(filters, min_celle=MIN_CELLE)
        with _tab_trend_ks:
            _render_koen_stil_trend(filters, min_celle=MIN_CELLE)
        with _tab_trend_pk:
            _render_pub_koen_trend_tab(filters, min_celle=MIN_CELLE)
        with _tab_trend_pr_pub:
            _render_koen_rate_trend(filters, taeller="publikationer", min_celle=MIN_CELLE)
        with _tab_trend_pr_fs:
            _render_koen_rate_trend(filters, taeller="forfatterskaber", min_celle=MIN_CELLE)

    else:

        # --- Statsborgerskab (endnu ikke bygget) ---
        st.markdown(
"""
---

### Statsborgerskab 

Fordelingen af KU's publicerende forfattere på statsborgerskab er grupperet efter **region**, frem for enkelte lande. 
Danmark vises som sin egen kategori, adskilt fra resten af Europa.

##### Statsborgerskabsfordeling

Fordelingen af KU's publicerede forfattere på statsborgerskab, opgjort på tværs af de
valgte organisatoriske niveauer. Andelen (%) angiver, hvor stor en del af enhedens
**publicerende forfattere** der har statsborgerskab i den pågældende region. 

**Eksempel**: Er 15 % af SUND's forfattere kategoriseret under 'Asien', betyder det, at 
15 % af de personer, der har publiceret fra SUND i perioden, har et asiatisk statsborgerskab. 
"""
        )
        _tab_sb_n, _tab_sb_p = st.tabs(["Antal", "Andel (%)"])
        with _tab_sb_n:
            _render_statsbg_section(filters, _mode, chart_mode="antal", min_celle=MIN_CELLE)
        with _tab_sb_p:
            _render_statsbg_section(filters, _mode, chart_mode="pct", min_celle=MIN_CELLE)

        _statsbg_stil_label = _current_unit_label(filters)
        _statsbg_stil_note = (
            " Siden ingen enheder er valgt i sidepanelet, vises figuren nedenfor for **hele KU**."
            if _statsbg_stil_label == "KU samlet" else ""
        )
        st.markdown("---")
        st.markdown(
f"""
##### Statsborgerskab pr. stillingsgruppe

Krydser statsborgerskabsfordelingen med stillingsgruppe - samme princip som
Kønsfordeling pr. stillingsgruppe ovenfor. Viser altid det aktuelt valgte
fakultet/institut-udsnit samlet, ikke yderligere opdelt pr. enhed.

{_statsbg_stil_note}
"""
        )
        _statsbg_stil_data_raw = _query_statsbg_pr_stil(filters)
        _statsbg_stil_data = {
            stil: cats for stil, cats in _statsbg_stil_data_raw.items()
            if not any(v < MIN_CELLE for k, v in cats.items() if k != "Ukendt")
        }
        if not any(_statsbg_stil_data_raw.values()):
            st.error("Ingen publikationer matcher de valgte filtre.")
        elif not _statsbg_stil_data:
            st.error(f"Alle stillingsgrupper er skjult, da mindst én region har færre end {MIN_CELLE} repræsenterede overalt.")
        else:
            _tab_sbs_n, _tab_sbs_p = st.tabs(["Antal", "Andel (%)"])
            _unit_label = _current_unit_label(filters)
            with _tab_sbs_n:
                fig = fig_hbar_stacked(
                    data=_statsbg_stil_data, order=STATSBG_ORDER, colors=STATSBG_COLORS, labels=STATSBG_LABELS,
                    title=f"Statsborgerskab pr. stillingsgruppe, {_unit_label}", xaxis_title="Antal forfattere",
                    mode="antal", legend_position="right", hover_unit="forfattere",
                )
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_statsbg_stil_antal")
            with _tab_sbs_p:
                fig = fig_hbar_stacked(
                    data=_statsbg_stil_data, order=STATSBG_ORDER, colors=STATSBG_COLORS, labels=STATSBG_LABELS,
                    title=f"Statsborgerskab pr. stillingsgruppe, {_unit_label}", xaxis_title="Andel (%)",
                    mode="pct", legend_position="right", hover_unit="forfattere",
                )
                st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key="diversitet_statsbg_stil_pct")
            render_table_export(
                data=_statsbg_stil_data, row_label="Stillingsgruppe", col_labels=STATSBG_LABELS,
                filename="statsbg_pr_stillingsgruppe.xlsx", sheet_name="Statsbg pr. stillingsgruppe",
                key="export_diversitet_statsbg_stil",
            )

        # --- Publikationer pr. statsborgerskab ---
        st.markdown("---")
        st.markdown(
"""
##### Publikationer pr. statsborgerskab

Samme princip som Publikationer pr. køn: tæller **publikationer**, ikke personer - en
publikation med forfattere fra flere regioner tælles med under **alle** de involverede.

**Gabet mellem de to rate-faner** ('Publikationer pr. forfatter' og 'Forfatterskaber pr. 
forfatter') er en indikator for, hvor meget forfattere fra samme region skriver sammen
med hinanden, ikke for regionens produktivitet i sig selv: 

- **Publikationer pr. forfatter** er forholdet mellem regionens samlede pulje af distinkte
publikationer og antal forfattere i regionen. 
- **Forfatterskaber pr. forfatter** er det reelle gennemsnit af, hvor mange publikationer
hver enkelt person selv har bidraget til. 

Er tallene tæt på hinanden, har forfattere fra regionen sjældent en anden forfatter fra
**samme** region som medforfatter på samme artikel. Er gabet stort, sker det oftere. 

**Eksempel**: Har Danmark 3.15 publikationer pr. forfatter, men 5.46 forfatterskaber pr.
forfatter, betyder det relativt store gab, at danske forfattere ofte deler artikel med 
**andre** danskere. Ligger de to tal tæt på hinanden for en anden region, betyder det 
typisk, at hver artikel kun har **én** forfatter fra netop den region, uanset hvor mange
forfattere regionen har totalt. 

"""
        )
        _pub_statsbg_totals = _query_koen_totals(filters, _mode, count_col="PURE_ID")
        _tab_psb_n, _tab_psb_p, _tab_psb_r_pub, _tab_psb_r_fs = st.tabs(
            ["Antal", "Andel (%)", "Publikationer pr. forfatter", "Forfatterskaber pr. forfatter"]
        )
        with _tab_psb_n:
            _render_statsbg_section(filters, _mode, chart_mode="antal", count_col="PURE_ID",
                                    xaxis_title="Antal publikationer", min_celle=MIN_CELLE)
        with _tab_psb_p:
            _render_statsbg_section(filters, _mode, chart_mode="pct", count_col="PURE_ID",
                                    xaxis_title="Antal publikationer", min_celle=MIN_CELLE)
        with _tab_psb_r_pub:
            _render_statsbg_rate(filters, _mode, taeller="publikationer", min_celle=MIN_CELLE)
        with _tab_psb_r_fs:
            _render_statsbg_rate(filters, _mode, taeller="forfatterskaber", min_celle=MIN_CELLE)

        _statsbg_trend_label = _current_unit_label(filters)
        _statsbg_trend_note = (
            "Figurene nedenfor vises for **hele KU**, da ingen specifikke enheder er valgt i sidepanelet."
            if _statsbg_trend_label == "KU samlet" else ""
        )

        st.markdown("---")
        st.markdown(
f"""
##### Udvikling i statsborgerskaber over tid

Udviklingen i statsborgerskabsfordelingen år for år - dækker altid **hele den tilgængelige
periode**, uanset det valgte årsinterval; sidepanelets øvrige filtre gælder stadig. Samme
fire faner som ovenfor (Statsborgerskabsfordeling, Publikationer pr. region, og de to
rate-faner), nu vist som udvikling over tid i stedet for et enkelt øjebliksbillede.

**Bemærk:** enkelte år kan mangle i en linje, hvis mindst én region det år havde færre end
{MIN_CELLE} repræsenterede - resten af perioden vises stadig. Brug derfor linjernes
overordnede tendens, ikke enkeltårs absolutte tal, til at vurdere udviklingen.

{_statsbg_stil_note}
"""
        )
        (_tab_sbt_f, _tab_sbt_p, _tab_sbt_r_pub, _tab_sbt_r_fs) = st.tabs([
            "Statsborgerskabsfordeling", "Publikationer pr. region",
            "Publikationer pr. forfatter", "Forfatterskaber pr. forfatter",
        ])
        with _tab_sbt_f:
            _render_statsbg_trend_tab(filters, min_celle=MIN_CELLE)
        with _tab_sbt_p:
            _render_statsbg_pub_trend_tab(filters, min_celle=MIN_CELLE)
        with _tab_sbt_r_pub:
            _render_statsbg_rate_trend(filters, taeller="publikationer", min_celle=MIN_CELLE)
        with _tab_sbt_r_fs:
            _render_statsbg_rate_trend(filters, taeller="forfatterskaber", min_celle=MIN_CELLE)