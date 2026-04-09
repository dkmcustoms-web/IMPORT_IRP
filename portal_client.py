"""
DKM Import Release Dashboard — IRP NxtPort API Client
Login via ForgeRock met e-mail verificatiecode (MFA)
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
        self._token   = st.session_state.get("irp_token")

    def start_login(self) -> dict:
        """
        Start de login flow en stuur een e-mail verificatiecode.
        Geeft de session state terug die nodig is voor stap 2.
        """
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

        # Stap 1: Gebruikersnaam
        resp = s.post(auth_url, json={}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for cb in data["callbacks"]:
            if cb["type"] == "NameCallback":
                cb["input"][0]["value"] = self.username

        resp = s.post(auth_url, json={"authId": data["authId"], "callbacks": data["callbacks"]}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Stap 2: Wachtwoord
        for cb in data["callbacks"]:
            if cb["type"] == "PasswordCallback":
                cb["input"][0]["value"] = self.password
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0
            elif cb["type"] == "BooleanAttributeInputCallback":
                cb["input"][0]["value"] = False
                if len(cb["input"]) > 1:
                    cb["input"][1]["value"] = False

        resp = s.post(auth_url, json={"authId": data["authId"], "callbacks": data["callbacks"]}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Stap 3: Kies "Verificatiecode via e-mail" (optie 1)
        for cb in data["callbacks"]:
            if cb["type"] == "ChoiceCallback":
                choices = next((o["value"] for o in cb["output"] if o["name"] == "choices"), [])
                log.info(f"MFA opties: {choices}")
                # Kies e-mail optie (index 1)
                email_idx = next((i for i, c in enumerate(choices) if "mail" in c.lower()), 1)
                cb["input"][0]["value"] = email_idx
                log.info(f"E-mail MFA gekozen (optie {email_idx})")

        resp = s.post(auth_url, json={"authId": data["authId"], "callbacks": data["callbacks"]}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Nu wacht ForgeRock op de e-mail code (NameCallback)
        log.info(f"Wacht op e-mail code. Callbacks: {[c['type'] for c in data.get('callbacks', [])]}")

        # Sla sessie op voor stap 2
        return {
            "auth_id"  : data["authId"],
            "callbacks": data["callbacks"],
            "session"  : s,
            "auth_url" : auth_url,
        }

    def complete_login(self, login_state: dict, otp_code: str) -> bool:
        """
        Voltooi de login met de e-mail verificatiecode.
        Slaat het token op in st.session_state.
        """
        s         = login_state["session"]
        auth_url  = login_state["auth_url"]
        callbacks = login_state["callbacks"]

        # Vul de OTP code in (NameCallback)
        for cb in callbacks:
            if cb["type"] == "NameCallback":
                cb["input"][0]["value"] = otp_code
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0

        resp = s.post(auth_url, json={
            "authId"   : login_state["auth_id"],
            "callbacks": callbacks,
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        token_id = data.get("tokenId")
        if not token_id:
            log.error(f"Login mislukt na OTP. Response: {list(data.keys())}")
            return False

        log.info("ForgeRock tokenId ontvangen ✓")

        # OAuth2 → auth code
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
            log.error("Kon OAuth2 auth code niet ophalen.")
            return False

        # Azure AD B2C → Bearer token
        token_resp = s.post(
            "https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/v2.0/token",
            data={
                "grant_type"  : "authorization_code",
                "client_id"   : "ac46ac63-390d-4906-9936-4057f91a93bd",
                "code"        : code_match.group(1),
                "redirect_uri": "https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp",
            },
            timeout=15,
        )
        token_data = token_resp.json()
        token = token_data.get("id_token") or token_data.get("access_token")
        if not token:
            log.error(f"Geen token van Azure AD B2C: {token_data}")
            return False

        # Sla token op in session state
        st.session_state["irp_token"] = token
        self._token = token
        log.info("Token opgeslagen in session state ✓")
        return True

    def is_logged_in(self) -> bool:
        return bool(st.session_state.get("irp_token"))

    def _get_token(self) -> str:
        token = st.session_state.get("irp_token")
        if not token:
            raise ValueError("Niet ingelogd — token ontbreekt.")
        return token

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
                log.error(f"HTTP {resp.status_code} voor BL {bl}")
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
                log.error(f"HTTP {resp.status_code} voor CRN {crn}")
                return None
        except Exception as e:
            log.error(f"Exception get_tsd_information({crn}): {e}")
            return None
