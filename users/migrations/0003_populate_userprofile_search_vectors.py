"""Populate search_vector for all existing UserProfile rows."""
from django.db import migrations


def populate_search_vectors(apps, schema_editor):
    """Use raw SQL because SearchVector with joined fields
    (user__username) cannot be used in .update() — Django raises
    'Joined field references are not permitted in this query'."""
    schema_editor.execute("""
        UPDATE users_userprofile
        SET search_vector =
            setweight(to_tsvector('english', COALESCE(u.username, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(users_userprofile.bio, '')), 'B')
        FROM users_user u
        WHERE users_userprofile.user_id = u.id
    """)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_userprofile_search_vector_and_more"),
    ]

    operations = [
        migrations.RunPython(
            populate_search_vectors,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
