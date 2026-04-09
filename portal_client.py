"""
DKM Import Release Dashboard — IRP NxtPort API Client
Login via ForgeRock met e-mail verificatiecode (MFA)
Twee-staps flow waarbij de sessie bewaard wordt via pickle in session_state
"""

import logging
import pickle
import re
import requests
import streamlit as st
from dataclasses import dataclass

log = logging.getLogger(__name__)

BASE_URL       = "https://api.irp.nxtport.com/irp-bff/v1"
FORGEROCK_BASE = "https://login.portofantwerpbruges.com/poam/json/realms/root/realms/portofantwerpbruges"
AUTH_SERVICE   = "GlobalAuthenticationPolicyLevel25_poab"
AUTH_URL       = (
    f"{FORGEROCK_BASE}/authenticate"
    f"?authIndexType=service&authIndexValue={AUTH_SERVICE}"
    f"&goto=https://login.portofantwerpbruges.com:443/poam/oauth2/authorize"
    f"?client_id%3Dnxtport_irp"
    f"%26redirect_uri%3Dhttps://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp"
    f"%26response_type%3Dcode"
    f"%26scope%3Dopenid%2520email%2520profile"
    f"%26response_mode%3Dform_post"
)
OAUTH_URL = (
    "https://login.portofantwerpbruges.com/poam/oauth2/authorize"
    "?client_id=nxtport_irp"
    "&redirect_uri=https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp"
    "&response_type=code"
    "&scope=openid email profile"
    "&response_mode=form_post"
)
AZURE_TOKEN_URL = (
    "https://b2cnxtweuprdirp.b2clogin.com"
    "/b2cnxtweuprdirp.onmicrosoft.com/oauth2/v2.0/token"
)
CLIENT_ID = "ac46ac63-390d-4906-9936-4057f91a93bd"
REDIRECT  = "https://b2cnxtweuprdirp.b2clogin.com/b2cnxtweuprdirp.onmicrosoft.com/oauth2/authresp"


@dataclass
class TSDResult:
    crn: str
    mrn: str | None
    bl: str
    eori: str
    status_tsd: str
    status_clearance: str


def _headers_fr() -> dict:
    return {
        "User-Agent"        : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        "Accept-API-Version": "resource=2.1, protocol=1.0",
        "Content-Type"      : "application/json",
        "Accept"            : "application/json",
    }


def _fr_post(url: str, body: dict, cookies: dict = None) -> tuple[dict, dict]:
    """
    POST naar ForgeRock. Geeft (response_json, cookies) terug.
    Cookies worden meegegeven zodat sessie bewaard blijft zonder requests.Session object.
    """
    resp = requests.post(url, json=body, headers=_headers_fr(),
                         cookies=cookies, timeout=15, allow_redirects=False)
    log.info(f"POST ForgeRock → HTTP {resp.status_code}")
    if not resp.ok:
        raise ValueError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    if not resp.text.strip():
        raise ValueError(f"Lege response (HTTP {resp.status_code})")
    # Merge cookies
    new_cookies = dict(cookies or {})
    new_cookies.update(dict(resp.cookies))
    return resp.json(), new_cookies


