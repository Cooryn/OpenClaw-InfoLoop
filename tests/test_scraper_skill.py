from __future__ import annotations

from typing import Dict

from skills import scraper_skill


def test_build_proxies_from_env(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:8888")
    proxies = scraper_skill._build_proxies_from_env()
    assert proxies == {
        "http": "http://127.0.0.1:8888",
        "https": "http://127.0.0.1:8888",
    }


def test_scrape_and_monitor_keyword_filter(monkeypatch) -> None:
    html_map: Dict[str, str] = {
        "https://a.test": """
            <html>
              <head>
                <title>AI Policy Update</title>
                <meta property="article:published_time" content="2026-04-10" />
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

    def fake_fetch(url: str, timeout: int = 12) -> str | None:  # noqa: ARG001
        return html_map.get(url)

    monkeypatch.setattr(scraper_skill, "_fetch_html", fake_fetch)
    results = scraper_skill.scrape_and_monitor(
        ["https://a.test", "https://b.test"], keyword="policy"
    )

    assert len(results) == 1
    assert results[0]["url"] == "https://a.test"
    assert results[0]["title"] == "AI Policy Update"
    assert "regulation" in results[0]["content"].lower()

