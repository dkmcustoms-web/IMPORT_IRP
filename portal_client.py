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
        return bool(st.session_state.get("irp_cookies"))

    def set_cookies(self, cookie_str: str):
        """Sla de cookie string op uit de browser."""
        st.session_state["irp_cookies"] = cookie_str.strip()

    def _get_cookies(self) -> dict:
        cookie_str = st.session_state.get("irp_cookies")
        if not cookie_str:
            raise ValueError("Niet ingelogd.")
        # Parseer "key=value; key2=value2" naar dict
        cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept"      : "application/json",
            "User-Agent"  : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/116.0.0.0",
        }

    def _call(self, method: str, url: str, **kwargs):
        resp = requests.request(
            method, url,
            headers=self._headers(),
            cookies=self._get_cookies(),
            timeout=15,
            **kwargs
        )
        if resp.status_code == 401:
            st.session_state.pop("irp_cookies", None)
            raise ValueError("Sessie verlopen — opnieuw inloggen.")
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

            # Fallback: BL only
            log.info(f"Zoeken via BL only: {bl}")
            resp = self._call("GET", f"{BASE_URL}/reference", params={"bl": bl})
            log.info(f"Reference response HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                log.warning(f"Geen CRN voor BL {bl}")
                return None
            else:
                log.error(f"HTTP {resp.status_code} voor BL {bl}: {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"Exception get_crn_from_bl: {e}")
            return None

    def get_tsd_information(self, crn: str) -> TSDResult | None:
        try:
            resp = self._call("GET", f"{BASE_URL}/tsd/{crn}/information")
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
