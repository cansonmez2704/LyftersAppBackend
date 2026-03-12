from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension, BtreeGinExtension

class Migration(migrations.Migration):

    dependencies = [
        # Removed the nonexistent initial migration!
    ]

    operations = [
        TrigramExtension(),  # Turns on Typo-Tolerance (pg_trgm)
        BtreeGinExtension(), # Supercharges our search indexes
    ]