import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
import math
from data.loader import _get_db_for_source
from components.charts import fig_hbar_stacked, PLOTLY_CONFIG
from config import FAC_ORDER, year_range_label, doi_filter_sql, author_count_filter

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


def _coverage_labels(source_name: str) -> dict:
    return {
        "Fundet": f"Fundet i {source_name}",
        "Ikke fundet": f"Ikke fundet i {source_name}",
    }


@st.cache_data
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

@st.cache_data
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

@st.cache_data
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

@st.cache_data
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


def render(filters):
    st.markdown(
"""
### Datagrundlag 

I modsætning til appens øvrige faner handler denne ikke om at analysere KU's publikationer, 
men derimod om selve **grundlaget**, de øvrige analyser hviler på: hvor kommer data fra, 
hvordan hænger datakilderne sammen, og hvor godt dækker de hinanden?

**CURIS** er KU's egen registrering af publikationer - alt starter her, uafhængigt af DOI
eller ekstern matchning. **OpenAlex** og **SciVal/Scopus** er begge **eksterne** kilder, 
som appen beriger med CURIS-data ved at slå CURIS' DOI'er op i hver database - de kan 
derfor per konstruktion aldrig indeholde mere, end CURIS allerede har. **HR-data** kobles
separat på for at give hver forfatter en organisationel tilknytning (fakultet/institut/
stillingsgruppe) - se afsnittet nedenfor for metode og begræsninger. 


---

#### HR-kobling

Hver forfatters fakultet, institut og stillingsgruppe kommer ikke fra CURIS selv, men 
kobles separat fra KU's personaledata (hentet fra datakilden Personalesammensætning på tableau.ku.dk).
Koblingen sker **år for år**: for en given publikation slås forfatterens organisatoriske tilknytning
op, som den var registreret **31. december** i udgivelsesåret - ikke på selve
udgivelsesdatoen, da data herfor mangler. 

**To praktiske konsekvenser af denne metode**:

- **Jobskifte midt i et år fanges ikke**. Skiftede en forfatter fakultet i løbet af 
udgivelsesåret, er det kun tilknytningen pr. 31. december, der indgår - uanset hvornår på året 
publikationen faktisk udkom. 
- **Indeværende år har endnu ingen HR-data**. Et års data kan først indhentes, efter 31. 
december samme år er passeret. 
""")

    _fc = _query_field_completeness(filters['aar_fra'], filters['aar_til'])
    if _fc['total'] > 0 and _fc['any_missing'] > 0:
        _pct_any = 100 * _fc['any_missing'] / _fc['total']
        _pct_affiliering = 100 * _fc['affiliering'] / _fc['any_missing']
        _pct_stil = 100 * _fc['stil'] / _fc['any_missing']
        _pct_ovrige = 100 * _fc['ovrige'] / _fc['any_missing']

        _intro = (
            f"**{_pct_any:.1f} %** af publikationerne i {year_range_label(filters['aar_fra'], filters['aar_til'])} "
            f"filtreres fra i appens analyser, fordi de mangler oplysninger om fakultet, institut, "
            f"stillingsgruppe. Af disse mangler **{_pct_affiliering:.1f} %** "
            f"oplysning om affiliering (fakultet og/eller institut), og **{_pct_stil:.1f} %** mangler "
            f"stillingsgruppe."
        )
        st.markdown(_intro)

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

