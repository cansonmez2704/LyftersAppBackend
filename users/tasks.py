"""
Celery tasks for the users app.
- Avatar resizing after upload
- Profile search vector rebuilds
- Bulk token blacklisting after password change
"""
import logging
from io import BytesIO

from celery import shared_task
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def resize_avatar(self, profile_id, max_size=400):
    """Resize an uploaded avatar to max_size × max_size pixels."""
    try:
        from PIL import Image
        from .models import UserProfile

        profile = UserProfile.objects.get(pk=profile_id)
        if not profile.avatar:
            return "No avatar to resize"

        img = Image.open(profile.avatar)

        if img.width <= max_size and img.height <= max_size:
            return "Avatar already within size limits"

        img.thumbnail((max_size, max_size), Image.LANCZOS)

        buffer = BytesIO()
        img_format = img.format or "JPEG"
        img.save(buffer, format=img_format, quality=85)
        buffer.seek(0)

        # Save back without triggering signals again
        file_name = profile.avatar.name.split("/")[-1]
        profile.avatar.save(file_name, ContentFile(buffer.read()), save=False)
        UserProfile.objects.filter(pk=profile_id).update(avatar=profile.avatar.name)

        return f"Resized avatar for profile {profile_id} to {max_size}x{max_size}"

    except UserProfile.DoesNotExist:
        return f"Profile {profile_id} not found"
    except Exception as exc:
        logger.error(f"Avatar resize failed for profile {profile_id}: {exc}")
        raise self.retry(exc=exc)


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
        logger.error(f"Search vector rebuild failed for user {user_pk}: {exc}")
        raise self.retry(exc=exc)


@shared_task
def bulk_blacklist_tokens(user_id):
    """Blacklist all outstanding JWT tokens for a user after password change."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    tokens = OutstandingToken.objects.filter(user_id=user_id)
    created_count = 0
    for token in tokens:
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            created_count += 1

    return f"Blacklisted {created_count} tokens for user {user_id}"
