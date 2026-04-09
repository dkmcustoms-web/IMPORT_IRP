"""
DKM Import Release Dashboard — Google Sheets Client
Sheet ID: 1TAjb5U4_t5vPVFvYXj2GNl0skZqQ6GFna17KNsL37tk
"""

import os
import json
import logging
import tempfile
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

log = logging.getLogger(__name__)

SPREADSHEET_ID = "1TAjb5U4_t5vPVFvYXj2GNl0skZqQ6GFna17KNsL37tk"
SHEET_NAME     = "Blad1"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Kolomindices (1-based voor gspread)
COL = {
    "DOSSIER_ID" : 1,
    "CONTAINER"  : 2,
    "BL"         : 3,
    "EORI"       : 4,
    "LAST_POLL"  : 5,
    "MRN_FOUND"  : 6,
    "CRN"        : 7,   # wordt toegevoegd indien nog niet aanwezig
    "STATUS_TSD" : 8,
}


def get_client() -> gspread.Spreadsheet:
    sa_json = os.environ["GCP_SERVICE_ACCOUNT_JSON"]
    data    = json.loads(sa_json)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        tmp = f.name
    creds = Credentials.from_service_account_file(tmp, scopes=SCOPES)
    os.unlink(tmp)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")


def ensure_headers(ws: gspread.Worksheet):
    """Voeg CRN en STATUS_TSD kolommen toe als die nog niet bestaan."""
    headers = ws.row_values(1)
    updates = []
    if len(headers) < 7 or headers[6].strip() == "":
        updates.append(("G1", "CRN"))
    if len(headers) < 8 or headers[7].strip() == "":
        updates.append(("H1", "STATUS_TSD"))
    for cell, val in updates:
        ws.update(cell, val)
        log.info(f"Header toegevoegd: {cell} = {val}")


def get_all_rows(ws: gspread.Worksheet) -> list[dict]:
    """Geeft alle rijen terug als lijst van dicts met row_index."""
    records = ws.get_all_values()
    rows = []
    for i, row in enumerate(records[1:], start=2):  # sla header over
        # Pad korte rijen aan
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
    """Sla CRN op nadat die gevonden werd."""
    ws.update(f"G{row_index}", [[crn]])
    ws.update(f"H{row_index}", [[status_tsd]])
    ws.update(f"E{row_index}", [[now_str()]])
    log.info(f"Rij {row_index}: CRN={crn}, Status={status_tsd}")


def update_row_mrn(ws: gspread.Worksheet, row_index: int, mrn: str, status_tsd: str):
    """Sla MRN op zodra die beschikbaar is."""
    ws.update(f"F{row_index}", [[mrn]])
    ws.update(f"H{row_index}", [[status_tsd]])
    ws.update(f"E{row_index}", [[now_str()]])
    # Groene achtergrond als MRN gevonden
    ws.format(f"F{row_index}", {
        "backgroundColor": {"red": 0.72, "green": 0.96, "blue": 0.72},
        "textFormat": {"bold": True},
    })
    log.info(f"Rij {row_index}: MRN={mrn} gevonden!")


def update_row_poll(ws: gspread.Worksheet, row_index: int, status_tsd: str):
    """Update enkel de LAST POLL timestamp en status (MRN nog niet gevonden)."""
    ws.update(f"E{row_index}", [[now_str()]])
    ws.update(f"H{row_index}", [[status_tsd]])
