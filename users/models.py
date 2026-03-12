

import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q , F
from django.db.models.signals import post_save
from django.dispatch import receiver


class CustomUserManager(UserManager):
    
    def create_user(self, username, email=None, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required for user registration.")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(username, email, password, **extra_fields)

class User(AbstractUser):
    
    objects = CustomUserManager()
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text="Public-facing identifier. Never expose the integer PK.",
    )
    class Meta(AbstractUser.Meta):
        pass
    def __str__(self) -> str:
        return self.username

def avatar_upload_path(instance, filename: str) -> str:
   
        ext = filename.rsplit(".", 1)[-1].lower()
        return f"avatars/user_{instance.user_id}/avatar.{ext}"

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
    )
    is_public = models.BooleanField(default=True)
    followers_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)
    bio = models.CharField(max_length=2000, blank=True, default="")
    height = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(50), MaxValueValidator(300)],
        help_text="Height in centimetres.",
    )
    weight = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(20), MaxValueValidator(500)],
        help_text="Weight in kilograms.",
    )
    gender = models.CharField(
        max_length=1,
        choices=GenderChoices.choices,
        blank=True,
        default="",
    )
    birth_date = models.DateField(null=True, blank=True)
    search_vector = SearchVectorField(null=True)
    # --- Timestamps (match the rest of the project) ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
   
    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        indexes = [
            GinIndex(fields=["search_vector"], name="userprofile_search_gin"),
        ]
   
    def __str__(self) -> str:
        return f"Profile of {self.user}"
   
    @property
    def avatar_url(self) -> str:
       
        if self.avatar and hasattr(self.avatar, "url"):
            return self.avatar.url
        return "/static/images/default-avatar.png"
   
    # NOTE: Avatar resizing should be handled asynchronously.
    # In production, enqueue a Celery task in the serializer's save
    # to resize after upload, rather than blocking the request here.

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: UserProfile.objects.get_or_create(user=instance)
        )
    else:
        # When username changes, update the profile search vector
        transaction.on_commit(
            lambda: _update_profile_search_vector(instance.pk)
        )


def _update_profile_search_vector(user_pk):
    """Rebuild the search vector for a user's profile.
    
    Uses raw SQL because SearchVector with joined fields (user__username)
    cannot be used in .update() — Django raises FieldError.
    """
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


@receiver(post_save, sender=UserProfile)
def update_profile_search_vector(sender, instance, **kwargs):
    """Update search vector whenever the profile itself is saved."""
    transaction.on_commit(
        lambda: _update_profile_search_vector(instance.user_id)
    )

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
            models.UniqueConstraint(
                fields=["from_user", "to_user"], 
                name="unique_user_follow"
            ),
            models.CheckConstraint(
                check=~Q(from_user=F("to_user")),
                name="prevent_self_follow",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_user} follows {self.to_user} ({self.get_status_display()})"
        
  