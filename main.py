"""
DKM Import Release Dashboard v2
"""

import logging
import time
from datetime import datetime, timezone
import streamlit as st

from portal_client import IRPClient
from sheets_client import (
    get_client,
    ensure_headers,
    get_all_rows,
    update_row_crn,
    update_row_mrn,
    update_row_poll,
    save_cookie,
    load_cookie,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_DELAY = 1.5


def auto_load_cookie():
    """Laad cookie automatisch uit Google Sheet bij opstarten."""
    if not st.session_state.get("irp_cookies"):
        try:
            cookie = load_cookie()
            if cookie:
                st.session_state["irp_cookies"] = cookie
                log.info("Cookie automatisch geladen uit sheet")
        except Exception as e:
            log.warning(f"Kon cookie niet laden: {e}")

st.set_page_config(
    page_title="DKM Import Dashboard",
    page_icon="🚢",
    layout="wide",
)

st.markdown("""
<style>
    /* Donker thema */
    .stApp { background-color: #1a1a2e; color: #e0e0e0; }
    [data-testid="stSidebar"] { background-color: #16213e; }
    [data-testid="stSidebar"] * { color: #e0e0e0 !important; }
    h1, h2, h3 { color: #3cceff !important; }
    .stDataFrame { background-color: #0f3460; }
    .stTabs [data-baseweb="tab-list"] { background-color: #16213e; }
    .stTabs [data-baseweb="tab"] { color: #e0e0e0; }
    .stTabs [aria-selected="true"] { background-color: #0f3460; color: #3cceff !important; }
    .stButton > button { background-color: #3cceff; color: #1a1a2e; border: none; font-weight: 600; }
    .stButton > button:hover { background-color: #1ab5ef; }
    .stMetric { background-color: #16213e; border-radius: 8px; padding: 8px; }
    .stTextArea textarea { background-color: #0f3460; color: #e0e0e0; }
    div[data-testid="metric-container"] { background-color: #16213e; border-radius: 8px; padding: 8px; }
    .stSuccess { background-color: #1a3a1a; }
    .stError { background-color: #3a1a1a; }
    .stWarning { background-color: #3a2a0a; }
    caption { color: #888; }
</style>
""", unsafe_allow_html=True)


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")


import re as _re

def extract_cookie_from_dump(text: str) -> str | None:
    """Extraheer de Cookie waarde uit een volledige DevTools header dump."""
    # Methode 1: Zoek "Cookie:" header gevolgd door waarde
    m = _re.search(r'Cookie:\s*
(.*?)(?=
\S|\Z)', text, _re.DOTALL | _re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        if '__Secure-next-auth' in candidate or 'ASLBSA=' in candidate:
            return candidate

    # Methode 2: Zoek de cookie waarde direct (begint met ASLBSA=)
    m2 = _re.search(r'(ASLBSA=[^
]+(?:
[^
:]+)*)', text)
    if m2:
        candidate = m2.group(1).strip().replace('
', '')
        if '__Secure-next-auth' in candidate:
            return candidate

    # Methode 3: Alle regels samenvoegen die cookie-achtig zijn
    lines = text.split('
')
    for i, line in enumerate(lines):
        if 'ASLBSA=' in line and '__Secure-next-auth' in line:
            return line.strip()
        if line.strip().lower() in ['cookie:', 'cookie']:
            if i + 1 < len(lines):
                candidate = lines[i+1].strip()
                if 'ASLBSA=' in candidate or '__Secure-next-auth' in candidate:
                    return candidate

    return None


# ── Token pagina ──────────────────────────────────────────────────────────────
def show_token_page():
    st.title("🚢 DKM Import Dashboard")
    st.subheader("🔑 Sessie invoeren")

    tab1, tab2 = st.tabs(["📋 Methode 1 — Cookie plakken", "📄 Methode 2 — Volledige call dump"])

    with tab1:
        st.markdown("""
        <div style="background:#1a2a3a;border:1px solid #3cceff;border-radius:8px;padding:14px;margin:8px 0;color:#e0e0e0">
        <b style="color:#3cceff">Stap voor stap:</b><br>
        1. Ga naar <a href="https://irp.nxtport.com" target="_blank" style="color:#3cceff">irp.nxtport.com</a> en log in<br>
        2. Druk <b>F12</b> → tab <b>Network</b> → filter op <b>Fetch/XHR</b><br>
        3. Klik op de request <b>session</b><br>
        4. Tab <b>Headers</b> → zoek <b>Cookie</b> onder Request Headers<br>
        5. Kopieer de volledige Cookie waarde en plak hieronder
        </div>
        """, unsafe_allow_html=True)

        cookie_str = st.text_area("Cookie waarde:", height=80,
            placeholder="ASLBSA=...; __Secure-next-auth.session-token.0=eyJ...",
            key="cookie_direct")

        if st.button("✅ Opslaan & inloggen", type="primary", key="btn1"):
            if cookie_str and cookie_str.strip():
                _save_and_login(cookie_str.strip())
            else:
                st.warning("Voer eerst de cookie in.")

    with tab2:
        st.markdown("""
        <div style="background:#1a2a3a;border:1px solid #3cceff;border-radius:8px;padding:14px;margin:8px 0;color:#e0e0e0">
        <b style="color:#3cceff">Plak hier de volledige inhoud van de DevTools call:</b><br>
        1. Ga naar <a href="https://irp.nxtport.com" target="_blank" style="color:#3cceff">irp.nxtport.com</a> en log in<br>
        2. Druk <b>F12</b> → tab <b>Network</b> → klik op <b>session</b> request<br>
        3. Klik rechtsboven op <b>Copy</b> → <b>Copy request headers</b><br>
        4. Plak alles hieronder — de app extraheert automatisch de cookie
        </div>
        """, unsafe_allow_html=True)

        dump_str = st.text_area("Volledige header dump:", height=120,
            placeholder=":authority: irp.nxtport.com
:method: GET
...
Cookie: ASLBSA=...",
            key="cookie_dump")

        if st.button("🔍 Extraheer cookie & inloggen", type="primary", key="btn2"):
            if dump_str and dump_str.strip():
                cookie = extract_cookie_from_dump(dump_str.strip())
                if cookie:
                    st.info(f"Cookie gevonden ({len(cookie)} tekens) ✓")
                    _save_and_login(cookie)
                else:
                    st.error("❌ Geen cookie gevonden in de dump. Probeer Methode 1.")
            else:
                st.warning("Plak eerst de header dump.")

    st.caption("💡 De cookie is geldig tot middernacht. Daarna opnieuw invoeren.")


def _save_and_login(cookie_str: str):
    """Sla cookie op en log in."""
    irp = IRPClient()
    irp.set_cookies(cookie_str)
    try:
        save_cookie(cookie_str)
        st.success("✅ Ingelogd en cookie bewaard in Google Sheet!")
    except Exception as e:
        st.success("✅ Ingelogd!")
        st.warning(f"Kon niet opslaan in sheet: {e}")
    st.rerun()


# ── Polling logica ────────────────────────────────────────────────────────────
def run_poll(irp: IRPClient):
    ss   = get_client()
    ws   = ss.worksheet("Blad1")
    ensure_headers(ws)
    rows = get_all_rows(ws)

    stats   = {"skipped": 0, "crn_found": 0, "mrn_found": 0, "no_mrn_yet": 0, "errors": 0}
    results = []
    progress = st.progress(0, text="Bezig...")

    for i, row in enumerate(rows):
        progress.progress((i + 1) / max(len(rows), 1), text=f"Verwerken: {row['container']}")
        container = row["container"]
        bl        = row["bl"]
        crn       = row["crn"]
        mrn       = row["mrn_found"]

        # MRN al gevonden → overslaan, datum NIET updaten, geen poll nodig
        if mrn and mrn.strip():
            stats["skipped"] += 1
            log.info(f"[SKIP] {container} — MRN al gevonden: {mrn}, geen poll nodig")
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "✅ MRN Gevonden",
                "MRN"      : mrn,
                "TSD"      : row["status_tsd"],
                "Datum/Uur": row["last_poll"],  # datum NIET overschrijven
            })
            continue

        time.sleep(API_DELAY)

        if not crn:
            crn_result = irp.get_crn_from_bl(bl, container=container, eori=row["eori"])
            if not crn_result:
                stats["errors"] += 1
                results.append({
                    "DossierId": row["dossier_id"],
                    "Container": container,
                    "CRN"      : "",
                    "Status"   : "❌ CRN niet gevonden",
                    "MRN"      : "",
                    "TSD"      : "",
                    "Datum/Uur": now_str(),
                })
                continue
            crn    = crn_result
            tsd    = irp.get_tsd_information(crn)
            status = tsd.status_tsd if tsd else ""
            update_row_crn(ws, row["row_index"], crn, status)
            stats["crn_found"] += 1

            if tsd and tsd.mrn:
                update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
                stats["mrn_found"] += 1
                results.append({
                    "DossierId": row["dossier_id"],
                    "Container": container,
                    "CRN"      : crn,
                    "Status"   : "✅ MRN Gevonden",
                    "MRN"      : tsd.mrn,
                    "TSD"      : tsd.status_tsd,
                    "Datum/Uur": now_str(),
                })
            else:
                results.append({
                    "DossierId": row["dossier_id"],
                    "Container": container,
                    "CRN"      : crn,
                    "Status"   : "🟡 Wachten",
                    "MRN"      : "",
                    "TSD"      : status,
                    "Datum/Uur": now_str(),
                })
                stats["no_mrn_yet"] += 1
            continue

        tsd = irp.get_tsd_information(crn)
        if not tsd:
            stats["errors"] += 1
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "❌ API fout",
                "MRN"      : "",
                "TSD"      : "",
                "Datum/Uur": now_str(),
            })
            continue

        if tsd.mrn:
            update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
            stats["mrn_found"] += 1
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "✅ MRN Gevonden",
                "MRN"      : tsd.mrn,
                "TSD"      : tsd.status_tsd,
                "Datum/Uur": now_str(),
            })
        else:
            update_row_poll(ws, row["row_index"], tsd.status_tsd)
            stats["no_mrn_yet"] += 1
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "🟡 Wachten",
                "MRN"      : "",
                "TSD"      : tsd.status_tsd,
                "Datum/Uur": now_str(),
            })

    progress.empty()
    return stats, results


