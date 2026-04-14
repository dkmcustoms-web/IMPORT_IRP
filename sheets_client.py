"""
DKM Import Release Dashboard — Google Sheets Client
Credentials via st.secrets["gcp_service_account"]
"""

import logging
from datetime import datetime, timezone

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

log = logging.getLogger(__name__)

SHEET_NAME = "Blad1"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

COL = {
    "DOSSIER_ID" : 1,
    "CONTAINER"  : 2,
    "BL"         : 3,
    "EORI"       : 4,
    "ETA"        : 5,
    "LAST_POLL"  : 6,
    "MRN_FOUND"  : 7,
    "CRN"        : 8,
    "STATUS_TSD" : 9,
    "EMAIL_SENT" : 10,
    "COLLIS"     : 11,  # Number of packages released by customs
    "GROSS_MASS" : 12,  # Total gross mass released by customs (kg)
}


def get_client() -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )
    gc             = gspread.authorize(creds)
    spreadsheet_id = st.secrets["sheets"]["spreadsheet_id"]
    return gc.open_by_key(spreadsheet_id)


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")


def ensure_headers(ws: gspread.Worksheet):
    """Voeg ontbrekende kolommen toe."""
    headers = ws.row_values(1)
    expected = ["DossierId", "Container", "BL", "EORI", "ETA",
                "LAST_POLL", "MRN_FOUND", "CRN", "STATUS_TSD", "EMAIL_SENT",
                "COLLIS", "GROSS_MASS_KG"]
    for i, name in enumerate(expected):
        col = i + 1
        if len(headers) < col or headers[i].strip() == "":
            ws.update_cell(1, col, name)
            log.info(f"Header toegevoegd: kolom {col} = {name}")


def get_all_rows(ws: gspread.Worksheet) -> list[dict]:
    records = ws.get_all_values()
    rows = []
    for i, row in enumerate(records[1:], start=2):
        while len(row) < 8:
            row.append("")
        while len(row) < 12:
            row.append("")
        rows.append({
            "row_index"  : i,
            "dossier_id" : row[0],
            "container"  : row[1].strip().upper(),
            "bl"         : row[2].strip(),
            "eori"       : row[3].strip(),
            "eta"        : row[4].strip(),   # Kolom E
            "last_poll"  : row[5],           # Kolom F
            "mrn_found"  : row[6],           # Kolom G
            "crn"        : row[7].strip(),   # Kolom H
            "status_tsd" : row[8],           # Kolom I
            "email_sent" : row[9].strip(),   # Kolom J
            "collis"     : row[10].strip(),  # Kolom K
            "gross_mass" : row[11].strip(),  # Kolom L
        })
    return [r for r in rows if r["container"]]


def update_row_crn(ws: gspread.Worksheet, row_index: int, crn: str, status_tsd: str):
    ws.update_cell(row_index, COL["CRN"], crn)
    ws.update_cell(row_index, COL["STATUS_TSD"], status_tsd)
    ws.update_cell(row_index, COL["LAST_POLL"], now_str())
    log.info(f"Rij {row_index}: CRN={crn}, Status={status_tsd}")


def update_row_mrn(ws: gspread.Worksheet, row_index: int, mrn: str, status_tsd: str):
    ws.update_cell(row_index, COL["MRN_FOUND"], mrn)
    ws.update_cell(row_index, COL["STATUS_TSD"], status_tsd)
    ws.update_cell(row_index, COL["LAST_POLL"], now_str())
    ws.format(f"F{row_index}", {
        "backgroundColor": {"red": 0.72, "green": 0.96, "blue": 0.72},
        "textFormat": {"bold": True},
    })
    log.info(f"Rij {row_index}: MRN={mrn} gevonden!")


def update_row_poll(ws: gspread.Worksheet, row_index: int, status_tsd: str):
    ws.update_cell(row_index, COL["LAST_POLL"], now_str())
    ws.update_cell(row_index, COL["STATUS_TSD"], status_tsd)


def save_cookie(cookie_str: str):
    """Sla de cookie op in een apart tabblad 'Config'."""
    ss = get_client()
    try:
        ws = ss.worksheet("Config")
    except Exception:
        ws = ss.add_worksheet(title="Config", rows=10, cols=3)
        ws.update_cell(1, 1, "KEY")
        ws.update_cell(1, 2, "VALUE")
    # Cookie is te lang voor 1 cel — splits in 2 stukken
    half = len(cookie_str) // 2
    part1 = cookie_str[:half]
    part2 = cookie_str[half:]
    ws.update_cell(2, 1, "irp_cookie_1")
    ws.update_cell(2, 2, part1)
    ws.update_cell(3, 1, "irp_cookie_2")
    ws.update_cell(3, 2, part2)
    log.info(f"Cookie opgeslagen in Config tab ({len(cookie_str)} tekens, 2 delen)")


def load_cookie() -> str | None:
    """Lees de cookie uit het 'Config' tabblad."""
    try:
        ss = get_client()
        ws = ss.worksheet("Config")
        records = ws.get_all_values()
        data = {row[0]: row[1] for row in records[1:] if len(row) >= 2}
        # Probeer gesplitste cookie
        if "irp_cookie_1" in data and "irp_cookie_2" in data:
            cookie = data["irp_cookie_1"] + data["irp_cookie_2"]
            if cookie.strip():
                log.info(f"Cookie geladen uit Config tab ({len(cookie)} tekens)")
                return cookie
        # Fallback: oude enkelvoudige cookie
        if "irp_cookie" in data and data["irp_cookie"].strip():
            return data["irp_cookie"]
        return None
    except Exception as e:
        log.warning(f"Geen cookie gevonden in sheet: {e}")
        return None


def mark_email_sent(ws: gspread.Worksheet, row_index: int):
    """Markeer dat de e-mail verstuurd is voor dit dossier."""
    ws.update_cell(row_index, COL["EMAIL_SENT"], "✓")
    log.info(f"Email gestuurd gemarkeerd voor rij {row_index}")


def add_dossier(ws: gspread.Worksheet, dossier_id: str, container: str, bl: str, eori: str, eta: str = "") -> int:
    """Voeg een nieuw dossier toe aan de Google Sheet. Geeft het rijnummer terug."""
    from datetime import datetime, timezone
    new_row = [dossier_id, container, bl, eori, eta, "", "", "", "", ""]
    ws.append_row(new_row, value_input_option="USER_ENTERED")
    all_values = ws.get_all_values()
    row_index = len(all_values)
    log.info(f"Nieuw dossier toegevoegd: {dossier_id} / {container} op rij {row_index}")
    return row_index


def update_row_packages(ws: gspread.Worksheet, row_index: int,
                        packages_released: int | None,
                        gross_mass_released: float | None):
    """Sla collis en gewicht op in de sheet."""
    if packages_released is not None:
        ws.update_cell(row_index, COL["COLLIS"], packages_released)
    if gross_mass_released is not None:
        ws.update_cell(row_index, COL["GROSS_MASS"], gross_mass_released)
    log.info(f"Rij {row_index}: collis={packages_released}, massa={gross_mass_released}")
