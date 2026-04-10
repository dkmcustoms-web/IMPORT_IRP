import streamlit as st
import time
import os
import re as _re
from sheets_queue import SheetsQueue
from gmail_sender import GmailSender
from gmail_reader import GmailReader
from code_validator import validate

st.set_page_config(page_title="DKM · Commodity Checker", page_icon="🔍", layout="wide")

for key in ["ANTHROPIC_API_KEY","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASSWORD",
            "SMTP_FROM","COMMODITY_SHEET_ID","COMMODITY_CC","COMMODITIES_CSV_PATH","GMAIL_SERVICE_ACCOUNT_JSON"]:
    if key in st.secrets and key not in os.environ:
        os.environ[key] = str(st.secrets[key])

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
[data-testid="stSidebar"]{background:#1a1a2e!important;border-right:2px solid #3cceff33;}
[data-testid="stSidebar"] *{color:#e0e0e0!important;}
.main{background:#0f0f1a;} .block-container{padding-top:2rem;}

.metric-card{background:#16213e;border:1px solid #3cceff22;border-radius:8px;padding:0.8rem 1rem;margin-bottom:0.6rem;border-left:3px solid var(--accent);}
.metric-card .label{font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:1px;}
.metric-card .value{font-family:'DM Mono',monospace;font-size:1.6rem;color:#fff;margin-top:2px;}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-family:'DM Mono',monospace;font-weight:500;}
.badge-pending{background:#2d2010;color:#f0a500;border:1px solid #f0a50055;}
.badge-flagged{background:#2d1010;color:#f35e40;border:1px solid #f35e4055;}
.badge-sent{background:#0d1a2d;color:#3cceff;border:1px solid #3cceff55;}
.queue-card{background:#16213e;border:1px solid #3cceff22;border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:0.8rem;}
.queue-card:hover{border-color:#3cceff55;}
.subject{font-weight:600;color:#e0e0e0;font-size:0.95rem;}
.meta{font-size:0.78rem;color:#666;font-family:'DM Mono',monospace;}
.code-block{background:#0f0f1a;border:1px solid #3cceff33;border-radius:6px;padding:0.5rem 0.8rem;font-family:'DM Mono',monospace;font-size:0.85rem;color:#3cceff;white-space:nowrap;}
.ai-verdict{padding:0.6rem 0.9rem;border-radius:6px;font-size:0.82rem;line-height:1.5;}
.verdict-found{background:#0d2d1a;border-left:3px solid #2ecc71;color:#b0f0c8;}
.verdict-notfound{background:#2d1010;border-left:3px solid #f35e40;color:#f0b0a0;}
.verdict-ambiguous{background:#2d2010;border-left:3px solid #f0a500;color:#f0d8a0;}
.resolution-tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-family:'DM Mono',monospace;}
.res-auto{background:#0d2d1a;color:#2ecc71;border:1px solid #2ecc7133;}
.res-existed{background:#0d1a2d;color:#3cceff;border:1px solid #3cceff33;}
.res-manual{background:#2d2010;color:#f0a500;border:1px solid #f0a50033;}
.res-notfound{background:#2d1010;color:#f35e40;border:1px solid #f35e4033;}
.badge-ignored{background:#1a1a2e;color:#555;border:1px solid #55555533;}
.poll-box{background:#16213e;border:1px solid #3cceff33;border-radius:10px;padding:1rem 1.4rem;margin-bottom:1.5rem;}
@keyframes fadeSlide{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
.queue-card{animation:fadeSlide 0.25s ease both;}
button[kind="primary"]{background:#f35e40!important;border:none!important;}
hr{border-color:#3cceff22!important;}
.stTabs [data-baseweb="tab-list"]{gap:4px;background:#16213e;border-radius:8px;padding:4px;}
.stTabs [data-baseweb="tab"]{border-radius:6px;padding:6px 16px;color:#888;}
.stTabs [aria-selected="true"]{background:#3cceff22!important;color:#3cceff!important;}
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_queue(): return SheetsQueue()
@st.cache_resource
def get_sender(): return GmailSender()
@st.cache_resource
def get_reader(): return GmailReader()

queue  = get_queue()
sender = get_sender()
reader = get_reader()

@st.cache_data(ttl=30)
def load_items(): return queue.get_all_items()

items_all = load_items()
n_queue  = len([i for i in items_all if i.get("status") in ("pending","flagged")])
n_ignored = len([i for i in items_all if i.get("status") == "ignored"])
n_sent   = len([i for i in items_all if i.get("status") == "sent"])
n_total  = len(items_all)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("dkm_logo.png", width=140)
    st.markdown("---")
    st.markdown(f"""
    <div class="metric-card" style="--accent:#f0a500">
        <div class="label">In queue</div><div class="value">{n_queue}</div>
    </div>
    <div class="metric-card" style="--accent:#2ecc71">
        <div class="label">Sent</div><div class="value">{n_sent}</div>
    </div>
    <div class="metric-card" style="--accent:#3cceff">
        <div class="label">Total</div><div class="value">{n_total}</div>
    </div>
    <div class="metric-card" style="--accent:#555">
        <div class="label">Ignored</div><div class="value">{n_ignored}</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    auto_refresh = st.toggle("Auto-refresh (600s)", value=False)
    st.markdown("---")
    st.markdown("**⚙️ Settings**")
    learn_setting = st.toggle("Remember confirmed codes", value=True, key="learn_toggle",
        help="When enabled, confirmed codes are saved to LearnedCodes sheet after Approve & Send")
    st.session_state["learn_codes"] = learn_setting
    st.markdown("---")
    st.markdown("<span style='color:#3cceff;font-size:0.75rem;font-family:monospace'>Commodity Checker v1.0</span>", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""<h1 style="font-family:'DM Mono',monospace;font-size:1.6rem;font-weight:500;color:#3cceff;margin-bottom:1.5rem;">DKM <span style="color:#f35e40">·</span> Commodity Checker</h1>""", unsafe_allow_html=True)

# ── Poll sectie ───────────────────────────────────────────────────────────────
c1, c2 = st.columns([3,1])
with c1:
    st.markdown("#### 📬 Fetch new emails")
    st.markdown("<span style='color:#888;font-size:0.82rem'>Picks up unread emails with label <b>CommodityCheckAI</b></span>", unsafe_allow_html=True)
with c2:
    check_btn = st.button("📥 Check Gmail now", type="primary", use_container_width=True)
st.markdown("---")

if check_btn:
    with st.spinner("Checking Gmail…"):
        try:
            new_messages = reader.fetch_new_messages()
            if not new_messages:
                st.info("No new emails found with tag `#commoditycheckAI`.")
            else:
                # Laad learned codes als lookup dict {proposed_or_confirmed_code: info}
                try:
                    learned_dict = queue.get_learned_lookup()
                    if learned_dict:
                        print(f"[Dashboard] Loaded {len(learned_dict)} learned code entries for cache lookup")
                except Exception:
                    learned_dict = {}

                progress = st.progress(0, text="Validating…")
                added = 0
                for i, msg in enumerate(new_messages):
                    progress.progress((i+1)/len(new_messages), text=f"Processing: {msg['subject'][:50]}")
                    if queue.msg_id_exists(msg["msg_id"]):
                        print(f"[Dashboard] Skip duplicate: {msg['msg_id'][:50]}")
                        continue
                    try:
                        result = validate(msg["body"], msg["subject"], learned_codes=learned_dict)
                    except Exception as e:
                        result = {"commodity_code":"ERROR","confirmed_code":"","code_found":"false",
                                  "ai_verdict":f"Validatie mislukt: {e}",
                                  "suggested_reply":"Automatic validation failed. A specialist will follow up.",
                                  "resolution_type":"error"}
                    status = "flagged" if result["code_found"] == "false" else "pending"
                    # Als from cache: direct op pending zetten met label
                    if result.get("from_cache"):
                        status = "pending"
                        print(f"[Dashboard] Cache hit — skipping Claude for {result.get('commodity_code')}")
                    queue.add_item({**msg, **result, "status": status})
                    added += 1
                progress.empty()
                if added > 0:
                    st.success(f"✅ {added} new email(s) processed!")
                    st.cache_data.clear(); time.sleep(1); st.rerun()
                else:
                    st.info("Emails already processed.")
        except Exception as e:
            st.error(f"Error: {e}")

# ── Render functie ────────────────────────────────────────────────────────────
def render_items(items, allow_actions=True):
    if not items:
        st.info("No items.")
        return

    for item in items:
        row_id      = item.get("row_id")
        status      = item.get("status","pending")
        subject     = item.get("subject","(geen subject)")
        sender_mail = item.get("sender_email","")
        received_at = item.get("received_at","")
        code_asked  = item.get("commodity_code","")
        ai_result   = item.get("ai_verdict","")
        ai_found    = str(item.get("code_found","")).lower()
        reply_body  = item.get("suggested_reply","")
        resolution  = item.get("resolution_type","")

        badge_map = {"pending":("badge-pending","⏳ Pending"),"flagged":("badge-flagged","🚩 Flagged"),"sent":("badge-sent","📤 Sent"),"ignored":("badge-ignored","🙈 Ignored")}
        badge_cls, badge_lbl = badge_map.get(status, ("badge-pending", status))
        v_cls = "verdict-found" if ai_found=="true" else ("verdict-ambiguous" if ai_found=="ambiguous" else "verdict-notfound")

        from_cache  = str(item.get("from_cache","")).lower() == "true"
        res_map = {"auto_resolved":('<span class="resolution-tag res-auto">' + ('⚡ Cached' if from_cache else '🤖 Auto resolved') + '</span>'),
                   "existed":'<span class="resolution-tag res-existed">✅ Code existed</span>',
                   "not_found":'<span class="resolution-tag res-notfound">❌ Not found</span>',
                   "manual":'<span class="resolution-tag res-manual">✏️ Manually added</span>'}
        res_html = res_map.get(resolution, "")

        # Confirmed code
        confirmed_code = str(item.get("confirmed_code","")).strip()
        if not confirmed_code and str(item.get("manual_code","")).strip():
            confirmed_code = str(item.get("manual_code","")).strip()
        if not confirmed_code and ai_found == "true":
            confirmed_code = code_asked
        if not confirmed_code and ai_result:
            codes_in_text = _re.findall(r"\b\d{10}\b", ai_result)
            for c in codes_in_text:
                if c != code_asked:
                    confirmed_code = c; break
            if not confirmed_code and codes_in_text:
                confirmed_code = codes_in_text[0]
        if not confirmed_code and resolution not in ("not_found","","error"):
            confirmed_code = code_asked

        if confirmed_code:
            confirmed_html = f'<div class="code-block" style="border-color:#2ecc7155;color:#2ecc71;">✅ <strong>{confirmed_code}</strong></div>'
        else:
            confirmed_html = '<div class="code-block" style="border-color:#f35e4055;color:#f35e40;">❓ Niet bevestigd</div>'

        # Extraheer alle 10-cijferige codes uit de reply bullets
        code_asked_str = str(code_asked).strip() if code_asked else ""
        # Haal alle confirmed codes uit reply (bullet lines: • 1234567890 — ...)
        all_confirmed = _re.findall(r"[•\-]\s*(\d{10})\s+[\u2014\-]", str(reply_body)) if reply_body else []
        if not all_confirmed:
            # Fallback: alle 10-cijferige codes in reply
            all_confirmed = _re.findall(r"\b(\d{10})\b", str(reply_body)) if reply_body else []
        if not all_confirmed and confirmed_code:
            all_confirmed = [confirmed_code]

        # Proposed codes (enkel primaire code beschikbaar)
        proposed_codes = [code_asked_str] if code_asked_str else []

        # Bouw HTML rijen
        code_rows_parts = []
        max_len = max(len(proposed_codes), len(all_confirmed), 1)
        for idx in range(max_len):
            prop = proposed_codes[idx] if idx < len(proposed_codes) else proposed_codes[0] if proposed_codes else ""
            conf = all_confirmed[idx] if idx < len(all_confirmed) else ""
            conf_style = "border-color:#2ecc7155;color:#2ecc71;" if conf else "border-color:#f35e4055;color:#f35e40;"
            conf_icon  = "✅" if conf else "❓"
            conf_text  = conf if conf else "Not confirmed"
            code_rows_parts.append(
                f'<div style="display:flex;gap:0.8rem;margin-top:0.4rem;align-items:center;">' +
                f'<div class="code-block" style="min-width:160px;">📦 <strong>{prop}</strong></div>' +
                f'<div class="code-block" style="{conf_style}min-width:160px;">{conf_icon} <strong>{conf_text}</strong></div>' +
                f'</div>'
            )
        res_div = f'<div style="margin-top:6px;">{res_html}</div>' if res_html else ""
        code_rows_html = "\n".join(code_rows_parts) + res_div

        st.markdown(f"""
        <div class="queue-card">
            <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
                <div class="subject" style="flex:2;min-width:180px;">{subject}</div>
                <div class="meta" style="flex:1;min-width:120px;">✉️ {sender_mail}</div>
                <div class="meta" style="flex:0 0 auto;white-space:nowrap;">🕐 {received_at}</div>
                <span class="badge {badge_cls}" style="flex:0 0 auto;">{badge_lbl}</span>
            </div>
            {code_rows_html}
            <div class="ai-verdict {v_cls}" style="margin-top:0.8rem;">
                <strong>AI:</strong> {ai_result}
            </div>
        </div>
        """, unsafe_allow_html=True)

        if allow_actions and status in ("pending","flagged"):
            with st.expander("✏️ Review, manual code & reply", expanded=False):
                if ai_found in ("false",""):
                    st.markdown("**🔎 Code not found — add manually:**")
                    mc1, mc2 = st.columns([1,2])
                    with mc1:
                        manual_code = st.text_input("GN Code", key=f"mcode_{row_id}", placeholder="e.g. 3926909700")
                    with mc2:
                        manual_desc = st.text_input("Description", key=f"mdesc_{row_id}", placeholder="e.g. Articles of plastics")
                    if st.button("💾 Save", key=f"msave_{row_id}"):
                        if manual_code:
                            queue.add_manual_code(manual_code, manual_desc)
                            queue.update_status(row_id, status, resolution_type="manual", manual_code=manual_code, manual_desc=manual_desc)
                            st.success(f"Code {manual_code} saved!")
                            st.cache_data.clear(); st.rerun()
                        else:
                            st.warning("Please enter a GN code.")
                    st.markdown("---")

                edited_reply = st.text_area("Reply", value=reply_body, height=180, key=f"reply_{row_id}")
                # ── Confirmatiescherm ──────────────────────────────────────
                confirm_key = f"confirm_{row_id}"
                if st.session_state.get(confirm_key):
                    st.warning("⚠️ Are you sure you want to send this reply?")
                    cc1, cc2 = st.columns([1,1])
                    with cc1:
                        if st.button("✅ Yes, send it", key=f"confirm_yes_{row_id}", type="primary"):
                            with st.spinner("Sending…"):
                                ok = sender.send_reply(to=sender_mail, subject=f"Re: {subject}", body=edited_reply)
                                if ok:
                                    res_type = "auto_resolved" if ai_found=="true" else ("manual" if ai_found=="false" else "existed")
                                    queue.update_status(row_id, "sent", reply_sent=edited_reply, resolution_type=res_type)
                                    # Leer de code als setting aan staat
                                    learn = st.session_state.get("learn_codes", True)
                                    if learn and res_type in ("auto_resolved","existed"):
                                        prop = code_asked  # originele voorgestelde code
                                        conf = confirmed_code if confirmed_code else code_asked
                                        queue.learn_code(
                                            proposed_code=prop,
                                            confirmed_code=conf,
                                            subject=subject,
                                        )
                                        st.success(f"✅ Sent! {prop} → {conf} saved to LearnedCodes.")
                                    else:
                                        st.success("✅ Sent!")
                                    st.session_state.pop(confirm_key, None)
                                    st.cache_data.clear(); time.sleep(1); st.rerun()
                                else:
                                    st.error("❌ Failed to send.")
                    with cc2:
                        if st.button("✖ Cancel", key=f"confirm_no_{row_id}"):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                else:
                    c1, c2, c3 = st.columns([2, 1, 1])
                    with c1:
                        if st.button("📤 Approve & Send", key=f"send_{row_id}", type="primary"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                    with c2:
                        if st.button("🚩 Flag", key=f"flag_{row_id}"):
                            queue.update_status(row_id, "flagged")
                            st.cache_data.clear(); time.sleep(0.5); st.rerun()
                    with c3:
                        if st.button("🙈 Ignore", key=f"ignore_{row_id}"):
                            queue.update_status(row_id, "ignored")
                            st.cache_data.clear(); time.sleep(0.5); st.rerun()
        st.markdown("")

# ── Tabs ──────────────────────────────────────────────────────────────────────
items_all = load_items()
queue_items  = [i for i in items_all if i.get("status") in ("pending","flagged")]
sent_items   = [i for i in items_all if i.get("status") == "sent"]

tab_queue, tab_sent, tab_all = st.tabs([
    f"📋 Queue  ({len(queue_items)})",
    f"📤 Sent  ({len(sent_items)})",
    f"🗂️ All  ({len(items_all)})",
])

with tab_queue:
    render_items(queue_items, allow_actions=True)

with tab_sent:
    render_items(sent_items, allow_actions=False)

with tab_all:
    render_items(items_all, allow_actions=False)

if auto_refresh:
    time.sleep(600); st.rerun()
