"""
DKM Import Release Dashboard — IRP NxtPort API Client
Token wordt manueel ingevoerd via de Streamlit UI.
"""

import logging
import requests
import streamlit as st
from dataclasses import dataclass

log = logging.getLogger(__name__)

BASE_URL    = "https://api.irp.nxtport.com/irp-bff/v1"
SESSION_URL = "https://irp.nxtport.com/api/auth/session"
TSD_BASE    = "https://api.irp.nxtport.com/irp-bff/v1/tsd"


@dataclass
class TSDResult:
    crn: str
    mrn: str | None
    bl: str
    eori: str
    status_tsd: str
    status_clearance: str


class IRPClient:

    def is_logged_in(self) -> bool:
        return bool(st.session_state.get("irp_token"))

    def set_token(self, token: str):
        """Sla de Bearer token op uit de browser."""
        token = token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:]
        st.session_state["irp_token"] = token

    def _get_token(self) -> str:
        token = st.session_state.get("irp_token")
        if not token:
            raise ValueError("Niet ingelogd.")
        return token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type" : "application/json",
            "Accept"       : "application/json",
            "Active-Role"  : "LSP",
            "User-Agent"   : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/116.0.0.0",
        }

    def _call(self, method: str, url: str, **kwargs):
        resp = requests.request(
            method, url,
            headers=self._headers(),
            timeout=15,
            **kwargs
        )
        if resp.status_code == 401:
            st.session_state.pop("irp_token", None)
            raise ValueError("Token verlopen — opnieuw inloggen.")
        return resp

    def get_crn_from_bl(self, bl: str, container: str = None, eori: str = None) -> str | None:
        """
        Zoek CRN via reference key (BL + container + EORI).
        Valt terug op BL-only als container/eori niet meegegeven.
        """
        try:
            # Probeer eerst via reference key (BL + container + EORI)
            if container and eori:
                params = {"bl": bl, "teId": container, "eori": eori}
                log.info(f"Zoeken via reference key: BL={bl}, container={container}, eori={eori}")
                resp = self._call("GET", f"{BASE_URL}/search", params=params)
                log.info(f"Search response HTTP {resp.status_code}: {resp.text[:200]}")
                if resp.status_code == 200:
                    data = resp.json()
                    # Response kan CRN direct zijn of een object met crn veld
                    if isinstance(data, str):
                        return data
                    if isinstance(data, dict):
                        return data.get("crn")
                elif resp.status_code == 404:
                    log.warning(f"Geen resultaat voor BL={bl}, container={container}")
                    return None

            # Fallback: BL only (met correcte URL en parameters)
            log.info(f"Zoeken via BL+container+eori: bl={bl}, teId={container}, eori={eori}")
            params = {"bl": bl, "sn": "", "eori": eori or "", "teId": container or ""}
            resp = self._call("GET", f"{TSD_BASE}/reference", params=params)
            log.info(f"Reference HTTP {resp.status_code}: {resp.text[:300]}")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, str):
                    return data
                if isinstance(data, dict):
                    return data.get("crn")
                return str(data)
            elif resp.status_code == 404:
                log.warning(f"Geen CRN voor BL={bl}, container={container}")
                return None
            else:
                log.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"Exception get_crn_from_bl: {e}")
            return None

    def get_tsd_information(self, crn: str) -> TSDResult | None:
        try:
            resp = self._call("GET", f"{TSD_BASE}/{crn}/information")
            if resp.status_code == 200:
                data = resp.json()
                mrn  = data.get("mrn") or None
                if mrn == "":
                    mrn = None
                return TSDResult(
                    crn              = data.get("crn", crn),
                    mrn              = mrn,
                    bl               = data.get("bl", ""),
                    eori             = data.get("saEORI", ""),
                    status_tsd       = data.get("status", {}).get("tsd", ""),
                    status_clearance = data.get("status", {}).get("clearance", ""),
                )
            elif resp.status_code == 404:
                return None
            else:
                log.error(f"HTTP {resp.status_code} voor CRN {crn}: {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"Exception get_tsd_information({crn}): {e}")
            return None
