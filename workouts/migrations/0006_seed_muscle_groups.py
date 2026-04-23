from django.db import migrations

MUSCLE_GROUPS = [
    ("Chest", "chest", "Pectoralis major and minor"),
    ("Upper Back", "upper-back", "Rhomboids and mid-trapezius"),
    ("Shoulders", "shoulders", "Anterior, lateral, and posterior deltoids"),
    ("Biceps", "biceps", "Biceps brachii"),
    ("Triceps", "triceps", "Triceps brachii"),
    ("Forearms", "forearms", "Wrist flexors, extensors, and brachioradialis"),
    ("Abs", "abs", "Rectus abdominis"),
    ("Obliques", "obliques", "Internal and external obliques"),
    ("Quads", "quads", "Quadriceps femoris group"),
    ("Hamstrings", "hamstrings", "Biceps femoris, semitendinosus, semimembranosus"),
    ("Glutes", "glutes", "Gluteus maximus, medius, and minimus"),
    ("Calves", "calves", "Gastrocnemius and soleus"),
    ("Traps", "traps", "Upper trapezius"),
    ("Lats", "lats", "Latissimus dorsi"),
    ("Neck", "neck", "Sternocleidomastoid and scalenes"),
    ("Hip Flexors", "hip-flexors", "Iliopsoas and rectus femoris"),
    ("Adductors", "adductors", "Adductor magnus, longus, and brevis"),
    ("Lower Back", "lower-back", "Erector spinae and quadratus lumborum"),
]


def seed(apps, schema_editor):
    MuscleGroup = apps.get_model("workouts", "MuscleGroup")
    for name, slug, description in MUSCLE_GROUPS:
        MuscleGroup.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "description": description},
        )


def unseed(apps, schema_editor):
    MuscleGroup = apps.get_model("workouts", "MuscleGroup")
    slugs = [slug for _, slug, _ in MUSCLE_GROUPS]
    MuscleGroup.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workouts", "0005_add_musclegroup_slug"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
