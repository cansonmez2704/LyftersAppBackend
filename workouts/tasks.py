import logging
from celery import shared_task
from django.contrib.postgres.search import SearchVector
from django.contrib.postgres.aggregates import StringAgg
from django.db.models import Subquery, OuterRef , CharField , Value
from django.db.models.functions import Coalesce
from django.db.models import CharField

logger = logging.getLogger(__name__)

# FIXED: Moved to a dedicated queue so bulk indexing doesn't block critical tasks (like emails).
@shared_task(bind=True, max_retries=3, default_retry_delay=5, queue="search_indexing")
def rebuild_exercise_search_vector(self, exercise_pk):
    """Rebuild the full-text search vector for an Exercise."""
    try:
        # Kept import inside to strictly avoid AppRegistryNotReady errors during Celery boot.
        from .models import Exercise

        updated = Exercise.objects.filter(pk=exercise_pk).update(
            search_vector=(
                SearchVector("name", weight="A")
                + SearchVector("description", weight="B")
            )
        )
        if not updated:
            return f"Exercise {exercise_pk} not found"
        return f"Search vector rebuilt for exercise {exercise_pk}"

    except Exception as exc:
        logger.error(f"Exercise search vector rebuild failed for {exercise_pk}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=5, queue="search_indexing")
def rebuild_workout_search_vector(self, workout_pk):
    """Rebuild the full-text search vector for a Workout, including its exercises."""
    try:
        from .models import Workout, WorkoutExercise

        # FIXED: Create a subquery that aggregates all exercise names for this workout into a single string.
        # e.g., "Bench Press Squat Deadlift"
        exercise_names_subquery = WorkoutExercise.objects.filter(
            workout=OuterRef("pk")
        ).values("workout").annotate(
            names=StringAgg("exercise__name", delimiter=" ")
        ).values("names")

        # Update the workout, concatenating its own name/description with the aggregated exercise names.
        # Coalesce ensures that if a workout has NO exercises yet, the Subquery returns an empty string instead of NULL.
        updated = Workout.objects.filter(pk=workout_pk).update(
            search_vector=(
                SearchVector("name", weight="A")
                + SearchVector("description", weight="B")
                + SearchVector(
                    Coalesce(Subquery(exercise_names_subquery), Value(''), output_field=CharField()), 
                    weight="C"
                )
            )
        )
        
        if not updated:
            return f"Workout {workout_pk} not found"
        return f"Search vector rebuilt for workout {workout_pk} (including exercises)"

    except Exception as exc:
        logger.error(f"Workout search vector rebuild failed for {workout_pk}: {exc}")
        raise self.retry(exc=exc)