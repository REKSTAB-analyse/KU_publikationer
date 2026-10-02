import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collections import Counter
import streamlit as st
import plotly.graph_objects as go
import math
from data.loader import _get_db_for_source, load_stillingsgruppe_loengrupper
from components.charts import fig_hbar_stacked, PLOTLY_CONFIG
from config import FAC_ORDER, year_range_label, doi_filter_sql, author_count_filter, STILLINGSGRUPPER
from components.export import render_table_export


def _base_where_and_params(filters, alias=""):
    """
    Identisk med _base_where_and_params i oversigt.py - bruges her for at
    sikre, at Datagrundlag-fanens dæknings- og Venn-tal bruger PRÆCIS samme
    population som Oversigt-fanens 'Publikationer'-KPI. Bruges IKKE af
    _query_missing_fak/_query_field_completeness, som bevidst ser på den
    bredere, ufiltrerede Intern+årsinterval-population - ellers ville de
    aldrig kunne vise andet end 0 (en publikation uden fx fakultet kan pr.
    definition ikke bestå et Fak IN (...)-filter, og ville derfor være
    filtreret væk, før den overhovedet nåede frem til optællingen).
    """
    ph = lambda lst: ", ".join(["?" for _ in lst])
    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'], alias=alias)
    where_sql = f"""
        WHERE {alias}Intern      = 'Intern'
          AND {alias}HR_status   IN ('match', 'match_fallback')
          AND {alias}Fak         IN ({ph(filters['fakultet'])})
          AND {alias}Inst        IN ({ph(filters['institutter'])})
          AND {alias}Stil        IN ({ph(filters['stillingsgrupper'])})
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


COV_ORDER = ["Fundet", "Ikke fundet"]
COV_COLORS = {"Fundet": "#901a1e", "Ikke fundet": "#122947"}

HR_STATUS_ORDER = [
    "match", "match_fallback", "ikke_i_hr", "kun_andre_hr_aar",
    "ext_id_ikke_i_ku_id", "ingen_ext_id", "uden_for_hr_vindue",
]
HR_STATUS_LABELS = {
    "match":               "Matchet (udgivelsesåret)",
    "match_fallback":      "Matchet (nærmeste år, ±1)",
    "ikke_i_hr":           "Aldrig fundet i HR-data",
    "kun_andre_hr_aar":    "I HR, men ikke inden for ±1 år af udgivelsen",
    "ext_id_ikke_i_ku_id": "Ekstern ID ikke fundet i KU-id-mapping",
    "ingen_ext_id":        "Ingen ekstern ID registreret i CURIS",
    "uden_for_hr_vindue":  "Udgivelsesår uden for HR-dækningens periode",
}
HR_STATUS_COLORS = {
    "match":               "#901a1e",
    "match_fallback":      "#c0392b",
    "ikke_i_hr":           "#122947",
    "kun_andre_hr_aar":    "#425570",
    "ext_id_ikke_i_ku_id": "#7d8ca3",
    "ingen_ext_id":        "#a9b4c4",
    "uden_for_hr_vindue":  "#666666",
}
HR_MATCHED = {"match", "match_fallback"}


def _coverage_labels(source_name: str) -> dict:
    return {
        "Fundet": f"Fundet i {source_name}",
        "Ikke fundet": f"Ikke fundet i {source_name}",
    }


@st.cache_data(show_spinner="Henter data...")
def _query_source_coverage(source_name: str, filters: dict) -> dict:
    """
    Andel af CURIS' publikationer, der har kunnet matches til en post i den
    angivne eksterne kilde (OpenAlex eller SciVal). Begge kilder er bygget
    ved at slå CURIS' egne DOI'er op eksternt, og kan derfor pr. konstruktion
    aldrig indeholde publikationer, CURIS ikke allerede har. Bruger samme
    fulde filtersæt som Oversigt-fanens 'Publikationer'-KPI (_base_where_and_params),
    så CURIS-grundpopulationen her er tal-for-tal identisk med Oversigt.
    """
    curis_conn = _get_db_for_source("CURIS")
    source_conn = _get_db_for_source(source_name)
    where_sql, params = _base_where_and_params(filters)

    curis_rows = curis_conn.execute(f"""
        SELECT DISTINCT Fak, PURE_ID
        FROM pubs
        {where_sql}
    """, params).fetchall()

    source_ids = {
        r[0] for r in source_conn.execute("SELECT DISTINCT PURE_ID FROM pubs").fetchall()
    }

    counts = {}
    for fak, pure_id in curis_rows:
        counts.setdefault(fak, {"Fundet": 0, "Ikke fundet": 0})
        key = "Fundet" if pure_id in source_ids else "Ikke fundet"
        counts[fak][key] += 1

    total = {"Fundet": 0, "Ikke fundet": 0}
    for fak_counts in counts.values():
        for k, v in fak_counts.items():
            total[k] += v

    ordered = {"KU samlet": total}
    for fak in sorted(FAC_ORDER):
        ordered[fak] = counts.get(fak, {"Fundet": 0, "Ikke fundet": 0})

    return ordered

@st.cache_data(show_spinner="Henter data...")
def _query_missing_fak(aar_fra: int, aar_til: int) -> dict:
    """
    Antal Intern-markerede CURIS-publikationer i det valgte årsinterval, hvor
    INGEN af forfatterne har kunnet tildeles et fakultet - dvs. hver eneste
    forfatter-række for publikationen mangler Fak, typisk fordi ingen af
    forfatterne kunne findes i HR-data (Personalesammensætning) pr. 31.
    december i udgivelsesåret, eller fordi publikationen slet ikke har
    forfatteroplysninger. Har blot ÉN forfatter en fakultetstilknytning,
    tæller publikationen IKKE med her. Disse publikationer indgår ikke i
    nogen af appens fakultetsopdelte analyser og kan per definition ikke
    fordeles på fakultet - de opgøres derfor samlet, ikke pr. fakultet.
    """
    curis_conn = _get_db_for_source("CURIS")

    total = curis_conn.execute("""
        SELECT COUNT(DISTINCT PURE_ID) FROM pubs
        WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
    """, [aar_fra, aar_til]).fetchone()[0]

    missing = curis_conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT PURE_ID
            FROM pubs
            WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
            GROUP BY PURE_ID
            HAVING SUM(CASE WHEN Fak IS NOT NULL AND Fak != '' THEN 1 ELSE 0 END) = 0
        )
    """, [aar_fra, aar_til]).fetchone()[0]

    return {"total": total, "missing": missing}

