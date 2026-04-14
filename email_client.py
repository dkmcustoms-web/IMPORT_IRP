"""
DKM Import Release Dashboard — E-mail notificaties
Verstuurt een e-mail wanneer een MRN gevonden wordt.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
SMTP_USER     = "dkmcustoms@gmail.com"
SMTP_PASSWORD = "vhamzgxprgvgktve"
SMTP_FROM     = "dkmcustoms@gmail.com"
TO_EMAILS     = ["luc.dekerf@dkm-customs.com", "bjorn.vanacker@dkm-customs.com", "import@dkm-customs.com"]


def send_mrn_notification(
    dossier_id: str,
    container: str,
    bl: str,
    crn: str,
    mrn: str,
    status_tsd: str,
) -> bool:
    """
    Verstuur e-mail notificatie voor gevonden MRN.
    Geeft True terug bij succes, False bij fout.
    """
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    subject = f"🚢 MRN Gevonden — Container {container} | Dossier {dossier_id}"

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px;">
      <div style="max-width: 600px; margin: auto; background: white; border-radius: 8px; overflow: hidden;">

        <!-- Header -->
        <div style="background: #1E3A5F; padding: 20px 30px;">
          <h1 style="color: #3CCEFF; margin: 0; font-size: 22px;">🚢 DKM Import Dashboard</h1>
          <p style="color: #e0e0e0; margin: 5px 0 0 0; font-size: 14px;">MRN Notificatie</p>
        </div>

        <!-- Body -->
        <div style="padding: 30px;">
          <p style="color: #222; font-size: 16px;">
            Er werd een <strong style="color: #1E3A5F;">MRN gevonden</strong> voor onderstaand dossier:
          </p>

          <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr style="background: #f0f9ff;">
              <td style="padding: 10px 15px; font-weight: bold; color: #1E3A5F; width: 40%; border-bottom: 1px solid #ddd;">Dossier ID</td>
              <td style="padding: 10px 15px; color: #333; border-bottom: 1px solid #ddd;">{dossier_id}</td>
            </tr>
            <tr>
              <td style="padding: 10px 15px; font-weight: bold; color: #1E3A5F; border-bottom: 1px solid #ddd;">Container</td>
              <td style="padding: 10px 15px; color: #333; border-bottom: 1px solid #ddd;">{container}</td>
            </tr>
            <tr style="background: #f0f9ff;">
              <td style="padding: 10px 15px; font-weight: bold; color: #1E3A5F; border-bottom: 1px solid #ddd;">Bill of Lading</td>
              <td style="padding: 10px 15px; color: #333; border-bottom: 1px solid #ddd;">{bl}</td>
            </tr>
            <tr>
              <td style="padding: 10px 15px; font-weight: bold; color: #1E3A5F; border-bottom: 1px solid #ddd;">CRN</td>
              <td style="padding: 10px 15px; color: #333; border-bottom: 1px solid #ddd;">{crn}</td>
            </tr>
            <tr style="background: #e8f9e8;">
              <td style="padding: 12px 15px; font-weight: bold; color: #1E3A5F; border-bottom: 1px solid #ddd; font-size: 16px;">✅ MRN</td>
              <td style="padding: 12px 15px; color: #1a7a1a; font-weight: bold; font-size: 16px; border-bottom: 1px solid #ddd;">{mrn}</td>
            </tr>
            <tr>
              <td style="padding: 10px 15px; font-weight: bold; color: #1E3A5F;">Status TSD</td>
              <td style="padding: 10px 15px; color: #333;">{status_tsd}</td>
            </tr>
          </table>

          <p style="color: #666; font-size: 13px;">
            Gevonden op: {now}<br>
            Dit is een automatische notificatie van het DKM Import Release Dashboard.
          </p>
        </div>

        <!-- Footer -->
        <div style="background: #1E3A5F; padding: 15px 30px; text-align: center;">
          <p style="color: #3CCEFF; margin: 0; font-size: 12px;">
            DKM Customs • Import Release Dashboard • NxtPort IRP
          </p>
        </div>
      </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = ", ".join(TO_EMAILS)
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, TO_EMAILS, msg.as_string())

        log.info(f"MRN notificatie verstuurd voor {container} (MRN: {mrn}) naar {TO_EMAILS}")
        return True

    except Exception as e:
        log.error(f"Fout bij versturen e-mail voor {container}: {e}")
        return False
