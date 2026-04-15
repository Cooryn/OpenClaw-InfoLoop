from __future__ import annotations

import json
from types import SimpleNamespace

from skills import web_radar


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


def test_build_proxies_from_env_prefers_proxy_url(monkeypatch) -> None:
    monkeypatch.setenv("PROXY_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:8888")

    proxies = web_radar.WebRadar._build_proxies_from_env()

    assert proxies == {
        "http": "http://127.0.0.1:9000",
        "https": "http://127.0.0.1:9000",
    }


def test_fetch_articles_keyword_filter(monkeypatch) -> None:
    html_map = {
        "https://a.test": """
            <html>
              <head>
                <title>AI Policy Update</title>
                <meta property="article:published_time" content="2026-04-10" />
                <meta property="article:section" content="Policy" />
              </head>
              <body>
                <article>
                  <p>This article discusses policy and regulation updates.</p>
                </article>
              </body>
            </html>
        """,
        "https://b.test": """
            <html>
              <head><title>Sports News</title></head>
              <body>
                <article>
                  <p>Completely unrelated content.</p>
                </article>
              </body>
            </html>
        """,
    }

    monkeypatch.setattr(web_radar.WebRadar, "_build_llm_client", staticmethod(lambda: None))
    radar = web_radar.WebRadar()
    monkeypatch.setattr(radar, "_fetch_html", lambda url: html_map.get(url))

    results = radar.fetch_articles(
        ["https://a.test", "https://b.test"],
        keywords=["policy"],
    )

    assert len(results) == 1
    assert results[0]["url"] == "https://a.test"
    assert results[0]["title"] == "AI Policy Update"
    assert results[0]["category"] == "Policy"
    assert "regulation" in results[0]["content"].lower()


def test_summarize_articles_uses_llm_json_payload(monkeypatch) -> None:
    payload = json.dumps({"summary": "A concise and factual summary."})
    monkeypatch.setattr(
        web_radar.WebRadar,
        "_build_llm_client",
        staticmethod(lambda: _FakeClient(payload)),
    )

    radar = web_radar.WebRadar()
    result = radar.summarize_articles(
        [
            {
                "url": "https://example.com",
                "title": "Title",
                "category": "Policy",
                "publication_date": "2026-04-15",
                "content": "Long source content.",
            }
        ]
    )

    assert result[0]["index"] == 1
    assert result[0]["summary"] == "A concise and factual summary."
    assert result[0]["category"] == "Policy"

