"""
DKM Import Release Dashboard — IRP NxtPort API Client
ForgeRock login flow:
  Stap 1: NameCallback → gebruikersnaam
  Stap 2: TextOutputCallback + ConfirmationCallback → bevestigen (0)
  Stap 3: PasswordCallback → wachtwoord
  → tokenId → OAuth2 code → Bearer token
"""

import logging
import re
import requests
import streamlit as st
from dataclasses import dataclass

log = logging.getLogger(__name__)

BASE_URL       = "https://api.irp.nxtport.com/irp-bff/v1"
FORGEROCK_BASE = "https://login.portofantwerpbruges.com/poam/json/realms/root/realms/portofantwerpbruges"
AUTH_SERVICE   = "GlobalAuthenticationPolicyLevel25_poab"
GOTO_URL       = (
    "https://login.portofantwerpbruges.com:443/poam/oauth2/authorize"
    "?client_id=nxtport_irp"
    "&redirect_uri=https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp"
    "&response_type=code"
    "&scope=openid%20email%20profile"
    "&response_mode=form_post"
)


@dataclass
class TSDResult:
    crn: str
    mrn: str | None
    bl: str
    eori: str
    status_tsd: str
    status_clearance: str


class IRPClient:

    def __init__(self):
        self.username = st.secrets["irp"]["username"]
        self.password = st.secrets["irp"]["password"]
        self._token   = None

    def _fill_callbacks(self, callbacks: list) -> list:
        """Vul alle bekende callback types correct in."""
        for cb in callbacks:
            t = cb["type"]
            if t == "NameCallback":
                # Gebruikersnaam
                cb["input"][0]["value"] = self.username
                log.info("NameCallback → gebruikersnaam ingevuld")
            elif t == "PasswordCallback":
                # Wachtwoord
                cb["input"][0]["value"] = self.password
                log.info("PasswordCallback → wachtwoord ingevuld")
            elif t == "ConfirmationCallback":
                # Altijd eerste optie kiezen (Login / Bevestigen)
                cb["input"][0]["value"] = 0
                log.info("ConfirmationCallback → 0 (bevestigen)")
            elif t == "BooleanAttributeInputCallback":
                cb["input"][0]["value"] = False
                if len(cb["input"]) > 1:
                    cb["input"][1]["value"] = False
            # TextOutputCallback heeft geen input → niets doen
        return callbacks

    def _login(self) -> str:
        log.info("Inloggen op IRP (ForgeRock)...")

        auth_url = (
            f"{FORGEROCK_BASE}/authenticate"
            f"?authIndexType=service&authIndexValue={AUTH_SERVICE}"
            f"&goto={GOTO_URL}"
        )

        s = requests.Session()
        s.headers.update({
            "User-Agent"        : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Accept-API-Version": "resource=2.1, protocol=1.0",
            "Content-Type"      : "application/json",
            "Accept"            : "application/json",
        })

        # Initieel verzoek
        resp = s.post(auth_url, json={}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Loop door alle stappen tot tokenId ontvangen
        max_stappen = 10
        for stap in range(max_stappen):
            cb_types = [c["type"] for c in data.get("callbacks", [])]
            log.info(f"Stap {stap+1} callbacks: {cb_types}")

            # Klaar — tokenId ontvangen
            if "tokenId" in data:
                break

            # Vul callbacks in en stuur terug
            auth_id   = data["authId"]
            callbacks = self._fill_callbacks(data["callbacks"])

            resp = s.post(auth_url, json={
                "authId"   : auth_id,
                "callbacks": callbacks,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()

        token_id = data.get("tokenId")
        if not token_id:
            cb_types = [c["type"] for c in data.get("callbacks", [])]
            raise ValueError(f"Login mislukt na {max_stappen} stappen. Laatste callbacks: {cb_types}")

        log.info("ForgeRock tokenId ontvangen ✓")

        # OAuth2 authorize → auth code
        oauth_url = (
            "https://login.portofantwerpbruges.com/poam/oauth2/authorize"
            "?client_id=nxtport_irp"
            "&redirect_uri=https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp"
            "&response_type=code"
            "&scope=openid email profile"
            "&response_mode=form_post"
        )
        s.cookies.set("iPlanetDirectoryPro", token_id, domain="login.portofantwerpbruges.com")
        resp3 = s.get(oauth_url, allow_redirects=True, timeout=15)

        code_match = re.search(r'name="code"\s+value="([^"]+)"', resp3.text)
        if not code_match:
            raise ValueError("Kon OAuth2 auth code niet ophalen.")

        auth_code = code_match.group(1)
        log.info("OAuth2 auth code ontvangen ✓")

        # Azure AD B2C → Bearer token
        token_resp = s.post(
            "https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/v2.0/token",
            data={
                "grant_type"  : "authorization_code",
                "client_id"   : "ac46ac63-390d-4906-9936-4057f91a93bd",
                "code"        : auth_code,
                "redirect_uri": "https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp",
            },
            timeout=15,
        )
        token_data = token_resp.json()
        token = token_data.get("id_token") or token_data.get("access_token")
        if not token:
            raise ValueError(f"Geen token van Azure AD B2C: {token_data}")

        log.info("Bearer token ontvangen ✓")
        return token

    def _get_token(self) -> str:
        if not self._token:
            self._token = self._login()
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type" : "application/json",
            "Accept"       : "application/json",
        }

    def _call(self, method: str, url: str, **kwargs):
        s    = requests.Session()
        resp = s.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        if resp.status_code == 401:
            log.warning("Token verlopen — opnieuw inloggen...")
            self._token = None
            resp = s.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        return resp

    def get_crn_from_bl(self, bl: str) -> str | None:
        try:
            resp = self._call("GET", f"{BASE_URL}/reference", params={"bl": bl})
            if resp.status_code == 200:
                crn = resp.json()
                log.info(f"CRN gevonden voor BL {bl}: {crn}")
                return crn
            elif resp.status_code == 404:
                log.warning(f"Geen CRN gevonden voor BL {bl}")
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
                log.warning(f"CRN {crn} niet gevonden")
                return None
            else:
                log.error(f"HTTP {resp.status_code} voor CRN {crn}: {resp.text[:200]}")
                return None
        except Exception as e:
            log.error(f"Exception get_tsd_information({crn}): {e}")
            return None
