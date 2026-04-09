"""
DKM Import Release Dashboard — IRP NxtPort API Client
Authenticatie via NextAuth sessie cookies (uit browser)
API: api.irp.nxtport.com/irp-bff/v1/tsd/...
"""

import logging
import requests
import streamlit as st
from dataclasses import dataclass

log = logging.getLogger(__name__)

TSD_BASE = "https://api.irp.nxtport.com/irp-bff/v1/tsd"


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
        st.session_state["irp_cookies"] = cookie_str.strip()

    def _get_cookies(self) -> dict:
        cookie_str = st.session_state.get("irp_cookies")
        if not cookie_str:
            raise ValueError("Niet ingelogd.")
        cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    def _headers(self) -> dict:
        return {
            "Content-Type" : "application/json",
            "Accept"       : "application/json",
            "Active-Role"  : "LSP",
            "User-Agent"   : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/116.0.0.0",
        }

    def _call(self, method: str, url: str, **kwargs):
        resp = requests.request(
            method, url,
            headers=self._headers(),
            cookies=self._get_cookies(),
            timeout=15,
            **kwargs
        )
        log.info(f"{method} {url} → HTTP {resp.status_code}")
        if resp.status_code == 401:
            st.session_state.pop("irp_cookies", None)
            raise ValueError("Sessie verlopen — opnieuw inloggen.")
        return resp

    def get_crn_from_bl(self, bl: str, container: str = None, eori: str = None) -> str | None:
        """Zoek CRN via BL + containernummer + EORI."""
        try:
            params = {
                "bl"  : bl,
                "teId": container or "",
                "eori": eori or "",
                "sn"  : "",
            }
            log.info(f"CRN zoeken: {params}")
            resp = self._call("GET", f"{TSD_BASE}/reference", params=params)
            log.info(f"CRN response: {resp.text[:200]}")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, str):
                    return data
                if isinstance(data, dict):
                    return data.get("crn")
                return str(data)
            elif resp.status_code == 404:
                log.warning(f"Geen CRN voor BL={bl}")
                return None
            else:
                log.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"Exception get_crn_from_bl: {e}")
            return None

    def get_tsd_information(self, crn: str) -> TSDResult | None:
        """Haal TSD info op via CRN — bevat MRN zodra container gelost."""
        try:
            resp = self._call("GET", f"{TSD_BASE}/{crn}/information")
            log.info(f"TSD response: {resp.text[:200]}")
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
                log.warning(f"CRN {crn} niet gevonden")
                return None
            else:
                log.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"Exception get_tsd_information: {e}")
            return None
