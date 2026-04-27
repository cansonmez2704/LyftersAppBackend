from django.db import migrations, models


def backfill_onboarding_completed(apps, schema_editor):
    """Existing profiles with any filled onboarding field are treated as
    already onboarded so returning users do not see the wizard again."""
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.filter(
        models.Q(birth_date__isnull=False)
        | models.Q(height__isnull=False)
        | models.Q(weight__isnull=False)
        | ~models.Q(bio="")
        | ~models.Q(avatar="")
    ).update(onboarding_completed=True)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_alter_userprofile_avatar_alter_userprofile_height_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="onboarding_completed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            backfill_onboarding_completed,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
