"""
DKM Import Release Dashboard
Streamlit app met login pagina via e-mail verificatiecode
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

# ── Pagina config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DKM Import Dashboard",
    page_icon="🚢",
    layout="wide",
)

# DKM stijl
st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #3cceff22; }
    .stButton > button { background-color: #3cceff; color: white; border: none; }
    .stButton > button:hover { background-color: #1ab5ef; }
    h1 { color: #f35e40; }
</style>
""", unsafe_allow_html=True)

# ── Login pagina ──────────────────────────────────────────────────────────────
def show_login():
    st.title("🚢 DKM Import Dashboard")
    st.subheader("Inloggen op IRP NxtPort")

    irp = IRPClient()

    # Stap 1: Login starten
    if "login_state" not in st.session_state:
        st.info("Klik op 'Verstuur verificatiecode' om een code naar je e-mail te sturen.")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("📧 Verstuur verificatiecode", use_container_width=True):
                with st.spinner("Bezig met inloggen..."):
                    try:
                        login_state = irp.start_login()
                        st.session_state["login_state"] = login_state
                        st.success(f"✅ Code verstuurd naar {st.secrets['irp']['username']}!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Fout bij inloggen: {e}")

    # Stap 2: Code invoeren
    else:
        st.success(f"✅ Verificatiecode verstuurd naar e-mail van {st.secrets['irp']['username']}")
        st.info("Voer de 6-cijferige code in die je per e-mail ontvangen hebt.")

        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            otp = st.text_input("Verificatiecode", max_chars=8, placeholder="123456")
        with col2:
            st.write("")
            st.write("")
            if st.button("✅ Bevestigen", use_container_width=True):
                if otp:
                    with st.spinner("Code verifiëren..."):
                        try:
                            success = irp.complete_login(
                                st.session_state["login_state"], otp.strip()
                            )
                            if success:
                                st.session_state.pop("login_state", None)
                                st.success("🎉 Ingelogd!")
                                st.rerun()
                            else:
                                st.error("❌ Ongeldige code. Probeer opnieuw.")
                                st.session_state.pop("login_state", None)
                        except Exception as e:
                            st.error(f"❌ Fout: {e}")
                            st.session_state.pop("login_state", None)
                else:
                    st.warning("Voer eerst de code in.")

        with col3:
            st.write("")
            st.write("")
            if st.button("🔄 Nieuwe code sturen"):
                st.session_state.pop("login_state", None)
                st.rerun()


# ── Polling logica ────────────────────────────────────────────────────────────
def run_poll(irp: IRPClient):
    ss  = get_client()
    ws  = ss.worksheet("Blad1")
    ensure_headers(ws)
    rows = get_all_rows(ws)

    stats = {"skipped": 0, "crn_found": 0, "mrn_found": 0, "no_mrn_yet": 0, "errors": 0}
    progress = st.progress(0, text="Bezig met ophalen...")
    results  = []

    for i, row in enumerate(rows):
        progress.progress((i + 1) / len(rows), text=f"Verwerken: {row['container']}")
        container = row["container"]
        bl        = row["bl"]
        crn       = row["crn"]
        mrn       = row["mrn_found"]

        if mrn and mrn.strip():
            stats["skipped"] += 1
            results.append({"container": container, "status": "⏭️ Overgeslagen", "mrn": mrn})
            continue

        time.sleep(API_DELAY)

        if not crn:
            crn_result = irp.get_crn_from_bl(bl)
            if not crn_result:
                stats["errors"] += 1
                results.append({"container": container, "status": "❌ CRN niet gevonden", "mrn": ""})
                continue

            crn = crn_result
            tsd = irp.get_tsd_information(crn)
            status = tsd.status_tsd if tsd else ""
            update_row_crn(ws, row["row_index"], crn, status)
            stats["crn_found"] += 1

            if tsd and tsd.mrn:
                update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
                stats["mrn_found"] += 1
                results.append({"container": container, "status": "✅ MRN gevonden", "mrn": tsd.mrn})
            else:
                results.append({"container": container, "status": f"🟡 Wachten ({status})", "mrn": ""})
                stats["no_mrn_yet"] += 1
            continue

        tsd = irp.get_tsd_information(crn)
        if not tsd:
            stats["errors"] += 1
            results.append({"container": container, "status": "❌ API fout", "mrn": ""})
            continue

        if tsd.mrn:
            update_row_mrn(ws, row["row_index"], tsd.mrn, tsd.status_tsd)
            stats["mrn_found"] += 1
            results.append({"container": container, "status": "✅ MRN gevonden", "mrn": tsd.mrn})
        else:
            update_row_poll(ws, row["row_index"], tsd.status_tsd)
            stats["no_mrn_yet"] += 1
            results.append({"container": container, "status": f"🟡 Wachten ({tsd.status_tsd})", "mrn": ""})

    progress.empty()
    return stats, results, rows


# ── Dashboard ─────────────────────────────────────────────────────────────────
def show_dashboard():
    irp = IRPClient()

    # Sidebar
    with st.sidebar:
        st.image("https://www.dkm-customs.com/wp-content/uploads/2021/03/DKM-logo.png",
                 use_column_width=True)
        st.markdown("---")
        st.success("✅ Ingelogd op IRP")
        if st.button("🔓 Uitloggen"):
            st.session_state.pop("irp_token", None)
            st.rerun()
        st.markdown("---")
        if st.button("🔄 Nu ophalen", use_container_width=True, type="primary"):
            st.session_state["run_poll"] = True

    st.title("🚢 DKM Import Dashboard")
    st.caption("Live MRN status via IRP NxtPort")

    # Poll uitvoeren
    if st.session_state.get("run_poll"):
        st.session_state.pop("run_poll", None)
        try:
            stats, results, rows = run_poll(irp)

            # Statistieken
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("✅ MRN Gevonden", stats["mrn_found"])
            col2.metric("🟡 Wachten", stats["no_mrn_yet"])
            col3.metric("⏭️ Overgeslagen", stats["skipped"])
            col4.metric("❌ Fouten", stats["errors"])

            # Resultaten tabel
            if results:
                st.markdown("### Resultaten")
                st.dataframe(results, use_container_width=True)

            st.success("✅ Sheet bijgewerkt!")

        except ValueError as e:
            if "Token verlopen" in str(e):
                st.error("⏱️ Sessie verlopen — log opnieuw in.")
                st.session_state.pop("irp_token", None)
                st.rerun()
            else:
                st.error(f"Fout: {e}")

    else:
        # Sheet tonen
        try:
            ss   = get_client()
            ws   = ss.worksheet("Blad1")
            rows = get_all_rows(ws)

            if rows:
                st.markdown("### 📋 Huidige dossiers")
                st.dataframe(rows, use_container_width=True)
                st.caption(f"{len(rows)} dossiers • Klik 'Nu ophalen' om te vernieuwen")
            else:
                st.info("Geen dossiers gevonden in de sheet.")
        except Exception as e:
            st.error(f"Fout bij laden sheet: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
irp = IRPClient()
if irp.is_logged_in():
    show_dashboard()
else:
    show_login()
