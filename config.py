from pathlib import Path
import streamlit as st

try:
    ERDA_ENABLED = st.secrets.get("erda", {}).get("use_erda", True)
except Exception:
    ERDA_ENABLED = True

# --- Data ---
if ERDA_ENABLED:
    # Cloud/delt brug: filerne hentes fra ERDA ned i dette lokale mellemlager
    _DATA_CACHE_DIR = Path(__file__).parent / "data_cache"
    PARQUET_PATHS = {
        "CURIS":    str(_DATA_CACHE_DIR / "KU_pub_long.parquet"),
        "OpenAlex": str(_DATA_CACHE_DIR / "KU_pub_long_OpenAlex.parquet"),
        "SciVal":   str(_DATA_CACHE_DIR / "KU_pub_long_SciVal.parquet"),
    }
    REFERENCE_TABLE_PATHS = {
        "scival_topics": str(_DATA_CACHE_DIR / "SciVal_topics_reference.parquet"),
        "scival_asjc":   str(_DATA_CACHE_DIR / "SciVal_ASJC_reference.parquet"),
    }
else:
    # Lokal udvikling: læs direkte fra dine egne, allerede byggede filer
    PARQUET_PATHS = {
        "CURIS":    r"H:\Publikationsapp\Data\KU_pub_long.parquet",
        "OpenAlex": r"H:\Publikationsapp\Data\KU_pub_long_OpenAlex.parquet",
        "SciVal":   r"H:\Publikationsapp\Data\KU_pub_long_SciVal.parquet",
    }
    REFERENCE_TABLE_PATHS = {
        "scival_topics": r"H:\Publikationsapp\Data\SciVal_topics_reference.parquet",
        "scival_asjc":   r"H:\Publikationsapp\Data\SciVal_ASJC_reference.parquet",
        "ku_pairs":      r"H:\Publikationsapp\Data\KU_pub_pairs_long.parquet",
    }

if ERDA_ENABLED:
    PAIRS_PARQUET_PATHS = {
        "CURIS":    str(_DATA_CACHE_DIR / "KU_pub_pairs_long.parquet"),
        "OpenAlex": str(_DATA_CACHE_DIR / "KU_pub_pairs_long_OpenAlex.parquet"),
        "SciVal":   str(_DATA_CACHE_DIR / "KU_pub_pairs_long_SciVal.parquet"),
    }
else:
    PAIRS_PARQUET_PATHS = {
        "CURIS":    r"H:\Publikationsapp\Data\KU_pub_pairs_long.parquet",
        "OpenAlex": r"H:\Publikationsapp\Data\KU_pub_pairs_long_OpenAlex.parquet",
        "SciVal":   r"H:\Publikationsapp\Data\KU_pub_pairs_long_SciVal.parquet",
    }




# --- Fakulteter ---
#FAC_ORDER = ["SAMF", "SCIENCE", "TEO", "SUND", "HUM", "JUR"]
FAC_ORDER = ["HUM", "JUR", "SAMF", "SCIENCE", "SUND", "TEO"]

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

