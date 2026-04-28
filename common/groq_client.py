"""Groq-backed content moderation.

Calls a general-purpose LLM on Groq (default ``llama-3.3-70b-versatile``)
with a strict JSON-mode prompt to classify user-submitted text against a
fixed safety taxonomy. We use a general LLM rather than a dedicated
"guard" model because Groq has decommissioned its Llama Guard line at
least twice; a general model with a structured prompt is decoupled from
provider product churn and handles multilingual input (Turkish, etc.)
better than English-centric safety classifiers.

The public surface (``moderate_text(text) -> ModerationResponse``) is
unchanged so the Celery task, audit log, and tests don't care which
provider backs it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from groq import Groq

logger = logging.getLogger(__name__)


# Fixed taxonomy. Adding a new category is a deliberate change — the
# system prompt enumerates these names verbatim, and downstream audit
# rows use them as JSON keys.
_CATEGORIES = (
    "hate",
    "harassment",
    "sexual",
    "sexual_minors",
    "violence",
    "self_harm",
    "illegal",
)

_SYSTEM_PROMPT = (
    "You are a content moderation classifier for a fitness social network. "
    "Classify the user's message against this safety taxonomy:\n"
    "- hate: slurs, dehumanising language, attacks on protected groups (race, "
    "religion, gender, sexual orientation, nationality, etc.)\n"
    "- harassment: personal insults, bullying, attacks on a person or their "
    "family (including profanity directed at someone, e.g. insulting their "
    "mother/family)\n"
    "- sexual: explicit sexual content\n"
    "- sexual_minors: any sexual content involving people under 18\n"
    "- violence: threats, incitement, graphic violence\n"
    "- self_harm: encouragement or instructions for self-injury or suicide\n"
    "- illegal: instructions for crimes, weapons, drug manufacture, etc.\n\n"
    "Apply the same standards regardless of language (Turkish, English, etc.). "
    "Profanity targeting another person or their family is harassment even if "
    "casual. Profanity in casual self-expression with no target is NOT a "
    "violation by itself.\n\n"
    "Respond ONLY with a JSON object of this exact shape:\n"
    "{\n"
    '  "flagged": <boolean>,\n'
    '  "categories": {"hate": <bool>, "harassment": <bool>, "sexual": <bool>, '
    '"sexual_minors": <bool>, "violence": <bool>, "self_harm": <bool>, '
    '"illegal": <bool>},\n'
    '  "confidence": <float between 0 and 1>\n'
    "}\n"
    "Set flagged=true if any category is true. No prose, no markdown."
)


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
    GROQ_API_KEY is absent in unrelated environments).
    """
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def moderate_text(text: str) -> ModerationResponse:
    """Classify ``text`` via Groq.

    Re-raises the SDK's exceptions; the Celery task catches them to drive
    its retry/fail-open logic. Network/timeout errors must NOT be silently
    converted to "allowed" here — that decision belongs in the caller.
    """
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.GROQ_MODERATION_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        max_tokens=256,
        response_format={"type": "json_object"},
    )

    raw_output = response.choices[0].message.content or "{}"
    flagged, categories, scores = _parse_classifier_output(raw_output)

    return ModerationResponse(
        flagged=flagged,
        categories=categories,
        category_scores=scores,
        model=response.model,
        raw=response.model_dump() if hasattr(response, "model_dump") else {},
    )


def reset_client() -> None:
    """Discard the cached Groq client.

    Call this after rotating ``GROQ_API_KEY`` at runtime, or inside test
    ``setUp`` / ``tearDown`` so ``@override_settings`` takes effect.
    """
    global _client
    _client = None


def _parse_classifier_output(raw: str) -> tuple[bool, dict[str, bool], dict[str, float]]:
    """Defensive parse: bad JSON or a missing field must not crash the
    task — callers treat parse failure as ``flagged=False`` so the
    fail-open path stays consistent with transport errors.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("groq_client: classifier returned non-JSON output: %r", raw[:200])
        return False, {name: False for name in _CATEGORIES}, {name: 0.0 for name in _CATEGORIES}

    raw_categories = data.get("categories") or {}
    categories = {name: bool(raw_categories.get(name, False)) for name in _CATEGORIES}

    confidence = data.get("confidence")
    try:
        score = float(confidence) if confidence is not None else 1.0
    except (TypeError, ValueError):
        score = 1.0
    scores = {name: (score if categories[name] else 0.0) for name in _CATEGORIES}

    flagged = bool(data.get("flagged")) or any(categories.values())
    return flagged, categories, scores
