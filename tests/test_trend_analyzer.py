from __future__ import annotations

import json
from types import SimpleNamespace

from skills import trend_analyzer


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


def test_generate_trend_report_fallback_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    analyzer = trend_analyzer.TrendAnalyzer()

    report = analyzer.generate_trend_report(
        [
            "OpenAI expands enterprise agent deployment and workflow governance.",
            "OpenAI and Microsoft discuss governance, enterprise deployment, and agents.",
        ]
    )

    assert report["document_count"] == 2
    assert report["top_entities"]
    assert report["top_keywords"]
    assert "下一天建议优先监控" in report["next_day_strategy"]


def test_generate_trend_report_llm_success(monkeypatch) -> None:
    payload = json.dumps(
        {
            "top_entities": [{"name": "OpenAI", "count": 3}],
            "top_keywords": [{"name": "agents", "count": 4}],
            "next_day_strategy": "继续监控 OpenAI 与 agents 相关动态。",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        trend_analyzer.TrendAnalyzer,
        "_build_llm_client",
        staticmethod(lambda: _FakeClient(payload)),
    )

    analyzer = trend_analyzer.TrendAnalyzer()
    report = analyzer.generate_trend_report(["demo text"])

    assert report["top_entities"][0]["name"] == "OpenAI"
    assert report["top_keywords"][0]["name"] == "agents"
    assert report["next_day_strategy"] == "继续监控 OpenAI 与 agents 相关动态。"
