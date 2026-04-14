"""InfoLoop discovery skill.

This module implements web article discovery and AI summarization for InfoLoop.
It provides both a class-based interface and module-level wrappers for OpenClaw
manifest compatibility.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from requests import Response, Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, Timeout
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_TIMEOUT_SECONDS = 15
SUMMARY_RETRIES = 3
MAX_SUMMARY_SOURCE_CHARS = 12000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class WebRadar:
    """Discovery and summarization engine for monitored web sources."""

    def __init__(
        self,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = 3,
        backoff_factor: float = 0.8,
        model: Optional[str] = None,
    ) -> None:
        """Initialize the WebRadar runtime.

        Args:
            timeout_seconds: HTTP timeout for each outbound request.
            max_retries: Retry count for transient HTTP failures.
            backoff_factor: Exponential backoff factor for retries.
            model: Optional Qwen model override.
        """
        load_dotenv()
        self.timeout_seconds = timeout_seconds
        self.model = model or os.getenv("QWEN_MODEL", DEFAULT_QWEN_MODEL).strip()
        self.proxies = self._build_proxies_from_env()
        self.session = self._build_session(max_retries=max_retries, backoff_factor=backoff_factor)
        self.client = self._build_llm_client()

    @staticmethod
    def _build_proxies_from_env() -> Optional[Dict[str, str]]:
        """Build proxy mapping from environment variables.

        Runtime contract:
            1) Prefer ``PROXY_URL``
            2) Fallback to ``HTTP_PROXY``

        Returns:
            Optional[Dict[str, str]]: Proxy mapping for ``requests`` if set.
        """
        proxy_url = os.getenv("PROXY_URL", "").strip() or os.getenv("HTTP_PROXY", "").strip()
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

    @staticmethod
    def _build_session(max_retries: int, backoff_factor: float) -> Session:
        """Create a resilient HTTP session.

        Args:
            max_retries: Retry count for retryable failures.
            backoff_factor: Backoff factor for retry intervals.

        Returns:
            Session: Configured requests session.
        """
        retry_strategy = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset({"GET", "POST"}),
            backoff_factor=backoff_factor,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"User-Agent": USER_AGENT})
        return session

    @staticmethod
    def _build_llm_client() -> Optional[OpenAI]:
        """Create the Qwen OpenAI-compatible client.

        Returns:
            Optional[OpenAI]: Initialized client if API key exists.
        """
        api_key = os.getenv("QWEN_API_KEY", "").strip()
        if not api_key:
            logger.warning("QWEN_API_KEY not configured; summary fallback mode enabled.")
            return None

        base_url = os.getenv("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL).strip()
        try:
            return OpenAI(api_key=api_key, base_url=base_url, timeout=45.0)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to initialize Qwen client: %s", exc)
            return None

    def fetch_articles(
        self, urls: Sequence[str], keywords: Optional[Sequence[str]] = None
    ) -> List[Dict[str, Any]]:
        """Fetch article payloads from monitored URLs.

        Args:
            urls: Source URL list.
            keywords: Optional keyword filters. Only matching records are kept.

        Returns:
            List[Dict[str, Any]]: Raw article list with title/category/content.
        """
        if not urls:
            logger.warning("fetch_articles called with empty URL list.")
            return []

        normalized_keywords = [kw.strip().lower() for kw in (keywords or []) if kw and kw.strip()]
        results: List[Dict[str, Any]] = []

        for raw_url in urls:
            url = (raw_url or "").strip()
            if not url:
                logger.warning("Skipped empty URL input.")
                continue

            html = self._fetch_html(url)
            if not html:
                continue

            try:
                article = self._parse_article(url=url, html=html)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to parse article from URL %s: %s", url, exc)
                continue

            if normalized_keywords and not self._article_matches_keywords(
                article=article, keywords=normalized_keywords
            ):
                logger.info("Filtered out URL by keywords: %s", url)
                continue

            results.append(article)

        logger.info("fetch_articles completed: %s/%s records returned.", len(results), len(urls))
        return results

    def summarize_articles(self, raw_data: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Summarize fetched records with Qwen into ~100-word digests.

        Args:
            raw_data: Raw article records from ``fetch_articles``.

        Returns:
            List[Dict[str, Any]]: Structured JSON-style summary records.
        """
        if not raw_data:
            logger.warning("summarize_articles called with empty raw_data.")
            return []

        summarized: List[Dict[str, Any]] = []
        for idx, article in enumerate(raw_data, start=1):
            try:
                summary = self._summarize_single_article(article)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected summarize failure on item %s: %s", idx, exc)
                summary = self._fallback_summary(str(article.get("content", "")))

            summarized.append(
                {
                    "index": idx,
                    "url": str(article.get("url", "")),
                    "title": str(article.get("title", "Untitled")),
                    "category": str(article.get("category", "Uncategorized")),
                    "publication_date": article.get("publication_date"),
                    "summary": summary,
                }
            )

        logger.info("summarize_articles completed for %s record(s).", len(summarized))
        return summarized

    def _fetch_html(self, url: str) -> Optional[str]:
        """Fetch HTML from a URL.

        Args:
            url: Target URL.

        Returns:
            Optional[str]: HTML text on success, else None.
        """
        try:
            response: Response = self.session.get(
                url,
                timeout=self.timeout_seconds,
                proxies=self.proxies,
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
            return response.text
        except Timeout:
            logger.warning("Request timeout for URL: %s", url)
        except RequestException as exc:
            logger.warning("Request failed for URL %s: %s", url, exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected HTTP fetch error for URL %s: %s", url, exc)
        return None

    def _parse_article(self, url: str, html: str) -> Dict[str, Any]:
        """Parse article fields from HTML content.

        Args:
            url: Source URL.
            html: Raw HTML text.

        Returns:
            Dict[str, Any]: Parsed article record.
        """
        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else "Untitled"
        publication_date = self._extract_publication_date(soup)
        category = self._extract_category(soup) or "Uncategorized"
        content = self._extract_plain_text(soup)

        return {
            "url": url,
            "title": title,
            "publication_date": publication_date,
            "category": category,
            "content": content,
        }

    @staticmethod
    def _extract_publication_date(soup: BeautifulSoup) -> Optional[str]:
        """Extract publication date from common HTML patterns.

        Args:
            soup: Parsed HTML object.

        Returns:
            Optional[str]: Date-like string if found.
        """
        date_meta_keys = [
            ("meta", {"property": "article:published_time"}),
            ("meta", {"name": "pubdate"}),
            ("meta", {"name": "publishdate"}),
            ("meta", {"name": "date"}),
            ("meta", {"name": "DC.date.issued"}),
        ]
        for tag, attrs in date_meta_keys:
            node = soup.find(tag, attrs=attrs)
            if node and node.get("content"):
                return str(node.get("content")).strip()

        for selector in ("time", ".publish-time", ".pub-date", ".article-time", ".post-date", ".date"):
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text
        return None

    @staticmethod
    def _extract_category(soup: BeautifulSoup) -> str:
        """Extract category from metadata or common category nodes.

        Args:
            soup: Parsed HTML object.

        Returns:
            str: Category string or fallback label.
        """
        meta_candidates = [
            ("meta", {"property": "article:section"}),
            ("meta", {"name": "section"}),
            ("meta", {"name": "category"}),
        ]
        for tag, attrs in meta_candidates:
            node = soup.find(tag, attrs=attrs)
            if node and node.get("content"):
                return str(node.get("content")).strip()

        for selector in (".category", ".article-category", "[rel='category tag']"):
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text

        return "General"

    @staticmethod
    def _extract_plain_text(soup: BeautifulSoup) -> str:
        """Extract readable plain text from article-like content blocks.

        Args:
            soup: Parsed HTML object.

        Returns:
            str: Extracted plain text.
        """
        for tag_name in ("script", "style", "noscript", "footer", "header"):
            for tag in soup.find_all(tag_name):
                tag.decompose()

        candidate = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_="article-content")
            or soup.find("div", class_="post-content")
            or soup.find("div", class_="content")
            or soup.body
        )
        if candidate is None:
            return ""

        paragraphs = []
        for node in candidate.find_all(["p", "li"]):
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if text:
                paragraphs.append(text)

        if paragraphs:
            return "\n".join(paragraphs)

        fallback = re.sub(r"\s+", " ", candidate.get_text(" ", strip=True)).strip()
        return fallback

    @staticmethod
    def _article_matches_keywords(article: Dict[str, Any], keywords: Sequence[str]) -> bool:
        """Check whether article content matches any keyword.

        Args:
            article: Parsed article record.
            keywords: Normalized keyword list.

        Returns:
            bool: True if any keyword appears in article text.
        """
        haystack = (
            f"{article.get('title', '')}\n"
            f"{article.get('category', '')}\n"
            f"{article.get('content', '')}"
        ).lower()
        return any(keyword in haystack for keyword in keywords)

    def _summarize_single_article(self, article: Dict[str, Any]) -> str:
        """Generate a ~100-word summary for one article.

        Args:
            article: Raw article payload.

        Returns:
            str: Generated summary text.
        """
        source_text = str(article.get("content", "")).strip()
        title = str(article.get("title", "Untitled")).strip()
        category = str(article.get("category", "General")).strip()
        source_text = source_text[:MAX_SUMMARY_SOURCE_CHARS]

        if not source_text:
            return "Summary unavailable because the source article content is empty."

        if self.client is None:
            return self._fallback_summary(source_text)

        system_prompt = (
            "You are an enterprise editorial assistant. "
            "Summarize the article into approximately 100 words. "
            "Return only a JSON object with one field: summary."
        )
        user_payload = {
            "title": title,
            "category": category,
            "content": source_text,
            "requirements": "summary should be concise, factual, and near 100 words",
        }

        last_error: Optional[Exception] = None
        for attempt in range(1, SUMMARY_RETRIES + 1):
            try:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(user_payload, ensure_ascii=False),
                            },
                        ],
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                except TypeError:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(user_payload, ensure_ascii=False),
                            },
                        ],
                        temperature=0.2,
                    )

                content = response.choices[0].message.content or "{}"
                summary = self._parse_summary_content(content)
                if summary:
                    return summary
                raise ValueError("Summary field is empty.")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Qwen summary attempt %s/%s failed: %s",
                    attempt,
                    SUMMARY_RETRIES,
                    exc,
                )
                if attempt < SUMMARY_RETRIES:
                    time.sleep(min(2**attempt, 8))

        logger.error("Qwen summary failed after retries: %s", last_error)
        return self._fallback_summary(source_text)

    @staticmethod
    def _parse_summary_content(raw_text: str) -> str:
        """Parse ``summary`` field from model output text.

        Args:
            raw_text: Raw model output.

        Returns:
            str: Summary text if present, else empty string.
        """
        try:
            payload = json.loads(WebRadar._extract_json_block(raw_text))
        except (json.JSONDecodeError, ValueError):
            return ""
        return str(payload.get("summary", "")).strip()

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """Extract JSON object block from model output.

        Args:
            text: Model output text.

        Returns:
            str: JSON object string.

        Raises:
            ValueError: If no JSON object block can be extracted.
        """
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
            stripped = re.sub(r"\s*```$", "", stripped)

        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", stripped)
        if not match:
            raise ValueError("No JSON object found in model output.")
        return match.group(0)

    @staticmethod
    def _fallback_summary(text: str) -> str:
        """Generate deterministic fallback summary without LLM.

        Args:
            text: Source text.

        Returns:
            str: Truncated fallback summary.
        """
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return "Summary unavailable because source content is missing."

        words = normalized.split(" ")
        if len(words) >= 30:
            clipped = " ".join(words[:100])
            if len(words) > 100:
                clipped += "..."
            return clipped

        if len(normalized) > 220:
            return normalized[:220].rstrip() + "..."
        return normalized


