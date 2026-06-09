import streamlit as st

""" vent til data er sat korrekt op
# --- ERDA / SFTP ---
_ERDA = st.secrets["erda"]
DATA_PATH = _ERDA["data_path"]
"""

# --- Fakulteter ---
FAC_ORDER = ["SAMF", "SCIENCE", "TEO", "SUND", "HUM", "JUR"]

FAC_ABBRS = {
    "Det Teologiske Fakultet": "TEO",
    "Det Juridiske Fakultet": "JUR",
    "Det Humanistiske Fakultet": "HUM",
    "Det Natur- og Biovidenskabelige Fakultet": "SCIENCE",
    "Det Samfundsvidenskabelige Fakultet": "SAMF",
    "Det Sundhedsvidenskabelige Fakultet": "SUND"
}

# --- Stillingsgrupper ---
STILLINGSGRUPPER = [
    "Professor",
    "Lektor",
    "Adjunkt",
    "Postdoc",
    "Ph.d.",
    "Øvrige VIP (DVIP)",
    "Stillinger u. adjunktniveau",
    "Særlig stilling"
]

HIERARKI = {
    "Særlig stilling": -1,
    "Øvrige VIP (DVIP)": 0,
    "Ph.d.": 1,
    "Stillinger u. adjunktniveau": 2,
    "Postdoc": 3,
    "Adjunkt": 4,
    "Lektor": 5,
    "Professor": 6
}

CPR = {
    "m": "Mænd",
    "k": "Kvinder",
}

GROUP_ORDER = sorted(HIERARKI.keys(), key=lambda g: HIERARKI[g])

# --- Nationaliteter ---
_COUNTRY_NAMES_DA = {
    "DK":  "Danmark",    "D":   "Tyskland",   "CN":  "Kina",
    "I":   "Italien",    "GB":  "Storbritannien", "E": "Spanien",
    "USA": "USA",        "S":   "Sverige",    "NL":  "Holland",
    "IND": "Indien",     "F":   "Frankrig",   "GR":  "Grækenland",
    "N":   "Norge",      "PL":  "Polen",      "IR":  "Iran",
    "AUS": "Australien", "CDN": "Canada",     "P":   "Portugal",
    "BR":  "Brasilien",  "B":   "Belgien",    "RUS": "Rusland",
    "SF":  "Finland",    "A":   "Østrig",     "IRL": "Irland",
    "CH":  "Schweiz",    "MEX": "Mexico",     "J":   "Japan",
    "TR":  "Tyrkiet",    "PAK": "Pakistan",   "ROK": "Sydkorea",
    "R":   "Rumænien",   "LTU": "Litauen",    "IS":  "Island",
    "H":   "Ungarn",     "ETH": "Etiopien",   "RCH": "Chile",
    "CZE": "Tjekkiet",   "CO":  "Colombia",   "HRV": "Kroatien",
    "BG":  "Bulgarien",  "IL":  "Israel",     "UKR": "Ukraine",
    "NEP": "Nepal",      "LVA": "Letland",    "SVN": "Slovenien",
    "SVK": "Slovakiet",  "EST": "Estland",    "SRB": "Serbien",
    "VN":  "Vietnam",    "PE":  "Peru",       "RI":  "Indonesien",
    "ZA":  "Sydafrika",  "ET":  "Egypten",    "T":   "Thailand",
    "AR":  "Argentina",  "NZ":  "New Zealand","PI":  "Filippinerne",
    "ZW":  "Zimbabwe",   "EAK": "Kenya",      "RC":  "Taiwan",
    "ARM": "Armenien",   "RL":  "Libanon",    "MAL": "Malaysia",
    "BD":  "Bangladesh", "GH":  "Ghana",      "SGP": "Singapore",
    "HKJ": "Jordan",     "GDA": "Ukendt",     "BHU": "Bhutan",
    "MOZ": "Mozambique", "CL":  "Sri Lanka",  "L":   "Luxembourg",
    "UZB": "Usbekistan", "EAT": "Tanzania",   "BH":  "Bahrain",
    "EC":  "Ecuador",    "DY":  "Benin",      "MDA": "Moldova",
    "RWA": "Rwanda",     "EAU": "Uganda",     "YV":  "Venezuela",
    "MS":  "Mauritius",  "BLR": "Belarus",    "AL":  "Albanien",
    "BIH": "Bosnien-Hercegovina",             "SN":  "Senegal",
    "YMN": "Yemen",      "WAN": "Nigeria",    "KAZ": "Kasakhstan",
    "SU":  "Sovjetunionen", "MAK": "Nordmakedonien", "MDG": "Madagaskar",
    "SWA": "Namibia",    "CY":  "Cypern",     "BOL": "Bolivia",
    "DZ":  "Algeriet",   "SYR": "Syrien",     "KWT": "Kuwait",
    "GEO": "Georgien",   "TN":  "Tunesien",   "DOM": "Dominikanske Republik",
    "CAM": "Cameroun",   "NIC": "Nicaragua",  "FL":  "Liechtenstein",
    "MA":  "Marokko",    "OMN": "Oman",       "Ukendt": "Ukendt",
}

def country_name(code: str) -> str:
    if not code:
        return "Ukendt"
    return _COUNTRY_NAMES_DA.get(code, _COUNTRY_NAMES_DA.get(code.upper(), code))

# --- Faner ---
TABS = [
    "Oversigt",
    "Output",
    "Publikationsformer",
    "Forskningsprofil",
    "Eksternt samarbejde",
    "Sampublicering",
    "Datagrundlag",
]

# --- Sampubliceringsapp URL ---
SAMPUBLICERING_URL = "https://ku-sampublicering.streamlit.app/"