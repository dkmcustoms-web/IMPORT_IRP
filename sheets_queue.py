"""
sheets_queue.py
Tabbladen: Queue | ManualCodes | LearnedCodes
"""

import os
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID       = os.environ.get("COMMODITY_SHEET_ID", "")
WORKSHEET_NAME = "Queue"
MANUAL_SHEET   = "ManualCodes"
LEARNED_SHEET  = "LearnedCodes"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COLUMNS = [
    "row_id", "msg_id", "sender_email", "subject", "received_at",
    "commodity_code", "code_found", "ai_verdict", "suggested_reply",
    "status", "reply_sent", "resolution_type", "confirmed_code",
    "manual_code", "manual_desc", "updated_at",
]

MANUAL_COLUMNS  = ["gn_code", "omschrijving", "added_at"]
LEARNED_COLUMNS = ["proposed_code", "confirmed_code", "confirmed_by", "confirmed_at", "times_seen", "last_seen", "source_subject", "duty_rate"]


class SheetsQueue:
    def __init__(self):
        creds_json = os.environ.get("GMAIL_SERVICE_ACCOUNT_JSON", "")
        if not creds_json:
            raise EnvironmentError("GMAIL_SERVICE_ACCOUNT_JSON not set.")
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)

        # Queue
        try:
            self.ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.WorksheetNotFound:
            self.ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(COLUMNS))
        if self.ws.row_values(1) != COLUMNS:
            self.ws.insert_row(COLUMNS, index=1)

        # ManualCodes
        try:
            self.ws_manual = sh.worksheet(MANUAL_SHEET)
        except gspread.WorksheetNotFound:
            self.ws_manual = sh.add_worksheet(title=MANUAL_SHEET, rows=500, cols=len(MANUAL_COLUMNS))
        if self.ws_manual.row_values(1) != MANUAL_COLUMNS:
            self.ws_manual.insert_row(MANUAL_COLUMNS, index=1)

        # LearnedCodes
        try:
            self.ws_learned = sh.worksheet(LEARNED_SHEET)
        except gspread.WorksheetNotFound:
            self.ws_learned = sh.add_worksheet(title=LEARNED_SHEET, rows=1000, cols=len(LEARNED_COLUMNS))
            self.ws_learned.insert_row(LEARNED_COLUMNS, index=1)
        except Exception as e:
            print(f"[SheetsQueue] LearnedCodes init error: {e}")
            self.ws_learned = None

    # ── Queue ────────────────────────────────────────────────────────────────

    def get_all_items(self) -> list:
        try:
            records = self.ws.get_all_records()
            valid = [r for r in records if str(r.get("row_id", "")).strip().isdigit()]
            return list(reversed(valid))
        except Exception as e:
            print(f"[SheetsQueue] get_all_items error: {e}")
            return []

    def msg_id_exists(self, msg_id: str) -> bool:
        def normalize(mid):
            return str(mid).strip().strip("<>").strip()
        needle = normalize(msg_id)
        try:
            col_values = self.ws.col_values(COLUMNS.index("msg_id") + 1)
            return any(normalize(v) == needle for v in col_values)
        except Exception:
            return False

    def add_item(self, item: dict) -> int:
        raw_mid = str(item.get("msg_id", "")).strip().strip("<>").strip()
        row_id  = len(self.ws.col_values(1))
        now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            row_id,
            raw_mid,
            item.get("sender_email", ""),
            item.get("subject", ""),
            item.get("received_at", ""),
            item.get("commodity_code", ""),
            item.get("code_found", ""),
            item.get("ai_verdict", ""),
            item.get("suggested_reply", ""),
            item.get("status", "pending"),
            "",
            item.get("resolution_type", ""),
            item.get("confirmed_code", ""),
            "",
            "",
            now,
        ]
        self.ws.append_row(row, value_input_option="RAW")
        return row_id

    def update_status(self, row_id, status, reply_sent="",
                      resolution_type="", manual_code="", manual_desc=""):
        try:
            col_values = self.ws.col_values(1)
            row_num = [str(v) for v in col_values].index(str(row_id)) + 1
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            updates = {
                "status": status, "updated_at": now,
                "reply_sent": reply_sent, "resolution_type": resolution_type,
                "manual_code": manual_code, "manual_desc": manual_desc,
            }
            for col_name, value in updates.items():
                if value:
                    self.ws.update_cell(row_num, COLUMNS.index(col_name) + 1, value)
        except Exception as e:
            print(f"[SheetsQueue] update_status error: {e}")

    # ── Manual codes ─────────────────────────────────────────────────────────

    def add_manual_code(self, gn_code: str, omschrijving: str = ""):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ws_manual.append_row([gn_code, omschrijving, now], value_input_option="RAW")

    def get_manual_codes(self) -> list:
        return self.ws_manual.get_all_records()

    # ── Learned codes ─────────────────────────────────────────────────────────

    def get_learned_codes(self) -> list:
        if not self.ws_learned:
            return []
        try:
            return self.ws_learned.get_all_records()
        except Exception as e:
            print(f"[SheetsQueue] get_learned_codes error: {e}")
            return []

    def is_learned(self, gn_code: str) -> bool:
        if not self.ws_learned:
            return False
        try:
            codes = self.ws_learned.col_values(1)
            return str(gn_code).strip() in [str(c).strip() for c in codes]
        except Exception:
            return False

    def learn_code(self, proposed_code: str, confirmed_code: str, subject: str = "",
                   confirmed_by: str = "operator", duty_rate: str = ""):
        """
        Sla zowel de originele (foute) code als de bevestigde code op.
        Zodat volgende keer de foute code ook herkend wordt.
        """
        if not self.ws_learned:
            return
        try:
            now            = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            proposed_clean = str(proposed_code).strip()
            confirmed_clean= str(confirmed_code).strip()

            # Kolom 1 = proposed_code, gebruik die als lookup sleutel
            col1 = self.ws_learned.col_values(1)
            normalized = [str(c).strip() for c in col1]

            if proposed_clean in normalized:
                # Update times_seen en last_seen
                row_num   = normalized.index(proposed_clean) + 1
                times_col = LEARNED_COLUMNS.index("times_seen") + 1
                last_col  = LEARNED_COLUMNS.index("last_seen") + 1
                try:
                    current = int(self.ws_learned.cell(row_num, times_col).value or 0)
                except Exception:
                    current = 0
                self.ws_learned.update_cell(row_num, times_col, current + 1)
                self.ws_learned.update_cell(row_num, last_col, now)
            else:
                self.ws_learned.append_row(
                    [proposed_clean, confirmed_clean, confirmed_by, now, 1, now, subject[:100], duty_rate],
                    value_input_option="RAW"
                )
        except Exception as e:
            print(f"[SheetsQueue] learn_code error: {e}")

    def get_learned_lookup(self) -> dict:
        """
        Geeft een dict terug: {proposed_code: {confirmed_code, duty_rate, times_seen, ...}}
        Zowel proposed als confirmed code worden als sleutel opgeslagen voor maximale herkenning.
        """
        if not self.ws_learned:
            return {}
        try:
            records = self.ws_learned.get_all_records()
            lookup = {}
            for r in records:
                prop = str(r.get("proposed_code","")).strip()
                conf = str(r.get("confirmed_code","")).strip()
                if prop:
                    lookup[prop] = r
                if conf and conf != prop:
                    lookup[conf] = r  # ook de bevestigde code herkennen
            return lookup
        except Exception as e:
            print(f"[SheetsQueue] get_learned_lookup error: {e}")
            return {}
