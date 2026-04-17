import uuid
from django.db import migrations, models


def backfill_exercise_uuids(apps, schema_editor):
    Exercise = apps.get_model("workouts", "Exercise")
    for row in Exercise.objects.filter(uuid__isnull=True).only("pk"):
        row.uuid = uuid.uuid4()
        row.save(update_fields=["uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("workouts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="exercise",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.RunPython(backfill_exercise_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="exercise",
            name="uuid",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="workoutset",
            constraint=models.CheckConstraint(
                check=models.Q(reps__isnull=False)
                | models.Q(duration_seconds__isnull=False),
                name="set_must_have_reps_or_duration",
            ),
        ),
    ]
