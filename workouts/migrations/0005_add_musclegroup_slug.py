"""
The MuscleGroup.slug column is defined in 0001_initial, but the database
table was created before that field was added to the migration file.
Django thinks it's already applied, so makemigrations won't detect the
missing column.  This migration adds the column if it doesn't exist.
"""

from django.db import migrations, models


def forwards_noop(apps, schema_editor):
    """Check if the column already exists; if so, skip."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'workouts_musclegroup' AND column_name = 'slug'"
        )
        if cursor.fetchone():
            return  # column already exists
    # Column is missing — add it
    with connection.cursor() as cursor:
        cursor.execute(
            'ALTER TABLE "workouts_musclegroup" '
            'ADD COLUMN "slug" varchar(100) NOT NULL DEFAULT \'\''
        )
        cursor.execute(
            'UPDATE "workouts_musclegroup" SET "slug" = LOWER(REPLACE("name", \' \', \'-\')) '
            'WHERE "slug" = \'\''
        )
        cursor.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS "workouts_musclegroup_slug_key" '
            'ON "workouts_musclegroup" ("slug")'
        )


class Migration(migrations.Migration):

    dependencies = [
        ("workouts", "0004_remove_workoutexercise_unique_exercise_order_per_workout_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards_noop, migrations.RunPython.noop),
    ]
