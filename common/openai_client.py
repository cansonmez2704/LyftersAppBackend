"""OpenAI-backed content moderation.

Calls the ``omni-moderation-latest`` endpoint to classify user-submitted
text against a fixed safety taxonomy. The endpoint is free and supports
multilingual input (Turkish, etc.); OpenAI's category set is finer-grained
than ours, so we collapse related keys into the seven names the rest of
the system already uses.

Public surface: a single ``moderate_text(text) -> ModerationResponse``.
The Celery task, audit log, and tests don't care about the provider —
swapping clients later only touches this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from openai import OpenAI


# Fixed taxonomy. Adding a new category is a deliberate change — downstream
# audit rows use these names as JSON keys.
_CATEGORIES = (
    "hate",
    "harassment",
    "sexual",
    "sexual_minors",
    "violence",
    "self_harm",
    "illegal",
)

# Map our taxonomy to one or more OpenAI category keys. A category is True
# if ANY of the mapped OpenAI categories is True; the score is the max.
_CATEGORY_MAP = {
    "hate":          ("hate", "hate/threatening"),
    "harassment":    ("harassment", "harassment/threatening"),
    "sexual":        ("sexual",),
    "sexual_minors": ("sexual/minors",),
    "violence":      ("violence", "violence/graphic"),
    "self_harm":     ("self-harm", "self-harm/instructions", "self-harm/intent"),
    "illegal":       ("illicit", "illicit/violent"),
}


@dataclass(frozen=True)
class ModerationResponse:
    flagged: bool
    categories: dict[str, Any]
    category_scores: dict[str, Any]
    model: str
    raw: dict[str, Any]


_client = None


def _get_client():
    """Lazy singleton — avoids constructing the SDK client at import time
    (so settings can be mutated in tests, and we don't crash imports when
    OPENAI_API_KEY is absent in unrelated environments).
    """
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def moderate_text(text: str) -> ModerationResponse:
    """Classify ``text`` via OpenAI's omni-moderation endpoint.

    Re-raises the SDK's exceptions; the Celery task catches them to drive
    its retry/fail-open logic. Network/timeout errors must NOT be silently
    converted to "allowed" here — that decision belongs in the caller.
    """
    response = _get_client().moderations.create(
        model="omni-moderation-latest",
        input=text,
        timeout=settings.OPENAI_MODERATION_TIMEOUT,
    )
    result = response.results[0]
    raw_cats = (
        result.categories.model_dump()
        if hasattr(result.categories, "model_dump")
        else dict(result.categories)
    )
    raw_scores = (
        result.category_scores.model_dump()
        if hasattr(result.category_scores, "model_dump")
        else dict(result.category_scores)
    )

    categories = {
        ours: any(raw_cats.get(k, False) for k in keys)
        for ours, keys in _CATEGORY_MAP.items()
    }
    scores = {
        ours: max((float(raw_scores.get(k, 0.0)) for k in keys), default=0.0)
        for ours, keys in _CATEGORY_MAP.items()
    }
    flagged = bool(result.flagged) or any(categories.values())

    return ModerationResponse(
        flagged=flagged,
        categories=categories,
        category_scores=scores,
        model=response.model,
        raw=response.model_dump() if hasattr(response, "model_dump") else {},
    )


def reset_client() -> None:
    """Discard the cached OpenAI client.

    Call this after rotating ``OPENAI_API_KEY`` at runtime, or inside test
    ``setUp`` / ``tearDown`` so ``@override_settings`` takes effect.
    """
    global _client
    _client = None
