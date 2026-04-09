"""
DKM Import Release Dashboard — IRP NxtPort API Client
Login via ForgeRock met e-mail verificatiecode (MFA)
"""

import logging
import re
import secrets as _secrets
import urllib.parse
import requests
import streamlit as st
from dataclasses import dataclass

log = logging.getLogger(__name__)

BASE_URL        = "https://api.irp.nxtport.com/irp-bff/v1"
FORGEROCK_BASE  = "https://login.portofantwerpbruges.com/poam/json/realms/root/realms/portofantwerpbruges"
AUTH_SERVICE    = "GlobalAuthenticationPolicyLevel25_poab"
CLIENT_ID       = "ac46ac63-390d-4906-9936-4057f91a93bd"
REDIRECT_URI    = "https://b2cnxtweuprdiirp.b2clogin.com/b2cnxtweuprdiirp.onmicrosoft.com/oauth2/authresp"
AZURE_TOKEN_URL = "https://b2cnxtweuprdiirp.b2clogin.com/b2cnxtweuprdiirp.onmicrosoft.com/oauth2/v2.0/token"

# ForgeRock authenticate endpoint
AUTH_URL = (
    f"{FORGEROCK_BASE}/authenticate"
    f"?authIndexType=service&authIndexValue={AUTH_SERVICE}"
)


@dataclass
class TSDResult:
    crn: str
    mrn: str | None
    bl: str
    eori: str
    status_tsd: str
    status_clearance: str


def _fr_post(url: str, body: dict, cookies: dict = None) -> tuple[dict, dict]:
    resp = requests.post(
        url, json=body,
        headers={
            "User-Agent"        : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "Accept-API-Version": "resource=2.1, protocol=1.0",
            "Content-Type"      : "application/json",
            "Accept"            : "application/json",
        },
        cookies=cookies or {},
        timeout=15,
        allow_redirects=False,
    )
    log.info(f"POST ForgeRock → HTTP {resp.status_code}")
    if not resp.ok:
        raise ValueError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    if not resp.text.strip():
        raise ValueError(f"Lege response (HTTP {resp.status_code})")
    new_cookies = dict(cookies or {})
    new_cookies.update(dict(resp.cookies))
    return resp.json(), new_cookies


