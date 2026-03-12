"""Populate search_vector for all existing Exercise and Workout rows."""
from django.contrib.postgres.search import SearchVector
from django.db import migrations


def populate_exercise_vectors(apps, schema_editor):
    Exercise = apps.get_model("workouts", "Exercise")
    Exercise.objects.update(
        search_vector=(
            SearchVector("name", weight="A")
            + SearchVector("description", weight="B")
        )
    )


def populate_workout_vectors(apps, schema_editor):
    Workout = apps.get_model("workouts", "Workout")
    Workout.objects.update(
        search_vector=(
            SearchVector("name", weight="A")
            + SearchVector("description", weight="B")
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        ("workouts", "0002_exercise_search_vector_workout_search_vector_and_more"),
    ]

    operations = [
        migrations.RunPython(
            populate_exercise_vectors,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            populate_workout_vectors,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