# fra Tableau:
COUNTRY_LOOKUP = {
    'AF': {'land': 'Afghanistan', 'iso3': 'AFG', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'AL': {'land': 'Albanien', 'iso3': 'ALB', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'DZ': {'land': 'Algeriet', 'iso3': 'DZA', 'region': 'Afrika', 'subregion': 'Nordafrika'}, 
    'AR': {'land': 'Argentina', 'iso3': 'ARG', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'AM': {'land': 'Armenien', 'iso3': 'ARM', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'AU': {'land': 'Australske Statsforbund', 'iso3': 'AUS', 'region': 'Oceanien', 'subregion': 'Australien og New Zealand'}, 
    'AZ': {'land': 'Azerbajdjan', 'iso3': 'AZE', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'BD': {'land': 'Bangladesh', 'iso3': 'BGD', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'BB': {'land': 'Barbados', 'iso3': 'BRB', 'region': 'Amerika', 'subregion': 'Caribien'}, 
    'BY': {'land': 'Belarus', 'iso3': 'BLR', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'BE': {'land': 'Belgien', 'iso3': 'BEL', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'BJ': {'land': 'Benin', 'iso3': 'BEN', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'BT': {'land': 'Bhutan', 'iso3': 'BTN', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'BO': {'land': 'Bolivia', 'iso3': 'BOL', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'BA': {'land': 'Bosnien-Hercegovina', 'iso3': 'BIH', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'BW': {'land': 'Botswana', 'iso3': 'BWA', 'region': 'Afrika', 'subregion': 'Sydlige Afrika'}, 
    'BR': {'land': 'Brasilien', 'iso3': 'BRA', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'BN': {'land': 'Brunei Darussalam', 'iso3': 'BRN', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'BG': {'land': 'Bulgarien', 'iso3': 'BGR', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'BF': {'land': 'Burkina Faso', 'iso3': 'BFA', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'BI': {'land': 'Burundi', 'iso3': 'BDI', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'KH': {'land': 'Cambodia', 'iso3': None, 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'CM': {'land': 'Cameroun', 'iso3': 'CMR', 'region': 'Afrika', 'subregion': 'Centralafrika'}, 
    'CA': {'land': 'Canada', 'iso3': 'CAN', 'region': 'Amerika', 'subregion': 'Nordamerika'}, 
    'CL': {'land': 'Chile', 'iso3': 'CHL', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'CO': {'land': 'Columbia', 'iso3': 'COL', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'CG': {'land': 'Congo', 'iso3': 'COG', 'region': 'Afrika', 'subregion': 'Centralafrika'}, 
    'CD': {'land': 'Congo, The Dem. Rep. Of The', 'iso3': 'COD', 'region': 'Afrika', 'subregion': 'Centralafrika'}, 
    'CR': {'land': 'Costa Rica', 'iso3': 'CRI', 'region': 'Amerika', 'subregion': 'Mellemamerika'}, 
    'CU': {'land': 'Cuba', 'iso3': 'CUB', 'region': 'Amerika', 'subregion': 'Caribien'}, 
    'CY': {'land': 'Cypern', 'iso3': 'CYP', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'DK': {'land': 'Danmark', 'iso3': 'DNK', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'DM': {'land': 'Dominica', 'iso3': 'DMA', 'region': 'Amerika', 'subregion': 'Caribien'}, 
    'DO': {'land': 'Dominikanske Republik', 'iso3': 'DOM', 'region': 'Amerika', 'subregion': 'Caribien'}, 
    'EC': {'land': 'Ecuador', 'iso3': 'ECU', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'EG': {'land': 'Egypten', 'iso3': 'EGY', 'region': 'Afrika', 'subregion': 'Nordafrika'}, 
    'SV': {'land': 'El Salvador', 'iso3': 'SLV', 'region': 'Amerika', 'subregion': 'Mellemamerika'}, 
    'CI': {'land': 'Elfenbenskysten', 'iso3': 'CIV', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'ER': {'land': 'Eritrea', 'iso3': 'ERI', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'EE': {'land': 'Estland', 'iso3': 'EST', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'SZ': {'land': 'Eswatini', 'iso3': 'SWZ', 'region': 'Afrika', 'subregion': 'Sydlige Afrika'}, 
    'ET': {'land': 'Ethiopien', 'iso3': 'ETH', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'FJ': {'land': 'Fiji', 'iso3': 'FJI', 'region': 'Oceanien', 'subregion': 'Melanesien'}, 
    'PH': {'land': 'Filippinerne', 'iso3': 'PHL', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'FI': {'land': 'Finland', 'iso3': 'FIN', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'AE': {'land': 'Forenede Arabiske Emirater', 'iso3': 'ARE', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'FR': {'land': 'Frankrig', 'iso3': 'FRA', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'FO': {'land': 'Færøerne', 'iso3': 'FRO', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'GM': {'land': 'Gambia', 'iso3': 'GMB', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'GE': {'land': 'Georgien', 'iso3': 'GEO', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'GH': {'land': 'Ghana', 'iso3': 'GHA', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'GR': {'land': 'Grækenland', 'iso3': 'GRC', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'GL': {'land': 'Grønland', 'iso3': 'GRL', 'region': 'Amerika', 'subregion': 'Nordamerika'}, 
    'GT': {'land': 'Guatemala', 'iso3': 'GTM', 'region': 'Amerika', 'subregion': 'Mellemamerika'}, 
    'GG': {'land': 'GUERNSEY', 'iso3': None, 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'GY': {'land': 'Guyana', 'iso3': 'GUY', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'HN': {'land': 'Honduras', 'iso3': 'HND', 'region': 'Amerika', 'subregion': 'Mellemamerika'}, 
    'HK': {'land': 'Hong Kong', 'iso3': 'HKG', 'region': 'Asien', 'subregion': 'Østasien'}, 
    'IN': {'land': 'Indien', 'iso3': 'IND', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'ID': {'land': 'Indonesien', 'iso3': 'IDN', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'IQ': {'land': 'Irak', 'iso3': 'IRQ', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'IR': {'land': 'Iran', 'iso3': 'IRN', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'IE': {'land': 'Irland', 'iso3': 'IRL', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'IS': {'land': 'Island', 'iso3': 'ISL', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'IL': {'land': 'Israel', 'iso3': 'ISR', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'IT': {'land': 'Italien', 'iso3': 'ITA', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'JM': {'land': 'Jamaica', 'iso3': 'JAM', 'region': 'Amerika', 'subregion': 'Caribien'}, 
    'JP': {'land': 'Japan', 'iso3': 'JPN', 'region': 'Asien', 'subregion': 'Østasien'}, 
    'JO': {'land': 'Jordan', 'iso3': 'JOR', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'YU': {'land': 'Jugoslavien', 'iso3': 'YUG', 'region': 'Ukendt', 'subregion': 'Ukendt'}, 
    'KZ': {'land': 'Kazakhstan', 'iso3': 'KAZ', 'region': 'Asien', 'subregion': 'Centralasien'}, 
    'KE': {'land': 'Kenya', 'iso3': 'KEN', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'CN': {'land': 'Kina', 'iso3': 'CHN', 'region': 'Asien', 'subregion': 'Østasien'}, 
    'KG': {'land': 'Kirgizstan', 'iso3': 'KGZ', 'region': 'Asien', 'subregion': 'Centralasien'}, 
    'XK': {'land': 'Kosovo', 'iso3': 'XKX', 'region': 'Ukendt', 'subregion': 'Ukendt'}, 
    'HR': {'land': 'Kroatien', 'iso3': 'HRV', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'KW': {'land': 'Kuwait', 'iso3': 'KWT', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'LA': {'land': 'Laos', 'iso3': 'LAO', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'LV': {'land': 'Letland', 'iso3': 'LVA', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'LB': {'land': 'Libanon', 'iso3': 'LBN', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'LR': {'land': 'Liberia', 'iso3': 'LBR', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'LI': {'land': 'Liechtenstein', 'iso3': 'LIE', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'LT': {'land': 'Litauen', 'iso3': 'LTU', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'LU': {'land': 'Luxembourg', 'iso3': 'LUX', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'MG': {'land': 'Madagascar', 'iso3': 'MDG', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'MK': {'land': 'Makedonien', 'iso3': 'MKD', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'MW': {'land': 'Malawi', 'iso3': 'MWI', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'MY': {'land': 'Malaysia', 'iso3': 'MYS', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'MV': {'land': 'Maldiverne', 'iso3': 'MDV', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'ML': {'land': 'Mali', 'iso3': 'MLI', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'MT': {'land': 'Malta', 'iso3': 'MLT', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'MA': {'land': 'Marokko', 'iso3': 'MAR', 'region': 'Afrika', 'subregion': 'Nordafrika'}, 
    'MU': {'land': 'Mauritius', 'iso3': 'MUS', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'MX': {'land': 'Mexico', 'iso3': 'MEX', 'region': 'Amerika', 'subregion': 'Mellemamerika'}, 
    'MD': {'land': 'Moldova', 'iso3': 'MDA', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'MN': {'land': 'Mongoliet', 'iso3': 'MNG', 'region': 'Asien', 'subregion': 'Østasien'}, 
    'ME': {'land': 'Montenegro', 'iso3': 'MNE', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'MZ': {'land': 'Mosambique', 'iso3': 'MOZ', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'MM': {'land': 'Myanmar', 'iso3': 'MMR', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'NA': {'land': 'Namibia', 'iso3': 'NAM', 'region': 'Afrika', 'subregion': 'Sydlige Afrika'}, 
    'NL': {'land': 'Nederlandene', 'iso3': 'NLD', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'NP': {'land': 'Nepal', 'iso3': 'NPL', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'NZ': {'land': 'New Zealand', 'iso3': 'NZL', 'region': 'Oceanien', 'subregion': 'Australien og New Zealand'}, 
    'NI': {'land': 'Nicaragua', 'iso3': 'NIC', 'region': 'Amerika', 'subregion': 'Mellemamerika'}, 
    'NE': {'land': 'Niger', 'iso3': 'NER', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'NG': {'land': 'Nigeria', 'iso3': 'NGA', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'NO': {'land': 'Norge', 'iso3': 'NOR', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'OM': {'land': 'Oman', 'iso3': 'OMN', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'PK': {'land': 'Pakistan', 'iso3': 'PAK', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'PS': {'land': 'Palæstina', 'iso3': 'PSE', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'PA': {'land': 'Panama', 'iso3': 'PAN', 'region': 'Amerika', 'subregion': 'Mellemamerika'}, 
    'PE': {'land': 'Peru', 'iso3': 'PER', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'PL': {'land': 'Polen', 'iso3': 'POL', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'PT': {'land': 'Portugal', 'iso3': 'PRT', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'QA': {'land': 'Qatar', 'iso3': 'QAT', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'RO': {'land': 'Rumænien', 'iso3': 'ROU', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'RU': {'land': 'Rusland', 'iso3': 'RUS', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'RW': {'land': 'Rwanda', 'iso3': 'RWA', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'LC': {'land': 'Saint Lucia', 'iso3': 'LCA', 'region': 'Amerika', 'subregion': 'Caribien'}, 
    'SA': {'land': 'Saudi-Arabien', 'iso3': 'SAU', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'CH': {'land': 'Schweiz', 'iso3': 'CHE', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'SN': {'land': 'Senegal', 'iso3': 'SEN', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'RS': {'land': 'Serbien', 'iso3': 'SRB', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'CS': {'land': 'Serbien og Montenegro', 'iso3': 'SCG', 'region': 'Ukendt', 'subregion': 'Ukendt'}, 
    'SL': {'land': 'Sierra Leone', 'iso3': 'SLE', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'SG': {'land': 'Singapore', 'iso3': 'SGP', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'SK': {'land': 'Slovakiet', 'iso3': 'SVK', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'SI': {'land': 'Slovenien', 'iso3': 'SVN', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'SO': {'land': 'Somalia', 'iso3': 'SOM', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'SU': {'land': 'Sovjetunionen', 'iso3': 'SUN', 'region': 'Ukendt', 'subregion': 'Ukendt'}, 
    'ES': {'land': 'Spanien', 'iso3': 'ESP', 'region': 'Europa', 'subregion': 'Sydeuropa'}, 
    'LK': {'land': 'Sri Lanka', 'iso3': 'LKA', 'region': 'Asien', 'subregion': 'Sydasien'}, 
    'GB': {'land': 'Storbritannien', 'iso3': 'GBR', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'SD': {'land': 'Sudan', 'iso3': 'SDN', 'region': 'Afrika', 'subregion': 'Nordafrika'}, 
    'SE': {'land': 'Sverige', 'iso3': 'SWE', 'region': 'Europa', 'subregion': 'Nordeuropa'}, 
    'ZA': {'land': 'Sydafrika', 'iso3': 'ZAF', 'region': 'Afrika', 'subregion': 'Sydlige Afrika'}, 
    'KR': {'land': 'Sydkorea', 'iso3': 'KOR', 'region': 'Asien', 'subregion': 'Østasien'}, 
    'SY': {'land': 'Syrien', 'iso3': 'SYR', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'TW': {'land': 'Taiwan', 'iso3': 'TWN', 'region': 'Ukendt', 'subregion': 'Ukendt'}, 
    'TZ': {'land': 'Tanzania', 'iso3': 'TZA', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'TH': {'land': 'Thailand', 'iso3': 'THA', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'CZ': {'land': 'Tjekkiet', 'iso3': 'CZE', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'TG': {'land': 'Togo', 'iso3': 'TGO', 'region': 'Afrika', 'subregion': 'Vestafrika'}, 
    'TT': {'land': 'Trinidad og Tobago', 'iso3': 'TTO', 'region': 'Amerika', 'subregion': 'Caribien'}, 
    'TN': {'land': 'Tunesien', 'iso3': 'TUN', 'region': 'Afrika', 'subregion': 'Nordafrika'}, 
    'TM': {'land': 'Turkmenistan', 'iso3': 'TMK', 'region': 'Asien', 'subregion': 'Centralasien'}, 
    'TR': {'land': 'Tyrkiet', 'iso3': 'TUR', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'DE': {'land': 'Tyskland', 'iso3': 'DEU', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'US': {'land': 'U S A', 'iso3': 'USA', 'region': 'Amerika', 'subregion': 'Nordamerika'}, 
    'UG': {'land': 'Uganda', 'iso3': 'UGA', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'UA': {'land': 'Ukraine', 'iso3': 'UKR', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'HU': {'land': 'Ungarn', 'iso3': 'HUN', 'region': 'Europa', 'subregion': 'Østeuropa'}, 
    'UY': {'land': 'Uruguay', 'iso3': 'URY', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'UZ': {'land': 'Uzbekistan', 'iso3': 'UZB', 'region': 'Asien', 'subregion': 'Centralasien'}, 
    'VE': {'land': 'Venezuela', 'iso3': 'VEN', 'region': 'Amerika', 'subregion': 'Sydamerika'}, 
    'VN': {'land': 'Vietnam', 'iso3': 'VNM', 'region': 'Asien', 'subregion': 'Sydøstasien'}, 
    'YE': {'land': 'Yemen', 'iso3': 'YEM', 'region': 'Asien', 'subregion': 'Vestasien'}, 
    'ZM': {'land': 'Zambia', 'iso3': 'ZMB', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'ZW': {'land': 'Zimbabwe', 'iso3': 'ZWE', 'region': 'Afrika', 'subregion': 'Østafrika'}, 
    'AT': {'land': 'Østrig', 'iso3': 'AUT', 'region': 'Europa', 'subregion': 'Vesteuropa'}, 
    'TL': {'land': 'Østtimor', 'iso3': 'TLS', 'region': 'Asien', 'subregion': 'Sydøstasien'}
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
    "Diversitet",
    "Forskningsprofil",
    "Citationsimpact",
    "Eksternt samarbejde",
    "Sampublicering",
    "Datagrundlag",
]

# --- Sampubliceringsapp URL ---
SAMPUBLICERING_URL = "https://ku-sampublicering.streamlit.app/"