_DEFAULT_RADAR: Optional[WebRadar] = None


def _get_default_radar() -> WebRadar:
    """Get singleton WebRadar instance for module-level wrappers.

    Returns:
        WebRadar: Initialized WebRadar instance.
    """
    global _DEFAULT_RADAR
    if _DEFAULT_RADAR is None:
        _DEFAULT_RADAR = WebRadar()
    return _DEFAULT_RADAR


def fetch_articles(
    urls: Sequence[str], keywords: Optional[Sequence[str]] = None
) -> List[Dict[str, Any]]:
    """Module wrapper for ``WebRadar.fetch_articles``.

    Args:
        urls: Source URL list.
        keywords: Optional keyword filters.

    Returns:
        List[Dict[str, Any]]: Raw article records.
    """
    return _get_default_radar().fetch_articles(urls=urls, keywords=keywords)


def summarize_articles(raw_data: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Module wrapper for ``WebRadar.summarize_articles``.

    Args:
        raw_data: Raw records from ``fetch_articles``.

    Returns:
        List[Dict[str, Any]]: Structured summary records.
    """
    return _get_default_radar().summarize_articles(raw_data=raw_data)


if __name__ == "__main__":
    radar = WebRadar()
    demo_articles = radar.fetch_articles(urls=["https://example.com"], keywords=["example"])
    print(f"Fetched articles: {len(demo_articles)}")
    if demo_articles:
        print(json.dumps(demo_articles[0], ensure_ascii=False, indent=2))

    summary_records = radar.summarize_articles(demo_articles)
    print(f"Summaries generated: {len(summary_records)}")
    if summary_records:
        print(json.dumps(summary_records[0], ensure_ascii=False, indent=2))
