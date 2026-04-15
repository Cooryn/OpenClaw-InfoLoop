"""InfoLoop evolution skill.

This module analyzes daily text corpora to extract recurring entities,
high-signal keywords, and a next-day monitoring strategy.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from dotenv import load_dotenv
from openai import OpenAI


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen-plus"
LLM_RETRIES = 3
MAX_DOC_CHARS = 4000
MAX_SIGNAL_ITEMS = 5

EN_STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "and",
    "are",
    "been",
    "being",
    "between",
    "could",
    "from",
    "have",
    "into",
    "more",
    "most",
    "only",
    "other",
    "over",
    "said",
    "some",
    "such",
    "than",
    "that",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "today",
    "using",
    "with",
    "would",
}

ZH_STOPWORDS = {
    "一个",
    "一些",
    "一种",
    "为了",
    "以及",
    "企业",
    "今天",
    "信息",
    "内容",
    "公司",
    "可以",
    "因为",
    "如果",
    "对于",
    "已经",
    "开始",
    "当前",
    "我们",
    "建议",
    "平台",
    "影响",
    "相关",
    "需要",
    "进行",
    "通过",
    "这个",
    "这些",
}


class TrendAnalyzer:
    """Analyze daily text corpora for next-day monitoring guidance."""

    def __init__(self, model: Optional[str] = None) -> None:
        """Initialize the analyzer.

        Args:
            model: Optional Qwen model override.
        """
        load_dotenv()
        self.model = model or os.getenv("QWEN_MODEL", DEFAULT_QWEN_MODEL).strip()
        self.client = self._build_llm_client()

    @staticmethod
    def _build_llm_client() -> Optional[OpenAI]:
        """Create the Qwen OpenAI-compatible client.

        Returns:
            Optional[OpenAI]: LLM client when API key is configured.
        """
        api_key = os.getenv("QWEN_API_KEY", "").strip()
        if not api_key:
            logger.warning("QWEN_API_KEY not configured; trend analysis fallback mode enabled.")
            return None

        base_url = os.getenv("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL).strip()
        try:
            return OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to initialize Qwen client: %s", exc)
            return None

    def generate_trend_report(self, all_daily_text: Sequence[str]) -> Dict[str, Any]:
        """Generate entity, keyword, and strategy report from daily corpus.

        Args:
            all_daily_text: Daily aggregated text corpus.

        Returns:
            Dict[str, Any]: Structured trend report.
        """
        documents = [self._normalize_text(text) for text in all_daily_text if self._normalize_text(text)]
        if not documents:
            logger.warning("generate_trend_report called with empty corpus.")
            return {
                "document_count": 0,
                "top_entities": [],
                "top_keywords": [],
                "next_day_strategy": "No daily corpus was provided, so no next-day monitoring strategy could be generated.",
            }

        llm_report = self._generate_with_llm(documents)
        if llm_report is not None:
            logger.info("Trend report generated with Qwen from %s document(s).", len(documents))
            return {
                "document_count": len(documents),
                "top_entities": llm_report["top_entities"],
                "top_keywords": llm_report["top_keywords"],
                "next_day_strategy": llm_report["next_day_strategy"],
            }

        entities = self._extract_entities_fallback(documents)
        keywords = self._extract_keywords_fallback(documents)
        strategy = self._build_strategy(
            document_count=len(documents),
            entities=entities,
            keywords=keywords,
        )
        logger.info("Trend report generated with fallback heuristics from %s document(s).", len(documents))
        return {
            "document_count": len(documents),
            "top_entities": entities,
            "top_keywords": keywords,
            "next_day_strategy": strategy,
        }

    def _generate_with_llm(self, documents: Sequence[str]) -> Optional[Dict[str, Any]]:
        """Generate trend report with Qwen.

        Args:
            documents: Normalized daily documents.

        Returns:
            Optional[Dict[str, Any]]: Structured report or None on failure.
        """
        if self.client is None:
            return None

        payload = [
            {"index": index, "text": document[:MAX_DOC_CHARS]}
            for index, document in enumerate(documents, start=1)
        ]
        system_prompt = (
            "你是一名内容情报分析师。请对输入语料做实体识别、关键词提取和趋势判断。"
            "严格输出 JSON 对象，只包含三个字段：top_entities、top_keywords、next_day_strategy。"
            "top_entities 和 top_keywords 都必须是数组，数组元素为对象，字段为 name 和 count。"
            "next_day_strategy 需要给出下一天应该继续监控的主题、主体和触发条件，要求简洁、具体、可执行。"
        )

        last_error: Optional[Exception] = None
        for attempt in range(1, LLM_RETRIES + 1):
            try:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                except TypeError:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        temperature=0.2,
                    )

                raw_text = response.choices[0].message.content or "{}"
                parsed = json.loads(self._extract_json_block(raw_text))
                top_entities = self._normalize_signal_items(parsed.get("top_entities"))
                top_keywords = self._normalize_signal_items(parsed.get("top_keywords"))
                next_day_strategy = str(parsed.get("next_day_strategy", "")).strip()
                if next_day_strategy:
                    return {
                        "top_entities": top_entities,
                        "top_keywords": top_keywords,
                        "next_day_strategy": next_day_strategy,
                    }
                raise ValueError("next_day_strategy is missing.")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Qwen trend analysis attempt %s/%s failed: %s",
                    attempt,
                    LLM_RETRIES,
                    exc,
                )
                if attempt < LLM_RETRIES:
                    time.sleep(min(2**attempt, 8))

        logger.error("Qwen trend analysis failed after retries: %s", last_error)
        return None

    @staticmethod
    def _normalize_signal_items(raw_items: Any) -> List[Dict[str, Any]]:
        """Normalize entity or keyword items into a stable list shape.

        Args:
            raw_items: Raw parsed items from LLM or fallback logic.

        Returns:
            List[Dict[str, Any]]: Normalized ``name`` and ``count`` items.
        """
        if not isinstance(raw_items, list):
            return []

        aggregated: Dict[str, int] = {}
        for raw_item in raw_items:
            if isinstance(raw_item, dict):
                name = str(
                    raw_item.get("name")
                    or raw_item.get("entity")
                    or raw_item.get("keyword")
                    or ""
                ).strip()
                try:
                    count = int(raw_item.get("count", 1))
                except (TypeError, ValueError):
                    count = 1
            else:
                name = str(raw_item).strip()
                count = 1

            if not name:
                continue
            aggregated[name] = aggregated.get(name, 0) + max(count, 1)

        normalized = [
            {"name": name, "count": count}
            for name, count in sorted(
                aggregated.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )
        ]
        return normalized[:MAX_SIGNAL_ITEMS]

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """Extract a JSON object from model output.

        Args:
            text: Model output text.

        Returns:
            str: JSON object block.
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
    def _normalize_text(text: str) -> str:
        """Normalize raw text for analysis.

        Args:
            text: Raw text.

        Returns:
            str: Normalized text.
        """
        normalized = re.sub(r"\s+", " ", str(text)).strip()
        return normalized

    def _extract_entities_fallback(self, documents: Sequence[str]) -> List[Dict[str, Any]]:
        """Extract recurring entity-like signals from corpus heuristically.

        Args:
            documents: Normalized documents.

        Returns:
            List[Dict[str, Any]]: Top entity candidates.
        """
        counter: Counter[str] = Counter()

        for document in documents:
            for match in re.findall(
                r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}|[A-Z]{2,}(?:\s+[A-Z]{2,})*)\b",
                document,
            ):
                entity = match.strip()
                if len(entity) >= 2:
                    counter[entity] += 1

            for token in re.findall(r"[\u4e00-\u9fff]{2,8}", document):
                if token in ZH_STOPWORDS:
                    continue
                if len(token) < 2:
                    continue
                counter[token] += 1

        results = [
            {"name": name, "count": count}
            for name, count in counter.most_common(MAX_SIGNAL_ITEMS * 3)
            if count >= 2 or re.search(r"[A-Z]", name)
        ]
        return results[:MAX_SIGNAL_ITEMS]

    def _extract_keywords_fallback(self, documents: Sequence[str]) -> List[Dict[str, Any]]:
        """Extract keyword signals from corpus heuristically.

        Args:
            documents: Normalized documents.

        Returns:
            List[Dict[str, Any]]: Top keyword items.
        """
        counter: Counter[str] = Counter()

        for document in documents:
            english_tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9+-]{2,20}\b", document.lower())
            chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,8}", document)

            for token in english_tokens:
                if token in EN_STOPWORDS:
                    continue
                counter[token] += 1

            for token in chinese_tokens:
                if token in ZH_STOPWORDS:
                    continue
                counter[token] += 1

        return [
            {"name": name, "count": count}
            for name, count in counter.most_common(MAX_SIGNAL_ITEMS)
        ]

    @staticmethod
    def _build_strategy(
        document_count: int,
        entities: Sequence[Dict[str, Any]],
        keywords: Sequence[Dict[str, Any]],
    ) -> str:
        """Build a next-day monitoring strategy string.

        Args:
            document_count: Number of analyzed documents.
            entities: Top entity items.
            keywords: Top keyword items.

        Returns:
            str: Suggested next-day monitoring strategy.
        """
        entity_names = "、".join(item["name"] for item in entities[:3]) or "重点主体"
        keyword_names = "、".join(item["name"] for item in keywords[:5]) or "核心关键词"
        return (
            f"基于今日 {document_count} 份材料，下一天建议优先监控 {entity_names} 等主体，"
            f"并围绕 {keyword_names} 持续观察新的政策、产品发布、商业合作与风险信号。"
            "如果同一主题在多个来源重复出现，或出现明确的数据更新、监管动作、重要发布节点，"
            "应立即提升为新的候选发布选题，并同步补充上下游关键词。"
        )