@st.cache_data(show_spinner="Henter data...")
def _query_fac_coverage(aar_fra: int, aar_til: int) -> dict:
    curis_conn = _get_db_for_source("CURIS")
    ph = ", ".join(["?" for _ in FAC_ORDER])

    row = curis_conn.execute(f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN has_fak = 0 THEN 1 ELSE 0 END) AS missing,
            SUM(CASE WHEN has_fak > 0 AND has_fac_fak = 0
                     THEN 1 ELSE 0 END) AS outside_fac,
            SUM(CASE WHEN has_fac_fak > 0 THEN 1 ELSE 0 END) AS visible
        FROM (
            SELECT
                PURE_ID,
                SUM(CASE WHEN Fak IS NOT NULL AND Fak != '' THEN 1 ELSE 0 END) AS has_fak,
                SUM(CASE WHEN Fak IN ({ph}) AND Stil != 'Ukendt'
                         THEN 1 ELSE 0 END) AS has_fac_fak
            FROM pubs
            WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
            GROUP BY PURE_ID
        )
    """, list(FAC_ORDER) + [aar_fra, aar_til]).fetchone()

    total, missing, outside_fac, visible = row
    return {"total": total or 0, "missing": missing or 0,
            "outside_fac": outside_fac or 0, "visible": visible or 0}

@st.cache_data(show_spinner="Henter data...")
def _query_hr_status(aar_fra: int, aar_til: int) -> dict:
    """Antal interne forfatter-FOREKOMSTER, fordelt på HR_status, samt for
    hver kategori: antal distinkte forfattere og antal distinkte
    PUBLIKATIONER, der har MINDST ÉN forfatter med denne status -
    uafhængigt af hvilken status eventuelle andre forfattere på samme
    publikation har. En publikation kan derfor tælle med i FLERE
    kategorier samtidig (fx både 'Matchet' og 'Aldrig fundet i HR-data',
    hvis den har én forfatter af hver slags) - andelene i 'Andel af
    publikationer'-fanen summerer derfor bevidst ikke til 100%.
    Forfattere uden ext_id (status 'ingen_ext_id') udelades helt: de deler
    alle placeholderen ext_id='0' og kan ikke individuelt skelnes fra
    hinanden."""
    curis_conn = _get_db_for_source("CURIS")
    rows = curis_conn.execute("""
        SELECT HR_status, COUNT(*) AS n,
               COUNT(DISTINCT ext_id) AS n_pers,
               COUNT(DISTINCT PURE_ID) AS n_pubs
        FROM pubs
        WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
          AND ext_id != '0'
        GROUP BY HR_status
    """, [aar_fra, aar_til]).fetchall()
    return {
        status: {"entries": n, "personer": n_pers, "publikationer": n_pubs}
        for status, n, n_pers, n_pubs in rows
    }

@st.cache_data(show_spinner="Henter data...")
def _query_hr_status_totals(aar_fra: int, aar_til: int) -> dict:
    """Nævnere til HR-status-sektionens faner - alle regnet i forhold til
    HELE CURIS' interne population i perioden.

    'personer': distinkte, identificerbare interne forfattere (ext_id !=
    '0') i perioden, uanset match-status.

    'publikationer': ALLE interne publikationer i perioden, uanset match.

    'uden_match': antal af disse publikationer, hvor INGEN forfatter kunne
    HR-matches (samme population som _query_missing_fak's 'missing').

    'uden_match_uden_id': delmængde af 'uden_match', hvor SAMTLIGE interne
    forfattere mangler ext_id - disse kan ikke optræde i NOGEN bjælke i
    'Andel af publikationer'-fanen, fordi den population udelades helt fra
    _query_hr_status. De resterende ('uden_match' minus denne gruppe)
    fordeler sig på kategorierne 'Aldrig fundet i HR-data' m.fl.
    """
    curis_conn = _get_db_for_source("CURIS")

    n_pers = curis_conn.execute("""
        SELECT COUNT(DISTINCT ext_id) FROM pubs
        WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
          AND ext_id != '0'
    """, [aar_fra, aar_til]).fetchone()[0] or 0

    n_pubs = curis_conn.execute("""
        SELECT COUNT(DISTINCT PURE_ID) FROM pubs
        WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
    """, [aar_fra, aar_til]).fetchone()[0] or 0

    n_uden_match = _query_missing_fak(aar_fra, aar_til)["missing"]

    n_uden_match_uden_id = curis_conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT PURE_ID
            FROM pubs
            WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
            GROUP BY PURE_ID
            HAVING SUM(CASE WHEN ext_id != '0' THEN 1 ELSE 0 END) = 0
        )
    """, [aar_fra, aar_til]).fetchone()[0] or 0

    return {
        "personer": n_pers,
        "publikationer": n_pubs,
        "uden_match": n_uden_match,
        "uden_match_uden_id": n_uden_match_uden_id,
    }

