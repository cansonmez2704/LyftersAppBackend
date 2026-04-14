"""
Celery tasks for the community app.
- Post media processing (thumbnail generation)
- Purge soft-deleted posts (30+ days old)
- Purge soft-deleted comments (30+ days old)
"""
import logging
from io import BytesIO
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

PURGE_AFTER_DAYS = 30


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
