"""
Celery tasks for the users app.
- Profile search vector rebuilds
- Bulk token blacklisting after password change

Avatar processing is intentionally NOT here: it happens synchronously inside
the request handler (see `users.serializers.process_avatar_upload`) so that
EXIF stripping, resizing, and WebP conversion are guaranteed before a byte
ever lands in S3.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def rebuild_profile_search_vector(self, user_pk):
    """Rebuild the full-text search vector for a user's profile."""
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE users_userprofile
                SET search_vector =
                    setweight(to_tsvector('english', COALESCE(u.username, '')), 'A') ||
                    setweight(to_tsvector('english', COALESCE(users_userprofile.bio, '')), 'B')
                FROM users_user u
                WHERE users_userprofile.user_id = u.id
                  AND users_userprofile.user_id = %s
            """, [user_pk])

        return f"Search vector rebuilt for user {user_pk}"

    except Exception as exc:
        logger.exception("Search vector rebuild failed for user %s", user_pk)
        raise self.retry(exc=exc)


def blacklist_user_tokens(user_id):
    """Blacklist all outstanding JWT tokens for a user.

    Runs synchronously so the caller (e.g. ChangePasswordView) can rely on
    revocation having happened before returning to the client — the old
    access token becomes unusable immediately instead of up to one access
    lifetime later.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    outstanding = OutstandingToken.objects.filter(user_id=user_id)
    already_blacklisted = set(
        BlacklistedToken.objects.filter(token__in=outstanding)
        .values_list("token_id", flat=True)
    )
    to_create = [
        BlacklistedToken(token=token)
        for token in outstanding
        if token.pk not in already_blacklisted
    ]
    BlacklistedToken.objects.bulk_create(to_create, ignore_conflicts=True)
    return len(to_create)


@shared_task
def bulk_blacklist_tokens(user_id):
    """Async wrapper around blacklist_user_tokens for scheduled cleanup."""
    created = blacklist_user_tokens(user_id)
    return f"Blacklisted {created} tokens for user {user_id}"
