"""
DKM Import Release Dashboard
Token manueel invoeren via de UI
"""

import logging
import time
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
    .token-box { background: #f0f9ff; border: 1px solid #3cceff;
                 border-radius: 8px; padding: 16px; margin: 8px 0; }
</style>
""", unsafe_allow_html=True)


# ── Token pagina ──────────────────────────────────────────────────────────────
def show_token_page():
    st.title("🚢 DKM Import Dashboard")

    st.markdown("### 🔑 IRP Token invoeren")

    st.markdown("""
    <div class="token-box">
    <b>Hoe krijg je de Bearer token?</b><br>
    1. Ga naar <a href="https://irp.nxtport.com" target="_blank">irp.nxtport.com</a> en log in (met MFA)<br>
    2. Druk <b>F12</b> → tab <b>Network</b> → filter op <b>Fetch/XHR</b><br>
    3. Klik op een API call (bv. <b>reference</b> of <b>session</b>)<br>
    4. Tab <b>Headers</b> → zoek <b>Authorization</b><br>
    5. Kopieer alles na <b>"Bearer "</b> (de lange eyJ... tekst)
    </div>
    """, unsafe_allow_html=True)

    cookie_str = st.text_area(
        "Plak hier de Bearer token (of volledige Authorization header):",
        height=120,
        placeholder="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
    )

    if st.button("✅ Opslaan & inloggen", type="primary"):
        if cookie_str and cookie_str.strip():
            irp = IRPClient()
            irp.set_token(cookie_str.strip())
            st.success("✅ Sessie opgeslagen! Dashboard laden...")
            st.rerun()
        else:
            st.warning("Voer eerst de cookie waarde in.")

    st.markdown("---")
    st.caption("💡 Tip: de token is geldig voor ±1 uur. Na verloop moet je opnieuw inloggen op irp.nxtport.com en een nieuwe token invoeren.")


# ── Polling logica ────────────────────────────────────────────────────────────
def run_poll(irp: IRPClient):
    ss   = get_client()
    ws   = ss.worksheet("Blad1")
    ensure_headers(ws)
    rows = get_all_rows(ws)

    stats    = {"skipped": 0, "crn_found": 0, "mrn_found": 0, "no_mrn_yet": 0, "errors": 0}
    results  = []
    progress = st.progress(0, text="Bezig...")

    for i, row in enumerate(rows):
        progress.progress((i + 1) / max(len(rows), 1), text=f"Verwerken: {row['container']}")
        container = row["container"]
        bl        = row["bl"]
        crn       = row["crn"]
        mrn       = row["mrn_found"]

        if mrn and mrn.strip():
            stats["skipped"] += 1
            results.append({"Container": container, "Status": "⏭️ Klaar", "MRN": mrn, "TSD": row["status_tsd"]})
            continue

        time.sleep(API_DELAY)

        if not crn:
            crn_result = irp.get_crn_from_bl(bl, container=container, eori=row['eori'])
            if not crn_result:
                stats["errors"] += 1
                results.append({"Container": container, "Status": "❌ CRN niet gevonden", "MRN": "", "TSD": ""})
                continue
            crn    = crn_result
            tsd    = irp.get_tsd_information(crn)
            status = tsd.status_tsd if tsd else ""
            update_row_crn(ws, row["row_index"], crn, status)
            stats["crn_found"] += 1
            if tsd and tsd.mrn:
                update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
                stats["mrn_found"] += 1
                results.append({"Container": container, "Status": "✅ MRN gevonden", "MRN": tsd.mrn, "TSD": tsd.status_tsd})
            else:
                results.append({"Container": container, "Status": f"🟡 Wachten", "MRN": "", "TSD": status})
                stats["no_mrn_yet"] += 1
            continue

        tsd = irp.get_tsd_information(crn)
        if not tsd:
            stats["errors"] += 1
            results.append({"Container": container, "Status": "❌ API fout", "MRN": "", "TSD": ""})
            continue

        if tsd.mrn:
            update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
            stats["mrn_found"] += 1
            results.append({"Container": container, "Status": "✅ MRN gevonden", "MRN": tsd.mrn, "TSD": tsd.status_tsd})
        else:
            update_row_poll(ws, row["row_index"], tsd.status_tsd)
            stats["no_mrn_yet"] += 1
            results.append({"Container": container, "Status": f"🟡 {tsd.status_tsd}", "MRN": "", "TSD": tsd.status_tsd})

    progress.empty()
    return stats, results


# ── Dashboard ─────────────────────────────────────────────────────────────────
def show_dashboard():
    irp = IRPClient()

    with st.sidebar:
        st.markdown("### 🚢 DKM Import")
        st.success("✅ Token actief")
        st.markdown("---")
        if st.button("🔄 Nu ophalen", use_container_width=True, type="primary"):
            st.session_state["run_poll"] = True
        st.markdown("---")
        if st.button("🔑 Nieuwe token invoeren", use_container_width=True):
            st.session_state.pop("irp_token", None)
            st.rerun()
        st.caption("Token vervalt na ±1 uur")

    st.title("🚢 DKM Import Dashboard")

    if st.session_state.get("run_poll"):
        st.session_state.pop("run_poll", None)
        try:
            stats, results = run_poll(irp)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ MRN Gevonden", stats["mrn_found"])
            c2.metric("🟡 Wachten", stats["no_mrn_yet"])
            c3.metric("⏭️ Klaar", stats["skipped"])
            c4.metric("❌ Fouten", stats["errors"])
            if results:
                st.dataframe(results, use_container_width=True)
            st.success("✅ Sheet bijgewerkt!")
        except ValueError as e:
            if "Token verlopen" in str(e):
                st.error("⏱️ Token verlopen — voer een nieuwe token in.")
                st.session_state.pop("irp_token", None)
                st.rerun()
            else:
                st.error(f"Fout: {e}")
    else:
        try:
            ss   = get_client()
            ws   = ss.worksheet("Blad1")
            rows = get_all_rows(ws)
            if rows:
                st.markdown("### 📋 Huidige dossiers")
                st.dataframe(rows, use_container_width=True)
                st.caption(f"{len(rows)} dossiers • Klik 'Nu ophalen' in de sidebar om te vernieuwen")
            else:
                st.info("Geen dossiers gevonden.")
        except Exception as e:
            st.error(f"Fout bij laden: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
irp = IRPClient()
if irp.is_logged_in():
    show_dashboard()
else:
    show_token_page()