@st.cache_data(show_spinner="Henter data...")
def _query_hr_status_per_person(aar_fra: int, aar_til: int) -> dict:
    """Klassificerer hver DISTINKT intern forfatter til NETOP ÉN
    HR-status-kategori, uanset hvor mange forekomster personen har i
    perioden - andelene her summerer derfor altid til 100%, i modsætning
    til 'Andel af forfattere'-fanen, hvor samme person kan tælle med i
    flere kategorier. Er personen matchet i mindst én forekomst, tæller
    personen som matchet (den bedste opnåede status); er personen aldrig
    matchet, får personen den mest informative fejlårsag blandt sine
    forekomster, efter samme prioritet som HR_STATUS_ORDER. Fejler en
    person to gange af samme årsag, tæller det som ÉN mislykket
    matchning, ikke to."""
    curis_conn = _get_db_for_source("CURIS")
    rows = curis_conn.execute("""
        SELECT DISTINCT ext_id, HR_status
        FROM pubs
        WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
          AND ext_id != '0'
    """, [aar_fra, aar_til]).fetchall()

    priority = {s: i for i, s in enumerate(HR_STATUS_ORDER)}
    best = {}
    for ext_id, status in rows:
        p = priority.get(status, len(HR_STATUS_ORDER))
        if ext_id not in best or p < best[ext_id][0]:
            best[ext_id] = (p, status)

    return dict(Counter(status for _, status in best.values()))

@st.cache_data(show_spinner="Henter data...")
def _query_hr_status_trend(vindue_aar: int = 15) -> dict:
    """Matchrate år for år, begrænset til de seneste `vindue_aar` år op til
    det nyeste udgivelsesår i data. CURIS indeholder spredte, langt ældre
    publikationer (og enkelte fejlregistrerede årstal) - uden denne
    begrænsning ville de presse hele den HR-relevante periode sammen i en
    smal stribe, siden matchraten pr. definition er 0% for alt ældre end
    HR-udtrækkets dækning."""
    curis_conn = _get_db_for_source("CURIS")

    max_year = curis_conn.execute("""
        SELECT MAX(Year) FROM pubs
        WHERE Intern = 'Intern' AND Year IS NOT NULL
          AND Year BETWEEN 1900 AND 2100
    """).fetchone()[0]
    if max_year is None:
        return {}
    min_year = max_year - vindue_aar

    rows = curis_conn.execute("""
        SELECT Year, HR_status, COUNT(*) AS n
        FROM pubs
        WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
        GROUP BY Year, HR_status
        ORDER BY Year
    """, [min_year, max_year]).fetchall()

    by_year = {}
    for year, status, n in rows:
        by_year.setdefault(year, {"total": 0, "matched": 0})
        by_year[year]["total"] += n
        if status in HR_MATCHED:
            by_year[year]["matched"] += n
    return by_year


