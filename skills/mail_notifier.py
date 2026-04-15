"""InfoLoop mail notifier skill.

This module sends indexed HTML digest emails through SMTP so users can reference
items like [1], [2], [3] directly in OpenClaw chat.
"""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any, Dict, List, Optional, Sequence

from dotenv import load_dotenv


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable.

    Args:
        name: Environment variable key.
        default: Default boolean value.

    Returns:
        bool: Parsed boolean result.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _safe_int(value: str, default: int) -> int:
    """Convert string to int with fallback.

    Args:
        value: Raw integer-like string.
        default: Default integer when conversion fails.

    Returns:
        int: Parsed integer or fallback value.
    """
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return default


def _normalize_items(summarized_json: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Normalize summary records into display-friendly string fields.

    Args:
        summarized_json: Raw summary records.

    Returns:
        List[Dict[str, str]]: Normalized list for HTML/text rendering.
    """
    normalized: List[Dict[str, str]] = []
    for idx, item in enumerate(summarized_json, start=1):
        record_index = str(item.get("index", idx))
        title = str(item.get("title", "Untitled")).strip() or "Untitled"
        category = str(item.get("category", "Uncategorized")).strip() or "Uncategorized"
        summary = str(item.get("summary", "")).strip() or "No summary available."
        url = str(item.get("url", "")).strip()
        normalized.append(
            {
                "index": record_index,
                "title": title,
                "category": category,
                "summary": summary,
                "url": url,
            }
        )
    return normalized


def _build_plain_text(items: Sequence[Dict[str, str]]) -> str:
    """Build plain-text email body as client fallback.

    Args:
        items: Normalized digest records.

    Returns:
        str: Plain-text digest body.
    """
    if not items:
        return "InfoLoop digest is empty today."

    lines = ["InfoLoop Digest", ""]
    for item in items:
        lines.append(f"[{item['index']}] {item['title']}")
        lines.append(f"Category: {item['category']}")
        lines.append(f"Summary: {item['summary']}")
        if item["url"]:
            lines.append(f"Source: {item['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _build_html_body(items: Sequence[Dict[str, str]]) -> str:
    """Build HTML digest body.

    Args:
        items: Normalized digest records.

    Returns:
        str: HTML email body.
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards: List[str] = []
    for item in items:
        source_html = ""
        if item["url"]:
            safe_url = escape(item["url"])
            source_html = (
                f'<p style="margin:8px 0 0;color:#334155;font-size:13px;">'
                f'Source: <a href="{safe_url}" style="color:#0f4c81;text-decoration:none;">'
                f"{safe_url}</a></p>"
            )

        cards.append(
            "<li style=\"list-style:none;margin:0 0 14px;padding:16px;border:1px solid #d6e2ef;"
            "border-radius:10px;background:#ffffff;\">"
            f"<div style=\"font-size:15px;font-weight:700;color:#0f172a;\">"
            f"[{escape(item['index'])}] {escape(item['title'])}</div>"
            f"<div style=\"margin-top:6px;font-size:13px;color:#0f4c81;\">"
            f"Category: {escape(item['category'])}</div>"
            f"<p style=\"margin:10px 0 0;line-height:1.6;color:#1e293b;font-size:14px;\">"
            f"{escape(item['summary'])}</p>"
            f"{source_html}"
            "</li>"
        )

    if not cards:
        cards.append(
            "<li style=\"list-style:none;margin:0;padding:16px;border:1px dashed #cbd5e1;"
            "border-radius:10px;background:#ffffff;color:#475569;\">"
            "No candidates were found for this digest window."
            "</li>"
        )

    card_html = "\n".join(cards)
    return (
        "<html><body style=\"margin:0;padding:20px;background:#f1f5f9;font-family:Arial,sans-serif;\">"
        "<div style=\"max-width:760px;margin:0 auto;background:#ffffff;border-radius:12px;"
        "padding:20px;border:1px solid #dbe5f0;\">"
        "<h2 style=\"margin:0 0 6px;color:#0f172a;\">InfoLoop Daily Digest</h2>"
        "<p style=\"margin:0 0 16px;color:#475569;font-size:13px;\">"
        f"Generated at {escape(generated_at)}"
        "</p>"
        "<ul style=\"padding:0;margin:0;\">"
        f"{card_html}"
        "</ul>"
        "<p style=\"margin:16px 0 0;color:#64748b;font-size:12px;\">"
        "Reply in OpenClaw chat using indexed references such as [1], [2]."
        "</p>"
        "</div></body></html>"
    )


def _build_message(
    smtp_user: str,
    recipient: str,
    subject: str,
    plain_text: str,
    html_body: str,
    sender_name: str,
) -> MIMEMultipart:
    """Create an SMTP multipart message.

    Args:
        smtp_user: Sender email account.
        recipient: Receiver email address.
        subject: Email subject.
        plain_text: Plain-text body.
        html_body: HTML body.
        sender_name: Sender display name.

    Returns:
        MIMEMultipart: SMTP-ready message.
    """
    message = MIMEMultipart("alternative")
    message["From"] = str(Header(f"{sender_name} <{smtp_user}>", "utf-8"))
    message["To"] = str(Header(recipient, "utf-8"))
    message["Subject"] = str(Header(subject, "utf-8"))
    message.attach(MIMEText(plain_text, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    return message


def send_digest_email(summarized_json: List[Dict[str, Any]]) -> bool:
    """Send indexed HTML digest email through SMTP.

    Args:
        summarized_json: Structured article summary list.

    Returns:
        bool: True when email is sent successfully, otherwise False.
    """
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    target_email = os.getenv("TARGET_EMAIL", "").strip()

    smtp_port = _safe_int(os.getenv("SMTP_PORT", "587"), 587)
    smtp_use_tls = _env_bool("SMTP_USE_TLS", True)
    sender_name = os.getenv("SMTP_SENDER_NAME", "InfoLoop Bot").strip() or "InfoLoop Bot"
    subject = os.getenv("DIGEST_SUBJECT", "InfoLoop Daily Digest").strip() or "InfoLoop Daily Digest"

    missing_keys = [
        key
        for key, value in (
            ("SMTP_HOST", smtp_host),
            ("SMTP_USER", smtp_user),
            ("SMTP_PASS", smtp_pass),
            ("TARGET_EMAIL", target_email),
        )
        if not value
    ]
    if missing_keys:
        logger.error("SMTP configuration missing: %s", ", ".join(missing_keys))
        return False

    normalized_items = _normalize_items(summarized_json)
    plain_text = _build_plain_text(normalized_items)
    html_body = _build_html_body(normalized_items)
    message = _build_message(
        smtp_user=smtp_user,
        recipient=target_email,
        subject=subject,
        plain_text=plain_text,
        html_body=html_body,
        sender_name=sender_name,
    )

    server: Optional[smtplib.SMTP] = None
    try:
        server = smtplib.SMTP(host=smtp_host, port=smtp_port, timeout=25)
        server.ehlo()
        if smtp_use_tls:
            server.starttls()
            server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [target_email], message.as_string())
        logger.info(
            "Digest email sent successfully to %s with %s item(s).",
            target_email,
            len(normalized_items),
        )
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Failed to send digest email: %s", exc)
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except OSError:
                logger.debug("SMTP connection already closed.")


if __name__ == "__main__":
    sample_items = [
        {
            "index": 1,
            "title": "Open-source AI monitor update",
            "category": "Industry",
            "summary": "A brief update describing new model releases and deployment trends.",
            "url": "https://example.com/article-1",
        },
        {
            "index": 2,
            "title": "Regulatory changes in AI governance",
            "category": "Policy",
            "summary": "A concise view of new compliance requirements affecting content operations.",
            "url": "https://example.com/article-2",
        },
    ]
    result = send_digest_email(sample_items)
    print(f"Digest sent: {result}")
