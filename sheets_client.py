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
    "LAST_POLL"  : 5,
    "MRN_FOUND"  : 6,
    "CRN"        : 7,
    "STATUS_TSD" : 8,
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
    """Voeg CRN en STATUS_TSD kolommen toe als die nog niet bestaan."""
    headers = ws.row_values(1)
    if len(headers) < 7 or headers[6].strip() == "":
        ws.update_cell(1, 7, "CRN")
        log.info("Header toegevoegd: G1 = CRN")
    if len(headers) < 8 or headers[7].strip() == "":
        ws.update_cell(1, 8, "STATUS_TSD")
        log.info("Header toegevoegd: H1 = STATUS_TSD")


def get_all_rows(ws: gspread.Worksheet) -> list[dict]:
    records = ws.get_all_values()
    rows = []
    for i, row in enumerate(records[1:], start=2):
        while len(row) < 8:
            row.append("")
        rows.append({
            "row_index"  : i,
            "dossier_id" : row[0],
            "container"  : row[1].strip().upper(),
            "bl"         : row[2].strip(),
            "eori"       : row[3].strip(),
            "last_poll"  : row[4],
            "mrn_found"  : row[5],
            "crn"        : row[6].strip(),
            "status_tsd" : row[7],
        })
    return [r for r in rows if r["container"]]


def update_row_crn(ws: gspread.Worksheet, row_index: int, crn: str, status_tsd: str):
    ws.update_cell(row_index, 7, crn)
    ws.update_cell(row_index, 8, status_tsd)
    ws.update_cell(row_index, 5, now_str())
    log.info(f"Rij {row_index}: CRN={crn}, Status={status_tsd}")


def update_row_mrn(ws: gspread.Worksheet, row_index: int, mrn: str, status_tsd: str):
    ws.update_cell(row_index, 6, mrn)
    ws.update_cell(row_index, 8, status_tsd)
    ws.update_cell(row_index, 5, now_str())
    ws.format(f"F{row_index}", {
        "backgroundColor": {"red": 0.72, "green": 0.96, "blue": 0.72},
        "textFormat": {"bold": True},
    })
    log.info(f"Rij {row_index}: MRN={mrn} gevonden!")


def update_row_poll(ws: gspread.Worksheet, row_index: int, status_tsd: str):
    ws.update_cell(row_index, 5, now_str())
    ws.update_cell(row_index, 8, status_tsd)


def save_cookie(cookie_str: str):
    """Sla de cookie op in een apart tabblad 'Config'."""
    ss = get_client()
    try:
        ws = ss.worksheet("Config")
    except Exception:
        ws = ss.add_worksheet(title="Config", rows=10, cols=2)
        ws.update("A1", "KEY")
        ws.update("B1", "VALUE")
    # Schrijf cookie naar rij 2
    ws.update("A2", "irp_cookie")
    ws.update("B2", cookie_str)
    log.info("Cookie opgeslagen in Google Sheet (Config tab)")


def load_cookie() -> str | None:
    """Lees de cookie uit het 'Config' tabblad."""
    try:
        ss = get_client()
        ws = ss.worksheet("Config")
        records = ws.get_all_values()
        for row in records[1:]:
            if len(row) >= 2 and row[0] == "irp_cookie":
                cookie = row[1].strip()
                if cookie:
                    log.info("Cookie geladen uit Google Sheet")
                    return cookie
        return None
    except Exception as e:
        log.warning(f"Geen cookie gevonden in sheet: {e}")
        return None