_DEFAULT_ANALYZER: Optional[TrendAnalyzer] = None


def _get_default_analyzer() -> TrendAnalyzer:
    """Get singleton analyzer instance for module-level access.

    Returns:
        TrendAnalyzer: Shared analyzer instance.
    """
    global _DEFAULT_ANALYZER
    if _DEFAULT_ANALYZER is None:
        _DEFAULT_ANALYZER = TrendAnalyzer()
    return _DEFAULT_ANALYZER


def generate_trend_report(all_daily_text: List[str]) -> Dict[str, Any]:
    """Generate trend report for next-day monitoring.

    Args:
        all_daily_text: Daily text corpus.

    Returns:
        Dict[str, Any]: Structured trend report.
    """
    return _get_default_analyzer().generate_trend_report(all_daily_text=all_daily_text)


if __name__ == "__main__":
    sample_docs = [
        "OpenAI and Microsoft continue expanding enterprise AI workflow tooling. "
        "Teams are discussing governance, deployment, and agent orchestration.",
        "人工智能 内容运营 团队正在关注 微信 公众号 发布节奏、模型治理、数据来源和合规要求。"
        "如果同类主题持续升温，就应该进入次日监控关键词清单。",
    ]
    report = generate_trend_report(sample_docs)
    print(json.dumps(report, ensure_ascii=False, indent=2))
