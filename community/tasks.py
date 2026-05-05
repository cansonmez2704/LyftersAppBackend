"""
Celery tasks for the community app.
- Post media processing (thumbnail generation)
- Content moderation via OpenAI (posts + comments)
- Purge soft-deleted posts (30+ days old)
- Purge soft-deleted comments (30+ days old)
"""

import logging
from io import BytesIO
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

PURGE_AFTER_DAYS = 30


# ---------------------------------------------------------------------------
# Debounce helper
# ---------------------------------------------------------------------------

def dispatch_moderation(content_type_id: int, object_id: int) -> None:
    """Schedule ``moderate_content`` with a 3-second countdown + debounce.

    When a user edits a post title ten times in a row, this fires only one
    effective moderation API call — not ten.  Each dispatch stamps a
    monotonic ``dispatch_ts`` into the cache.  The task compares its own
    timestamp against the latest one; if a newer dispatch superseded it,
    the task exits early.

    **Must be called inside** ``transaction.on_commit()`` — this function
    does NOT wrap itself in one.
    """
    import time

    ts = time.time()
    try:
        from django.core.cache import cache
        cache.set(f"mod_dispatch:{content_type_id}:{object_id}", str(ts), timeout=60)
    except Exception:
        ts = None  # Cache down — fall through without debounce.

    kwargs = {"dispatch_ts": ts} if ts is not None else {}
    moderate_content.apply_async(
        args=[content_type_id, object_id],
        kwargs=kwargs,
        countdown=3,
    )