# ── Dashboard ─────────────────────────────────────────────────────────────────
def show_dashboard():
    irp = IRPClient()

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🚢 DKM Import")
        st.markdown("---")

        # NxtPort verbindingsstatus
        try:
            cookies = irp._parse_cookies(st.session_state.get("irp_cookies", ""))
            import requests as _req
            resp = _req.get(
                "https://irp.nxtport.com/api/auth/session",
                headers={
                    "Accept"      : "application/json",
                    "Content-Type": "application/json",
                    "User-Agent"  : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/116.0.0.0",
                },
                cookies=cookies, timeout=5,
            )
            data = resp.json() if resp.ok else {}
            if resp.status_code == 200 and data.get("idToken"):
                user = data.get("user", {})
                st.success("🟢 Verbonden met NxtPort")
                st.caption(f"👤 {user.get('email', '')}")
            elif resp.status_code == 200 and not data.get("idToken"):
                # Sessie bestaat maar token is verlopen
                st.warning("🟡 Sessie verlopen — nieuwe cookie nodig")
            else:
                st.error(f"🔴 Verbinding mislukt (HTTP {resp.status_code})")
        except Exception as e:
            st.warning(f"🟡 Verbinding onbekend: {e}")

        st.markdown("---")
        if st.button("🔄 Nu ophalen", use_container_width=True, type="primary"):
            st.session_state["run_poll"] = True
        st.markdown("---")
        if st.button("🔑 Nieuwe sessie", use_container_width=True):
            st.session_state.pop("irp_cookies", None)
            st.rerun()
        st.caption(f"🕐 {now_str()} UTC")

    # ── Hoofdpagina ───────────────────────────────────────────────────────────
    st.title("🚢 DKM Import Dashboard")

    if st.session_state.get("run_poll"):
        st.session_state.pop("run_poll", None)
        try:
            stats, results = run_poll(irp)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ MRN Gevonden", stats["mrn_found"])
            c2.metric("🟡 Wachten",      stats["no_mrn_yet"])
            c3.metric("⏭️ Klaar",        stats["skipped"])
            c4.metric("❌ Fouten",        stats["errors"])

            _show_results(results)
            st.success("✅ Sheet bijgewerkt!")

        except ValueError as e:
            if "verlopen" in str(e).lower():
                st.error("⏱️ Sessie verlopen — voer nieuwe cookie in.")
                st.session_state.pop("irp_cookies", None)
                st.rerun()
            else:
                st.error(f"Fout: {e}")
    else:
        try:
            ss   = get_client()
            ws   = ss.worksheet("Blad1")
            rows = get_all_rows(ws)
            if rows:
                results = [{
                    "DossierId": r["dossier_id"],
                    "Container": r["container"],
                    "CRN"      : r["crn"],
                    "Status"   : ("✅ MRN Gevonden" if r["mrn_found"]
                                  else "🟡 Wachten" if r["crn"]
                                  else "⏳ Nieuw"),
                    "MRN"      : r["mrn_found"],
                    "TSD"      : r["status_tsd"],
                    "Datum/Uur": r["last_poll"],
                } for r in rows]
                _show_results(results)
                st.caption(f"{len(rows)} dossiers • Klik 'Nu ophalen' om te vernieuwen")
            else:
                st.info("Geen dossiers gevonden.")
        except Exception as e:
            st.error(f"Fout: {e}")


def _show_results(results: list):
    """Toon resultaten met filter tabs."""
    if not results:
        return

    actief  = [r for r in results if "Wachten" in r["Status"] or "Nieuw" in r["Status"] or "Fout" in r["Status"]]
    klaar   = [r for r in results if "MRN Gevonden" in r["Status"]]

    tab1, tab2, tab3 = st.tabs([
        f"🟡 Actief / Pre-lodged ({len(actief)})",
        f"✅ MRN Gevonden ({len(klaar)})",
        f"📋 Alle dossiers ({len(results)})",
    ])

    with tab1:
        if actief:
            st.dataframe(actief, use_container_width=True, hide_index=True)
        else:
            st.info("Geen actieve dossiers.")

    with tab2:
        if klaar:
            st.dataframe(klaar, use_container_width=True, hide_index=True)
        else:
            st.info("Nog geen MRN gevonden.")

    with tab3:
        st.dataframe(results, use_container_width=True, hide_index=True)


# ── Main ──────────────────────────────────────────────────────────────────────
auto_load_cookie()
irp = IRPClient()
if irp.is_logged_in():
    show_dashboard()
else:
    show_token_page()
