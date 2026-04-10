"""
code_validator.py
Valideert commodity codes tegen de DKM TARIC CSV via Claude AI.
"""

import os
import re
import anthropic
import pandas as pd

CLAUDE_MODEL = "claude-opus-4-5"


def _load_commodities() -> pd.DataFrame:
    """Laad taric_clean.csv — UTF-8, puntkomma-separator."""
    csv_path = os.environ.get("COMMODITIES_CSV_PATH", "taric_clean.csv")
    print(f"[Validator] Laden van: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str, sep=";", encoding="utf-8")
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.fillna("")
    print(f"[Validator] CSV geladen: {len(df)} rijen, kolommen: {list(df.columns)}")
    return df


def _search_code(code: str) -> dict:
    """
    Zoeklogica:
    1. Exacte match op volledige code → bevestigd
    2. Geen exacte match → zoek op eerste 8 digits → stel alternatieven voor
    3. Niets gevonden → not found
    """
    df = _load_commodities()
    code_clean = re.sub(r"\D", "", code).strip()
    if not code_clean:
        return {"found": False, "exact": False, "suggested": "", "duty_rate": "", "alternatives": []}

    code_col = "gn_code"
    duty_col = "douanerecht" if "douanerecht" in df.columns else None
    db_codes = df[code_col].fillna("").str.replace(r"\D", "", regex=True)

    # Stap 1: exacte match
    exact_hits = df[db_codes == code_clean]
    if not exact_hits.empty:
        duty = str(exact_hits.iloc[0][duty_col]).strip() if duty_col else ""
        print(f"[Validator] {code_clean} → EXACT MATCH, duty={duty}")
        return {"found": True, "exact": True, "suggested": code_clean, "duty_rate": duty, "alternatives": []}

    # Stap 2: eerste 8 digits
    prefix8 = code_clean[:8]
    alt_hits = df[db_codes.str.startswith(prefix8)]
    if not alt_hits.empty:
        seen = set()
        alternatives = []
        for _, row in alt_hits.iterrows():
            c = str(row[code_col]).strip()
            if c not in seen:
                seen.add(c)
                alternatives.append({"code": c, "duty_rate": str(row[duty_col]).strip() if duty_col else ""})
        # Meest logische = hoogste suffix
        alternatives_sorted = sorted(alternatives, key=lambda x: x["code"], reverse=True)
        suggested = alternatives_sorted[0]["code"]
        duty = alternatives_sorted[0]["duty_rate"]
        print(f"[Validator] {code_clean} → niet gevonden, suggestie: {suggested}, alternatieven: {[a['code'] for a in alternatives]}")
        return {"found": True, "exact": False, "suggested": suggested, "duty_rate": duty, "alternatives": [a["code"] for a in alternatives]}

    print(f"[Validator] {code_clean} → NIET GEVONDEN")
    return {"found": False, "exact": False, "suggested": "", "duty_rate": "", "alternatives": []}


def validate(email_body: str, email_subject: str, learned_codes: dict = None) -> dict:
    """
    Hoofdfunctie. Extraheert codes uit email, valideert ze, schrijft reply.
    learned_codes: dict van {gn_code: {confirmed_by, times_seen, ...}} voor cache lookup.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Stap 1: extraheer alle codes uit de email
    extract_resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=128,
        messages=[{"role": "user", "content": f"""
Extract ALL commodity/GN/HS codes mentioned in this email.
Return ONLY the numeric codes, comma-separated (e.g. "3926909790,3926909799").
Include both proposed codes AND alternative codes mentioned.
If no code found, return "UNKNOWN".

Subject: {email_subject}
Body: {email_body[:2000]}
"""}],
    )
    raw_codes = extract_resp.content[0].text.strip()
    all_codes = [re.sub(r"\D", "", c).strip() for c in raw_codes.split(",") if re.sub(r"\D", "", c).strip()]
    if not all_codes or all_codes == ["UNKNOWN"]:
        all_codes = ["UNKNOWN"]
    primary_code = all_codes[0]
    print(f"[Validator] Codes gevonden in email: {all_codes}")

    # Stap 2: valideer elke code
    results = {code: _search_code(code) for code in all_codes if code != "UNKNOWN"}

    # Stap 3: bouw zoekresultaat samenvatting
    search_summary = ""
    for code, r in results.items():
        if r["exact"]:
            search_summary += f"- Code {code}: EXACT MATCH ✓ | Duty: {r['duty_rate']}\n"
        elif r["found"]:
            alts = ", ".join(r["alternatives"])
            search_summary += f"- Code {code}: NIET GEVONDEN. Suggestie op basis van {code[:8]}xx: {r['suggested']} (duty: {r['duty_rate']}). Alle alternatieven: {alts}\n"
        else:
            search_summary += f"- Code {code}: NIET GEVONDEN in database\n"

    # Stap 4: Claude schrijft analyse + reply
    verdict_resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": f"""
You are a customs expert at DKM Customs (Antwerp).
Declarants ask you to verify commodity codes. They propose a code — you confirm or correct it.

Email subject: {email_subject}
Email body: {email_body[:1500]}

Database results:
{search_summary}

Instructions:
1. Internal analysis (max 2 sentences). End with RESOLUTION_TYPE: auto_resolved|existed|not_found
   - auto_resolved = exact match found
   - existed = no exact match but alternative suggested
   - not_found = nothing found at all

2. Short professional reply using EXACTLY this structure:

Dear Team Member,

I checked your question and below I provide you with my findings.

[For each code in the email, one bullet per code:]
• [confirmed/suggested code]  —  [Confirmed / Suggested, code existed / Not found]  —  [short goods description, max 10 words]  —  Third country tariff: [duty rate]

[Only if not found:] A DKM specialist will follow up for this item.

---
AI Analysis: [copy your internal analysis here, exactly as written above]

Kind regards,
DKM Customs — Commodity Validation Service

Rules:
- NO website links
- Use the confirmed or suggested code as the code in the bullet, NOT the wrong proposed code
- Description: brief goods description based on HS chapter knowledge (e.g. "Articles of plastics, nes")
- If multiple codes in email, list each on a separate bullet
- Keep it short and scannable
- Always include the AI Analysis line at the bottom

Return format:
ANALYSIS: <max 2 sentences ending with RESOLUTION_TYPE: ...>
REPLY:
<reply text>
"""}],
    )

    raw = verdict_resp.content[0].text.strip()
    analysis = ""
    reply_body = ""
    if "ANALYSIS:" in raw and "REPLY:" in raw:
        analysis   = raw.split("ANALYSIS:")[1].split("REPLY:")[0].strip()
        reply_body = raw.split("REPLY:")[1].strip()
    else:
        analysis   = raw[:300]
        reply_body = raw

    # Bepaal code_found en resolution_type
    primary_result = results.get(primary_code, {"found": False, "exact": False})
    if primary_result["exact"]:
        code_found      = "true"
        resolution_type = "auto_resolved"
    elif primary_result["found"]:
        code_found      = "ambiguous"
        resolution_type = "existed"
    else:
        # Check of een andere code in de email wel gevonden werd
        any_found = any(r["found"] for r in results.values())
        code_found      = "ambiguous" if any_found else "false"
        resolution_type = "existed"   if any_found else "not_found"

    # Bepaal de bevestigde code
    primary_result = results.get(primary_code, {})
    if primary_result.get("exact"):
        confirmed_code = primary_code
    elif primary_result.get("found"):
        confirmed_code = primary_result.get("suggested", "")
    else:
        # Zoek of een andere code in de email wel exact gevonden werd
        confirmed_code = ""
        for code, r in results.items():
            if r.get("exact"):
                confirmed_code = code
                break
            elif r.get("found") and not confirmed_code:
                confirmed_code = r.get("suggested", "")

    return {
        "commodity_code":  primary_code,
        "confirmed_code":  confirmed_code,
        "code_found":      code_found,
        "ai_verdict":      analysis,
        "suggested_reply": reply_body,
        "resolution_type": resolution_type,
    }
