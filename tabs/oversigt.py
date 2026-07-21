import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
 
import streamlit as st
 
 
def render(filters):
    st.markdown(
""" 
### Oversigt over KU's publikationer

Fanen giver et samlet overblik over publikationsaktiviteten på Københavns Universitet, 
opgjort på tværs af fakulteter, institutter og stillingsgrupper. 

Oversigten beskriver **omfang og fordeling** af KU's publicering, herunder hvor mange
publikationer, der udgives, og hvordan outputtet fordeler sig på prganisatoriske enheder.

Fanen er bevidst deskriptiv og fungerer som et analytisk udgangspunkt til de øvrige faner,
hvor output, publiceringsformer og samarbejdsmønstre analyseres mere detaljeret.

---

#### Fordeling
Treemap kommer her.

---

#### Nøgletal
KPI'er kommer her.

#### Udvikling over tid.
Linjeplots kommer her.
""")
