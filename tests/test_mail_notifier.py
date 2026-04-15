from __future__ import annotations

from email import message_from_string

from skills import mail_notifier


class _FakeSMTP:
    last_message: str = ""

    def __init__(self, host: str, port: int, timeout: int) -> None:  # noqa: ARG002
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged_in = False

    def ehlo(self) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, user: str, passwd: str) -> None:
        if not user or not passwd:
            raise OSError("missing credentials")
        self.logged_in = True

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:  # noqa: ARG002
        if not self.logged_in:
            raise OSError("not logged in")
        _FakeSMTP.last_message = msg

    def quit(self) -> None:
        return None


def test_send_digest_email_success(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("TARGET_EMAIL", "user@example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setattr(mail_notifier.smtplib, "SMTP", _FakeSMTP)

    ok = mail_notifier.send_digest_email(
        [
            {
                "index": 1,
                "title": "Test title",
                "category": "Policy",
                "summary": "Summary text",
                "url": "https://example.com/item",
            }
        ]
    )

    assert ok is True
    assert "InfoLoop Daily Digest" in _FakeSMTP.last_message
    message = message_from_string(_FakeSMTP.last_message)
    html_part = message.get_payload()[1]
    html_body = html_part.get_payload(decode=True).decode("utf-8")
    assert "[1] Test title" in html_body
    assert "https://example.com/item" in html_body


def test_send_digest_email_missing_config(monkeypatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASS", raising=False)
    monkeypatch.delenv("TARGET_EMAIL", raising=False)

    assert mail_notifier.send_digest_email([]) is False
