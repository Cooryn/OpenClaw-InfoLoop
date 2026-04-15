from __future__ import annotations

import pytest

from skills import content_studio


def test_expand_content_fallback_generates_long_article(monkeypatch) -> None:
    monkeypatch.setattr(
        content_studio.ContentStudio,
        "_build_llm_client",
        staticmethod(lambda: None),
    )
    studio = content_studio.ContentStudio()

    article = studio.expand_content(
        selected_indices=[1, 2],
        full_cache=[
            {
                "index": 1,
                "title": "OpenAI enterprise rollout",
                "category": "Industry",
                "summary": "Teams are moving from pilots to production.",
                "content": "Enterprises are formalizing deployment and review workflows.",
                "url": "https://example.com/1",
            },
            {
                "index": 2,
                "title": "AI governance pressure increases",
                "category": "Policy",
                "summary": "Governance requirements now shape publishing workflows.",
                "content": "Compliance and source traceability are becoming mandatory.",
                "url": "https://example.com/2",
            },
        ],
    )

    assert "title" in article
    assert len(article["content"]) >= content_studio.MIN_ARTICLE_LENGTH
    assert "https://example.com/1" in article["content"]


def test_post_to_wechat_success_with_existing_cover_media_id(monkeypatch) -> None:
    monkeypatch.setenv("WECHAT_APP_ID", "app-id")
    monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
    monkeypatch.setenv("WECHAT_COVER_MEDIA_ID", "cover-001")
    monkeypatch.setattr(
        content_studio.ContentStudio,
        "_build_llm_client",
        staticmethod(lambda: None),
    )

    studio = content_studio.ContentStudio()
    monkeypatch.setattr(studio, "_get_wechat_access_token", lambda app_id, app_secret: "token-123")
    monkeypatch.setattr(studio, "_create_draft", lambda access_token, title, content, thumb_media_id: "draft-001")

    result = studio.post_to_wechat("Demo title", "Demo content")

    assert result["status"] == "draft_created"
    assert result["thumb_media_id"] == "cover-001"
    assert result["draft_media_id"] == "draft-001"


def test_post_to_wechat_missing_config(monkeypatch) -> None:
    monkeypatch.delenv("WECHAT_APP_ID", raising=False)
    monkeypatch.delenv("WECHAT_APP_SECRET", raising=False)

    with pytest.raises(RuntimeError):
        content_studio.post_to_wechat("title", "content")
