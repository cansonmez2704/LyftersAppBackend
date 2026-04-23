import uuid
import pathlib
import logging
from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import MaxValueValidator, MinValueValidator, FileExtensionValidator
from django.db import models, transaction, IntegrityError
from django.db.models import Q, F
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _ip_from_request(request) -> str:
    """Best-effort client IP for audit logs; mirrors views._client_ip."""
    if request is None:
        return "-"
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") if hasattr(request, "META") else ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "-") if hasattr(request, "META") else "-"

# ==========================================
# MANAGERS
# ==========================================

class CustomUserManager(UserManager):
    """Overrides default behavior to strictly enforce email collection upon registration."""

    def create_user(self, username: str, email: str | None = None, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("Email is required for user registration.")
        if not username or not str(username).strip():
            raise ValueError("Username is required and cannot be empty.")
            
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)

        try:
            user.save(using=self._db)
            logger.info("Successfully provisioned user: %s", username)
            return user
        except IntegrityError as e:
            logger.warning("Failed to provision user %s: IntegrityError. Details: %s", username, e)
            raise  

    def create_superuser(self, username: str, email: str | None = None, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        logger.debug("Attempting to provision superuser: %s", username)
        return self.create_user(username, email, password, **extra_fields)


# ==========================================
# MEDIA HELPERS
# ==========================================

def avatar_upload_path(instance, filename: str) -> str:
    """
    Generates a secure, randomized path for S3 uploads.
    Uses the User UUID to prevent IDOR, and a random string to prevent caching and storage bloat.
    """
    ext = pathlib.Path(filename).suffix.lower()
    return f"avatars/{instance.user.uuid}/{uuid.uuid4().hex}{ext}"


# ==========================================
# MODELS
# ==========================================

class User(AbstractUser):
    objects = CustomUserManager()

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text="Public-facing identifier. Never expose the integer PK.",
    )
    email = models.EmailField(
        "email address",
        unique=True,
        help_text="Unique per account. Used for recovery flows and duplicate-account prevention.",
    )

    class Meta(AbstractUser.Meta):
        pass

    def __str__(self) -> str:
        return self.username


class UserProfile(models.Model):
    class GenderChoices(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    
    avatar = models.ImageField(
        upload_to=avatar_upload_path,
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])]
    )
    
    is_public = models.BooleanField(default=True)
    followers_count = models.PositiveIntegerField(default=0, editable=False)
    following_count = models.PositiveIntegerField(default=0, editable=False)
    
    bio = models.CharField(max_length=2000, blank=True, default="")
    height = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(50), MaxValueValidator(300)], help_text="Height in cm."
    )
    weight = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(500)], help_text="Weight in kg."
    )
    gender = models.CharField(max_length=1, choices=GenderChoices.choices, blank=True, default="")
    birth_date = models.DateField(null=True, blank=True)
    
    search_vector = SearchVectorField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
   
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        indexes = [
            GinIndex(fields=["search_vector"], name="userprofile_search_gin"),
            models.Index(fields=["user"], name="userprofile_public_idx", condition=Q(is_public=True)),
        ]
   
    def __str__(self) -> str:
        return f"Profile of {self.user}"
   
    @property
    def avatar_url(self) -> str:
        if self.avatar and hasattr(self.avatar, "url"):
            return self.avatar.url
        # Optional: update to staticfiles if using a CDN for static assets
        return "/static/images/default-avatar.png"


