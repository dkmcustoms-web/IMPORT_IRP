"""
DKM Import Release Dashboard — Hoofdscript
Poll elk uur de IRP API voor MRN updates per container.
Credentials via st.secrets
"""

import logging
import time
import streamlit as st

from portal_client import IRPClient
from sheets_client import (
    get_client,
    ensure_headers,
    get_all_rows,
    update_row_crn,
    update_row_mrn,
    update_row_poll,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

API_DELAY_SECONDS = 1.5


def run_poll():
    log.info("=== DKM Import MRN Poller gestart ===")

    # IRPClient haalt zelf username/password uit st.secrets
    irp = IRPClient()
    ss  = get_client()
    ws  = ss.worksheet("Blad1")

    ensure_headers(ws)
    rows = get_all_rows(ws)

    log.info(f"{len(rows)} actieve rijen gevonden in sheet")

    stats = {"skipped": 0, "crn_found": 0, "mrn_found": 0, "no_mrn_yet": 0, "errors": 0}

    for row in rows:
        container = row["container"]
        bl        = row["bl"]
        crn       = row["crn"]
        mrn       = row["mrn_found"]

        # MRN al gevonden → overslaan
        if mrn and mrn.strip():
            log.info(f"[SKIP] {container} — MRN al bekend: {mrn}")
            stats["skipped"] += 1
            continue

        time.sleep(API_DELAY_SECONDS)

        # Geen CRN → zoek eerst via BL
        if not crn:
            log.info(f"[CRN] {container} — CRN opzoeken via BL={bl}")
            crn_result = irp.get_crn_from_bl(bl)
            if not crn_result:
                log.warning(f"[ERROR] {container} — geen CRN gevonden voor BL={bl}")
                stats["errors"] += 1
                continue

            crn = crn_result
            tsd = irp.get_tsd_information(crn)
            status = tsd.status_tsd if tsd else ""
            update_row_crn(ws, row["row_index"], crn, status)
            stats["crn_found"] += 1

            if tsd and tsd.mrn:
                update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
                stats["mrn_found"] += 1
            else:
                log.info(f"[WAIT] {container} — CRN={crn}, MRN nog niet beschikbaar")
                stats["no_mrn_yet"] += 1
            continue

        # CRN bekend → poll MRN
        log.info(f"[POLL] {container} — CRN={crn}")
        tsd = irp.get_tsd_information(crn)

        if not tsd:
            log.warning(f"[ERROR] {container} — geen response voor CRN={crn}")
            stats["errors"] += 1
            continue

        if tsd.mrn:
            update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
            stats["mrn_found"] += 1
            log.info(f"[MRN] {container} — MRN={tsd.mrn}")
        else:
            update_row_poll(ws, row["row_index"], tsd.status_tsd)
            stats["no_mrn_yet"] += 1

    log.info(
        f"=== Klaar | "
        f"Skip: {stats['skipped']} | "
        f"CRN: {stats['crn_found']} | "
        f"MRN: {stats['mrn_found']} | "
        f"Wacht: {stats['no_mrn_yet']} | "
        f"Fouten: {stats['errors']} ==="
    )
    return stats


if __name__ == "__main__":
    run_poll()