@st.cache_data(show_spinner="Henter data...")
def _query_field_completeness(aar_fra: int, aar_til: int) -> dict:
    """
    For hvert felt, appens filtre bygger på (Fak/Inst/Stil/Type/Sprog/
    Indholdstype/Peer_review), tælles hvor mange Intern-publikationer i det
    valgte årsinterval der mangler feltet FULDSTÆNDIGT - dvs. INGEN af
    publikationens forfatter-rækker har en værdi. Sådanne publikationer kan
    aldrig matches af et IN(...)-filter på feltet (heller ikke når "alt" er
    valgt i sidepanelet, da valgmulighederne selv udelader tomme værdier via
    load_filter_options), og forsvinder derfor stille fra enhver analyse,
    der filtrerer på det pågældende felt.
    """
    curis_conn = _get_db_for_source("CURIS")

    row = curis_conn.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN has_fak = 0 THEN 1 ELSE 0 END) AS fak,
            SUM(CASE WHEN has_inst = 0 THEN 1 ELSE 0 END) AS inst,
            SUM(CASE WHEN has_stil = 0 THEN 1 ELSE 0 END) AS stil,
            SUM(CASE WHEN has_type = 0 THEN 1 ELSE 0 END) AS type,
            SUM(CASE WHEN has_sprog = 0 THEN 1 ELSE 0 END) AS sprog,
            SUM(CASE WHEN has_indholdstype = 0 THEN 1 ELSE 0 END) AS indholdstype,
            SUM(CASE WHEN has_fak = 0 OR has_inst = 0 THEN 1 ELSE 0 END) AS affiliering,
            SUM(CASE WHEN has_type = 0 OR has_sprog = 0 OR has_indholdstype = 0
                 THEN 1 ELSE 0 END) AS ovrige,
            SUM(CASE WHEN has_fak = 0 OR has_inst = 0 OR has_stil = 0 OR has_type = 0
                      OR has_sprog = 0 OR has_indholdstype = 0
                 THEN 1 ELSE 0 END) AS any_missing
        FROM (
            SELECT
                PURE_ID,
                MAX(CASE WHEN Fak IS NOT NULL AND Fak != '' THEN 1 ELSE 0 END) AS has_fak,
                MAX(CASE WHEN Inst IS NOT NULL AND Inst != '' THEN 1 ELSE 0 END) AS has_inst,
                MAX(CASE WHEN Stil IS NOT NULL AND Stil != '' THEN 1 ELSE 0 END) AS has_stil,
                MAX(CASE WHEN Type IS NOT NULL AND Type != '' THEN 1 ELSE 0 END) AS has_type,
                MAX(CASE WHEN Sprog IS NOT NULL AND Sprog != '' THEN 1 ELSE 0 END) AS has_sprog,
                MAX(CASE WHEN Indholdstype IS NOT NULL AND Indholdstype != '' THEN 1 ELSE 0 END) AS has_indholdstype
            FROM pubs
            WHERE Intern = 'Intern' AND Year BETWEEN ? AND ?
            GROUP BY PURE_ID
        )
    """, [aar_fra, aar_til]).fetchone()

    cols = ["total", "fak", "inst", "stil", "type", "sprog", "indholdstype",
            "affiliering", "ovrige", "any_missing"]
    return dict(zip(cols, row))

@st.cache_data(show_spinner="Henter data...")
def _query_openalex_scival_overlap(filters: dict) -> dict:
    """
    Antal CURIS-publikationer fundet i hhv. OpenAlex, SciVal, begge og ingen
    af delene - til Venn-diagrammet. Samme grundpopulation som dæknings-
    sektionerne ovenfor (_base_where_and_params - identisk med Oversigt-
    fanens 'Publikationer'-KPI), så tallene er direkte sammenlignelige.
    """
    curis_conn = _get_db_for_source("CURIS")
    openalex_conn = _get_db_for_source("OpenAlex")
    scival_conn = _get_db_for_source("SciVal")
    where_sql, params = _base_where_and_params(filters)

    curis_ids = {
        r[0] for r in curis_conn.execute(f"""
            SELECT DISTINCT PURE_ID FROM pubs
            {where_sql}
        """, params).fetchall()
    }
    openalex_ids = {r[0] for r in openalex_conn.execute("SELECT DISTINCT PURE_ID FROM pubs").fetchall()}
    scival_ids = {r[0] for r in scival_conn.execute("SELECT DISTINCT PURE_ID FROM pubs").fetchall()}

    openalex_in_scope = curis_ids & openalex_ids
    scival_in_scope = curis_ids & scival_ids

    both = openalex_in_scope & scival_in_scope
    only_openalex = openalex_in_scope - scival_in_scope
    only_scival = scival_in_scope - openalex_in_scope
    neither = curis_ids - openalex_in_scope - scival_in_scope

    return {
        "total": len(curis_ids),
        "only_openalex": len(only_openalex),
        "only_scival": len(only_scival),
        "both": len(both),
        "neither": len(neither),
    }


def _circle_intersection_area(r1: float, r2: float, d: float) -> float:
    """Areal af overlap mellem to cirkler med radier r1, r2 og centerafstand d."""
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        return math.pi * min(r1, r2) ** 2  # den ene cirkel er helt inde i den anden
    part1 = r1**2 * math.acos((d**2 + r1**2 - r2**2) / (2 * d * r1))
    part2 = r2**2 * math.acos((d**2 + r2**2 - r1**2) / (2 * d * r2))
    part3 = 0.5 * math.sqrt((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2))
    return part1 + part2 - part3


def _solve_circle_distance(r1: float, r2: float, target_area: float, max_iter: int = 100) -> float:
    """Finder centerafstanden d, der giver target_area i overlap, via bisektion -
    håndterer automatisk indlejring, delvist overlap og intet overlap."""
    lo, hi = abs(r1 - r2), r1 + r2
    if target_area <= 0:
        return hi
    if target_area >= math.pi * min(r1, r2) ** 2 - 1e-9:
        return lo
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        area = _circle_intersection_area(r1, r2, mid)
        if area > target_area:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _render_venn(counts: dict):
    """
    Arealproportionalt to-cirkel-Venn/Euler-diagram (OpenAlex vs. SciVal).
    Cirklernes areal er proportionalt med de faktiske tal, og deres indbyrdes
    afstand løses numerisk, så selve overlap-arealet også passer - håndterer
    automatisk både almindeligt overlap OG fuld indlejring (relevant, så
    længe SciVal-hentningen ikke er færdig og én mængde kan vise sig at
    ligge helt inden i den anden).
    """
    only_a, only_b, both = counts["only_openalex"], counts["only_scival"], counts["both"]
    neither, total = counts["neither"], counts["total"]

    area_a = only_a + both
    area_b = only_b + both
    max_area = max(area_a, area_b, 1)
    scale = 3.0 / math.sqrt(max_area)

    r_a = scale * math.sqrt(area_a) if area_a > 0 else 0.01
    r_b = scale * math.sqrt(area_b) if area_b > 0 else 0.01
    #d = _solve_circle_distance(r_a, r_b, both * scale**2 * math.pi)
    d = _solve_circle_distance(r_a, r_b, both * scale**2)

    center_a, center_b = 0.0, d

    fig = go.Figure()
    fig.add_shape(type="circle", x0=center_a - r_a, y0=-r_a, x1=center_a + r_a, y1=r_a,
                   fillcolor="#901a1e", opacity=0.45, line=dict(color="#901a1e"))
    fig.add_shape(type="circle", x0=center_b - r_b, y0=-r_b, x1=center_b + r_b, y1=r_b,
                   fillcolor="#122947", opacity=0.45, line=dict(color="#122947"))

    nested_b_in_a = d <= r_a - r_b + 1e-6
    nested_a_in_b = d <= r_b - r_a + 1e-6
    no_overlap = d >= r_a + r_b - 1e-6

    if only_a > 0:
        label_x = center_a - r_a * 0.45 if not nested_a_in_b else center_a
        fig.add_annotation(x=label_x, y=0, text=f"<b>Kun OpenAlex</b><br>{only_a:,}", showarrow=False, font=dict(size=13))
    if only_b > 0:
        label_x = center_b + r_b * 0.45 if not nested_b_in_a else center_b
        fig.add_annotation(x=label_x, y=0, text=f"<b>Kun SciVal</b><br>{only_b:,}", showarrow=False, font=dict(size=13))
    if both > 0:
        overlap_x = center_b if nested_b_in_a else (center_a if nested_a_in_b else (center_a + center_b) / 2)
        fig.add_annotation(x=overlap_x, y=0, text=f"<b>Begge</b><br>{both:,}", showarrow=False, font=dict(size=13, color="white"))

    caption_bits = [f"Ingen af delene: {neither:,} ud af {total:,} i alt"]
    if only_a == 0:
        caption_bits.append("Kun OpenAlex: 0")
    if only_b == 0:
        caption_bits.append("Kun SciVal: 0")
    fig.add_annotation(x=(center_a + center_b) / 2, y=-max(r_a, r_b) - 0.8,
                        text=" · ".join(caption_bits), showarrow=False, font=dict(size=11, color="#666666"))

    x_min = min(center_a - r_a, center_b - r_b) - 0.5
    x_max = max(center_a + r_a, center_b + r_b) + 0.5
    fig.update_xaxes(visible=False, range=[x_min, x_max])
    fig.update_yaxes(visible=False, range=[-max(r_a, r_b) - 1.5, max(r_a, r_b) + 0.8], scaleanchor="x", scaleratio=1)
    fig.update_layout(
        title=dict(text="Overlap mellem OpenAlex- og SciVal-dækning", font=dict(size=14)),
        plot_bgcolor="white", height=420,
        margin=dict(t=50, b=10, l=10, r=10),
        showlegend=False,
    )
    return fig

def _hr_status_fig(order, values, denom, xaxis_title, chart_title):
    labels = [HR_STATUS_LABELS.get(s, s) for s in order]
    pct_values = [100 * v / denom if denom else 0 for v in values]
    colors = [HR_STATUS_COLORS.get(s, "#666666") for s in order]

    fig = go.Figure(go.Bar(
        x=pct_values, y=labels, orientation="h",
        marker=dict(color=colors),
        text=[f"{v:,} ({p:.1f}%)" for v, p in zip(values, pct_values)],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=chart_title, font=dict(size=14)),
        xaxis=dict(title=xaxis_title,
                    range=[0, max(pct_values) * 1.25 if pct_values else 1]),
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="white",
        height=max(260, len(order) * 45 + 90),
        margin=dict(t=50, b=10, l=10, r=90),
    )
    return fig


def _render_hr_status(filters):
    data = _query_hr_status(filters['aar_fra'], filters['aar_til'])
    if not any(v["entries"] for v in data.values()):
        st.info("Ingen interne forfattere i den valgte periode.")
        return

    totals = _query_hr_status_totals(filters['aar_fra'], filters['aar_til'])
    person_status = _query_hr_status_per_person(filters['aar_fra'], filters['aar_til'])
    cov = _query_fac_coverage(filters['aar_fra'], filters['aar_til'])
    pct_pub_matched = 100 * cov["visible"] / cov["total"] if cov["total"] else 0
    n_matched_pers = person_status.get("match", 0) + person_status.get("match_fallback", 0)
    pct_pers_matched = 100 * n_matched_pers / totals["personer"] if totals["personer"] else 0

    st.markdown(
        f"De to faner nedenfor kan give meget forskellige procenttal, og det "
        f"er forventeligt: **{pct_pub_matched:.1f} %** af publikationerne har "
        f"en HR-matchet forfatter, mens kun **{pct_pers_matched:.1f} %** af de "
        "enkelte forfattere selv kunne matches. Det skyldes, at mange "
        "umatchede forfattere kun har bidraget til én eller få publikationer "
        "hver - de vejer derfor tungt i en forfatteroptælling, men fylder "
        "lidt i en publikationsoptælling. Se selv fordelingerne i figurene "
        "nedenfor."
    )

    order = [s for s in HR_STATUS_ORDER if s in data]

    _tab_personer_entydig, _tab_pub = st.tabs([
        "Andel af forfattere (hver talt én gang)", "Andel af publikationer",
    ])


    with _tab_personer_entydig:
        st.caption(
            f"Hver af de {totals['personer']:,} distinkte interne forfattere "
            "tælles her NETOP ÉN gang, uanset hvor mange forekomster de har: "
            "er personen matchet mindst én gang i perioden, tæller de som "
            "matchet; ellers får de deres mest informative fejlårsag. "
            "Andelene summerer altid til 100%."
        )
        order_pers = [s for s in HR_STATUS_ORDER if s in person_status]
        values = [person_status[s] for s in order_pers]
        fig = _hr_status_fig(
            order_pers, values, totals["personer"],
            "Andel af forfattere (%)",
            "Interne forfattere efter bedste opnåede HR-match-status",
        )
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    with _tab_pub:
        cov = _query_fac_coverage(filters['aar_fra'], filters['aar_til'])
        total_pub = cov["total"]
        pct = lambda n: 100 * n / total_pub if total_pub else 0

        st.caption(
            f"Ud af ALLE {total_pub:,} interne publikationer i "
            f"{year_range_label(filters['aar_fra'], filters['aar_til'])}: "
            "'Fundet i HR-data' har mindst én forfatter matchet til et af "
            "de seks fakulteter appen viser. 'Matchet, uden for de seks "
            "fakulteter' har mindst én HR-matchet forfatter, men KUN til "
            "andre enheder (fx Universitetsadministrationen) - disse "
            "publikationer indgår derfor ikke i appens fakultets- eller "
            "institutopdelte analyser, selvom HR-koblingen lykkedes. "
            "'Ikke fundet i HR-data' har ingen forfatter, der kunne "
            "matches overhovedet."
        )

        labels = ["Fundet i HR-data", "Matchet, uden for de seks fakulteter",
                   "Ikke fundet i HR-data"]
        values = [cov["visible"], cov["outside_fac"], cov["missing"]]
        colors = ["#901a1e", "#c98a2c", "#122947"]
        pct_values = [pct(v) for v in values]

        fig = go.Figure(go.Bar(
            x=pct_values, y=labels, orientation="h",
            marker=dict(color=colors),
            text=[f"{v:,} ({p:.1f}%)" for v, p in zip(values, pct_values)],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>%{text}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text="Publikationer efter HR-match og fakultetsdækning", font=dict(size=14)),
            xaxis=dict(title="Andel af alle interne publikationer (%)", range=[0, 110]),
            yaxis=dict(autorange="reversed"),
            plot_bgcolor="white", height=280,
            margin=dict(t=50, b=10, l=10, r=90),
        )
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    total_entries = sum(v["entries"] for v in data.values())

    export_data_personer = {
        HR_STATUS_LABELS.get(s, s): {
            "Distinkte forfattere (entydigt talt)": person_status.get(s, 0),
            "Andel af forfattere (%)": round(100 * person_status.get(s, 0) / totals["personer"], 1) if totals["personer"] else 0,
        }
        for s in order_pers
    }
    export_data_pub = {
        "Fundet i HR-data": {"Publikationer": cov["visible"], "Andel (%)": round(pct(cov["visible"]), 1)},
        "Matchet, uden for de seks fakulteter": {"Publikationer": cov["outside_fac"], "Andel (%)": round(pct(cov["outside_fac"]), 1)},
        "Ikke fundet i HR-data": {"Publikationer": cov["missing"], "Andel (%)": round(pct(cov["missing"]), 1)},
    }

    with st.expander("Se tabel: forfattere"):
        st.dataframe(
            [{"Kategori": k, **v} for k, v in export_data_personer.items()],
            width="stretch", hide_index=True,
        )
    with st.expander("Se tabel: publikationer"):
        st.dataframe(
            [{"Kategori": k, **v} for k, v in export_data_pub.items()],
            width="stretch", hide_index=True,
        )


def render(filters):
    st.markdown(
"""
### Datagrundlag 

