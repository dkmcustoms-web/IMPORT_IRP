"""
DKM Import Release Dashboard — IRP NxtPort API Client
Automatische login via ForgeRock (Port of Antwerp-Bruges) → Azure AD B2C
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
        self.session  = requests.Session()
        self.session.headers.update({
            "User-Agent"        : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Accept-API-Version": "resource=2.1, protocol=1.0",
        })

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

        # ── Stap 1: Eerste POST → krijg authId + callbacks ───────────────────
        resp1 = s.post(auth_url, json={}, timeout=15)
        resp1.raise_for_status()
        data1    = resp1.json()
        auth_id  = data1["authId"]
        callbacks = data1["callbacks"]

        log.info(f"Stap 1 callbacks: {[c['type'] for c in callbacks]}")

        # ── Stap 2: Wachtwoord + alle callbacks invullen ─────────────────────
        for cb in callbacks:
            if cb["type"] == "PasswordCallback":
                cb["input"][0]["value"] = self.password
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0  # eerste optie = Login/Bevestigen
            elif cb["type"] == "BooleanAttributeInputCallback":
                cb["input"][0]["value"] = False
                if len(cb["input"]) > 1:
                    cb["input"][1]["value"] = False

        resp2 = s.post(auth_url, json={"authId": auth_id, "callbacks": callbacks}, timeout=15)
        resp2.raise_for_status()
        data2 = resp2.json()

        log.info(f"Stap 2 response keys: {list(data2.keys())}")

        # ── Stap 3: Verwerk extra stappen indien aanwezig ────────────────────
        max_stappen = 5
        stap = 0
        while "callbacks" in data2 and stap < max_stappen:
            stap += 1
            extra_callbacks = data2["callbacks"]
            cb_types = [c["type"] for c in extra_callbacks]
            log.info(f"Extra stap {stap} callbacks: {cb_types}")

            new_auth_id = data2.get("authId", auth_id)

            for cb in extra_callbacks:
                if cb["type"] == "ConfirmationCallback":
                    cb["input"][0]["value"] = 0
                elif cb["type"] == "BooleanAttributeInputCallback":
                    cb["input"][0]["value"] = False
                    if len(cb["input"]) > 1:
                        cb["input"][1]["value"] = False
                elif cb["type"] == "PasswordCallback":
                    cb["input"][0]["value"] = self.password
                # TextOutputCallback heeft geen input → niets doen

            resp_extra = s.post(auth_url, json={
                "authId"   : new_auth_id,
                "callbacks": extra_callbacks,
            }, timeout=15)
            resp_extra.raise_for_status()
            data2 = resp_extra.json()
            log.info(f"Extra stap {stap} response keys: {list(data2.keys())}")

        # ── Stap 4: tokenId ophalen ──────────────────────────────────────────
        token_id = data2.get("tokenId")
        if not token_id:
            raise ValueError(f"Login mislukt na {stap} stappen. Response: {list(data2.keys())}")

        log.info("ForgeRock tokenId ontvangen.")

        # ── Stap 5: OAuth2 auth code ophalen ────────────────────────────────
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
        log.info("OAuth2 auth code ontvangen.")

        # ── Stap 6: Token ophalen bij Azure AD B2C ───────────────────────────
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

        log.info("Bearer token ontvangen!")
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
        resp = self.session.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        if resp.status_code == 401:
            log.warning("Token verlopen — opnieuw inloggen...")
            self._token = None
            resp = self.session.request(method, url, headers=self._headers(), timeout=15, **kwargs)
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
