import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

def render(filters: dict) -> None:
    st.subheader("Diversitet")

    st.markdown(
"""
Fanen belyser den demografiske sammensætning af KU's publicerende forfattere - køn og 
statsborgerskab - fordelt på organisatoriske niveauer og tid. 

---
"""
    )

    min_celle = 5

    st.markdown(
"""
### Køn 

##### Kønsfordeling

Fordelingen af KU's publicerende forfattere på køn, opgjort på tværs af de valgte
organisatoriske niveauer. 
"""
    )

    st.error("Figur under opbygning")

    st.markdown(
"""
##### Kønsfordeling pr. stillingsgruppe

Krydser kønsfordeling med stillingsgruppe - gør det muligt at se, om kønsbalancen ændrer sig
hen over karrieretrin (f.eks. fra ph,d, til professor). 
"""
    )

    st.error("Figur under opbygning")

    st.markdown(
"""
##### Kønsfordeling over tid

Udvikling i kønrfordeling år for år. Graferne dækker altid hele den tilgængelige periode, uanset
sidepanelets årsinterval - øvrige filtre gælder stadig. 
"""
    )

    st.error("Figur under opbygning")

    st.markdown("---")

    st.markdown(
"""
### Statsborgerskab

##### Statsborgerskabsfordeling

Fordelingen af KU's publicerende forfattere på statsborgerskab, grupperet i bredere
kategorier (fx "Danmark / Øvrige Norden / Øvrige Europa / Uden for Europa") frem for enkelte
lande - dels for overskuelighedens skyld, dels fordi enkeltlande med få forfattere er
præcis der, minimumscellestørrelsen oftest slår igennem.
"""
    )
    st.error("Figur under opbygning.")

    st.markdown(
"""
##### Statsborgerskab over tid

Udviklingen i statsborgerskabsfordelingen år for år, samme princip som kønsfordelingen
ovenfor.
"""
    )
    st.error("Figur under opbygning.")

