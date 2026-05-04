from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workouts", "0008_workout_spotify_playlist_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="exercise",
            name="cardio_intensity",
            field=models.CharField(
                blank=True,
                choices=[
                    ("liss", "LISS"),
                    ("miss", "MISS"),
                    ("hiit", "HIIT"),
                    ("sit", "SIT"),
                ],
                default="",
                help_text=(
                    "Intensity bucket for cardio exercises "
                    "(LISS / MISS / HIIT / SIT). Leave blank for non-cardio."
                ),
                max_length=10,
            ),
        ),
    ]
