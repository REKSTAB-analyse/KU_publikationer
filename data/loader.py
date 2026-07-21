import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import base64
import os
import subprocess
from datetime import datetime
import duckdb
import paramiko

from config import FAC_ORDER, STILLINGSGRUPPER, PARQUET_PATHS, hier_cols, doi_filter_sql, author_count_filter

@st.cache_resource()
def _sync_parquet_from_erda():
    """Henter de tre parquet-filer fra ERDA via SFTP ned på de stier,
    PARQUET_PATHS allerede peger på - resten af loader.py er uændret,
    den læser stadig bare lokale filer bagefter."""
    erda = st.secrets["erda"]

    print("[ERDA-sync] Forbinder til ERDA...", flush=True)
    transport = paramiko.Transport((erda["host"], erda.get("port", 22)))
    transport.connect(username=erda["username"], password=erda["password"])
    sftp = paramiko.SFTPClient.from_transport(transport)
    print("[ERDA-sync] Forbundet.", flush=True)

    try:
        for data_source, local_path in PARQUET_PATHS.items():
            remote_filename = Path(local_path).name
            remote_path = f"{erda['data_path']}/{remote_filename}"
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            print(f"[ERDA-sync] Henter {remote_path} ...", flush=True)
            sftp.get(remote_path, local_path)
            print(f"[ERDA-sync] Færdig: {local_path}", flush=True)
    finally:
        sftp.close()
        transport.close()
        print("[ERDA-sync] Forbindelse lukket.", flush=True)

@st.cache_resource
def _get_db_for_source(data_source: str):
    conn = duckdb.connect()
    conn.execute(f"CREATE TABLE pubs AS SELECT * FROM read_parquet('{PARQUET_PATHS[data_source]}')")
    return conn

def set_active_data_source(data_source: str) -> None:
    st.session_state["_active_data_source"] = data_source

def _active_data_source() -> str:
    return st.session_state.get("_active_data_source", "CURIS")

def get_db():
    return _get_db_for_source(_active_data_source())

def get_cursor():
    return get_db().cursor()


@st.cache_data
def load_filter_options(data_source: str) -> dict:
    conn = _get_db_for_source(data_source)
    def distinct(col):
        return sorted(
            r[0] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM pubs WHERE {col} IS NOT NULL AND {col} != ''"
            ).fetchall()
        )
    return {
    "typer": distinct("Type"),
    "sprog": distinct("Sprog"),
    "indholds": distinct("Indholdstype"),
    "open_access": distinct("Open_Access"),
    "year": [r[0] for r in conn.execute(
        "SELECT DISTINCT Year FROM pubs WHERE Year IS NOT NULL ORDER BY Year DESC"
    ).fetchall()],
}

@st.cache_data
def load_sprog_options(year_fra: int, year_til: int) -> list:
    return sorted(
        r[0] for r in get_cursor().execute(
            "SELECT DISTINCT Sprog FROM pubs WHERE Sprog IS NOT NULL AND Sprog != '' "
            "AND Intern = 'Intern' AND Year BETWEEN ? AND ?",
            [year_fra, year_til],
        ).fetchall()
    )

@st.cache_data
def load_institut_options(data_source: str, fakulteter: list) -> list:
    conn = _get_db_for_source(data_source)
    ph = ", ".join(["?" for _ in fakulteter])
    sql = f"""
        SELECT DISTINCT Inst FROM pubs
        WHERE Inst IS NOT NULL AND Inst != '' AND Fak IN ({ph})
        ORDER BY Inst
    """
    return [r[0] for r in conn.execute(sql, fakulteter).fetchall()]



# --- Logo (hentes lokalt) ---
@st.cache_data
def load_logo() -> bytes:
    logo_path = Path(__file__).parent.parent / "KU-logo.png"
    if logo_path.exists():
        return logo_path.read_bytes()
    return b""


def logo_base64() -> str:
    return base64.b64encode(load_logo()).decode()


