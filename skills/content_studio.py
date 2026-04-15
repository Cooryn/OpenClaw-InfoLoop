"""InfoLoop production skill.

This module expands selected news items into long-form WeChat articles and
creates WeChat Official Account drafts with uploaded cover images.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import time
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import requests
from dotenv import load_dotenv
from openai import OpenAI
from requests import Response, Session
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-plus"
DEFAULT_HTTP_TIMEOUT = 30
DEFAULT_AUTHOR = "InfoLoop Bot"
DEFAULT_SOURCE_URL = ""
MIN_ARTICLE_LENGTH = 800
LLM_RETRIES = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class ContentStudio:
    """Content expansion and WeChat publishing workflow."""

    def __init__(
        self,
        model: Optional[str] = None,
        timeout_seconds: int = DEFAULT_HTTP_TIMEOUT,
        max_retries: int = 3,
        backoff_factor: float = 0.8,
    ) -> None:
        """Initialize the content studio runtime.

        Args:
            model: Optional model override for article generation.
            timeout_seconds: HTTP timeout seconds for WeChat API calls.
            max_retries: Retry count for transient HTTP failures.
            backoff_factor: Retry backoff factor.
        """
        load_dotenv()
        self.timeout_seconds = timeout_seconds
        self.model = (
            model
            or os.getenv("CONTENT_STUDIO_MODEL", "").strip()
            or os.getenv("QWEN_MODEL", DEFAULT_QWEN_MODEL).strip()
        )
        self.proxies = self._build_proxies_from_env()
        self.session = self._build_session(max_retries=max_retries, backoff_factor=backoff_factor)
        self.client = self._build_llm_client()

    @staticmethod
    def _build_proxies_from_env() -> Optional[Dict[str, str]]:
        """Build proxy mapping from environment variables.

        Returns:
            Optional[Dict[str, str]]: Proxy mapping for requests if configured.
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
            backoff_factor: Retry delay backoff factor.

        Returns:
            Session: Configured session.
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
        """Create a Qwen OpenAI-compatible client.

        Returns:
            Optional[OpenAI]: Client instance when API key is configured.
        """
        api_key = os.getenv("QWEN_API_KEY", "").strip()
        if not api_key:
            logger.warning("QWEN_API_KEY not configured; content expansion fallback mode enabled.")
            return None

        base_url = os.getenv("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL).strip()
        try:
            return OpenAI(api_key=api_key, base_url=base_url, timeout=90.0)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to initialize Qwen client: %s", exc)
            return None

    def expand_content(
        self, selected_indices: Sequence[int], full_cache: Sequence[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Expand selected records into a long-form WeChat article.

        Args:
            selected_indices: User-selected digest indices.
            full_cache: Full cached source materials.

        Returns:
            Dict[str, str]: Generated article payload with ``title`` and ``content``.
        """
        records = self._select_records(selected_indices=selected_indices, full_cache=full_cache)
        if self.client is not None:
            article = self._generate_article_with_llm(records)
            if article:
                logger.info(
                    "Generated WeChat article with LLM from %s selected item(s).",
                    len(records),
                )
                return article

        fallback = self._build_fallback_article(records)
        logger.info(
            "Generated fallback WeChat article from %s selected item(s).",
            len(records),
        )
        return fallback

    def post_to_wechat(self, title: str, content: str) -> Dict[str, str]:
        """Create a WeChat Official Account draft.

        Args:
            title: Draft title.
            content: Draft content in plain text or HTML.

        Returns:
            Dict[str, str]: Draft creation metadata.
        """
        app_id = os.getenv("WECHAT_APP_ID", "").strip()
        app_secret = os.getenv("WECHAT_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            raise RuntimeError("WECHAT_APP_ID and WECHAT_APP_SECRET must be configured.")

        access_token = self._get_wechat_access_token(app_id=app_id, app_secret=app_secret)
        thumb_media_id = self._resolve_cover_media_id(access_token=access_token)
        draft_media_id = self._create_draft(
            access_token=access_token,
            title=title,
            content=content,
            thumb_media_id=thumb_media_id,
        )
        result = {
            "status": "draft_created",
            "access_token": access_token[:8] + "...",
            "thumb_media_id": thumb_media_id,
            "draft_media_id": draft_media_id,
        }
        logger.info("WeChat draft created successfully. draft_media_id=%s", draft_media_id)
        return result

    def _select_records(
        self, selected_indices: Sequence[int], full_cache: Sequence[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Resolve selected digest indices into source records.

        Args:
            selected_indices: User-selected indices.
            full_cache: Cached source records.

        Returns:
            List[Dict[str, Any]]: Matched records.
        """
        if not selected_indices:
            raise ValueError("selected_indices cannot be empty.")
        if not full_cache:
            raise ValueError("full_cache cannot be empty when expanding content.")

        normalized_indices: List[int] = []
        for raw_index in selected_indices:
            try:
                value = int(raw_index)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid selected index: {raw_index}") from exc
            if value <= 0:
                raise ValueError(f"selected_indices must be positive: {raw_index}")
            if value not in normalized_indices:
                normalized_indices.append(value)

        record_map: Dict[int, Dict[str, Any]] = {}
        for position, record in enumerate(full_cache, start=1):
            try:
                record_index = int(record.get("index", position))
            except (TypeError, ValueError):
                record_index = position
            record_map[record_index] = dict(record)

        missing = [idx for idx in normalized_indices if idx not in record_map]
        if missing:
            raise ValueError(f"Selected indices not found in cache: {missing}")

        return [record_map[idx] for idx in normalized_indices]

    def _generate_article_with_llm(
        self, records: Sequence[Dict[str, Any]]
    ) -> Optional[Dict[str, str]]:
        """Generate article with Qwen.

        Args:
            records: Selected source records.

        Returns:
            Optional[Dict[str, str]]: Generated article or None on failure.
        """
        prompt_payload = []
        for record in records:
            prompt_payload.append(
                {
                    "index": record.get("index"),
                    "title": record.get("title"),
                    "category": record.get("category"),
                    "summary": record.get("summary"),
                    "publication_date": record.get("publication_date"),
                    "url": record.get("url"),
                    "content": str(record.get("content", ""))[:5000],
                }
            )

        system_prompt = (
            "你是一名资深微信公众号主编，擅长把多条资讯整合成一篇高质量、可直接发布的长文。"
            "请基于输入材料，产出一篇适合企业读者的微信公众号文章，语气专业、克制、可信，"
            "强调洞察与行动建议，不要杜撰事实。严格输出 JSON 对象，字段只有 title 和 content。"
            "其中 content 必须是不少于 800 字的正文，使用自然段，不要使用 Markdown 代码块。"
        )

        last_error: Optional[Exception] = None
        for attempt in range(1, LLM_RETRIES + 1):
            try:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(prompt_payload, ensure_ascii=False),
                            },
                        ],
                        temperature=0.5,
                        response_format={"type": "json_object"},
                    )
                except TypeError:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(prompt_payload, ensure_ascii=False),
                            },
                        ],
                        temperature=0.5,
                    )

                raw_content = response.choices[0].message.content or "{}"
                payload = json.loads(self._extract_json_block(raw_content))
                title = str(payload.get("title", "")).strip()
                content = self._normalize_article_content(str(payload.get("content", "")).strip())
                if title and len(content) >= MIN_ARTICLE_LENGTH:
                    return {"title": title, "content": content}
                raise ValueError("LLM returned incomplete article payload.")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Qwen content generation attempt %s/%s failed: %s",
                    attempt,
                    LLM_RETRIES,
                    exc,
                )
                if attempt < LLM_RETRIES:
                    time.sleep(min(2**attempt, 8))

        logger.error("Qwen content generation failed after retries: %s", last_error)
        return None

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """Extract JSON object block from model output.

        Args:
            text: Model output text.

        Returns:
            str: JSON block string.
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
    def _normalize_article_content(content: str) -> str:
        """Normalize article text into readable plain text paragraphs.

        Args:
            content: Raw generated content.

        Returns:
            str: Normalized content.
        """
        normalized = content.replace("\r\n", "\n")
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        return normalized

    def _build_fallback_article(self, records: Sequence[Dict[str, Any]]) -> Dict[str, str]:
        """Build a deterministic article when LLM generation is unavailable.

        Args:
            records: Selected source records.

        Returns:
            Dict[str, str]: Article payload.
        """
        titles = [str(record.get("title", "未命名选题")).strip() for record in records]
        main_title = titles[0] if titles else "今日内容观察"
        title = f"{main_title}：给内容运营团队的重点解读"

        intro = (
            "今天我们从信息流中挑选出几条值得进一步放大的线索，目的不是简单复述原文，"
            "而是把它们整理成一篇适合内容运营团队快速判断的工作稿。对于公众号场景来说，"
            "真正有价值的内容往往同时具备三个特征：议题足够清晰、材料足够可信、观点能够落到行动。"
            "以下内容将围绕这些标准展开，帮助我们判断哪些信息适合继续加工、如何设置表达角度，"
            "以及后续在标题、摘要和选题跟进上应当如何取舍。"
        )

        paragraphs = [intro]
        for order, record in enumerate(records, start=1):
            record_title = str(record.get("title", f"选题 {order}")).strip() or f"选题 {order}"
            category = str(record.get("category", "未分类")).strip() or "未分类"
            summary = str(record.get("summary", "")).strip() or "原始摘要暂缺。"
            url = str(record.get("url", "")).strip()
            source_excerpt = self._build_excerpt(str(record.get("content", "")))

            paragraphs.append(f"{order}. {record_title}")
            paragraphs.append(
                f"这条线索所属的类别是“{category}”。从当前材料看，它之所以值得被纳入内容池，"
                f"核心原因在于它不仅能提供事实层面的更新，还能帮助读者形成更稳定的判断框架。{summary}"
            )
            paragraphs.append(
                "如果我们把这条内容用于公众号正文，建议不要停留在“发生了什么”这一层，"
                "而应继续追问三个问题：这件事为什么在当下出现、它会影响哪些角色、内容团队应该据此如何调整选题或表达。"
                "这样的写法更容易让文章从资讯搬运升级为观点型稿件。"
            )
            paragraphs.append(
                f"结合原始内容，当前最值得保留的素材包括：{source_excerpt}"
            )
            if url:
                paragraphs.append(
                    f"从引用管理的角度看，这条材料的原始来源是 {url}。后续如果进入正式发稿流程，"
                    "建议把来源信息整理到编辑备注中，以便在人工复核时快速回溯。"
                )

        conclusion = (
            "综合来看，这批材料更适合被整合为一篇“信息更新 + 影响判断 + 行动建议”的复合型文章。"
            "标题层面可以强调变化本身，也可以强调变化背后的业务意义；正文层面则应尽量减少松散堆砌，"
            "用统一的分析框架把不同线索串起来。对于 InfoLoop 的人机协同流程来说，这一步扩写并不是替代人工判断，"
            "而是把零散信息先组织成一个高质量初稿，让最终发布前的人工把关更聚焦、更高效。"
        )
        paragraphs.append(conclusion)

        content = "\n\n".join(paragraphs).strip()
        while len(content) < MIN_ARTICLE_LENGTH:
            content += (
                "\n\n补充建议：在进入正式发布前，可以再做一轮人工校对，重点检查事实来源、表述边界、"
                "观点是否过度延伸，以及文章是否真正服务于目标读者的决策需求。对于公众号内容来说，"
                "节奏感和结构感同样重要，因此标题、导语、小标题和结尾行动建议最好形成同一条叙事主线。"
            )

        return {"title": title, "content": content}

    @staticmethod
    def _build_excerpt(content: str, max_chars: int = 180) -> str:
        """Build a short excerpt from source content.

        Args:
            content: Raw source text.
            max_chars: Maximum excerpt length.

        Returns:
            str: Short excerpt.
        """
        normalized = re.sub(r"\s+", " ", content).strip()
        if not normalized:
            return "原始正文暂时不足，后续需要在人工复核时补齐关键事实。"
        if len(normalized) <= max_chars:
            return normalized
        return normalized[:max_chars].rstrip() + "..."

    def _get_wechat_access_token(self, app_id: str, app_secret: str) -> str:
        """Get WeChat Official Account access token.

        Args:
            app_id: WeChat app ID.
            app_secret: WeChat app secret.

        Returns:
            str: Access token.
        """
        payload = self._request_json(
            method="GET",
            url="https://api.weixin.qq.com/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": app_id,
                "secret": app_secret,
            },
        )
        access_token = str(payload.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError("Failed to obtain WeChat access token.")
        return access_token

    def _resolve_cover_media_id(self, access_token: str) -> str:
        """Resolve cover media ID from env or by uploading a local image.

        Args:
            access_token: WeChat access token.

        Returns:
            str: Thumbnail media ID.
        """
        existing_media_id = os.getenv("WECHAT_COVER_MEDIA_ID", "").strip()
        if existing_media_id:
            return existing_media_id

        cover_image_path = os.getenv("WECHAT_COVER_IMAGE_PATH", "").strip()
        if not cover_image_path:
            raise RuntimeError(
                "WECHAT_COVER_MEDIA_ID or WECHAT_COVER_IMAGE_PATH must be configured."
            )

        path = Path(cover_image_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"WeChat cover image not found: {path}")
        return self._upload_cover_image(access_token=access_token, image_path=path)

    def _upload_cover_image(self, access_token: str, image_path: Path) -> str:
        """Upload cover image and return thumbnail media ID.

        Args:
            access_token: WeChat access token.
            image_path: Local cover image path.

        Returns:
            str: Thumbnail media ID.
        """
        mime_type, _ = mimetypes.guess_type(str(image_path))
        media_type = mime_type or "image/jpeg"
        with image_path.open("rb") as file_handle:
            payload = self._request_json(
                method="POST",
                url="https://api.weixin.qq.com/cgi-bin/material/add_material",
                params={"access_token": access_token, "type": "thumb"},
                files={"media": (image_path.name, file_handle, media_type)},
            )

        media_id = str(payload.get("media_id", "")).strip()
        if not media_id:
            raise RuntimeError("Cover image upload succeeded but media_id is missing.")
        return media_id

    def _create_draft(
        self,
        access_token: str,
        title: str,
        content: str,
        thumb_media_id: str,
    ) -> str:
        """Create WeChat draft article.

        Args:
            access_token: WeChat access token.
            title: Article title.
            content: Plain text or HTML content.
            thumb_media_id: Cover thumbnail media ID.

        Returns:
            str: Draft media ID.
        """
        payload = {
            "articles": [
                {
                    "title": title,
                    "author": os.getenv("WECHAT_AUTHOR", DEFAULT_AUTHOR).strip() or DEFAULT_AUTHOR,
                    "digest": self._build_digest(content),
                    "content": self._to_wechat_html(content),
                    "content_source_url": os.getenv(
                        "WECHAT_CONTENT_SOURCE_URL", DEFAULT_SOURCE_URL
                    ).strip(),
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                    "show_cover_pic": 1 if self._env_bool("WECHAT_SHOW_COVER_PIC", True) else 0,
                }
            ]
        }
        response = self._request_json(
            method="POST",
            url="https://api.weixin.qq.com/cgi-bin/draft/add",
            params={"access_token": access_token},
            data=payload,
        )
        media_id = str(response.get("media_id", "")).strip()
        if not media_id:
            raise RuntimeError("Draft creation succeeded but media_id is missing.")
        return media_id

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send HTTP request and parse JSON response.

        Args:
            method: HTTP method.
            url: Request URL.
            params: Query params.
            data: JSON payload when not sending files.
            files: Multipart files payload.

        Returns:
            Dict[str, Any]: Response JSON.
        """
        try:
            response: Response = self.session.request(
                method=method.upper(),
                url=url,
                params=params,
                json=data if files is None else None,
                files=files,
                timeout=self.timeout_seconds,
                proxies=self.proxies,
            )
            response.raise_for_status()
        except RequestException as exc:
            logger.exception("WeChat API request failed: %s %s", method, url)
            raise RuntimeError(f"WeChat API request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            logger.exception("WeChat API returned non-JSON response from %s", url)
            raise RuntimeError("WeChat API returned non-JSON response.") from exc

        if "errcode" in payload and int(payload.get("errcode", 0)) != 0:
            errcode = payload.get("errcode")
            errmsg = payload.get("errmsg", "unknown error")
            raise RuntimeError(f"WeChat API error ({errcode}): {errmsg}")

        return payload

    @staticmethod
    def _build_digest(content: str, max_chars: int = 120) -> str:
        """Build a WeChat digest string from article content.

        Args:
            content: Article content.
            max_chars: Maximum digest length.

        Returns:
            str: Digest string.
        """
        normalized = re.sub(r"\s+", " ", content).strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[:max_chars].rstrip() + "..."

    @staticmethod
    def _to_wechat_html(content: str) -> str:
        """Convert plain text article into simple HTML for WeChat drafts.

        Args:
            content: Plain text or existing HTML content.

        Returns:
            str: HTML content.
        """
        stripped = content.strip()
        if re.search(r"<(p|section|div|h1|h2|h3|ul|ol|li|br)\b", stripped, flags=re.IGNORECASE):
            return stripped

        paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", stripped) if segment.strip()]
        html_parts: List[str] = []
        for paragraph in paragraphs:
            safe_text = escape(paragraph)
            if len(paragraph) <= 24 and "。" not in paragraph and "：" not in paragraph:
                html_parts.append(f"<h2>{safe_text}</h2>")
            else:
                safe_text = safe_text.replace("\n", "<br/>")
                html_parts.append(f"<p>{safe_text}</p>")
        return "".join(html_parts)

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        """Parse a boolean environment variable.

        Args:
            name: Environment variable name.
            default: Default boolean value.

        Returns:
            bool: Parsed boolean.
        """
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}


