"""
Celery tasks for the workouts app.
- Exercise search vector rebuild
- Workout search vector rebuild
"""
import logging

from celery import shared_task
from django.contrib.postgres.search import SearchVector

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def rebuild_exercise_search_vector(self, exercise_pk):
    """Rebuild the full-text search vector for an Exercise."""
    try:
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


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def rebuild_workout_search_vector(self, workout_pk):
    """Rebuild the full-text search vector for a Workout."""
    try:
        from .models import Workout

        updated = Workout.objects.filter(pk=workout_pk).update(
            search_vector=(
                SearchVector("name", weight="A")
                + SearchVector("description", weight="B")
            )
        )
        if not updated:
            return f"Workout {workout_pk} not found"
        return f"Search vector rebuilt for workout {workout_pk}"

    except Exception as exc:
        logger.error(f"Workout search vector rebuild failed for {workout_pk}: {exc}")
        raise self.retry(exc=exc)