I modsætning til appens øvrige faner handler denne ikke om at analysere KU's publikationer, 
men derimod om selve **grundlaget**, de øvrige analyser hviler på: hvor kommer data fra, 
hvordan hænger datakilderne sammen, og hvor godt dækker de hinanden?

**Dataafgrænsning**: Databehandlingen filtrerer ikke publikationer på Synlighed, 
Valideringsstatus eller Publikationsstatus - alt, CURIS har registreret, føres
uændret igennem til den endelige fil; den eneste afgrænsning sker i selve appen,
via sidepanelets filtre og kravet om en HR-matchet forfatter (se HR-kobling nedenfor).

**CURIS** er KU's egen registrering af publikationer - alt starter her, uafhængigt af DOI
eller ekstern matchning. **OpenAlex** og **SciVal/Scopus** er begge **eksterne** kilder, 
som appen beriger med CURIS-data ved at slå CURIS' DOI'er op i hver database - de kan 
derfor per konstruktion aldrig indeholde mere, end CURIS allerede har. **HR-data** kobles
separat på for at give hver forfatter en organisationel tilknytning (fakultet/institut/
stillingsgruppe) - se afsnittet nedenfor for metode og begræsninger. 


---

#### HR-kobling

Hver forfatters fakultet, institut og stillingsgruppe kommer ikke fra CURIS selv, men
kobles separat fra KU's personaledata (hentet fra datakilden Personalesammensætning på
tableau.ku.dk). Data er registreret pr. måned, og koblingen sker **år for år**:

