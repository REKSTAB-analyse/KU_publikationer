from data.loader import get_pairs_cursor
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import plotly.graph_objects as go

import streamlit as st
from config import SAMPUBLICERING_URL, doi_filter_sql, FAC_ORDER
from components.charts import fig_year_trend, fig_hbar_stacked, PLOTLY_CONFIG
from components.export import render_table_export
from components.colors import build_faculty_colors, ku_color_sequence, stillingsgruppe_colors
from components.charts import _hls_gradient

_NIVEAU_EDGE_COL = {"fak": "Edge_type_fak", "inst": "Edge_type_inst", "stil": "Edge_type_stil"}
_NIVEAU_LABEL = {"fak": "fakultet", "inst": "institut", "stil": "stillingsgruppe"}

@st.cache_data(show_spinner="Henter data...")
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

def _top_units_base_where(filters):
    """Samme generelle filtre som _samarbejde_base_where, men UDEN
    organisatorisk for-selektion - denne sektion rangerer ALLE enheder på
    niveauet, ikke kun dem valgt i sidepanelet. Respekterer i stedet
    sidepanelets årsinterval, siden dette er et øjebliksbillede, ikke en
    trend-graf."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    where_sql = f"""
        WHERE Year BETWEEN ? AND ?
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt')
              IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND COALESCE(Open_Access, 'Unknown')
              IN ({ph(filters['open_access'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND Antal_forfattere BETWEEN ? AND ?
    """
    params = (
        [filters['aar_fra'], filters['aar_til']] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['min_forfattere'], filters['max_forfattere']]
    )
    return where_sql, params

def _top_units_base_where_alltime(filters):
    """Samme som _top_units_base_where, men UDEN årsinterval-begrænsning -
    dækker hele den tilgængelige periode, samme princip som fanens øvrige
    trend-grafer (fx _query_intra_inter_trend)."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    where_sql = f"""
        WHERE Year IS NOT NULL
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND COALESCE(NULLIF(Peer_review, ''), 'Ukendt')
              IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND COALESCE(Open_Access, 'Unknown')
              IN ({ph(filters['open_access'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND Antal_forfattere BETWEEN ? AND ?
    """
    params = (
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['min_forfattere'], filters['max_forfattere']]
    )
    return where_sql, params

_NIVEAU_UNIT_COLS = {"fak": ("Fak_1", "Fak_2"), "inst": ("Inst_1", "Inst_2")}

def _unit_pairs_extra_filter(niveau, kun_tvaerfakultaert):
    """Delt SQL-fragment + parametre til at begrænse fakultetspar
    (niveau='fak') til de seks FAC_ORDER-definerede fakulteter, og
    institutpar til kun tværfakultære, når kun_tvaerfakultaert=True -
    genbruges af BÅDE _query_unit_pairs og _query_unit_pairs_trend, så de
    to forespørgsler aldrig kan komme ud af trit med hinanden."""
    ph_fac = ", ".join(["?" for _ in FAC_ORDER])
    if niveau == "fak":
        return f" AND Fak_1 IN ({ph_fac}) AND Fak_2 IN ({ph_fac})", list(FAC_ORDER) * 2
    if niveau == "inst" and kun_tvaerfakultaert:
        return f" AND Fak_1 != Fak_2 AND Fak_1 IN ({ph_fac}) AND Fak_2 IN ({ph_fac})", list(FAC_ORDER) * 2
    return "", []

@st.cache_data(show_spinner="Henter data...")
def _query_unit_pairs(filters, metric, niveau, kun_tvaerfakultaert=False):
    """Antal forfatterpar/publikationer PR. PAR AF FORSKELLIGE enheder (fx
    SCIENCE-SUND, eller to institutter), rækkefølge-uafhængigt - A-B og B-A
    summeres sammen. Kun par, hvor de to enheder er FORSKELLIGE, indgår.
    Filtrering af niveau/tværfakultært sker via _unit_pairs_extra_filter."""
    col_1, col_2 = _NIVEAU_UNIT_COLS[niveau]
    where_sql, params = _top_units_base_where(filters)

    count_expr = (
        "COUNT(*)" if metric == "forfatterpar"
        else "COUNT(DISTINCT PURE_ID)"
    )
    extra_filter, extra_params = _unit_pairs_extra_filter(niveau, kun_tvaerfakultaert)

    sql = f"""
        SELECT {col_1} AS u1, {col_2} AS u2, {count_expr} AS n
        FROM pairs
        {where_sql}
          AND {col_1} != '' AND {col_2} != '' AND {col_1} != {col_2}
          {extra_filter}
        GROUP BY {col_1}, {col_2}
    """
    data_source = filters.get("data_source", "CURIS")
    rows = get_pairs_cursor(data_source).execute(sql, params + extra_params).fetchall()

    result = {}
    for u1, u2, n in rows:
        key = tuple(sorted([u1, u2]))
        result[key] = result.get(key, 0) + n
    return result

def _unit_pairs_change_data(filters, metric, niveau, kun_tvaerfakultaert=False):
    """Par-udvikling mellem sidepanelets valgte start- og slutår
    (aar_fra/aar_til) - genbruger _query_unit_pairs_trend (som allerede
    beregner ALLE pars tal år for år, over hele perioden) og trækker blot
    de to relevante år ud, i stedet for at bygge en ny SQL-forespørgsel.
    rel_change er None, hvor n_from = 0 (procentvis vækst er udefineret
    fra 0)."""
    year_from, year_to = filters['aar_fra'], filters['aar_til']
    trend_data_all = _query_unit_pairs_trend(filters, metric, niveau, kun_tvaerfakultaert)

    cats_from = trend_data_all.get(year_from, {})
    cats_to = trend_data_all.get(year_to, {})
    all_keys = set(cats_from) | set(cats_to)

    result = []
    for key in all_keys:
        n_from = cats_from.get(key, 0)
        n_to = cats_to.get(key, 0)
        abs_change = n_to - n_from
        rel_change = round(100 * (n_to - n_from) / n_from, 1) if n_from > 0 else None
        result.append({
            "key": key, "n_from": n_from, "n_to": n_to,
            "abs_change": abs_change, "rel_change": rel_change,
        })
    return result, year_from, year_to

@st.cache_data(show_spinner="Henter data...")
def _query_unit_pairs_trend(filters, metric, niveau, kun_tvaerfakultaert=False):
    """Samme klassificering som _query_unit_pairs, men ÅR FOR ÅR over HELE
    perioden - ignorerer bevidst sidepanelets årsinterval, øvrige filtre
    gælder stadig. Henter ALLE kvalificerende par (ikke kun top X), så både
    selve top X-parrenes udvikling OG en korrekt totalnævner til Andel (%)
    kan udledes i Python bagefter."""
    col_1, col_2 = _NIVEAU_UNIT_COLS[niveau]
    where_sql, params = _top_units_base_where_alltime(filters)
    count_expr = (
        "COUNT(*)" if metric == "forfatterpar"
        else "COUNT(DISTINCT PURE_ID)"
    )
    extra_filter, extra_params = _unit_pairs_extra_filter(niveau, kun_tvaerfakultaert)

    sql = f"""
        SELECT Year, {col_1} AS u1, {col_2} AS u2, {count_expr} AS n
        FROM pairs
        {where_sql}
          AND {col_1} != '' AND {col_2} != '' AND {col_1} != {col_2}
          {extra_filter}
        GROUP BY Year, {col_1}, {col_2}
    """
    data_source = filters.get("data_source", "CURIS")
    rows = get_pairs_cursor(data_source).execute(sql, params + extra_params).fetchall()

    result = {}
    for year, u1, u2, n in rows:
        key = tuple(sorted([u1, u2]))
        year_dict = result.setdefault(year, {})
        year_dict[key] = year_dict.get(key, 0) + n
    return result

@st.cache_data(show_spinner=False)
def _institut_to_fak(data_source):
    """Statisk opslag institut -> moderfakultet, udledt direkte af pairs-
    tabellens Fak_1/Inst_1 (og Fak_2/Inst_2) - bruges til at lade et
    eksplicit FAKULTETSVALG 'arve' ned til dets underliggende institutter,
    når institutparrenes kandidatliste filtreres."""
    sql = """
        SELECT DISTINCT Inst_1 AS inst, Fak_1 AS fak FROM pairs WHERE Inst_1 != ''
        UNION
        SELECT DISTINCT Inst_2 AS inst, Fak_2 AS fak FROM pairs WHERE Inst_2 != ''
    """
    rows = get_pairs_cursor(data_source).execute(sql).fetchall()
    return {inst: fak for inst, fak in rows}

def _render_unit_pairs(filters, metric, niveau):
    kun_tvaerfak = False
    if niveau == "inst":
        visning = st.radio(
            "Institutsamarbejde",
            options=["Alle institutpar", "Kun institutpar på tværs af fakulteter"],
            index=0, horizontal=True,
            key="sampub_toppar_tvaerfak",
        )
        kun_tvaerfak = (visning == "Kun institutpar på tværs af fakulteter")

    top_x = st.number_input(
        "Vis top-x samarbejdspar", min_value=1, max_value=50, value=4,
        step=1, key=f"sampub_toppar_n_{niveau}",
    )

    pairs_data = _query_unit_pairs(filters, metric, niveau, kun_tvaerfak)
    if not pairs_data:
        st.error("Ingen data matcher de valgte filtre.")
        return

    # Nævneren ("Andel af alt tværgående samarbejde") dækker ALTID alle
    # kvalificerende par, uanset om specifikke enheder er valgt i
    # sidepanelet. Er der derimod eksplicit valgt fakultet(er)/institut(ter)
    # på DETTE niveau, begrænses selve KANDIDATLISTEN (det, der rangeres og
    # vises) til kun par, hvor mindst én af de to enheder er blandt de
    # valgte - den valgte enhed skal altså udgøre den ene "side" af parret.
    total_alle_par = sum(pairs_data.values()) or 1

    # Fakultetsniveauet begrænses UDELUKKENDE af et eksplicit fakultetsvalg
    # - et institutvalg påvirker aldrig fakultetsparrene. Institutniveauet
    # begrænses derimod af BÅDE et eksplicit institutvalg OG et eksplicit
    # fakultetsvalg - vælges et fakultet, "arver" alle dets underliggende
    # institutter valget, så deres institutpar også indgår.
    selected_units = set()
    if niveau == "fak":
        if filters.get("fakultet_explicit", False):
            selected_units = set(filters["fakultet"])
    else:  # niveau == "inst"
        if filters.get("institutter_explicit", False):
            selected_units |= set(filters["institutter"])
        # Bruger fakultet_explicit_direct (KUN et reelt brugervalg i selve
        # Fakultet-boksen), ikke fakultet_explicit - ellers ville et
        # institutvalg, der blot AFLEDER ét fakultet i FI-mode, fejlagtigt
        # trække ALLE institutter under det afledte fakultet ind, i stedet
        # for kun det/de faktisk valgte institutter.
        if filters.get("fakultet_explicit_direct", False):
            inst_to_fak = _institut_to_fak(filters.get("data_source", "CURIS"))
            selected_units |= {
                inst for inst, fak in inst_to_fak.items()
                if fak in filters["fakultet"]
            }

    if selected_units:
        candidate_items = [
            (key, n) for key, n in pairs_data.items()
            if key[0] in selected_units or key[1] in selected_units
        ]
        st.caption(
            "Viser kun par, hvor mindst én enhed er blandt de valgte i sidepanelet "
            "(institutter under et valgt fakultet indgår også). Andelen (%) regnes "
            "fortsat ud af **alt** tværgående samarbejde på niveauet."
        )
    else:
        candidate_items = list(pairs_data.items())

    top_pairs = sorted(candidate_items, key=lambda kv: -kv[1])[:top_x]

    rows = [
        {
            "Enhed A": u1,
            "Enhed B": u2,
            "Antal": n,
            "Andel af alt tværgående samarbejde (%)":
                round(100 * n / total_alle_par, 1),
        }
        for (u1, u2), n in top_pairs
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    export_data = {
        f"{u1} - {u2}": {
            "Antal": n,
            "Andel (%)": round(100 * n / total_alle_par, 1),
        }
        for (u1, u2), n in top_pairs
    }
    #render_table_export(
        #data=export_data, row_label="Samarbejdspar",
        #col_labels={"Antal": "Antal", "Andel (%)": "Andel (%)"},
        #filename=f"sampub_top{top_x}_par_{niveau}_{metric}.xlsx",
        #sheet_name="Top samarbejdspar",
        #key=f"export_sampub_toppar_{niveau}_{metric}_{kun_tvaerfak}",
    #)

    st.markdown(
"""
##### Udvikling for de viste top-samarbejdspar

Viser, hvordan **netop disse** par har udviklet sig - dækker altid hele den tilgængelige
periode, uanset sidepanelets valgte årsinterval; øvrige filtre gælder stadig. Ændres top
X-antallet eller årsintervallet ovenfor, opdateres linjerne til de nye top-par.
"""
    )
    top_pair_keys = [key for key, _ in top_pairs]
    _render_unit_pairs_trend(filters, metric, niveau, kun_tvaerfak, top_pair_keys)

def _render_unit_pairs_trend(filters, metric, niveau, kun_tvaerfakultaert, top_pair_keys):
    """Viser, hvordan de AKTUELT VISTE top X-samarbejdspar (baseret på
    sidepanelets valgte årsinterval) har udviklet sig over HELE perioden -
    selve rangeringen ændres ikke af denne graf, kun de valgte parres
    antal/andel år for år."""
    if not top_pair_keys:
        return

    trend_data_all = _query_unit_pairs_trend(filters, metric, niveau, kun_tvaerfakultaert)
    if not trend_data_all:
        st.error("Ingen data matcher de valgte filtre.")
        return

    years_sorted = sorted(trend_data_all.keys())
    pair_labels = {key: f"{key[0]} - {key[1]}" for key in top_pair_keys}
    order = [pair_labels[key] for key in top_pair_keys]

    # Nævner til Andel (%): ALLE kvalificerende par det år, ikke kun top X
    year_totals = {year: sum(cats.values()) or 1 for year, cats in trend_data_all.items()}

    trend_data = {}
    for year in years_sorted:
        cats = trend_data_all.get(year, {})
        trend_data[year] = {pair_labels[key]: cats.get(key, 0) for key in top_pair_keys}

    palette = ku_color_sequence(len(top_pair_keys))
    colors = {pair_labels[key]: palette[i] for i, key in enumerate(top_pair_keys)}

    def _build_and_render(chart_mode):
        pct_denominators = year_totals if chart_mode == "pct" else None
        fig = fig_year_trend(
            trend_data, order=order, colors=colors, labels={l: l for l in order},
            title=f"Top samarbejdspar over tid ({_NIVEAU_LABEL[niveau]}, {metric})",
            yaxis_title=f"Antal {metric}",
            mode=chart_mode, hover_unit=metric,
            pct_denominators=pct_denominators,
        )
        st.plotly_chart(
            fig, width="stretch", config=PLOTLY_CONFIG,
            key=f"sampub_toppar_trend_chart_{niveau}_{metric}_{chart_mode}",
        )
        render_table_export(
            data={str(year): cats for year, cats in sorted(trend_data.items())},
            row_label="År",
            filename=f"sampub_toppar_trend_{niveau}_{metric}_{chart_mode}.xlsx",
            sheet_name="Top samarbejdspar over tid",
            key=f"export_sampub_toppar_trend_{niveau}_{metric}_{chart_mode}",
        )

    _tab_antal, _tab_pct = st.tabs(["Antal", "Andel (%)"])
    with _tab_antal:
        _build_and_render("antal")
    with _tab_pct:
        _build_and_render("pct")

def _render_unit_pairs_change(filters, metric, niveau):
    kun_tvaerfak = False
    if niveau == "inst":
        visning = st.radio(
            "Institutsamarbejde",
            options=["Alle institutpar", "Kun institutpar på tværs af fakulteter"],
            index=0, horizontal=True,
            key=f"sampub_parvaekst_tvaerfak_{niveau}",
        )
        kun_tvaerfak = (visning == "Kun institutpar på tværs af fakulteter")

    change_data, year_from, year_to = _unit_pairs_change_data(filters, metric, niveau, kun_tvaerfak)
    if not change_data or year_from == year_to:
        st.error("Vælg et årsinterval med mindst to forskellige år i sidepanelet for at se udviklingen.")
        return

    # Samme asymmetriske arve-logik som _render_unit_pairs: et fakultetsvalg
    # begrænser BÅDE fakultets- og institutparrene (institutter under det
    # valgte fakultet arver valget); et institutvalg begrænser KUN
    # institutparrene, aldrig fakultetsparrene.
    selected_units = set()
    if niveau == "fak":
        if filters.get("fakultet_explicit", False):
            selected_units = set(filters["fakultet"])
    else:  # niveau == "inst"
        if filters.get("institutter_explicit", False):
            selected_units |= set(filters["institutter"])
        if filters.get("fakultet_explicit_direct", False):
            inst_to_fak = _institut_to_fak(filters.get("data_source", "CURIS"))
            selected_units |= {
                inst for inst, fak in inst_to_fak.items()
                if fak in filters["fakultet"]
            }

    if selected_units:
        change_data = [
            r for r in change_data
            if r["key"][0] in selected_units or r["key"][1] in selected_units
        ]
        if not change_data:
            st.warning("Ingen par matcher de valgte enheder i sidepanelet.")
            return
        st.caption(
            "Viser kun par, hvor mindst én enhed er blandt de valgte i sidepanelet "
            "(institutter under et valgt fakultet indgår også)."
        )

    top_x = st.number_input(
        "Antal par at vise (top voksende + top aftagende)", min_value=1, max_value=25,
        value=4, step=1, key=f"sampub_parvaekst_n_{niveau}",
    )

    def _build_and_render(chart_mode):
        field = "abs_change" if chart_mode == "abs" else "rel_change"
        rows = [r for r in change_data if r[field] is not None]
        rows_sorted = sorted(rows, key=lambda r: r[field])
        top_declining = rows_sorted[:top_x]
        top_growing = rows_sorted[-top_x:] if rows_sorted else []

        shown, seen = [], set()
        for r in top_declining + top_growing:
            if r["key"] not in seen:
                shown.append(r)
                seen.add(r["key"])
        shown.sort(key=lambda r: r[field])

        if not shown:
            st.warning("Ingen par at vise for denne visning.")
            return

        labels = [f"{r['key'][0]} ↔ {r['key'][1]}" for r in shown]
        values = [r[field] for r in shown]
        colors = ["#901a1e" if v < 0 else "#122947" for v in values]
        texts = [f"{v:+.1f}" if chart_mode == "abs" else f"{v:+.1f}%" for v in values]

        fig = go.Figure(go.Bar(
            x=values, y=labels, orientation="h",
            marker=dict(color=colors),
            text=texts, textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white"),
            hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(
                text=f"{'Absolut' if chart_mode == 'abs' else 'Relativ'} vækst i {metric}, {year_from}-{year_to}",
                font=dict(size=14),
            ),
            xaxis=dict(title=f"Ændring i {metric} ({year_from}→{year_to})" if chart_mode == "abs" else "Ændring (%)"),
            yaxis=dict(autorange="reversed"),
            plot_bgcolor="white",
            height=max(200, len(shown) * 30 + 100),
            margin=dict(t=50, b=10, l=10, r=10),
        )
        st.plotly_chart(
            fig, width="stretch", config=PLOTLY_CONFIG,
            key=f"sampub_parvaekst_{niveau}_{metric}_{chart_mode}",
        )

        with st.expander("Se tabel"):
            table_rows = [
                {
                    "Enhed A": r["key"][0], "Enhed B": r["key"][1],
                    str(year_from): r["n_from"], str(year_to): r["n_to"],
                    "Absolut ændring": r["abs_change"],
                    "Relativ ændring (%)": r["rel_change"],
                }
                for r in sorted(change_data, key=lambda r: -r["abs_change"])
            ]
            st.dataframe(table_rows, width="stretch", hide_index=True)
            render_table_export(
                data={
                    f"{r['key'][0]} - {r['key'][1]}": {
                        str(year_from): r["n_from"], str(year_to): r["n_to"],
                        "Absolut ændring": r["abs_change"],
                        "Relativ ændring (%)": r["rel_change"],
                    }
                    for r in change_data
                },
                row_label="Samarbejdspar",
                filename=f"sampub_parvaekst_{niveau}_{metric}_{chart_mode}.xlsx",
                sheet_name="Par-udvikling",
                key=f"export_sampub_parvaekst_{niveau}_{metric}_{chart_mode}",
            )

    _tab_abs, _tab_rel = st.tabs(["Absolut ændring", "Relativ ændring (%)"])
    with _tab_abs:
        _build_and_render("abs")
    with _tab_rel:
        _build_and_render("rel")

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

def _kpi_base_where(filters):
    """Samme OR-match som _samarbejde_base_where (mindst én af de to
    personer matcher sidepanelets Fak/Inst/Stil), men begrænset til
    sidepanelets valgte ÅRSINTERVAL - i modsætning til resten af fanens
    trend-grafer, som altid dækker hele perioden."""
    ph = lambda lst: ", ".join(["?" for _ in lst])
    where_sql = f"""
        WHERE Year BETWEEN ? AND ?
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
        [filters['aar_fra'], filters['aar_til']] +
        filters['typer'] + filters['sprog'] + filters['peer'] +
        filters['indholdstyper'] + filters['open_access'] +
        [filters['min_forfattere'], filters['max_forfattere']] +
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper']
    )
    return where_sql, params

@st.cache_data(show_spinner="Henter data...")
def _query_kpi_summary(filters):
    """Antal solo/intra/inter-publikationer, summeret over sidepanelets
    valgte årsinterval - PÅ BÅDE fakultet- og institutniveau samtidig, så
    render-funktionen selv kan vælge, hvilke af de to niveauer der vises,
    afhængigt af sidepanelets F/I/FI-mode. Klassificeringen matcher
    _query_internt_samarbejde_by_unit (solo, via Edge_type_inst) og
    _query_intra_inter_trend (intra/inter, via Edge_type_fak/Edge_type_inst) -
    enhver publikation falder i præcis ÉN intra/inter-kategori pr. niveau."""
    where_sql, params = _kpi_base_where(filters)
    data_source = filters.get("data_source", "CURIS")
    sql = f"""
        WITH pub_class AS (
            SELECT PURE_ID,
                   MAX(CASE WHEN Edge_type_fak = 'inter' THEN 1 ELSE 0 END) AS has_inter_fak,
                   MAX(CASE WHEN Edge_type_inst = 'inter' THEN 1 ELSE 0 END) AS has_inter_inst,
                   MAX(CASE WHEN Edge_type_inst = 'solo' THEN 1 ELSE 0 END) AS is_solo
            FROM pairs
            {where_sql}
            GROUP BY PURE_ID
        )
        SELECT
            COUNT(*) AS total,
            SUM(is_solo) AS solo_n,
            SUM(CASE WHEN is_solo = 0 AND has_inter_fak = 0 THEN 1 ELSE 0 END) AS intra_fak_n,
            SUM(CASE WHEN is_solo = 0 AND has_inter_fak = 1 THEN 1 ELSE 0 END) AS inter_fak_n,
            SUM(CASE WHEN is_solo = 0 AND has_inter_inst = 0 THEN 1 ELSE 0 END) AS intra_inst_n,
            SUM(CASE WHEN is_solo = 0 AND has_inter_inst = 1 THEN 1 ELSE 0 END) AS inter_inst_n
        FROM pub_class
    """
    row = get_pairs_cursor(data_source).execute(sql, params).fetchone()
    total, solo_n, intra_fak_n, inter_fak_n, intra_inst_n, inter_inst_n = row
    total = total or 0
    solo_n = solo_n or 0
    return {
        "total": total,
        "internt": total - solo_n,
        "intra_fak": intra_fak_n or 0,
        "inter_fak": inter_fak_n or 0,
        "intra_inst": intra_inst_n or 0,
        "inter_inst": inter_inst_n or 0,
    }

@st.cache_data(show_spinner="Henter data...")
def _query_kpi_summary_pairs(filters):
    """Samme som _query_kpi_summary, men talt i FORFATTERPAR - hver række i
    pairs ER allerede ét forfatterpar, så klassificeringen kan læses direkte
    af Edge_type_fak/Edge_type_inst, uden PURE_ID-aggregering."""
    where_sql, params = _kpi_base_where(filters)
    data_source = filters.get("data_source", "CURIS")
    sql = f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN Edge_type_inst = 'solo' THEN 1 ELSE 0 END) AS solo_n,
            SUM(CASE WHEN Edge_type_fak = 'intra' THEN 1 ELSE 0 END) AS intra_fak_n,
            SUM(CASE WHEN Edge_type_fak = 'inter' THEN 1 ELSE 0 END) AS inter_fak_n,
            SUM(CASE WHEN Edge_type_inst = 'intra' THEN 1 ELSE 0 END) AS intra_inst_n,
            SUM(CASE WHEN Edge_type_inst = 'inter' THEN 1 ELSE 0 END) AS inter_inst_n
        FROM pairs
        {where_sql}
    """
    row = get_pairs_cursor(data_source).execute(sql, params).fetchone()
    total, solo_n, intra_fak_n, inter_fak_n, intra_inst_n, inter_inst_n = row
    total = total or 0
    solo_n = solo_n or 0
    return {
        "total": total,
        "internt": total - solo_n,
        "intra_fak": intra_fak_n or 0,
        "inter_fak": inter_fak_n or 0,
        "intra_inst": intra_inst_n or 0,
        "inter_inst": inter_inst_n or 0,
    }

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


@st.cache_data(show_spinner="Henter data...")
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

def _render_kpi_summary(filters, metric):
    if metric == "forfatterpar":
        kpi = _query_kpi_summary_pairs(filters)
        enhed_navn, enhed_flertal = "forfatterpar", "forfatterpar"
    else:
        kpi = _query_kpi_summary(filters)
        enhed_navn, enhed_flertal = "publikation", "publikationer"

    total = kpi["total"]
    if not total:
        st.error("Ingen data matcher de valgte filtre i den valgte periode.")
        return

    def _pct(n):
        return round(100 * n / total, 1)

    _mode = filters.get("mode", "F")
    _vis_fak = "F" in _mode
    _vis_inst = "I" in _mode
    if not _vis_fak and not _vis_inst:
        _vis_fak = True  # fallback, samme som Top X-sektionens standardvalg

    st.markdown(
f"""
#### Nøgletal for den valgte periode

Summeret over sidepanelets valgte årsinterval ({filters['aar_fra']}-{filters['aar_til']}),
talt i **{enhed_flertal}** - indsnævr årsintervallet i sidepanelet for at se tallene for
et enkelt år. Andelen (%) regnes ud af alle {enhed_flertal} i perioden (inkl. solo). Solo-
{enhed_flertal} (kun én intern forfatter) bidrager med **0** til hvert nøgletals tæller,
men tælles stadig med i nævneren - de trækker derfor andelen (%) nedad, uden selv at
optræde i noget af de viste antal.
"""
    )

    kort = [("Internt samarbejde", kpi["internt"])]
    if _vis_fak:
        kort.append(("Intrafakultært samarbejde", kpi["intra_fak"]))
        kort.append(("Interfakultært samarbejde", kpi["inter_fak"]))
    if _vis_inst:
        kort.append(("Intra-institut samarbejde", kpi["intra_inst"]))
        kort.append(("Inter-institut samarbejde", kpi["inter_inst"]))

    cols = st.columns(len(kort))
    for col, (label, n) in zip(cols, kort):
        with col:
            st.metric(label, f"{n:,}")
            st.caption(f"{_pct(n)}% af alle {enhed_flertal}")

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
            yaxis=dict(title="Andel (%)" if chart_mode == "pct" else "Antal publikationer", range=[0, 100] if chart_mode == "pct" else None),
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

@st.cache_data(show_spinner="Henter data...")
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

@st.cache_data(show_spinner="Henter data...")
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

@st.cache_data(show_spinner="Henter data...")
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
            yaxis=dict(title="Andel (%)" if chart_mode == "pct" else f"Antal {metric}", range=[0, 100] if chart_mode == "pct" else None),
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
            yaxis_title=f"Antal {metric}",
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
            yaxis_title=f"Antal {metric}",
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
    st.markdown(
"""
### Sampublicering

Fanen viser KU's interne sampubliceringsmønstre - hvor meget forskere fra forskellige
organisatoriske enheder skriver sammen, og hvor meget samarbejdet foregår inden for egen
enhed (*intra*) versus på tværs af enheder (*inter*). Kun **interne** medforfattere indgår; 
eksternt samarbejde med ikke-KU-parter dækkes i stedet af fanen **Eksternt samarbejde**. 

Fanen er bygget op i følgende afsnit:

- **Nøgletal for den valgte periode**: antal og andel af internt, intrafakultært/institut
og interfakultært/institut samarbejde, summeret over sidepanelets valgte årsinterval
- **Internt samarbejde**: andel af publikationer med mindst to interne forfattere, versus
solo-publikationer (kun én intern forfatter), pr. enhed
- **Fakultet / Institut / Stillingsgruppe**: intra- versus inter-fordelingen på hvert
niveau, udviklet over tid
- **Top-x samarbejdspar**: hvilke fakultets- eller institutpar, der samarbejder mest
- **Hvilke samarbejder vokser?**: hvilke par der har haft størst stigning eller fald i
samarbejde mellem sidepanelets valgte start- og slutår

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

    _render_kpi_summary(filters, _metric_arg)

    _mode = filters.get("mode", "F")
    _vis_fak_par = "F" in _mode
    _vis_inst_par = "I" in _mode

    
    st.markdown("---")

    _alle_pub = False
    if _metrik == "Publikationer":
        st.markdown(
"""
#### Internt samarbejde

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
#### Fakultet

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

    if _vis_inst_par:
        st.markdown("---")
        st.markdown(
"""#### Institut

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
"""#### Stillingsgruppe

Figuren nedenfor viser samarbejde på tværs af stillingsgrupper. **Intra** viser samarbejde inden for samme
stillingsgruppe, mens **inter** viser samarbejde på tværs af stillingsgrupper. 

Er specifikke stillingsgrupper valgt i sidepanelet, vises ét linjepar pr. valgt stillingsgruppe. 
Er ingen valgt, falder figuren tilbage til institut eller fakultet - og til 'KU samlet',
hvis intet af det heller er valgt. 

**Bemærk**: Uanset hvilken enhed, der vises, er selve intra/inter her altid baseret på 
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

    st.markdown(
"""
#### Top-x samarbejdspar

Rangerer de fakultet- eller institutpar, der samarbejdet mest. 'Antal' tæller hver publikation/forfatterpar, 
der krydser fakultets- eller institutskellet; 'Andel' angiver, hvor stor en del af **alt** tværgående
samarbejde på dette niveau dette ene samarbejdspar udgør. Niveauet (fakultet/institut) fælger sidepanelets
valg. 
"""
    )

    if _vis_fak_par and _vis_inst_par:
        st.markdown("###### Fakultetsniveau")
        _render_unit_pairs(filters, _metric_arg, "fak")
        st.markdown("###### Institutniveau")
        _render_unit_pairs(filters, _metric_arg, "inst")
    elif _vis_inst_par:
        _render_unit_pairs(filters, _metric_arg, "inst")
    else:
        _render_unit_pairs(filters, _metric_arg, "fak")
    
    st.markdown("---")
    st.markdown(
"""
#### Hvilke samarbejder vokser?

Figuren viser de par, der har haft den **største stigning** i antal forfatterpar/publikationer
fra sidepanelets valgte startår til slutår. Positive værdier indikerer voksende samarbejde;
negative indikerer aftagende.

Den **absolutte** ændring viser den rå forskel i forfatterpar/publikationer. Den **relative**
ændring viser procentvis vækst - nyttig for at sammenligne par med meget forskellige
udgangspunkter, men udelader par med 0 i første år.
"""
    )
    if _vis_fak_par and _vis_inst_par:
        st.markdown("###### Fakultetsniveau")
        _render_unit_pairs_change(filters, _metric_arg, "fak")
        st.markdown("###### Institutniveau")
        _render_unit_pairs_change(filters, _metric_arg, "inst")
    elif _vis_inst_par:
        _render_unit_pairs_change(filters, _metric_arg, "inst")
    else:
        _render_unit_pairs_change(filters, _metric_arg, "fak")
