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
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_DELAY = 1.5

st.set_page_config(
    page_title="DKM Import Dashboard",
    page_icon="🚢",
    layout="wide",
)

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #e8f9ff; }
    h1 { color: #f35e40; }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 13px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


def now_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")


# ── Token pagina ──────────────────────────────────────────────────────────────
def show_token_page():
    st.title("🚢 DKM Import Dashboard")
    st.subheader("🔑 Sessie invoeren")

    st.markdown("""
    <div style="background:#f0f9ff;border:1px solid #3cceff;border-radius:8px;padding:16px;margin:8px 0">
    <b>Hoe krijg je de sessie cookie?</b><br>
    1. Ga naar <a href="https://irp.nxtport.com" target="_blank">irp.nxtport.com</a> en log in<br>
    2. Druk <b>F12</b> → tab <b>Network</b> → filter op <b>Fetch/XHR</b><br>
    3. Klik op de request <b>session</b><br>
    4. Tab <b>Headers</b> → zoek <b>Cookie</b> onder Request Headers<br>
    5. Kopieer de volledige Cookie waarde en plak hieronder
    </div>
    """, unsafe_allow_html=True)

    cookie_str = st.text_area("Cookie:", height=100,
        placeholder="ASLBSA=...; __Secure-next-auth.session-token.0=eyJ...")

    if st.button("✅ Opslaan & inloggen", type="primary"):
        if cookie_str and cookie_str.strip():
            irp = IRPClient()
            irp.set_cookies(cookie_str.strip())
            st.success("✅ Sessie opgeslagen!")
            st.rerun()
        else:
            st.warning("Voer eerst de cookie in.")

    st.caption("💡 De cookie is geldig tot middernacht. Daarna opnieuw invoeren.")


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

        # MRN al gevonden → overslaan, datum NIET updaten
        if mrn and mrn.strip():
            stats["skipped"] += 1
            results.append({
                "DossierId": row["dossier_id"],
                "Container": container,
                "CRN"      : crn,
                "Status"   : "✅ MRN Gevonden",
                "MRN"      : mrn,
                "TSD"      : row["status_tsd"],
                "Datum/Uur": row["last_poll"],
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
                headers={"Accept": "application/json"},
                cookies=cookies, timeout=5,
            )
            if resp.status_code == 200 and resp.json().get("idToken"):
                user = resp.json().get("user", {})
                st.success("🟢 Verbonden met NxtPort")
                st.caption(f"👤 {user.get('email', '')}")
            else:
                st.error("🔴 Sessie verlopen")
        except Exception:
            st.warning("🟡 Verbinding onbekend")

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
irp = IRPClient()
if irp.is_logged_in():
    show_dashboard()
else:
    show_token_page()
