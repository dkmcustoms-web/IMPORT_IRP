"""
DKM Import Release Dashboard — IRP NxtPort API Client
Token wordt manueel ingevoerd via de Streamlit UI.
"""

import logging
import requests
import streamlit as st
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

    def is_logged_in(self) -> bool:
        return bool(st.session_state.get("irp_token"))

    def set_token(self, token: str):
        st.session_state["irp_token"] = token.strip().removeprefix("Bearer ")

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
        }

    def _call(self, method: str, url: str, **kwargs):
        resp = requests.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        if resp.status_code == 401:
            st.session_state.pop("irp_token", None)
            raise ValueError("Token verlopen — opnieuw inloggen.")
        return resp

    def get_crn_from_bl(self, bl: str) -> str | None:
        try:
            resp = self._call("GET", f"{BASE_URL}/reference", params={"bl": bl})
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                log.warning(f"Geen CRN voor BL {bl}")
                return None
            else:
                log.error(f"HTTP {resp.status_code} voor BL {bl}: {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"Exception get_crn_from_bl({bl}): {e}")
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
