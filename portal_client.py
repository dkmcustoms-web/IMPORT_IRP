"""
DKM Import Release Dashboard — IRP NxtPort API Client
Automatische login via ForgeRock (Port of Antwerp-Bruges) → Azure AD B2C → Bearer token
"""

import logging
import re
import requests
import streamlit as st
from dataclasses import dataclass

log = logging.getLogger(__name__)

BASE_URL = "https://api.irp.nxtport.com/irp-bff/v1"

# ForgeRock / Port of Antwerp-Bruges login
FORGEROCK_BASE   = "https://login.portofantwerpbruges.com/poam/json/realms/root/realms/portofantwerpbruges"
AUTH_SERVICE     = "GlobalAuthenticationPolicyLevel25_poab"
GOTO_URL         = (
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
    """
    Client voor de IRP NxtPort API.
    Logt automatisch in via ForgeRock → Azure AD B2C.
    Token wordt gecached en automatisch vernieuwd bij 401.
    """

    def __init__(self):
        self.username = st.secrets["irp"]["username"]
        self.password = st.secrets["irp"]["password"]
        self._token   = None
        self.session  = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})

    # ── Login flow ────────────────────────────────────────────────────────────

    def _login(self) -> str:
        """
        Volledige login flow:
        1. ForgeRock stap 1 — gebruikersnaam sturen
        2. ForgeRock stap 2 — wachtwoord sturen → krijg auth code
        3. Auth code inwisselen voor Bearer token via Azure AD B2C
        """
        log.info("Inloggen op IRP (ForgeRock)...")
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0", "Accept-API-Version": "resource=2.1, protocol=1.0"})

        auth_url = (
            f"{FORGEROCK_BASE}/authenticate"
            f"?authIndexType=service&authIndexValue={AUTH_SERVICE}"
            f"&goto={GOTO_URL}"
        )

        # ── Stap 1: Initieel verzoek → krijg authId + callbacks ──────────────
        resp1 = s.post(auth_url, json={}, timeout=15)
        resp1.raise_for_status()
        data1 = resp1.json()
        auth_id = data1["authId"]

        # ── Stap 2: Wachtwoord invullen + Login bevestigen ───────────────────
        # Callbacks aanpassen: IDToken2 = wachtwoord, IDToken4 = 0 (Login)
        callbacks = data1["callbacks"]
        for cb in callbacks:
            if cb["type"] == "PasswordCallback":
                cb["input"][0]["value"] = self.password
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0  # 0 = "Login"
            elif cb["type"] == "BooleanAttributeInputCallback":
                cb["input"][0]["value"] = False
                cb["input"][1]["value"] = False

        resp2 = s.post(auth_url, json={
            "authId":    auth_id,
            "callbacks": callbacks,
        }, timeout=15)
        resp2.raise_for_status()
        data2 = resp2.json()

        # ── Stap 3: Haal tokenId op (ForgeRock sessie cookie) ────────────────
        token_id = data2.get("tokenId")
        if not token_id:
            # Controleer of er nog een extra stap is (MFA)
            if "callbacks" in data2:
                cb_types = [c["type"] for c in data2["callbacks"]]
                raise ValueError(f"Login vereist extra stap (MFA?). Callbacks: {cb_types}")
            raise ValueError(f"Login mislukt. Response: {data2}")

        log.info("ForgeRock login geslaagd, tokenId ontvangen.")

        # ── Stap 4: Gebruik tokenId om OAuth2 auth code te krijgen ───────────
        oauth_url = (
            "https://login.portofantwerpbruges.com/poam/oauth2/authorize"
            f"?client_id=nxtport_irp"
            f"&redirect_uri=https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp"
            f"&response_type=code"
            f"&scope=openid email profile"
            f"&response_mode=form_post"
        )
        s.cookies.set("iPlanetDirectoryPro", token_id, domain="login.portofantwerpbruges.com")
        resp3 = s.get(oauth_url, allow_redirects=True, timeout=15)

        # Haal code uit response (form_post geeft HTML met hidden input)
        code_match = re.search(r'name="code"\s+value="([^"]+)"', resp3.text)
        if not code_match:
            raise ValueError("Kon OAuth2 auth code niet ophalen na ForgeRock login.")

        auth_code = code_match.group(1)
        log.info("OAuth2 auth code ontvangen.")

        # ── Stap 5: Auth code inwisselen bij Azure AD B2C voor JWT token ──────
        token_resp = s.post(
            "https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/v2.0/token",
            data={
                "grant_type":   "authorization_code",
                "client_id":    "ac46ac63-390d-4906-9936-4057f91a93bd",
                "code":         auth_code,
                "redirect_uri": "https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp",
            },
            timeout=15,
        )
        token_data = token_resp.json()
        token = token_data.get("id_token") or token_data.get("access_token")
        if not token:
            raise ValueError(f"Geen token ontvangen van Azure AD B2C: {token_data}")

        log.info("Bearer token succesvol ontvangen!")
        return token

    def _get_token(self) -> str:
        if not self._token:
            self._token = self._login()
        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def _call(self, method: str, url: str, **kwargs):
        """API call met automatische token refresh bij 401."""
        resp = self.session.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        if resp.status_code == 401:
            log.warning("Token verlopen — opnieuw inloggen...")
            self._token = None
            resp = self.session.request(method, url, headers=self._headers(), timeout=15, **kwargs)
        return resp

    # ── API methodes ──────────────────────────────────────────────────────────

    def get_crn_from_bl(self, bl: str) -> str | None:
        """Zoek CRN op basis van Bill of Lading nummer."""
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
                log.error(f"HTTP {resp.status_code} voor BL {bl}: {resp.text}")
                return None
        except Exception as e:
            log.error(f"Exception get_crn_from_bl({bl}): {e}")
            return None

    def get_tsd_information(self, crn: str) -> TSDResult | None:
        """Haal TSD informatie op — bevat MRN zodra container gelost is."""
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
                log.error(f"HTTP {resp.status_code} voor CRN {crn}: {resp.text}")
                return None
        except Exception as e:
            log.error(f"Exception get_tsd_information({crn}): {e}")
            return None
