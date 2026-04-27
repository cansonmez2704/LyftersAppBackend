"""Generic content moderation primitives.

Used by any model whose user-supplied text needs to be screened by the
OpenAI Moderation API before becoming visible to other users. Today that's
``community.Post`` and ``community.Comment``; tomorrow it could be bios,
DMs, group descriptions, etc. — they only need to subclass ``Moderatable``
and implement ``get_moderation_text``.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ModerationStatus(models.TextChoices):
    PENDING   = "pending",   "Pending review"
    PUBLISHED = "published", "Published"
    REJECTED  = "rejected",  "Rejected"
    ERROR     = "error",     "Moderation error"


class ModerationDecision(models.TextChoices):
    ALLOW         = "allow",         "Allow"
    BLOCK         = "block",         "Block"
    MANUAL_REVIEW = "manual_review", "Manual review"


class Moderatable(models.Model):
    """Mixin: adds a moderation lifecycle to any model.

    Subclasses must implement ``get_moderation_text`` so the Celery task
    knows what string to send to OpenAI. Returning an empty string is
    treated as auto-allow (nothing to screen).
    """

    moderation_status = models.CharField(
        max_length=16,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
        db_index=True,
    )
    requires_manual_review = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Set when the OpenAI call failed all retries and we fell open.",
    )
    moderated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def get_moderation_text(self) -> str:  # pragma: no cover — abstract
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_moderation_text()"
        )


class ModerationResult(models.Model):
    """Append-only log of every moderation API call.

    Storing raw ``category_scores`` lets us re-tune thresholds later without
    re-spending on API calls — e.g. "show me everything we approved where
    the hate score was > 0.4" becomes a single SQL query.
    """

    content_type   = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id      = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    decision         = models.CharField(max_length=20, choices=ModerationDecision.choices)
    flagged          = models.BooleanField(default=False)
    categories       = models.JSONField(default=dict, blank=True)
    category_scores  = models.JSONField(default=dict, blank=True)

    model_name = models.CharField(max_length=64, blank=True)
    error      = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Moderation result"
        verbose_name_plural = "Moderation results"
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["flagged", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.content_type} #{self.object_id} → {self.decision}"
