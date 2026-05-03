"""OpenAI Moderation backend (omni-moderation-latest).

Public surface mirrors ``common.groq_client``: a single ``moderate_text(text)``
returning a ``ModerationResponse``. Selected via settings.MODERATION_PROVIDER.

OpenAI's taxonomy is finer-grained than ours; this module collapses related
categories into the seven names the rest of the system already uses.
"""

from __future__ import annotations

from django.conf import settings
from openai import OpenAI

from common.groq_client import ModerationResponse


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


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def moderate_text(text: str) -> ModerationResponse:
    """Classify ``text`` via OpenAI's omni-moderation endpoint.

    Re-raises SDK exceptions so the caller's retry/fail-open logic can
    handle network/rate-limit errors uniformly with the Groq path.
    """
    response = _get_client().moderations.create(
        model="omni-moderation-latest",
        input=text,
    )
    result = response.results[0]
    raw_cats = result.categories.model_dump() if hasattr(result.categories, "model_dump") else dict(result.categories)
    raw_scores = result.category_scores.model_dump() if hasattr(result.category_scores, "model_dump") else dict(result.category_scores)

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
