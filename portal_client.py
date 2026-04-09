"""
DKM Import Release Dashboard — IRP NxtPort API Client
API Base: https://api.irp.nxtport.com/irp-bff/v1/
"""

import logging
import requests
from dataclasses import dataclass

log = logging.getLogger(__name__)

BASE_URL = "https://api.irp.nxtport.com/irp-bff/v1"


@dataclass
class TSDResult:
    crn: str
    mrn: str | None
    bl: str
    eori: str
    status_tsd: str
    status_clearance: str


class IRPClient:
    """
    Client voor de IRP NxtPort API.
    Authenticeert via de my.portofantwerpbruges.com sessie cookie.
    """

    def __init__(self, session_token: str):
        """
        session_token: de waarde van het auth cookie/bearer token
                       uit de browser (zie README voor hoe je dit ophaalt)
        """
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {session_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def get_crn_from_bl(self, bl: str) -> str | None:
        """Zoek CRN op basis van Bill of Lading nummer."""
        try:
            resp = self.session.get(
                f"{BASE_URL}/reference",
                params={"bl": bl},
                timeout=15,
            )
            if resp.status_code == 200:
                crn = resp.json()
                log.info(f"CRN gevonden voor BL {bl}: {crn}")
                return crn
            elif resp.status_code == 404:
                log.warning(f"Geen CRN gevonden voor BL {bl}")
                return None
            else:
                log.error(f"Fout bij ophalen CRN voor BL {bl}: HTTP {resp.status_code}")
                return None
        except Exception as e:
            log.error(f"Exception bij get_crn_from_bl({bl}): {e}")
            return None

    def get_tsd_information(self, crn: str) -> TSDResult | None:
        """Haal TSD informatie op via CRN — bevat MRN zodra container gelost is."""
        try:
            resp = self.session.get(
                f"{BASE_URL}/tsd/{crn}/information",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                mrn = data.get("mrn") or None
                # Lege string behandelen als None
                if mrn == "":
                    mrn = None
                result = TSDResult(
                    crn=data.get("crn", crn),
                    mrn=mrn,
                    bl=data.get("bl", ""),
                    eori=data.get("saEORI", ""),
                    status_tsd=data.get("status", {}).get("tsd", ""),
                    status_clearance=data.get("status", {}).get("clearance", ""),
                )
                log.info(f"TSD info voor CRN {crn}: MRN={result.mrn}, Status={result.status_tsd}")
                return result
            elif resp.status_code == 404:
                log.warning(f"CRN {crn} niet gevonden op IRP")
                return None
            else:
                log.error(f"Fout bij ophalen TSD voor CRN {crn}: HTTP {resp.status_code}")
                return None
        except Exception as e:
            log.error(f"Exception bij get_tsd_information({crn}): {e}")
            return None

    def search_tsd(self, bl: str, container: str, eori: str) -> TSDResult | None:
        """
        Volledige flow: BL + container + EORI → CRN → TSD info
        Gebruikt als CRN nog niet bekend is in de sheet.
        """
        crn = self.get_crn_from_bl(bl)
        if not crn:
            log.warning(f"Geen CRN voor BL={bl}, container={container}")
            return None
        return self.get_tsd_information(crn)
