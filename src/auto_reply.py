"""Auto-reply naar de forward-afzender bij onvolledige orders.

Triggers (zie ``diagnose_order``):
  - parse_failed  — parser gaf een exception of ongeldige JSON
  - no_lines      — parser lukte, maar er zijn 0 regels (forward zonder PDF)
  - customer_unknown — geen klant-match of fuzzy-score < 0.9
  - items_unmatched  — specifieke regels zonder item-match (met top-3 suggesties
                       via fuzzy op item-beschrijving/-code)

Max één reply per order (``incoming_orders.auto_reply_sent_at``). Reset bij
reingest. SMTP-credentials via ``SMTP_HOST/PORT/USER/PASS/FROM``; als die
ontbreken wordt er gelogd maar niet verstuurd.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

CUSTOMER_CONFIDENCE_THRESHOLD = 0.9
SUGGESTION_TOP_K = 3
SUGGESTION_MIN_SCORE = 60  # onder deze fuzzy-score tonen we geen suggesties


@dataclass
class ItemSuggestion:
    code: str | None
    description: str | None
    score: float


@dataclass
class UnmatchedLine:
    description: str
    quantity: Any
    item_code_in_mail: str | None
    suggestions: list[ItemSuggestion] = field(default_factory=list)


@dataclass
class Diagnosis:
    parse_failed: bool = False
    parse_error: str | None = None
    no_lines: bool = False
    customer_unknown: bool = False
    customer_best_guess: str | None = None
    customer_confidence: float | None = None
    items_unmatched: list[UnmatchedLine] = field(default_factory=list)

    @property
    def has_problems(self) -> bool:
        return (
            self.parse_failed
            or self.no_lines
            or self.customer_unknown
            or bool(self.items_unmatched)
        )


def _fetch_items(sb) -> list[dict]:
    """Alle items uit Supabase, paginerend (Supabase default limit = 1000)."""
    from matcher import _fetch_paginated

    return _fetch_paginated(
        sb, "exact_items", "id,code,description,description_normalized,unit"
    )


def gather_item_suggestions(
    sb, line: dict, top_k: int = SUGGESTION_TOP_K, items_cache: list[dict] | None = None
) -> list[ItemSuggestion]:
    """Top-K kandidaat-items voor een niet-gematchte regel.

    Matcht op de description van de regel tegen alle items; als de regel
    een ``item_code`` heeft, wordt die ook als losse fuzzy-kandidaat meegepakt
    (handig als de klant een typo heeft in de EW-code).
    """
    from catalog_sync import normalize_name

    items = items_cache if items_cache is not None else _fetch_items(sb)
    if not items:
        return []

    description = (line.get("description") or "").strip()
    desc_norm = normalize_name(description)

    scores: dict[str, float] = {}  # item_id -> beste score
    if desc_norm:
        for it in items:
            target = it.get("description_normalized") or ""
            if not target:
                continue
            s = fuzz.token_set_ratio(desc_norm, target)
            if s >= SUGGESTION_MIN_SCORE:
                scores[it["id"]] = max(scores.get(it["id"], 0.0), float(s))

    code_in_mail = (line.get("item_code") or "").strip().upper()
    if code_in_mail:
        for it in items:
            it_code = (it.get("code") or "").strip().upper()
            if not it_code:
                continue
            s = fuzz.ratio(code_in_mail, it_code)
            if s >= 75:
                scores[it["id"]] = max(scores.get(it["id"], 0.0), float(s))

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    by_id = {it["id"]: it for it in items}
    return [
        ItemSuggestion(
            code=by_id[item_id].get("code"),
            description=by_id[item_id].get("description"),
            score=round(score / 100, 3),
        )
        for item_id, score in ranked
    ]


def diagnose_order(row: dict, sb=None) -> Diagnosis:
    """Bepaal of en waarom een order niet door kan naar Exact.

    Retourneert een Diagnosis; roep ``diagnosis.has_problems`` aan om te
    checken of er een reply verstuurd moet worden.
    """
    d = Diagnosis()
    status = row.get("parse_status")
    parsed = row.get("parsed_data") or {}

    # 1. Parser crashte of ongeldige JSON.
    if status == "failed" or (row.get("error") and not parsed):
        d.parse_failed = True
        d.parse_error = row.get("error")
        return d

    lines = parsed.get("lines") or []
    if not lines:
        d.no_lines = True
        # Bij 0 regels heeft item-matching geen zin; klant kunnen we wel checken.

    # 2. Klant onbekend of laag vertrouwen.
    mc = parsed.get("matched_customer") or {}
    conf = float(mc.get("confidence") or 0.0) if mc else 0.0
    if not mc or not mc.get("id") or conf < CUSTOMER_CONFIDENCE_THRESHOLD:
        d.customer_unknown = True
        d.customer_best_guess = mc.get("name") if mc else None
        d.customer_confidence = conf if mc else None

    # 3. Regels zonder item-match. Verzamel suggesties in batch.
    matched_items = parsed.get("matched_items") or []
    items_cache: list[dict] | None = None
    for m in matched_items:
        if m.get("item_id"):
            continue
        line = m.get("line") or {}
        if sb is not None and items_cache is None:
            items_cache = _fetch_items(sb)
        suggestions = (
            gather_item_suggestions(sb, line, items_cache=items_cache)
            if sb is not None
            else []
        )
        d.items_unmatched.append(
            UnmatchedLine(
                description=line.get("description") or "(geen omschrijving)",
                quantity=line.get("quantity"),
                item_code_in_mail=line.get("item_code"),
                suggestions=suggestions,
            )
        )

    return d


def build_reply(row: dict, diagnosis: Diagnosis) -> tuple[str, str]:
    """Bouw subject + plain-text body in het Nederlands."""
    original_subject = row.get("subject") or "je bestelling"
    # Behoud 'Re:'-prefix conventie.
    subj = original_subject.strip()
    if not subj.lower().startswith("re:"):
        subj = f"Re: {subj}"

    lines: list[str] = []
    lines.append("Hoi Patrick,")
    lines.append("")
    lines.append(
        "Ik kon deze order niet automatisch verwerken. Kun je het volgende aanvullen?"
    )
    lines.append("")

    if diagnosis.parse_failed:
        lines.append("- De inhoud van de mail/PDF was niet leesbaar voor het systeem.")
        if diagnosis.parse_error:
            short = diagnosis.parse_error.splitlines()[0][:200]
            lines.append(f"  (technische melding: {short})")
        lines.append(
            "  Kun je de bestelling opnieuw doorsturen, bij voorkeur met een goede PDF-bijlage?"
        )
        lines.append("")

    if diagnosis.no_lines and not diagnosis.parse_failed:
        lines.append(
            "- Er staan geen bestelregels in de mail of in een leesbare bijlage."
        )
        lines.append(
            "  Stuur je de originele bestel-PDF alsnog mee? Forwards slaan bijlagen soms over."
        )
        lines.append("")

    if diagnosis.customer_unknown:
        parsed = row.get("parsed_data") or {}
        cust_name = parsed.get("customer_name") or "(onbekend)"
        if diagnosis.customer_best_guess:
            conf_pct = int((diagnosis.customer_confidence or 0) * 100)
            lines.append(
                f"- Klant in de mail: \"{cust_name}\". Beste gok in Exact: "
                f"\"{diagnosis.customer_best_guess}\" (vertrouwen {conf_pct}%). "
                "Is dat de juiste klant, of welke dan wel?"
            )
        else:
            lines.append(
                f"- Klant in de mail: \"{cust_name}\". Ik vind geen match in Exact. "
                "Welke klant is dit?"
            )
        lines.append("")

    if diagnosis.items_unmatched:
        lines.append("- De volgende regels konden niet aan een Exact-artikel gekoppeld worden:")
        for ul in diagnosis.items_unmatched:
            qty = ul.quantity if ul.quantity is not None else "?"
            code_note = f" (code in bestelling: {ul.item_code_in_mail})" if ul.item_code_in_mail else ""
            lines.append(f"  • {qty}× {ul.description}{code_note}")
            if ul.suggestions:
                lines.append("    Mogelijke treffers:")
                for s in ul.suggestions:
                    code = s.code or "—"
                    desc = s.description or "—"
                    pct = int(s.score * 100)
                    lines.append(f"      - {code}: {desc}  (gelijkenis {pct}%)")
            else:
                lines.append("    (geen goede suggesties gevonden)")
        lines.append("")
        lines.append(
            "  Kun je per regel aangeven welke Earth Water-code erbij hoort?"
        )
        lines.append("")

    lines.append(
        "Zodra je reageert pak ik de order direct opnieuw op."
    )
    lines.append("")
    lines.append("— Earth Water orderverwerking (automatisch)")

    return subj, "\n".join(lines)


def _smtp_config() -> dict | None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM", user)
    if not (host and user and password and sender):
        return None
    return {"host": host, "port": port, "user": user, "password": password, "from": sender}


def _send_via_smtp(msg: EmailMessage, config: dict) -> None:
    ctx = ssl.create_default_context()
    with smtplib.SMTP(config["host"], config["port"], timeout=20) as s:
        s.starttls(context=ctx)
        s.login(config["user"], config["password"])
        s.send_message(msg)


def send_auto_reply(
    row: dict, diagnosis: Diagnosis, *, smtp_sender=None
) -> bool:
    """Stuur de auto-reply. Retourneert True als daadwerkelijk verstuurd.

    ``smtp_sender`` is alleen bedoeld voor tests — geef een callable
    ``(msg: EmailMessage) -> None`` mee om de transport te mocken.
    """
    to_address = row.get("from_address")
    if not to_address:
        log.warning("Auto-reply overgeslagen: geen from_address op rij %s", row.get("id"))
        return False

    config = _smtp_config() if smtp_sender is None else {"from": os.getenv("SMTP_FROM") or "noreply@earthwater.nl"}
    if smtp_sender is None and config is None:
        log.warning(
            "Auto-reply NIET verstuurd (SMTP niet geconfigureerd) voor rij %s",
            row.get("id"),
        )
        return False

    subject, body = build_reply(row, diagnosis)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["from"]
    msg["To"] = to_address
    msg["Message-ID"] = make_msgid(domain="earthwater.nl")

    original_msg_id = row.get("message_id")
    if original_msg_id:
        # Zorg voor RFC 5322-conforme header-waarde met hoekhaken.
        ref = original_msg_id.strip()
        if not ref.startswith("<"):
            ref = f"<{ref}>"
        msg["In-Reply-To"] = ref
        msg["References"] = ref

    msg.set_content(body)

    try:
        if smtp_sender is not None:
            smtp_sender(msg)
        else:
            _send_via_smtp(msg, config)
    except Exception as e:
        log.error("Auto-reply versturen mislukt voor rij %s: %s", row.get("id"), e)
        return False

    log.info("Auto-reply verstuurd naar %s voor rij %s", to_address, row.get("id"))
    return True


def maybe_send_auto_reply(row: dict, sb, *, smtp_sender=None) -> dict:
    """Stuur een reply als dat nog niet is gebeurd en er problemen zijn.

    Update ``auto_reply_sent_at`` in Supabase bij succes. Retourneert
    een kleine stats-dict voor logging.
    """
    out = {"diagnosed": False, "skipped_already_sent": False, "sent": False, "problems": 0}

    if row.get("auto_reply_sent_at"):
        out["skipped_already_sent"] = True
        return out

    diagnosis = diagnose_order(row, sb=sb)
    out["diagnosed"] = True
    out["problems"] = (
        (1 if diagnosis.parse_failed else 0)
        + (1 if diagnosis.no_lines else 0)
        + (1 if diagnosis.customer_unknown else 0)
        + len(diagnosis.items_unmatched)
    )
    if not diagnosis.has_problems:
        return out

    sent = send_auto_reply(row, diagnosis, smtp_sender=smtp_sender)
    out["sent"] = sent
    if sent:
        try:
            sb.table("incoming_orders").update(
                {"auto_reply_sent_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", row.get("id")).execute()
        except Exception as e:
            log.error("Kon auto_reply_sent_at niet updaten voor %s: %s", row.get("id"), e)

    return out