1. For hver person og hvert år findes den enhed (fakultet og institut), hvor personen
har været registreret i **flest måneder**. Står to enheder lige, vinder den, personen
senest var tilknyttet det år.
2. Stillingsgruppen vælges blandt månederne i den vindende enhed, igen efter flest
måneder.
3. Forfatteren får den enhed og stillingsgruppe, personen havde i publikationens
udgivelsesår. Findes personen ikke i HR-data det år, bruges året før - og hvis heller
ikke det findes, året efter.

**Praktiske konsekvenser af denne metode**:

- **Jobskifte i løbet af et år fanges kun delvist**. Hele året tilskrives den enhed,
personen var tilknyttet længst - uanset hvornår på året publikationen udkom.
- **HR-data starter i 2022**. Publikationer fra 2021 er derfor koblet på forfatternes
tilknytning i 2022, og forfattere, der forlod KU inden 2022, kan ikke kobles.
- **Forfattere uden HR-data** kan ikke tildeles en enhed og indgår derfor ikke i de
organisatoriske opdelinger - se den præcise fordeling af årsager nedenfor.
""")
    with st.expander("Se hvilke løngrupper der indgår i hver stillingsgruppe"):
        st.markdown(
"""
Appens 'Stillingsgruppe' er en sammenlægning af de mere finkornede
løngrupper fra HR-data. Tabellen viser, hvilke løngruppekoder der indgår i
hver af stillingsgrupperne.
"""
        )
        by_stil = load_stillingsgruppe_loengrupper()

        # Appens 'Ukendt'-kategori er en sammenlægning af tre rå
        # HR-kategorier (se STIL_NORM i create_CURIS_parquet.py) - de
        # samles derfor under samme række her.
        UKENDT_RAA_KILDER = ["Fejlrække", "TAP", "UKENDT"]

        stil_liste = list(STILLINGSGRUPPER)

        def _loengrupper_for(stil: str):
            if stil == "Ukendt":
                kilder = UKENDT_RAA_KILDER
            else:
                kilder = [stil]
            samlet = [lg for k in kilder for lg in by_stil.get(k, [])]
            return sorted(samlet, key=lambda t: t[1])

        rows = "\n".join(
            f"| **{stil}** | {' · '.join(f'{nr} {navn}' for navn, nr in _loengrupper_for(stil))} |"
            for stil in stil_liste
            if _loengrupper_for(stil)
        )
        st.markdown(
            "| Stillingsgruppe | Indeholdte løngrupper |\n|---|---|\n" + rows
        )

    _render_hr_status(filters)

    _fc = _query_field_completeness(filters['aar_fra'], filters['aar_til'])

    st.markdown(
"""
---
#### Datakilder 

