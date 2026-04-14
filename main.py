"""
DKM Import Release Dashboard v2
"""

import logging
import time
from datetime import datetime, timezone, timedelta
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
    mark_email_sent,
    add_dossier,
    update_row_packages,
)
from email_client import send_mrn_notification

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_DELAY = 1.5


def auto_load_cookie():
    """Laad cookie automatisch uit Google Sheet bij opstarten."""
    if not st.session_state.get("irp_cookies"):
        try:
            cookie = load_cookie()
            if cookie and len(cookie) > 50:  # lege of gewiste cookie negeren
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


def parse_eta(eta_str: str):
    """Parseer ETA datum string (DD/MM/YYYY of YYYY-MM-DD). Geeft date object terug of None."""
    if not eta_str or not eta_str.strip():
        return None
    for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]:
        try:
            return datetime.strptime(eta_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def should_poll(row: dict) -> tuple[bool, str]:
    """
    Bepaal of een container gepolled moet worden.
    Geeft (True, "") terug als polling nodig is.
    Geeft (False, status_msg) terug als polling overgeslagen wordt.
    """
    eta_str = row.get("eta", "")
    eta = parse_eta(eta_str)
    if eta is None:
        return True, ""  # Geen ETA → altijd pollen
    today = datetime.now(timezone.utc).date()
    drempel = today + timedelta(days=7)
    if eta > drempel:
        return False, f"📅 ETA {eta.strftime('%d/%m/%Y')}"
    return True, ""


import re as _re

def extract_cookie_from_dump(text: str) -> str | None:
    """Extraheer de Cookie waarde uit een volledige DevTools header dump."""
    lines = text.split("\n")

    # Methode 1: Zoek "Cookie:" label gevolgd door waarde op volgende regel
    for i, line in enumerate(lines):
        stripped = line.strip().rstrip(":")
        if stripped.lower() == "cookie" and i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if "ASLBSA=" in candidate or "__Secure-next-auth" in candidate:
                return candidate

    # Methode 2: Zoek een regel die de cookie waarde bevat
    for line in lines:
        stripped = line.strip()
        if "ASLBSA=" in stripped and "__Secure-next-auth" in stripped:
            return stripped

    # Methode 3: Combineer meerdere regels na Cookie:
    for i, line in enumerate(lines):
        if "Cookie:" in line:
            # Cookie staat misschien op dezelfde regel
            after = line.split("Cookie:", 1)[1].strip()
            if after and ("ASLBSA=" in after or "__Secure-next-auth" in after):
                return after

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
            placeholder="Plak hier de volledige inhoud van de DevTools call...",
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

        # ETA check → overslaan als ETA meer dan 7 dagen in de toekomst
        poll_ok, eta_status = should_poll(row)
        if not poll_ok:
            stats["skipped"] += 1
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : eta_status,
                "MRN"      : "",
                "TSD"      : row["status_tsd"],
                "Collis"   : "",
                "Massa(kg)": "",
                "Datum/Uur": row["last_poll"],
                "ETA"      : row.get("eta", ""),
            })
            continue

        # MRN al gevonden → overslaan, datum NIET updaten, geen poll nodig
        if mrn and mrn.strip():
            stats["skipped"] += 1
            log.info(f"[SKIP] {container} — MRN al gevonden: {mrn}, geen poll nodig")
            # Check of email al verstuurd — zo niet, alsnog sturen
            if row.get("email_sent") != "✓":
                log.info(f"[EMAIL] {container} — MRN gekend maar email nog niet verstuurd")
                _send_mrn_email(ws, row, container, crn, mrn, row["status_tsd"])
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "✅ MRN Gevonden",
                "MRN"      : mrn,
                "TSD"      : row["status_tsd"],
                "Collis"   : row.get("collis", ""),
                "Massa(kg)": row.get("gross_mass", ""),
                "Datum/Uur": row["last_poll"],
            })
            continue

        time.sleep(API_DELAY)

        if not crn:
            # Check eerst of parameters volledig zijn
            if not bl or not row["eori"]:
                stats["errors"] += 1
                missing = []
                if not bl: missing.append("BL")
                if not row["eori"]: missing.append("EORI")
                results.append({
                    "DossierId": row["dossier_id"],
                    "Container": container,
                    "CRN"      : "",
                    "Status"   : f"⚠️ Parameters onvolledig ({', '.join(missing)})",
                    "MRN"      : "",
                    "TSD"      : "",
                    "Collis"   : "",
                    "Massa(kg)": "",
                    "Datum/Uur": now_str(),
                })
                continue

            crn_result = irp.get_crn_from_bl(bl, container=container, eori=row["eori"])
            if not crn_result:
                stats["errors"] += 1
                results.append({
                    "DossierId": row["dossier_id"],
                    "Container": container,
                    "CRN"      : "",
                    "Status"   : "❓ Geen CRN in NxtPort",
                    "MRN"      : "",
                    "TSD"      : "",
                    "Collis"   : "",
                    "Massa(kg)": "",
                    "Datum/Uur": now_str(),
                })
                continue
            crn    = crn_result
            tsd    = irp.get_tsd_information(crn)  # Altijd write-off ophalen voor nieuwe CRN
            status = tsd.status_tsd if tsd else ""
            update_row_crn(ws, row["row_index"], crn, status)
            stats["crn_found"] += 1

            if tsd and tsd.mrn:
                update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
                update_row_packages(ws, row["row_index"], tsd.packages_released, tsd.gross_mass_released)
                stats["mrn_found"] += 1
                _send_mrn_email(ws, row, container, crn, tsd.mrn, tsd.status_tsd)
                results.append({
                    "DossierId": row["dossier_id"],
                    "Container": container,
                    "CRN"      : crn,
                    "Status"   : "✅ MRN Gevonden",
                    "MRN"      : tsd.mrn,
                    "TSD"      : tsd.status_tsd,
                    "Collis"   : "",
                    "Massa(kg)": "",
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
                    "Collis"   : "",
                    "Massa(kg)": "",
                    "Datum/Uur": now_str(),
                })
                stats["no_mrn_yet"] += 1
            continue

        # Skip write-off als collis al ingevuld in sheet
        collis_known = bool(row.get("collis") and row["collis"].strip())
        tsd = irp.get_tsd_information(crn, skip_writeoff=collis_known)
        if not tsd:
            stats["errors"] += 1
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "❌ API fout",
                "MRN"      : "",
                "TSD"      : "",
                "Collis"   : "",
                "Massa(kg)": "",
                "Datum/Uur": now_str(),
            })
            continue

        if tsd.mrn:
            update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
            update_row_packages(ws, row["row_index"], tsd.packages_released, tsd.gross_mass_released)
            stats["mrn_found"] += 1
            _send_mrn_email(ws, row, container, crn, tsd.mrn, tsd.status_tsd)
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "✅ MRN Gevonden",
                "MRN"      : tsd.mrn,
                "TSD"      : tsd.status_tsd,
                "Collis"   : "",
                "Massa(kg)": "",
                "Datum/Uur": now_str(),
            })
        else:
            update_row_poll(ws, row["row_index"], tsd.status_tsd)
            update_row_packages(ws, row["row_index"], tsd.packages_released, tsd.gross_mass_released)
            stats["no_mrn_yet"] += 1
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "🟡 Wachten",
                "MRN"      : "",
                "TSD"      : tsd.status_tsd,
                "Collis"   : "",
                "Massa(kg)": "",
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
                st.warning("🟡 Sessie verlopen")
                if st.button("🔑 Vernieuwen", use_container_width=True, key="renew_sidebar"):
                    st.session_state.pop("irp_cookies", None)
                    try:
                        save_cookie("")
                    except Exception:
                        pass
                    st.rerun()
            else:
                st.error(f"🔴 Verbinding mislukt")
                if st.button("🔑 Nieuwe sessie", use_container_width=True, key="renew_error"):
                    st.session_state.pop("irp_cookies", None)
                    try:
                        save_cookie("")
                    except Exception:
                        pass
                    st.rerun()
        except Exception as e:
            st.warning(f"🟡 Verbinding onbekend: {e}")

        st.markdown("---")
        if st.button("🔄 Nu ophalen", use_container_width=True, type="primary"):
            st.session_state["run_poll"] = True
            st.session_state["page"] = "dashboard"
        if st.button("➕ Nieuw dossier", use_container_width=True):
            st.session_state["page"] = "nieuw"
            st.rerun()
        st.markdown("---")

        # Auto-refresh toggle
        auto = st.toggle("⏱️ Auto-refresh (60 min)", value=st.session_state.get("auto_refresh", False))
        st.session_state["auto_refresh"] = auto
        if auto:
            st.caption("🟢 Volgende refresh over 60 min")
        st.markdown("---")
        sidebar_stats = st.container()
        st.markdown("---")
        if st.button("🔑 Nieuwe sessie invoeren", use_container_width=True):
            st.session_state.pop("irp_cookies", None)
            try:
                save_cookie("")  # Wis ook de cookie in de sheet
            except Exception:
                pass
            st.rerun()
        st.caption(f"🕐 {now_str()} UTC")

    # ── Hoofdpagina ───────────────────────────────────────────────────────────
    st.title("🚢 DKM Import Dashboard")

    # Auto-refresh elke 60 minuten
    if st.session_state.get("auto_refresh"):
        import time as _time
        last = st.session_state.get("last_auto_poll", 0)
        now  = _time.time()
        remaining = max(0, 3600 - int(now - last))
        mins, secs = divmod(remaining, 60)
        if remaining == 0:
            st.session_state["last_auto_poll"] = now
            st.session_state["run_poll"] = True
        else:
            # Refresh de pagina elke 60 seconden om countdown bij te werken
            st.markdown(
                f'<meta http-equiv="refresh" content="60">',
                unsafe_allow_html=True
            )

    if st.session_state.get("run_poll"):
        st.session_state.pop("run_poll", None)
        try:
            with st.spinner("Bezig met ophalen..."):
                stats, results = run_poll(irp)

            # Statistieken in sidebar
            with sidebar_stats:
                st.markdown("**Laatste run:**")
                st.metric("✅ MRN Gevonden", stats["mrn_found"])
                st.metric("🟡 Wachten",      stats["no_mrn_yet"])
                st.metric("⏭️ Klaar",        stats["skipped"])
                st.metric("❌ Fouten",        stats["errors"])
                st.success("✅ Sheet bijgewerkt!")

            _show_results(results)

        except ValueError as e:
            if "verlopen" in str(e).lower() or "cookie" in str(e).lower():
                with sidebar_stats:
                    st.error("⏱️ Sessie verlopen!")
                st.session_state.pop("irp_cookies", None)
                st.rerun()
            else:
                with sidebar_stats:
                    st.error(f"Fout: {e}")
    else:
        try:
            ss   = get_client()
            ws   = ss.worksheet("Blad1")
            rows = get_all_rows(ws)
            if rows:
                def _status(r):
                    if r["mrn_found"]:
                        return "✅ MRN Gevonden"
                    if r["crn"]:
                        # Check ETA
                        poll_ok, eta_st = should_poll(r)
                        if not poll_ok:
                            return eta_st
                        return "🟡 Wachten"
                    if not r["bl"] or not r["eori"]:
                        return "⚠️ Parameters onvolledig"
                    # Check ETA ook voor nieuwe containers
                    poll_ok, eta_st = should_poll(r)
                    if not poll_ok:
                        return eta_st
                    if r["last_poll"]:
                        return "❓ Geen CRN in NxtPort"
                    return "⏳ Nieuw"

                results = [{
                    "DossierId": r["dossier_id"],
                    "Container": r["container"],
                    "BL"       : r["bl"],
                    "EORI"     : r["eori"],
                    "CRN"      : r["crn"],
                    "Status"   : _status(r),
                    "MRN"      : r["mrn_found"],
                    "TSD"      : r["status_tsd"],
                    "Collis"   : r.get("collis", ""),
                    "Massa(kg)": r.get("gross_mass", ""),
                    "Datum/Uur": r["last_poll"],
                    "ETA"      : r.get("eta", ""),
                } for r in rows]
                _show_results(results)
                st.caption(f"{len(rows)} dossiers • Klik 'Nu ophalen' in de sidebar")
            else:
                st.info("Geen dossiers gevonden.")
        except Exception as e:
            st.error(f"Fout: {e}")