class IRPClient:

    def __init__(self):
        self.username = st.secrets["irp"]["username"]
        self.password = st.secrets["irp"]["password"]

    def start_login(self) -> dict:
        """
        Stap 1: gebruikersnaam + wachtwoord + e-mail MFA kiezen.
        Stuurt verificatiecode naar e-mail.
        Geeft serialiseerbare login_state terug (geen Session object).
        """
        cookies = {}

        # Stap 1: Gebruikersnaam
        log.info("Login stap 1: gebruikersnaam")
        data, cookies = _fr_post(AUTH_URL, {}, cookies)
        for cb in data["callbacks"]:
            if cb["type"] == "NameCallback":
                cb["input"][0]["value"] = self.username
        data, cookies = _fr_post(AUTH_URL, {"authId": data["authId"], "callbacks": data["callbacks"]}, cookies)

        # Stap 2: Wachtwoord
        log.info("Login stap 2: wachtwoord")
        for cb in data["callbacks"]:
            if cb["type"] == "PasswordCallback":
                cb["input"][0]["value"] = self.password
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0
            elif cb["type"] == "BooleanAttributeInputCallback":
                cb["input"][0]["value"] = False
                if len(cb["input"]) > 1:
                    cb["input"][1]["value"] = False
        data, cookies = _fr_post(AUTH_URL, {"authId": data["authId"], "callbacks": data["callbacks"]}, cookies)

        # Stap 3: Kies e-mail MFA
        log.info("Login stap 3: e-mail MFA kiezen")
        for cb in data["callbacks"]:
            if cb["type"] == "ChoiceCallback":
                choices = next((o["value"] for o in cb["output"] if o["name"] == "choices"), [])
                log.info(f"MFA opties: {choices}")
                email_idx = next((i for i, c in enumerate(choices) if "mail" in c.lower()), 1)
                cb["input"][0]["value"] = email_idx
                log.info(f"Gekozen: optie {email_idx} = {choices[email_idx] if choices else '?'}")
        data, cookies = _fr_post(AUTH_URL, {"authId": data["authId"], "callbacks": data["callbacks"]}, cookies)

        cb_types = [c["type"] for c in data.get("callbacks", [])]
        log.info(f"Wacht op OTP code. Callbacks: {cb_types}")

        return {
            "auth_id"  : data["authId"],
            "callbacks": data["callbacks"],
            "cookies"  : cookies,
        }

    def complete_login(self, login_state: dict, otp_code: str) -> bool:
        """Stap 2: OTP code invoeren en token ophalen."""
        callbacks = login_state["callbacks"]
        cookies   = login_state["cookies"]

        for cb in callbacks:
            if cb["type"] == "NameCallback":
                cb["input"][0]["value"] = otp_code.strip()
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0

        log.info("OTP versturen...")
        data, cookies = _fr_post(AUTH_URL, {"authId": login_state["auth_id"], "callbacks": callbacks}, cookies)

        token_id = data.get("tokenId")
        if not token_id:
            cb_types = [c["type"] for c in data.get("callbacks", [])]
            log.error(f"Geen tokenId na OTP. Callbacks: {cb_types}")
            return False

        log.info("tokenId ontvangen ✓")

        # OAuth2 → auth code
        resp3 = requests.get(
            OAUTH_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            cookies={**cookies, "iPlanetDirectoryPro": token_id},
            allow_redirects=True,
            timeout=15,
        )
        log.info(f"OAuth2 → HTTP {resp3.status_code}, URL: {resp3.url[:100]}")

        code_match = re.search(r'name="code"\s+value="([^"]+)"', resp3.text)
        if not code_match:
            log.error(f"Geen auth code. Preview: {resp3.text[:300]}")
            raise ValueError("Kon OAuth2 auth code niet ophalen.")

        auth_code = code_match.group(1)
        log.info("OAuth2 auth code ontvangen ✓")

        # Azure AD B2C → Bearer token
        token_resp = requests.post(
            AZURE_TOKEN_URL,
            data={
                "grant_type"  : "authorization_code",
                "client_id"   : CLIENT_ID,
                "code"        : auth_code,
                "redirect_uri": REDIRECT,
            },
            timeout=15,
        )
        log.info(f"Azure token → HTTP {token_resp.status_code}")
        token_data = token_resp.json()
        token = token_data.get("id_token") or token_data.get("access_token")
        if not token:
            raise ValueError(f"Geen token van Azure AD B2C: {token_data}")

        st.session_state["irp_token"] = token
        log.info("Bearer token opgeslagen ✓")
        return True

    def is_logged_in(self) -> bool:
        return bool(st.session_state.get("irp_token"))

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