def _get_last_deploy_date() -> str:
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        ts = subprocess.check_output(
            ["git", "log", "-1", "--format=%ci"],
            cwd=repo_dir,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        dt = datetime.fromisoformat(ts)
        return f"{dt.day}. {dt.strftime('%B').lower()} {dt.year}"
    except Exception:
        d = datetime.today()
        return f"{d.day}. {d.strftime('%B').lower()} {d.year}"

_DEPLOY_DATE = _get_last_deploy_date()

def build_pub_query(filters, dims):
    placeholders = lambda lst: ", ".join(["?" for _ in lst])
    where = f"""
        WHERE Intern     = 'Intern'
          AND Fak        IN ({placeholders(filters['fakultet'])})
          AND Stil       IN ({placeholders(filters['stillingsgrupper'])})
          AND Type       IN ({placeholders(filters['typer'])})
          AND Sprog      IN ({placeholders(filters['sprog'])})
          AND Peer_review IN ({placeholders(filters['peer'])})
          AND Open_Access IN ({placeholders(filters['open_access'])})
    """
    group = ", ".join(dims)
    params = (filters['fakultet'] + filters['stillingsgrupper'] +
              filters['typer'] + filters['sprog'] +
              filters['peer'] + filters['open_access'])
    return f"SELECT {group}, COUNT(DISTINCT PURE_ID) AS n FROM pubs {where} GROUP BY {group}", params


@st.cache_data
def load_org_volume(filters: dict, mode: str) -> list:
    """
    Henter publikationsvolumen for hvert niveau i det valgte organisatoriske
    hierarki (Fak/Inst/Stil, afhængig af mode) - til treemap'et over fanerne.
    Fak hentes altid med til farvelægning, uanset om den indgår i nestingen.
    """
    dims = hier_cols(mode)
    if not dims:
        return []
    ph = lambda lst: ", ".join(["?" for _ in lst])
    select_cols = dims if "Fak" in dims else dims + ["Fak"]
    select_sql = ", ".join(select_cols)

    ac_sql, ac_params = author_count_filter(filters['min_forfattere'], filters['max_forfattere'])

    sql = f"""
        SELECT {select_sql}, COUNT(DISTINCT PURE_ID) AS n
        FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year        BETWEEN ? AND ?
          AND ({ac_sql})
        GROUP BY {select_sql}
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']] + ac_params
    )
    rows = get_cursor().execute(sql, params).fetchall()
    return [dict(zip(select_cols, row[:-1]), n=row[-1]) for row in rows]

@st.cache_data
def load_author_counts(filters: dict, mode: str) -> dict:
    dims = hier_cols(mode)
    if not dims:
        return {}
    ph = lambda lst: ", ".join(["?" for _ in lst])
    where_sql = f"""
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year        BETWEEN ? AND ?
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']]
    )

    select_dims = ", ".join(dims)
    sql = f"SELECT {select_dims}, COUNT(DISTINCT ext_id) AS n FROM pubs {where_sql} GROUP BY {select_dims}"
    rows = get_cursor().execute(sql, params).fetchall()

    result = {}
    for row in rows:
        dim_values, n = row[:-1], row[-1]
        dim_label = " | ".join(str(v) for v in reversed(dim_values))
        result[dim_label] = n

    if mode == "F":
        total = get_cursor().execute(
            f"SELECT COUNT(DISTINCT ext_id) FROM pubs {where_sql}", params
        ).fetchone()[0]
        result["KU samlet"] = total

    return result

@st.cache_data
def load_max_author_count(data_source: str, filters: dict) -> int:
    conn = _get_db_for_source(data_source)
    ph = lambda lst: ", ".join(["?" for _ in lst])
    sql = f"""
        SELECT MAX(Antal_forfattere) FROM pubs
        WHERE Intern      = 'Intern'
          AND Fak         IN ({ph(filters['fakultet'])})
          AND Inst        IN ({ph(filters['institutter'])})
          AND Stil        IN ({ph(filters['stillingsgrupper'])})
          AND Type        IN ({ph(filters['typer'])})
          AND Sprog       IN ({ph(filters['sprog'])})
          AND Peer_review IN ({ph(filters['peer'])})
          AND Indholdstype IN ({ph(filters['indholdstyper'])})
          AND ({doi_filter_sql(filters['har_doi'])})
          AND COALESCE(Open_Access, 'Unknown') IN ({ph(filters['open_access'])})
          AND Year BETWEEN ? AND ?
    """
    params = (
        filters['fakultet'] + filters['institutter'] + filters['stillingsgrupper'] +
        filters['typer'] + filters['sprog'] +
        filters['peer'] + filters['indholdstyper'] + filters['open_access'] +
        [filters['aar_fra'], filters['aar_til']]
    )
    result = conn.execute(sql, params).fetchone()
    return result[0] or 1