Hvor godt dækker OpenAlex og SciVal reelt CURIS' publikationer - og hvor meget overlapper de
to kilder hinanden? De følgende tre afsnit besvarer de spørgsmål. 

En metode til at gøre OpenAlex og SciVal uafhængige af CURIS' dækningsgrad er under
udarbejdelse - lykkes det, vil disse datakilder på sigt kunne vise flere publikationer 
end CURIS selv har registreret. 
""")

    st.markdown(
"""
##### OpenAlex-dækning

Sektionen viser, hvor stor en andel af CURIS's publikationer der har kunnet matches 
med en tilsvarende OpenAlex-post via DOI. OpenAlex kan - som nævnt ovenfor - pr. 
konstruktion aldrig indeholde publikationer, CURIS ikke allerede har. 

Grafen nedenfor respekterer sidepanelets valgte årsinterval, men ignorerer alle øvrige filtre 
(fakultet/institut/stillingsgruppe/etc.). 
""")

    openalex_coverage = _query_source_coverage("OpenAlex", filters)

    fig = fig_hbar_stacked(
        data=openalex_coverage, order=COV_ORDER, colors=COV_COLORS, labels=_coverage_labels("OpenAlex"),
        title=f"OpenAlex-dækning pr. fakultet, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal publikationer", mode="pct", legend_position="bottom",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    st.markdown(
"""
##### SciVal-dækning