class UserFollower(models.Model):
    class FollowStatus(models.TextChoices):
        PENDING = "P", "Pending"
        ACCEPTED = "A", "Accepted"

    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="outgoing_followers")
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="incoming_followers")
    
    status = models.CharField(max_length=1, choices=FollowStatus.choices, default=FollowStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Follower"
        verbose_name_plural = "User Followers"
        indexes = [
            models.Index(fields=["from_user", "status"]),
            models.Index(fields=["to_user", "status"]),
            models.Index(fields=["to_user", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["from_user", "to_user"], name="unique_user_follow"),
            models.CheckConstraint(check=~Q(from_user=F("to_user")), name="prevent_self_follow"),
        ]

    def __str__(self) -> str:
        return f"{self.from_user} follows {self.to_user} ({self.get_status_display()})"


# ==========================================
# SIGNALS
# ==========================================

SEARCH_RELEVANT_USER_FIELDS = frozenset({"username"})
SEARCH_RELEVANT_PROFILE_FIELDS = frozenset({"bio"})

@receiver(post_save, sender=User)
def create_user_profile(sender, instance: User, created: bool, update_fields, **kwargs):
    if created:
        transaction.on_commit(lambda: UserProfile.objects.get_or_create(user=instance))
        return

    changed = set(update_fields or [])
    if not update_fields or changed & SEARCH_RELEVANT_USER_FIELDS:
        from users.tasks import rebuild_profile_search_vector
        transaction.on_commit(lambda: rebuild_profile_search_vector.delay(instance.pk))

@receiver(post_save, sender=UserProfile)
def update_profile_search_vector(sender, instance: UserProfile, created: bool, update_fields, **kwargs):
    changed = set(update_fields or [])
    if not created and update_fields and not (changed & SEARCH_RELEVANT_PROFILE_FIELDS):
        return

    from users.tasks import rebuild_profile_search_vector
    transaction.on_commit(lambda: rebuild_profile_search_vector.delay(instance.user_id))


# ------------------------------------------
# Orphan avatar cleanup
# When a user replaces or deletes their avatar, the previous file must be
# removed from storage (S3 in production) so we do not accumulate orphaned
# blobs that cost money and retain user images indefinitely.
# ------------------------------------------

@receiver(pre_save, sender=UserProfile)
def delete_old_avatar_on_change(sender, instance: UserProfile, **kwargs):
    if not instance.pk:
        return

    try:
        previous = UserProfile.objects.only("avatar").get(pk=instance.pk)
    except UserProfile.DoesNotExist:
        return

    old_file = previous.avatar
    new_file = instance.avatar

    if not old_file or not old_file.name:
        return

    if new_file and old_file.name == getattr(new_file, "name", None):
        return

    try:
        old_file.delete(save=False)
    except Exception:
        logger.exception("Failed to delete previous avatar for profile %s", instance.pk)


@receiver(post_delete, sender=UserProfile)
def delete_avatar_on_profile_delete(sender, instance: UserProfile, **kwargs):
    if instance.avatar and instance.avatar.name:
        try:
            instance.avatar.delete(save=False)
        except Exception:
            logger.exception("Failed to delete avatar for deleted profile %s", instance.pk)


# ------------------------------------------
# Auth audit log
# Hook Django's built-in auth signals so every login / logout / failed login
# is recorded regardless of which library did the authentication
# (dj_rest_auth, admin, allauth). Tail these with e.g.
#     journalctl -u gunicorn | grep 'auth\.'
# or ingest via your SIEM of choice.
# ------------------------------------------

@receiver(user_logged_in)
def _audit_user_logged_in(sender, request, user, **kwargs):
    logger.info(
        "auth.login user_id=%s username=%s ip=%s",
        getattr(user, "id", "-"),
        getattr(user, "username", "-"),
        _ip_from_request(request),
    )


@receiver(user_logged_out)
def _audit_user_logged_out(sender, request, user, **kwargs):
    logger.info(
        "auth.logout_signal user_id=%s ip=%s",
        getattr(user, "id", "-") if user else "-",
        _ip_from_request(request),
    )


@receiver(user_login_failed)
def _audit_login_failed(sender, credentials, request=None, **kwargs):
    # Deliberately do NOT log the password field; only the username/email key.
    attempted = credentials.get("username") or credentials.get("email") or "-"
    logger.warning(
        "auth.login_failed attempted=%s ip=%s",
        attempted,
        _ip_from_request(request),
    )