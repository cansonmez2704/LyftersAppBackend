
import uuid as uuid_lib
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models import Q , F
from django.db.models.signals import post_save, m2m_changed , post_delete
from django.dispatch import receiver
from django.db import transaction
from django.core.validators import MinValueValidator
from decimal import Decimal

class MuscleGroup(models.Model):

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    class Meta:
        ordering = ["name"]
        verbose_name = "Muscle Group"
        verbose_name_plural = "Muscle Groups"
    def __str__(self) -> str:
        return self.name

class Exercise(models.Model):

    class ExerciseType(models.TextChoices):
        CARDIO = "cardio", "Cardio"
        CALISTHENICS = "calisthenics", "Calisthenics"
        WEIGHTLIFTING = "weightlifting", "Weightlifting"
    class MovementType(models.TextChoices):
        COMPOUND = "compound", "Compound"
        ISOMETRIC = "isometric", "Isometric"
        ISOLATION = "isolation", "Isolation"  
    class DifficultyLevel(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True, default="")
    exercise_type = models.CharField(
        max_length=20,
        choices=ExerciseType.choices,
        default=ExerciseType.WEIGHTLIFTING,
       
    )
    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        default=MovementType.COMPOUND,
        db_index=True,
    )
    difficulty = models.CharField(
        max_length=20,
        choices=DifficultyLevel.choices,
        default=DifficultyLevel.BEGINNER,
        db_index=True,
    )
    muscles = models.ManyToManyField(
        MuscleGroup,
        related_name="exercises",
        blank=True,
        help_text="Muscles activated by this exercise.",
    )
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Step-by-step form instructions.",
    )
    video_url = models.URLField(
        blank=True,
        default="",
        help_text="Link to a demo video.",
    )
    equipment_needed = ArrayField(
        models.CharField(max_length=50),
        blank=True,
        default=list,
        help_text="List of required equipment, e.g., ['barbell', 'bench']"
    )
    
    uuid = models.UUIDField(
        default=uuid_lib.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )
    search_vector = SearchVectorField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["name"]
        verbose_name = "Exercise"
        verbose_name_plural = "Exercises"
        indexes = [
            models.Index(fields=["exercise_type", "movement_type"]),
            GinIndex(fields=["search_vector"], name="exercise_search_gin"),
            GinIndex(
                OpClass(models.F("name"), name="gin_trgm_ops"),
                name="exercise_name_trgm",
            ),
        ]
    def __str__(self) -> str:
        return f"{self.name} ({self.get_exercise_type_display()})"

class Workout(models.Model):
   
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        PUBLIC = "public", "Public"
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workouts",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    cover_image = models.ImageField(
        upload_to="workout_covers/",
        blank=True,
        null=True,
    )
    
    exercises = models.ManyToManyField(
        Exercise,
        through="WorkoutExercise",
        related_name="workouts",
        blank=True,
    )
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PRIVATE,
        db_index=True,
    )
    estimated_duration_min = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Estimated duration in minutes.",
    )

    spotify_playlist_url = models.URLField(
        blank=True,
        default="",
        help_text="Optional Spotify playlist link for this workout.",
    )
    
    uuid = models.UUIDField(default=uuid_lib.uuid4, editable=False, unique=True, db_index=True)
    search_vector = SearchVectorField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Workout"
        verbose_name_plural = "Workouts"
        indexes = [
            models.Index(fields=["owner", "visibility"]),
            models.Index(fields=["owner", "-created_at"]),
            GinIndex(fields=["search_vector"], name="workout_search_gin"),
            GinIndex(
                OpClass(models.F("name"), name="gin_trgm_ops"),
                name="workout_name_trgm",
            ),
        ]
    def __str__(self) -> str:
        return f"{self.name} (by {self.owner})"

class WorkoutExercise(models.Model):
    
    workout = models.ForeignKey(
        Workout,
        on_delete=models.CASCADE,
        related_name="workout_exercises",
    )
    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.CASCADE,
        related_name="workout_exercises",
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order (0-indexed).",
    )
    notes = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        help_text="Per-exercise notes for this workout.",
    )
    class Meta:
        ordering = ["order"]
        verbose_name = "Workout Exercise"
        verbose_name_plural = "Workout Exercises"
        constraints = [
            models.UniqueConstraint(
                fields=["workout", "order"],
                name="unique_exercise_order_per_workout",
            ),
        ]
    def __str__(self) -> str:
        return f"{self.workout} → {self.exercise} (#{self.order})"

class WorkoutSet(models.Model):
    
    class WeightUnit(models.TextChoices):
        KILOGRAM = "KG", "Kilogram"
        POUND = "LBS", "Pound"
    workout_exercise = models.ForeignKey(
        WorkoutExercise,
        on_delete=models.CASCADE,
        related_name="sets",
    )
    set_number = models.PositiveSmallIntegerField(
        help_text="1-indexed set number within this exercise.",
    )
    reps = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Reps performed (strength / calisthenics).",
    )
    weight = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))], # ADD THIS
        help_text="Weight lifted in the specified unit.",
    )
    weight_unit = models.CharField(
        max_length=3,
        choices=WeightUnit.choices,
        blank=True,
        default="",
        help_text="Unit of the weight field.",
    )
    duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration in seconds (cardio / isometric).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        ordering = ["set_number"]
        verbose_name = "Workout Set"
        verbose_name_plural = "Workout Sets"
        constraints = [
            models.UniqueConstraint(
                fields=["workout_exercise", "set_number"],
                name="unique_set_number_per_exercise",
            ),
            models.CheckConstraint(
                check=Q(reps__isnull=False) | Q(duration_seconds__isnull=False),
                name="set_must_have_reps_or_duration",
            ),
        ]
    def __str__(self) -> str:
        return f"{self.workout_exercise} — Set {self.set_number}"


# ---------------------------------------------------------------------------
# Search-vector signals (dispatched to Celery)
# ---------------------------------------------------------------------------

@receiver(post_save, sender=Exercise)
def update_exercise_search_vector(sender, instance, **kwargs):
    from workouts.tasks import rebuild_exercise_search_vector
    transaction.on_commit(
        lambda: rebuild_exercise_search_vector.delay(instance.pk)
    )

@receiver(m2m_changed, sender=Exercise.muscles.through)
def update_exercise_search_vector_on_m2m(sender, instance, action, **kwargs):
    """Also rebuild when muscles are added/removed."""
    # ADDED THE ACTION CHECK: Prevents Celery from queueing duplicate tasks.
    if action in ["post_add", "post_remove", "post_clear"]:
        from workouts.tasks import rebuild_exercise_search_vector
        transaction.on_commit(
            lambda: rebuild_exercise_search_vector.delay(instance.pk)
        )

# REMOVED the "from .models import WorkoutExercise" because we are already in models.py!
from workouts.tasks import rebuild_workout_search_vector

# COMBINED decorators to fix your IDE yellow line
@receiver([post_save, post_delete], sender=WorkoutExercise)
def update_workout_search_vector_on_exercise_change(sender, instance, **kwargs):
    """
    If an exercise is added to, updated in, or removed from a workout,
    rebuild the parent workout's search vector to keep the index fresh.
    """
    transaction.on_commit(
        lambda: rebuild_workout_search_vector.delay(instance.workout_id)
    )