"""Thin wrapper around the OpenAI Moderation endpoint.

Centralising the call here means tests only ever need to mock one symbol
(``moderate_text``), not the entire OpenAI SDK surface. It also gives us
one place to add transport-level concerns later (per-request timeouts,
circuit breaker, telemetry) without touching task code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings


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
        from openai import OpenAI

        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def moderate_text(text: str) -> ModerationResponse:
    """Call the OpenAI ``/v1/moderations`` endpoint.

    Re-raises the SDK's exceptions; the Celery task catches them to drive
    its retry/fail-open logic. Network/timeout errors must NOT be silently
    converted to "allowed" here — that decision belongs in the caller.
    """
    client = _get_client()
    response = client.moderations.create(
        model=settings.OPENAI_MODERATION_MODEL,
        input=text,
    )

    # The SDK returns a Pydantic-style object; the API guarantees at least
    # one result. Normalise into plain dicts so callers (and JSONField
    # storage) don't depend on SDK internals.
    result = response.results[0]
    return ModerationResponse(
        flagged=bool(result.flagged),
        categories=_to_dict(result.categories),
        category_scores=_to_dict(result.category_scores),
        model=response.model,
        raw=response.model_dump() if hasattr(response, "model_dump") else {},
    )


def _to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj.__dict__)
