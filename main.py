"""
DKM Import Release Dashboard — Hoofdscript
Polt elk uur de IRP API voor MRN updates per container.

Logica per rij:
  1. Geen CRN → zoek CRN via BL → sla op
  2. CRN aanwezig, geen MRN → poll TSD info → sla MRN op indien gevonden
  3. MRN al aanwezig → overslaan
"""

import os
import logging
import time

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

# Kleine pauze tussen API calls om rate limiting te vermijden
API_DELAY_SECONDS = 1.5


def main():
    log.info("=== DKM Import MRN Poller gestart ===")

    # Auth token uit GitHub Secret
    session_token = os.environ["IRP_SESSION_TOKEN"]

    irp    = IRPClient(session_token)
    ss     = get_client()
    ws     = ss.worksheet("Blad1")

    ensure_headers(ws)
    rows = get_all_rows(ws)

    log.info(f"{len(rows)} actieve rijen gevonden in sheet")

    stats = {"skipped": 0, "crn_found": 0, "mrn_found": 0, "no_mrn_yet": 0, "errors": 0}

    for row in rows:
        container = row["container"]
        bl        = row["bl"]
        eori      = row["eori"]
        crn       = row["crn"]
        mrn       = row["mrn_found"]

        # Stap 3: MRN al gevonden → overslaan
        if mrn and mrn.strip():
            log.info(f"[SKIP] {container} — MRN al bekend: {mrn}")
            stats["skipped"] += 1
            continue

        time.sleep(API_DELAY_SECONDS)

        # Stap 1: Geen CRN → zoek eerst CRN via BL
        if not crn:
            log.info(f"[CRN] {container} — CRN opzoeken via BL={bl}")
            crn_result = irp.get_crn_from_bl(bl)
            if not crn_result:
                log.warning(f"[SKIP] {container} — geen CRN gevonden voor BL={bl}")
                stats["errors"] += 1
                continue

            crn = crn_result
            # Haal meteen ook TSD info op
            tsd = irp.get_tsd_information(crn)
            status = tsd.status_tsd if tsd else ""
            update_row_crn(ws, row["row_index"], crn, status)
            stats["crn_found"] += 1

            if tsd and tsd.mrn:
                update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
                stats["mrn_found"] += 1
                log.info(f"[MRN] {container} — MRN gevonden: {tsd.mrn}")
            else:
                log.info(f"[WAIT] {container} — CRN={crn}, MRN nog niet beschikbaar")
                stats["no_mrn_yet"] += 1
            continue

        # Stap 2: CRN bekend, MRN nog niet → poll
        log.info(f"[POLL] {container} — CRN={crn}, MRN pollen...")
        tsd = irp.get_tsd_information(crn)

        if not tsd:
            log.warning(f"[ERROR] {container} — geen response van IRP voor CRN={crn}")
            stats["errors"] += 1
            continue

        if tsd.mrn:
            update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
            stats["mrn_found"] += 1
            log.info(f"[MRN] {container} — MRN gevonden: {tsd.mrn}")
        else:
            update_row_poll(ws, row["row_index"], tsd.status_tsd)
            stats["no_mrn_yet"] += 1
            log.info(f"[WAIT] {container} — Status: {tsd.status_tsd}, MRN nog niet beschikbaar")

    log.info(
        f"=== Klaar | "
        f"Overgeslagen: {stats['skipped']} | "
        f"CRN gevonden: {stats['crn_found']} | "
        f"MRN gevonden: {stats['mrn_found']} | "
        f"Wachten op MRN: {stats['no_mrn_yet']} | "
        f"Fouten: {stats['errors']} ==="
    )


if __name__ == "__main__":
    main()
