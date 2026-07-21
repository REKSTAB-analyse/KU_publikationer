import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
import math
from data.loader import _get_db_for_source
from components.charts import fig_hbar_stacked, PLOTLY_CONFIG
from config import FAC_ORDER, year_range_label

COV_ORDER = ["Fundet", "Ikke fundet"]
COV_COLORS = {"Fundet": "#901a1e", "Ikke fundet": "#122947"}


def _coverage_labels(source_name: str) -> dict:
    return {
        "Fundet": f"Fundet i {source_name}",
        "Ikke fundet": f"Ikke fundet i {source_name}",
    }


@st.cache_data
def _query_source_coverage(source_name: str, aar_fra: int, aar_til: int) -> dict:
    """
    Andel af CURIS' publikationer, der har kunnet matches til en post i den
    angivne eksterne kilde (OpenAlex eller SciVal). Begge kilder er bygget
    ved at slå CURIS' egne DOI'er op eksternt, og kan derfor pr. konstruktion
    aldrig indeholde publikationer, CURIS ikke allerede har.
    """
    curis_conn = _get_db_for_source("CURIS")
    source_conn = _get_db_for_source(source_name)

    curis_rows = curis_conn.execute("""
        SELECT DISTINCT Fak, PURE_ID
        FROM pubs
        WHERE Intern = 'Intern' AND Fak != '' AND Year BETWEEN ? AND ?
    """, [aar_fra, aar_til]).fetchall()

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
def _query_openalex_scival_overlap(aar_fra: int, aar_til: int) -> dict:
    """
    Antal CURIS-publikationer fundet i hhv. OpenAlex, SciVal, begge og ingen
    af delene - til Venn-diagrammet. Samme grundpopulation som dæknings-
    sektionerne ovenfor (CURIS-publikationer med kendt fakultet i det valgte
    årsinterval), så tallene er direkte sammenlignelige med søjlerne ovenfor.
    """
    curis_conn = _get_db_for_source("CURIS")
    openalex_conn = _get_db_for_source("OpenAlex")
    scival_conn = _get_db_for_source("SciVal")

    curis_ids = {
        r[0] for r in curis_conn.execute("""
            SELECT DISTINCT PURE_ID FROM pubs
            WHERE Intern = 'Intern' AND Fak != '' AND Year BETWEEN ? AND ?
        """, [aar_fra, aar_til]).fetchall()
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



---

#### HR-kobling

HR-data er hentet fra Personalesammensætning på Tableauserveren. 

---

#### Datakilder 

For nu er publikationerne fra SciVal og OpenAlex betinget af CURIS' dækningsgrad. En metode til
at sætte SciVal og OpenAlex fri fra CURIS er under udarbejdelse.
""")

    st.markdown(
"""
---

#### OpenAlex-dækning

Sektionen viser, hvor stor en andel af CURIS's publikationer der har kunnet matches 
med en tilsvarende OpenAlex-post via DOI. Bemærk: fordi OpenAlexdatasættet er bygget 
ved at slå CURIS' egne DOI'er op i OpenAlex, kan OpenAlex per kontruktion aldrig kan
indeholde  publikationer, CURIS ikke allerede har. 

Fordelingen dækker hele den tilgængelige periode uafhængigt af sidepanelets øvrige
filtre, ud over årsintervallet - da formålet er at vurdere selve datagrundagets dækning, 
ikke en bestemt delmængde af publikationer. 
""")

    openalex_coverage = _query_source_coverage("OpenAlex", filters['aar_fra'], filters['aar_til'])

    fig = fig_hbar_stacked(
        data=openalex_coverage, order=COV_ORDER, colors=COV_COLORS, labels=_coverage_labels("OpenAlex"),
        title=f"OpenAlex-dækning pr. fakultet, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal publikationer", mode="pct", legend_position="bottom",
    )
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)

    st.markdown(
"""
---

#### SciVal-dækning

Samme opgørelse som ovenfor, men for SciVal - hvor stor en andel af CURIS' publikationer
der har kunnet matches til en post i Scopus/SciVal via DOI. Samme forbehold gælder: SciVal
kan pr. konstruktion aldrig indeholde publikationer, CURIS ikke allerede har.
"""
    )

    scival_coverage = _query_source_coverage("SciVal", filters['aar_fra'], filters['aar_til'])

    fig_scival = fig_hbar_stacked(
        data=scival_coverage, order=COV_ORDER, colors=COV_COLORS, labels=_coverage_labels("SciVal"),
        title=f"SciVal-dækning pr. fakultet, {year_range_label(filters['aar_fra'], filters['aar_til'])}",
        xaxis_title="Antal publikationer", mode="pct", legend_position="bottom",
    )
    st.plotly_chart(fig_scival, width="stretch", config=PLOTLY_CONFIG)

    st.markdown(
"""
---

#### Overlap mellem OpenAlex og SciVal

I modsætning til sammenligningen med CURIS ovenfor er dette Venn-diagram reelt meningsfuldt:
OpenAlex og SciVal er uafhængigt bygget ved at slå CURIS' DOI-liste op i hver deres eksterne
database, så de kan dække forskellige delmængder af de samme publikationer. Diagrammet er
**ikke** arealproportionalt - cirklernes størrelse afspejler ikke de faktiske tal, kun de
skrevne tal gør.
"""
    )

    overlap = _query_openalex_scival_overlap(filters['aar_fra'], filters['aar_til'])
    fig_venn = _render_venn(overlap)
    st.plotly_chart(fig_venn, width="stretch", config=PLOTLY_CONFIG)