def _send_mrn_email(ws, row: dict, container: str, crn: str, mrn: str, status_tsd: str):
    """Stuur MRN notificatie email — max 1x per container."""
    if row.get("email_sent") == "✓":
        log.info(f"Email al verstuurd voor {container} — overgeslagen")
        return
    ok = send_mrn_notification(
        dossier_id = row.get("dossier_id", ""),
        container  = container,
        bl         = row.get("bl", ""),
        crn        = crn,
        mrn        = mrn,
        status_tsd = status_tsd,
    )
    if ok:
        mark_email_sent(ws, row["row_index"])
        log.info(f"MRN email verstuurd voor {container}")
    else:
        log.error(f"E-mail versturen mislukt voor {container}")


def _show_results(results: list):
    """Toon resultaten met filter tabs."""
    if not results:
        return

    from datetime import date
    vandaag     = date.today().strftime("%d/%m/%Y")

    actief      = [r for r in results if "Wachten" in r["Status"] or "Nieuw" in r["Status"]]
    klaar       = [r for r in results if "MRN Gevonden" in r["Status"] and r.get("Datum/Uur", "")[:10] >= vandaag]
    klaar_oud   = [r for r in results if "MRN Gevonden" in r["Status"] and r.get("Datum/Uur", "")[:10] < vandaag]
    geen_crn    = [r for r in results if "Geen CRN" in r["Status"]]
    onvolledig  = [r for r in results if "onvolledig" in r["Status"]]
    eta_wacht   = [r for r in results if "📅 ETA" in r["Status"]]

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        f"🟡 Actief ({len(actief)})",
        f"✅ MRN Gevonden ({len(klaar)})",
        f"📦 MRN Ouder dan vandaag ({len(klaar_oud)})",
        f"📅 ETA — nog niet aan bod ({len(eta_wacht)})",
        f"❓ Geen CRN in NxtPort ({len(geen_crn)})",
        f"⚠️ Onvolledige parameters ({len(onvolledig)})",
        f"📋 Alle dossiers ({len(results)})",
    ])

    with tab1:
        if actief:
            st.dataframe(actief, use_container_width=True, hide_index=True, height=400)
        else:
            st.info("Geen actieve dossiers.")

    with tab2:
        if klaar:
            st.dataframe(klaar, use_container_width=True, hide_index=True, height=400)
        else:
            st.info("Nog geen MRN gevonden.")

    with tab3:
        if klaar_oud:
            st.info("MRN's gevonden vóór vandaag — deze dossiers zijn afgehandeld.")
            st.dataframe(klaar_oud, use_container_width=True, hide_index=True, height=400)
        else:
            st.success("Geen afgehandelde dossiers van vorige dagen.")

    with tab4:
        if eta_wacht:
            st.info("Deze containers worden nog niet gepolled — hun ETA is meer dan 7 dagen in de toekomst.")
            st.dataframe(eta_wacht, use_container_width=True, hide_index=True, height=350)
        else:
            st.success("Geen containers in ETA-wachtstatus.")

    with tab5:
        if geen_crn:
            st.info("Deze containers zijn correct ingegeven maar hebben nog geen CRN in NxtPort. Ze worden bij elke poll opnieuw gecontroleerd.")
            st.dataframe(geen_crn, use_container_width=True, hide_index=True, height=350)
        else:
            st.success("Alle dossiers met volledige parameters hebben een CRN.")

    with tab6:
        if onvolledig:
            st.warning("Vul de ontbrekende parameters aan zodat de opzoeking in NxtPort kan starten.")
            for r in onvolledig:
                with st.expander(f"✏️  {r['DossierId']} — {r['Container']}  ({r['Status']})"):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        bl_val = st.text_input(
                            "Bill of Lading",
                            value=r.get("BL") or r.get("bl") or "",
                            key=f"bl_{r['Container']}",
                            placeholder="MEDUXO084545",
                        )
                    with col2:
                        eori_val = st.text_input(
                            "EORI Ship Agent",
                            value=r.get("EORI") or r.get("eori") or "",
                            key=f"eori_{r['Container']}",
                            placeholder="BE0464255361",
                        )
                    with col3:
                        eta_val = st.text_input(
                            "ETA (DD/MM/YYYY)",
                            value=r.get("ETA") or r.get("eta") or "",
                            key=f"eta_{r['Container']}",
                            placeholder="28/04/2026",
                        )
                    if st.button(f"💾 Opslaan", key=f"save_{r['Container']}"):
                        if not bl_val.strip() or not eori_val.strip():
                            st.error("BL en EORI zijn verplicht.")
                        else:
                            try:
                                ss  = get_client()
                                ws  = ss.worksheet("Blad1")
                                row_idx = None
                                # Zoek de juiste rij via container nummer
                                all_rows = get_all_rows(ws)
                                for row in all_rows:
                                    if row["container"] == r["Container"]:
                                        row_idx = row["row_index"]
                                        break
                                if row_idx:
                                    from sheets_client import COL
                                    ws.update_cell(row_idx, COL["BL"],   bl_val.strip())
                                    ws.update_cell(row_idx, COL["EORI"], eori_val.strip())
                                    if eta_val.strip():
                                        ws.update_cell(row_idx, COL["ETA"], eta_val.strip())
                                    st.success(f"✅ {r['Container']} bijgewerkt!")
                                    st.rerun()
                                else:
                                    st.error("Rij niet gevonden in sheet.")
                            except Exception as e:
                                st.error(f"Fout: {e}")
        else:
            st.success("Alle dossiers hebben volledige parameters.")

    with tab7:
        st.dataframe(results, use_container_width=True, hide_index=True, height=500)


