# Generated for unique-email enforcement.
#
# If this migration fails with IntegrityError it means existing rows have
# duplicate or empty emails. Resolve those in a data migration first, e.g.:
#
#   for user in User.objects.filter(email="") | User.objects.values("email")
#                .annotate(c=Count("id")).filter(c__gt=1):
#       ...reconcile...
#
# before re-running migrate.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_userprofile_userprofile_public_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(
                help_text=(
                    "Unique per account. Used for recovery flows and "
                    "duplicate-account prevention."
                ),
                max_length=254,
                unique=True,
                verbose_name="email address",
            ),
        ),
    ]