class IRPClient:

    def __init__(self):
        self.username = st.secrets["irp"]["username"]
        self.password = st.secrets["irp"]["password"]

    def start_login(self) -> dict:
        """Start login: gebruikersnaam + wachtwoord + kies e-mail MFA."""
        # Bouw goto URL op — exact zoals browser dit doet
        nonce = _secrets.token_urlsafe(16)
        goto = urllib.parse.quote(
            f"https://login.portofantwerpbruges.com:443/poam/oauth2/authorize"
            f"?client_id=nxtport_irp"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=openid email profile"
            f"&response_mode=form_post"
            f"&nonce={nonce}",
            safe=""
        )
        auth_url = f"{AUTH_URL}&goto={goto}"
        cookies  = {}

        # Stap 1: Gebruikersnaam
        log.info("Login stap 1: gebruikersnaam")
        data, cookies = _fr_post(auth_url, {}, cookies)
        for cb in data["callbacks"]:
            if cb["type"] == "NameCallback":
                cb["input"][0]["value"] = self.username
        data, cookies = _fr_post(auth_url, {"authId": data["authId"], "callbacks": data["callbacks"]}, cookies)

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
        data, cookies = _fr_post(auth_url, {"authId": data["authId"], "callbacks": data["callbacks"]}, cookies)

        # Stap 3: Kies e-mail MFA
        log.info("Login stap 3: e-mail MFA kiezen")
        for cb in data["callbacks"]:
            if cb["type"] == "ChoiceCallback":
                choices = next((o["value"] for o in cb["output"] if o["name"] == "choices"), [])
                log.info(f"MFA opties: {choices}")
                email_idx = next((i for i, c in enumerate(choices) if "mail" in c.lower()), 1)
                cb["input"][0]["value"] = email_idx
                log.info(f"Gekozen: optie {email_idx} = {choices[email_idx] if choices else '?'}")
        data, cookies = _fr_post(auth_url, {"authId": data["authId"], "callbacks": data["callbacks"]}, cookies)

        cb_types = [c["type"] for c in data.get("callbacks", [])]
        log.info(f"Wacht op OTP. Callbacks: {cb_types}")

        # De goto URL is de OAuth2 authorize URL die ForgeRock na login gebruikt
        goto_url = (
            "https://login.portofantwerpbruges.com/poam/oauth2/authorize"
            f"?client_id=nxtport_irp"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope=openid+email+profile"
            f"&response_mode=form_post"
            f"&nonce={nonce}"
        )

        return {
            "auth_id"  : data["authId"],
            "callbacks": data["callbacks"],
            "cookies"  : cookies,
            "auth_url" : auth_url,
            "nonce"    : nonce,
            "goto_url" : goto_url,
        }

    def complete_login(self, login_state: dict, otp_code: str) -> bool:
        """OTP code invoeren en Bearer token ophalen."""
        callbacks = login_state["callbacks"]
        cookies   = login_state["cookies"]
        auth_url  = login_state["auth_url"]
        nonce     = login_state["nonce"]

        for cb in callbacks:
            if cb["type"] == "NameCallback":
                cb["input"][0]["value"] = otp_code.strip()
            elif cb["type"] == "ConfirmationCallback":
                cb["input"][0]["value"] = 0

        log.info("OTP versturen...")
        data, cookies = _fr_post(auth_url, {"authId": login_state["auth_id"], "callbacks": callbacks}, cookies)

        token_id = data.get("tokenId")
        if not token_id:
            cb_types = [c["type"] for c in data.get("callbacks", [])]
            log.error(f"Geen tokenId. Callbacks: {cb_types}")
            return False

        log.info(f"tokenId ontvangen ✓")
        log.info(f"Volledige login response keys: {list(data.keys())}")
        log.info(f"successUrl: {data.get('successUrl', 'NIET AANWEZIG')}")
        log.info(f"realm: {data.get('realm', 'NIET AANWEZIG')}")

        # ForgeRock redirect opvolgen via de successUrl
        # Na succesvolle login geeft ForgeRock een successUrl terug
        # OF we halen de goto URL op via de session endpoint
        session_url = f"https://login.portofantwerpbruges.com/poam/json/realms/root/realms/portofantwerpbruges/sessions/{token_id}?_action=getProperty&_prettyPrint=true"
        
        # Gebruik de tokenId als cookie en volg de goto redirect
        all_cookies = {**cookies, "iPlanetDirectoryPro": token_id}
        
        # Haal de goto URL op die we meegaven bij stap 1
        goto_url = login_state.get("goto_url")
        log.info(f"Goto URL: {goto_url[:150] if goto_url else 'niet opgeslaan'}")
        
        resp3 = requests.get(
            goto_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Accept": "text/html,application/xhtml+xml",
            },
            cookies=all_cookies,
            allow_redirects=True,
            timeout=15,
        )
        log.info(f"Goto → HTTP {resp3.status_code}, finale URL: {resp3.url[:150]}")
        log.info(f"Response preview: {resp3.text[:500]}")

        # Auth code zoeken in HTML form
        code_match = re.search(r'name="code"\s+value="([^"]+)"', resp3.text)
        if not code_match:
            url_match = re.search(r'[?&]code=([^&\s"]+)', resp3.url)
            if url_match:
                auth_code = url_match.group(1)
                log.info("Auth code gevonden in URL ✓")
            else:
                log.error(f"Geen auth code. Status: {resp3.status_code}. Preview: {resp3.text[:300]}")
                raise ValueError("Kon OAuth2 auth code niet ophalen.")
        else:
            auth_code = code_match.group(1)
            log.info("Auth code gevonden in HTML ✓")

        # Azure AD B2C → Bearer token
        log.info("Azure token aanvragen...")
        token_resp = requests.post(
            AZURE_TOKEN_URL,
            data={
                "grant_type"  : "authorization_code",
                "client_id"   : CLIENT_ID,
                "code"        : auth_code,
                "redirect_uri": REDIRECT_URI,
                "scope"       : "openid email profile",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        log.info(f"Azure token → HTTP {token_resp.status_code}")
        if not token_resp.ok:
            raise ValueError(f"Azure fout HTTP {token_resp.status_code}: {token_resp.text[:300]}")

        token_data = token_resp.json()
        token = token_data.get("id_token") or token_data.get("access_token")
        if not token:
            raise ValueError(f"Geen token in response: {token_data}")

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