_DEFAULT_STUDIO: Optional[ContentStudio] = None


def _get_default_studio() -> ContentStudio:
    """Get a singleton studio instance for module-level wrappers.

    Returns:
        ContentStudio: Shared studio instance.
    """
    global _DEFAULT_STUDIO
    if _DEFAULT_STUDIO is None:
        _DEFAULT_STUDIO = ContentStudio()
    return _DEFAULT_STUDIO


def expand_content(selected_indices: List[int], full_cache: List[Dict[str, Any]]) -> Dict[str, str]:
    """Expand selected materials into a long-form WeChat article.

    Args:
        selected_indices: User-selected digest indices.
        full_cache: Full source material cache.

    Returns:
        Dict[str, str]: Article title and content.
    """
    return _get_default_studio().expand_content(
        selected_indices=selected_indices,
        full_cache=full_cache,
    )


def post_to_wechat(title: str, content: str) -> Dict[str, str]:
    """Create a WeChat draft from prepared article content.

    Args:
        title: Draft title.
        content: Draft content.

    Returns:
        Dict[str, str]: Draft creation metadata.
    """
    return _get_default_studio().post_to_wechat(title=title, content=content)


if __name__ == "__main__":
    demo_cache: List[Dict[str, Any]] = [
        {
            "index": 1,
            "title": "AI Agent enters enterprise workflow",
            "category": "Productivity",
            "summary": "Enterprises are moving from experimentation to limited operational deployment.",
            "content": (
                "Several teams are now testing AI agents in reporting, customer support, "
                "and knowledge retrieval. The shift is no longer about novelty, but about "
                "whether workflow quality, governance, and human review can scale together."
            ),
            "url": "https://example.com/agent-workflow",
        },
        {
            "index": 2,
            "title": "Policy pressure reshapes model deployment",
            "category": "Policy",
            "summary": "Compliance and auditability are becoming hard requirements for deployment.",
            "content": (
                "Teams that once optimized only for generation quality are now expected to "
                "prove traceability, content safety, and source governance before publishing."
            ),
            "url": "https://example.com/policy-shift",
        },
    ]

    studio = ContentStudio()
    article = studio.expand_content(selected_indices=[1, 2], full_cache=demo_cache)
    print(f"Draft title: {article['title']}")
    print(f"Draft content length: {len(article['content'])}")

    if os.getenv("WECHAT_APP_ID") and os.getenv("WECHAT_APP_SECRET"):
        try:
            draft_result = studio.post_to_wechat(
                title=article["title"],
                content=article["content"],
            )
            print(json.dumps(draft_result, ensure_ascii=False, indent=2))
        except Exception as exc:  # noqa: BLE001
            logger.error("WeChat draft creation failed: %s", exc)
    else:
        print("Skip WeChat draft demo: missing WECHAT_APP_ID or WECHAT_APP_SECRET.")
