from django.db import models
from django.conf import settings




class MuscleGroup(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Muscle Group"
        verbose_name_plural = "Muscle Groups"

    def __str__(self) -> str:
        return self.name


class Exercise(models.Model):
    
    class ExerciseType(models.TextChoices):
        CARDIO        = "cardio",        "Cardio"
        CALISTHENICS  = "calisthenics",  "Calisthenics"
        WEIGHTLIFTING = "weightlifting", "Weightlifting"

    class MovementType(models.TextChoices):
        COMPOUND  = "compound",  "Compound"
        ISOMETRIC = "isometric", "Isometric"

    class DifficultyLevel(models.TextChoices):
        BEGINNER     = "beginner",     "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED     = "advanced",     "Advanced"

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    exercise_type = models.CharField(
        max_length=20,
        choices=ExerciseType.choices,
        default=ExerciseType.WEIGHTLIFTING,
        db_index=True,
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
    )

    muscles = models.ManyToManyField(
        MuscleGroup,
        related_name="exercises",
        blank=True,
        help_text="Primary and secondary muscles activated by this exercise.",
    )

    instructions = models.TextField(
        blank=True,
        help_text="Step-by-step instructions for performing the exercise safely.",
    )
    video_url = models.URLField(
        blank=True,
        help_text="Optional link to a demo video (YouTube, etc.).",
    )
    equipment_needed = models.CharField(
        max_length=200,
        blank=True,
        help_text="Equipment required, e.g. 'Barbell, Bench' or 'None'.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Exercise"
        verbose_name_plural = "Exercises"
        indexes = [
            models.Index(fields=["exercise_type", "movement_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_exercise_type_display()})"


class WorkoutExercise(models.Model):
    
    workout  = models.ForeignKey("Workout",  on_delete=models.CASCADE, related_name="workout_exercises")
    exercise = models.ForeignKey(Exercise,   on_delete=models.CASCADE, related_name="workout_exercises")

    order        = models.PositiveSmallIntegerField(default=1, help_text="Order of this exercise in the workout.")
    sets         = models.PositiveSmallIntegerField(null=True, blank=True)
    reps         = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Reps per set (for strength / calisthenics).")
    weight_kg    = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Load in kilograms.")
    duration_sec = models.PositiveIntegerField(null=True, blank=True, help_text="Duration in seconds (for cardio / isometric holds).")
    rest_sec     = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Rest between sets in seconds.")
    notes        = models.TextField(blank=True)

    class Meta:
        ordering = ["order"]
        verbose_name = "Workout Exercise"
        verbose_name_plural = "Workout Exercises"
        constraints = [
            models.UniqueConstraint(
                fields=["workout", "exercise", "order"],
                name="unique_exercise_order_per_workout",
            )
        ]

    def __str__(self) -> str:
        return f"{self.workout} → {self.exercise} (#{self.order})"


class Workout(models.Model):

    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        PUBLIC  = "public",  "Public"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workouts",
        help_text="The user who created this workout.",
    )

    name        = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(
        upload_to="workout_covers/",
        blank=True,
        null=True,
        help_text="Optional thumbnail / cover image for this workout.",
    )

    exercises = models.ManyToManyField(
        Exercise,
        through=WorkoutExercise,
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
        help_text="Estimated total workout duration in minutes.",
    )
    is_template = models.BooleanField(
        default=False,
        help_text="Mark as a reusable template that others can copy.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Workout"
        verbose_name_plural = "Workouts"
        indexes = [
            models.Index(fields=["owner", "visibility"]),
            models.Index(fields=["owner", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} (by {self.owner})"

    @property
    def exercise_count(self) -> int:
        return self.workout_exercises.count()