# OpenAI SDK exception classes are loaded lazily in the task body so that
# importing tasks.py does not require the openai package at module-import
# time (e.g. during makemigrations or when running unrelated tests).
def _moderation_retry_exceptions():
    try:
        from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError

        return (APIConnectionError, APIError, APITimeoutError, RateLimitError, TimeoutError)
    except ImportError:
        return (TimeoutError,)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def process_post_media(self, post_media_id):
    """Generate a thumbnail for uploaded image media."""
    try:
        from PIL import Image
        from .models import PostMedia

        media = PostMedia.objects.get(pk=post_media_id)

        # Only process images, skip videos
        if media.media_type != PostMedia.MediaType.IMAGE:
            return f"Skipped non-image media {post_media_id}"

        if not media.file:
            return f"No file for media {post_media_id}"

        img = Image.open(media.file)
        max_dimension = 1920

        if img.width <= max_dimension and img.height <= max_dimension:
            return f"Media {post_media_id} already within size limits"

        # Resize keeping aspect ratio
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        buffer = BytesIO()
        img_format = img.format or "JPEG"
        img.save(buffer, format=img_format, quality=85)
        buffer.seek(0)

        file_name = media.file.name.split("/")[-1]
        media.file.save(file_name, ContentFile(buffer.read()), save=False)
        PostMedia.objects.filter(pk=post_media_id).update(file=media.file.name)

        return f"Processed media {post_media_id}"

    except PostMedia.DoesNotExist:
        return f"PostMedia {post_media_id} not found"
    except Exception as exc:
        logger.error(f"Media processing failed for {post_media_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def moderate_content(self, content_type_id: int, object_id: int, dispatch_ts=None):
    """Screen a Moderatable instance against the OpenAI moderation endpoint.

    Outcomes:
      * Allowed → status=PUBLISHED.
      * Flagged → status=REJECTED. We log raw category_scores so we can
        re-tune thresholds later from historical data.
      * API errors → exponential-backoff retries (handled by Celery via
        autoretry_for). On final failure we fall open: status=PUBLISHED
        but requires_manual_review=True so an admin sees it. Set
        ``MODERATION_FAIL_OPEN=False`` to fail-closed instead.
    """
    # --- Debounce: skip if a newer dispatch has superseded this one -------
    if dispatch_ts is not None:
        try:
            from django.core.cache import cache
            latest = cache.get(f"mod_dispatch:{content_type_id}:{object_id}")
            if latest and float(latest) > dispatch_ts:
                logger.info(
                    "moderate_content: debounced %s#%s (superseded by newer edit)",
                    content_type_id, object_id,
                )
                return "debounced"
        except Exception:
            pass  # Cache unavailable — run moderation anyway.
    from common.moderation import ModerationDecision, ModerationResult, ModerationStatus
    from common import openai_client

    try:
        ct = ContentType.objects.get_for_id(content_type_id)
        obj = ct.get_object_for_this_type(pk=object_id)
    except Exception:
        # The content disappeared between dispatch and execution (deleted,
        # rolled back). Nothing to moderate — drop silently rather than
        # retry.
        logger.warning(
            "moderate_content: target %s#%s not found", content_type_id, object_id
        )
        return "target_missing"

    text = obj.get_moderation_text()
    if not text.strip():
        # Nothing to screen (e.g. a post with only media). Auto-allow.
        _finalise(obj, ModerationStatus.PUBLISHED)
        return "empty_text"

    try:
        response = openai_client.moderate_text(text)
    except _moderation_retry_exceptions() as exc:
        # Let Celery's autoretry_for handle the retry with backoff. When
        # max_retries is hit, this re-raises and lands in on_failure-style
        # handling below (we use the task's `request.retries` to detect
        # exhaustion since Celery re-raises the original exception).
        if self.request.retries >= self.max_retries:
            logger.error(
                "moderate_content: retries exhausted for %s#%s (%s)",
                content_type_id, object_id, exc,
            )
            _finalise_after_outage(obj, str(exc))
            return "fail_open"
        raise

    decision = (
        ModerationDecision.BLOCK if response.flagged else ModerationDecision.ALLOW
    )
    ModerationResult.objects.create(
        content_type=ct,
        object_id=obj.pk,
        decision=decision,
        flagged=response.flagged,
        categories=response.categories,
        category_scores=response.category_scores,
        model_name=response.model,
    )

    new_status = (
        ModerationStatus.REJECTED if response.flagged else ModerationStatus.PUBLISHED
    )
    _finalise(obj, new_status)
    return decision


def _finalise(obj, status):
    """Write moderation_status + moderated_at without touching unrelated
    fields. ``update_fields`` is critical: a plain ``obj.save()`` would
    bump ``updated_at`` and risk overwriting concurrent edits to the post
    body.
    """
    type(obj).objects.filter(pk=obj.pk).update(
        moderation_status=status,
        moderated_at=timezone.now(),
    )


def _finalise_after_outage(obj, error_message: str):
    """Fail-open path: OpenAI was unreachable past our retry budget.

    Two writes — one to flip status, one append-only audit row — so the
    admin dashboard can surface "moderation outage" cohorts separately
    from genuine API allow/block decisions.
    """
    from common.moderation import ModerationDecision, ModerationResult, ModerationStatus

    if settings.MODERATION_FAIL_OPEN:
        type(obj).objects.filter(pk=obj.pk).update(
            moderation_status=ModerationStatus.PUBLISHED,
            requires_manual_review=True,
            moderated_at=timezone.now(),
        )
    else:
        type(obj).objects.filter(pk=obj.pk).update(
            moderation_status=ModerationStatus.ERROR,
            moderated_at=timezone.now(),
        )

    ModerationResult.objects.create(
        content_type=ContentType.objects.get_for_model(type(obj)),
        object_id=obj.pk,
        decision=ModerationDecision.MANUAL_REVIEW,
        flagged=False,
        error=error_message[:8000],
    )


@shared_task
def purge_soft_deleted_posts():
    """Hard-delete posts that have been soft-deleted for more than 30 days.
    
    Also cleans up associated S3 media files via Django's CASCADE.
    """
    from .models import Post

    cutoff = timezone.now() - timedelta(days=PURGE_AFTER_DAYS)
    queryset = Post.objects.filter(is_deleted=True, updated_at__lte=cutoff)

    count = queryset.count()
    if count == 0:
        return "No posts to purge"

    # Delete associated media files from storage before hard delete
    for post in queryset.prefetch_related("media"):
        for media in post.media.all():
            if media.file:
                media.file.delete(save=False)
        if post.cover_image:
            post.cover_image.delete(save=False)

    # CASCADE handles PostMedia, Comments, Reactions
    queryset.delete()

    logger.info(f"Purged {count} soft-deleted posts older than {PURGE_AFTER_DAYS} days")
    return f"Purged {count} posts"


@shared_task
def purge_soft_deleted_comments():
    """Hard-delete comments that have been soft-deleted for more than 30 days."""
    from .models import Comment

    cutoff = timezone.now() - timedelta(days=PURGE_AFTER_DAYS)
    queryset = Comment.objects.filter(is_deleted=True, updated_at__lte=cutoff)

    count = queryset.count()
    if count == 0:
        return "No comments to purge"

    # CASCADE handles CommentReaction
    queryset.delete()

    logger.info(f"Purged {count} soft-deleted comments older than {PURGE_AFTER_DAYS} days")
    return f"Purged {count} comments"
