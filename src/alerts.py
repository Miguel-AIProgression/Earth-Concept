"""Email-alerts voor kritieke syncfouten.

Stuurt een mail naar ALERT_EMAIL (default: miguel@aiprogression.nl) via SMTP.
SMTP-credentials komen uit env-vars; als die ontbreken wordt de alert
gelogd maar niet verstuurd (zodat lokale dev niet crasht).
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger(__name__)

ALERT_EMAIL = os.getenv("ALERT_EMAIL", "miguel@aiprogression.nl")


def send_alert(subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM", user)

    if not (host and user and password and sender):
        log.warning("SMTP niet geconfigureerd; alert NIET verstuurd: %s", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = f"[Earth Water sync] {subject}"
    msg["From"] = sender
    msg["To"] = ALERT_EMAIL
    msg.set_content(body)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)
        log.info("Alert verstuurd naar %s: %s", ALERT_EMAIL, subject)
        return True
    except Exception as e:
        log.error("Alert versturen mislukt: %s", e)
        return False
