from __future__ import annotations

from pathlib import Path

import pytest

from skills import distribute_skill


class _FakeSMTP:
    def __init__(self, host: str, port: int, timeout: int) -> None:  # noqa: ARG002
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged_in = False
        self.sent = False

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
        self.sent = True

    def quit(self) -> None:
        return None


def test_send_email_alert_success(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    monkeypatch.setattr(distribute_skill.smtplib, "SMTP", _FakeSMTP)

    ok = distribute_skill.send_email_alert(
        recipient="user@example.com",
        subject="test",
        content="hello",
    )
    assert ok is True


def test_send_email_alert_missing_config(monkeypatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASS", raising=False)
    assert distribute_skill.send_email_alert("u@example.com", "s", "c") is False


def test_publish_to_wechat_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WECHAT_APP_ID", "app_id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "app_secret")

    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"img")

    monkeypatch.setattr(distribute_skill, "_get_wechat_access_token", lambda a, b: "token123")  # noqa: ARG005
    monkeypatch.setattr(distribute_skill, "_upload_temp_image", lambda token, path: "media001")  # noqa: ARG005
    monkeypatch.setattr(distribute_skill, "_create_draft", lambda token, title, content, media: "draft001")  # noqa: ARG005
    monkeypatch.setattr(distribute_skill, "_submit_publish", lambda token, media: "publish001")  # noqa: ARG005

    result = distribute_skill.publish_to_wechat(
        title="demo",
        content="content",
        cover_image_path=str(cover),
    )
    assert result["status"] == "submitted"
    assert result["draft_media_id"] == "draft001"
    assert result["publish_id"] == "publish001"


def test_publish_to_wechat_missing_config(monkeypatch) -> None:
    monkeypatch.delenv("WECHAT_APP_ID", raising=False)
    monkeypatch.delenv("WECHAT_APP_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        distribute_skill.publish_to_wechat("title", "content", "missing.jpg")

