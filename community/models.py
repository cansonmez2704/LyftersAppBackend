import uuid, os
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.core.validators import FileExtensionValidator, MaxLengthValidator
from django.core.exceptions import ValidationError
from common.validators import validate_media_size, validate_real_content_type

POST_DESCRIPTION_MAX_LENGTH = 5000



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
MAX_COMMENT_DEPTH = 3 
def post_image_upload_path(instance, filename):
    """Dynamic upload path: community/posts/<post_uuid>/<filename>"""
    return f"community/posts/{instance.post.uuid}/{filename}"


def post_cover_upload_path(instance, filename):
    """Dynamic upload path: community/posts/<uuid>/cover/<filename>"""
    return f"community/posts/{instance.uuid}/cover/{filename}"


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------

class Post(models.Model):
   

    class Visibility(models.TextChoices):
        PUBLIC    = "public",    "Public"
        FOLLOWERS = "followers", "Followers Only"
        PRIVATE   = "private",   "Private"

    class PostType(models.TextChoices):
        GENERAL  = "general",  "General"
        WORKOUT  = "workout",  "Workout Share"
        PROGRESS = "progress", "Progress Update"
        QUESTION = "question", "Question"
        REVIEW   = "review",   "Review"

   
    uuid   = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="posts",
    )

   
    title       = models.CharField(max_length=300, blank=True, help_text="Optional headline for the post.")
    slug        = models.SlugField(max_length=350, blank=True, unique=True, help_text="Auto-generated from title.")
    description = models.TextField(
        help_text="Main body / caption of the post.",
        validators=[MaxLengthValidator(POST_DESCRIPTION_MAX_LENGTH)],
    )
    cover_image = models.ImageField(
        upload_to=post_cover_upload_path,
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(['jpg', 'jpeg', 'png', 'gif']),
            validate_media_size,
            validate_real_content_type,
        ],
        help_text="Optional single cover/header image.",
    )

    
    post_type  = models.CharField(
        max_length=20,
        choices=PostType.choices,
        default=PostType.GENERAL,
        db_index=True,
    )
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        db_index=True,
    )

    linked_workout = models.ForeignKey(
        "workouts.Workout",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_posts",
        help_text="Attach a workout to this post.",
    )

    
    likes_count    = models.PositiveIntegerField(default=0,editable=False)
    dislikes_count = models.PositiveIntegerField(default=0,editable=False)
    comments_count = models.PositiveIntegerField(default=0,editable=False)
   

    
    is_pinned   = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Post"
        verbose_name_plural = "Posts"
        indexes = [
            models.Index(fields=["is_deleted", "is_archived", "-created_at"]),
            models.Index(fields=["author", "-created_at"]),
            models.Index(fields=["visibility", "is_archived", "-created_at"]),
            models.Index(fields=["post_type", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        # 12 hex chars give ~2.8e14 possibilities — collision risk is far
        # below Post.slug's unique-constraint failure surface. 8 hex chars
        # (the old value) only covered 4.3e9 and did hit IntegrityError
        # → 500 in practice on large tables.
        if self.title and not self.slug:
            base_slug = slugify(self.title)
            suffix = str(self.uuid).replace("-", "")[:12]
            self.slug = f"{base_slug}-{suffix}" if base_slug else suffix
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title or f"Post #{self.uuid}"

    @property
    def reaction_score(self) -> int:
     
        return self.likes_count - self.dislikes_count


class PostMedia(models.Model):

    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    post       = models.ForeignKey("Post", on_delete=models.CASCADE, related_name="media")
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.IMAGE)
    
    file       = models.FileField(
        upload_to=post_image_upload_path,
        validators=[
            FileExtensionValidator(
            ['jpg', 'jpeg', 'png', 'gif', 'mp4', 'avi', 'mov', 'mkv', 'webm']
        ),
        validate_media_size, 
        validate_real_content_type
        ]
    )
    
    order      = models.PositiveSmallIntegerField(default=0, help_text="Display order within the post.")
    alt_text   = models.CharField(max_length=255, blank=True, help_text="Accessibility description.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        
        if not self.file:
            return

        ext = os.path.splitext(self.file.name)[1].lower()
        image_exts = ['.jpg', '.jpeg', '.png', '.gif']
        video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.webm']

        if self.media_type == self.MediaType.IMAGE:
            limit_bytes = settings.MAX_IMAGE_UPLOAD_SIZE
        else:
            limit_bytes = settings.MAX_VIDEO_UPLOAD_SIZE

        if self.file.size > limit_bytes:
            limit_mb = limit_bytes / (1024 * 1024)
            raise ValidationError(
                {"file": f"Maximum file size is {limit_mb:.0f} MB. "
                        f"Your file is {self.file.size / (1024 * 1024):.1f} MB."}
            )
        
    class Meta:
        indexes = [
            models.Index(fields=["post", "order"])
        ]
        verbose_name = "Post Media"
        verbose_name_plural = "Post Media"
        

    def __str__(self) -> str:
        return f"{self.get_media_type_display()} for Post {self.post_id} (#{self.order})"



class Comment(models.Model):
   
    
    post   = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        help_text="Set to create a reply to another comment.",
    )

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    body = models.TextField(help_text="The comment text.")
    depth = models.PositiveSmallIntegerField(default=0)

    likes_count    = models.PositiveIntegerField(default=0,editable=False)
    dislikes_count = models.PositiveIntegerField(default=0,editable=False)

    is_deleted = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Comment"
        verbose_name_plural = "Comments"
        indexes = [
            models.Index(fields=["post", "parent", "created_at"]),
            models.Index(fields=["author", "-created_at"]),
            models.Index(fields=["is_deleted", "-created_at"]),
            models.Index(fields=["post", "parent"]),
            models.Index(fields=["post", "-created_at"]),
        ]

    

    def clean(self):
        super().clean()
        if not self.body or not self.body.strip():
            raise ValidationError("Comment body cannot be empty.")
        if self.parent:
            if self.parent.post != self.post:
                raise ValidationError("Reply must belong to the same post as its parent.")
            if self.parent.is_deleted:
                raise ValidationError("Cannot reply to a deleted comment.")
            self.depth = self.parent.depth + 1
            if self.depth > MAX_COMMENT_DEPTH:
                raise ValidationError(f"Maximum reply depth is {MAX_COMMENT_DEPTH}.")
        else:
            self.depth = 0

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        
    def __str__(self) -> str:
        snippet = self.body[:60] + ("…" if len(self.body) > 60 else "")
        return f'Comment by {self.author} on "{self.post}": {snippet}'
        

    @property
    def is_reply(self) -> bool:
        return self.parent_id is not None

class ReactionType(models.TextChoices):
        LIKE    = "like",    "Like"
        DISLIKE = "dislike", "Dislike"

class PostReaction(models.Model):

    user          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_reactions")
    post          = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="reactions")
    reaction_type = models.CharField(max_length=10, choices=ReactionType.choices, db_index=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Post Reaction"
        verbose_name_plural = "Post Reactions"
        constraints = [
            models.UniqueConstraint(fields=["user", "post"], name="unique_post_reaction_per_user"),
        ]
        indexes = [
            models.Index(fields=["post", "reaction_type"]),
            models.Index(fields=["user", "-created_at"], name="postreaction_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} {self.reaction_type}d Post {self.post_id}"


class CommentReaction(models.Model):

    user          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comment_reactions")
    comment       = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="reactions")
    reaction_type = models.CharField(max_length=10, choices=ReactionType.choices, db_index=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Comment Reaction"
        verbose_name_plural = "Comment Reactions"
        constraints = [
            models.UniqueConstraint(fields=["user", "comment"], name="unique_comment_reaction_per_user"),
        ]
        indexes = [
            models.Index(fields=["comment", "reaction_type"]),
            models.Index(fields=["user", "-created_at"], name="commentreaction_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} {self.reaction_type}d Comment {self.comment_id}"
