import uuid
from django.db import migrations, models


def backfill_comment_uuids(apps, schema_editor):
    Comment = apps.get_model("community", "Comment")
    for comment in Comment.objects.filter(uuid__isnull=True).only("pk"):
        comment.uuid = uuid.uuid4()
        comment.save(update_fields=["uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("community", "0002_alter_postmedia_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.RunPython(backfill_comment_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="comment",
            name="uuid",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
            ),
        ),
    ]