def show_nieuw_dossier():
    """Pagina om een nieuw dossier toe te voegen."""
    st.title("➕ Nieuw dossier toevoegen")

    with st.sidebar:
        st.markdown("### 🚢 DKM Import")
        st.markdown("---")
        if st.button("← Terug naar dashboard", use_container_width=True):
            st.session_state["page"] = "dashboard"
            st.rerun()

    st.markdown("Vul alle velden in om een nieuw dossier toe te voegen aan de Google Sheet.")
    st.markdown("---")

    with st.form("nieuw_dossier_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            dossier_id = st.text_input("Dossier ID *", placeholder="244999")
            container  = st.text_input("Container nummer *", placeholder="MSCU1234567")
            bl         = st.text_input("Bill of Lading (BL) *", placeholder="MEDUXO084545")

        with col2:
            eori       = st.text_input("EORI Ship Agent *", placeholder="BE0464255361")
            eta_input  = st.date_input("ETA (verwachte aankomst)", value=None)
            st.caption("ETA is optioneel — laat leeg als onbekend")

        st.markdown("---")
        submitted = st.form_submit_button("✅ Dossier toevoegen", type="primary", use_container_width=True)

        if submitted:
            # Validatie
            errors = []
            if not dossier_id.strip(): errors.append("Dossier ID")
            if not container.strip():  errors.append("Container nummer")
            if not bl.strip():         errors.append("Bill of Lading")
            if not eori.strip():       errors.append("EORI Ship Agent")

            if errors:
                st.error(f"❌ Vul de verplichte velden in: {', '.join(errors)}")
            else:
                eta_str = eta_input.strftime("%d/%m/%Y") if eta_input else ""
                try:
                    ss = get_client()
                    ws = ss.worksheet("Blad1")
                    add_dossier(ws,
                        dossier_id = dossier_id.strip(),
                        container  = container.strip().upper(),
                        bl         = bl.strip(),
                        eori       = eori.strip(),
                        eta        = eta_str,
                    )
                    st.success(f"✅ Dossier {dossier_id.strip()} — {container.strip().upper()} succesvol toegevoegd!")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ Fout bij opslaan: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
auto_load_cookie()
irp = IRPClient()

if not irp.is_logged_in():
    show_token_page()
elif st.session_state.get("page") == "nieuw":
    show_nieuw_dossier()
else:
    st.session_state["page"] = "dashboard"
    show_dashboard()