Samme opgørelse som ovenfor, men for SciVal - hvor stor en andel af CURIS' publikationer
der har kunnet matches til en post i Scopus/SciVal via DOI. Samme forbehold gælder: SciVal
kan pr. konstruktion aldrig indeholde publikationer, CURIS ikke allerede har.
"""
    )

    scival_coverage = _query_source_coverage("SciVal", filters)

    fig_scival = fig_hbar_stacked(
        data=scival_coverage, order=COV_ORDER, colors=COV_COLORS, labels=_coverage_labels("SciVal"),
        title=f"SciVal-dækning pr. fakultet, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal publikationer", mode="pct", legend_position="bottom",
    )
    st.plotly_chart(fig_scival, width="stretch", config=PLOTLY_CONFIG)

    st.markdown(
"""
##### Overlap mellem OpenAlex og SciVal

I modsætning til sammenligningen med CURIS ovenfor er dette Venn-diagram reelt meningsfuldt:
OpenAlex og SciVal er uafhængigt bygget ved at slå CURIS' DOI-liste op i hver deres eksterne
database, så de kan dække forskellige delmængder af de samme publikationer. Diagrammet er
**ikke** arealproportionalt - cirklernes størrelse afspejler ikke de faktiske tal, kun de
skrevne tal gør.
"""
    )

    overlap = _query_openalex_scival_overlap(filters)
    fig_venn = _render_venn(overlap)
    st.plotly_chart(fig_venn, width="stretch", config=PLOTLY_CONFIG)

