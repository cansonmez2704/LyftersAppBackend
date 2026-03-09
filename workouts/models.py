
from django.conf import settings
from django.db import models
from django.db.models import Q , F
class MuscleGroup(models.Model):

    name = models.CharField(max_length=100, unique=True)
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
    description = models.TextField(blank=True, default="")
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
    equipment_needed = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="e.g. 'Barbell, Bench' or 'Bodyweight'.",
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
    is_template = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Reusable template that others can copy.",
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
                fields=["workout", "exercise", "order"],
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
    class Meta:
        ordering = ["set_number"]
        verbose_name = "Workout Set"
        verbose_name_plural = "Workout Sets"
        constraints = [
            models.UniqueConstraint(
                fields=["workout_exercise", "set_number"],
                name="unique_set_number_per_exercise",
            ),
        ]
    def __str__(self) -> str:
        return f"{self.workout_exercise} — Set {self.set_number}"