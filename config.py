from pathlib import Path


# --- Data ---
"""
PARQUET_PATHS = {
    "CURIS":    r"H:\Publikationsapp\Data\KU_pub_long.parquet",
    "OpenAlex": r"H:\Publikationsapp\Data\KU_pub_long_OpenAlex.parquet",
    "SciVal":   r"H:\Publikationsapp\Data\KU_pub_long_SciVal.parquet", 
}
"""
_DATA_CACHE_DIR = Path(__file__).parent / "data_cache"

PARQUET_PATHS = {
    "CURIS":    str(_DATA_CACHE_DIR / "KU_pub_long.parquet"),
    "OpenAlex": str(_DATA_CACHE_DIR / "KU_pub_long_OpenAlex.parquet"),
    "SciVal":   str(_DATA_CACHE_DIR / "KU_pub_long_SciVal.parquet"),
}

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

FAC_FULL = {v: k for k, v in FAC_ABBRS.items()}

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
    "Særlig stilling": 6,
    "Øvrige VIP (DVIP)": 5,
    "Ph.d.": 4,
    "Stillinger u. adjunktniveau": 3,
    "Postdoc": 2,
    "Adjunkt": 1,
    "Lektor": 0,
    "Professor": -1
}

STIL_ORDER = sorted(HIERARKI, key=lambda k: HIERARKI[k]) + ["Ukendt"]

# --- Organisatoriske dimensioner / hierarki ---
MODE_COLS = {"F": "Fak", "I": "Inst", "G": "Stil", "S": "Koen", "N": "Statsbg"}
HIER_ORDER = ("F", "I", "G", "S", "N")

def hier_cols(mode: str) -> list[str]:
    return [MODE_COLS[c] for c in HIER_ORDER if c in mode]

def breakdown_label(mode: str) -> str:
    names = {"F": "fakultet", "I": "institut", "G": "stillingsgruppe", "S": "køn", "N": "nationalitet"}
    parts = [names[c] for c in HIER_ORDER if c in mode]
    return ("pr. " + ", ".join(parts)) if parts else "KU samlet"


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

def doi_filter_sql(har_doi: list) -> str:
    """Bygger SQL-betingelse for DOI-filteret. har_doi er en liste af 'Ja'/'Nej'."""
    conditions = []
    if "Ja" in har_doi:
        conditions.append("(DOI IS NOT NULL AND DOI != '')")
    if "Nej" in har_doi:
        conditions.append("(DOI IS NULL OR DOI = '')")
    return " OR ".join(conditions) if conditions else "FALSE"

def year_range_label(aar_fra: int, aar_til: int) -> str:
    return f"{aar_fra}-{aar_til}" if aar_fra != aar_til else str(aar_fra)

def author_count_filter(min_forfattere: int, max_forfattere: int, alias: str = "") -> tuple:
    """Bygger SQL-betingelse + params for forfatterantal-filteret."""
    col = f"{alias}Antal_forfattere"
    return f"{col} BETWEEN ? AND ?", [min_forfattere, max_forfattere]

def show_ku_samlet(filters: dict) -> bool:
    return set(filters.get('fakultet', [])) == set(FAC_ORDER)

# --- Faner ---
TABS = [
    "Oversigt",
    "Publikationsformer",
    "Forfatterprofil",
    "Forskningsprofil",
    "Citationsimpact",
    "Eksternt samarbejde",
    "Sampublicering",
    "Datagrundlag",
]

# --- Sampubliceringsapp URL ---
SAMPUBLICERING_URL = "https://ku-sampublicering.streamlit.app/"