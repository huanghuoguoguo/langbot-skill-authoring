from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


EXPLICIT_DEPOSITION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bmake this (?:a )?skill\b",
        r"\bsave this (?:as a )?(?:workflow|skill|runbook)\b",
        r"\blearn this (?:workflow|procedure|process)\b",
        r"\bremember this (?:workflow|procedure|process)\b",
        r"\bdeposit this\b",
        r"沉淀",
        r"记住(?:这个|这套)?(?:流程|步骤|做法|办法)",
        r"保存(?:这个|这套)?(?:流程|步骤|做法|办法)",
        r"以后(?:都|就)?(?:这样|按这个|按照这个)",
        r"下次(?:也|就)?(?:这样|按这个|按照这个)",
        r"作为(?:一个)?skill",
    ]
]

PROCEDURAL_MARKERS = {
    "步骤",
    "流程",
    "操作",
    "排查",
    "调试",
    "验证",
    "复现",
    "配置",
    "安装",
    "部署",
    "运行",
    "执行",
    "检查",
    "回归",
    "测试",
    "step",
    "workflow",
    "procedure",
    "runbook",
    "debug",
    "troubleshoot",
    "verify",
    "install",
    "configure",
    "deploy",
    "pytest",
    "pnpm",
    "uv ",
    "register_skill",
    "skill.md",
}

ONE_OFF_MARKERS = {
    "今天",
    "明天",
    "昨天",
    "今晚",
    "刚才",
    "会议",
    "meeting",
    "tomorrow",
    "yesterday",
    "today",
    "tonight",
}

META_ONLY_MARKERS = {
    "怎么实现",
    "讲讲",
    "解释",
    "为什么",
    "what is",
    "how does",
}


@dataclass(frozen=True)
class PostResponseDecision:
    should_create: bool
    confidence: float
    reason: str
    explicit_request: bool = False
    procedural_score: int = 0
    source_excerpt: str = ""
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_create": self.should_create,
            "confidence": self.confidence,
            "reason": self.reason,
            "explicit_request": self.explicit_request,
            "procedural_score": self.procedural_score,
            "title": self.title,
        }


def decide_post_response_candidate(
    *,
    user_text: str,
    response_text: str,
    funcs_called: list[str] | None = None,
    min_confidence: float = 0.72,
    explicit_only: bool = False,
    max_source_chars: int = 6000,
) -> PostResponseDecision:
    """Classify whether a completed turn is worth a Skill Authoring candidate."""

    user_text = _clean_text(user_text)
    response_text = _clean_text(response_text)
    funcs_called = [str(item) for item in funcs_called or [] if str(item).strip()]
    combined = "\n".join(part for part in [user_text, response_text, " ".join(funcs_called)] if part)

    if not combined.strip():
        return PostResponseDecision(False, 0.0, "empty turn")
    if len(response_text) < 80 and not _has_explicit_deposition(user_text):
        return PostResponseDecision(False, 0.0, "assistant response too short")

    explicit_request = _has_explicit_deposition(user_text)
    procedural_score = _procedural_score(combined, funcs_called)
    confidence = _confidence(
        explicit_request=explicit_request,
        procedural_score=procedural_score,
        text=combined,
    )
    if _looks_meta_only(user_text, response_text) and not explicit_request:
        confidence = min(confidence, 0.45)
    if explicit_only and not explicit_request:
        return PostResponseDecision(
            False,
            confidence,
            "explicit deposition phrase required",
            explicit_request=explicit_request,
            procedural_score=procedural_score,
            source_excerpt=_source_excerpt(user_text, response_text, funcs_called, max_source_chars),
            title=_title_from_text(user_text, response_text),
        )
    if confidence < min_confidence:
        return PostResponseDecision(
            False,
            confidence,
            f"confidence below threshold {min_confidence:.2f}",
            explicit_request=explicit_request,
            procedural_score=procedural_score,
            source_excerpt=_source_excerpt(user_text, response_text, funcs_called, max_source_chars),
            title=_title_from_text(user_text, response_text),
        )

    reason = "explicit user deposition request" if explicit_request else "reusable procedural workflow"
    return PostResponseDecision(
        True,
        confidence,
        reason,
        explicit_request=explicit_request,
        procedural_score=procedural_score,
        source_excerpt=_source_excerpt(user_text, response_text, funcs_called, max_source_chars),
        title=_title_from_text(user_text, response_text),
    )


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _has_explicit_deposition(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in EXPLICIT_DEPOSITION_PATTERNS)


def _procedural_score(text: str, funcs_called: list[str]) -> int:
    lowered = text.lower()
    score = 0
    for marker in PROCEDURAL_MARKERS:
        if marker.lower() in lowered:
            score += 1
    score += min(len(funcs_called), 3)
    score += len(re.findall(r"(?:^|\n|\s)(?:step\s*\d+|\d+\.)", text, flags=re.IGNORECASE))
    score += len(re.findall(r"(?:首先|然后|接着|最后|first|then|next|finally)", lowered))
    return score


def _confidence(*, explicit_request: bool, procedural_score: int, text: str) -> float:
    if explicit_request:
        base = 0.76
    else:
        base = 0.22
    confidence = base + min(procedural_score * 0.08, 0.45)
    lowered = text.lower()
    if any(marker in lowered for marker in ONE_OFF_MARKERS):
        confidence -= 0.12
    if len(text) > 800:
        confidence += 0.05
    return max(0.0, min(confidence, 0.98))


def _looks_meta_only(user_text: str, response_text: str) -> bool:
    lowered_user = user_text.lower()
    if not any(marker in lowered_user for marker in META_ONLY_MARKERS):
        return False
    lowered_response = response_text.lower()
    return not any(marker in lowered_response for marker in ["1.", "step", "步骤", "pytest", "pnpm", "uv "])


def _source_excerpt(
    user_text: str,
    response_text: str,
    funcs_called: list[str],
    max_source_chars: int,
) -> str:
    sections = [
        "# User Message\n" + (user_text or "(empty)"),
        "# Assistant Response\n" + (response_text or "(empty)"),
    ]
    if funcs_called:
        sections.append("# Functions Called\n" + "\n".join(f"- {name}" for name in funcs_called))
    source = "\n\n".join(sections).strip()
    if max_source_chars <= 0:
        return source
    if len(source) <= max_source_chars:
        return source
    return source[: max_source_chars - 1].rstrip() + "\n"


def _title_from_text(user_text: str, response_text: str) -> str:
    for source in [user_text, response_text]:
        cleaned = _clean_title(source)
        if cleaned:
            return cleaned
    return "Post-response learned workflow"


def _clean_title(text: str) -> str:
    cleaned = _clean_text(text)
    cleaned = re.sub(r"^(请|帮我|麻烦|please)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(沉淀一下|沉淀|记住这个流程|保存这个流程|make this.*)$", "", cleaned, flags=re.IGNORECASE).strip(" ，,。.")
    if not cleaned:
        return ""
    return cleaned[:80].rstrip(" ，,。.")
