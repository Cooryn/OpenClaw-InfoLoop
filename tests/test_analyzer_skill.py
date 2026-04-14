from __future__ import annotations

import json
from types import SimpleNamespace

from skills import analyzer_skill


class _FakeCompletions:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def create(self, **kwargs):  # noqa: ANN003, D401
        _ = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._payload))]
        )


class _FakeClient:
    def __init__(self, payload: str) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(payload))


def test_analyze_articles_fallback_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setattr(
        analyzer_skill,
        "_fallback_analyze",
        lambda article: {"category": analyzer_skill.CATEGORIES[0], "summary": "fallback"},
    )

    items = [{"title": "t", "url": "u", "content": "c", "publication_date": None}]
    result = analyzer_skill.analyze_articles(items)

    assert len(result) == 1
    assert result[0]["category"] == analyzer_skill.CATEGORIES[0]
    assert result[0]["summary"] == "fallback"


def test_analyze_articles_remap_unknown_category(monkeypatch) -> None:
    fake_payload = json.dumps({"category": "unknown", "summary": "valid summary"})
    monkeypatch.setattr(analyzer_skill, "_build_client", lambda: _FakeClient(fake_payload))
    monkeypatch.setenv("QWEN_MODEL", "qwen-plus")

    items = [{"title": "t", "url": "u", "content": "c", "publication_date": None}]
    result = analyzer_skill.analyze_articles(items)

    assert len(result) == 1
    assert result[0]["category"] == analyzer_skill.CATEGORIES[-1]
    assert result[0]["summary"] == "valid summary"

